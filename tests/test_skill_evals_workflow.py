"""Checks on .github/workflows/skill-evals.yml that no other test reaches.

They read the workflow as text and as YAML and guard what a later edit could break without a visible
failure: the cost ceilings stay above what a suite at its attempt cap costs, every eval test module
runs in CI, Terraform is installed before the steps that use it, the API key reaches one step only,
permissions stay read-only and actions stay pinned.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(os.environ.get("VALIDATOR_SCRIPTS_DIR") or REPO_ROOT / "scripts")
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "skill-evals.yml"
sys.path.insert(0, str(SCRIPTS_DIR))

import validate_evals  # noqa: E402


@pytest.fixture(scope="module")
def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def document(text: str) -> dict:
    return yaml.safe_load(text)


def steps_of(document: dict):
    for job_name, job in document["jobs"].items():
        for step in job["steps"]:
            yield job_name, step


def test_a_suite_at_its_cap_costs_well_under_the_ceiling_the_workflow_sets(text):
    found = set(re.findall(r"CEILING: \$\{\{ matrix\.suite == 'authoring' && '(\d+)' \|\| '(\d+)' \}\}", text))
    assert len(found) == 1, "the two steps that use a cost ceiling must agree"
    authoring, gate = (float(value) for value in found.pop())
    for suite_name, ceiling in {"gate": gate, "authoring": authoring}.items():
        worst_case = validate_evals.ATTEMPT_CAPS[suite_name] * validate_evals.MEASURED_COST_PER_ATTEMPT_USD[suite_name]
        assert worst_case <= 0.75 * ceiling, f"{suite_name}: {worst_case:.2f} against a ceiling of {ceiling:.2f}"


def test_the_workflow_runs_every_eval_test_module(text):
    command = re.search(r"python -m pytest\s+((?:tests/\S+\s+)+)-q", text)
    assert command, "the offline job must run the eval tooling tests with python -m pytest"
    listed = set(command.group(1).split())
    modules = {f"tests/{path.name}" for path in (REPO_ROOT / "tests").glob("test_*eval*.py")}
    assert modules <= listed, f"these test modules never run in CI: {sorted(modules - listed)}"


def test_terraform_is_installed_without_its_wrapper_before_any_step_that_uses_it(document):
    # The tests that run the real binary skip themselves when it is missing, so a lost install step would not fail a check.
    # The wrapper that setup-terraform can add changes what `terraform` prints and returns, which the grading reads.
    users = ("pytest", "grade_eval_workspaces.py")
    checked = 0
    for job_name, job in document["jobs"].items():
        steps = job["steps"]
        first_use = next((i for i, step in enumerate(steps) if any(word in str(step.get("run", "")) for word in users)), None)
        if first_use is None:
            continue
        installs = [i for i, step in enumerate(steps) if str(step.get("uses", "")).startswith("hashicorp/setup-terraform@")]
        assert installs and installs[0] < first_use, f"{job_name}: Terraform is not installed before its first use"
        assert steps[installs[0]]["with"].get("terraform_wrapper") is False, f"{job_name}: the wrapper changes terraform's output"
        checked += 1
    assert checked >= 2, "expected the offline and live jobs to use Terraform"


def test_the_api_key_reaches_one_step_only(document):
    assert "secrets." not in str(document.get("env", "")), "a secret in the workflow-level env reaches every step"
    carriers = []
    for job_name, job in document["jobs"].items():
        assert "secrets." not in str(job.get("env", "")), f"{job_name}: a secret in the job-level env reaches every step"
    for job_name, step in steps_of(document):
        assert "secrets." not in str(step.get("with", "")), f"{step['name']}: a secret passed as an input"
        assert "secrets." not in str(step.get("run", "")), f"{step['name']}: a secret expanded into a script"
        for key, value in (step.get("env") or {}).items():
            # Comparing the secret with '' hands the step a boolean, not the secret.
            if "secrets." in str(value) and "!=" not in str(value):
                carriers.append((job_name, step["name"], key))
    assert carriers == [("live", "Run the evals", "ANTHROPIC_API_KEY")]


def test_permissions_are_read_only_and_never_widened(document):
    assert document["permissions"] == {"contents": "read"}
    assert [name for name, job in document["jobs"].items() if "permissions" in job] == []


def test_every_action_is_pinned_to_a_commit_with_a_version_comment(text):
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)(.*)$", text, flags=re.MULTILINE)
    assert uses, "the workflow uses no actions, so this check has nothing to read"
    for target, rest in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", target), f"{target} is not pinned to a commit"
        assert re.match(r"\s+# v\d", rest), f"{target} has no version comment"
