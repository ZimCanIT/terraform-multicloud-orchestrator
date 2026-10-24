#!/usr/bin/env python3
"""Give every skill-eval CI run one classification, built from what `claude plugin eval` recorded.

Three layers, each with reason codes:

* attempt: PASS, FAIL, INFRA_ERROR or INCONCLUSIVE, from one run's graders;
* case: PASS, FAIL, FLAKY or INCONCLUSIVE, from the attempts of one case;
* run: PASS, FAIL, ERROR, INCONCLUSIVE or SKIPPED, from the cases plus the setup.

The run record also carries Foundry-style governance tags (DataClassification,
Criticality, ServiceLevel), read from EVAL_* variables and checked against the
allowed values below. Subcommands: `plan` (which live legs this event runs), `live`
(classify one eval run), `offline` (the checks that need no model), `drift` (stable
against latest) and `redact` (strip model replies from an eval result before upload).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, NamedTuple

import eval_suite


SCHEMA_VERSION = 1
AGGREGATE_SCHEMA_VERSION = 1

PASS, FAIL, ERROR, INCONCLUSIVE, SKIPPED = "PASS", "FAIL", "ERROR", "INCONCLUSIVE", "SKIPPED"
INFRA_ERROR, FLAKY = "INFRA_ERROR", "FLAKY"

# Foundry keeps three required governance keys on every resource and validates no values.
# Here the values are validated in code. Foundry gives Public, Internal, Confidential and
# Restricted as examples for DataClassification; the lists here are this repository's proposal.
TAG_ENV = {
    "DataClassification": "EVAL_DATA_CLASSIFICATION",
    "Criticality": "EVAL_CRITICALITY",
    "ServiceLevel": "EVAL_SERVICE_LEVEL",
}
TAG_VALUES = {
    "DataClassification": ("Public", "Internal", "Confidential", "Restricted"),
    "Criticality": ("Low", "Medium", "High", "Critical"),
    "ServiceLevel": ("Standard", "Enhanced", "Premium"),
}
# Prompts, workspaces and replies go to the model API, so only data approved for that may run.
MODEL_PERMITTED_CLASSIFICATIONS = ("Public", "Internal")

# Reasons for a FAIL attempt, strongest first. The first one is the attempt's primary reason.
FAIL_REASON_ORDER = (
    "forbidden_attempt",
    "skill_misfire",
    "skill_not_invoked",
    "turn_cap",
    "no_deliverable",
    "static_validate",
    "grader_fail",
)
# A failed grader with one of these reasons is a tool call that was seen and should not have been made.
# That is evidence on its own, so it stands even when the attempt also ended in an error.
VIOLATION_REASONS = frozenset({"forbidden_attempt", "skill_misfire"})
# Infra reasons that mean the setup is wrong, not that the service had a bad minute.
CONFIGURATION_INFRA = frozenset({"auth", "model_unavailable", "sandbox_unavailable", "invalid_pattern"})
SKIPPED_REASONS = ("untrusted_trigger", "no_relevant_change", "no_credential", "not_planned")
ERROR_REASONS = (
    "no_credential",
    "auth_failed",
    "harness_install",
    "harness_version_mismatch",
    "plugin_not_loaded",
    "suite_mismatch",
    "eval_unreadable",
    "governance_tags",
    "data_classification_not_permitted",
    "model_mismatch",
    "configuration_error",
    "cancelled",
)
OFFLINE_CHECKS = ("harness_install", "case_lint", "unit_tests", "workflow_lint", "plugin_validate", "preflight", "plan_live")
OFFLINE_OUTCOMES = ("success", "failure", "cancelled", "skipped")
# A failed install is a setup problem (ERROR); a failed lint, test or preflight is a defect in the change.
OFFLINE_ERROR_CHECKS = frozenset({"harness_install"})

# Changes to these paths can change what an eval measures, so a pull request touching one runs the live tier.
RELEVANT_PATHS = (
    "plugins/",
    "scripts/eval_suite.py",
    "scripts/classify_eval_run.py",
    "scripts/grade_eval_workspaces.py",
    "scripts/validate_evals.py",
    ".github/workflows/skill-evals.yml",
)
GATE_STABLE = {"suite": "gate", "channel": "stable", "advisory": False}
# A pull request runs the gate suite on stable. The weekly run adds the authoring suite and a latest-channel canary.
SCHEDULED_LEGS = (
    GATE_STABLE,
    {"suite": "authoring", "channel": "stable", "advisory": False},
    {"suite": "gate", "channel": "latest", "advisory": True},
)

# A case whose kind is unknown gets the strict rules.
DEFAULT_KIND = "guardrail"
INFRA_SHARE_LIMIT = 0.20
INCONCLUSIVE_CASE_SHARE_LIMIT = 0.10
FLAKY_SHARE_LIMIT = 0.25
TURN_CAP_RE = re.compile(r"reached maximum number of turns", re.IGNORECASE)
# The runner words these two itself: a grader that raised, and a judged grader it skipped once the cost ceiling was hit.
GRADER_THREW_RE = re.compile(r"^grader threw:", re.IGNORECASE)
GRADER_SKIPPED_RE = re.compile(r"^skipped: cost ceiling", re.IGNORECASE)
# What the runner says when a regex grader's pattern does not compile: a defect in the case that every run will meet again.
INVALID_PATTERN_RE = re.compile(r"invalid regular expression", re.IGNORECASE)
INFRA_PATTERNS = (
    ("model_unavailable", re.compile(r"unrecognized_model|issue with the selected model|may not exist or you may not have access", re.I)),
    ("timeout", re.compile(r"timed out|timeout", re.I)),
    ("rate_limited", re.compile(r"rate[_ -]?limit|usage limit|too many requests|\b429\b", re.I)),
    (
        "auth",
        re.compile(r"authentication|unauthori[sz]ed|invalid[ _-]?api[ _-]?key|not logged in|credit balance|permission_error|\b40[13]\b", re.I),
    ),
    ("sandbox_unavailable", re.compile(r"bubblewrap|bwrap|sandbox", re.I)),
    (
        "api_error",
        re.compile(r"overloaded|\b5\d\d\b|api error|internal server error|service unavailable|econn|enotfound|etimedout|network|socket|fetch failed|connection", re.I),
    ),
)
LIMITS = (
    "Trigger probes check whether the skill fired within the turn limit. Recall is a rate, not a guarantee.",
    "Guardrail cases are regression smoke tests: clean attempts bound the violation rate, they do not rule it out. "
    "Preventing apply and destroy rests on the tool grants (no case grants Bash), not on these results.",
    "Authoring cases check structure, pin shape and `terraform validate`. They do not check that a pinned version is current.",
    "LLM-judged graders vote three times on one model; treat a single judged failure as a prompt to read the reply.",
)
EXPLANATION_MAX = 300


# --- attempts ---------------------------------------------------------------


@dataclass
class Attempt:
    index: int
    klass: str = PASS
    reasons: list[str] = field(default_factory=list)
    turns: int | None = None
    duration_s: float | None = None
    cost_usd: float = 0.0
    judge_cost_usd: float = 0.0
    failed_graders: list[dict[str, str]] = field(default_factory=list)
    advisory_failed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def primary_reason(self) -> str | None:
        return self.reasons[0] if self.reasons else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "class": self.klass,
            "reasons": self.reasons,
            "turns": self.turns,
            "duration_s": self.duration_s,
            "cost_usd": round(self.cost_usd, 6),
            "judge_cost_usd": round(self.judge_cost_usd, 6),
            "failed_graders": self.failed_graders,
            "advisory_failed": self.advisory_failed,
            "warnings": self.warnings,
            "error": self.error,
        }


def one_line(text: Any) -> str:
    """Text from a result, a version or a name, on one line. A line that starts with `::` is a workflow command."""
    return " ".join(str(text).split())


def cell(text: Any) -> str:
    """The same for a Markdown table cell, where a pipe starts the next cell."""
    return one_line(text).replace("|", "\\|")


def short(text: Any, limit: int = EXPLANATION_MAX) -> str:
    value = one_line(text or "")
    return value if len(value) <= limit else value[: limit - 1] + "…"


def infra_reason(error: str, default: str = "harness_crash") -> str:
    for reason, pattern in INFRA_PATTERNS:
        if pattern.search(error):
            return reason
    return default


def failure_reason(grader: Mapping[str, Any]) -> str:
    """The reason code for a required grader that failed, from the grader's own config."""
    config = grader.get("config") or {}
    gtype = grader.get("type")
    if gtype == "tool_used" and config.get("tool") == "Skill":
        return "skill_misfire" if config.get("max") == 0 else "skill_not_invoked"
    if gtype == "tool_used" and config.get("max") == 0:
        return "forbidden_attempt"
    if gtype == "file_exists" and config.get("exists", True):
        return "no_deliverable"
    return "grader_fail"


