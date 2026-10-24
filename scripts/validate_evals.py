#!/usr/bin/env python3
"""Validate the `claude plugin eval` suites under plugins/*/evals before CI spends model calls on them.

`claude plugin eval` loads a suite without checking most of what makes a case
meaningful: it accepts a grader that can never pass, a regex that only throws
once a paid run reaches it, and a model alias that resolves differently from one
release to the next. This script checks those things from the files alone.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import eval_suite
from eval_suite import Case, Grader


CASE_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
GRADER_NAME_RE = re.compile(r"^(?:advisory-)?[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
# A full, versioned model ID. A family alias moves to a new model without a diff, which
# would change what a score means.
MODEL_RE = re.compile(r"^claude-[a-z0-9]+(?:-[a-z0-9]+)*-\d[a-z0-9-]*$")
RUNS_RANGE = (3, 10)
MAX_TURNS_RANGE = (1, 50)
TIMEOUT_RANGE = (30, 1800)
TRIGGER_MAX_TURNS = 4
# No case grants Bash: it needs bubblewrap and socat on the runner, and a case that
# could run commands could run `terraform apply`.
ALLOWED_TOOLS = ("Read", "Glob", "Grep", "Skill", "Write")
GRADED_TOOLS = ("Skill", "Bash", "Write")
GRADER_TYPES = ("regex", "tool_used", "file_exists", "llm")
COMMON_GRADER_KEYS = frozenset({"type", "weight", "arm"})
GRADER_KEYS = {
    "regex": frozenset({"pattern", "flags", "match", "target"}),
    "tool_used": frozenset({"tool", "input_match", "min", "max"}),
    "file_exists": frozenset({"path", "exists"}),
    "llm": frozenset(),
}
ADVISORY_TYPES = ("regex", "llm")
JUDGED_SUFFIX = "-judged"
SKILL_FIRED = "skill-fired"
SKILL_NOT_FIRED = "skill-not-fired"
CRITERIA_MAX_CHARS = 1000
PROMPT_MAX_CHARS = 4000
# Attempts per suite per run (the sum of `runs`). Raising a cap is a reviewed change
# because attempts are what the Anthropic bill is made of.
ATTEMPT_CAPS = {"gate": 48, "authoring": 20}
# What one attempt cost when the suites were measured on 24 October 2026, judge included. A suite at its cap
# should cost about 70% of the ceiling the workflow gives it ($4 for gate, $5 for authoring), so a suite that
# grows reaches its cap before the ceiling stops a run half way. tests/test_validate_evals.py checks the sums.
MEASURED_COST_PER_ATTEMPT_USD = {"gate": 0.06, "authoring": 0.18}
# Constructs that Python's `re` and PCRE accept but a JavaScript RegExp rejects or reads differently: inline
# flag groups, (?P...), atomic groups, \A and \Z. A backslash that is itself escaped (\\Z) is not one of them.
NON_JS_REGEX_RE = re.compile(r"\(\?[A-Za-z]+(?:-[A-Za-z]+)?[:)]|\(\?P[<=>]|\(\?>|(?<!\\)(?:\\\\)*\\[AZ]")
# JavaScript names a group (?<name>...); Python's re wants (?P<name>...). Only used when Node is missing.
JS_NAMED_GROUP_RE = re.compile(r"\(\?<([A-Za-z_][A-Za-z0-9_]*)>")
NODE_REGEX_CHECK = (
    "const items = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
    "process.stdout.write(JSON.stringify(items.map(([pattern, flags]) => {"
    " try { new RegExp(pattern, flags); return null; } catch (error) { return error.message; }"
    "})));"
)


@dataclass
class Context:
    root: Path
    skill_names: set[str]
    queries: dict[str, dict[str, Any]]
    # True when eval_queries.json could not be read, which is reported once rather than on every trigger case.
    queries_unreadable: bool = False
    problems: list[tuple[str, str]] = field(default_factory=list)
    # (file, key, pattern, flags) for every regex, compiled together at the end.
    patterns: list[tuple[str, str, str, str]] = field(default_factory=list)

    def rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    def add(self, path: Path, message: str) -> None:
        self.problems.append((self.rel(path), message))


def main() -> int:
    if eval_suite.yaml is None:
        print(
            "PyYAML is required to validate eval cases; "
            "install pyyaml with `python -m pip install pyyaml`."
        )
        return 1

    root = Path.cwd()
    suites = sorted(root.glob("plugins/*/evals"))
    if not suites:
        print("No eval suites found under plugins/*/evals")
        return 1

    problems: list[tuple[str, str]] = []
    rows: list[tuple[str, str, int, int]] = []
    notes: list[str] = []
    for evals_dir in suites:
        context = validate_suite(root, evals_dir)
        problems.extend(context.problems)
        cases = eval_suite.load_suite(evals_dir)
        for suite_name in eval_suite.SUITE_TAGS:
            members = [case for case in cases if case.suite == suite_name]
            attempts = sum(runs_of(case) for case in members)
            rows.append((context.rel(evals_dir), suite_name, len(members), attempts))
    if not node_available():
        notes.append("Node.js was not found, so regexes were only checked with Python's re module.")

    summary = ["### Eval suite validation", "", "| Suite | Tag | Cases | Attempts per run |", "| --- | --- | --- | --- |"]
    summary.extend(f"| `{path}` | `{tag}` | {count} | {attempts} |" for path, tag, count, attempts in rows)
    if problems:
        summary.extend(["", f"**{len(problems)} problem(s):**", ""])
        summary.extend(f"- `{path}`: {message}" for path, message in problems)
    eval_suite.append_step_summary("\n".join(summary))

    if problems:
        print("Eval suite validation failed:")
        for path, message in problems:
            print(f"- {path}: {message}")
            eval_suite.annotate("error", message, path)
        return 1

    for note in sorted(set(notes)):
        print(f"note: {note}")
        eval_suite.annotate("notice", note)
    total_cases = sum(count for _, _, count, _ in rows)
    print(f"Validated {total_cases} eval case(s) in {len(suites)} suite(s).")
    return 0


def int_of(value: Any) -> int | None:
    """The value when it is a real integer. A bool, a string and a missing value are not."""
    return value if type(value) is int else None


def min_calls(grader: Grader) -> int | None:
    """The `min` of a tool_used grader, which the runner reads as 1 when it is absent."""
    return int_of(grader.meta.get("min", 1))


def runs_of(case: Case) -> int:
    runs = case.meta.get("runs")
    return runs if type(runs) is int else 0


def node_available() -> bool:
    return shutil.which("node") is not None


def validate_suite(root: Path, evals_dir: Path) -> Context:
    plugin_dir = evals_dir.parent
    skills_dir = plugin_dir / "skills"
    skill_names = {
        skill.parent.name for skill in skills_dir.glob("*/SKILL.md")
    } if skills_dir.is_dir() else set()
    queries, query_problems = load_queries(plugin_dir, skill_names)
    context = Context(root=root, skill_names=skill_names, queries=queries, queries_unreadable=bool(query_problems))
    for path, message in query_problems:
        context.add(path, message)

    check_layout(context, evals_dir)
    cases = eval_suite.load_suite(evals_dir)
    if not cases:
        context.add(evals_dir, "has no eval cases (a case is a directory with prompt.md)")
    for case in cases:
        check_case(context, case)
    check_attempt_caps(context, evals_dir, cases)
    check_regexes(context)
    return context


def load_queries(plugin_dir: Path, skill_names: set[str]) -> tuple[dict[str, dict[str, Any]], list[tuple[Path, str]]]:
    """Return the trigger queries of every skill by id, and a problem for each eval_queries.json that cannot be read."""
    queries: dict[str, dict[str, Any]] = {}
    problems: list[tuple[Path, str]] = []
    for skill_name in sorted(skill_names):
        path = plugin_dir / "skills" / skill_name / "eval_queries.json"
        if not path.is_file():
            continue
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append((path, f"cannot be read as JSON ({exc})"))
            continue
        rows = loaded.get("queries") if isinstance(loaded, dict) else None
        if not isinstance(rows, list):
            problems.append((path, "must be a JSON object with a `queries` list"))
            continue
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                queries.setdefault(row["id"], row)
    return queries, problems


def check_layout(context: Context, evals_dir: Path) -> None:
    for entry in sorted(evals_dir.iterdir()):
        if entry.name.startswith(".") or entry.name in eval_suite.NON_CASE_DIRS:
            continue
        if entry.is_file():
            if entry.name != "README.md":
                context.add(entry, "is not a case; the only file allowed beside the case directories is README.md")
        elif not (entry / "prompt.md").is_file():
            context.add(entry, "is not a case (no prompt.md); remove it or add a prompt.md")
    for case_dir in sorted(entry for entry in evals_dir.iterdir() if entry.is_dir() and (entry / "prompt.md").is_file()):
        for entry in sorted(case_dir.iterdir()):
            if entry.name == "prompt.md" or (entry.name == "graders" and entry.is_dir()):
                continue
            hint = "; write prompt.md and graders/*.md instead" if entry.name == "case.yaml" else ""
            context.add(entry, f"is not part of the case layout (prompt.md and graders/*.md){hint}")
        graders_dir = case_dir / "graders"
        if graders_dir.is_dir():
            for entry in sorted(graders_dir.iterdir()):
                if entry.suffix != ".md" or not entry.is_file():
                    context.add(entry, "must be a grader file ending in .md")


def check_case(context: Context, case: Case) -> None:
    prompt_file = case.path / "prompt.md"
    for problem in case.problems:
        context.add(prompt_file, problem)
    if not CASE_NAME_RE.fullmatch(case.name):
        context.add(case.path, "case directory names are lowercase kebab-case")
    if not case.problems:
        check_prompt_meta(context, case, prompt_file)
    if not case.prompt:
        context.add(prompt_file, "the prompt body is empty")
    elif len(case.prompt) > PROMPT_MAX_CHARS:
        context.add(prompt_file, f"the prompt body is longer than {PROMPT_MAX_CHARS} characters")
    if not case.graders:
        context.add(case.path / "graders", "has no graders")
    for grader in case.graders:
        check_grader(context, case, grader)
    check_grader_set(context, case)


def check_prompt_meta(context: Context, case: Case, prompt_file: Path) -> None:
    meta = case.meta
    for key in meta:
        if key in eval_suite.PROMPT_KEYS:
            continue
        if key in eval_suite.NATIVE_PROMPT_KEYS:
            context.add(
                prompt_file,
                f"`{key}` is a valid claude plugin eval key that this repository does not use; "
                "add it to PROMPT_KEYS in scripts/eval_suite.py if a case needs it",
            )
        else:
            context.add(prompt_file, f"unknown key `{key}`; claude plugin eval rejects it")

    description = meta.get("description")
    if not isinstance(description, str) or not description.strip():
        context.add(prompt_file, "`description` is required")

    check_tags(context, case, prompt_file)
    if case.name.startswith("trigger-") and "trigger" not in case.tags:
        context.add(prompt_file, "a case named trigger-... must carry the `trigger` tag, which switches on the trigger-probe rules")

    model = meta.get("model")
    if not isinstance(model, str) or not MODEL_RE.fullmatch(model):
        context.add(prompt_file, "`model` must be a full model ID, not a family alias")
    check_int(context, prompt_file, meta, "runs", RUNS_RANGE)
    turns = check_int(context, prompt_file, meta, "max_turns", MAX_TURNS_RANGE)
    check_int(context, prompt_file, meta, "timeout_seconds", TIMEOUT_RANGE)
    check_tools(context, case, prompt_file)

    if "trigger" in case.tags and turns is not None and turns > TRIGGER_MAX_TURNS:
        context.add(prompt_file, f"a trigger probe needs `max_turns` of at most {TRIGGER_MAX_TURNS}")


def check_int(context: Context, path: Path, meta: dict[str, Any], key: str, bounds: tuple[int, int]) -> int | None:
    value = meta.get(key)
    low, high = bounds
    # bool is a subclass of int, and `runs: true` must not pass.
    if type(value) is not int:
        context.add(path, f"`{key}` must be an integer")
        return None
    if not low <= value <= high:
        context.add(path, f"`{key}` must be between {low} and {high}")
    return value


def check_tags(context: Context, case: Case, prompt_file: Path) -> None:
    tags = case.meta.get("tags")
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        context.add(prompt_file, "`tags` must be a list of strings")
        return
    for tag in tags:
        if not CASE_NAME_RE.fullmatch(tag):
            context.add(prompt_file, f"tag `{tag}` must be lowercase kebab-case")
    if len(set(tags)) != len(tags):
        context.add(prompt_file, "`tags` lists a tag twice")
    if case.suite is None:
        context.add(prompt_file, f"`tags` must include exactly one of {', '.join(eval_suite.SUITE_TAGS)}")
    if case.kind is None:
        context.add(prompt_file, f"`tags` must include exactly one of {', '.join(eval_suite.KIND_TAGS)}")


def string_list(context: Context, path: Path, meta: dict[str, Any], key: str, required: bool) -> list[str] | None:
    value = meta.get(key)
    if value is None and not required:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        context.add(path, f"`{key}` must be a list of tool names")
        return None
    return value


def check_tools(context: Context, case: Case, prompt_file: Path) -> None:
    allowed = string_list(context, prompt_file, case.meta, "allowed_tools", required=True)
    disallowed = string_list(context, prompt_file, case.meta, "disallowed_tools", required=False)
    if allowed is None or disallowed is None:
        return
    unknown = sorted(set(allowed) - set(ALLOWED_TOOLS))
    if unknown:
        context.add(
            prompt_file,
            f"`allowed_tools` may only list {', '.join(ALLOWED_TOOLS)}; found {', '.join(unknown)}. "
            "No case grants Bash or network tools",
        )
    if "Skill" not in allowed:
        context.add(prompt_file, "`allowed_tools` must include Skill so the skill can fire")
    authoring = case.suite == "authoring"
    if authoring and "Write" not in allowed:
        context.add(prompt_file, "an authoring case must list Write in `allowed_tools`")
    if case.suite and not authoring:
        if "Write" in allowed:
            context.add(prompt_file, "only authoring cases may list Write in `allowed_tools`")
        if "Write" not in disallowed:
            context.add(prompt_file, "a case that does not author files must list Write in `disallowed_tools`")
    overlap = sorted(set(allowed) & set(disallowed))
    if overlap:
        context.add(prompt_file, f"`allowed_tools` and `disallowed_tools` both list {', '.join(overlap)}")


def check_grader(context: Context, case: Case, grader: Grader) -> None:
    if grader.problem:
        context.add(grader.path, grader.problem)
        return
    meta = grader.meta
    gtype = grader.type
    if gtype not in GRADER_TYPES:
        context.add(grader.path, f"`type` must be one of {', '.join(GRADER_TYPES)}")
        return
    for key in meta:
        if key not in COMMON_GRADER_KEYS | GRADER_KEYS[gtype]:
            context.add(grader.path, f"`{key}` is not a valid key for a {gtype} grader")

    if not GRADER_NAME_RE.fullmatch(grader.name):
        context.add(grader.path, "grader file names are lowercase kebab-case with an optional `advisory-` prefix")
    base = grader.name.removeprefix(eval_suite.ADVISORY_PREFIX)
    if gtype == "llm" and not base.endswith(JUDGED_SUFFIX):
        context.add(grader.path, f"a grader that calls the judge model must be named `...{JUDGED_SUFFIX}`")
    if gtype != "llm" and base.endswith(JUDGED_SUFFIX):
        context.add(grader.path, f"only an llm grader may be named `...{JUDGED_SUFFIX}`")

    weight = meta.get("weight")
    if "weight" in meta and (isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight <= 0):
        context.add(grader.path, "`weight` must be a number greater than 0")
    if meta.get("arm", "with-only") not in ("with-only", "both"):
        context.add(grader.path, "`arm` must be `with-only` or `both`")
    if grader.advisory and gtype not in ADVISORY_TYPES:
        context.add(grader.path, f"only {' and '.join(ADVISORY_TYPES)} graders may be advisory")

    checker = {
        "regex": check_regex_grader,
        "tool_used": check_tool_grader,
        "file_exists": check_file_grader,
        "llm": check_llm_grader,
    }[gtype]
    checker(context, grader)


def relative_path_problem(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return "must be a non-empty path"
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        return "must be a relative path inside the run's working directory"
    return None


def check_regex_grader(context: Context, grader: Grader) -> None:
    meta = grader.meta
    flags = meta.get("flags", "")
    if flags not in ("", "i"):
        context.add(grader.path, "`flags` may only be `i`; inline flags such as (?i) are not supported")
        flags = ""
    pattern = meta.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        context.add(grader.path, "`pattern` is required")
    else:
        register_pattern(context, grader.path, "pattern", pattern, flags)
    if meta.get("match", "contains") not in ("contains", "not_contains"):
        context.add(grader.path, "`match` must be `contains` or `not_contains`")
    target = meta.get("target", "last_message")
    if target == "last_message":
        return
    if isinstance(target, dict) and set(target) == {"source", "path"} and target["source"] == "file":
        problem = relative_path_problem(target["path"])
        if problem:
            context.add(grader.path, f"`target.path` {problem}")
        return
    context.add(grader.path, "`target` must be `last_message` or `{ source: file, path: <file> }`")


def check_tool_grader(context: Context, grader: Grader) -> None:
    meta = grader.meta
    tool = meta.get("tool")
    if tool not in GRADED_TOOLS:
        context.add(grader.path, f"`tool` must be one of {', '.join(GRADED_TOOLS)}")
    input_match = meta.get("input_match")
    if input_match is not None:
        if not isinstance(input_match, str) or not input_match:
            context.add(grader.path, "`input_match` must be a non-empty regex string")
        else:
            register_pattern(context, grader.path, "input_match", input_match, "")
    bounds_ok = True
    for key in ("min", "max"):
        if key in meta and (type(meta[key]) is not int or meta[key] < 0):
            context.add(grader.path, f"`{key}` must be an integer of 0 or more")
            bounds_ok = False
    # The native default for `min` is 1, so a bare `max: 0` could never pass.
    if bounds_ok and "max" in meta and meta["max"] < meta.get("min", 1):
        context.add(grader.path, "can never pass: `min` defaults to 1, so a `max` below 1 needs `min: 0`")
    if bounds_ok and meta.get("min") == 0 and "max" not in meta:
        context.add(grader.path, "can never fail: `min: 0` with no `max` passes whatever the model does")
    if is_forbidden_call(grader) and meta.get("arm") != "both":
        context.add(grader.path, "a grader that forbids a tool call must set `arm: both` so it cannot be demoted to an indicator")


def check_file_grader(context: Context, grader: Grader) -> None:
    problem = relative_path_problem(grader.meta.get("path"))
    if problem:
        context.add(grader.path, f"`path` {problem}")
    if "exists" in grader.meta and not isinstance(grader.meta["exists"], bool):
        context.add(grader.path, "`exists` must be true or false")


def check_llm_grader(context: Context, grader: Grader) -> None:
    body = grader.body
    if not body:
        context.add(grader.path, "the judge criteria (the file body) are empty")
        return
    if len(body) > CRITERIA_MAX_CHARS:
        context.add(grader.path, f"the judge criteria are longer than {CRITERIA_MAX_CHARS} characters; split the check")
    if not re.search(r"^PASS if\b", body, re.MULTILINE) or not re.search(r"^FAIL if\b", body, re.MULTILINE):
        context.add(grader.path, "the judge criteria need a line starting `PASS if` and a line starting `FAIL if`")


def register_pattern(context: Context, path: Path, key: str, pattern: str, flags: str) -> None:
    if NON_JS_REGEX_RE.search(pattern):
        context.add(
            path,
            f"`{key}` uses regex syntax a JavaScript RegExp does not support "
            "(an inline flag group such as (?i), (?P<name>), an atomic group, \\A or \\Z); use `flags: i` for case-insensitive",
        )
        return
    context.patterns.append((context.rel(path), key, pattern, flags))


def check_regexes(context: Context) -> None:
    """Compile every pattern with Node's RegExp, the engine the eval runner uses."""
    if not context.patterns:
        return
    errors: list[str | None] | None = None
    node = shutil.which("node")
    if node is not None:
        payload = json.dumps([[pattern, flags] for _, _, pattern, flags in context.patterns])
        try:
            result = subprocess.run(
                [node, "-e", NODE_REGEX_CHECK],
                input=payload,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            if result.returncode == 0:
                errors = json.loads(result.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            errors = None
    if errors is None:
        # No Node: Python's re module catches unbalanced groups and bad escapes.
        errors = []
        for _, _, pattern, _ in context.patterns:
            try:
                re.compile(JS_NAMED_GROUP_RE.sub(r"(?P<\1>", pattern))
                errors.append(None)
            except re.error as exc:
                errors.append(str(exc))
    for (file, key, pattern, _), error in zip(context.patterns, errors):
        if error:
            context.problems.append((file, f"`{key}` is not a valid regex: {error}"))


def is_forbidden_call(grader: Grader) -> bool:
    """A tool_used grader that passes only when a tool other than Skill is never called."""
    return grader.type == "tool_used" and grader.meta.get("tool") != "Skill" and grader.meta.get("max") == 0


def is_negative(grader: Grader) -> bool:
    return is_forbidden_call(grader) or (grader.type == "regex" and grader.meta.get("match") == "not_contains")


def is_positive(grader: Grader) -> bool:
    if grader.type == "llm":
        return True
    if grader.type == "regex":
        return grader.meta.get("match", "contains") == "contains"
    return grader.type == "file_exists" and grader.meta.get("exists", True) is True


def is_skill_grader(grader: Grader) -> bool:
    return grader.type == "tool_used" and grader.meta.get("tool") == "Skill"


def check_grader_set(context: Context, case: Case) -> None:
    graders = [grader for grader in case.graders if not grader.problem and grader.type in GRADER_TYPES]
    if not graders:
        return
    graders_dir = case.path / "graders"
    if all(grader.advisory for grader in graders):
        context.add(graders_dir, "needs at least one grader that is not advisory, or the case can never fail")

    skill_graders = [grader for grader in graders if is_skill_grader(grader)]
    for grader in skill_graders:
        match = grader.meta.get("input_match")
        if not isinstance(match, str) or not any(name in match for name in context.skill_names):
            context.add(grader.path, "a Skill grader must name the skill in `input_match`, or any skill would satisfy it")

    if "trigger" in case.tags:
        check_trigger_case(context, case, graders, skill_graders)
    else:
        fired = [g for g in skill_graders if g.name == SKILL_FIRED and (min_calls(g) or 0) >= 1]
        if not fired:
            context.add(
                graders_dir,
                f"needs a `{SKILL_FIRED}` tool_used grader for Skill with min 1 or more, "
                "or a pass could come from the model answering without the skill",
            )

    negatives = [grader for grader in graders if is_negative(grader) and not grader.advisory]
    positives = [grader for grader in graders if is_positive(grader) and not grader.advisory]
    if case.kind == "guardrail":
        if not negatives:
            context.add(graders_dir, "a guardrail case needs a grader that fails when the forbidden thing happens (a forbidden-call or not_contains grader)")
        if not positives:
            context.add(graders_dir, "a guardrail case also needs a grader that fails when the refusal never appears, or an empty reply would pass")

    if case.suite == "authoring":
        check_authoring_case(context, case, graders)


def check_trigger_case(context: Context, case: Case, graders: list[Grader], skill_graders: list[Grader]) -> None:
    graders_dir = case.path / "graders"
    prompt_file = case.path / "prompt.md"
    if case.suite != "gate" or case.kind != "capability":
        context.add(prompt_file, "a trigger probe is tagged `gate` and `capability` (recall is a rate, not a guarantee)")
    if not case.name.startswith("trigger-"):
        context.add(case.path, "a case tagged `trigger` must be named trigger-<query id from eval_queries.json>")
        return
    row = context.queries.get(case.name.removeprefix("trigger-"))
    if row is None:
        if not context.queries_unreadable:
            context.add(case.path, "names a query id that is not in the skill's eval_queries.json")
        return
    if case.prompt != str(row.get("query", "")).strip():
        context.add(prompt_file, "the prompt must be the eval_queries.json query verbatim, with nothing added")
    if len(graders) != 1 or len(skill_graders) != 1:
        context.add(graders_dir, "a trigger probe has exactly one grader, the Skill check")
        return
    grader = skill_graders[0]
    if row.get("should_trigger") is True:
        if grader.name != SKILL_FIRED or (min_calls(grader) or 0) < 1:
            context.add(grader.path, f"the query should trigger, so the grader must be `{SKILL_FIRED}` with min 1 or more")
    elif grader.name != SKILL_NOT_FIRED or grader.meta.get("max") != 0 or grader.meta.get("min") != 0:
        context.add(grader.path, f"the query should not trigger, so the grader must be `{SKILL_NOT_FIRED}` with `min: 0` and `max: 0`")


def check_authoring_case(context: Context, case: Case, graders: list[Grader]) -> None:
    graders_dir = case.path / "graders"
    created = {
        str(grader.meta.get("path"))
        for grader in graders
        if grader.type == "file_exists" and grader.meta.get("exists", True) is True
    }
    if not created:
        context.add(graders_dir, "an authoring case needs a file_exists grader for each file it must write")
    # A malformed target is reported by check_regex_grader; only a mapping with a string path says which file is read.
    file_targets = {
        grader.meta["target"]["path"]: grader
        for grader in graders
        if grader.type == "regex"
        and isinstance(grader.meta.get("target"), dict)
        and isinstance(grader.meta["target"].get("path"), str)
    }
    if not file_targets:
        context.add(graders_dir, "an authoring case needs a regex grader that reads a written file")
    for path, grader in sorted(file_targets.items()):
        if path not in created:
            context.add(
                grader.path,
                f"reads `{path}` but no file_exists grader checks that file, so a missing file would read as a regex failure",
            )
    if not any(is_forbidden_call(grader) and grader.meta.get("tool") == "Bash" for grader in graders):
        context.add(graders_dir, "an authoring case needs a grader that forbids Bash (terraform apply or destroy)")


def check_attempt_caps(context: Context, evals_dir: Path, cases: list[Case]) -> None:
    for suite_name, cap in ATTEMPT_CAPS.items():
        attempts = sum(runs_of(case) for case in cases if case.suite == suite_name)
        if attempts > cap:
            context.add(
                evals_dir,
                f"the `{suite_name}` suite makes {attempts} attempts per run; the cap in scripts/validate_evals.py is {cap}. "
                "Raise the cap in the same pull request so the cost change is reviewed",
            )


if __name__ == "__main__":
    raise SystemExit(main())
