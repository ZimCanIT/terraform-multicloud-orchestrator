"""Tests for the skill's read-only audit script."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "plugins/terraform-multicloud-orchestrator/skills/terraform-multicloud-orchestrator"
SCRIPT = SKILL / "scripts/tf_audit.py"

spec = importlib.util.spec_from_file_location("tf_audit", SCRIPT)
tf_audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tf_audit)

# Not a credential: a placeholder that the fixtures below put where a secret would be.
FAKE = "example-" + "value"
# A Key Vault reference is not a secret. It is assembled here so that secret scanners do not read it as one.
REFERENCE = "@Microsoft.KeyVault(" + "Secret" + "Uri=https://kv.vault.azure.net/secrets/x)"

BAD_ROOT = """
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.40"
    }
    random = {
      source = "hashicorp/random"
    }
  }

  backend "azurerm" {
    storage_account_name = "sttfstate"
    container_name       = "tfstate"
    key                  = "all.tfstate"
    access_key           = "{FAKE}"
  }
}

provider "azurerm" {
  subscription_id = "11111111-2222-3333-4444-555555555555"
  client_secret   = var.client_secret
}

variable "client_secret" {}

variable "names" {
  type = any
}

resource "azurerm_resource_group" "rg" {
  count    = length(var.names)
  name     = var.names[count.index]
  location = terraform.workspace == "prod" ? "uksouth" : "ukwest"
}

resource "azurerm_storage_account" "st" {
  name                            = "stbad"
  min_tls_version                 = "TLS1_0"
  allow_nested_items_to_be_public = true
  public_network_access_enabled   = true

  queue_properties {
    logging {
      delete = true
    }
  }

  lifecycle {
    ignore_changes = all
  }
}

resource "azurerm_key_vault" "kv" {
  name                      = "kv-bad"
  enable_rbac_authorization = false
}

resource "azurerm_mssql_server" "sql" {
  name                         = "sql-bad"
  administrator_login          = "sqladmin"
  administrator_login_password = "{FAKE}"
}

resource "azurerm_subnet" "app" {
  name              = "snet-app"
  service_endpoints = ["Microsoft.Storage"]
}

resource "azurerm_network_security_rule" "ssh" {
  name                       = "ssh"
  direction                  = "Inbound"
  access                     = "Allow"
  destination_port_range     = "20-25"
  source_address_prefix      = "Internet"
  destination_address_prefix = "*"
}

resource "azurerm_role_assignment" "owner" {
  scope                = "/subscriptions/${var.subscription_id}"
  role_definition_name = "Owner"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_app_service" "old" {
  name = "app-old"
}

resource "null_resource" "cli" {
  provisioner "local-exec" {
    command = "az group create"
  }
}

data "terraform_remote_state" "network" {
  backend = "azurerm"
}

data "azurerm_key_vault_secret" "db" {
  name         = "db"
  key_vault_id = azurerm_key_vault.kv.id
}

module "naming" {
  source = "Azure/naming/azurerm"
}

output "storage" {
  value = azurerm_storage_account.st
}

output "storage_key" {
  value = azurerm_storage_account.st.primary_access_key
}

resource "azurerm_kubernetes_cluster" "aks" {
  name       = "aks"
  depends_on = [azurerm_subnet.app]
}

resource "azurerm_cognitive_account" "ai" {
  name     = "cog-bad"
  kind     = "OpenAI"
  sku_name = "S0"
}

resource "azurerm_search_service" "search" {
  name                         = "srch-bad"
  local_authentication_enabled = true
}
""".replace("{FAKE}", FAKE)

BAD_MODULE = """
provider "azurerm" {
  features {}
}

terraform {
  backend "local" {}
}