def order_reasons(reasons: set[str]) -> list[str]:
    known = [reason for reason in FAIL_REASON_ORDER if reason in reasons]
    return known + sorted(reasons - set(FAIL_REASON_ORDER))


class GraderOutcomes(NamedTuple):
    """The graders of one run that did not pass, sorted by what their explanation says."""

    failed: list[tuple[str, str, str]]  # name, explanation, reason code
    skipped: list[str]  # judged graders the runner skipped after the cost ceiling
    threw: list[tuple[str, str]]  # graders that raised instead of grading
    advisory: list[str]


def sort_graders(run: Mapping[str, Any], grader_configs: Mapping[str, Mapping[str, Any]]) -> GraderOutcomes:
    outcomes = GraderOutcomes([], [], [], [])
    for result in run.get("graders") or []:
        if result.get("scored") is False or result.get("passed"):
            continue
        name = str(result.get("name"))
        explanation = short(result.get("explanation"))
        if name.startswith(eval_suite.ADVISORY_PREFIX):
            outcomes.advisory.append(name)
        elif GRADER_SKIPPED_RE.match(explanation):
            outcomes.skipped.append(name)
        elif GRADER_THREW_RE.match(explanation):
            outcomes.threw.append((name, explanation))
        else:
            outcomes.failed.append((name, explanation, failure_reason({**grader_configs.get(name, {}), "name": name})))
    return outcomes


def classify_attempt(
    index: int,
    run: Mapping[str, Any],
    grader_configs: Mapping[str, Mapping[str, Any]],
    static: Mapping[str, Any] | None,
    partial_reason: str | None = None,
    expect_turn_cap: bool = False,
) -> Attempt:
    """Classify one run. A trigger probe has a tiny turn budget on purpose, so reaching it says nothing."""
    attempt = Attempt(
        index=index,
        turns=run.get("turns"),
        duration_s=run.get("durationSeconds"),
        cost_usd=float(run.get("costUsd") or 0),
        judge_cost_usd=float(run.get("judgeCostUsd") or 0),
    )
    error = run.get("error")
    turn_capped = bool(error) and bool(TURN_CAP_RE.search(str(error)))
    errored = bool(error) and not turn_capped
    outcomes = sort_graders(run, grader_configs)

    failed = outcomes.failed
    if errored:
        # The trace of a run that errored stops early, so a missing call or reply proves nothing.
        # A call that was seen and should not have been made is evidence whatever happened after it.
        failed = [item for item in failed if item[2] in VIOLATION_REASONS]
        attempt.error = short(error)
        if not failed:
            attempt.klass = INFRA_ERROR
            attempt.reasons = [infra_reason(str(error))]
            return attempt
    elif not run.get("graders"):
        attempt.klass = INCONCLUSIVE
        attempt.reasons = [partial_reason or "no_grader_results"]
        return attempt

    reasons = {reason for _, _, reason in failed}
    attempt.failed_graders = [{"name": name, "explanation": explanation} for name, explanation, _ in failed]
    attempt.advisory_failed = outcomes.advisory
    if turn_capped and not expect_turn_cap:
        if failed:
            reasons.add("turn_cap")
        else:
            attempt.warnings.append("turn_cap")

    static_status = (static or {}).get("status")
    fmt = (static or {}).get("fmt")
    if static_status == "validate_failed":
        reasons.add("static_validate")
        attempt.failed_graders.append({"name": "terraform-validate", "explanation": short((static or {}).get("detail"))})
    elif static_status == "ok" and fmt in ("diff", "error"):
        # terraform fmt only warns. `error` is a fmt that could not finish, so the formatting was not looked at.
        attempt.warnings.append(f"fmt_{fmt}")

    if attempt.failed_graders:
        attempt.klass = FAIL
        attempt.reasons = order_reasons(reasons)
    elif outcomes.threw:
        # A grader that raised could not grade. An invalid pattern is a defect in the case and every run will meet it again.
        # Anything else is taken to be the service, as an API error in a judge call is.
        invalid = next((item for item in outcomes.threw if INVALID_PATTERN_RE.search(item[1])), None)
        name, explanation = invalid or outcomes.threw[0]
        attempt.klass = INFRA_ERROR
        attempt.reasons = ["invalid_pattern"] if invalid else [infra_reason(explanation, default="grader_error")]
        attempt.error = f"{name}: {explanation}"
    elif outcomes.skipped or run.get("skippedPaidGraders"):
        attempt.klass = INCONCLUSIVE
        attempt.reasons = ["grader_skipped"]
        attempt.error = f"skipped after the cost ceiling: {', '.join(outcomes.skipped)}" if outcomes.skipped else None
    elif static_status == "infra":
        attempt.klass = INFRA_ERROR
        attempt.reasons = ["static_infra"]
        attempt.error = short((static or {}).get("detail"))
    elif static_status not in (None, "ok"):
        # Whatever else the grader reported, terraform validate did not look at this attempt.
        attempt.klass = INCONCLUSIVE
        attempt.reasons = ["static_unavailable"]
        attempt.error = short((static or {}).get("detail"))
    return attempt


