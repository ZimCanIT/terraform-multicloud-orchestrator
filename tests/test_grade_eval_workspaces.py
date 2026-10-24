"""Behavioural tests for scripts/grade_eval_workspaces.py.

Most cases use a stand-in `terraform` that reads marker words in the copied files, so they
run anywhere. The cases at the end run the real binary and are skipped when it is not
installed; the CI job that installs Terraform runs them. The scripts come from this
repository's scripts/ directory unless VALIDATOR_SCRIPTS_DIR names another directory.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(os.environ.get("VALIDATOR_SCRIPTS_DIR") or REPO_ROOT / "scripts")
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "eval-workspaces"
sys.path.insert(0, str(SCRIPTS_DIR))

import grade_eval_workspaces as grader  # noqa: E402

# The stand-in reads marker words in the copied files to decide what to do.
FAKE_TERRAFORM = """\
import os, pathlib, re, subprocess, sys, time

args = sys.argv[1:]
text = "".join(path.read_text() for path in sorted(pathlib.Path.cwd().rglob("*.tf")))
if args[:1] == ["version"]:
    print('{"terraform_version": "1.16.6"}')
    sys.exit(0)
leaked = [name for name in ("ANTHROPIC_API_KEY", "AWS_ACCESS_KEY_ID", "GITHUB_TOKEN") if name in os.environ]
if leaked:
    print("LEAK " + ",".join(leaked), file=sys.stderr)
    sys.exit(9)
if os.environ.get("TF_CLI_CONFIG_FILE") in (None, "") or os.environ.get("HOME", "").startswith("/root"):
    print("unscrubbed environment", file=sys.stderr)
    sys.exit(9)
flood = re.search(r"FLOOD:(\\w+)", text)
if flood and flood.group(1) == args[0]:
    # Prints without end, as a plugin that never stops would. The loop ends by itself, so a missing limit cannot hang the test.
    print("Error: flood", flush=True)
    for _ in range(300):
        os.write(1, b"x" * 65536)
        time.sleep(0.005)
    sys.exit(0)
if args[0] == "init":
    failure = re.search(r"INIT_ERROR:(.+)", text)
    if failure:
        print("Error: " + failure.group(1), file=sys.stderr)
        sys.exit(1)
    if "NETWORK_DOWN" in text:
        print("Error: Failed to query available provider packages: dial tcp: lookup registry.terraform.io: no such host", file=sys.stderr)
        sys.exit(1)
    if "NO_SUCH_VERSION" in text:
        print("Error: Failed to query available provider packages: no available releases match the given constraints ~> 99.0", file=sys.stderr)
        sys.exit(1)
    if "CONFIGDUMP" in text:
        print("CONFIG " + pathlib.Path(os.environ["TF_CLI_CONFIG_FILE"]).read_text().replace("\\n", " "))
    if "HANG_INIT" in text:
        time.sleep(30)
    if "SLOW_INIT" in text:
        time.sleep(1.5)
    late = re.search(r"LEAVE_CHILD:(\\S+)", text)
    if late:
        code = (
            "import pathlib, sys, time; target = pathlib.Path(sys.argv[1]); "
            "pathlib.Path(str(target) + '.started').write_text('x'); time.sleep(1.0); target.write_text('late')"
        )
        subprocess.Popen([sys.executable, "-c", code, late.group(1)], stdin=subprocess.DEVNULL)
        for _ in range(200):
            if pathlib.Path(late.group(1) + ".started").exists():
                break
            time.sleep(0.02)
    sys.exit(0)
if args[0] == "validate":
    if "HANG_VALIDATE" in text:
        time.sleep(30)
    if "HOLD_OUTPUT" in text:
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
        sys.exit(0)
    if "ENVDUMP" in text:
        print("ENV " + ",".join(sorted(os.environ)))
    if "BAD_BYTES" in text:
        sys.stderr.buffer.write(b"Error: caf\\xe9.tf\\n")
        sys.exit(1)
    if "INVALID" in text:
        print("Error: Unsupported argument", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)
if args[0] == "fmt":
    if "HANG_FMT" in text:
        time.sleep(30)
    if "UNFORMATTED" in text:
        print("main.tf")
        sys.exit(3)
    sys.exit(0)
sys.exit(2)
"""


@pytest.fixture(autouse=True)
def no_model_credentials(monkeypatch):
    """The script will not run beside a model credential, so one in the developer's shell must not reach these tests."""
    for name in grader.SECRET_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def fake_terraform(tmp_path: Path) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "terraform.py"
    script.write_text(FAKE_TERRAFORM, encoding="utf-8")
    wrapper = bin_dir / "terraform"
    wrapper.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(script))} \"$@\"\n", encoding="utf-8")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    return str(wrapper)


def make_workspace(root: Path, name: str, files: dict[str, str]) -> str:
    """Create <root>/<name>/{out,home/cwd} the way the eval runner keeps it; return the trace path."""
    run = root / name
    workspace = run / "home" / "cwd"
    workspace.mkdir(parents=True)
    (run / "out").mkdir()
    for relative, text in files.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return str(run / "out" / "trace.jsonl")


def aggregate(*attempts: tuple[str, str]) -> dict:
    """One authoring case with an attempt per (name, trace path), plus a case that writes no files."""
    return {
        "cases": [
            {
                "name": "author-sample",
                "graders": [{"name": "versions-file", "type": "file_exists", "config": {"path": "versions.tf", "exists": True}}],
                "arms": {"with": [{"tracePath": trace} for _, trace in attempts]},
            },
            {
                "name": "refuse-apply",
                "graders": [{"name": "skill-fired", "type": "tool_used", "config": {"tool": "Skill", "min": 1}}],
                "arms": {"with": [{"tracePath": "/nonexistent/out/trace.jsonl"}]},
            },
        ]
    }


def grade(tmp_path: Path, terraform: str, *attempts: tuple[str, str]) -> dict:
    return grader.grade_aggregate(aggregate(*attempts), terraform, 60)


def only(result: dict) -> dict:
    assert len(result["attempts"]) == 1, result
    return result["attempts"][0]


GOOD = {"versions.tf": 'terraform {\n  required_version = ">= 1.5"\n}\n', "main.tf": 'resource "terraform_data" "a" {}\n'}


# --- selection --------------------------------------------------------------