data "azurerm_resource_group" "this" {
  name = "rg"
}
"""

EXPECTED = {
    ("ST1", "major", "provider azurerm"),
    ("ST1", "major", "backend local"),
    ("ST2", "blocker", "backend azurerm"),
    ("ST2", "minor", "backend azurerm"),
    ("ST3", "major", "azurerm_resource_group.rg"),
    ("ST4", "major", "data.terraform_remote_state.network"),
    ("MD2", "major", "data.azurerm_resource_group.this"),
    ("MD3", "major", "var.names"),
    ("MD3", "major", "var.client_secret"),
    ("MD3", "minor", "var.client_secret"),
    ("MD5", "major", "output.storage"),
    ("MD5", "blocker", "output.storage_key"),
    ("HC1", "major", "azurerm_resource_group.rg"),
    ("HC2", "major", "azurerm"),
    ("HC5", "major", "azurerm_storage_account.st"),
    ("HC6", "major", "null_resource.cli"),
    ("HC7", "minor", "azurerm_kubernetes_cluster.aks"),
    ("HC8", "major", "random"),
    ("HC8", "major", "module.naming"),
    ("HC8", "minor", "terraform"),
    ("AZ1", "major", "azurerm_storage_account.st"),
    ("AZ1", "major", "azurerm_key_vault.kv"),
    ("AZ1", "major", "azurerm_role_assignment.owner"),
    ("AZ1", "minor", "azurerm_role_assignment.owner"),
    ("AZ1", "major", "azurerm_kubernetes_cluster.aks"),
    ("AZ1", "major", "azurerm_cognitive_account.ai"),
    ("AZ1", "major", "azurerm_search_service.search"),
    ("AZ3", "major", "azurerm_cognitive_account.ai"),
    ("AZ6", "minor", "azurerm_search_service.search"),
    ("AZ2", "blocker", "azurerm_mssql_server.sql"),
    ("AZ2", "major", "provider azurerm"),
    ("AZ2", "major", "data.azurerm_key_vault_secret.db"),
    ("AZ3", "blocker", "azurerm_storage_account.st"),
    ("AZ3", "blocker", "azurerm_network_security_rule.ssh"),
    ("AZ3", "major", "azurerm_subnet.app"),
    ("AZ3", "minor", "azurerm_subnet.app"),
    ("AZ4", "major", "azurerm_storage_account.st"),
    ("AZ5", "major", "azurerm_key_vault.kv"),
    ("AZ6", "minor", "azurerm_key_vault.kv"),
    ("AZ7", "minor", "azurerm_resource_group.rg"),
    ("AZ8", "major", "provider azurerm"),
    ("AZ8", "minor", "azurerm_app_service.old"),
    ("AZ8", "minor", "azurerm_key_vault.kv"),
    ("AZ8", "minor", "azurerm_storage_account.st"),
    ("AZ8", "minor", "azurerm_subnet.app"),
}


def audit(directory: Path) -> list[dict]:
    return tf_audit.Audit(directory).run()


@pytest.fixture()
def bad(tmp_path: Path) -> Path:
    (tmp_path / "modules/thing").mkdir(parents=True)
    (tmp_path / "main.tf").write_text(BAD_ROOT, encoding="utf-8")
    (tmp_path / "modules/thing/main.tf").write_text(BAD_MODULE, encoding="utf-8")
    return tmp_path


def test_reference_stack_has_no_findings() -> None:
    findings = audit(SKILL / "assets/reference-stack")
    assert findings == [], "the reference stack must pass the audit it ships with"


def test_reference_stack_is_really_parsed() -> None:
    blocks = tf_audit.Parser((SKILL / "assets/reference-stack/modules/virtual_network/main.tf").read_text(encoding="utf-8")).parse()
    kinds = [block.labels[0] for block in blocks if block.kind == "resource"]
    assert kinds.count("azurerm_network_security_rule") == 2 and "azurerm_subnet" in kinds
    subnet = next(block for block in blocks if block.labels[:1] == ["azurerm_subnet"])
    assert subnet.children("delegation"), "a dynamic block must read as the block it generates"
    assert subnet.has("delegation.service_delegation.actions")


def test_bad_configuration_is_reported(bad: Path) -> None:
    found = {(item["rule"], item["severity"], item["subject"]) for item in audit(bad)}
    assert EXPECTED <= found, f"missing findings: {sorted(EXPECTED - found)}"


def test_findings_are_ordered_and_located(bad: Path) -> None:
    findings = audit(bad)
    levels = [tf_audit.SEVERITIES.index(item["severity"]) for item in findings]
    assert levels == sorted(levels)
    password = next(item for item in findings if item["rule"] == "AZ2" and item["subject"] == "azurerm_mssql_server.sql")
    line = BAD_ROOT.split("\n")[password["line"] - 1]
    assert "administrator_login_password" in line and password["file"] == "main.tf"


def test_upgrade_findings_follow_the_provider_pin(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        """
terraform {
  required_version = "~> 1.13"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.13"
    }
  }
}