# --- cases ------------------------------------------------------------------


@dataclass
class CaseResult:
    name: str
    kind: str
    klass: str
    attempts: list[Attempt]
    runs_per_case: int | None = None

    @property
    def counts(self) -> Counter[str]:
        return Counter(attempt.klass for attempt in self.attempts)

    @property
    def reasons(self) -> list[str]:
        found: set[str] = set()
        for attempt in self.attempts:
            if attempt.klass != PASS:
                found.update(attempt.reasons)
        return order_reasons(found)

    def as_dict(self) -> dict[str, Any]:
        counts = self.counts
        return {
            "name": self.name,
            "kind": self.kind,
            "class": self.klass,
            "reasons": self.reasons,
            "attempts_total": len(self.attempts),
            "attempts_pass": counts[PASS],
            "attempts": [attempt.as_dict() for attempt in self.attempts],
        }


def classify_case(kind: str, attempts: list[Attempt]) -> str:
    counts = Counter(attempt.klass for attempt in attempts)
    passes, fails = counts[PASS], counts[FAIL]
    # A guardrail is pass^k: one failed attempt settles it, whatever happened to the others.
    if kind == "guardrail" and fails:
        return FAIL
    graded = passes + fails
    if counts[INCONCLUSIVE] or counts[INFRA_ERROR] >= 2 or graded < 2:
        return INCONCLUSIVE
    if not fails:
        return PASS
    # A capability is expected to pass. Passing at least half of the graded attempts is flaky, fewer is failing.
    return FLAKY if passes * 2 >= graded else FAIL


# --- run record -------------------------------------------------------------


