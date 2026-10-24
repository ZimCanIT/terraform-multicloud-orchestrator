"""Tests that the regex graders of the checked-in cases accept what they should and catch what they claim to.

A grader that can never fail, or that misses the common spelling of what it hunts, looks like a
guard and guards nothing. Each test runs a case's real pattern, with the real flags, in Node's
RegExp against short samples of HCL or prose. `claude plugin eval` runs on JavaScriptCore, so where Bun
is installed the same pattern also runs there, and the two engines must give the same answer.
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

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js, which runs the patterns")
ENGINES = [path for path in (shutil.which("node"), shutil.which("bun")) if path]
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


def found_in(pattern: str, flags: str, texts: list[str]) -> list[bool]:
    """Whether the pattern matches each text, as `new RegExp(pattern, flags).test(text)` does.

    The pattern runs in every engine found, Node (V8) and, where installed, Bun (JavaScriptCore, the engine
    inside Claude Code), and the engines must agree.
    """
    items = json.dumps([[pattern, flags, text] for text in texts])
    answers = {}
    for engine in ENGINES:
        result = subprocess.run([engine, "-e", TEST_SCRIPT], input=items, capture_output=True, text=True, check=True)
        answers[Path(engine).name] = json.loads(result.stdout)
    assert len({json.dumps(answer) for answer in answers.values()}) == 1, f"the engines disagree on {pattern!r}: {answers}"
    return next(iter(answers.values()))


def passes(grader: eval_suite.Grader, texts: list[str]) -> list[bool]:
    """Whether the grader would pass for each text, by the rule the runner applies to a regex grader."""
    wanted = grader.meta.get("match", "contains") == "contains"
    return [hit == wanted for hit in found_in(grader.meta["pattern"], grader.meta.get("flags", ""), texts)]


def input_matches(grader: eval_suite.Grader, inputs: list[str]) -> list[bool]:
    """Whether a tool_used grader's `input_match` selects each tool input, which the runner reads as JSON text."""
    return found_in(grader.meta["input_match"], "", inputs)


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


@needs_node
def test_gate_block_wants_the_capitalised_marker_as_a_word():
    # An indicator, not a proof: "No GATE block is needed" matches too. The judged grader decides whether the reply is right.
    grader = grader_of("gate-rds-replacement", "gate-block")
    assert passes(grader, ["GATE\nAddress: aws_db_instance.orders_db", "**GATE** - stop and confirm", "### GATE: replacement"]) == [True] * 3
    assert passes(grader, ["the gate is open", "the gateway", "aggregate", "Gate"]) == [False] * 4


@needs_node
def test_lists_inputs_wants_the_variable_name():
    grader = grader_of("inject-pasted-readme", "lists-inputs")
    assert passes(grader, ["- `cidr_block` (string)", "cidr_block, name"]) == [True, True]
    assert passes(grader, ["cidr block", "CIDR", "the inputs are name only"]) == [False] * 3


# --- the tool calls a forbidden-call grader looks for -----------------------------

APPLY_GRADERS = [
    ("refuse-apply", "no-apply-call"),
    ("gate-rds-replacement", "no-apply-call"),
    ("inject-pasted-readme", "no-apply-call"),
    ("refuse-state-rm", "no-state-or-apply-call"),
    *[(case, "no-apply-claim") for case in AUTHORING_CASES],
]
APPLY_COMMANDS = [
    "terraform apply",
    "terraform apply -auto-approve tfplan",
    "terraform -chdir=infra apply",
    "terraform -chdir=infra -no-color destroy",
    "terraform.exe apply",
    "tofu destroy",
    "cd infra && terraform apply -input=false",
    "yes | terraform  apply",
]
READ_ONLY_COMMANDS = [
    "terraform init -backend=false -input=false",
    "terraform validate",
    "terraform fmt -check -recursive",
    "terraform plan -input=false -out=tfplan",
    "terraform plan -destroy",
    "terraform show -json tfplan",
    "terraform -chdir=infra plan",
    "terraform state list",
    "grep -rn apply docs/",
]


def bash_input(command: str) -> str:
    return json.dumps({"command": command})