resource "azurerm_kubernetes_cluster" "aks" {
  name = "aks"
}

resource "azurerm_monitor_diagnostic_setting" "aks" {
  target_resource_id = azurerm_kubernetes_cluster.aks.id

  metric {
    category = "AllMetrics"
  }
}
""",
        encoding="utf-8",
    )
    upgrade = [item for item in audit(tmp_path) if item["rule"] == "AZ8"]
    messages = " | ".join(item["message"] for item in upgrade)
    assert all(item["severity"] == "major" for item in upgrade)
    assert "metric was removed in azurerm 5.0. Use enabled_metric." in messages
    assert "node_provisioning_profile is required from azurerm 5.0." in messages
    assert "Before upgrading" not in messages


def test_expressions_are_not_judged(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        """
resource "azurerm_key_vault" "this" {
  name                          = var.name
  rbac_authorization_enabled    = true
  purge_protection_enabled      = var.purge_protection_enabled
  public_network_access_enabled = local.public
  tags                          = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_monitor_diagnostic_setting" "this" {
  target_resource_id = azurerm_key_vault.this.id
}
""",
        encoding="utf-8",
    )
    assert audit(tmp_path) == []


def test_ordinary_code_is_not_flagged(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        """
terraform {
  required_version = "~> 1.13"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.5"
    }
  }
}

variable "disaster_recovery_region" {
  description = "Paired region."
  type        = string
}

variable "token_lifetime_minutes" {
  description = "Lifetime of issued tokens."
  type        = number
  default     = 60
}

variable "key_vault_secret_name" {
  description = "Name of the secret, not its value."
  type        = string
  default     = "orders-database"
}

variable "token_ttl" {
  description = "Seconds a token stays valid."
  type        = number
  default     = 3600
}

variable "tenant_id" {
  description = "Tenant ID, for example 00000000-0000-0000-0000-000000000000."
  type        = string
}

resource "azurerm_management_lock" "optional" {
  count = length(var.locked_scopes) > 0 ? 1 : 0

  name       = "lock"
  scope      = var.locked_scopes[0]
  lock_level = "CanNotDelete"
}

locals {
  builtin_policy = "/providers/Microsoft.Authorization/policyDefinitions/06a78e20-9358-41c9-923c-fb736d382a4d"
  graph_app_id   = "00000003-0000-0000-c000-000000000000"
}

resource "azurerm_site_recovery_protection_container_mapping" "this" {
  name = "mapping"
}

resource "azurerm_key_vault" "old" {
  name                      = var.name
  enable_rbac_authorization = true
  purge_protection_enabled  = true
  tags                      = var.tags

  public_network_access_enabled = false

  lifecycle {
    prevent_destroy = true
  }
}

output "key_secret_id" {
  description = "ID of the secret that holds the key. The resource is named primary_key; the output is not a secret."
  value       = azurerm_key_vault_secret.primary_key.id
}

module "diagnostics" {
  source = "../modules/diagnostics"

