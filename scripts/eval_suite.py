#!/usr/bin/env python3
"""Read a `claude plugin eval` suite: evals/<case>/prompt.md plus graders/*.md.

validate_evals.py and classify_eval_run.py both import this module so that they
read the cases the same way and format GitHub annotations the same way. Run it
directly to list the cases it finds.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # reported by the callers so the failure says what to install
    yaml = None

if yaml is not None:
    # The scalar types PyYAML reads by YAML 1.1 rules and the runner's parser (`Bun.YAML`) by 1.2 rules.
    _SCALARS_READ_DIFFERENTLY = ("bool", "int", "float", "timestamp")

    class Yaml12Loader(yaml.SafeLoader):
        """A SafeLoader that reads scalars as YAML 1.2 does, which is how `claude plugin eval` reads the frontmatter.

        PyYAML follows YAML 1.1: `yes`, `no`, `on` and `off` are booleans, `010` is octal 8, and `1_000`,
        `1:30` and `2026-10-24` are a number, a number and a date. The runner reads each of them as the text it
        looks like, and `010` as 10, so a value like `runs: 010` would otherwise be counted differently here.
        """

    Yaml12Loader.yaml_implicit_resolvers = {
        first: [(tag, rule) for tag, rule in resolvers if tag.rsplit(":", 1)[-1] not in _SCALARS_READ_DIFFERENTLY]
        for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    Yaml12Loader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF"))
    Yaml12Loader.add_implicit_resolver(
        "tag:yaml.org,2002:int", re.compile(r"^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$"), list("-+0123456789")
    )
    Yaml12Loader.add_implicit_resolver(
        "tag:yaml.org,2002:float",
        re.compile(r"^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$"),
        list("-+0123456789."),
    )

    def _construct_int(loader: Any, node: Any) -> int:
        text = loader.construct_scalar(node)
        sign = -1 if text.startswith("-") else 1
        digits = text.lstrip("+-")
        if digits.startswith("0o"):
            return sign * int(digits[2:], 8)
        if digits.startswith("0x"):
            return sign * int(digits[2:], 16)
        return sign * int(digits, 10)

    Yaml12Loader.add_constructor("tag:yaml.org,2002:int", _construct_int)


# Keys the native loader accepts in prompt.md frontmatter (read from the stable release, Claude Code 2.1.308).
# It rejects any other key, but it ignores unknown keys in case.yaml.
NATIVE_PROMPT_KEYS = frozenset(
    {
        "schema_version",
        "name",
        "description",
        "tags",
        "plugins",
        "runs",
        "expected_outcome",
        "model",
        "max_turns",
        "timeout_seconds",
        "allowed_tools",
        "disallowed_tools",
        "artifact_publish",
        "growthbook_overrides",
        "append_system_prompt",
        "env",
    }
)
# Keys this repository uses. Every other native key is rejected by the validator.
PROMPT_KEYS = (
    "description",
    "tags",
    "runs",
    "model",
    "max_turns",
    "timeout_seconds",
    "allowed_tools",
    "disallowed_tools",
)
SUITE_TAGS = ("gate", "authoring")
KIND_TAGS = ("guardrail", "capability")
ADVISORY_PREFIX = "advisory-"

# The closing `---` starts a line. The runner takes the first `---` it finds, wherever it is, so a `---` that
# ends a value would cut the frontmatter short there; reading only a line start as the closing leaves that
# `---` inside the block, where split_frontmatter rejects it.
FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(?:(.*?)\r?\n)?---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
# `results/` holds run output and `mocks/` holds MCP mocks. Neither is a case.
NON_CASE_DIRS = frozenset({"results", "mocks"})


@dataclass
class Grader:
    name: str
    path: Path
    meta: dict[str, Any]
    body: str
    problem: str | None = None

    @property
    def type(self) -> str | None:
        value = self.meta.get("type")
        return value if isinstance(value, str) else None

    @property
    def advisory(self) -> bool:
        return self.name.startswith(ADVISORY_PREFIX)


@dataclass
class Case:
    name: str
    path: Path
    meta: dict[str, Any] = field(default_factory=dict)
    prompt: str = ""
    graders: list[Grader] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def tags(self) -> list[str]:
        tags = self.meta.get("tags")
        return [tag for tag in tags if isinstance(tag, str)] if isinstance(tags, list) else []

    @property
    def kind(self) -> str | None:
        kinds = [tag for tag in self.tags if tag in KIND_TAGS]
        return kinds[0] if len(kinds) == 1 else None

    @property
    def suite(self) -> str | None:
        suites = [tag for tag in self.tags if tag in SUITE_TAGS]
        return suites[0] if len(suites) == 1 else None

    @property
    def model(self) -> str | None:
        value = self.meta.get("model")
        return value if isinstance(value, str) else None

    @property
    def writes_terraform(self) -> bool:
        """The case must leave a .tf file behind, so its output gets `terraform validate`."""
        return any(
            grader.type == "file_exists" and str(grader.meta.get("path", "")).endswith(".tf") for grader in self.graders
        )


def split_frontmatter(text: str) -> tuple[dict[str, Any] | None, str, str | None]:
    """Return (frontmatter mapping, body, problem). The mapping is None on a problem."""
    if yaml is None:
        return None, text, "PyYAML is not installed"
    if text.startswith("\ufeff"):
        return None, text, "the file starts with a byte-order mark; save it as UTF-8 without one"
    match = FRONTMATTER_RE.match(text)
    if match is None:
        return None, text, "no `---` frontmatter block at the top of the file"
    block = match.group(1) or ""
    if "---" in block:
        # The runner ends the frontmatter at the first `---` it finds, even inside a value, and then
        # fails to parse what is left (checked on Claude Code 2.1.308). A YAML parser would accept it.
        return None, text[match.end() :], (
            "the frontmatter contains `---`, which `claude plugin eval` reads as its closing line; "
            "write a run of hyphens in a regex as -{3} or -{5}"
        )
    try:
        loaded = yaml.load(block, Loader=Yaml12Loader)  # noqa: S506 - a SafeLoader subclass
    except yaml.YAMLError as exc:
        return None, text[match.end() :], f"frontmatter is not valid YAML ({exc})"
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        return None, text[match.end() :], "frontmatter must be a mapping"
    return loaded, text[match.end() :].strip("\n"), None


def read_text(path: Path) -> tuple[str, str | None]:
    """The file's text and, when it cannot be read as UTF-8, a problem to report instead of a traceback."""
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError:
        return "", "the file is not valid UTF-8"
    except OSError as exc:
        return "", f"the file cannot be read ({exc.strerror or exc})"