def test_only_cases_that_must_write_terraform_are_graded(tmp_path, fake_terraform):
    trace = make_workspace(tmp_path, "a", GOOD)
    result = grade(tmp_path, fake_terraform, ("a", trace))
    assert [(entry["case"], entry["attempt"]) for entry in result["attempts"]] == [("author-sample", 0)]


def test_grader_and_classifier_agree_on_which_cases_write_terraform():
    """grade_eval_workspaces.py reads the eval result; classify_eval_run.py reads the case files. Both must pick the same cases."""
    import eval_suite

    cases = eval_suite.load_suite(REPO_ROOT / "plugins" / "terraform-multicloud-orchestrator" / "evals")
    assert cases, "the repository has no eval cases"
    for case in cases:
        shaped = {"graders": [{"type": g.type, "config": {key: value for key, value in g.meta.items() if key != "type"}} for g in case.graders]}
        assert grader.wants_static_grading(shaped) == case.writes_terraform, case.name
    assert {case.name for case in cases if case.writes_terraform} == {case.name for case in cases if case.suite == "authoring"}


def test_attempts_are_numbered_in_order(tmp_path, fake_terraform):
    first = make_workspace(tmp_path, "a", GOOD)
    second = make_workspace(tmp_path, "b", {**GOOD, "main.tf": "INVALID\n"})
    result = grade(tmp_path, fake_terraform, ("a", first), ("b", second))
    assert [(entry["attempt"], entry["status"]) for entry in result["attempts"]] == [(0, "ok"), (1, "validate_failed")]


def test_workspace_is_found_beside_the_trace():
    assert grader.workspace_for("/tmp/claude-eval-x/out/trace.jsonl") == Path("/tmp/claude-eval-x/home/cwd")


# --- statuses ---------------------------------------------------------------


def test_clean_configuration_is_ok(tmp_path, fake_terraform):
    result = only(grade(tmp_path, fake_terraform, ("a", make_workspace(tmp_path, "a", GOOD))))
    assert (result["status"], result["fmt"]) == ("ok", "clean")
    assert result["files"] == ["main.tf", "versions.tf"]


def test_unformatted_configuration_is_ok_with_a_fmt_diff(tmp_path, fake_terraform):
    files = {**GOOD, "main.tf": "UNFORMATTED\n"}
    result = only(grade(tmp_path, fake_terraform, ("a", make_workspace(tmp_path, "a", files))))
    assert (result["status"], result["fmt"]) == ("ok", "diff")


def test_validate_error_is_validate_failed(tmp_path, fake_terraform):
    result = only(grade(tmp_path, fake_terraform, ("a", make_workspace(tmp_path, "a", {**GOOD, "main.tf": "INVALID\n"}))))
    assert result["status"] == "validate_failed"
    assert result["detail"] == "validate: Error: Unsupported argument"


def test_unreachable_registry_is_infra(tmp_path, fake_terraform):
    result = only(grade(tmp_path, fake_terraform, ("a", make_workspace(tmp_path, "a", {**GOOD, "main.tf": "NETWORK_DOWN\n"}))))
    assert result["status"] == "infra"
    assert "no such host" in result["detail"]


def test_provider_version_that_does_not_exist_is_not_infra(tmp_path, fake_terraform):
    result = only(grade(tmp_path, fake_terraform, ("a", make_workspace(tmp_path, "a", {**GOOD, "main.tf": "NO_SUCH_VERSION\n"}))))
    assert result["status"] == "validate_failed"
    assert result["detail"].startswith("init: ")


# What init prints when it could not reach the registry, one line for each way the pattern recognises.
NETWORK_ERRORS = (
    "Get https://registry.terraform.io/.well-known/terraform.json: dial tcp 192.0.2.1:443: connect failed",
    "lookup registry.terraform.io on 192.0.2.53:53: no such host",
    "read tcp 192.0.2.1:50000->192.0.2.2:443: connection reset by peer",
    "connect: connection refused",
    "connection timed out after 30s",
    "net/http: TLS handshake timeout",
    "read: i/o timeout",
    "Client.Timeout exceeded: context deadline exceeded",
    "Temporary failure in name resolution",
    "the registry answered with status 429",
    "the registry answered with status 503",
    "could not connect to registry.terraform.io",
    "connect: network is unreachable",
    "the request failed after 2 attempts, please try again later",
)
# What init prints when the configuration is at fault, which must not be taken for a broken network.
CONFIGURATION_ERRORS = (
    "Unsupported argument",
    "no available releases match the given constraints ~> 99.0",
    "provider registry.terraform.io/acme/thing was not found in any of the search locations",
    "Invalid provider source address",
    "the registry answered with status 404",
    "the registry answered with status 403",
)


@pytest.mark.parametrize("message", NETWORK_ERRORS)
def test_each_way_the_registry_can_be_unreachable_is_recognised(message):
    assert grader.INFRA_RE.search(message), message


@pytest.mark.parametrize("message", CONFIGURATION_ERRORS)
def test_a_mistake_in_the_configuration_is_not_taken_for_a_network_error(message):
    assert not grader.INFRA_RE.search(message), message


@pytest.mark.parametrize("message", [NETWORK_ERRORS[3], NETWORK_ERRORS[5], NETWORK_ERRORS[9]])
def test_an_init_error_that_names_the_network_is_infra(tmp_path, fake_terraform, message):
    trace = make_workspace(tmp_path, "a", {**GOOD, "probe.tf": f"# INIT_ERROR:{message}\n"})
    result = only(grade(tmp_path, fake_terraform, ("a", trace)))
    assert result["status"] == "infra", result
    assert result["detail"] == f"init: Error: {message}"


@pytest.mark.parametrize("message", [CONFIGURATION_ERRORS[0], CONFIGURATION_ERRORS[2], CONFIGURATION_ERRORS[4]])
def test_an_init_error_about_the_configuration_is_validate_failed(tmp_path, fake_terraform, message):
    trace = make_workspace(tmp_path, "a", {**GOOD, "probe.tf": f"# INIT_ERROR:{message}\n"})
    result = only(grade(tmp_path, fake_terraform, ("a", trace)))
    assert result["status"] == "validate_failed", result


