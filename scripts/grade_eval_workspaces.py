#!/usr/bin/env python3
"""Run terraform init, validate and fmt on copies of the workspaces a `claude plugin eval` run kept.

`claude plugin eval --keep-temp` leaves each attempt's working directory on disk.
This script never runs anything inside those directories. It copies the Terraform
files into a fresh directory and runs terraform there with a scrubbed environment:
no API key, no cloud credential and a CLI configuration that installs only providers
published by HashiCorp, Azure and Oracle on the public registry. It writes one record
per attempt for classify_eval_run.py.

Terraform loads provider plugins, and a plugin is a program that runs as the user who
started this script. The scrubbed environment stops terraform from being handed a
secret, but it cannot stop a plugin from reading this process's own environment, so
the script refuses to start while one of the model credentials in SECRET_VARIABLES is
set. That list is the credentials this repository's own tooling uses, not every secret
there could be: run the script from a shell or a job step that holds no credentials.

Status values:
  ok                 init and validate passed (`fmt` says clean, diff or error)
  validate_failed    init or validate rejected the configuration, the workspace is larger
                     than the limits below, or a command printed more than MAX_SINK_BYTES
  infra              init could not reach the registry, a command timed out, a path in
                     the workspace could not be read or the grading deadline passed; says
                     nothing about the configuration. A timed-out `terraform fmt` is the
                     exception: it leaves `ok` with `fmt` set to error, because fmt only warns
  no_workspace       the kept workspace could not be found, or is reached through a symlink
  no_terraform_files the workspace holds no Terraform files
  unavailable        the terraform binary could not be run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MAX_FILES = 200
MAX_TOTAL_BYTES = 1024 * 1024
MAX_DEPTH = 6
# Entries listed in one workspace. reopen() and collect_files() share it, so neither looks at a tree the other skipped.
MAX_ENTRIES = 20000
DEFAULT_TIMEOUT = 300
DEFAULT_DEADLINE = 1200
DETAIL_CHARS = 600
# Output read back from one command, which keeps the report and the memory small.
MAX_OUTPUT_BYTES = 64 * 1024
# Output a command may write before it is stopped. The output goes to a file, so this keeps a plugin that prints
# without end from filling the disk. It is checked a few times a second, so the file can pass it by a little.
MAX_SINK_BYTES = 4 * 1024 * 1024
POLL_SECONDS = 0.25
SKIPPED_DIRS = frozenset({".terraform", ".git"})
# The model credentials this repository's own tooling puts in an environment. The script will not run beside them.
SECRET_VARIABLES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
# The only variables passed to terraform. Everything else, including ANTHROPIC_API_KEY and any
# cloud credential, is dropped.
PASSED_ENV = (
    "PATH",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "TF_PLUGIN_CACHE_DIR",
)
# A configuration can name any provider source, and terraform runs the provider it installs. This installs only the
# namespaces the skill's cloud references name, on the public registry, so a provider from another host or another
# publisher fails at init instead of being downloaded and run. A namespace is still somebody's to publish under:
# these three belong to HashiCorp, Microsoft's Azure organisation and Oracle.
PROVIDER_NAMESPACES = ("hashicorp", "azure", "oracle")
CLI_CONFIG = (
    "provider_installation {\n"
    "  direct {\n"
    "    include = [" + ", ".join(f'"registry.terraform.io/{namespace}/*"' for namespace in PROVIDER_NAMESPACES) + "]\n"
    "  }\n"
    "}\n"
)
INFRA_RE = re.compile(
    r"dial tcp|no such host|connection (?:refused|reset|timed out)|tls handshake|i/o timeout|context deadline exceeded"
    r"|temporary failure in name resolution|status (?:429|5\d\d)|could not connect|network is unreachable|request failed after",
    re.IGNORECASE,
)
TIMED_OUT = 124
OUTPUT_LIMIT = 125
NOT_FOUND = 127


def workspace_for(trace_path: str) -> Path:
    """The kept working directory sits beside the trace: <run>/out/trace.jsonl -> <run>/home/cwd."""
    return Path(trace_path).parent.parent / "home" / "cwd"


def grant(path: Path, bits: int) -> bool:
    """Add owner permission bits to a path that is not a symlink. False for a symlink or when the chmod is refused."""
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            return False
        os.chmod(path, (mode & 0o7777) | bits)
    except OSError:
        return False
    return True


def reopen_parents(workspace: Path) -> None:
    """Open the two directories above the workspace, outermost first.

    Looking at the workspace at all, even to ask whether it is a symlink, needs search permission on
    the directory above it. A user who is not root gets "permission denied" from a closed one.
    """
    for directory in (workspace.parent.parent, workspace.parent):
        grant(directory, 0o700)


def reopen(workspace: Path) -> None:
    """Reopen the modes the eval runner may have closed on what the agent wrote.

    The runner closes the modes of what the agent wrote, and `chmod -R u+rwX` opens them again. Only
    the two directories above the workspace and the workspace tree are touched, symlinks are never
    followed, and a directory is opened before it is listed because a closed one cannot be.
    """
    reopen_parents(workspace)
    pending = [(workspace, 0)]
    seen = 0
    # One more directory than the cap allows is listed, so a tree over MAX_ENTRIES is seen to be over it.
    while pending and seen <= MAX_ENTRIES:
        directory, depth = pending.pop()
        if not grant(directory, 0o700):
            continue
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            seen += 1
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                if entry.name not in SKIPPED_DIRS and depth < MAX_DEPTH:
                    pending.append((Path(entry.path), depth + 1))
            elif entry.is_file(follow_symlinks=False):
                # A file with another link could be the same file as one outside the workspace.
                try:
                    shared = entry.stat(follow_symlinks=False).st_nlink != 1
                except OSError:
                    continue
                if not shared:
                    grant(Path(entry.path), 0o600)


@dataclass
class Collected:
    files: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    problem: str | None = None  # the workspace is over a limit, which the agent caused
    unreadable: str | None = None  # a path could not be read, which says nothing about what the agent wrote


def collect_files(workspace: Path) -> Collected:
    """Terraform files under the workspace as relative paths, within fixed limits.

    A file is taken only when it is a regular file with one link. A symlink, or a hard link that
    could be the same file as one outside the workspace, is skipped and listed in `skipped`.
    """
    collected = Collected()
    total = 0
    walked = 0
    unreadable: list[str] = []
    for current, dirs, files in os.walk(workspace, followlinks=False, onerror=lambda error: unreadable.append(str(error.filename))):
        walked += len(dirs) + len(files)
        if walked > MAX_ENTRIES:
            collected.problem = f"more than {MAX_ENTRIES} entries"
            break
        relative_dir = Path(current).relative_to(workspace)
        real_dirs = sorted(d for d in dirs if d not in SKIPPED_DIRS and not os.path.islink(os.path.join(current, d)))
        if len(relative_dir.parts) >= MAX_DEPTH:
            if real_dirs:
                collected.problem = f"directories nested more than {MAX_DEPTH} levels deep"
                break
            real_dirs = []
        dirs[:] = real_dirs
        for name in sorted(files):
            if not (name.endswith(".tf") or name.endswith(".tf.json")):
                continue
            path = Path(current) / name
            try:
                info = path.lstat()
            except OSError:
                unreadable.append(str(path))
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                collected.skipped.append((relative_dir / name).as_posix())
                continue
            total += info.st_size
            collected.files.append(relative_dir / name)
            if len(collected.files) > MAX_FILES or total > MAX_TOTAL_BYTES:
                collected.problem = f"more than {MAX_FILES} Terraform files or {MAX_TOTAL_BYTES} bytes"
                break
        if collected.problem:
            break
    if not collected.problem and unreadable:
        collected.unreadable = f"{len(unreadable)} path(s) could not be read, such as {unreadable[0]}"
    collected.files = sorted(collected.files[:MAX_FILES], key=Path.as_posix)
    collected.skipped.sort()
    return collected


def terraform_env(home: Path) -> dict[str, str]:
    env = {name: os.environ[name] for name in PASSED_ENV if name in os.environ}
    rc_file = home / "terraformrc"
    rc_file.write_text(CLI_CONFIG, encoding="utf-8")
    env.update(
        HOME=str(home),
        TF_IN_AUTOMATION="1",
        TF_INPUT="0",
        CHECKPOINT_DISABLE="1",
        TF_CLI_CONFIG_FILE=str(rc_file),
    )
    return env


def stop_group(pid: int) -> None:
    """Kill every process left in the group a command started. terraform's own plugins are among them.

    A process that starts a session of its own, as a daemon does, leaves the group and is not killed.
    """
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_terraform(binary: str, args: list[str], cwd: Path, env: dict[str, str], timeout: float) -> tuple[int, str]:
    """Run one command in its own process group and return its exit code and output.

    Output goes to a file rather than a pipe, so a child that outlives terraform and keeps the pipe
    open cannot hold this function up. When the command ends, on timeout, or once it has written more
    than MAX_SINK_BYTES, the whole group is killed. The last case returns OUTPUT_LIMIT with the start of the output.
    """
    with tempfile.TemporaryFile() as sink:
        try:
            process = subprocess.Popen(
                [binary, *args], cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=sink, stderr=subprocess.STDOUT, start_new_session=True
            )
        except OSError as exc:
            return NOT_FOUND, str(exc)
        try:
            code = wait_for(process, sink, timeout)
        finally:
            stop_group(process.pid)
            process.wait()
        if code == TIMED_OUT:
            return code, f"timed out after {timeout:g}s"
        sink.seek(0)
        return code, sink.read(MAX_OUTPUT_BYTES).decode("utf-8", errors="replace").strip()


def wait_for(process: subprocess.Popen[bytes], sink: Any, timeout: float) -> int:
    """The exit code of the process, TIMED_OUT after `timeout` seconds, or OUTPUT_LIMIT when the sink outgrows MAX_SINK_BYTES."""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return TIMED_OUT
        try:
            return process.wait(timeout=min(POLL_SECONDS, remaining))
        except subprocess.TimeoutExpired:
            if os.fstat(sink.fileno()).st_size > MAX_SINK_BYTES:
                return OUTPUT_LIMIT


def terraform_version(binary: str) -> str | None:
    env = {"PATH": os.environ.get("PATH", ""), "CHECKPOINT_DISABLE": "1"}
    code, output = run_terraform(binary, ["version", "-json"], Path.cwd(), env, 60)
    if code != 0:
        return None
    try:
        return json.loads(output).get("terraform_version")
    except ValueError:
        return output.splitlines()[0] if output else None


def detail_of(step: str, output: str) -> str:
    """The step and what its output says, from the first `Error:` when there is one, because init prints progress lines first."""
    text = " ".join(output.split())
    start = text.find("Error:")
    if start > 0:
        text = text[start:]
    return f"{step}: {text[:DETAIL_CHARS]}"


def grade_workspace(binary: str, workspace: Path, timeout: float, deadline_at: float | None = None) -> dict[str, Any]:
    reopen_parents(workspace)
    try:
        linked = workspace.is_symlink() or workspace.parent.is_symlink()
        if linked:
            return {"status": "no_workspace", "detail": "the kept workspace is reached through a symlink, so it was not read"}
        reopen(workspace)
        present = workspace.is_dir()
    except OSError as exc:
        return {"status": "no_workspace", "detail": f"the kept workspace cannot be reached ({exc.strerror or exc})"}
    if not present:
        return {"status": "no_workspace", "detail": "the kept workspace was not found; run the eval with --keep-temp"}
    collected = collect_files(workspace)
    if collected.unreadable:
        return {"status": "infra", "detail": f"workspace: {collected.unreadable}"}
    if not collected.files and not collected.problem:
        return {"status": "no_terraform_files", "detail": "no .tf files in the workspace"}
    record: dict[str, Any] = {"files": [path.as_posix() for path in collected.files]}
    if collected.skipped:
        record["skipped"] = collected.skipped
    if collected.problem:
        record.update(status="validate_failed", detail=f"workspace: {collected.problem}")
        return record

    def run(args: list[str], cwd: Path, env: dict[str, str]) -> tuple[int, str]:
        allowed = timeout if deadline_at is None else max(1.0, min(timeout, deadline_at - time.monotonic()))
        return run_terraform(binary, args, cwd, env, allowed)

    with tempfile.TemporaryDirectory(prefix="eval-grade-") as scratch:
        root = Path(scratch)
        copy = root / "config"
        home = root / "home"
        home.mkdir()
        try:
            for relative in collected.files:
                target = copy / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(workspace / relative, target)
        except OSError as exc:
            # A file that cannot be read says nothing about the configuration.
            record.update(status="infra", detail=f"copy: {exc.strerror or exc} ({exc.filename})")
            return record
        env = terraform_env(home)

        code, output = run(["init", "-backend=false", "-input=false", "-no-color"], copy, env)
        if code == NOT_FOUND:
            record.update(status="unavailable", detail=detail_of("init", output))
            return record
        if code != 0:
            infra = code == TIMED_OUT or bool(INFRA_RE.search(output))
            record.update(status="infra" if infra else "validate_failed", detail=detail_of("init", output))
            return record

        code, output = run(["validate", "-no-color"], copy, env)
        if code != 0:
            record.update(status="infra" if code == TIMED_OUT else "validate_failed", detail=detail_of("validate", output))
            return record

        code, output = run(["fmt", "-check", "-recursive", "-no-color"], copy, env)
        fmt = "clean" if code == 0 else "diff" if code == 3 else "error"
        record.update(status="ok", fmt=fmt)
        if fmt != "clean":
            record["detail"] = detail_of("fmt", output)
        return record


def wants_static_grading(case: dict[str, Any]) -> bool:
    """Cases that must write Terraform: they have a file_exists grader for a .tf file."""
    graders = case.get("graders")
    if not isinstance(graders, list):
        return False
    for grader in graders:
        config = grader.get("config") if isinstance(grader, dict) else None
        if isinstance(grader, dict) and grader.get("type") == "file_exists" and isinstance(config, dict):
            if str(config.get("path", "")).endswith(".tf"):
                return True
    return False


def attempts_of(case: dict[str, Any]) -> list[Any]:
    """The runs of the case in the arm with the skill, which are the attempts."""
    arms = case.get("arms")
    runs = arms.get("with") if isinstance(arms, dict) else None
    return runs if isinstance(runs, list) else []


def grade_aggregate(aggregate: dict[str, Any], binary: str, timeout: float, deadline: float | None = None) -> dict[str, Any]:
    """Grade every attempt of every case that writes Terraform. `deadline` bounds the whole run, in seconds."""
    version = terraform_version(binary) if shutil.which(binary) or Path(binary).is_file() else None
    deadline_at = None if deadline is None else time.monotonic() + deadline
    attempts: list[dict[str, Any]] = []
    for case in aggregate.get("cases", []):
        if not isinstance(case, dict) or not isinstance(case.get("name"), str) or not wants_static_grading(case):
            continue
        for index, run in enumerate(attempts_of(case)):
            trace = run.get("tracePath") if isinstance(run, dict) else None
            if version is None:
                result = {"status": "unavailable", "detail": f"{binary} could not be run"}
            elif not trace:
                result = {"status": "no_workspace", "detail": "the run recorded no trace path"}
            elif deadline_at is not None and time.monotonic() >= deadline_at:
                result = {"status": "infra", "detail": f"the {deadline:g}s grading deadline passed before this attempt was graded"}
            else:
                try:
                    result = grade_workspace(binary, workspace_for(trace), timeout, deadline_at)
                except Exception as exc:  # noqa: BLE001 - one attempt's crash must not hide the other attempts' grades
                    result = {"status": "infra", "detail": f"grading this attempt failed: {type(exc).__name__}: {exc}"}
            attempts.append({"case": case["name"], "attempt": index, **result})
    return {"schema_version": SCHEMA_VERSION, "terraform": {"binary": binary, "version": version}, "attempts": attempts}


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run terraform validate on the workspaces kept by claude plugin eval.")
    parser.add_argument("--aggregate", type=Path, required=True, help="aggregate-result.json from the eval run")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--terraform", default="terraform", help="the terraform binary to run")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="seconds allowed for each terraform command")
    parser.add_argument("--deadline", type=int, default=DEFAULT_DEADLINE, help="seconds allowed for all attempts together")
    args = parser.parse_args(argv)

    held = [name for name in SECRET_VARIABLES if (os.environ if env is None else env).get(name)]
    if held:
        unset = " ".join(f"-u {name}" for name in held)
        print(
            f"{', '.join(held)} {'is' if len(held) == 1 else 'are'} set in this environment. terraform runs files the model wrote, "
            f"and the programs it starts can read this process's environment. Unset {'it' if len(held) == 1 else 'them'} for this command, "
            f"for example: env {unset} python scripts/grade_eval_workspaces.py --aggregate ... --out ..."
        )
        return 2

    try:
        aggregate = json.loads(args.aggregate.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"{args.aggregate}: cannot read the eval result ({exc})")
        return 1
    if not isinstance(aggregate, dict) or not isinstance(aggregate.get("cases", []), list):
        print(f"{args.aggregate}: the eval result is not in the shape this script reads (an object with a `cases` list)")
        return 1

    graded = grade_aggregate(aggregate, args.terraform, args.timeout, args.deadline)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(graded, indent=2) + "\n", encoding="utf-8")

    version = graded["terraform"]["version"] or "not available"
    print(f"Terraform {version}: graded {len(graded['attempts'])} attempt(s).")
    for entry in graded["attempts"]:
        suffix = f", fmt {entry['fmt']}" if entry.get("fmt") else ""
        print(f"  {entry['case']}[{entry['attempt']}]: {entry['status']}{suffix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
