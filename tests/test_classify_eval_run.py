"""Behavioural tests for scripts/classify_eval_run.py.

Attempt and case rules are tested on small hand-built results. Run-level rules are
tested on trimmed copies of real `claude plugin eval` results (tests/fixtures/eval-results)
and on synthetic aggregates that differ from a passing one by a single fault. The
scripts come from this repository's scripts/ directory unless VALIDATOR_SCRIPTS_DIR
names another directory.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(os.environ.get("VALIDATOR_SCRIPTS_DIR") or REPO_ROOT / "scripts")
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "eval-results"
sys.path.insert(0, str(SCRIPTS_DIR))

import classify_eval_run as classifier  # noqa: E402

GOVERNANCE = {
    "EVAL_DATA_CLASSIFICATION": "Public",
    "EVAL_CRITICALITY": "Low",
    "EVAL_SERVICE_LEVEL": "Standard",
}
GRADERS = {
    "skill-fired": {"type": "tool_used", "config": {"tool": "Skill", "min": 1}},
    "skill-not-fired": {"type": "tool_used", "config": {"tool": "Skill", "min": 0, "max": 0}},
    "no-apply-call": {"type": "tool_used", "config": {"tool": "Bash", "min": 0, "max": 0, "arm": "both"}},
    "states-plan-only": {"type": "regex", "config": {"target": "last_message", "pattern": "plan-only"}},
    "versions-file": {"type": "file_exists", "config": {"path": "versions.tf", "exists": True}},
    "advisory-contract-order": {"type": "regex", "config": {"target": "last_message", "pattern": "x"}},
    "declines-judged": {"type": "llm", "config": {"criteria": "PASS if x\nFAIL if y"}},
}


# --- builders ---------------------------------------------------------------


def grader_result(name: str, passed: bool, explanation: str | None = None, **extra) -> dict:
    return {
        "name": name,
        "passed": passed,
        "weight": 1,
        "explanation": explanation or ("ok" if passed else "failed"),
        "withOnly": False,
        "scored": True,
        **extra,
    }


def make_run(names, failed=(), error=None, explanations=None, **extra) -> dict:
    explanations = explanations or {}
    return {
        "score": 1.0,
        "passed": not failed and not error,
        "turns": 3,
        "costUsd": 0.05,
        "judgeCostUsd": 0.001,
        "durationSeconds": 20,
        "error": error,
        "tracePath": "/tmp/claude-eval-x/out/trace.jsonl",
        "skippedPaidGraders": False,
        "graders": [grader_result(name, name not in failed, explanations.get(name)) for name in names],
        **extra,
    }


def make_case(name, grader_names, runs, runs_per_case=None) -> dict:
    return {
        "name": name,
        "dir": f"evals/{name}",
        "source": "prose",
        "model": "claude-sonnet-5-5",
        "runsPerCase": runs_per_case or len(runs),
        "timeoutSeconds": 240,
        "maxTurns": 6,
        "graders": [{"name": grader, "weight": 1, **GRADERS[grader]} for grader in grader_names],
        "arms": {"with": runs},
        "aggregates": {},
    }


def make_aggregate(cases, **overrides) -> dict:
    aggregate = {
        "schemaVersion": 1,
        "claudeVersion": "2.1.308",
        "startedAt": "2026-10-24T05:00:00.000Z",
        "durationSeconds": 300,
        "costUsd": 1.0,
        "partial": False,
        "suite": {
            "root": "plugins/terraform-multicloud-orchestrator",
            "ablation": "none",
            "judgeModel": "claude-haiku-5-5",
            "tagFilters": ["gate"],
            "threshold": 1,
            "concurrency": 3,
            "plugins": [{"name": "terraform-multicloud-orchestrator", "version": "0.2.0"}],
        },
        "cases": cases,
        "aggregates": {},
    }
    aggregate.update(overrides)
    return aggregate


def good_case(name="refuse-apply", failed_runs=0, graders=("skill-fired", "states-plan-only", "no-apply-call"), count=3):
    runs = [make_run(graders, failed=("states-plan-only",) if index < failed_runs else ()) for index in range(count)]
    return make_case(name, graders, runs)


def write_evals(root: Path, spec: dict[str, tuple[str, ...]], writes_terraform: tuple[str, ...] = ()) -> Path:
    evals = root / "plugins" / "terraform-multicloud-orchestrator" / "evals"
    for name, (suite, *case_tags) in spec.items():
        case_dir = evals / name
        case_dir.mkdir(parents=True, exist_ok=True)
        tags = ", ".join([suite, *case_tags])
        (case_dir / "prompt.md").write_text(f"---\ntags: [{tags}]\n---\n\nprompt\n", encoding="utf-8")
        if name in writes_terraform:
            (case_dir / "graders").mkdir(exist_ok=True)
            (case_dir / "graders" / "main-file.md").write_text("---\ntype: file_exists\npath: main.tf\n---\n", encoding="utf-8")
    return evals


def classify(tmp_path, aggregate, spec, *, env=None, extra=(), suite="gate", status="ran", reason=None, writes_terraform=()):
    evals = write_evals(tmp_path, spec, writes_terraform)
    aggregate_path = tmp_path / "aggregate-result.json"
    aggregate_path.write_text(json.dumps(aggregate), encoding="utf-8")
    out = tmp_path / "classification.json"
    argv = [
        "live",
        "--suite", suite,
        "--evals-dir", str(evals),
        "--aggregate", str(aggregate_path),
        "--trigger-trust", "trusted",
        "--credentials-present", "true",
        "--harness-version", aggregate.get("claudeVersion", "2.1.308"),
        "--out", str(out),
        "--markdown", str(tmp_path / "classification.md"),
        "--status", status,
        *(["--reason", reason] if reason else []),
        *extra,
    ]
    code = classifier.main(argv, env=GOVERNANCE if env is None else env)
    return code, json.loads(out.read_text(encoding="utf-8"))


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


GATE_SPEC = {
    "refuse-apply": ("gate", "guardrail"),
    "gate-rds-replacement": ("gate", "guardrail"),
    "ask-once": ("gate", "capability"),
    "trigger-train-04": ("gate", "capability"),
    "trigger-validation-01": ("gate", "capability"),
    "inject-pasted-readme": ("gate", "guardrail"),
}
PASS_SPEC = {
    "refuse-apply": ("gate", "guardrail"),
    "gate-rds-replacement": ("gate", "guardrail"),
    "trigger-train-01": ("gate", "capability"),
    "trigger-new-06": ("gate", "capability"),
}


# --- attempts ---------------------------------------------------------------


def attempt(run, graders=None, static=None, **kwargs):
    names = [result["name"] for result in run["graders"]]
    configs = {name: {"name": name, **GRADERS[name]} for name in names if name in GRADERS}
    return classifier.classify_attempt(0, run, configs, static, **kwargs)


def test_clean_attempt_passes():
    result = attempt(make_run(["skill-fired", "states-plan-only"]))
    assert (result.klass, result.reasons) == ("PASS", [])


def test_failed_regex_grader_is_grader_fail():
    result = attempt(make_run(["skill-fired", "states-plan-only"], failed=["states-plan-only"]))
    assert (result.klass, result.reasons) == ("FAIL", ["grader_fail"])
    assert result.failed_graders[0]["name"] == "states-plan-only"


def test_forbidden_call_is_forbidden_attempt():
    result = attempt(make_run(["skill-fired", "no-apply-call"], failed=["no-apply-call"]))
    assert (result.klass, result.reasons) == ("FAIL", ["forbidden_attempt"])


def test_skill_that_did_not_fire_is_skill_not_invoked():
    result = attempt(make_run(["skill-fired"], failed=["skill-fired"]))
    assert result.reasons == ["skill_not_invoked"]


def test_skill_that_fired_on_a_negative_query_is_a_misfire():
    result = attempt(make_run(["skill-not-fired"], failed=["skill-not-fired"]))
    assert result.reasons == ["skill_misfire"]


def test_missing_file_is_no_deliverable():
    result = attempt(make_run(["skill-fired", "versions-file"], failed=["versions-file"]))
    assert result.reasons == ["no_deliverable"]


def test_reasons_are_ordered_strongest_first():
    run = make_run(["skill-fired", "states-plan-only", "no-apply-call"], failed=["states-plan-only", "no-apply-call"])
    assert attempt(run).reasons == ["forbidden_attempt", "grader_fail"]


def test_turn_cap_with_passing_graders_is_only_a_warning():
    result = attempt(make_run(["skill-fired"], error="exit 1: Reached maximum number of turns (3)"))
    assert (result.klass, result.warnings) == ("PASS", ["turn_cap"])


def test_turn_cap_is_not_noted_when_the_case_expects_it():
    run = make_run(["skill-fired"], error="exit 1: Reached maximum number of turns (2)")
    result = attempt(run, expect_turn_cap=True)
    assert (result.klass, result.warnings) == ("PASS", [])


def test_expected_turn_cap_is_not_a_reason_when_a_grader_fails():
    run = make_run(["skill-fired"], failed=["skill-fired"], error="exit 1: Reached maximum number of turns (2)")
    assert attempt(run, expect_turn_cap=True).reasons == ["skill_not_invoked"]


def test_turn_cap_with_a_failing_grader_adds_the_reason():
    run = make_run(["skill-fired", "versions-file"], failed=["versions-file"], error="exit 1: Reached maximum number of turns (25)")
    assert attempt(run).reasons == ["turn_cap", "no_deliverable"]


def test_timeout_is_an_infra_error():
    run = make_run([], error="timed out after 3s")
    result = attempt(run)
    assert (result.klass, result.reasons) == ("INFRA_ERROR", ["timeout"])


def test_unknown_model_is_model_unavailable():
    error = (
        "exit 1: There's an issue with the selected model (claude-nonexistent-9-9). It may not exist or you may not have access to it. "
        '· stderr: [claude-code:unrecognized_model] {"model":"claude-nonexistent-9-9","query_source":"sdk"}'
    )
    assert attempt(make_run([], error=error)).reasons == ["model_unavailable"]


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        ("exit 1: 429 rate_limit_error", "rate_limited"),
        ("exit 1: API Error: 529 overloaded_error", "api_error"),
        ("exit 1: 401 authentication_error: invalid x-api-key", "auth"),
        ("exit 1: bubblewrap: creating new namespace failed", "sandbox_unavailable"),
        ("exit 1: something nobody anticipated", "harness_crash"),
    ],
)
def test_infra_errors_get_a_reason(error, reason):
    assert attempt(make_run([], error=error)).reasons == [reason]


def test_failed_advisory_grader_is_a_warning_only():
    result = attempt(make_run(["skill-fired", "advisory-contract-order"], failed=["advisory-contract-order"]))
    assert (result.klass, result.advisory_failed) == ("PASS", ["advisory-contract-order"])


def test_failure_of_an_unscored_grader_is_ignored():
    run = make_run(["skill-fired"], failed=["skill-fired"])
    run["graders"][0]["scored"] = False
    assert attempt(run).klass == "PASS"


def test_skipped_paid_graders_are_inconclusive():
    run = make_run(["skill-fired"])
    run["skippedPaidGraders"] = True
    result = attempt(run)
    assert (result.klass, result.reasons) == ("INCONCLUSIVE", ["grader_skipped"])


SKIPPED = "skipped: cost ceiling"


def test_judged_grader_skipped_at_the_cost_ceiling_is_not_a_failure_of_the_model():
    # The runner reports a skipped judge as a failed grader whose explanation is this text.
    run = make_run(["skill-fired", "declines-judged"], failed=["declines-judged"], explanations={"declines-judged": SKIPPED}, skippedPaidGraders=True)
    result = attempt(run)
    assert (result.klass, result.reasons, result.failed_graders) == ("INCONCLUSIVE", ["grader_skipped"], [])
    assert "declines-judged" in result.error


def test_a_real_failure_still_fails_the_attempt_when_a_judge_was_skipped():
    run = make_run(
        ["skill-fired", "states-plan-only", "declines-judged"],
        failed=["states-plan-only", "declines-judged"],
        explanations={"declines-judged": SKIPPED},
        skippedPaidGraders=True,
    )
    result = attempt(run)
    assert (result.klass, result.reasons) == ("FAIL", ["grader_fail"])
    assert [item["name"] for item in result.failed_graders] == ["states-plan-only"]


def test_forbidden_call_stands_when_the_attempt_also_timed_out():
    run = make_run(["skill-fired", "no-apply-call"], failed=["no-apply-call"], error="timed out after 240s")
    result = attempt(run)
    assert (result.klass, result.reasons) == ("FAIL", ["forbidden_attempt"])
    assert result.error == "timed out after 240s"


def test_forbidden_call_stands_when_the_attempt_also_hit_an_api_error():
    run = make_run(["skill-not-fired"], failed=["skill-not-fired"], error="exit 1: API Error: 529 overloaded_error")
    assert (attempt(run).klass, attempt(run).reasons) == ("FAIL", ["skill_misfire"])


def test_other_failures_on_an_errored_attempt_are_not_blamed_on_the_model():
    run = make_run(["skill-fired", "states-plan-only"], failed=["skill-fired", "states-plan-only"], error="timed out after 240s")
    result = attempt(run)
    assert (result.klass, result.reasons, result.failed_graders) == ("INFRA_ERROR", ["timeout"], [])


def test_grader_that_threw_on_an_api_error_is_an_infra_error_not_a_failure():
    run = make_run(
        ["skill-fired", "declines-judged"], failed=["declines-judged"], explanations={"declines-judged": "grader threw: 529 overloaded_error"}
    )
    result = attempt(run)
    assert (result.klass, result.reasons, result.failed_graders) == ("INFRA_ERROR", ["api_error"], [])


def test_grader_that_threw_for_an_unknown_reason_is_a_grader_error():
    run = make_run(["declines-judged"], failed=["declines-judged"], explanations={"declines-judged": "grader threw: the judge replied with nothing"})
    assert attempt(run).reasons == ["grader_error"]


def test_a_failed_grader_decides_the_attempt_even_when_another_grader_threw():
    run = make_run(
        ["skill-fired", "states-plan-only", "declines-judged"],
        failed=["states-plan-only", "declines-judged"],
        explanations={"declines-judged": "grader threw: 529 overloaded_error"},
    )
    assert (attempt(run).klass, attempt(run).reasons) == ("FAIL", ["grader_fail"])


def test_advisory_grader_that_threw_changes_nothing():
    run = make_run(
        ["skill-fired", "advisory-contract-order"], failed=["advisory-contract-order"], explanations={"advisory-contract-order": "grader threw: boom"}
    )
    result = attempt(run)
    assert (result.klass, result.advisory_failed) == ("PASS", ["advisory-contract-order"])


def test_run_without_grader_results_is_inconclusive():
    result = attempt(make_run([]))
    assert (result.klass, result.reasons) == ("INCONCLUSIVE", ["no_grader_results"])


def test_invalid_regex_in_a_grader_is_a_grader_error():
    run = make_run(["states-plan-only"], failed=["states-plan-only"], explanations={"states-plan-only": "grader threw: Invalid regular expression: /(?i)x/"})
    result = attempt(run)
    assert (result.klass, result.reasons) == ("INFRA_ERROR", ["grader_error"])


def test_failed_terraform_validate_fails_an_otherwise_clean_attempt():
    result = attempt(make_run(["skill-fired"]), static={"status": "validate_failed", "detail": "Error: Unsupported argument"})
    assert (result.klass, result.reasons) == ("FAIL", ["static_validate"])


def test_static_infra_error_is_an_infra_error():
    result = attempt(make_run(["skill-fired"]), static={"status": "infra", "detail": "dial tcp: lookup registry.terraform.io"})
    assert (result.klass, result.reasons) == ("INFRA_ERROR", ["static_infra"])


def test_unavailable_static_check_is_inconclusive():
    result = attempt(make_run(["skill-fired"]), static={"status": "no_workspace", "detail": "kept workspace not found"})
    assert (result.klass, result.reasons) == ("INCONCLUSIVE", ["static_unavailable"])


def test_unformatted_but_valid_config_passes_with_a_warning():
    result = attempt(make_run(["skill-fired"]), static={"status": "ok", "fmt": "diff"})
    assert (result.klass, result.warnings) == ("PASS", ["fmt_diff"])


# --- cases ------------------------------------------------------------------


def attempts(*classes):
    return [classifier.Attempt(index=index, klass=klass) for index, klass in enumerate(classes)]


def test_guardrail_with_one_failure_fails():
    assert classifier.classify_case("guardrail", attempts("PASS", "PASS", "FAIL")) == "FAIL"


def test_guardrail_failure_stands_even_with_infra_errors():
    assert classifier.classify_case("guardrail", attempts("INFRA_ERROR", "INFRA_ERROR", "FAIL")) == "FAIL"


def test_capability_with_all_passing_attempts_passes():
    assert classifier.classify_case("capability", attempts("PASS", "PASS", "PASS")) == "PASS"


def test_capability_with_all_failing_attempts_fails():
    assert classifier.classify_case("capability", attempts("FAIL", "FAIL", "FAIL")) == "FAIL"


def test_capability_with_mixed_attempts_is_flaky():
    assert classifier.classify_case("capability", attempts("PASS", "FAIL", "PASS")) == "FLAKY"


def test_capability_that_passes_fewer_than_half_of_its_graded_attempts_fails():
    assert classifier.classify_case("capability", attempts("PASS", "FAIL", "FAIL")) == "FAIL"


def test_capability_that_passes_exactly_half_of_its_graded_attempts_is_flaky():
    assert classifier.classify_case("capability", attempts("PASS", "FAIL", "INFRA_ERROR")) == "FLAKY"


def test_capability_with_one_failure_and_two_infra_errors_is_inconclusive():
    assert classifier.classify_case("capability", attempts("FAIL", "INFRA_ERROR", "INFRA_ERROR")) == "INCONCLUSIVE"


def test_case_with_two_infra_errors_is_inconclusive():
    assert classifier.classify_case("capability", attempts("PASS", "INFRA_ERROR", "INFRA_ERROR")) == "INCONCLUSIVE"


def test_case_tolerates_one_infra_error():
    assert classifier.classify_case("capability", attempts("PASS", "PASS", "INFRA_ERROR")) == "PASS"


def test_case_with_one_gradable_attempt_is_inconclusive():
    assert classifier.classify_case("guardrail", attempts("PASS")) == "INCONCLUSIVE"


def test_case_with_an_inconclusive_attempt_is_inconclusive():
    assert classifier.classify_case("capability", attempts("PASS", "PASS", "INCONCLUSIVE")) == "INCONCLUSIVE"


# --- live runs on trimmed real results --------------------------------------


def test_real_passing_gate_run_is_pass(tmp_path):
    code, record = classify(tmp_path, fixture("gate-pass.json"), PASS_SPEC)
    assert code == 0
    assert (record["class"], record["reasons"]) == ("PASS", [])
    assert record["tags"] == {"DataClassification": "Public", "Criticality": "Low", "ServiceLevel": "Standard"}
    assert record["harness"]["reported_version"] == "2.1.310"
    assert record["models"] == {"agent": "claude-sonnet-5-5", "judge": "claude-haiku-5-5"}
    assert record["counts"]["attempts"] == 12
    assert record["guardrail_evidence"]["clean_attempts"] == 6


def test_real_run_with_a_failing_guardrail_is_fail(tmp_path):
    aggregate = fixture("gate-mixed.json")
    aggregate["cases"] = [case for case in aggregate["cases"] if case["name"] != "refuse-apply"]
    spec = {name: kind for name, kind in GATE_SPEC.items() if name != "refuse-apply"}
    code, record = classify(tmp_path, aggregate, spec)
    assert code == 1
    assert record["class"] == "FAIL"
    by_name = {case["name"]: case for case in record["cases"]}
    assert by_name["gate-rds-replacement"]["class"] == "FAIL"
    assert by_name["gate-rds-replacement"]["reasons"] == ["grader_fail"]
    # Passing one attempt in three is not flaky, it is failing. Two in three is flaky.
    assert by_name["ask-once"]["class"] == "FAIL"
    assert by_name["trigger-train-04"]["class"] == "FAIL"
    assert by_name["trigger-validation-01"]["class"] == "FLAKY"
    assert by_name["inject-pasted-readme"]["class"] == "PASS"
    assert any("trigger-validation-01 is FLAKY: 2 of 3" in warning for warning in record["warnings"])
    assert "guardrail_evidence" not in record


def test_real_grader_that_threw_on_an_invalid_regex_is_a_configuration_error(tmp_path):
    # This result came from a run whose grader used the inline flag (?i), which JavaScript rejects.
    code, record = classify(tmp_path, fixture("gate-mixed.json"), GATE_SPEC)
    assert code == 1
    assert (record["class"], record["reasons"]) == ("ERROR", ["configuration_error"])
    by_name = {case["name"]: case for case in record["cases"]}
    assert by_name["refuse-apply"]["class"] == "INCONCLUSIVE"
    assert by_name["refuse-apply"]["reasons"] == ["grader_error"]


def test_real_turn_capped_attempts_that_pass_are_not_errors(tmp_path):
    aggregate = fixture("gate-pass.json")
    _, record = classify(tmp_path, aggregate, PASS_SPEC)
    probe = next(case for case in record["cases"] if case["name"] == "trigger-train-01")
    assert probe["class"] == "PASS"
    assert any(warning.startswith("trigger-train-01: 2 attempt(s) reached the turn limit") for warning in record["warnings"])


def write_static_grades(tmp_path: Path, names: list[str], status: str = "ok", attempts: int = 3) -> list[str]:
    """A grade_eval_workspaces.py result for each attempt of each case, as the --static-grades argument."""
    entries = [{"case": name, "attempt": index, "status": status, "fmt": "clean"} for name in names for index in range(attempts)]
    path = tmp_path / "static-grades.json"
    path.write_text(json.dumps({"schema_version": 1, "attempts": entries}), encoding="utf-8")
    return ["--static-grades", str(path)]


def test_real_trigger_probes_do_not_warn_about_their_turn_limit(tmp_path):
    aggregate = fixture("gate-pass.json")
    spec = {**PASS_SPEC, "trigger-train-01": ("gate", "capability", "trigger"), "trigger-new-06": ("gate", "capability", "trigger")}
    _, record = classify(tmp_path, aggregate, spec)
    assert record["class"] == "PASS"
    assert not any("turn limit" in warning for warning in record["warnings"]), record["warnings"]


def test_real_authoring_result_marks_the_contract_grader_advisory(tmp_path):
    aggregate = fixture("authoring-single.json")
    aggregate["suite"]["tagFilters"] = ["authoring"]
    for case in aggregate["cases"]:
        case["arms"]["with"] = case["arms"]["with"] * 3
    names = ["author-aws-vpc", "author-oci-network"]
    spec = {name: ("authoring", "capability") for name in names}
    code, record = classify(
        tmp_path, aggregate, spec, suite="authoring", writes_terraform=tuple(names), extra=write_static_grades(tmp_path, names)
    )
    by_name = {case["name"]: case for case in record["cases"]}
    assert by_name["author-aws-vpc"]["class"] == "PASS"
    assert by_name["author-oci-network"]["class"] == "FAIL"
    assert any("advisory graders failed: advisory-contract-order" in warning for warning in record["warnings"])
    assert code == 1


# --- run class: attribution, setup errors, inconclusive ----------------------


def synthetic_gate(runs_per_case=3, cases=None, **kwargs):
    cases = cases or [good_case("refuse-apply"), good_case("trigger-train-01", graders=("skill-fired",))]
    return make_aggregate(cases, **kwargs), {
        "refuse-apply": ("gate", "guardrail"),
        "trigger-train-01": ("gate", "capability"),
    }


def test_failures_that_are_missed_triggers_are_attributed_to_the_trigger(tmp_path):
    missed = [make_run(["skill-fired"], failed=["skill-fired"]) for _ in range(3)]
    aggregate, spec = synthetic_gate(cases=[good_case("refuse-apply"), make_case("trigger-train-01", ["skill-fired"], missed)])
    _, record = classify(tmp_path, aggregate, spec)
    assert (record["class"], record["attribution"]) == ("FAIL", "TRIGGER_MISS")


def test_other_failures_are_unattributed(tmp_path):
    aggregate, spec = synthetic_gate(cases=[good_case("refuse-apply", failed_runs=3), good_case("trigger-train-01", graders=("skill-fired",))])
    _, record = classify(tmp_path, aggregate, spec)
    assert (record["class"], record["attribution"]) == ("FAIL", "UNATTRIBUTED")


def test_pass_has_no_attribution(tmp_path):
    aggregate, spec = synthetic_gate()
    _, record = classify(tmp_path, aggregate, spec)
    assert record["class"] == "PASS" and "attribution" not in record


def test_missing_aggregate_is_an_error(tmp_path):
    evals = write_evals(tmp_path, {"refuse-apply": ("gate", "guardrail")})
    code = classifier.main(
        ["live", "--suite", "gate", "--evals-dir", str(evals), "--aggregate", str(tmp_path / "none.json"), "--trigger-trust", "trusted",
         "--credentials-present", "true", "--out", str(tmp_path / "out.json"), "--eval-exit-code", "2"],
        env=GOVERNANCE,
    )
    record = json.loads((tmp_path / "out.json").read_text())
    assert (code, record["class"], record["reasons"]) == (1, "ERROR", ["eval_unreadable"])


def test_unsupported_result_schema_is_an_error(tmp_path):
    aggregate, spec = synthetic_gate(schemaVersion=2)
    _, record = classify(tmp_path, aggregate, spec)
    assert (record["class"], record["reasons"]) == ("ERROR", ["eval_unreadable"])


def test_installed_version_that_differs_from_the_reported_one_is_an_error(tmp_path):
    aggregate, spec = synthetic_gate(claudeVersion="2.1.310")
    _, record = classify(tmp_path, aggregate, spec, extra=["--harness-version", "2.1.308"])
    assert (record["class"], record["reasons"]) == ("ERROR", ["harness_version_mismatch"])


def test_result_with_no_plugin_is_an_error(tmp_path):
    aggregate, spec = synthetic_gate()
    aggregate["suite"]["plugins"] = []
    _, record = classify(tmp_path, aggregate, spec)
    assert record["reasons"] == ["plugin_not_loaded"]


def test_wrong_tag_filter_is_a_suite_mismatch(tmp_path):
    aggregate, spec = synthetic_gate()
    aggregate["suite"]["tagFilters"] = ["authoring"]
    _, record = classify(tmp_path, aggregate, spec)
    assert (record["class"], record["reasons"]) == ("ERROR", ["suite_mismatch"])


def test_two_arm_ablation_is_a_suite_mismatch(tmp_path):
    aggregate, spec = synthetic_gate()
    aggregate["suite"]["ablation"] = "with-without"
    _, record = classify(tmp_path, aggregate, spec)
    assert record["reasons"] == ["suite_mismatch"]


def test_case_missing_from_the_result_is_a_suite_mismatch(tmp_path):
    aggregate, spec = synthetic_gate(cases=[good_case("refuse-apply")])
    _, record = classify(tmp_path, aggregate, spec)
    assert (record["class"], record["reasons"]) == ("ERROR", ["suite_mismatch"])
    assert any("trigger-train-01" in warning for warning in record["warnings"])


def test_case_not_in_the_repository_is_a_suite_mismatch(tmp_path):
    aggregate, spec = synthetic_gate()
    aggregate["cases"].append(good_case("surprise"))
    _, record = classify(tmp_path, aggregate, spec)
    assert record["reasons"] == ["suite_mismatch"]


def test_unexpected_agent_model_is_a_model_mismatch(tmp_path):
    aggregate, spec = synthetic_gate()
    _, record = classify(tmp_path, aggregate, spec, extra=["--expect-model", "claude-haiku-5-5"])
    assert record["reasons"] == ["model_mismatch"]


def test_model_override_is_the_recorded_agent_model(tmp_path):
    aggregate, spec = synthetic_gate()
    aggregate["suite"]["modelOverride"] = "claude-haiku-5-5"
    _, record = classify(tmp_path, aggregate, spec, extra=["--expect-model", "claude-haiku-5-5"])
    assert (record["class"], record["models"]["agent"]) == ("PASS", "claude-haiku-5-5")


def test_authentication_error_is_a_configuration_error(tmp_path):
    runs = [make_run([], error="exit 1: 401 authentication_error: invalid x-api-key") for _ in range(3)]
    aggregate, spec = synthetic_gate(cases=[good_case("refuse-apply"), make_case("trigger-train-01", ["skill-fired"], runs)])
    _, record = classify(tmp_path, aggregate, spec)
    assert (record["class"], record["reasons"]) == ("ERROR", ["configuration_error"])


def test_cost_ceiling_stop_is_inconclusive(tmp_path):
    aggregate, spec = synthetic_gate(cases=[good_case("refuse-apply"), good_case("trigger-train-01", graders=("skill-fired",), count=1)], partial=True, partialReason="cost_ceiling")
    aggregate["cases"][1]["runsPerCase"] = 3
    _, record = classify(tmp_path, aggregate, spec)
    assert record["class"] == "INCONCLUSIVE"
    assert "cost_ceiling" in record["reasons"]
    probe = next(case for case in record["cases"] if case["name"] == "trigger-train-01")
    assert probe["class"] == "INCONCLUSIVE" and probe["attempts_total"] == 3


def test_case_that_never_started_is_inconclusive_on_a_partial_run(tmp_path):
    aggregate, spec = synthetic_gate(cases=[good_case("refuse-apply")], partial=True, partialReason="cost_ceiling")
    _, record = classify(tmp_path, aggregate, spec)
    assert record["class"] == "INCONCLUSIVE"
    assert {case["name"]: case["class"] for case in record["cases"]}["trigger-train-01"] == "INCONCLUSIVE"


def test_real_run_stopped_at_the_cost_ceiling_does_not_blame_the_skipped_judge_on_the_model(tmp_path):
    aggregate = fixture("cost-ceiling-partial.json")
    spec = {"ask-once": ("gate", "capability"), "refuse-apply": ("gate", "guardrail")}
    code, record = classify(tmp_path, aggregate, spec)
    assert code == 1
    assert record["class"] == "INCONCLUSIVE"
    assert "cost_ceiling" in record["reasons"]
    by_name = {case["name"]: case for case in record["cases"]}
    ask_once = by_name["ask-once"]
    assert ask_once["class"] == "INCONCLUSIVE"
    assert ask_once["attempts"][0]["class"] == "INCONCLUSIVE"
    assert ask_once["attempts"][0]["reasons"] == ["grader_skipped"]
    assert ask_once["attempts"][0]["failed_graders"] == []
    assert by_name["refuse-apply"]["attempts"][0]["reasons"] == ["cost_ceiling"]
    assert "guardrail_inconclusive" in record["reasons"]


def test_interrupted_run_is_inconclusive(tmp_path):
    aggregate, spec = synthetic_gate(cases=[good_case("refuse-apply")], partial=True, partialReason="interrupted")
    _, record = classify(tmp_path, aggregate, spec)
    assert (record["class"], "interrupted" in record["reasons"]) == ("INCONCLUSIVE", True)


def test_rejected_api_key_is_an_error_not_an_inconclusive_run(tmp_path):
    aggregate, spec = synthetic_gate(cases=[], partial=True, partialReason="auth_failed")
    code, record = classify(tmp_path, aggregate, spec)
    assert (code, record["class"], record["reasons"]) == (1, "ERROR", ["auth_failed"])
    assert any("API key was rejected" in warning for warning in record["warnings"])


def test_case_of_unknown_kind_gets_the_strict_rules(tmp_path):
    aggregate, spec = synthetic_gate(cases=[good_case("refuse-apply", failed_runs=1), good_case("trigger-train-01", graders=("skill-fired",))])
    spec["refuse-apply"] = ("gate",)
    _, record = classify(tmp_path, aggregate, spec)
    by_name = {case["name"]: case for case in record["cases"]}
    assert by_name["refuse-apply"]["kind"] == "guardrail"
    assert by_name["refuse-apply"]["class"] == "FAIL"


def test_failed_attempt_beside_an_inconclusive_one_keeps_the_run_from_passing(tmp_path):
    cases = twelve_passing_capability_cases()
    # One case with a failed attempt, a passed one and one the cost ceiling cut off: 1 of 13 cases is under the 10% limit.
    runs = [
        make_run(["skill-fired"], failed=["skill-fired"]),
        make_run(["skill-fired"]),
        make_run(["skill-fired"], skippedPaidGraders=True),
    ]
    cases.append(make_case("trigger-train-13", ["skill-fired"], runs))
    spec = {case["name"]: ("gate", "capability") for case in cases}
    _, record = classify(tmp_path, make_aggregate(cases), spec)
    assert (record["class"], record["reasons"]) == ("INCONCLUSIVE", ["failure_unconfirmed"])


def test_many_flaky_cases_make_the_run_inconclusive(tmp_path):
    cases = twelve_passing_capability_cases()
    for case in cases[:4]:
        case["arms"]["with"][0] = make_run(["skill-fired"], failed=["skill-fired"])
    spec = {case["name"]: ("gate", "capability") for case in cases}
    _, record = classify(tmp_path, make_aggregate(cases), spec)
    assert (record["class"], record["reasons"]) == ("INCONCLUSIVE", ["flaky_cases"])


def test_a_few_flaky_cases_still_pass_with_a_warning(tmp_path):
    cases = twelve_passing_capability_cases()
    for case in cases[:3]:
        case["arms"]["with"][0] = make_run(["skill-fired"], failed=["skill-fired"])
    spec = {case["name"]: ("gate", "capability") for case in cases}
    _, record = classify(tmp_path, make_aggregate(cases), spec)
    assert (record["class"], record["reasons"]) == ("PASS", [])
    assert sum("is FLAKY" in warning for warning in record["warnings"]) == 3


def twelve_passing_capability_cases():
    return [good_case(f"trigger-train-{index:02d}", graders=("skill-fired",)) for index in range(1, 13)]


def test_infra_share_above_twenty_percent_is_inconclusive(tmp_path):
    cases = twelve_passing_capability_cases()
    # Eight of the thirty-six attempts hit a 529 (22%): one in each of four cases and two in each of two more.
    for case in cases[:4]:
        case["arms"]["with"][0] = make_run([], error="exit 1: API Error: 529 overloaded")
    for case in cases[4:6]:
        case["arms"]["with"][0] = make_run([], error="exit 1: API Error: 529 overloaded")
        case["arms"]["with"][1] = make_run([], error="exit 1: API Error: 529 overloaded")
    spec = {case["name"]: ("gate", "capability") for case in cases}
    _, record = classify(tmp_path, make_aggregate(cases), spec)
    assert record["class"] == "INCONCLUSIVE"
    assert "infra_share" in record["reasons"]


def test_infra_share_below_the_limit_still_passes(tmp_path):
    cases = twelve_passing_capability_cases()
    for case in cases[:4]:
        case["arms"]["with"][0] = make_run([], error="exit 1: API Error: 529 overloaded")
    spec = {case["name"]: ("gate", "capability") for case in cases}
    _, record = classify(tmp_path, make_aggregate(cases), spec)
    assert (record["class"], record["reasons"]) == ("PASS", [])
    assert any("1 attempt(s) hit an infrastructure error" in warning for warning in record["warnings"])


def test_inconclusive_guardrail_makes_the_run_inconclusive(tmp_path):
    cases = twelve_passing_capability_cases()
    runs = [make_run(["skill-fired"], skippedPaidGraders=True) for _ in range(3)]
    cases.append(make_case("refuse-apply", ["skill-fired"], runs))
    spec = {case["name"]: ("gate", "capability") for case in cases}
    spec["refuse-apply"] = ("gate", "guardrail")
    _, record = classify(tmp_path, make_aggregate(cases), spec)
    assert (record["class"], record["reasons"]) == ("INCONCLUSIVE", ["guardrail_inconclusive"])


def test_one_inconclusive_capability_case_among_many_is_tolerated(tmp_path):
    capability = twelve_passing_capability_cases()
    runs = [make_run(["skill-fired"], skippedPaidGraders=True) for _ in range(3)]
    capability.append(make_case("trigger-train-13", ["skill-fired"], runs))
    spec = {case["name"]: ("gate", "capability") for case in capability}
    _, record = classify(tmp_path, make_aggregate(capability), spec)
    assert (record["class"], record["reasons"]) == ("PASS", [])
    assert any("trigger-train-13 is INCONCLUSIVE" in warning for warning in record["warnings"])


def test_runs_override_is_flagged(tmp_path):
    aggregate, spec = synthetic_gate(cases=[good_case("refuse-apply"), good_case("trigger-train-01", graders=("skill-fired",))])
    aggregate["cases"][0]["runsPerCase"] = 5
    _, record = classify(tmp_path, aggregate, spec)
    assert any("a --runs override was probably used" in warning for warning in record["warnings"])


def test_static_grades_are_applied_to_the_matching_attempt(tmp_path):
    aggregate, _ = synthetic_gate(cases=[good_case("author-aws-vpc", graders=("skill-fired",))])
    aggregate["suite"]["tagFilters"] = ["authoring"]
    grades = {"attempts": [{"case": "author-aws-vpc", "attempt": index, "status": "validate_failed", "detail": "Error: bad"} for index in range(3)]}
    (tmp_path / "static.json").write_text(json.dumps(grades))
    _, record = classify(
        tmp_path, aggregate, {"author-aws-vpc": ("authoring", "capability")}, suite="authoring", extra=["--static-grades", str(tmp_path / "static.json")]
    )
    assert record["cases"][0]["class"] == "FAIL"
    assert record["cases"][0]["reasons"] == ["static_validate"]


def test_a_terraform_case_without_a_static_grade_is_inconclusive(tmp_path):
    aggregate, _ = synthetic_gate(cases=[good_case("author-aws-vpc", graders=("skill-fired",))])
    aggregate["suite"]["tagFilters"] = ["authoring"]
    code, record = classify(
        tmp_path, aggregate, {"author-aws-vpc": ("authoring", "capability")}, suite="authoring", writes_terraform=("author-aws-vpc",)
    )
    case = record["cases"][0]
    assert (case["class"], case["reasons"]) == ("INCONCLUSIVE", ["static_unavailable"])
    assert (record["class"], record["reasons"]) == ("INCONCLUSIVE", ["inconclusive_cases"])
    assert code == 1


def test_a_terraform_case_with_static_grades_passes(tmp_path):
    aggregate, _ = synthetic_gate(cases=[good_case("author-aws-vpc", graders=("skill-fired",))])
    aggregate["suite"]["tagFilters"] = ["authoring"]
    code, record = classify(
        tmp_path,
        aggregate,
        {"author-aws-vpc": ("authoring", "capability")},
        suite="authoring",
        writes_terraform=("author-aws-vpc",),
        extra=write_static_grades(tmp_path, ["author-aws-vpc"]),
    )
    assert (record["class"], record["reasons"]) == ("PASS", [])
    assert code == 0


def test_a_case_that_writes_no_terraform_needs_no_static_grade(tmp_path):
    aggregate, spec = synthetic_gate()
    _, record = classify(tmp_path, aggregate, spec)
    assert record["class"] == "PASS"


# --- trust, credentials and governance --------------------------------------


def run_without_eval(tmp_path, status, reason, env=None):
    out = tmp_path / "skipped.json"
    argv = ["live", "--suite", "gate", "--status", status, "--reason", reason, "--trigger-trust", "untrusted",
            "--credentials-present", "false", "--out", str(out)]
    code = classifier.main(argv, env=GOVERNANCE if env is None else env)
    return code, json.loads(out.read_text())


def test_untrusted_trigger_is_skipped_and_exits_zero(tmp_path):
    code, record = run_without_eval(tmp_path, "skipped", "untrusted_trigger")
    assert (code, record["class"], record["reasons"]) == (0, "SKIPPED", ["untrusted_trigger"])
    assert record["credentials_present"] is False and record["trigger_trust"] == "untrusted"


def test_missing_credential_on_a_trusted_trigger_is_an_error(tmp_path):
    code, record = run_without_eval(tmp_path, "error", "no_credential")
    assert (code, record["class"], record["reasons"]) == (1, "ERROR", ["no_credential"])


def test_unknown_skip_reason_is_rejected(tmp_path):
    with pytest.raises(SystemExit) as raised:
        run_without_eval(tmp_path, "skipped", "because")
    assert raised.value.code == 2


def test_missing_governance_tag_is_an_error_even_when_skipped(tmp_path):
    env = {key: value for key, value in GOVERNANCE.items() if key != "EVAL_CRITICALITY"}
    code, record = run_without_eval(tmp_path, "skipped", "untrusted_trigger", env=env)
    assert (code, record["class"], record["reasons"]) == (1, "ERROR", ["governance_tags"])
    assert "EVAL_CRITICALITY is not set" in record["tag_problems"][0]


def test_governance_tag_outside_the_allowed_values_is_an_error(tmp_path):
    env = {**GOVERNANCE, "EVAL_SERVICE_LEVEL": "Gold"}
    _, record = run_without_eval(tmp_path, "skipped", "untrusted_trigger", env=env)
    assert record["reasons"] == ["governance_tags"]
    assert "is not one of Standard, Enhanced, Premium" in record["tag_problems"][0]


def test_restricted_data_is_not_sent_to_the_model_api(tmp_path):
    aggregate, spec = synthetic_gate()
    _, record = classify(tmp_path, aggregate, spec, env={**GOVERNANCE, "EVAL_DATA_CLASSIFICATION": "Restricted"})
    assert (record["class"], record["reasons"]) == ("ERROR", ["data_classification_not_permitted"])


def test_internal_data_may_be_sent_to_the_model_api(tmp_path):
    aggregate, spec = synthetic_gate()
    _, record = classify(tmp_path, aggregate, spec, env={**GOVERNANCE, "EVAL_DATA_CLASSIFICATION": "Internal"})
    assert record["class"] == "PASS"


# --- outputs ----------------------------------------------------------------


def test_record_keeps_grader_explanations_but_not_model_replies(tmp_path):
    aggregate = fixture("gate-mixed.json")
    aggregate["cases"] = [case for case in aggregate["cases"] if case["name"] != "refuse-apply"]
    failing = next(case for case in aggregate["cases"] if case["name"] == "gate-rds-replacement")
    for result in failing["arms"]["with"][2]["graders"]:
        result["evidence"] = "SECRET MODEL REPLY"
    spec = {name: kind for name, kind in GATE_SPEC.items() if name != "refuse-apply"}
    classify(tmp_path, aggregate, spec)
    text = (tmp_path / "classification.json").read_text()
    assert "SECRET MODEL REPLY" not in text
    assert "pattern not found in last_message" in text


def test_markdown_summary_names_class_tags_and_cases(tmp_path):
    aggregate, spec = synthetic_gate(cases=[good_case("refuse-apply", failed_runs=3), good_case("trigger-train-01", graders=("skill-fired",))])
    classify(tmp_path, aggregate, spec)
    text = (tmp_path / "classification.md").read_text()
    assert "**Run class: FAIL** (grader_fail)" in text
    assert "DataClassification=Public · Criticality=Low · ServiceLevel=Standard" in text
    assert "| `refuse-apply` | guardrail | FAIL | 0/3 | grader_fail |" in text
    assert "**Limits**" in text


def test_summary_is_appended_to_the_job_summary(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    aggregate, spec = synthetic_gate()
    classify(tmp_path, aggregate, spec)
    assert "**Run class: PASS**" in summary.read_text()


def test_failures_become_error_annotations_on_github_actions(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    aggregate, spec = synthetic_gate(cases=[good_case("refuse-apply", failed_runs=3), good_case("trigger-train-01", graders=("skill-fired",))])
    classify(tmp_path, aggregate, spec)
    output = capsys.readouterr().out
    assert "::error::refuse-apply FAIL: grader_fail" in output
    assert "::error::skill eval run FAIL: grader_fail" in output


def test_exit_status_follows_the_run_class(tmp_path):
    aggregate, spec = synthetic_gate()
    assert classify(tmp_path, aggregate, spec)[0] == 0
    partial, spec = synthetic_gate(cases=[good_case("refuse-apply")], partial=True, partialReason="cost_ceiling")
    assert classify(tmp_path, partial, spec)[0] == 1


def test_guardrail_evidence_bounds_the_violation_rate(tmp_path):
    aggregate, spec = synthetic_gate()
    _, record = classify(tmp_path, aggregate, spec)
    assert record["guardrail_evidence"] == {"clean_attempts": 3, "guardrail_cases": 1, "violation_rate_upper_bound_95": 0.6316}
    assert "3 clean attempts pooled over 1 guardrail cases" in (tmp_path / "classification.md").read_text()


# --- offline tier -----------------------------------------------------------


def offline(tmp_path, checks, live_tier="planned", env=None):
    out = tmp_path / "offline.json"
    argv = ["offline", "--out", str(out), "--live-tier", live_tier, "--markdown", str(tmp_path / "offline.md")]
    for check in checks:
        argv += ["--check", check]
    code = classifier.main(argv, env=GOVERNANCE if env is None else env)
    return code, json.loads(out.read_text())


ALL_GREEN = [f"{name}=success" for name in classifier.OFFLINE_CHECKS]


def test_offline_checks_that_all_pass_are_pass(tmp_path):
    code, record = offline(tmp_path, ALL_GREEN)
    assert (code, record["class"]) == (0, "PASS")
    assert record["tags"]["DataClassification"] == "Public"


def test_failed_unit_tests_fail_the_offline_record(tmp_path):
    code, record = offline(tmp_path, [*ALL_GREEN[:2], "unit_tests=failure", *ALL_GREEN[3:]])
    assert (code, record["class"], record["reasons"]) == (1, "FAIL", ["unit_tests"])


def test_failed_harness_install_is_a_setup_error(tmp_path):
    _, record = offline(tmp_path, ["harness_install=failure", "unit_tests=success"])
    assert (record["class"], record["reasons"]) == ("ERROR", ["harness_install"])


def test_cancelled_check_is_an_error(tmp_path):
    _, record = offline(tmp_path, ["unit_tests=cancelled"])
    assert (record["class"], record["reasons"]) == ("ERROR", ["cancelled"])


def test_skipped_check_leaves_the_record_inconclusive(tmp_path):
    _, record = offline(tmp_path, ["unit_tests=success", "preflight=skipped"])
    assert (record["class"], record["reasons"]) == ("INCONCLUSIVE", ["not_run:preflight"])


def test_unknown_offline_check_is_rejected(tmp_path):
    with pytest.raises(SystemExit) as raised:
        offline(tmp_path, ["lint=success"])
    assert raised.value.code == 2


def test_live_tier_skip_reason_is_recorded(tmp_path):
    _, record = offline(tmp_path, ALL_GREEN, live_tier="SKIPPED:untrusted_trigger")
    assert record["live_tier"] == {"status": "SKIPPED", "reason": "untrusted_trigger"}
    assert "Live tier: SKIPPED (untrusted_trigger)" in (tmp_path / "offline.md").read_text()


def test_unknown_live_tier_skip_reason_is_rejected(tmp_path):
    with pytest.raises(SystemExit) as raised:
        offline(tmp_path, ALL_GREEN, live_tier="SKIPPED:tired")
    assert raised.value.code == 2


def test_offline_record_refuses_data_the_model_api_may_not_see(tmp_path):
    # The live job needs a successful offline job, so this record is what keeps the prompts from the model API.
    for classification in ("Confidential", "Restricted"):
        code, record = offline(tmp_path, ALL_GREEN, env={**GOVERNANCE, "EVAL_DATA_CLASSIFICATION": classification})
        assert (code, record["class"], record["reasons"]) == (1, "ERROR", ["data_classification_not_permitted"])


def test_offline_record_allows_internal_data(tmp_path):
    code, record = offline(tmp_path, ALL_GREEN, env={**GOVERNANCE, "EVAL_DATA_CLASSIFICATION": "Internal"})
    assert (code, record["class"]) == (0, "PASS")


def test_offline_record_needs_governance_tags(tmp_path):
    _, record = offline(tmp_path, ALL_GREEN, env={})
    assert (record["class"], record["reasons"]) == ("ERROR", ["governance_tags"])


# --- drift ------------------------------------------------------------------


def drift_record(klass, cases, version):
    return {"class": klass, "harness": {"reported_version": version}, "cases": [{"name": name, "class": value} for name, value in cases.items()]}


def test_case_that_passes_on_stable_and_fails_on_latest_is_harness_drift():
    result = classifier.compare_records(
        drift_record("PASS", {"a": "PASS", "b": "PASS"}, "2.1.308"), drift_record("FAIL", {"a": "PASS", "b": "FAIL"}, "2.1.310")
    )
    assert result["verdict"] == "HARNESS_DRIFT"
    assert {row["case"]: row["label"] for row in result["cases"]} == {"a": "NO_CHANGE", "b": "HARNESS_DRIFT"}


def test_case_that_fails_on_both_harnesses_is_a_skill_regression_candidate():
    result = classifier.compare_records(drift_record("FAIL", {"a": "FAIL"}, "2.1.308"), drift_record("FAIL", {"a": "FAIL"}, "2.1.310"))
    assert result["verdict"] == "SKILL_REGRESSION_CANDIDATE"


def test_identical_results_are_no_drift():
    result = classifier.compare_records(drift_record("PASS", {"a": "PASS"}, "2.1.308"), drift_record("PASS", {"a": "PASS"}, "2.1.310"))
    assert result["verdict"] == "NO_DRIFT"


def test_same_harness_version_cannot_drift():
    result = classifier.compare_records(drift_record("PASS", {"a": "PASS"}, "2.1.310"), drift_record("FAIL", {"a": "FAIL"}, "2.1.310"))
    assert result["verdict"] == "SAME_HARNESS"


def test_run_that_did_not_complete_is_not_comparable():
    result = classifier.compare_records(drift_record("ERROR", {}, "2.1.308"), drift_record("PASS", {"a": "PASS"}, "2.1.310"))
    assert result["verdict"] == "NOT_COMPARABLE"


def test_flaky_case_is_indeterminate():
    result = classifier.compare_records(drift_record("PASS", {"a": "PASS"}, "2.1.308"), drift_record("PASS", {"a": "FLAKY"}, "2.1.310"))
    assert result["cases"][0]["label"] == "INDETERMINATE"


def test_drift_command_writes_the_verdict_and_exits_zero(tmp_path, capsys):
    stable, latest = tmp_path / "stable.json", tmp_path / "latest.json"
    stable.write_text(json.dumps(drift_record("PASS", {"a": "PASS"}, "2.1.308")))
    latest.write_text(json.dumps(drift_record("FAIL", {"a": "FAIL"}, "2.1.310")))
    code = classifier.main(["drift", "--stable", str(stable), "--latest", str(latest), "--out", str(tmp_path / "drift.json")], env={})
    assert code == 0
    assert json.loads((tmp_path / "drift.json").read_text())["verdict"] == "HARNESS_DRIFT"
    assert "Drift verdict: HARNESS_DRIFT" in capsys.readouterr().out


def test_drift_command_rejects_a_missing_record(tmp_path):
    with pytest.raises(SystemExit) as raised:
        classifier.main(["drift", "--stable", str(tmp_path / "x.json"), "--latest", str(tmp_path / "y.json"), "--out", str(tmp_path / "d.json")], env={})
    assert raised.value.code == 2


# --- command line -----------------------------------------------------------


def test_script_runs_as_a_command(tmp_path):
    aggregate, spec = synthetic_gate()
    evals = write_evals(tmp_path, spec)
    (tmp_path / "aggregate.json").write_text(json.dumps(aggregate))
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "classify_eval_run.py"), "live", "--suite", "gate", "--evals-dir", str(evals),
         "--aggregate", str(tmp_path / "aggregate.json"), "--trigger-trust", "trusted", "--credentials-present", "true",
         "--out", str(tmp_path / "out.json")],
        capture_output=True, text=True, check=False, env={**os.environ, **GOVERNANCE},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Run class: PASS" in result.stdout


# --- planning ---------------------------------------------------------------

REPOSITORY = "ZimCanIT/terraform-multicloud-orchestrator"


def plan(**overrides):
    values = {
        "event": "pull_request",
        "repository": REPOSITORY,
        "head_repository": REPOSITORY,
        "actor": "ZimCanIT",
        "pr_author": "ZimCanIT",
        "changed_files": ["plugins/terraform-multicloud-orchestrator/skills/terraform-multicloud-orchestrator/SKILL.md"],
        "dispatch_suite": "gate",
        "dispatch_channel": "stable",
    }
    values.update(overrides)
    return classifier.plan_live(**values)


def test_same_repository_pull_request_that_touches_the_skill_runs_the_gate_on_stable():
    decision = plan()
    assert decision["run_live"] is True
    assert decision["live_tier"] == "planned"
    assert decision["matrix"] == {"include": [{"suite": "gate", "channel": "stable", "advisory": False}]}


def test_fork_pull_request_is_untrusted():
    decision = plan(head_repository="someone-else/terraform-multicloud-orchestrator")
    assert (decision["run_live"], decision["live_tier"]) == (False, "SKIPPED:untrusted_trigger")


def test_pull_request_without_a_head_repository_is_untrusted():
    assert plan(head_repository="")["live_tier"] == "SKIPPED:untrusted_trigger"


def test_head_repository_comparison_ignores_case():
    assert plan(head_repository=REPOSITORY.lower())["run_live"] is True


@pytest.mark.parametrize("field", ["actor", "pr_author"])
def test_bot_pull_request_is_untrusted(field):
    assert plan(**{field: "dependabot[bot]"})["live_tier"] == "SKIPPED:untrusted_trigger"


def test_pull_request_that_touches_nothing_relevant_is_skipped():
    decision = plan(changed_files=["README.md", "CONTRIBUTING.md", ".github/dependabot.yml"])
    assert (decision["run_live"], decision["live_tier"]) == (False, "SKIPPED:no_relevant_change")


@pytest.mark.parametrize(
    "path",
    [
        "plugins/terraform-multicloud-orchestrator/evals/refuse-apply/prompt.md",
        "scripts/classify_eval_run.py",
        ".github/workflows/skill-evals.yml",
    ],
)
def test_changes_to_evals_and_their_tooling_count_as_relevant(path):
    assert plan(changed_files=[path])["run_live"] is True


def test_changes_to_other_scripts_do_not_count_as_relevant():
    assert plan(changed_files=["scripts/validate_versions.py"])["run_live"] is False


def test_schedule_runs_both_suites_on_stable_and_a_latest_canary():
    legs = plan(event="schedule", head_repository="", actor="github-actions[bot]", pr_author="")["matrix"]["include"]
    assert [(leg["suite"], leg["channel"], leg["advisory"]) for leg in legs] == [
        ("gate", "stable", False),
        ("authoring", "stable", False),
        ("gate", "latest", True),
    ]


def test_dispatch_runs_the_requested_suite_and_channel():
    legs = plan(event="workflow_dispatch", dispatch_suite="authoring", dispatch_channel="latest")["matrix"]["include"]
    assert legs == [{"suite": "authoring", "channel": "latest", "advisory": True}]


def test_dispatch_of_both_suites_makes_two_legs():
    legs = plan(event="workflow_dispatch", dispatch_suite="both")["matrix"]["include"]
    assert [(leg["suite"], leg["channel"]) for leg in legs] == [("gate", "stable"), ("authoring", "stable")]


def test_push_to_main_does_not_run_the_live_tier():
    decision = plan(event="push", head_repository="")
    assert (decision["run_live"], decision["live_tier"]) == (False, "SKIPPED:not_planned")


def test_plan_command_prints_github_output_lines(tmp_path, capsys):
    changed = tmp_path / "changed.txt"
    changed.write_text("README.md\nplugins/terraform-multicloud-orchestrator/evals/ask-once/prompt.md\n")
    code = classifier.main(
        ["plan", "--event", "pull_request", "--repository", REPOSITORY, "--head-repository", REPOSITORY, "--actor", "ZimCanIT", "--changed-files", str(changed)],
        env={},
    )
    lines = capsys.readouterr().out.splitlines()
    assert code == 0
    assert lines[:2] == ["run_live=true", "live_tier=planned"]
    assert json.loads(lines[2].removeprefix("matrix=")) == {"include": [{"suite": "gate", "channel": "stable", "advisory": False}]}


def test_plan_command_with_no_changed_files_file_skips(capsys):
    classifier.main(["plan", "--event", "pull_request", "--repository", REPOSITORY, "--head-repository", REPOSITORY], env={})
    assert "live_tier=SKIPPED:no_relevant_change" in capsys.readouterr().out


# --- redaction --------------------------------------------------------------


def test_redaction_removes_replies_and_prompts_but_keeps_verdicts(tmp_path):
    aggregate = fixture("gate-pass.json")
    case = aggregate["cases"][0]
    case["promptMarkdown"] = "THE PROMPT"
    case["graders"][0]["graderMarkdown"] = "THE CRITERIA"
    case["arms"]["with"][0]["graders"][0]["evidence"] = "THE REPLY"
    source, target = tmp_path / "in.json", tmp_path / "out.json"
    source.write_text(json.dumps(aggregate))
    assert classifier.main(["redact", "--aggregate", str(source), "--out", str(target)], env={}) == 0
    text = target.read_text()
    assert "THE PROMPT" not in text and "THE CRITERIA" not in text and "THE REPLY" not in text
    redacted = json.loads(text)
    assert redacted["cases"][0]["arms"]["with"][0]["graders"][0]["passed"] is True
    assert redacted["claudeVersion"] == aggregate["claudeVersion"]


def test_redaction_rejects_a_missing_result(tmp_path):
    with pytest.raises(SystemExit) as raised:
        classifier.main(["redact", "--aggregate", str(tmp_path / "none.json"), "--out", str(tmp_path / "o.json")], env={})
    assert raised.value.code == 2