def test_the_detail_starts_at_the_first_error_and_is_cut_to_the_limit():
    progress = 'Initializing provider plugins...\n- Finding hashicorp/aws versions matching "~> 5.0"...\n' * 20
    detail = grader.detail_of("init", progress + "Error: Failed to query available provider packages\n\n" + "and the reason " * 200)
    assert detail.startswith("init: Error: Failed to query available provider packages and the reason")
    assert len(detail) == len("init: ") + grader.DETAIL_CHARS
    assert grader.DETAIL_CHARS == 600


def test_the_detail_of_output_without_an_error_starts_at_the_beginning():
    assert grader.detail_of("fmt", "main.tf\nmodules/net/main.tf\n") == "fmt: main.tf modules/net/main.tf"
    assert grader.detail_of("validate", "Error: Unsupported argument") == "validate: Error: Unsupported argument"


def test_missing_workspace_is_reported(tmp_path, fake_terraform):
    result = only(grade(tmp_path, fake_terraform, ("a", str(tmp_path / "gone" / "out" / "trace.jsonl"))))
    assert result["status"] == "no_workspace"
    assert "--keep-temp" in result["detail"]


def test_workspace_without_terraform_files_is_reported(tmp_path, fake_terraform):
    result = only(grade(tmp_path, fake_terraform, ("a", make_workspace(tmp_path, "a", {"notes.md": "no terraform here\n"}))))
    assert result["status"] == "no_terraform_files"


def test_missing_binary_makes_every_attempt_unavailable(tmp_path):
    trace = make_workspace(tmp_path, "a", GOOD)
    result = grade(tmp_path, str(tmp_path / "no-such-terraform"), ("a", trace))
    assert only(result)["status"] == "unavailable"
    assert result["terraform"]["version"] is None


def test_attempt_without_a_trace_path_has_no_workspace(tmp_path, fake_terraform):
    data = aggregate(("a", ""))
    data["cases"][0]["arms"]["with"] = [{}]
    result = grader.grade_aggregate(data, fake_terraform, 60)
    assert only(result)["status"] == "no_workspace"


def test_version_is_recorded(tmp_path, fake_terraform):
    result = grade(tmp_path, fake_terraform, ("a", make_workspace(tmp_path, "a", GOOD)))
    assert result["terraform"]["version"] == "1.16.6"


# --- isolation --------------------------------------------------------------


# Every variable the script's own refusal covers, plus credentials of the clouds the skill writes for.
SECRET_NAMES = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "ARM_CLIENT_SECRET",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "OCI_CLI_KEY_CONTENT",
    "GITHUB_TOKEN",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    "TF_VAR_password",
    "TF_TOKEN_app_terraform_io",
)


def test_credentials_are_not_passed_to_terraform(tmp_path, fake_terraform, monkeypatch):
    for name in SECRET_NAMES:
        monkeypatch.setenv(name, "secret")
    result = only(grade(tmp_path, fake_terraform, ("a", make_workspace(tmp_path, "a", GOOD))))
    assert result["status"] == "ok", result


# Written out rather than read from the script, so a variable added to PASSED_ENV fails here until somebody decides it should pass.
ALLOWED_VARIABLES = frozenset(
    {
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
    }
)
# Variables that change what terraform does, which the script must not hand on from its own environment.
UNLISTED_VARIABLES = (
    "TF_LOG",
    "TF_LOG_PATH",
    "TF_CLI_ARGS",
    "TF_CLI_ARGS_init",
    "TF_DATA_DIR",
    "TF_VAR_region",
    "TF_WORKSPACE",
    "TF_REGISTRY_CLIENT_TIMEOUT",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
)


def test_the_allowlist_is_exactly_these_variables():
    assert set(grader.PASSED_ENV) == ALLOWED_VARIABLES
    assert len(grader.PASSED_ENV) == len(ALLOWED_VARIABLES)


def test_terraform_sees_only_the_variables_on_the_allowlist(tmp_path, fake_terraform, monkeypatch):
    for name in (*SECRET_NAMES, *UNLISTED_VARIABLES):
        monkeypatch.setenv(name, "secret")
    monkeypatch.setenv("TF_PLUGIN_CACHE_DIR", str(tmp_path / "cache"))
    trace = make_workspace(tmp_path, "a", {**GOOD, "probe.tf": "ENVDUMP\nINVALID\n"})
    result = only(grade(tmp_path, fake_terraform, ("a", trace)))
    seen = set(re.search(r"ENV (\S+)", result["detail"]).group(1).split(","))
    # The shell behind the stand-in adds PWD (and SHLVL or _ in some shells), and Python adds LC_CTYPE when it coerces the C locale.
    added_by_the_stand_in = {"PWD", "OLDPWD", "SHLVL", "_", "LC_CTYPE"}
    allowed = ALLOWED_VARIABLES | {"HOME", "TF_IN_AUTOMATION", "TF_INPUT", "CHECKPOINT_DISABLE", "TF_CLI_CONFIG_FILE"} | added_by_the_stand_in
    assert seen <= allowed, sorted(seen - allowed)
    assert not seen & set(SECRET_NAMES)
    assert not seen & set(UNLISTED_VARIABLES)


@pytest.mark.parametrize("name", sorted(ALLOWED_VARIABLES))
def test_each_allowlisted_variable_that_is_set_reaches_terraform(tmp_path, monkeypatch, name):
    monkeypatch.setenv(name, f"value-of-{name}")
    home = tmp_path / "home"
    home.mkdir()
    assert grader.terraform_env(home)[name] == f"value-of-{name}"


