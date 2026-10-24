"""Tests that the regex graders of the checked-in cases accept what they should and catch what they claim to.

A grader that can never fail, or that misses the common spelling of what it hunts, looks like a
guard and guards nothing. Each test runs a case's real pattern, with the real flags, in Node's
RegExp (the engine `claude plugin eval` uses) against short samples of HCL or prose.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(os.environ.get("VALIDATOR_SCRIPTS_DIR") or REPO_ROOT / "scripts")
EVALS = REPO_ROOT / "plugins" / "terraform-multicloud-orchestrator" / "evals"
sys.path.insert(0, str(SCRIPTS_DIR))

import eval_suite  # noqa: E402

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js, the engine the eval runner uses")
AUTHORING_CASES = ("author-aws-vpc", "author-azure-storage", "author-gcp-network", "author-oci-network")
TEST_SCRIPT = (
    "const items = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
    "process.stdout.write(JSON.stringify(items.map(([pattern, flags, text]) => new RegExp(pattern, flags).test(text))));"
)


def grader_of(case: str, name: str) -> eval_suite.Grader:
    for candidate in eval_suite.load_case(EVALS / case).graders:
        if candidate.name == name:
            return candidate
    raise AssertionError(f"{case} has no grader {name}")


def passes(grader: eval_suite.Grader, texts: list[str]) -> list[bool]:
    """Whether the grader would pass for each text, by the rule the runner applies to a regex grader."""
    items = [[grader.meta["pattern"], grader.meta.get("flags", ""), text] for text in texts]
    result = subprocess.run(["node", "-e", TEST_SCRIPT], input=json.dumps(items), capture_output=True, text=True, check=True)
    found = json.loads(result.stdout)
    wanted = grader.meta.get("match", "contains") == "contains"
    return [hit == wanted for hit in found]


# --- ask-once: no resource block before the questions -------------------------


@needs_node
def test_no_hcl_yet_catches_resource_types_with_digits():
    grader = grader_of("ask-once", "no-hcl-yet")
    hcl = [
        'resource "aws_s3_bucket" "logs" {',
        'resource "aws_ec2_transit_gateway" "main" {',
        'resource "aws_route53_zone" "z" {',
        'resource  "google_compute_network_v2"   "net" {',
    ]
    assert passes(grader, hcl) == [False] * len(hcl)


@needs_node
def test_no_hcl_yet_lets_questions_and_prose_through():
    grader = grader_of("ask-once", "no-hcl-yet")
    prose = [
        "Which cloud should this target, and which pinning strategy do you want?",
        "A resource is declared with a block, for example a VPC.",
    ]
    assert passes(grader, prose) == [True, True]


# --- gate: graders that look for a name or a phrase ------------------------------


@needs_node
def test_names_resource_accepts_the_spellings_a_terraform_address_takes():
    # A real reply wrote `aws_db_instance.orders_db` for the pasted `orders-db`, which a literal pattern missed.
    grader = grader_of("gate-rds-replacement", "names-resource")
    named = ["aws_db_instance.orders_db", "`orders-db`", "the orders db instance", "Orders-DB", "ordersdb"]
    assert passes(grader, named) == [True] * len(named)
    assert passes(grader, ["the database instance", "orders_cache", "an order database"]) == [False] * 3


@needs_node
def test_states_plan_only_accepts_a_hyphen_or_a_space():
    grader = grader_of("refuse-apply", "states-plan-only")
    assert passes(grader, ["This skill is plan-only.", "I work plan only", "PLAN-ONLY"]) == [True] * 3
    assert passes(grader, ["I only plan", "planning only", "apply is not available"]) == [False] * 3


@needs_node
def test_removed_block_accepts_the_ways_a_reply_names_it():
    grader = grader_of("refuse-state-rm", "removed-block")
    named = ["Use a `removed` block", "Removed block with lifecycle", "removed {\n  from = aws_x.y", "REMOVED {"]
    assert passes(grader, named) == [True] * len(named)
    assert passes(grader, ["terraform state rm aws_x.y", "the resource was removed from the console"]) == [False] * 2


# --- authoring: the echoed session configuration ----------------------------------

PINNING_BY_CASE = [
    ("author-aws-vpc", "pessimistic-minor"),
    ("author-azure-storage", "exact"),
    ("author-gcp-network", "pessimistic-patch"),
    ("author-oci-network", "latest-stable-and-pin"),
]


@needs_node
@pytest.mark.parametrize(("case", "strategy"), PINNING_BY_CASE)
def test_session_config_accepts_the_label_a_reply_may_write(case, strategy):
    # A real reply wrote "Session config" where the skill's block says SESSION CONFIG, and failed a
    # case-sensitive pattern while it had done exactly what was asked.
    grader = grader_of(case, "session-config")
    replies = [
        f"SESSION CONFIG\n- Clouds: x\n- Pinning: {strategy}",
        f"**Session config**\n- Clouds: x\n- Pinning: {strategy}\n",
        f"## Session config\n\n**Pinning:** `{strategy}`",
        f"SESSION CONFIG\nPinning strategy: {strategy}",
    ]
    assert passes(grader, replies) == [True] * len(replies)


@needs_node
@pytest.mark.parametrize(("case", "strategy"), PINNING_BY_CASE)
def test_session_config_still_fails_without_the_block_or_the_strategy(case, strategy):
    grader = grader_of(case, "session-config")
    other = "exact" if strategy != "exact" else "pessimistic-minor"
    replies = [f"SESSION CONFIG\n- Pinning: {other}", f"Pinning: {strategy}", "SESSION CONFIG only", ""]
    assert passes(grader, replies) == [False] * len(replies)


# --- authoring: no literal secret ----------------------------------------------

# These are invented samples. Each flagged line carries the allowlist pragma, and the key header is split
# in the source so that the private-key hook does not take the file for a key.
LITERAL_SECRETS = [
    'secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"',  # pragma: allowlist secret
    'access_key = "AKIAIOSFODNN7EXAMPLE"',  # pragma: allowlist secret
    'aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG"',  # pragma: allowlist secret
    'administrator_login_password = "P@ssw0rd1234"',  # pragma: allowlist secret
    '  password = "hunter2hunter2"',  # pragma: allowlist secret
    'client_secret = "abcdefgh-1234"',  # pragma: allowlist secret
    'private_key = "-----BEGIN RSA PRIV' 'ATE KEY-----"',  # pragma: allowlist secret
    'default = "AKIAIOSFODNN7EXAMPLE"',  # pragma: allowlist secret
    'api_key = "0123456789abcdef"',
    'SECRET_TOKEN = "abcdefghij"',
]
NOT_SECRETS = [
    "password = var.db_password",
    'password = "${var.db_password}"',
    'description = "The password for the database administrator"',
    'secret_id = "${var.name}-secret"',
    'token_ttl = "3600"',
    'name = "app-logs"',
    "access_key = random_password.key.result",
    'kms_key_id = "alias/aws/s3"',
]


@needs_node
@pytest.mark.parametrize("case", AUTHORING_CASES)
@pytest.mark.parametrize(("name", "path"), [("no-literal-secret", "main.tf"), ("no-literal-secret-variables", "variables.tf")])
def test_secret_graders_fail_on_a_literal_credential(case, name, path):
    grader = grader_of(case, name)
    assert grader.meta["target"] == {"source": "file", "path": path}
    assert passes(grader, LITERAL_SECRETS) == [False] * len(LITERAL_SECRETS)


@needs_node
@pytest.mark.parametrize("case", AUTHORING_CASES)
def test_secret_graders_pass_on_references_and_prose(case):
    for name in ("no-literal-secret", "no-literal-secret-variables"):
        assert passes(grader_of(case, name), NOT_SECRETS) == [True] * len(NOT_SECRETS)


# --- authoring: every variable and output is described --------------------------

DESCRIBED_VARIABLES = """\
variable "name" {
  type        = string
  description = "Name prefix"
}

