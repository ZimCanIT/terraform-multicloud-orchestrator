#!/usr/bin/env python3
"""Audit Terraform for Azure against the authoring standard in SKILL.md section 3.

Read-only: it reads the *.tf and *.tfvars files under a directory and prints findings. It runs no Terraform
command, makes no network call and writes nothing. The one program it starts is `git ls-files`, to
see whether a tfvars file is tracked. It checks what can be decided from the text
alone, so a clean report is not a review: values that are expressions are never judged.

Usage: tf_audit.py [--json] [--fail-on blocker|major|minor] [--rules ST1,AZ3] [DIRECTORY]

Exit codes: 0 by default; 1 when --fail-on is given and a finding at or above that level exists;
2 on a usage or read error.

Suppress one finding with a comment on the same line or the line above. A reason is required:
    # tf-audit:ignore=AZ3 public by design, fronted by Front Door
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import subprocess
import sys
from pathlib import Path

SEVERITIES = ("blocker", "major", "minor")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
HEREDOC = re.compile(r"<<-?([A-Za-z_][A-Za-z0-9_]*)[ \t]*\r?\n")
GUID = re.compile(r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b")
SIMPLE_STRING = re.compile(r'^"([^"\\$%]*)"$')
IGNORE = re.compile(r"tf-audit:ignore=([A-Z0-9,]+)(.*)")
SECRET_ATTR = re.compile(r"(?:^|_)(?:password|passwd|secret|access_key|sas_token|api_key|connection_string|shared_key|primary_key)$")
SECRET_NAME = re.compile(r"(?:^|_)(?:password|passwd|pwd|secret|token|sas|(?:api|access|shared|account)_key|connection_string)(?:_|$)")
NOT_A_SECRET = ("_version", "_id", "_ids", "_name", "_names", "_enabled", "_uri", "_url", "_type", "_length", "_days", "_minutes", "_hours", "_seconds", "_ttl", "_expiry", "_path", "_permissions", "_count")
WELL_KNOWN_GUIDS = {"00000003-0000-0000-c000-000000000000", "00000002-0000-0000-c000-000000000000"}
# name = "literal" on one line of a variable file, at any depth. Interpolations and Key Vault references do not match.
TFVARS_STRING = re.compile(r'^\s*"?([A-Za-z_][\w-]*)"?\s*=\s*"(?!@Microsoft\.KeyVault)[^"$%]+"\s*(?:#.*|//.*)?,?\s*$')
SECRET_OUTPUT = re.compile(
    r"\.(?:primary_access_key|secondary_access_key|primary_connection_string|secondary_connection_string|"
    r"primary_blob_connection_string|admin_password|administrator_login_password|client_secret|kube_config_raw|"
    r"kube_admin_config_raw|primary_key|secondary_key|primary_shared_key)\b(?![.\[])"
)
WHOLE_OBJECT = re.compile(r"^(?:(?:azurerm|azapi|azuread)_\w+\.\w+|module\.\w+)(?:\[[^\]]*\])?$")
CHANGES_FILE = Path(__file__).resolve().parent.parent / "assets" / "azurerm-5-changes.json"


class Attr:
    __slots__ = ("name", "value", "line")

    def __init__(self, name: str, value: str, line: int) -> None:
        self.name, self.value, self.line = name, value, line


class Block:
    __slots__ = ("kind", "labels", "line", "attrs", "blocks")

    def __init__(self, kind: str, labels: list[str], line: int, attrs: dict[str, Attr], blocks: list["Block"]) -> None:
        self.kind, self.labels, self.line, self.attrs, self.blocks = kind, labels, line, attrs, blocks

    def children(self, kind: str) -> list["Block"]:
        return [block for block in self.blocks if block.kind == kind]

    def find(self, path: str) -> list[Attr]:
        """Attributes at a dotted path through nested blocks, for example `site_config.ftps_state`."""
        head, _, rest = path.partition(".")
        if not rest:
            return [self.attrs[head]] if head in self.attrs else []
        return [attr for child in self.children(head) for attr in child.find(rest)]

    def has(self, path: str) -> bool:
        """Whether an attribute or a nested block exists at a dotted path."""
        head, _, rest = path.partition(".")
        if not rest:
            return head in self.attrs or bool(self.children(head))
        return any(child.has(rest) for child in self.children(head))

    def walk(self):
        """Every attribute in this block and the blocks nested in it."""
        yield from self.attrs.values()
        for child in self.blocks:
            yield from child.walk()

    def nested(self):
        for child in self.blocks:
            yield child
            yield from child.nested()


class Parser:
    """A structural scanner for HCL: blocks, labels and raw attribute values. It does not evaluate anything."""

    def __init__(self, text: str) -> None:
        self.text, self.pos, self.end = text, 0, len(text)
        self.line_starts = [0] + [match.end() for match in re.finditer("\n", text)]
        self.comments: dict[int, str] = {}

    def line_of(self, pos: int) -> int:
        return bisect.bisect_right(self.line_starts, pos)

    def parse(self) -> list[Block]:
        return normalise(self.body(top=True)[1])

    def body(self, top: bool = False) -> tuple[dict[str, Attr], list[Block]]:
        attrs: dict[str, Attr] = {}
        blocks: list[Block] = []
        while True:
            self.skip_space()
            if self.pos >= self.end:
                break
            if self.text[self.pos] == "}":
                self.pos += 1
                if top:
                    continue
                break
            match = IDENT.match(self.text, self.pos)
            if not match:
                self.pos += 1
                continue
            name, line = match.group(0), self.line_of(self.pos)
            self.pos = match.end()
            self.skip_inline()
            if self.text.startswith("=", self.pos) and not self.text.startswith(("==", "=>"), self.pos):
                self.pos += 1
                attrs[name] = Attr(name, self.expression().strip(), line)
                continue
            labels: list[str] = []
            while self.pos < self.end:
                self.skip_inline()
                char = self.text[self.pos : self.pos + 1]
                if char == '"':
                    start = self.pos
                    self.string()
                    labels.append(self.text[start + 1 : self.pos - 1])
                elif char == "{":
                    self.pos += 1
                    inner_attrs, inner_blocks = self.body()
                    blocks.append(Block(name, labels, line, inner_attrs, inner_blocks))
                    break
                else:
                    label = IDENT.match(self.text, self.pos)
                    if not label:
                        break
                    labels.append(label.group(0))
                    self.pos = label.end()
        return attrs, blocks

    def expression(self) -> str:
        parts: list[str] = []
        start, depth = self.pos, 0
        while self.pos < self.end:
            char = self.text[self.pos]
            if char == '"':
                self.string()
            elif char == "<" and self.heredoc():
                pass
            elif char == "#" or self.text.startswith(("//", "/*"), self.pos):
                parts.append(self.text[start : self.pos])
                self.comment()
                start = self.pos
            elif char in "([{":
                depth += 1
                self.pos += 1
            elif char in ")]}":
                if depth == 0:
                    break
                depth -= 1
                self.pos += 1
            elif char == "\n" and depth == 0:
                break
            else:
                self.pos += 1
        parts.append(self.text[start : self.pos])
        return "".join(parts)

    def string(self) -> None:
        self.pos += 1
        while self.pos < self.end:
            char = self.text[self.pos]
            if char == "\\":
                self.pos += 2
            elif char == '"':
                self.pos += 1
                return
            elif char == "\n":
                return
            elif self.text.startswith(("${", "%{"), self.pos):
                self.pos += 2
                depth = 1
                while self.pos < self.end and depth:
                    inner = self.text[self.pos]
                    if inner == '"':
                        self.string()
                        continue
                    depth += inner == "{"
                    depth -= inner == "}"
                    self.pos += 1
            else:
                self.pos += 1

    def heredoc(self) -> bool:
        match = HEREDOC.match(self.text, self.pos)
        if not match:
            return False
        closing = re.compile(r"\n[ \t]*" + re.escape(match.group(1)) + r"[ \t]*(?=\r?\n|$)")
        found = closing.search(self.text, match.end() - 1)
        self.pos = found.end() if found else self.end
        return True

    def comment(self) -> None:
        start = self.pos
        if self.text.startswith("/*", self.pos):
            close = self.text.find("*/", self.pos + 2)
            self.pos = self.end if close < 0 else close + 2
        else:
            close = self.text.find("\n", self.pos)
            self.pos = self.end if close < 0 else close
        for line in range(self.line_of(start), self.line_of(max(start, self.pos - 1)) + 1):
            self.comments[line] = self.text[start : self.pos]

    def skip_inline(self) -> None:
        while self.pos < self.end and self.text[self.pos] in " \t":
            self.pos += 1

    def skip_space(self) -> None:
        while self.pos < self.end:
            if self.text[self.pos].isspace():
                self.pos += 1
            elif self.text[self.pos] == "#" or self.text.startswith(("//", "/*"), self.pos):
                self.comment()
            else:
                return


def normalise(blocks: list[Block]) -> list[Block]:
    """Read `dynamic "x" { content { ... } }` as a block named x, so that rules see one shape."""
    result = []
    for block in blocks:
        block.blocks = normalise(block.blocks)
        content = block.children("content") if block.kind == "dynamic" and block.labels else []
        if content:
            result.append(Block(block.labels[0], [], block.line, content[0].attrs, content[0].blocks))
        else:
            result.append(block)
    return result


def literal(value: str) -> str | None:
    """The value of a plain literal (string, bool, number), or None for an expression."""
    value = value.strip()
    match = SIMPLE_STRING.match(value)
    if match:
        return match.group(1)
    return value.lower() if re.fullmatch(r"true|false|null|-?\d+(?:\.\d+)?", value) else None


# resource type -> (rule, severity, [(path, accepted literals)], flag when absent, message)
ON_PUBLIC = "Public network access is not turned off."
BASELINE: dict[str, list[tuple]] = {
    "azurerm_storage_account": [
        ("AZ1", "major", [("shared_access_key_enabled", {"false"})], True, "Shared key access is on. Set shared_access_key_enabled = false and grant data roles."),
        ("AZ3", "major", [("public_network_access", {"Disabled", "SecuredByPerimeter"}), ("public_network_access_enabled", {"false"})], True, ON_PUBLIC),
        ("AZ3", "blocker", [("allow_nested_items_to_be_public", {"false"})], False, "Anonymous access to blobs is allowed."),
        ("AZ3", "major", [("network_rules.default_action", {"Deny"})], False, "The storage firewall allows every network."),
        ("AZ4", "major", [("min_tls_version", {"TLS1_2", "TLS1_3"})], False, "The TLS floor is below 1.2."),
        ("AZ4", "major", [("https_traffic_only_enabled", {"true"}), ("enable_https_traffic_only", {"true"})], False, "Plain HTTP is allowed."),
    ],
    "azurerm_key_vault": [
        ("AZ1", "major", [("rbac_authorization_enabled", {"true"}), ("enable_rbac_authorization", {"true"})], True, "The vault uses access policies. Turn on role-based access control."),
        ("AZ5", "major", [("purge_protection_enabled", {"true"})], True, "Purge protection is off."),
        ("AZ3", "major", [("public_network_access_enabled", {"false"})], True, ON_PUBLIC),
        ("AZ3", "major", [("network_acls.default_action", {"Deny"})], False, "The vault firewall allows every network."),
    ],
    "azurerm_mssql_server": [
        ("AZ3", "major", [("public_network_access_enabled", {"false"})], True, ON_PUBLIC),
        ("AZ1", "major", [("azuread_administrator.azuread_authentication_only", {"true"})], True, "SQL logins are enabled. Use azuread_administrator with azuread_authentication_only = true."),
        ("AZ4", "major", [("minimum_tls_version", {"1.2", "1.3"})], False, "The TLS floor is below 1.2."),
    ],
    "azurerm_postgresql_flexible_server": [
        ("AZ3", "major", [("public_network_access_enabled", {"false"})], True, ON_PUBLIC),
        ("AZ1", "major", [("authentication.password_auth_enabled", {"false"})], True, "Password authentication is on. Use Entra ID authentication only."),
    ],
    "azurerm_cosmosdb_account": [
        ("AZ1", "major", [("local_authentication_enabled", {"false"}), ("local_authentication_disabled", {"true"})], True, "Key authentication is on."),
        ("AZ3", "major", [("public_network_access_enabled", {"false"})], True, ON_PUBLIC),
    ],
    "azurerm_servicebus_namespace": [
        ("AZ1", "major", [("local_auth_enabled", {"false"})], True, "Shared access signature authentication is on."),
        ("AZ3", "major", [("public_network_access_enabled", {"false"})], True, ON_PUBLIC),
    ],
    "azurerm_eventhub_namespace": [
        ("AZ1", "major", [("local_authentication_enabled", {"false"})], True, "Shared access signature authentication is on."),
        ("AZ3", "major", [("public_network_access_enabled", {"false"})], True, ON_PUBLIC),
    ],
    "azurerm_container_registry": [
        ("AZ1", "major", [("admin_enabled", {"false"})], False, "The registry admin user is enabled."),
        ("AZ3", "major", [("public_network_access_enabled", {"false"})], True, ON_PUBLIC),
        ("AZ3", "blocker", [("anonymous_pull_enabled", {"false"})], False, "Anonymous pull is enabled."),
    ],
    "azurerm_kubernetes_cluster": [
        ("AZ1", "major", [("local_account_disabled", {"true"})], True, "Local accounts are enabled."),
        ("AZ3", "minor", [("private_cluster_enabled", {"true"})], True, "The API server is public. Confirm that this is intended."),
    ],
    "azurerm_linux_virtual_machine": [
        ("AZ1", "major", [("disable_password_authentication", {"true"})], False, "Password sign-in is enabled. Use an SSH key."),
    ],
    "azurerm_subnet": [
        ("AZ3", "minor", [("default_outbound_access_enabled", {"false"})], True, "Default outbound access is on. Make the subnet private and give it an explicit outbound path."),
    ],
    "azurerm_storage_container": [
        ("AZ3", "blocker", [("container_access_type", {"private"})], False, "The container allows anonymous access."),
    ],
    "azurerm_redis_cache": [
        ("AZ4", "major", [("non_ssl_port_enabled", {"false"}), ("enable_non_ssl_port", {"false"})], False, "The port without TLS is enabled."),
        ("AZ3", "major", [("public_network_access_enabled", {"false"})], True, ON_PUBLIC),
        ("AZ1", "minor", [("access_keys_authentication_enabled", {"false"})], True, "Access key authentication is on. Turn it off once every client signs in with Entra ID."),
    ],
    "azurerm_cognitive_account": [
        ("AZ1", "major", [("local_auth_enabled", {"false"})], True, "Key authentication is on. Set local_auth_enabled = false and grant data roles."),
        ("AZ3", "major", [("public_network_access_enabled", {"false"})], True, ON_PUBLIC),
    ],
    "azurerm_search_service": [
        ("AZ1", "major", [("local_authentication_enabled", {"false"})], True, "API key authentication is on. Set local_authentication_enabled = false and grant data roles."),
        ("AZ3", "major", [("public_network_access_enabled", {"false"})], True, ON_PUBLIC),
    ],
    "azurerm_app_configuration": [
        ("AZ1", "major", [("local_auth_enabled", {"false"})], True, "Access key authentication is on."),
        ("AZ3", "major", [("public_network_access", {"Disabled"})], True, ON_PUBLIC),
    ],
    "azurerm_mysql_flexible_server": [
        ("AZ3", "major", [("public_network_access", {"Disabled"}), ("public_network_access_enabled", {"false"})], False, ON_PUBLIC),
    ],
    "azurerm_machine_learning_workspace": [
        ("AZ3", "major", [("public_network_access_enabled", {"false"})], True, ON_PUBLIC),
    ],
}
WEB_APP = [
    ("AZ4", "major", [("https_only", {"true"})], True, "Plain HTTP is allowed. Set https_only = true."),
    ("AZ4", "major", [("site_config.ftps_state", {"Disabled", "FtpsOnly"})], False, "Plain FTP is allowed."),
    ("AZ4", "major", [("site_config.minimum_tls_version", {"1.2", "1.3"})], False, "The TLS floor is below 1.2."),
    ("AZ3", "minor", [("public_network_access_enabled", {"false"})], True, "The app accepts traffic from the internet. Confirm that this is intended."),
]
for _kind in ("linux_web_app", "windows_web_app", "linux_function_app", "windows_function_app"):
    BASELINE[f"azurerm_{_kind}"] = WEB_APP

DATA_HOLDING = {
    "storage_account", "key_vault", "mssql_server", "mssql_database", "postgresql_flexible_server", "mysql_flexible_server",
    "cosmosdb_account", "container_registry", "log_analytics_workspace", "recovery_services_vault", "managed_disk", "kusto_cluster",
}
LOGGED = {
    "storage_account", "key_vault", "kubernetes_cluster", "postgresql_flexible_server", "cosmosdb_account", "servicebus_namespace",
    "eventhub_namespace", "container_registry", "linux_web_app", "windows_web_app", "linux_function_app", "windows_function_app",
    "application_gateway", "firewall", "api_management", "virtual_network_gateway", "bastion_host", "recovery_services_vault",
    "cognitive_account", "search_service", "app_configuration",
}
TAGGABLE = DATA_HOLDING | LOGGED | {
    "resource_group", "virtual_network", "network_security_group", "route_table", "public_ip", "nat_gateway", "private_endpoint",
    "user_assigned_identity", "application_insights", "service_plan", "linux_virtual_machine", "windows_virtual_machine",
    "network_interface", "private_dns_zone", "redis_cache", "machine_learning_workspace",
}
MODULE_SURROUNDINGS = {
    "azurerm_resource_group", "azurerm_virtual_network", "azurerm_subnet", "azurerm_key_vault", "azurerm_log_analytics_workspace",
    "azurerm_private_dns_zone", "azurerm_user_assigned_identity", "azurerm_storage_account",
}
# Azure applies no network security group to these. AzureBastionSubnet is not here: it takes one, with the rules Bastion needs.
UNGUARDED_SUBNETS = {"GatewaySubnet", "AzureFirewallSubnet", "AzureFirewallManagementSubnet", "RouteServerSubnet"}
NOT_MODULE_CODE = {"examples", "example", "tests", "fixtures"}


def admits_major(constraint: str | None, major: int = 5) -> bool:
    """Whether a provider version constraint allows a release of the given major."""
    if not constraint:
        return False
    for clause in constraint.split(","):
        match = re.match(r"\s*(~>|>=|<=|!=|=|>|<)?\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", clause)
        if not match:
            continue
        operator, bound, minor, patch = match.group(1) or "=", int(match.group(2)), int(match.group(3) or 0), int(match.group(4) or 0)
        allowed = {
            "=": bound == major,
            # Provider constraints follow the Ruby rules: `~> 4` means 4.x, and never the next major.
            "~>": bound == major,
            ">=": bound <= major,
            ">": bound <= major,
            "<": (bound, minor, patch) > (major, 0, 0),
            "<=": bound >= major,
            "!=": True,
        }[operator]
        if not allowed:
            return False
    return True


def closes_at_end(call: str) -> bool:
    """Whether the parenthesis that `length(` opens closes at the last character."""
    depth = 0
    for index, char in enumerate(call):
        depth += char == "("
        depth -= char == ")"
        if depth == 0 and char == ")":
            return index == len(call) - 1
    return False


def counts_a_list(value: str) -> bool:
    """`count = length(x)`, bare or behind a condition, makes one instance per element. `length(x) > 0 ? 1 : 0` is a switch."""
    text = value.strip()
    candidates = [text] + re.findall(r"\?\s*(length\(.*\))\s*:\s*0\s*$", text, re.S)
    return any(candidate.startswith("length(") and closes_at_end(candidate) for candidate in candidates)


def mentions(text: str, address: str) -> bool:
    """Whether text refers to this resource address: not to a longer one, and not to a data source of the same name."""
    return re.search(r"(?<![\w.-])" + re.escape(address) + r"(?![\w-])", text) is not None

BROAD_ROLES = {"Owner", "Contributor", "User Access Administrator"}
OPEN_SOURCES = {"*", "internet", "0.0.0.0/0", "any"}


class Audit:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.findings: list[dict] = []
        self.comments: dict[Path, dict[int, str]] = {}
        try:
            self.changes = json.loads(CHANGES_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.changes = {}

    def add(self, rule: str, severity: str, path: Path, line: int, subject: str, message: str) -> None:
        location = {"file": path.relative_to(self.root).as_posix(), "line": line, "subject": subject}
        comments = self.comments.get(path, {})
        matches = [match for match in (IGNORE.search(comments.get(line, "")), IGNORE.search(comments.get(line - 1, "")))
                   if match and rule in match.group(1).split(",")]
        if any(re.search(r"[A-Za-z]{3}", match.group(2)) for match in matches):
            return
        if matches:
            note = f"A suppression of {rule} gives no reason, so the finding stands. Say why after the rule ID."
            self.findings.append({"rule": "AUDIT", "severity": "minor", **location, "message": note})
        self.findings.append({"rule": rule, "severity": severity, **location, "message": message})

    def run(self) -> list[dict]:
        directories: dict[Path, list[tuple[Path, list[Block]]]] = {}
        for path in sorted(self.root.rglob("*.tf")):
            if any(part.startswith(".") for part in path.relative_to(self.root).parts[:-1]):
                continue
            try:
                parser = Parser(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError) as error:
                self.add("AUDIT", "minor", path, 1, path.name, f"The file could not be read and was skipped: {error}")
                continue
            blocks = parser.parse()
            self.comments[path] = parser.comments
            directories.setdefault(path.parent, []).append((path, blocks))
        for directory, files in directories.items():
            self.directory(directory, files)
        for path in sorted(self.root.rglob("*.tf.json"))[:1]:
            self.add("AUDIT", "minor", path, 1, path.name, "Terraform in JSON syntax is not audited. Only *.tf files were read.")
        self.variable_files()
        order = {name: index for index, name in enumerate(SEVERITIES)}
        self.findings.sort(key=lambda item: (order[item["severity"]], item["file"], item["line"], item["rule"]))
        return self.findings

    def variable_files(self) -> None:
        """Variable files: a committed file that loads by itself, and secret-looking values in any of them."""
        for path in sorted(self.root.rglob("*.tfvars")):
            if any(part.startswith(".") for part in path.relative_to(self.root).parts[:-1]):
                continue
            try:
                lines = path.read_text(encoding="utf-8-sig").split("\n")
            except (OSError, UnicodeDecodeError):
                continue
            try:
                tracked = subprocess.run(["git", "ls-files", "--error-unmatch", path.name], cwd=path.parent, capture_output=True, check=False).returncode == 0
            except OSError:  # git is not installed: treat the file as untracked and still read it
                tracked = False
            if tracked and (path.name == "terraform.tfvars" or path.name.endswith(".auto.tfvars")):
                self.add("HC8", "major", path, 1, path.name, "This file loads automatically and is committed. Commit terraform.tfvars.example and keep real values out of version control.")
            for number, line in enumerate(lines, start=1):
                match = TFVARS_STRING.match(line)
                if match and SECRET_NAME.search(match.group(1).lower()) and not match.group(1).lower().endswith(NOT_A_SECRET):
                    where = "a committed variable file" if tracked else "a variable file. Make sure the file is never committed"
                    self.add("AZ2", "blocker" if tracked else "major", path, number, match.group(1),
                             f"A secret-looking value in {where}. Use Entra ID authentication or a Key Vault reference, and rotate the value.")

    def directory(self, directory: Path, files: list[tuple[Path, list[Block]]]) -> None:
        parts = directory.relative_to(self.root).parts
        is_module = ("modules" in parts or "modules" in self.root.parts[-2:]) and not NOT_MODULE_CODE & set(parts)
        every = [(path, block) for path, blocks in files for block in blocks]
        resources = [(path, block) for path, block in every if block.kind == "resource" and len(block.labels) == 2]
        constraint = None
        terraform_blocks = [(path, block) for path, block in every if block.kind == "terraform"]
        for path, block in terraform_blocks:
            for required in block.children("required_providers"):
                for attr in required.attrs.values():
                    version = re.search(r'version\s*=\s*"([^"]+)"', attr.value)
                    if attr.name == "azurerm" and version:
                        constraint = version.group(1)
                    if not version:
                        self.add("HC8", "major", path, attr.line, attr.name, "The provider has no version constraint.")
            for backend in block.children("backend"):
                self.backend(path, backend, is_module)
        if terraform_blocks and not any("required_version" in block.attrs for _, block in terraform_blocks):
            self.add("HC8", "minor", terraform_blocks[0][0], terraform_blocks[0][1].line, "terraform", "No required_version. State the runtime versions the code works with.")
        admits_v5 = admits_major(constraint)
        for path, block in every:
            self.generic(path, block)
            handler = getattr(self, f"on_{block.kind}", None)
            if handler:
                handler(path, block, is_module)
        references = {kind: " ".join(attr.value for _, block in resources if block.labels[0] == kind for attr in block.walk())
                      for kind in ("azurerm_subnet_network_security_group_association", "azurerm_monitor_diagnostic_setting")}
        # A module that is handed the resource may be the one that adds the diagnostic setting or the association.
        modules = [block for _, block in every if block.kind == "module"]
        references["azurerm_monitor_diagnostic_setting"] += " " + " ".join(attr.value for block in modules for attr in block.walk())
        references["azurerm_subnet_network_security_group_association"] += " " + " ".join(
            attr.value for block in modules if re.search(r"nsg|security[_-]group", " ".join(block.labels) + block.attrs.get("source", Attr("", "", 0)).value) for attr in block.walk())
        for path, block in resources:
            self.resource(path, block, is_module, references, admits_v5)
        for path, block in every:
            if block.kind == "data" and len(block.labels) == 2:
                self.upgrade(path, block, "data_sources", "removed_data_sources", admits_v5)

    def backend(self, path: Path, backend: Block, is_module: bool) -> None:
        name = backend.labels[0] if backend.labels else "?"
        if is_module:
            self.add("ST1", "major", path, backend.line, f"backend {name}", "A reusable module declares a backend. Only a root module does.")
        for secret in ("access_key", "sas_token"):
            if secret in backend.attrs:
                self.add("ST2", "blocker", path, backend.attrs[secret].line, f"backend {name}", f"The backend signs in with {secret}. Use use_azuread_auth = true and a data role on the container.")
        if name == "azurerm" and (literal(backend.attrs["use_azuread_auth"].value) if "use_azuread_auth" in backend.attrs else None) != "true":
            self.add("ST2", "minor", path, backend.line, "backend azurerm", "The backend block does not set use_azuread_auth = true. Unless a backend file or ARM_USE_AZUREAD sets it, the backend falls back to access keys.")
        if name == "local":
            self.add("ST2", "major", path, backend.line, "backend local", "State is local. Use the azurerm backend with Entra ID authentication.")

    def generic(self, path: Path, block: Block) -> None:
        subject = ".".join(block.labels) or block.kind
        for attr in block.walk():
            if "terraform.workspace" in attr.value:
                self.add("ST3", "major", path, attr.line, subject, "The code branches on terraform.workspace. Environments should differ by inputs only.")
            guids = {found.lower() for found in GUID.findall(attr.value)} - WELL_KNOWN_GUIDS
            if block.kind in {"resource", "data", "provider", "module", "locals", "variable"} and guids and "Definitions/" not in attr.value and attr.name not in {"description", "error_message"}:
                self.add("HC2", "major", path, attr.line, subject, f"{attr.name} holds a literal GUID. Pass subscription, tenant and object IDs in, or read them from azurerm_client_config.")
            value = literal(attr.value)
            if block.kind != "terraform" and SECRET_ATTR.search(attr.name) and not attr.name.endswith("_wo") and value and not value.startswith("@Microsoft.KeyVault(") and value not in {"true", "false", "null"}:
                self.add("AZ2", "blocker", path, attr.line, subject, f"{attr.name} is a literal in code. Remove it and rotate the value.")
            if attr.name == "ignore_changes" and attr.value.strip() == "all":
                self.add("HC5", "major", path, attr.line, subject, "ignore_changes = all stops Terraform managing the resource. List the attributes and say who else owns them.")
            if attr.name == "depends_on" and block.kind in {"resource", "data", "module"}:
                comments = self.comments.get(path, {})
                if block.kind == "module":
                    self.add("HC7", "minor", path, attr.line, subject, "depends_on on a module defers every data source inside it to apply. Pass a value from the dependency in.")
                elif not (comments.get(attr.line) or comments.get(attr.line - 1)):
                    self.add("HC7", "minor", path, attr.line, subject, "depends_on has no comment. Say which dependency Terraform cannot see.")
        for child in block.nested():
            if child.kind == "provisioner":
                self.add("HC6", "major", path, child.line, subject, "A provisioner runs outside the plan. Use a native resource or azapi.")

    def on_variable(self, path: Path, block: Block, is_module: bool) -> None:
        name = block.labels[0] if block.labels else "?"
        if "type" not in block.attrs:
            self.add("MD3", "major", path, block.line, f"var.{name}", "The variable has no type.")
        elif re.search(r"\bany\b", block.attrs["type"].value):
            self.add("MD3", "major", path, block.attrs["type"].line, f"var.{name}", "The type uses any. State the shape of the value.")
        if "description" not in block.attrs:
            self.add("MD3", "minor", path, block.line, f"var.{name}", "The variable has no description.")
        if SECRET_NAME.search(name.lower()) and not name.lower().endswith(NOT_A_SECRET):
            default = literal(block.attrs["default"].value) if "default" in block.attrs else None
            if default and default not in {"true", "false", "null"} and not re.fullmatch(r"-?\d+(?:\.\d+)?", default):
                self.add("AZ2", "blocker", path, block.attrs["default"].line, f"var.{name}", "A secret has a default value in code. Remove it and rotate the value.")
            if literal(block.attrs["sensitive"].value if "sensitive" in block.attrs else "") != "true" and literal(block.attrs["ephemeral"].value if "ephemeral" in block.attrs else "") != "true":
                self.add("MD3", "minor", path, block.line, f"var.{name}", "The name suggests a secret, but the variable is not marked sensitive.")

    def on_output(self, path: Path, block: Block, is_module: bool) -> None:
        name = block.labels[0] if block.labels else "?"
        value = block.attrs["value"].value if "value" in block.attrs else ""
        if "description" not in block.attrs:
            self.add("MD3", "minor", path, block.line, f"output.{name}", "The output has no description.")
        if WHOLE_OBJECT.match(value.strip()):
            self.add("MD5", "major", path, block.line, f"output.{name}", "The output returns a whole resource or module. Output the IDs and names callers need.")
        if SECRET_OUTPUT.search(value):
            self.add("MD5", "blocker", path, block.line, f"output.{name}", "The output returns a secret, which then sits in every caller's state. Grant callers a role on the resource ID.")

    def on_provider(self, path: Path, block: Block, is_module: bool) -> None:
        name = block.labels[0] if block.labels else "?"
        if is_module:
            self.add("ST1", "major", path, block.line, f"provider {name}", "A reusable module configures a provider. Only a root module does.")
        if name == "azurerm" and not block.children("features"):
            self.add("AZ8", "major", path, block.line, "provider azurerm", "The provider block has no features {} block, which is required.")
        for secret in ("client_secret", "client_certificate_password"):
            if secret in block.attrs:
                self.add("AZ2", "blocker" if literal(block.attrs[secret].value) else "major", path, block.attrs[secret].line, f"provider {name}",
                         f"The provider signs in with {secret}. Use workload identity federation or a managed identity.")

    def on_data(self, path: Path, block: Block, is_module: bool) -> None:
        kind = block.labels[0] if block.labels else "?"
        subject = "data." + ".".join(block.labels)
        if kind == "terraform_remote_state":
            self.add("ST4", "major", path, block.line, subject, "terraform_remote_state needs read access to the whole of another state. Pass the value in, or read the real resource.")
        if kind == "azurerm_key_vault_secret":
            self.add("AZ2", "major", path, block.line, subject, "This data source copies the secret value into state. Pass the secret ID and let the workload read the value.")
        if is_module and kind in MODULE_SURROUNDINGS:
            self.add("MD2", "major", path, block.line, subject, "A reusable module looks up its surroundings. Take the ID as an input.")

    def on_module(self, path: Path, block: Block, is_module: bool) -> None:
        subject = "module." + ".".join(block.labels)
        source = literal(block.attrs["source"].value) if "source" in block.attrs else None
        if "count" in block.attrs and counts_a_list(block.attrs["count"].value):
            self.add("HC1", "major", path, block.attrs["count"].line, subject, "count over a list renumbers instances when one is removed. Use for_each over a map.")
        if not source or source.startswith((".", "/")):
            return
        if source.startswith(("git::", "github.com", "http")) or ".git" in source:
            if "ref=" not in source:
                self.add("HC8", "major", path, block.attrs["source"].line, subject, "The Git source is not pinned. Add ?ref= with a tag.")
        elif "version" not in block.attrs:
            self.add("HC8", "major", path, block.line, subject, "The registry module has no version. Pin it exactly.")

    def resource(self, path: Path, block: Block, is_module: bool, references: dict[str, str], admits_v5: bool) -> None:
        kind, name = block.labels
        address, short = f"{kind}.{name}", kind.removeprefix("azurerm_")
        if kind == "null_resource":
            self.add("HC6", "major", path, block.line, address, "null_resource hides work from the plan. Use a native resource, azapi, or terraform_data as a trigger only.")
        if "count" in block.attrs and counts_a_list(block.attrs["count"].value):
            self.add("HC1", "major", path, block.attrs["count"].line, address, "count over a list renumbers instances when one is removed. Use for_each over a map.")
        if "for_each" in block.attrs and re.search(r"\[\*\]\.|toset\(\s*\[?\s*for\b.*\.id\b", block.attrs["for_each"].value):
            self.add("HC1", "major", path, block.attrs["for_each"].line, address, "for_each keys come from resource attributes, which are unknown at plan time. Key by the input map.")
        for rule, severity, alternatives, when_absent, message in BASELINE.get(kind, []):
            seen = [literal(attr.value) for option, _ in alternatives for attr in block.find(option)]
            present = [(option, attr) for option, _ in alternatives for attr in block.find(option)]
            accepted = any(literal(attr.value) in good for option, good in alternatives for attr in block.find(option))
            unknown = any(value is None for value in seen)
            if accepted or unknown or (not present and not when_absent):
                continue
            line = present[0][1].line if present else block.line
            self.add(rule, severity, path, line, address, message)
        if kind.startswith("azurerm_") and short in DATA_HOLDING:
            guarded = any(literal(attr.value) == "true" for attr in block.find("lifecycle.prevent_destroy"))
            if not guarded:
                self.add("HC5", "minor" if is_module else "major", path, block.line, address,
                         "The resource holds data and has no prevent_destroy. Add it, or say in the hand-off that nothing stops Terraform from destroying it.")
        if kind.startswith("azurerm_") and short in TAGGABLE and "tags" not in block.attrs:
            self.add("AZ7", "minor", path, block.line, address, "The resource takes no tags. Pass the merged tag map.")
        if kind.startswith("azurerm_") and short in LOGGED and not mentions(references["azurerm_monitor_diagnostic_setting"], address):
            self.add("AZ6", "minor", path, block.line, address, "No diagnostic setting targets this resource in this directory.")
        if kind == "azurerm_subnet" and not mentions(references["azurerm_subnet_network_security_group_association"], address):
            subnet_name = literal(block.attrs["name"].value) if "name" in block.attrs else None
            if subnet_name not in UNGUARDED_SUBNETS:
                self.add("AZ3", "major", path, block.line, address, "No network security group is associated with this subnet in this directory.")
        if kind == "azurerm_public_ip":
            self.add("AZ3", "minor", path, block.line, address, "A public IP address. Confirm that the request asked for one.")
        if kind in {"azurerm_network_security_rule", "azurerm_network_security_group"}:
            for rule_block in [block] if kind.endswith("_rule") else block.children("security_rule"):
                self.security_rule(path, rule_block, address)
        if kind == "azurerm_role_assignment":
            role = literal(block.attrs["role_definition_name"].value) if "role_definition_name" in block.attrs else None
            if role in BROAD_ROLES:
                self.add("AZ1", "major", path, block.attrs["role_definition_name"].line, address, f"{role} is a broad role. Use the built-in role with the fewest permissions at the narrowest scope.")
            principal = block.attrs["principal_id"].value if "principal_id" in block.attrs else ""
            if "principal_type" not in block.attrs and re.search(r"identity|kubelet", principal):
                self.add("AZ1", "minor", path, block.line, address, 'The principal is a managed identity but principal_type is not set. Set it to "ServicePrincipal".')
        if kind == "azurerm_key_vault_access_policy" or (kind == "azurerm_key_vault" and block.children("access_policy")):
            self.add("AZ1", "minor", path, block.line, address, "Access policies grant access outside role-based access control. Use role assignments.")
        if kind == "azurerm_key_vault_secret" and "value" in block.attrs:
            is_literal = literal(block.attrs["value"].value) not in (None, "")
            self.add("AZ2", "blocker" if is_literal else "minor", path, block.attrs["value"].line, address,
                     "The secret value is a literal in code. Remove it and rotate the value." if is_literal else "The secret value is stored in state. Prefer value_wo with an ephemeral value.")
        if kind == "random_password":
            self.add("AZ2", "minor", path, block.line, address, "The generated value is stored in state. Prefer an ephemeral random_password with a write-only argument.")
        if kind in {"azurerm_linux_virtual_machine", "azurerm_windows_virtual_machine"} and "admin_password" in block.attrs and kind.startswith("azurerm_linux"):
            self.add("AZ1", "major", path, block.attrs["admin_password"].line, address, "The virtual machine has a password. Use an SSH key and Entra ID sign-in.")
        self.upgrade(path, block, "resources", "removed_resources", admits_v5)

    def security_rule(self, path: Path, rule: Block, address: str) -> None:
        def value(name: str) -> str:
            return (literal(rule.attrs[name].value) or "").lower() if name in rule.attrs else ""

        sources = {value("source_address_prefix")}
        if "source_address_prefixes" in rule.attrs:
            sources |= {source.lower() for source in re.findall(r'"([^"]*)"', rule.attrs["source_address_prefixes"].value)}
        if value("direction") != "inbound" or value("access") != "allow" or not sources & OPEN_SOURCES:
            return
        ports = value("destination_port_range") + " " + (rule.attrs["destination_port_ranges"].value if "destination_port_ranges" in rule.attrs else "")
        risky = "*" in ports
        for low, high in re.findall(r"(\d+)(?:-(\d+))?", ports):
            risky = risky or any(int(low) <= port <= int(high or low) for port in (22, 3389))
        if risky:
            self.add("AZ3", "blocker", path, rule.line, address, "A management port is open to the internet. Use Bastion or a private path.")

    def upgrade(self, path: Path, block: Block, changed_key: str, removed_key: str, admits_v5: bool) -> None:
        kind = block.labels[0]
        address = ("data." if changed_key == "data_sources" else "") + ".".join(block.labels)
        severity = "major" if admits_v5 else "minor"
        prefix = "" if admits_v5 else "Before upgrading to azurerm 5: "
        if kind in self.changes.get(removed_key, {}):
            successors = self.changes[removed_key][kind]
            use = f" Use {' or '.join(successors)}." if successors else ""
            self.add("AZ8", severity, path, block.line, address, f"{prefix}{kind} was removed in azurerm 5.0.{use}")
        for change in self.changes.get(changed_key, {}).get(kind, []):
            target, use = change["path"], change.get("use")
            if change["kind"] in {"renamed", "removed"} and block.has(target):
                attrs = block.find(target)
                self.add("AZ8", severity, path, attrs[0].line if attrs else block.line, address,
                         f"{prefix}{target} was removed in azurerm 5.0." + (f" Use {use}." if use else ""))
            elif change["kind"] == "values":
                for attr in block.find(target):
                    if literal(attr.value) in change.get("values", []):
                        self.add("AZ8", severity, path, attr.line, address, f"{prefix}{target} no longer accepts {literal(attr.value)} in azurerm 5.0.")
            elif change["kind"] == "required" and admits_v5 and not block.has(target) and ("." not in target or block.has(target.rpartition(".")[0])):
                self.add("AZ8", "major", path, block.line, address, f"{target} is required from azurerm 5.0.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Terraform for Azure against the authoring standard. Read-only.")
    parser.add_argument("directory", nargs="?", default=".", help="directory to scan (default: the current directory)")
    parser.add_argument("--json", action="store_true", help="print findings as JSON")
    parser.add_argument("--fail-on", choices=SEVERITIES, help="exit 1 when a finding at or above this level exists")
    parser.add_argument("--rules", help="comma-separated rule IDs to report, for example ST2,AZ3")
    arguments = parser.parse_args(argv)
    root = Path(arguments.directory).resolve()
    if not root.is_dir():
        print(f"Error: {arguments.directory} is not a directory.", file=sys.stderr)
        return 2
    try:
        findings = Audit(root).run()
    except (OSError, UnicodeDecodeError) as error:
        print(f"Error: could not read the configuration: {error}", file=sys.stderr)
        return 2
    if arguments.rules:
        wanted = {rule.strip().upper() for rule in arguments.rules.split(",")}
        findings = [finding for finding in findings if finding["rule"] in wanted]
    counts = {level: sum(finding["severity"] == level for finding in findings) for level in SEVERITIES}
    if arguments.json:
        print(json.dumps({"directory": str(root), "counts": counts, "findings": findings}, indent=2))
    else:
        for finding in findings:
            print(f'{finding["severity"]:<8}{finding["rule"]:<6}{finding["file"]}:{finding["line"]}  {finding["subject"]}: {finding["message"]}')
        print(f'{counts["blocker"]} blocker, {counts["major"]} major, {counts["minor"]} minor. Checked by text only: values that are expressions are not judged.')
    if arguments.fail_on:
        threshold = SEVERITIES.index(arguments.fail_on)
        return 1 if any(SEVERITIES.index(finding["severity"]) <= threshold for finding in findings) else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