def test_terraform_runs_without_prompts_and_with_a_home_of_its_own(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = grader.terraform_env(home)
    assert env["HOME"] == str(home)
    assert env["TF_INPUT"] == "0"
    assert env["TF_IN_AUTOMATION"] == "1"
    assert env["CHECKPOINT_DISABLE"] == "1"
    assert env["TF_CLI_CONFIG_FILE"] == str(home / "terraformrc")


def test_providers_are_installed_from_three_publishers_on_the_public_registry_only(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    config = Path(grader.terraform_env(home)["TF_CLI_CONFIG_FILE"]).read_text(encoding="utf-8")
    assert config == (
        "provider_installation {\n"
        "  direct {\n"
        '    include = ["registry.terraform.io/hashicorp/*", "registry.terraform.io/azure/*", "registry.terraform.io/oracle/*"]\n'
        "  }\n"
        "}\n"
    )
    assert "*/*" not in config


def test_the_model_credentials_the_script_refuses_to_run_beside():
    assert grader.SECRET_VARIABLES == ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")


@pytest.mark.parametrize("name", grader.SECRET_VARIABLES)
def test_script_refuses_to_run_beside_a_model_credential(tmp_path, fake_terraform, capsys, name):
    path = tmp_path / "aggregate-result.json"
    path.write_text(json.dumps(aggregate(("a", make_workspace(tmp_path, "a", GOOD)))), encoding="utf-8")
    out = tmp_path / "static.json"
    code = grader.main(["--aggregate", str(path), "--out", str(out), "--terraform", fake_terraform], env={name: "sk-ant-secret"})  # pragma: allowlist secret
    output = capsys.readouterr().out
    assert code == 2 and not out.exists()
    assert f"{name} is set" in output and "sk-ant-secret" not in output
    assert "Unset it for this command" in output
    assert f"env -u {name} python scripts/grade_eval_workspaces.py" in output


def test_the_refusal_names_every_credential_that_is_set(tmp_path, fake_terraform, capsys):
    path = tmp_path / "aggregate-result.json"
    path.write_text(json.dumps(aggregate(("a", make_workspace(tmp_path, "a", GOOD)))), encoding="utf-8")
    held = {"CLAUDE_CODE_OAUTH_TOKEN": "oauth-secret", "ANTHROPIC_API_KEY": "sk-ant-secret"}  # pragma: allowlist secret
    code = grader.main(["--aggregate", str(path), "--out", str(tmp_path / "o.json"), "--terraform", fake_terraform], env=held)
    output = capsys.readouterr().out
    assert code == 2
    assert "ANTHROPIC_API_KEY, CLAUDE_CODE_OAUTH_TOKEN are set" in output
    assert "Unset them for this command" in output
    assert "env -u ANTHROPIC_API_KEY -u CLAUDE_CODE_OAUTH_TOKEN python" in output
    assert "oauth-secret" not in output and "sk-ant-secret" not in output


def test_a_credential_that_is_set_to_nothing_is_not_a_reason_to_refuse(tmp_path, fake_terraform):
    # A workflow that maps an absent secret passes an empty string, which holds nothing a provider could read.
    path = tmp_path / "aggregate-result.json"
    path.write_text(json.dumps(aggregate(("a", make_workspace(tmp_path, "a", GOOD)))), encoding="utf-8")
    code = grader.main(["--aggregate", str(path), "--out", str(tmp_path / "o.json"), "--terraform", fake_terraform], env={"ANTHROPIC_API_KEY": ""})
    assert code == 0 and (tmp_path / "o.json").exists()


@pytest.mark.parametrize("name", grader.SECRET_VARIABLES)
def test_script_refuses_to_run_beside_a_model_credential_as_a_command(tmp_path, fake_terraform, name):
    path = tmp_path / "aggregate-result.json"
    path.write_text(json.dumps(aggregate(("a", make_workspace(tmp_path, "a", GOOD)))), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "grade_eval_workspaces.py"), "--aggregate", str(path), "--out", str(tmp_path / "o.json"), "--terraform", fake_terraform],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, name: "sk-ant-secret"},  # pragma: allowlist secret
    )
    assert result.returncode == 2
    assert not (tmp_path / "o.json").exists()


def test_only_regular_terraform_files_are_copied(tmp_path, fake_terraform):
    trace = make_workspace(tmp_path, "a", {**GOOD, "modules/vpc/main.tf": "# module\n", "notes.txt": "x", ".terraform/skipped.tf": "x", ".git/skipped.tf": "x"})
    workspace = grader.workspace_for(trace)
    (workspace / "link.tf").symlink_to("/etc/hostname")
    (workspace / "linked-dir").symlink_to(tmp_path)
    result = only(grade(tmp_path, fake_terraform, ("a", trace)))
    assert result["files"] == ["main.tf", "modules/vpc/main.tf", "versions.tf"]
    assert result["skipped"] == ["link.tf"]


def test_too_many_files_is_a_validate_failure(tmp_path, fake_terraform):
    files = {f"f{index}.tf": "# x\n" for index in range(grader.MAX_FILES + 1)}
    result = only(grade(tmp_path, fake_terraform, ("a", make_workspace(tmp_path, "a", files))))
    assert result["status"] == "validate_failed"
    assert "more than" in result["detail"]


def test_exactly_the_file_limit_is_graded(tmp_path, fake_terraform):
    files = {f"f{index}.tf": "# x\n" for index in range(grader.MAX_FILES)}
    result = only(grade(tmp_path, fake_terraform, ("a", make_workspace(tmp_path, "a", files))))
    assert result["status"] == "ok", result
    assert len(result["files"]) == grader.MAX_FILES


def test_terraform_files_over_the_byte_limit_are_a_validate_failure(tmp_path, fake_terraform, monkeypatch):
    monkeypatch.setattr(grader, "MAX_TOTAL_BYTES", 50)
    files = {"a.tf": "#" * 30, "b.tf": "#" * 30}
    result = only(grade(tmp_path, fake_terraform, ("a", make_workspace(tmp_path, "a", files))))
    assert result["status"] == "validate_failed"
    assert result["detail"] == "workspace: more than 200 Terraform files or 50 bytes"


def test_terraform_files_of_exactly_the_byte_limit_are_graded(tmp_path, fake_terraform, monkeypatch):
    monkeypatch.setattr(grader, "MAX_TOTAL_BYTES", 60)
    files = {"a.tf": "#" * 30, "b.tf": "#" * 30}
    result = only(grade(tmp_path, fake_terraform, ("a", make_workspace(tmp_path, "a", files))))
    assert result["status"] == "ok", result


def test_the_limits_are_the_documented_ones():
    assert (grader.MAX_FILES, grader.MAX_TOTAL_BYTES, grader.MAX_ENTRIES, grader.MAX_DEPTH) == (200, 1024 * 1024, 20000, 6)