variable "tags" {
  description = "Tags"
  type        = map(string)
  default     = {}
}

variable "subnets" {
  type = object({
    cidr = string
  })
  description = "Subnet settings"
}
"""
UNDESCRIBED_FIRST = 'variable "name" {\n  type = string\n}\n\nvariable "tags" {\n  description = "Tags"\n  type = map(string)\n}\n'
UNDESCRIBED_LAST = 'variable "tags" {\n  description = "Tags"\n  type = map(string)\n}\n\nvariable "name" {\n  type = string\n  default = "x"\n}\n'
UNDESCRIBED_NESTED = 'variable "cfg" {\n  type = object({\n    a = string\n  })\n}\n'
UNDESCRIBED_EMPTY = 'variable "name" {}\n'


@needs_node
@pytest.mark.parametrize("case", AUTHORING_CASES)
def test_variable_grader_passes_when_every_block_has_a_description(case):
    grader = grader_of(case, "no-undescribed-variable")
    assert grader.meta["target"] == {"source": "file", "path": "variables.tf"}
    assert passes(grader, [DESCRIBED_VARIABLES]) == [True]


@needs_node
@pytest.mark.parametrize("case", AUTHORING_CASES)
@pytest.mark.parametrize("sample", [UNDESCRIBED_FIRST, UNDESCRIBED_LAST, UNDESCRIBED_NESTED, UNDESCRIBED_EMPTY])
def test_variable_grader_fails_when_any_block_lacks_one(case, sample):
    assert passes(grader_of(case, "no-undescribed-variable"), [sample]) == [False]


@needs_node
@pytest.mark.parametrize("case", AUTHORING_CASES)
def test_output_grader_checks_each_output_block(case):
    grader = grader_of(case, "no-undescribed-output")
    assert grader.meta["target"] == {"source": "file", "path": "outputs.tf"}
    described = 'output "vpc_id" {\n  description = "The VPC id"\n  value       = aws_vpc.main.id\n}\n'
    assert passes(grader, [described]) == [True]
    missing_second = described + '\noutput "subnet_ids" {\n  value = aws_subnet.private[*].id\n}\n'
    assert passes(grader, [missing_second]) == [False]
    assert passes(grader, ['output "x" {}\n']) == [False]


@needs_node
@pytest.mark.parametrize("case", AUTHORING_CASES)
def test_presence_graders_still_fail_on_an_empty_file(case):
    # A not_contains grader passes on an empty file, so the presence graders must stay beside them.
    for name in ("variables-described", "outputs-described"):
        assert passes(grader_of(case, name), [""]) == [False]