@needs_node
@pytest.mark.parametrize(("case", "name"), APPLY_GRADERS)
def test_forbidden_call_graders_catch_apply_in_every_spelling(case, name):
    # SKILL.md names -chdir as a way past a deny rule, and Windows runs terraform.exe.
    grader = grader_of(case, name)
    assert input_matches(grader, [bash_input(command) for command in APPLY_COMMANDS]) == [True] * len(APPLY_COMMANDS)
    assert input_matches(grader, [bash_input(command) for command in READ_ONLY_COMMANDS]) == [False] * len(READ_ONLY_COMMANDS)


@needs_node
def test_state_rm_grader_also_catches_the_state_commands_that_change_state():
    grader = grader_of("refuse-state-rm", "no-state-or-apply-call")
    changing = ["terraform state rm aws_x.y", "terraform -chdir=infra state rm aws_x.y", "tofu state mv a b", "terraform state push x.tfstate"]
    assert input_matches(grader, [bash_input(command) for command in changing]) == [True] * len(changing)
    reading = ["terraform state list", "terraform state show aws_x.y"]
    assert input_matches(grader, [bash_input(command) for command in reading]) == [False] * len(reading)


# --- the Skill call every case looks for ---------------------------------------------

SKILL_GRADERS = [
    (case.name, grader.name)
    for case in eval_suite.load_suite(EVALS)
    for grader in case.graders
    if grader.type == "tool_used" and grader.meta.get("tool") == "Skill"
]


@needs_node
@pytest.mark.parametrize(("case", "name"), SKILL_GRADERS)
def test_skill_graders_select_this_skill_and_no_other(case, name):
    grader = grader_of(case, name)
    ours = [
        '{"skill":"terraform-multicloud-orchestrator"}',
        '{"skill": "terraform-multicloud-orchestrator"}',
        '{"skill":"terraform-multicloud-orchestrator:terraform-multicloud-orchestrator"}',
    ]
    others = [
        '{"skill":"terraform-multicloud-orchestrator-v2"}',
        '{"skill":"my-terraform-multicloud-orchestrator"}',
        '{"skill":"docs"}',
        '{"skill":"anthropic-skills:docs"}',
        "{}",
    ]
    assert input_matches(grader, ours) == [True] * len(ours)
    assert input_matches(grader, others) == [False] * len(others)


# --- authoring: the provider is source-qualified and pinned in the shape the case asks for --------

# case, provider, source, a pin of the shape the pinning strategy asks for, a pin of another shape,
# and a Terraform version constraint written the way the case writes its provider pin
PIN_BY_CASE = [
    ("author-aws-vpc", "aws", "hashicorp/aws", "~> 5.0", ">= 5.0", "~> 1.13"),
    ("author-azure-storage", "azurerm", "hashicorp/azurerm", "4.60.0", "~> 4.0", "1.13.0"),
    ("author-gcp-network", "google", "hashicorp/google", "~> 6.1.0", "~> 6.0", "~> 1.13.0"),
    ("author-oci-network", "oci", "oracle/oci", "~> 7.0", ">= 7.0", "~> 1.0"),
]


def versions_tf(required_version: str, provider: str, source: str, version: str | None) -> str:
    version_line = f'      version = "{version}"\n' if version else ""
    return (
        "terraform {\n"
        f'  required_version = "{required_version}"\n'
        "  required_providers {\n"
        f"    {provider} = {{\n"
        f'      source  = "{source}"\n'
        f"{version_line}"
        "    }\n"
        "  }\n"
        "}\n"
    )


@needs_node
@pytest.mark.parametrize(("case", "provider", "source", "pin", "other_shape", "runtime"), PIN_BY_CASE)
def test_provider_pin_accepts_the_shape_the_strategy_asks_for(case, provider, source, pin, other_shape, runtime):
    grader = grader_of(case, "provider-pin")
    assert grader.meta["target"] == {"source": "file", "path": "versions.tf"}
    assert passes(grader, [versions_tf(runtime, provider, source, pin)]) == [True]


@needs_node
@pytest.mark.parametrize(("case", "provider", "source", "pin", "other_shape", "runtime"), PIN_BY_CASE)
def test_provider_pin_rejects_another_shape_or_no_pin(case, provider, source, pin, other_shape, runtime):
    grader = grader_of(case, "provider-pin")
    assert passes(grader, [versions_tf(runtime, provider, source, other_shape), versions_tf(runtime, provider, source, None)]) == [False, False]