def test_a_path_the_grader_cannot_read_is_infra_and_not_a_failure_of_the_model(tmp_path, fake_terraform, monkeypatch):
    # Root reads everything, so make lstat refuse one file as it does for another user. A read error on the
    # grader's side says nothing about what the model wrote; a workspace over a limit does.
    trace = make_workspace(tmp_path, "a", {**GOOD, "blocked.tf": "# x\n"})
    original = Path.lstat

    def refusing(self, *args, **kwargs):
        if self.name == "blocked.tf":
            raise PermissionError(13, "Permission denied", str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", refusing)
    result = only(grade(tmp_path, fake_terraform, ("a", trace)))
    assert result["status"] == "infra", result
    assert "could not be read" in result["detail"]


def seal(workspace: Path) -> None:
    """Close every mode in a kept workspace and the two directories above it, children first."""
    for path in sorted(workspace.rglob("*"), reverse=True):
        path.chmod(0o000)
    for directory in (workspace, workspace.parent, workspace.parent.parent):
        directory.chmod(0o000)


def test_closed_modes_on_a_kept_workspace_are_reopened(tmp_path, fake_terraform):
    trace = make_workspace(tmp_path, "a", {**GOOD, "modules/net/main.tf": 'variable "a" {}\n'})
    workspace = grader.workspace_for(trace)
    seal(workspace)
    result = only(grade(tmp_path, fake_terraform, ("a", trace)))
    assert result["status"] == "ok", result
    assert "modules/net/main.tf" in result["files"]
    # Mode bits are checked rather than access, so the test also means something when it runs as root.
    for path in [workspace.parent.parent, workspace.parent, workspace, *workspace.rglob("*")]:
        wanted = 0o700 if path.is_dir() else 0o600
        assert path.stat().st_mode & wanted == wanted, path


def test_a_closed_parent_is_opened_before_the_workspace_is_looked_up(tmp_path, fake_terraform, monkeypatch):
    # Root ignores mode bits, so a run as root passes whatever the order. This makes lstat and stat refuse a
    # path whose parent cannot be searched, as they do for every other user, such as the runner on GitHub.
    def refusing(original):
        def checked(self, *args, **kwargs):
            try:
                searchable = os.stat(self.parent).st_mode & stat.S_IXUSR
            except OSError:
                searchable = stat.S_IXUSR
            if not searchable:
                raise PermissionError(13, "Permission denied", str(self))
            return original(self, *args, **kwargs)

        return checked

    trace = make_workspace(tmp_path, "a", GOOD)
    seal(grader.workspace_for(trace))
    monkeypatch.setattr(Path, "lstat", refusing(Path.lstat))
    monkeypatch.setattr(Path, "stat", refusing(Path.stat))
    result = only(grade(tmp_path, fake_terraform, ("a", trace)))
    assert result["status"] == "ok", result


def test_a_workspace_that_cannot_be_reached_is_reported_not_raised(tmp_path, fake_terraform, monkeypatch):
    trace = make_workspace(tmp_path, "a", GOOD)

    def denied(self):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "is_symlink", denied)
    result = only(grade(tmp_path, fake_terraform, ("a", trace)))
    assert result["status"] == "no_workspace"
    assert "cannot be reached (Permission denied)" in result["detail"]


def test_a_file_that_cannot_be_copied_is_an_infrastructure_error(tmp_path, fake_terraform, monkeypatch):
    trace = make_workspace(tmp_path, "a", GOOD)

    def refuse(source, target, **kwargs):
        raise PermissionError(13, "Permission denied", str(source))

    monkeypatch.setattr(grader.shutil, "copyfile", refuse)
    result = only(grade(tmp_path, fake_terraform, ("a", trace)))
    assert result["status"] == "infra"
    assert result["detail"].startswith("copy: Permission denied")


def test_a_crash_while_grading_one_attempt_does_not_hide_the_others(tmp_path, fake_terraform, monkeypatch):
    first = make_workspace(tmp_path, "a", GOOD)
    second = make_workspace(tmp_path, "b", GOOD)
    real = grader.grade_workspace

    def crashing(binary, workspace, timeout, deadline_at=None):
        if workspace == grader.workspace_for(first):
            raise RuntimeError("boom")
        return real(binary, workspace, timeout, deadline_at)

    monkeypatch.setattr(grader, "grade_workspace", crashing)
    result = grade(tmp_path, fake_terraform, ("a", first), ("b", second))
    assert [entry["status"] for entry in result["attempts"]] == ["infra", "ok"]
    assert "RuntimeError: boom" in result["attempts"][0]["detail"]


def test_reopening_does_not_follow_a_symlink_out_of_the_workspace(tmp_path, fake_terraform):
    outside = tmp_path / "outside.txt"
    outside.write_text("not part of the workspace\n", encoding="utf-8")
    outside.chmod(0o000)
    trace = make_workspace(tmp_path, "a", GOOD)
    workspace = grader.workspace_for(trace)
    (workspace / "link.txt").symlink_to(outside)
    grade(tmp_path, fake_terraform, ("a", trace))
    assert outside.stat().st_mode & 0o777 == 0o000


def test_reopening_does_not_change_the_mode_of_a_file_that_is_hard_linked_in(tmp_path, fake_terraform):
    # A second link to a file outside the workspace is the same file, so a chmod through it changes the original.
    outside = tmp_path / "outside.txt"
    outside.write_text("not part of the workspace\n", encoding="utf-8")
    outside.chmod(0o400)
    trace = make_workspace(tmp_path, "a", GOOD)
    os.link(outside, grader.workspace_for(trace) / "linked.txt")
    grade(tmp_path, fake_terraform, ("a", trace))
    assert outside.stat().st_mode & 0o777 == 0o400


def test_kept_workspace_is_left_untouched(tmp_path, fake_terraform):
    trace = make_workspace(tmp_path, "a", GOOD)
    workspace = grader.workspace_for(trace)
    before = sorted(path.name for path in workspace.rglob("*"))
    grade(tmp_path, fake_terraform, ("a", trace))
    assert sorted(path.name for path in workspace.rglob("*")) == before
    assert not (workspace / ".terraform").exists()


def kept_run(tmp_path: Path, name: str = "a") -> tuple[Path, str]:
    """An empty kept-run layout (<name>/out only) and its trace path, for tests that build home/cwd themselves."""
    run = tmp_path / name
    (run / "out").mkdir(parents=True)
    return run, str(run / "out" / "trace.jsonl")


def test_a_symlinked_workspace_is_not_read(tmp_path, fake_terraform):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "main.tf").write_text("INVALID\n", encoding="utf-8")
    run, trace = kept_run(tmp_path)
    (run / "home").mkdir()
    (run / "home" / "cwd").symlink_to(outside)
    result = only(grade(tmp_path, fake_terraform, ("a", trace)))
    assert result["status"] == "no_workspace"
    assert "symlink" in result["detail"]