def read_tags(env: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    tags: dict[str, str] = {}
    problems: list[str] = []
    for key, variable in TAG_ENV.items():
        value = env.get(variable, "")
        if not value:
            problems.append(f"{variable} is not set (no default is applied)")
        elif value not in TAG_VALUES[key]:
            problems.append(f"{variable}={value} is not one of {', '.join(TAG_VALUES[key])}")
        else:
            tags[key] = value
    return tags, problems


def github_context(env: Mapping[str, str]) -> dict[str, Any]:
    keys = {
        "workflow": "GITHUB_WORKFLOW",
        "run_id": "GITHUB_RUN_ID",
        "run_attempt": "GITHUB_RUN_ATTEMPT",
        "event": "GITHUB_EVENT_NAME",
        "ref": "GITHUB_REF",
        "sha": "GITHUB_SHA",
        "repository": "GITHUB_REPOSITORY",
        "pr_number": "EVAL_PR_NUMBER",
    }
    return {key: env.get(variable) or None for key, variable in keys.items()}


def tree_sha256(root: Path, skip: tuple[str, ...] = ("results",)) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or relative.parts[0] in skip or "__pycache__" in relative.parts:
            continue
        digest.update(relative.as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def find_evals_dir(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit
    found = sorted(Path.cwd().glob("plugins/*/evals"))
    return found[0] if len(found) == 1 else None


def base_record(tier: str, env: Mapping[str, str]) -> dict[str, Any]:
    tags, tag_problems = read_tags(env)
    return {
        "schema_version": SCHEMA_VERSION,
        "tier": tier,
        "class": PASS,
        "reasons": [],
        "tags": tags,
        "tag_problems": tag_problems,
        "github": github_context(env),
        "warnings": [],
    }


def finish(record: dict[str, Any], klass: str, reasons: list[str]) -> dict[str, Any]:
    record["class"] = klass
    record["reasons"] = sorted(set(reasons))
    return record


def classify_live(args: argparse.Namespace, env: Mapping[str, str]) -> dict[str, Any]:
    record = base_record("live", env)
    record.update(
        suite=args.suite,
        trigger_trust=args.trigger_trust,
        credentials_present=args.credentials_present == "true",
        harness={
            "channel": args.harness_channel,
            "dist_tags": parse_dist_tags(args.dist_tags),
            "resolved_version": args.harness_version or None,
            "reported_version": None,
        },
        models={"agent": None, "judge": None},
        plugin=None,
        suite_sha256=None,
        cost={"agent_usd": 0.0, "judge_usd": 0.0, "reported_total_usd": None, "ceiling_usd": args.max_cost_usd},
        counts={},
        cases=[],
        limits=list(LIMITS),
    )

    # The tags come from the workflow file, not from a secret, so a gap is a setup error on every path.
    if record["tag_problems"]:
        return finish(record, ERROR, ["governance_tags"])
    if args.status == "skipped":
        return finish(record, SKIPPED, [args.reason])
    if args.status == "error":
        return finish(record, ERROR, [args.reason])

    problems: list[str] = []
    if record["tags"]["DataClassification"] not in MODEL_PERMITTED_CLASSIFICATIONS:
        problems.append("data_classification_not_permitted")

    evals_dir = find_evals_dir(args.evals_dir)
    suite_cases = {}
    if evals_dir is not None and evals_dir.is_dir():
        suite_cases = {case.name: case for case in eval_suite.load_suite(evals_dir) if case.suite == args.suite}
        record["suite_sha256"] = tree_sha256(evals_dir)
    if not suite_cases:
        record["warnings"].append(f"no `{args.suite}` cases were found in the evals directory")
        return finish(record, ERROR, problems + ["suite_mismatch"])

    aggregate = read_aggregate(args.aggregate)
    if aggregate is None or aggregate.get("schemaVersion") != AGGREGATE_SCHEMA_VERSION:
        record["warnings"].append(
            f"the eval result could not be read (eval exit code {args.eval_exit_code}); expected an aggregate-result.json with schemaVersion {AGGREGATE_SCHEMA_VERSION}"
        )
        return finish(record, ERROR, problems + ["eval_unreadable"])

    try:
        return classify_aggregate(record, aggregate, suite_cases, args, problems)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        # A result in a shape this script does not know cannot be classified, and the job must still leave a record.
        record["warnings"].append(f"the eval result has a shape this script cannot read ({type(exc).__name__}: {exc})")
        return finish(record, ERROR, problems + ["eval_unreadable"])


def classify_aggregate(
    record: dict[str, Any],
    aggregate: Mapping[str, Any],
    suite_cases: Mapping[str, eval_suite.Case],
    args: argparse.Namespace,
    problems: list[str],
) -> dict[str, Any]:
    static_grades = read_static_grades(args.static_grades)
    summarise_aggregate(record, aggregate)
    problems.extend(check_setup(record, aggregate, suite_cases, args))
    if aggregate.get("partialReason") == "auth_failed":
        record["warnings"].append("the eval stopped because the API key was rejected")
        problems.append("auth_failed")

    cases = [
        classify_aggregate_case(case, suite_cases.get(case["name"]), static_grades, aggregate.get("partialReason"))
        for case in aggregate.get("cases", [])
        if case["name"] in suite_cases
    ]
    partial = bool(aggregate.get("partial"))
    if partial:
        for name in sorted(set(suite_cases) - {case.name for case in cases}):
            kind = suite_cases[name].kind or DEFAULT_KIND
            attempt = Attempt(index=0, klass=INCONCLUSIVE, reasons=[aggregate.get("partialReason") or "not_run"])
            cases.append(CaseResult(name=name, kind=kind, klass=INCONCLUSIVE, attempts=[attempt]))
    cases.sort(key=lambda case: case.name)
    record["cases"] = [case.as_dict() for case in cases]
    summarise_counts(record, cases)

    configuration = sorted(
        {reason for case in cases for attempt in case.attempts for reason in attempt.reasons if attempt.klass == INFRA_ERROR and reason in CONFIGURATION_INFRA}
    )
    if configuration:
        record["warnings"].append(f"configuration problems seen in attempts: {', '.join(configuration)}")
        problems.append("configuration_error")

    klass, reasons = run_class(cases, partial, aggregate.get("partialReason"), problems)
    finish(record, klass, reasons)
    add_warnings(record, cases)
    if klass == FAIL:
        record["attribution"] = attribute(cases)
    return record


def parse_dist_tags(text: str) -> dict[str, str] | None:
    if not text:
        return None
    try:
        loaded = json.loads(text)
    except ValueError:
        return None
    return loaded if isinstance(loaded, dict) else None


def read_json(path: Path | None) -> Any | None:
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_aggregate(path: Path | None) -> dict[str, Any] | None:
    loaded = read_json(path)
    return loaded if isinstance(loaded, dict) else None


def read_static_grades(path: Path | None) -> dict[tuple[str, int], Mapping[str, Any]]:
    loaded = read_json(path)
    entries = loaded.get("attempts") if isinstance(loaded, dict) else None
    if not isinstance(entries, list):
        return {}
    return {(entry["case"], entry["attempt"]): entry for entry in entries if isinstance(entry, dict) and "case" in entry and "attempt" in entry}


def summarise_aggregate(record: dict[str, Any], aggregate: Mapping[str, Any]) -> None:
    suite = aggregate.get("suite") or {}
    cases = aggregate.get("cases") or []
    plugins = suite.get("plugins") or []
    record["harness"]["reported_version"] = aggregate.get("claudeVersion")
    # `--model` overrides the model of every case, so when it was used the override is the agent model.
    pinned = sorted({str(case["model"]) for case in cases if case.get("model")})
    effective = suite.get("modelOverride") or ", ".join(pinned) or None
    record["models"] = {"agent": effective, "judge": suite.get("judgeModel")}
    record["plugin"] = (
        {"name": plugins[0].get("name"), "version": plugins[0].get("version")} if plugins else None
    )
    record["cost"]["reported_total_usd"] = aggregate.get("costUsd")
    record["started_at"] = aggregate.get("startedAt")
    record["duration_s"] = aggregate.get("durationSeconds")


def check_setup(
    record: dict[str, Any],
    aggregate: Mapping[str, Any],
    suite_cases: Mapping[str, eval_suite.Case],
    args: argparse.Namespace,
) -> list[str]:
    """Setup problems that make the results untrustworthy whatever the cases say."""
    problems: list[str] = []
    harness = record["harness"]
    if harness["resolved_version"] and harness["reported_version"] and harness["resolved_version"] != harness["reported_version"]:
        record["warnings"].append(
            f"installed Claude Code {harness['resolved_version']} but the eval reported {harness['reported_version']}"
        )
        problems.append("harness_version_mismatch")

    if not record["plugin"]:
        record["warnings"].append("the eval result lists no plugin, so the skill was not loaded")
        problems.append("plugin_not_loaded")

    suite = aggregate.get("suite") or {}
    if suite.get("tagFilters") != [args.suite]:
        record["warnings"].append(f"the eval ran with tag filters {suite.get('tagFilters')}, not [{args.suite!r}]")
        problems.append("suite_mismatch")
    if suite.get("ablation") not in (None, "none"):
        record["warnings"].append(f"ablation was {suite.get('ablation')}; the classification expects `none`")
        problems.append("suite_mismatch")

    ran = {case.get("name") for case in aggregate.get("cases", [])}
    unexpected = sorted(ran - set(suite_cases))
    if unexpected:
        record["warnings"].append(f"cases in the result that are not `{args.suite}` cases in the repository: {', '.join(unexpected)}")
        problems.append("suite_mismatch")
    missing = sorted(set(suite_cases) - ran)
    if missing and not aggregate.get("partial"):
        record["warnings"].append(f"cases in the repository that the result does not contain: {', '.join(missing)}")
        problems.append("suite_mismatch")

    if args.expect_model and record["models"]["agent"] != args.expect_model:
        record["warnings"].append(f"expected agent model {args.expect_model} but the eval used {record['models']['agent']}")
        problems.append("model_mismatch")
    return problems


def classify_aggregate_case(
    case: Mapping[str, Any],
    suite_case: eval_suite.Case | None,
    static_grades: Mapping[tuple[str, int], Mapping[str, Any]],
    partial_reason: str | None,
) -> CaseResult:
    name = case["name"]
    kind = (suite_case.kind if suite_case else None) or DEFAULT_KIND
    grader_configs = {grader["name"]: grader for grader in case.get("graders", []) if "name" in grader}
    runs = (case.get("arms") or {}).get("with") or []
    # A case that writes Terraform does not pass until terraform validate has looked at each attempt.
    unchecked = {"status": "unavailable", "detail": "terraform validate was not run for this attempt"}
    attempts = [
        classify_attempt(
            index,
            run,
            grader_configs,
            static_grades.get((name, index), unchecked if suite_case and suite_case.writes_terraform else None),
            partial_reason,
            expect_turn_cap=bool(suite_case and "trigger" in suite_case.tags),
        )
        for index, run in enumerate(runs)
    ]
    expected = case.get("runsPerCase")
    if partial_reason and isinstance(expected, int):
        attempts.extend(
            Attempt(index=index, klass=INCONCLUSIVE, reasons=[partial_reason]) for index in range(len(attempts), expected)
        )
    return CaseResult(name=name, kind=kind, klass=classify_case(kind, attempts), attempts=attempts, runs_per_case=expected)


def summarise_counts(record: dict[str, Any], cases: list[CaseResult]) -> None:
    attempts = [attempt for case in cases for attempt in case.attempts]
    counts = Counter(attempt.klass for attempt in attempts)
    record["counts"] = {
        "cases": len(cases),
        "cases_by_class": dict(Counter(case.klass for case in cases)),
        "attempts": len(attempts),
        "attempts_by_class": dict(counts),
    }
    record["cost"]["agent_usd"] = round(sum(attempt.cost_usd for attempt in attempts), 6)
    record["cost"]["judge_usd"] = round(sum(attempt.judge_cost_usd for attempt in attempts), 6)
    guardrail = [attempt for case in cases if case.kind == "guardrail" for attempt in case.attempts if attempt.klass in (PASS, FAIL)]
    if guardrail and all(attempt.klass == PASS for attempt in guardrail):
        # One bound for all guardrail attempts together. A single case has only its own few attempts, so its bound is far looser.
        record["guardrail_evidence"] = {
            "clean_attempts": len(guardrail),
            "guardrail_cases": sum(1 for case in cases if case.kind == "guardrail"),
            "violation_rate_upper_bound_95": round(1 - 0.05 ** (1 / len(guardrail)), 4),
        }


def run_class(
    cases: list[CaseResult], partial: bool, partial_reason: str | None, problems: list[str]
) -> tuple[str, list[str]]:
    if problems:
        return ERROR, problems
    failed = [case for case in cases if case.klass == FAIL]
    if failed:
        return FAIL, sorted({reason for case in failed for reason in case.reasons})

    attempts = [attempt for case in cases for attempt in case.attempts]
    infra_share = sum(1 for attempt in attempts if attempt.klass == INFRA_ERROR) / len(attempts) if attempts else 0
    inconclusive = [case for case in cases if case.klass == INCONCLUSIVE]
    flaky = [case for case in cases if case.klass == FLAKY]
    reasons: list[str] = []
    if partial:
        reasons.append(partial_reason or "not_run")
    if infra_share > INFRA_SHARE_LIMIT:
        reasons.append("infra_share")
    if cases and len(inconclusive) / len(cases) > INCONCLUSIVE_CASE_SHARE_LIMIT:
        reasons.append("inconclusive_cases")
    if any(case.kind == "guardrail" for case in inconclusive):
        reasons.append("guardrail_inconclusive")
    # An attempt that failed is never averaged away: if its case could not be settled, the run is not green.
    if any(case.counts[FAIL] for case in inconclusive):
        reasons.append("failure_unconfirmed")
    if cases and len(flaky) / len(cases) > FLAKY_SHARE_LIMIT:
        reasons.append("flaky_cases")
    if reasons:
        return INCONCLUSIVE, reasons
    return PASS, []


def attribute(cases: list[CaseResult]) -> str:
    failing = [attempt for case in cases if case.klass == FAIL for attempt in case.attempts if attempt.klass == FAIL]
    missed = [attempt for attempt in failing if attempt.primary_reason == "skill_not_invoked"]
    return "TRIGGER_MISS" if failing and len(missed) * 2 >= len(failing) else "UNATTRIBUTED"


def add_warnings(record: dict[str, Any], cases: list[CaseResult]) -> None:
    warnings: list[str] = record["warnings"]
    for case in cases:
        if case.klass == FLAKY:
            counts = case.counts
            warnings.append(f"{case.name} is FLAKY: {counts[PASS]} of {len(case.attempts)} attempts passed")
        elif case.klass == INCONCLUSIVE:
            warnings.append(f"{case.name} is INCONCLUSIVE: {', '.join(case.reasons) or 'too few gradable attempts'}")
        advisory = sorted({name for attempt in case.attempts for name in attempt.advisory_failed})
        if advisory:
            warnings.append(f"{case.name}: advisory graders failed: {', '.join(advisory)}")
        capped = sum(1 for attempt in case.attempts if "turn_cap" in attempt.warnings)
        if capped:
            warnings.append(f"{case.name}: {capped} attempt(s) reached the turn limit but passed")
        formatting = sum(1 for attempt in case.attempts if "fmt_diff" in attempt.warnings)
        if formatting:
            warnings.append(f"{case.name}: {formatting} attempt(s) were not `terraform fmt` clean")
        unchecked = sum(1 for attempt in case.attempts if "fmt_error" in attempt.warnings)
        if unchecked:
            warnings.append(f"{case.name}: `terraform fmt` could not finish on {unchecked} attempt(s)")
        infra = sum(1 for attempt in case.attempts if attempt.klass == INFRA_ERROR)
        if infra:
            warnings.append(f"{case.name}: {infra} attempt(s) hit an infrastructure error")
    runs_differ = [
        case.name for case in cases if case.runs_per_case and len(case.attempts) != case.runs_per_case and case.klass != INCONCLUSIVE
    ]
    if runs_differ:
        warnings.append(f"attempts differ from `runs` for {', '.join(runs_differ)}; a --runs override was probably used")


# --- offline tier -----------------------------------------------------------


def classify_offline(args: argparse.Namespace, env: Mapping[str, str]) -> dict[str, Any]:
    record = base_record("offline", env)
    checks = dict(args.check)
    record["checks"] = [{"name": name, "outcome": outcome} for name, outcome in checks.items()]
    record["live_tier"] = {"status": args.live_tier.split(":")[0], "reason": args.live_tier.partition(":")[2] or None}
    record["limits"] = [
        "This record covers the checks that need no model. The live tier has its own record.",
    ]
    reasons: list[str] = []
    klass = PASS
    if record["tag_problems"]:
        klass, reasons = ERROR, ["governance_tags"]
    elif record["tags"]["DataClassification"] not in MODEL_PERMITTED_CLASSIFICATIONS:
        # The live job needs this record to succeed, so no prompt reaches the model API.
        klass, reasons = ERROR, ["data_classification_not_permitted"]
    else:
        cancelled = [name for name, outcome in checks.items() if outcome == "cancelled"]
        failed = [name for name, outcome in checks.items() if outcome == "failure"]
        not_run = [name for name, outcome in checks.items() if outcome == "skipped"]
        if cancelled:
            klass, reasons = ERROR, ["cancelled"]
        elif failed:
            setup = [name for name in failed if name in OFFLINE_ERROR_CHECKS]
            klass, reasons = (ERROR, setup) if setup else (FAIL, failed)
        elif not_run:
            klass, reasons = INCONCLUSIVE, [f"not_run:{name}" for name in not_run]
    return finish(record, klass, reasons)


# --- drift ------------------------------------------------------------------


def compare_records(stable: Mapping[str, Any], latest: Mapping[str, Any]) -> dict[str, Any]:
    stable_cases = {case["name"]: case["class"] for case in stable.get("cases", [])}
    latest_cases = {case["name"]: case["class"] for case in latest.get("cases", [])}
    stable_version = (stable.get("harness") or {}).get("reported_version")
    latest_version = (latest.get("harness") or {}).get("reported_version")
    same_harness = bool(stable_version) and stable_version == latest_version
    rows: list[dict[str, str]] = []
    for name in sorted(set(stable_cases) | set(latest_cases)):
        before, after = stable_cases.get(name), latest_cases.get(name)
        if before == FAIL and after == FAIL:
            label = "SKILL_REGRESSION_CANDIDATE"
        elif before == after:
            label = "NO_CHANGE"
        elif {before, after} == {PASS, FAIL} and not same_harness:
            label = "HARNESS_DRIFT"
        else:
            # The same release on both channels cannot have drifted, so a flip between them is the case's own noise.
            label = "INDETERMINATE"
        rows.append({"case": name, "stable": before or "-", "latest": after or "-", "label": label})

    comparable = stable.get("class") in (PASS, FAIL) and latest.get("class") in (PASS, FAIL)
    labels = {row["label"] for row in rows}
    if not comparable:
        verdict = "NOT_COMPARABLE"
    elif same_harness:
        verdict = "SAME_HARNESS"
    elif "HARNESS_DRIFT" in labels:
        verdict = "HARNESS_DRIFT"
    elif "SKILL_REGRESSION_CANDIDATE" in labels:
        verdict = "SKILL_REGRESSION_CANDIDATE"
    else:
        verdict = "NO_DRIFT"
    return {
        "schema_version": SCHEMA_VERSION,
        "tier": "drift",
        "verdict": verdict,
        "stable": {"class": stable.get("class"), "version": stable_version},
        "latest": {"class": latest.get("class"), "version": latest_version},
        "cases": rows,
    }


# --- planning and redaction ---------------------------------------------------


def is_relevant(path: str) -> bool:
    # git quotes a path with unusual characters and then starts it with a double quote. It cannot be matched
    # against a prefix, and skipping it would let a change slip past the gate, so it counts as relevant.
    if path.startswith('"'):
        return True
    return any(path == entry or (entry.endswith("/") and path.startswith(entry)) for entry in RELEVANT_PATHS)


def plan_live(
    event: str,
    repository: str,
    head_repository: str,
    actor: str,
    pr_author: str,
    changed_files: list[str],
    dispatch_suite: str,
    dispatch_channel: str,
) -> dict[str, Any]:
    """Decide which live legs an event runs. Anything not clearly trusted is not run."""

    def skipped(reason: str) -> dict[str, Any]:
        return {"run_live": False, "live_tier": f"SKIPPED:{reason}", "matrix": {"include": []}}

    def planned(legs: list[dict[str, Any]]) -> dict[str, Any]:
        return {"run_live": True, "live_tier": "planned", "matrix": {"include": legs}}

    if event == "pull_request":
        # Fork pull requests and bot-authored ones (Dependabot) never receive the repository's secrets.
        same_repository = bool(head_repository) and head_repository.lower() == repository.lower()
        if not same_repository or actor.endswith("[bot]") or pr_author.endswith("[bot]"):
            return skipped("untrusted_trigger")
        if not any(is_relevant(path) for path in changed_files):
            return skipped("no_relevant_change")
        return planned([GATE_STABLE])
    if event == "schedule":
        return planned(list(SCHEDULED_LEGS))
    if event == "workflow_dispatch":
        suites = ["gate", "authoring"] if dispatch_suite == "both" else [dispatch_suite]
        return planned([{"suite": suite, "channel": dispatch_channel, "advisory": dispatch_channel == "latest"} for suite in suites])
    return skipped("not_planned")


def redact_aggregate(aggregate: dict[str, Any]) -> dict[str, Any]:
    """Drop what holds model replies or prompts. Grader names, verdicts and explanations stay."""
    for case in aggregate.get("cases", []):
        case.pop("promptMarkdown", None)
        for grader in case.get("graders", []):
            grader.pop("graderMarkdown", None)
        for runs in (case.get("arms") or {}).values():
            for run in runs:
                for result in run.get("graders", []):
                    result.pop("evidence", None)
    return aggregate


# --- rendering --------------------------------------------------------------


def render_markdown(record: Mapping[str, Any]) -> str:
    if record["tier"] == "drift":
        return render_drift(record)
    if record["tier"] == "offline":
        return render_offline(record)
    harness = record.get("harness") or {}
    version = one_line(harness.get("reported_version") or harness.get("resolved_version") or "unknown")
    lines = [
        f"### Skill eval ({record.get('suite')}) on Claude Code {version} ({harness.get('channel')})",
        "",
        f"**Run class: {record['class']}**" + (f" ({one_line(', '.join(record['reasons']))})" if record["reasons"] else "")
        + (f", attribution {record['attribution']}" if record.get("attribution") else ""),
        "",
    ]
    counts = record.get("counts") or {}
    cost = record.get("cost") or {}
    models = record.get("models") or {}
    plugin = record.get("plugin") or {}
    github = record.get("github") or {}
    lines += ["| Field | Value |", "| --- | --- |"]
    lines.append(f"| Harness | Claude Code {cell(version)}, channel {cell(harness.get('channel'))}, dist-tags {cell(format_tags(harness.get('dist_tags')))} |")
    lines.append(f"| Agent model | {cell(models.get('agent') or '-')} |")
    lines.append(f"| Judge model | {cell(models.get('judge') or '-')} |")
    lines.append(f"| Plugin | {cell(plugin.get('name', '-'))} {cell(plugin.get('version', ''))} |")
    lines.append(f"| Classification | {cell(format_governance(record.get('tags')))} |")
    credential = "present" if record.get("credentials_present") else "absent"
    lines.append(f"| Trigger | {cell(github.get('event') or '-')} ({record.get('trigger_trust')}, credential {credential}) |")
    if counts:
        by_class = ", ".join(f"{count} {klass}" for klass, count in sorted((counts.get("attempts_by_class") or {}).items()))
        lines.append(f"| Attempts | {counts.get('attempts')} ({by_class}) |")
        lines.append(f"| Cost | agent ${cost.get('agent_usd', 0):.2f} + judge ${cost.get('judge_usd', 0):.2f}, ceiling {cost.get('ceiling_usd')} |")
    if record.get("guardrail_evidence"):
        evidence = record["guardrail_evidence"]
        lines.append(
            f"| Guardrail evidence | {evidence['clean_attempts']} clean attempts pooled over {evidence['guardrail_cases']} guardrail cases: "
            f"pooled violation rate at most {evidence['violation_rate_upper_bound_95']:.0%} (95% upper bound); "
            "each case alone is bounded far less tightly |"
        )
    if record["cases"]:
        lines += ["", "| Case | Kind | Class | Passed | Reasons |", "| --- | --- | --- | --- | --- |"]
        for case in record["cases"]:
            lines.append(
                f"| `{cell(case['name'])}` | {case['kind']} | {case['class']} | {case['attempts_pass']}/{case['attempts_total']} | {cell(', '.join(case['reasons']) or '-')} |"
            )
    failures = [
        (case["name"], attempt)
        for case in record["cases"]
        for attempt in case["attempts"]
        if attempt["class"] in (FAIL, INFRA_ERROR) and (attempt["failed_graders"] or attempt["error"])
    ]
    if failures:
        lines += ["", "**Failed attempts**", ""]
        for name, attempt in failures[:20]:
            detail = "; ".join(f"{item['name']}: {item['explanation']}" for item in attempt["failed_graders"]) or attempt["error"]
            lines.append(f"- `{one_line(name)}` attempt {attempt['index']} {attempt['class']} ({one_line(', '.join(attempt['reasons']))}): {one_line(detail)}")
        if len(failures) > 20:
            lines.append(f"- … and {len(failures) - 20} more in the JSON record")
    lines += render_notes(record)
    return "\n".join(lines) + "\n"


def render_offline(record: Mapping[str, Any]) -> str:
    live = record.get("live_tier") or {}
    lines = [
        "### Skill eval offline checks",
        "",
        f"**Run class: {record['class']}**" + (f" ({one_line(', '.join(record['reasons']))})" if record["reasons"] else ""),
        "",
        "| Check | Outcome |",
        "| --- | --- |",
    ]
    lines += [f"| {check['name']} | {check['outcome']} |" for check in record["checks"]]
    lines += [
        "",
        f"Classification: {one_line(format_governance(record.get('tags')))}. Live tier: {live.get('status')}"
        + (f" ({live.get('reason')})" if live.get("reason") else "")
        + ".",
    ]
    lines += render_notes(record)
    return "\n".join(lines) + "\n"


def render_drift(record: Mapping[str, Any]) -> str:
    lines = [
        "### Skill eval drift, stable against latest",
        "",
        f"**Verdict: {record['verdict']}** (stable {one_line(record['stable']['version'])} was {record['stable']['class']}; latest {one_line(record['latest']['version'])} was {record['latest']['class']})",
        "",
        "| Case | Stable | Latest | Label |",
        "| --- | --- | --- | --- |",
    ]
    lines += [f"| `{cell(row['case'])}` | {row['stable']} | {row['latest']} | {row['label']} |" for row in record["cases"]]
    return "\n".join(lines) + "\n"


def render_notes(record: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    notes = list(record.get("warnings") or []) + [f"governance tag: {problem}" for problem in record.get("tag_problems") or []]
    if notes:
        lines += ["", "**Warnings**", ""] + [f"- {one_line(note)}" for note in notes]
    if record.get("limits"):
        lines += ["", "**Limits**", ""] + [f"- {limit}" for limit in record["limits"]]
    return lines


def format_tags(tags: Mapping[str, str] | None) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(tags.items())) if tags else "not recorded"


def format_governance(tags: Mapping[str, str] | None) -> str:
    return " · ".join(f"{key}={tags[key]}" for key in TAG_ENV if tags and key in tags) or "not set"


def report(record: Mapping[str, Any]) -> None:
    """Print a short account and GitHub annotations."""
    reasons = f" ({one_line(', '.join(record['reasons']))})" if record.get("reasons") else ""
    print(f"Run class: {record['class']}{reasons}")
    if record["tier"] == "live":
        for case in record["cases"]:
            print(f"  {case['class']:<13} {one_line(case['name'])} ({case['attempts_pass']}/{case['attempts_total']} attempts passed)")
            if case["class"] == FAIL:
                eval_suite.annotate("error", f"{case['name']} FAIL: {', '.join(case['reasons'])}")
            elif case["class"] in (FLAKY, INCONCLUSIVE):
                eval_suite.annotate("warning", f"{case['name']} {case['class']}: {', '.join(case['reasons']) or 'mixed results'}")
    for warning in record.get("warnings") or []:
        print(f"  warning: {one_line(warning)}")
    if record["class"] in (FAIL, ERROR):
        eval_suite.annotate("error", f"skill eval run {record['class']}: {', '.join(record['reasons'])}")
    elif record["class"] == INCONCLUSIVE:
        eval_suite.annotate("warning", f"skill eval run INCONCLUSIVE: {', '.join(record['reasons'])}")
    elif record["class"] == SKIPPED:
        eval_suite.annotate("notice", f"skill eval run SKIPPED: {', '.join(record['reasons'])}")
    for problem in record.get("tag_problems") or []:
        eval_suite.annotate("error", f"governance tag: {problem}")


# --- command line -----------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Classify skill-eval CI runs.")
    commands = parser.add_subparsers(dest="command", required=True)

    live = commands.add_parser("live", help="classify one `claude plugin eval` run")
    live.add_argument("--suite", required=True, choices=eval_suite.SUITE_TAGS)
    live.add_argument("--evals-dir", type=Path)
    live.add_argument("--aggregate", type=Path, help="aggregate-result.json from --output-dir")
    live.add_argument("--static-grades", type=Path, help="output of grade_eval_workspaces.py")
    live.add_argument("--status", choices=("ran", "skipped", "error"), default="ran")
    live.add_argument("--reason", help="reason code when --status is skipped or error")
    live.add_argument("--eval-exit-code", type=int)
    live.add_argument("--harness-channel", default="stable")
    live.add_argument("--harness-version", default="", help="the version the job installed")
    live.add_argument("--dist-tags", default="", help="JSON object of npm dist-tags seen")
    live.add_argument("--expect-model", default="")
    live.add_argument("--max-cost-usd", type=float)
    live.add_argument("--trigger-trust", choices=("trusted", "untrusted"), required=True)
    live.add_argument("--credentials-present", choices=("true", "false"), required=True)

    offline = commands.add_parser("offline", help="classify the checks that need no model")
    offline.add_argument("--check", action="append", required=True, type=parse_check, metavar="NAME=OUTCOME")
    offline.add_argument("--live-tier", default="planned", type=parse_live_tier, metavar="STATUS[:REASON]")

    drift = commands.add_parser("drift", help="compare a stable record with a latest record")
    drift.add_argument("--stable", type=Path, required=True)
    drift.add_argument("--latest", type=Path, required=True)

    for command in (live, offline, drift):
        command.add_argument("--out", type=Path, required=True, help="where to write the JSON record")
        command.add_argument("--markdown", type=Path, help="where to write the Markdown summary")

    plan = commands.add_parser("plan", help="print the live legs this event runs, as GITHUB_OUTPUT lines")
    plan.add_argument("--event", required=True)
    plan.add_argument("--repository", required=True)
    plan.add_argument("--head-repository", default="", help="the pull request's head repository, owner/name")
    plan.add_argument("--actor", default="")
    plan.add_argument("--pr-author", default="")
    plan.add_argument("--changed-files", type=Path, help="file listing one changed path per line")
    plan.add_argument("--dispatch-suite", default="gate", choices=(*eval_suite.SUITE_TAGS, "both"))
    plan.add_argument("--dispatch-channel", default="stable", choices=("stable", "latest"))

    redact = commands.add_parser("redact", help="remove model replies and prompts from an eval result")
    redact.add_argument("--aggregate", type=Path, required=True)
    redact.add_argument("--out", type=Path, required=True)
    return parser


def parse_check(text: str) -> tuple[str, str]:
    name, _, outcome = text.partition("=")
    if name not in OFFLINE_CHECKS:
        raise argparse.ArgumentTypeError(f"unknown check `{name}`; expected one of {', '.join(OFFLINE_CHECKS)}")
    if outcome not in OFFLINE_OUTCOMES:
        raise argparse.ArgumentTypeError(f"unknown outcome `{outcome}`; expected one of {', '.join(OFFLINE_OUTCOMES)}")
    return name, outcome


def parse_live_tier(text: str) -> str:
    status, _, reason = text.partition(":")
    if status == "planned" and not reason:
        return text
    if status == SKIPPED and reason in SKIPPED_REASONS:
        return text
    raise argparse.ArgumentTypeError(f"expected `planned` or `SKIPPED:<{'|'.join(SKIPPED_REASONS)}>`")


def validate_status(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    allowed = {"skipped": SKIPPED_REASONS, "error": ERROR_REASONS}.get(args.status)
    if allowed is None:
        return
    if args.reason not in allowed:
        parser.error(f"--reason for --status {args.status} must be one of {', '.join(allowed)}")


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    env = os.environ if env is None else env

    if args.command == "plan":
        changed = args.changed_files.read_text(encoding="utf-8").splitlines() if args.changed_files and args.changed_files.is_file() else []
        decision = plan_live(
            args.event, args.repository, args.head_repository, args.actor, args.pr_author, changed, args.dispatch_suite, args.dispatch_channel
        )
        print(f"run_live={str(decision['run_live']).lower()}")
        print(f"live_tier={decision['live_tier']}")
        print(f"matrix={json.dumps(decision['matrix'], separators=(',', ':'))}")
        return 0
    if args.command == "redact":
        aggregate = read_aggregate(args.aggregate)
        if aggregate is None:
            parser.error("--aggregate must be an eval result")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(redact_aggregate(aggregate), indent=2) + "\n", encoding="utf-8")
        return 0
    if args.command == "live":
        validate_status(parser, args)
        record = classify_live(args, env)
    elif args.command == "offline":
        record = classify_offline(args, env)
    else:
        stable, latest = read_json(args.stable), read_json(args.latest)
        if not isinstance(stable, dict) or not isinstance(latest, dict):
            parser.error("--stable and --latest must be classification records")
        record = compare_records(stable, latest)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    markdown = render_markdown(record)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown, encoding="utf-8")
    eval_suite.append_step_summary(markdown)

    if record["tier"] == "drift":
        print(f"Drift verdict: {record['verdict']}")
        if record["verdict"] in ("HARNESS_DRIFT", "SKILL_REGRESSION_CANDIDATE"):
            eval_suite.annotate("warning", f"stable against latest: {record['verdict']}")
        return 0
    report(record)
    return 0 if record["class"] in (PASS, SKIPPED) else 1


if __name__ == "__main__":
    sys.exit(main())