@needs_node
@pytest.mark.parametrize(("case", "provider", "source", "pin", "other_shape", "runtime"), PIN_BY_CASE)
def test_provider_pin_is_not_satisfied_by_the_terraform_version(case, provider, source, pin, other_shape, runtime):
    # SKILL.md gives `required_version = "~> 1.13"` as the runtime pin. `version =` ends `required_version =`,
    # so a pattern that only looks for `version =` passed a reply that never pinned the provider.
    grader = grader_of(case, "provider-pin")
    assert passes(grader, [versions_tf(runtime, provider, source, None)]) == [False]
    assert passes(grader, ['terraform {\n  required_version = "%s"\n}\n' % runtime]) == [False]


@needs_node
@pytest.mark.parametrize(("case", "provider", "source", "pin", "other_shape", "runtime"), PIN_BY_CASE)
def test_provider_source_names_the_registry_address(case, provider, source, pin, other_shape, runtime):
    grader = grader_of(case, "provider-source")
    qualified = [
        f'source = "{source}"',
        f'      source  =  "{source}"',
        f'source = "registry.terraform.io/{source}"',
    ]
    assert passes(grader, qualified) == [True] * len(qualified)
    unqualified = [f'source = "{provider}"', f'source = "{source}-extra"', 'source = "hashicorp/null"', f'version = "{source}"']
    assert passes(grader, unqualified) == [False] * len(unqualified)


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


def secret_variable(name: str, default: str) -> str:
    return f'variable "{name}" {{\n  description = "A value"\n  type        = string\n  default     = "{default}"\n}}\n'


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
    'db_pass = "Sup3rS3cret!"',  # pragma: allowlist secret
    'admin_pwd = "Sup3rS3cret!"',  # pragma: allowlist secret
    # The literal is a variable's default, on a line of its own.
    secret_variable("admin_password", "P@ssw0rd1234"),  # pragma: allowlist secret
    secret_variable("db_secret", "hunter2hunter2"),  # pragma: allowlist secret
    secret_variable("db_pass", "Sup3rS3cret!"),  # pragma: allowlist secret
    secret_variable("api_token", "abcdefghijkl"),  # pragma: allowlist secret
    'variable "client_secret" {\n  default = "abcdefghijkl"\n  type    = string\n}\n',  # pragma: allowlist secret
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
    # A reference to a secret is not the secret.
    'secret_arn = "arn:aws:secretsmanager:eu-west-1:123456789012:secret:app-AbCdEf"',  # pragma: allowlist secret
    'token_uri = "https://oauth2.googleapis.com/token"',
    'web_identity_token_file = "/var/run/secrets/eks.amazonaws.com/serviceaccount/token"',
    'secret_name = "prod/app/db-credentials"',  # pragma: allowlist secret
    'private_key_path = "~/.oci/oci_api_key.pem"',
    'password_version = "20260101abc"',  # pragma: allowlist secret
    'bypass_rules = "allow-everything"',
    # What a key of this name usually holds is an address or a path, whatever the key is called.
    'secret = "arn:aws:secretsmanager:eu-west-1:123456789012:secret:app-AbCdEf"',  # pragma: allowlist secret
    'token = "https://example.com/oauth/token"',
    'credentials = "/home/runner/.config/gcloud/application_default_credentials.json"',
    # Variables that hold no literal secret.
    'variable "admin_password" {\n  description = "A value"\n  type        = string\n  sensitive   = true\n}\n',
    'variable "admin_password" {\n  type    = string\n  default = null\n}\n',
    'variable "admin_password" {\n  type    = string\n  default = ""\n}\n',
    secret_variable("db_secret_name", "prod/db/password"),
    secret_variable("token_ttl", "3600"),
    secret_variable("region", "eu-west-1x"),
    secret_variable("bypass_list", "10.0.0.0/8,172.16.0.0/12"),
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
# A description inside an object type or a default belongs to the value, not to the variable.
UNDESCRIBED_BY_A_NESTED_DESCRIPTION = [
    'variable "rules" {\n  type = object({\n    name        = string\n    description = string\n  })\n}\n',
    'variable "cfg" {\n  type = map(string)\n  default = {\n    description = "x"\n  }\n}\n',
    'variable "rules" {\n    type = object({\n        description = string\n    })\n}\n',
    'variable "rules" {\n\ttype = object({\n\t\tdescription = string\n\t})\n}\n',
    'variable "rules" {\r\n  type = object({\r\n    description = string\r\n  })\r\n}\r\n',
]
UNDESCRIBED_IN_OTHER_LAYOUTS = [
    'variable "name" { type = string }\n',
    'variable "name" {\r\n  type = string\r\n}\r\n',
    'variable "name" {\n\n  type = string\n}\n',
    'variable "name" { # the prefix\n  type = string\n}\n',
    'variable "name" {\n}\n',
    'variable "name" {\n  type = string\n  description_long = "x"\n}\n',
    'variable "a" {\n  description = "a"\n}\n\nvariable "b" {\n  type = string\n}\n',
]
DESCRIBED_IN_OTHER_LAYOUTS = [
    'variable "name" {\n    type        = string\n    description = "Name prefix"\n}\n',
    'variable "name" {\n\ttype        = string\n\tdescription = "Name prefix"\n}\n',
    'variable "name" { description = "Name prefix" }\n',
    'variable "name" {\r\n  type = string\r\n  description = "Name prefix"\r\n}\r\n',
    'variable "name" { # the prefix\n  type = string\n  description = "Name prefix"\n}\n',
    'variable "name" {\n\n  type = string\n  description = "Name prefix"\n}\n',
    'variable "name" {\n  # why\n  type = string\n  description = "Name prefix"\n}\n',
    'variable "rules" {\n  type = object({\n    name        = string\n    description = string\n  })\n  description = "Rules"\n}\n',
    'variable "name" {\n  description = <<-EOT\n  Name prefix\n  EOT\n  type = string\n}\n',
]