def test_a_symlinked_home_directory_is_neither_read_nor_changed(tmp_path, fake_terraform):
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "cwd").mkdir(parents=True)
    (elsewhere / "cwd" / "main.tf").write_text("INVALID\n", encoding="utf-8")
    elsewhere.chmod(0o500)
    run, trace = kept_run(tmp_path)
    (run / "home").symlink_to(elsewhere)
    try:
        result = only(grade(tmp_path, fake_terraform, ("a", trace)))
        assert result["status"] == "no_workspace"
        assert elsewhere.stat().st_mode & 0o777 == 0o500
    finally:
        elsewhere.chmod(0o700)


def test_a_mode_is_never_granted_through_a_symlink(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    target.chmod(0o500)
    link = tmp_path / "link"
    link.symlink_to(target)
    try:
        assert grader.grant(link, 0o700) is False
        assert target.stat().st_mode & 0o777 == 0o500
    finally:
        target.chmod(0o700)


def test_a_hard_linked_terraform_file_is_skipped_and_not_copied(tmp_path, fake_terraform):
    outside = tmp_path / "outside.tf"
    outside.write_text("INVALID\n", encoding="utf-8")
    trace = make_workspace(tmp_path, "a", GOOD)
    os.link(outside, grader.workspace_for(trace) / "linked.tf")
    result = only(grade(tmp_path, fake_terraform, ("a", trace)))
    assert result["status"] == "ok", result
    assert "linked.tf" not in result["files"]
    assert result["skipped"] == ["linked.tf"]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes need a POSIX system")
def test_a_named_pipe_with_a_terraform_name_is_skipped_without_blocking(tmp_path, fake_terraform):
    trace = make_workspace(tmp_path, "a", GOOD)
    os.mkfifo(grader.workspace_for(trace) / "pipe.tf")
    result = only(grade(tmp_path, fake_terraform, ("a", trace)))
    assert result["status"] == "ok", result
    assert result["skipped"] == ["pipe.tf"]


def test_a_module_at_the_depth_limit_is_still_collected(tmp_path, fake_terraform):
    nested = "/".join("abcdef") + "/main.tf"
    result = only(grade(tmp_path, fake_terraform, ("a", make_workspace(tmp_path, "a", {**GOOD, nested: "# deep\n"}))))
    assert result["status"] == "ok", result
    assert nested in result["files"]


def test_directories_below_the_depth_limit_are_a_validate_failure_not_a_silent_drop(tmp_path, fake_terraform):
    nested = "/".join("abcdefg") + "/main.tf"
    result = only(grade(tmp_path, fake_terraform, ("a", make_workspace(tmp_path, "a", {**GOOD, nested: "# deeper\n"}))))
    assert result["status"] == "validate_failed"
    assert "nested more than 6 levels" in result["detail"]


def test_a_workspace_with_too_many_entries_is_a_validate_failure(tmp_path, fake_terraform, monkeypatch):
    monkeypatch.setattr(grader, "MAX_ENTRIES", 5)
    files = {**GOOD, **{f"note{index}.txt": "x" for index in range(10)}}
    result = only(grade(tmp_path, fake_terraform, ("a", make_workspace(tmp_path, "a", files))))
    assert result["status"] == "validate_failed"
    assert "more than 5 entries" in result["detail"]


def test_a_tree_of_exactly_the_entry_limit_is_graded(tmp_path, fake_terraform, monkeypatch):
    monkeypatch.setattr(grader, "MAX_ENTRIES", len(GOOD))
    result = only(grade(tmp_path, fake_terraform, ("a", make_workspace(tmp_path, "a", GOOD))))
    assert result["status"] == "ok", result


# --- processes --------------------------------------------------------------


def test_a_child_left_behind_by_terraform_is_killed(tmp_path, fake_terraform):
    marker = tmp_path / "late.txt"
    trace = make_workspace(tmp_path, "a", {**GOOD, "probe.tf": f"LEAVE_CHILD:{marker}\n"})
    result = only(grade(tmp_path, fake_terraform, ("a", trace)))
    assert result["status"] == "ok", result
    assert (tmp_path / "late.txt.started").exists(), "the stand-in never started its child"
    time.sleep(1.6)
    assert not marker.exists()


def test_a_child_that_keeps_the_output_open_neither_blocks_nor_fails_validate(tmp_path, fake_terraform):
    trace = make_workspace(tmp_path, "a", {**GOOD, "probe.tf": "HOLD_OUTPUT\n"})
    started = time.monotonic()
    result = only(grade(tmp_path, fake_terraform, ("a", trace)))
    assert result["status"] == "ok", result
    assert time.monotonic() - started < 4


def test_a_hung_init_is_killed_at_the_timeout_and_is_infra(tmp_path, fake_terraform):
    trace = make_workspace(tmp_path, "a", {**GOOD, "probe.tf": "HANG_INIT\n"})
    started = time.monotonic()
    result = only(grader.grade_aggregate(aggregate(("a", trace)), fake_terraform, 1))
    assert (result["status"], result["detail"]) == ("infra", "init: timed out after 1s")
    assert time.monotonic() - started < 6


def test_a_hung_validate_is_infra_and_not_a_failure_of_the_model(tmp_path, fake_terraform):
    trace = make_workspace(tmp_path, "a", {**GOOD, "probe.tf": "HANG_VALIDATE\n"})
    result = only(grader.grade_aggregate(aggregate(("a", trace)), fake_terraform, 1))
    assert (result["status"], result["detail"]) == ("infra", "validate: timed out after 1s")


def test_a_hung_fmt_still_leaves_a_valid_configuration_ok_with_fmt_error(tmp_path, fake_terraform):
    # terraform fmt only warns, so a fmt that cannot finish does not throw away a configuration that validated.
    # The classifier records it as a warning.
    trace = make_workspace(tmp_path, "a", {**GOOD, "probe.tf": "HANG_FMT\n"})
    result = only(grader.grade_aggregate(aggregate(("a", trace)), fake_terraform, 1))
    assert (result["status"], result["fmt"]) == ("ok", "error")
    assert result["detail"] == "fmt: timed out after 1s"


def test_attempts_after_the_deadline_are_infra(tmp_path, fake_terraform):
    data = aggregate(("a", make_workspace(tmp_path, "a", GOOD)), ("b", make_workspace(tmp_path, "b", GOOD)))
    result = grader.grade_aggregate(data, fake_terraform, 60, deadline=0)
    assert [entry["status"] for entry in result["attempts"]] == ["infra", "infra"]
    assert "0s grading deadline" in result["attempts"][0]["detail"]


def test_a_command_may_not_run_past_the_deadline(tmp_path, fake_terraform):
    slow = make_workspace(tmp_path, "a", {**GOOD, "probe.tf": "HANG_INIT\n"})
    data = aggregate(("a", slow), ("b", make_workspace(tmp_path, "b", GOOD)))
    started = time.monotonic()
    result = grader.grade_aggregate(data, fake_terraform, 60, deadline=1)
    assert [entry["status"] for entry in result["attempts"]] == ["infra", "infra"]
    assert result["attempts"][0]["detail"] == "init: timed out after 1s"
    assert "1s grading deadline" in result["attempts"][1]["detail"]
    assert time.monotonic() - started < 6


@pytest.mark.parametrize("step", ["init", "validate", "fmt"])
def test_a_command_that_prints_without_end_is_stopped_at_the_output_limit(tmp_path, fake_terraform, monkeypatch, step):
    monkeypatch.setattr(grader, "MAX_SINK_BYTES", 200_000)
    monkeypatch.setattr(grader, "POLL_SECONDS", 0.02)
    trace = make_workspace(tmp_path, "a", {**GOOD, "probe.tf": f"FLOOD:{step}\n"})
    started = time.monotonic()
    result = only(grade(tmp_path, fake_terraform, ("a", trace)))
    # The stand-in stops by itself and exits 0 after about two seconds, so a limit that does not work shows as a pass here.
    assert time.monotonic() - started < 5
    if step == "fmt":
        assert (result["status"], result["fmt"]) == ("ok", "error"), result
    else:
        assert result["status"] == "validate_failed", result
    assert result["detail"].startswith(f"{step}: Error: flood")
    assert len(result["detail"]) == len(f"{step}: ") + grader.DETAIL_CHARS


def test_run_terraform_stops_a_command_over_the_output_limit_and_keeps_the_start_of_its_output(tmp_path, monkeypatch):
    monkeypatch.setattr(grader, "MAX_SINK_BYTES", 100_000)
    monkeypatch.setattr(grader, "POLL_SECONDS", 0.02)
    command = "import sys, time; sys.stdout.write('z' * 300000); sys.stdout.flush(); time.sleep(30)"
    started = time.monotonic()
    code, output = grader.run_terraform(sys.executable, ["-c", command], tmp_path, dict(os.environ), 60)
    assert code == grader.OUTPUT_LIMIT
    assert output == "z" * grader.MAX_OUTPUT_BYTES
    assert time.monotonic() - started < 5


def test_run_terraform_lets_a_command_write_exactly_the_output_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(grader, "MAX_SINK_BYTES", 100_000)
    monkeypatch.setattr(grader, "POLL_SECONDS", 0.02)
    command = "import sys, time; sys.stdout.write('z' * 100000); sys.stdout.flush(); time.sleep(0.3)"
    code, output = grader.run_terraform(sys.executable, ["-c", command], tmp_path, dict(os.environ), 60)
    # Exit 0 is the point: the limit is a strict one, so a sink of exactly MAX_SINK_BYTES is not over it. The read back is capped separately.
    assert (code, len(output)) == (0, grader.MAX_OUTPUT_BYTES)


def test_only_the_start_of_a_long_output_is_read_back(tmp_path):
    code, output = grader.run_terraform(sys.executable, ["-c", "print('y' * 200000)"], tmp_path, dict(os.environ), 30)
    assert code == 0
    assert len(output) == grader.MAX_OUTPUT_BYTES == 64 * 1024


def test_output_that_is_not_utf8_is_decoded_with_replacement(tmp_path, fake_terraform):
    trace = make_workspace(tmp_path, "a", {**GOOD, "probe.tf": "BAD_BYTES\n"})
    result = only(grade(tmp_path, fake_terraform, ("a", trace)))
    assert result["status"] == "validate_failed"
    assert "caf\ufffd.tf" in result["detail"]


# --- command line -----------------------------------------------------------


def run_script_on(tmp_path: Path, terraform: str, text: str) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "aggregate-result.json"
    path.write_text(text, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "grade_eval_workspaces.py"), "--aggregate", str(path), "--out", str(tmp_path / "static.json"), "--terraform", terraform],
        capture_output=True,
        text=True,
        check=False,
    )