def load_case(case_dir: Path) -> Case:
    case = Case(name=case_dir.name, path=case_dir)
    prompt_file = case_dir / "prompt.md"
    if prompt_file.is_file():
        content, unreadable = read_text(prompt_file)
        meta, body, problem = (None, "", unreadable) if unreadable else split_frontmatter(content)
        if problem:
            case.problems.append(f"prompt.md: {problem}")
        else:
            case.meta = meta or {}
        case.prompt = body.strip()
    else:
        case.problems.append("prompt.md is missing")

    grader_dir = case_dir / "graders"
    if grader_dir.is_dir():
        for grader_file in sorted(grader_dir.glob("*.md")):
            content, unreadable = read_text(grader_file)
            meta, body, problem = (None, "", unreadable) if unreadable else split_frontmatter(content)
            case.graders.append(
                Grader(
                    name=grader_file.stem,
                    path=grader_file,
                    meta=meta or {},
                    body=body.strip(),
                    problem=problem,
                )
            )
    return case


def load_suite(evals_dir: Path) -> list[Case]:
    """Load every case directory (one that holds prompt.md or case.yaml) under evals_dir."""
    cases: list[Case] = []
    for entry in sorted(evals_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name in NON_CASE_DIRS:
            continue
        if (entry / "prompt.md").is_file() or (entry / "case.yaml").is_file():
            cases.append(load_case(entry))
    return cases


def annotation(level: str, message: str, file: str | None = None) -> str:
    """Format a GitHub Actions workflow command such as `::error file=a.md::text`."""

    def escape(text: str) -> str:
        return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")

    properties = f" file={escape(file).replace(':', '%3A').replace(',', '%2C')}" if file else ""
    return f"::{level}{properties}::{escape(message)}"


def annotate(level: str, message: str, file: str | None = None) -> None:
    """Print a workflow command, but only on a GitHub runner where it is interpreted."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(annotation(level, message, file))


def append_step_summary(markdown: str) -> None:
    """Append to the job summary when running in GitHub Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(markdown.rstrip("\n") + "\n")


def main(argv: list[str]) -> int:
    if yaml is None:
        print("PyYAML is required; install it with `python -m pip install pyyaml`.")
        return 1
    evals_dir = Path(argv[1]) if len(argv) > 1 else Path.cwd() / "plugins" / "terraform-multicloud-orchestrator" / "evals"
    if not evals_dir.is_dir():
        print(f"{evals_dir}: not a directory")
        return 1
    for case in load_suite(evals_dir):
        print(f"{case.name}\t{case.suite}\t{case.kind}\t{case.model}\t{len(case.graders)} graders")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