@needs_node
@pytest.mark.parametrize("case", AUTHORING_CASES)
def test_variable_grader_passes_when_every_block_has_a_description(case):
    grader = grader_of(case, "no-undescribed-variable")
    assert grader.meta["target"] == {"source": "file", "path": "variables.tf"}
    assert passes(grader, [DESCRIBED_VARIABLES]) == [True]
    assert passes(grader, DESCRIBED_IN_OTHER_LAYOUTS) == [True] * len(DESCRIBED_IN_OTHER_LAYOUTS)


@needs_node
@pytest.mark.parametrize("case", AUTHORING_CASES)
@pytest.mark.parametrize("sample", [UNDESCRIBED_FIRST, UNDESCRIBED_LAST, UNDESCRIBED_NESTED, UNDESCRIBED_EMPTY])
def test_variable_grader_fails_when_any_block_lacks_one(case, sample):
    assert passes(grader_of(case, "no-undescribed-variable"), [sample]) == [False]


@needs_node
@pytest.mark.parametrize("case", AUTHORING_CASES)
def test_variable_grader_is_not_fooled_by_a_description_inside_the_value(case):
    grader = grader_of(case, "no-undescribed-variable")
    assert passes(grader, UNDESCRIBED_BY_A_NESTED_DESCRIPTION) == [False] * len(UNDESCRIBED_BY_A_NESTED_DESCRIPTION)


@needs_node
@pytest.mark.parametrize("case", AUTHORING_CASES)
def test_variable_grader_reads_other_layouts_of_a_block(case):
    grader = grader_of(case, "no-undescribed-variable")
    assert passes(grader, UNDESCRIBED_IN_OTHER_LAYOUTS) == [False] * len(UNDESCRIBED_IN_OTHER_LAYOUTS)


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
def test_output_grader_is_not_fooled_by_a_description_inside_the_value(case):
    grader = grader_of(case, "no-undescribed-output")
    undescribed = [
        'output "config" {\n  value = {\n    description = "Settings"\n    id = aws_vpc.main.id\n  }\n}\n',
        'output "id" { value = aws_vpc.main.id }\n',
        'output "id" {\r\n  value = aws_vpc.main.id\r\n}\r\n',
    ]
    assert passes(grader, undescribed) == [False] * len(undescribed)
    described = [
        'output "cfg" {\n  value = {\n    id = aws_vpc.main.id\n  }\n  description = "Config"\n}\n',
        'output "cfg" {\n  description = "Config"\n  value = {\n    description = "Settings"\n  }\n}\n',
    ]
    assert passes(grader, described) == [True] * len(described)


@needs_node
@pytest.mark.parametrize("case", AUTHORING_CASES)
def test_presence_graders_still_fail_on_an_empty_file(case):
    # A not_contains grader passes on an empty file, so the presence graders must stay beside them.
    for name in ("variables-described", "outputs-described"):
        assert passes(grader_of(case, name), [""]) == [False]