def run_script(tmp_path: Path, terraform: str, data: dict) -> subprocess.CompletedProcess[str]:
    return run_script_on(tmp_path, terraform, json.dumps(data))


def test_script_writes_one_record_per_attempt(tmp_path, fake_terraform):
    data = aggregate(("a", make_workspace(tmp_path, "a", GOOD)), ("b", make_workspace(tmp_path, "b", {**GOOD, "main.tf": "INVALID\n"})))
    result = run_script(tmp_path, fake_terraform, data)
    assert result.returncode == 0, result.stdout + result.stderr
    written = json.loads((tmp_path / "static.json").read_text())
    assert [entry["status"] for entry in written["attempts"]] == ["ok", "validate_failed"]
    assert "author-sample[0]: ok, fmt clean" in result.stdout
    assert "Terraform 1.16.6: graded 2 attempt(s)." in result.stdout


def test_script_reports_an_unreadable_result(tmp_path, fake_terraform):
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "grade_eval_workspaces.py"), "--aggregate", str(tmp_path / "none.json"), "--out", str(tmp_path / "o.json"), "--terraform", fake_terraform],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "cannot read the eval result" in result.stdout


@pytest.mark.parametrize("content", ["[]", '"cases"', "null", "3", '{"cases": "x"}', '{"cases": null}', '{"cases": {}}', '{"cases": 3}'])
def test_an_eval_result_of_another_shape_is_reported_and_not_a_traceback(tmp_path, fake_terraform, content):
    result = run_script_on(tmp_path, fake_terraform, content)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "is not in the shape this script reads" in result.stdout
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "static.json").exists()