  target_resource_id = azurerm_key_vault.old.id
}
""",
        encoding="utf-8",
    )
    (tmp_path / "modules/thing/examples/basic").mkdir(parents=True)
    (tmp_path / "modules/thing/examples/basic/main.tf").write_text('provider "azurerm" {\n  features {}\n}\n', encoding="utf-8")
    findings = audit(tmp_path)
    assert [(item["rule"], item["severity"]) for item in findings] == [("AZ8", "minor")], findings
    assert findings[0]["message"].startswith("Before upgrading to azurerm 5: enable_rbac_authorization")


def test_references_and_rules_are_matched_exactly(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        """
resource "azurerm_subnet" "app" {
  name                            = "snet-app"
  default_outbound_access_enabled = false
}

resource "azurerm_subnet" "app2" {
  name                            = "snet-app2"
  default_outbound_access_enabled = false
}

resource "azurerm_subnet" "bastion" {
  name                            = "AzureBastionSubnet"
  default_outbound_access_enabled = false
}

resource "azurerm_subnet" "gateway" {
  name                            = "GatewaySubnet"
  default_outbound_access_enabled = false
}

resource "azurerm_subnet_network_security_group_association" "app2" {
  subnet_id                 = azurerm_subnet.app2.id
  network_security_group_id = var.network_security_group_id
}

resource "azurerm_subnet_network_security_group_association" "elsewhere" {
  subnet_id                 = data.azurerm_subnet.app.id
  network_security_group_id = var.network_security_group_id
}

resource "azurerm_network_security_rule" "rdp" {
  name                    = "rdp"
  direction               = "Inbound"
  access                  = "Allow"
  destination_port_range  = "3389"
  source_address_prefixes = ["10.0.0.0/8", "0.0.0.0/0"]
}
""",
        encoding="utf-8",
    )
    found = {(item["rule"], item["severity"], item["subject"]) for item in audit(tmp_path)}
    assert found == {
        ("AZ3", "major", "azurerm_subnet.app"),
        ("AZ3", "major", "azurerm_subnet.bastion"),
        ("AZ3", "blocker", "azurerm_network_security_rule.rdp"),
    }


@pytest.mark.parametrize(
    ("constraint", "expected"),
    [
        ("~> 5.13", True), ("= 5.0.0", True), (">= 4.0", True), (">= 4.0, < 6.0", True), (">= 5.0", True), ("< 5.0.1", True),
        (">= 4, < 5.0.1", True), ("~> 5", True), ("~> 4", False), ("~> 4.5", False), ("~> 4.5.0", False), (">= 4.5.0, < 5.0.0", False),
        ("= 4.15.0", False), ("4.50.0", False), (">= 6", False), (None, False),
    ],
)
def test_provider_pin_is_read_clause_by_clause(constraint: str | None, expected: bool) -> None:
    assert tf_audit.admits_major(constraint) is expected


def test_secret_looking_values_in_variable_files(tmp_path: Path) -> None:
    (tmp_path / "environments").mkdir()
    (tmp_path / "environments/prod.tfvars").write_text(
        """
workload              = "orders"
key_vault_secret_name = "{NAME}"
database_password     = "{FAKE}"
sql = {
  admin_secret = "{FAKE}"
  reference    = "{REFERENCE}"
  token_ttl    = "3600"
}
""".replace("{FAKE}", FAKE).replace("{REFERENCE}", REFERENCE).replace("{NAME}", "orders-database"),
        encoding="utf-8",
    )
    findings = audit(tmp_path)
    assert [(item["rule"], item["severity"], item["subject"], item["line"]) for item in findings] == [
        ("AZ2", "major", "database_password", 4),
        ("AZ2", "major", "admin_secret", 6),
    ]


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("length(var.names)", True), ("var.create ? length(var.names) : 0", True), ("length(var.ips) > 0 ? 1 : 0", False),
        ("length(var.a) > 0 ? 1 : max(0, 1)", False), ("var.enabled ? 1 : 0", False), ("3", False),
    ],
)
def test_count_over_a_list_is_told_from_a_switch(expression: str, expected: bool) -> None:
    assert tf_audit.counts_a_list(expression) is expected


def test_a_reason_on_either_line_suppresses(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        """
# tf-audit:ignore=AZ3 ingress address for the public load balancer
resource "azurerm_public_ip" "a" { # tf-audit:ignore=AZ3
  tags = var.tags
}