def test_an_eval_result_with_no_cases_grades_nothing(tmp_path, fake_terraform):
    result = run_script_on(tmp_path, fake_terraform, "{}")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads((tmp_path / "static.json").read_text())["attempts"] == []


WRITES_TERRAFORM = {"type": "file_exists", "config": {"path": "versions.tf", "exists": True}}
ODD_CASES = {
    "entries that are not cases": [1, "text", None, [], {"name": 3}],
    "graders that are not a list": [{"name": "x", "graders": "nope"}, {"name": "y", "graders": 3}, {"name": "z", "graders": None}],
    "no graders": [{"name": "x"}],
    "graders that are not objects": [{"name": "x", "graders": [1, None, "nope", {"type": "file_exists", "config": "nope"}, {"type": "file_exists"}]}],
    "arms that are not an object": [{"name": "x", "graders": [WRITES_TERRAFORM], "arms": "nope"}],
    "an arm that is not a list": [{"name": "x", "graders": [WRITES_TERRAFORM], "arms": {"with": "nope"}}],
    "no arms": [{"name": "x", "graders": [WRITES_TERRAFORM]}],
}


@pytest.mark.parametrize("cases", ODD_CASES.values(), ids=ODD_CASES.keys())
def test_cases_of_an_odd_shape_are_skipped_and_not_a_traceback(tmp_path, fake_terraform, cases):
    result = run_script(tmp_path, fake_terraform, {"cases": cases})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert json.loads((tmp_path / "static.json").read_text())["attempts"] == []


def test_attempts_that_are_not_objects_have_no_workspace(tmp_path, fake_terraform):
    case = {"name": "x", "graders": [WRITES_TERRAFORM], "arms": {"with": [1, None, "text", {}, {"tracePath": ""}]}}
    result = run_script(tmp_path, fake_terraform, {"cases": [case]})
    assert result.returncode == 0, result.stdout + result.stderr
    attempts = json.loads((tmp_path / "static.json").read_text())["attempts"]
    assert [(entry["attempt"], entry["status"]) for entry in attempts] == [(index, "no_workspace") for index in range(5)]
    assert {entry["detail"] for entry in attempts} == {"the run recorded no trace path"}


# --- the real binary --------------------------------------------------------

real_terraform = pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform is not installed")
# Read at import: the autouse fixture in conftest.py removes the variable for each test.
ON_GITHUB_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"


def real_fixture_trace(tmp_path: Path, name: str) -> str:
    """Copy tests/fixtures/eval-workspaces/<name> into a kept-workspace layout."""
    run = tmp_path / name
    shutil.copytree(FIXTURES / name, run / "home" / "cwd")
    (run / "out").mkdir()
    return str(run / "out" / "trace.jsonl")


@real_terraform
def test_real_terraform_accepts_the_good_fixture(tmp_path):
    result = only(grade(tmp_path, "terraform", ("good", real_fixture_trace(tmp_path, "good"))))
    assert (result["status"], result["fmt"]) == ("ok", "clean"), result


@real_terraform
def test_real_terraform_rejects_an_unsupported_argument(tmp_path):
    result = only(grade(tmp_path, "terraform", ("bad", real_fixture_trace(tmp_path, "unsupported-argument"))))
    assert result["status"] == "validate_failed"
    assert "Unsupported argument" in result["detail"]


@real_terraform
def test_real_terraform_rejects_a_syntax_error(tmp_path):
    result = only(grade(tmp_path, "terraform", ("bad", real_fixture_trace(tmp_path, "syntax-error"))))
    assert result["status"] == "validate_failed"
    # init parses the configuration, so terraform may reject the syntax there or in validate.
    assert result["detail"].split(":", 1)[0] in ("init", "validate"), result


@real_terraform
def test_real_terraform_reports_unformatted_files(tmp_path):
    result = only(grade(tmp_path, "terraform", ("fmt", real_fixture_trace(tmp_path, "unformatted"))))
    assert (result["status"], result["fmt"]) == ("ok", "diff")


@real_terraform
def test_real_terraform_checks_modules(tmp_path):
    result = only(grade(tmp_path, "terraform", ("mod", real_fixture_trace(tmp_path, "with-module"))))
    assert result["status"] == "ok", result
    assert "modules/pair/main.tf" in result["files"]


OTHER_HOST_PROVIDER = """\
terraform {
  required_providers {
    thing = {
      source  = "example.invalid/acme/thing"
      version = "1.0.0"
    }
  }
}
"""
# Published on the public registry by a namespace the skill's references do not name. No version is pinned, so a
# configuration that let init reach the registry would install it rather than fail on the constraint.
OTHER_NAMESPACE_PROVIDER = """\
terraform {
  required_providers {
    github = {
      source = "integrations/github"
    }
  }
}
"""
REGISTRY_PROVIDER = """\
terraform {
  required_providers {
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}

resource "null_resource" "this" {}
"""


@real_terraform
def test_real_terraform_does_not_go_looking_for_a_provider_on_another_host(tmp_path):
    trace = make_workspace(tmp_path, "other", {"main.tf": OTHER_HOST_PROVIDER})
    result = only(grade(tmp_path, "terraform", ("other", trace)))
    # `infra` would mean terraform tried to reach the host, which the CLI configuration must stop.
    assert result["status"] == "validate_failed", result
    assert result["detail"].startswith("init:"), result


@real_terraform
def test_real_terraform_does_not_install_a_provider_from_another_namespace_on_the_registry(tmp_path):
    trace = make_workspace(tmp_path, "namespace", {"main.tf": OTHER_NAMESPACE_PROVIDER})
    result = only(grade(tmp_path, "terraform", ("namespace", trace)))
    # The provider exists, so without the namespace list init would install it: `ok`, or `infra` without a network.
    assert result["status"] == "validate_failed", result
    assert result["detail"].startswith("init:"), result


@real_terraform
def test_real_terraform_installs_a_provider_from_the_public_registry(tmp_path):
    trace = make_workspace(tmp_path, "registry", {"main.tf": REGISTRY_PROVIDER})
    result = only(grade(tmp_path, "terraform", ("registry", trace)))
    # A machine without a network skips this. A runner has one, so there an `infra` result is a failure, not a skip.
    if result["status"] == "infra" and not ON_GITHUB_ACTIONS:
        pytest.skip(f"the registry could not be reached: {result['detail']}")
    assert (result["status"], result.get("fmt")) == ("ok", "clean"), result