# tf-audit:ignore=AZ3 ---
resource "azurerm_public_ip" "b" {
  tags = var.tags
}
""",
        encoding="utf-8",
    )
    assert [(item["rule"], item["subject"]) for item in audit(tmp_path)] == [("AUDIT", "azurerm_public_ip.b"), ("AZ3", "azurerm_public_ip.b")]


def test_suppression_needs_a_reason(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        """
# tf-audit:ignore=AZ3 the public address is the product: an ingress load balancer
resource "azurerm_public_ip" "ingress" {
  tags = var.tags
}

# tf-audit:ignore=AZ3
resource "azurerm_public_ip" "other" {
  tags = var.tags
}
""",
        encoding="utf-8",
    )
    findings = audit(tmp_path)
    assert [(item["rule"], item["subject"]) for item in findings] == [("AUDIT", "azurerm_public_ip.other"), ("AZ3", "azurerm_public_ip.other")]
    assert tf_audit.main(["--fail-on", "minor", str(tmp_path)]) == 1, "a suppression without a reason must not hide the finding"


def test_parser_survives_strings_heredocs_and_comments() -> None:
    text = '''
resource "azurerm_x" "a" { # trailing { brace
  name = "a-${var.b ? "}" : "{"}" // not a block {
  /* block {
     comment */
  body = <<-EOT
    resource "fake" "block" {
      inside = "heredoc"
    }
  EOT
  list = [
    "one", # comment inside a list
    "two",
  ]
  nested { value = 1 }
}

resource "azurerm_y" "b" {
  after = true
}
'''
    blocks = tf_audit.Parser(text).parse()
    assert [block.labels for block in blocks] == [["azurerm_x", "a"], ["azurerm_y", "b"]]
    first = blocks[0]
    assert set(first.attrs) == {"name", "body", "list"}
    assert "comment inside" not in first.attrs["list"].value and '"two"' in first.attrs["list"].value
    assert first.children("nested")[0].attrs["value"].value == "1"
    assert blocks[1].attrs["after"].line == text[: text.index("after")].count("\n") + 1


def test_command_line_output_and_exit_codes(bad: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert tf_audit.main([str(bad)]) == 0
    assert "blocker" in capsys.readouterr().out
    assert tf_audit.main(["--fail-on", "blocker", str(bad)]) == 1
    capsys.readouterr()
    assert tf_audit.main(["--json", "--rules", "st4", str(bad)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [item["rule"] for item in report["findings"]] == ["ST4"] and report["counts"]["major"] == 1
    assert tf_audit.main([str(bad / "missing")]) == 2
    assert tf_audit.main(["--fail-on", "minor", str(SKILL / "assets/reference-stack")]) == 0


def test_change_data_is_well_formed() -> None:
    data = json.loads((SKILL / "assets/azurerm-5-changes.json").read_text(encoding="utf-8"))
    assert data["removed_resources"]["azurerm_app_service"] == ["azurerm_linux_web_app", "azurerm_windows_web_app"]
    assert {"kind": "renamed", "path": "enable_rbac_authorization", "use": "rbac_authorization_enabled"} in data["resources"]["azurerm_key_vault"]
    for section in ("resources", "data_sources"):
        for kind, changes in data[section].items():
            assert kind.startswith("azurerm_")
            assert all(change["kind"] in {"renamed", "removed", "values", "required"} for change in changes)
            assert all(re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*", change["path"]) for change in changes)
