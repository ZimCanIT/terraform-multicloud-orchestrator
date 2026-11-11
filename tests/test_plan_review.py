"""Tests for the skill's plan reader."""

from __future__ import annotations

import importlib.util
import io
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "plugins/terraform-multicloud-orchestrator/skills/terraform-multicloud-orchestrator"

spec = importlib.util.spec_from_file_location("plan_review", SKILL / "scripts/plan_review.py")
plan_review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan_review)

# A value that must never appear in any output.
HIDDEN = "do-not-print-" + "this"


def change(address: str, kind: str, actions: list[str], **extra) -> dict:
    item = {"address": address, "mode": "managed", "type": kind, "name": address.split(".")[-1],
            "change": {"actions": actions, "before": {"value": HIDDEN}, "after": {"value": HIDDEN}}}
    item["change"].update(extra.pop("change", {}))
    item.update(extra)
    return item


PLAN = {
    "format_version": "1.2",
    "resource_changes": [
        change("azurerm_resource_group.this", "azurerm_resource_group", ["no-op"]),
        change("azurerm_storage_account.this", "azurerm_storage_account", ["delete", "create"],
               action_reason="replace_because_cannot_update", change={"replace_paths": [["name"], ["network_rules", 0, "default_action"]]}),
        change("azurerm_role_assignment.reader", "azurerm_role_assignment", ["create", "delete"], change={"replace_paths": [["principal_type"]]}),
        change('module.network.azurerm_subnet.this["app"]', "azurerm_subnet", ["delete"], action_reason="delete_because_each_key"),
        change("azurerm_key_vault.this", "azurerm_key_vault", ["update"]),
        change("azurerm_public_ip.old", "azurerm_public_ip", ["delete"], deposed="00000001"),
        change("azurerm_private_endpoint.blob", "azurerm_private_endpoint", ["create"]),
        change("azurerm_virtual_network.hub", "azurerm_virtual_network", ["no-op"], previous_address="azurerm_virtual_network.main"),
        change("azurerm_log_analytics_workspace.this", "azurerm_log_analytics_workspace", ["no-op"], change={"importing": {"id": HIDDEN}}),
        change("azurerm_application_insights.legacy", "azurerm_application_insights", ["forget"]),
        {"address": "data.azurerm_client_config.current", "mode": "data", "type": "azurerm_client_config", "change": {"actions": ["read"]}},
    ],
}


def test_review_classifies_changes() -> None:
    report = plan_review.review(PLAN)
    assert report["counts"] == {"create": 1, "update": 1, "delete": 2, "replace": 2}
    assert [(entry["action"], entry["address"], entry["stop"] is not None) for entry in report["deletions"]] == [
        ("delete", "azurerm_public_ip.old", True),
        ("replace", "azurerm_storage_account.this", True),
        ("delete", 'module.network.azurerm_subnet.this["app"]', True),
        ("replace", "azurerm_role_assignment.reader", False),
    ]
    assert report["deletions"][0]["deposed"] is True
    storage = report["deletions"][1]
    assert storage["forced_by"] == ["name", "network_rules[0].default_action"] and storage["reason"] == "replace_because_cannot_update"
    assert {(note["note"], note["address"]) for note in report["notes"]} == {
        ("moved", "azurerm_virtual_network.hub"),
        ("import", "azurerm_log_analytics_workspace.this"),
        ("forget", "azurerm_application_insights.legacy"),
    }
    assert report["stopped"] == 3


def test_output_never_prints_values(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(PLAN), encoding="utf-8")
    assert plan_review.main([str(path)]) == 0
    text = capsys.readouterr().out
    assert plan_review.main(["--json", str(path)]) == 0
    text += capsys.readouterr().out
    assert HIDDEN not in text
    assert "STOP  replace azurerm_storage_account.this  [azurerm_storage_account]  (holds data)" in text
    assert "forced by: name, network_rules[0].default_action" in text
    assert "STOP  delete  azurerm_public_ip.old (deposed object)  [azurerm_public_ip]" in text
    assert "4 to delete or replace (3 on the stop list)" in text


def test_exit_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(PLAN), encoding="utf-8")
    assert plan_review.main(["--fail-on-stop", str(path)]) == 3
    assert plan_review.main(["--fail-on-delete", str(path)]) == 3
    quiet = {"resource_changes": [change("azurerm_role_assignment.reader", "azurerm_role_assignment", ["delete", "create"])]}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(quiet)))
    assert plan_review.main(["--fail-on-stop", "-"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"resource_changes": []})))
    assert plan_review.main(["--fail-on-delete", "-"]) == 0
    assert "0 to delete or replace" in capsys.readouterr().out


def test_malformed_entries_do_not_crash_or_hide_changes() -> None:
    plan = {"resource_changes": [
        None, "text", {"address": None, "type": None, "change": None},
        {"address": "azurerm_key_vault.a", "type": "azurerm_key_vault", "change": {"actions": "delete"}},
        {"address": "azurerm_key_vault.b", "type": "azurerm_key_vault", "change": {"actions": ["delete", 1, None], "replace_paths": "name"}},
        {"address": "azurerm_key_vault.c", "type": "azurerm_key_vault", "change": {"actions": ["delete", "create"], "replace_paths": [["a", 0, True, None, "b"], "x"]}},
    ]}
    report = plan_review.review(plan)
    assert [(entry["action"], entry["address"], entry["forced_by"]) for entry in report["deletions"]] == [
        ("delete", "azurerm_key_vault.b", []),
        ("replace", "azurerm_key_vault.c", ["a[0].b"]),
    ]
    assert ("unknown", "azurerm_key_vault.a") in {(note["note"], note["address"]) for note in report["notes"]}
    assert plan_review.review({"resource_changes": {"not": "a list"}})["deletions"] == []


def test_non_string_fields_are_never_printed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plan = {"resource_changes": [
        {"address": "azurerm_key_vault.a", "type": ["azurerm_key_vault"], "previous_address": {"x": HIDDEN}, "action_reason": {"x": HIDDEN},
         "change": {"actions": ["delete"]}},
        {"address": "azurerm_resource_group.rg", "mode": "managed", "type": "azurerm_resource_group", "change": {"actions": ["delete"]}},
    ]}
    path = tmp_path / "plan.json"
    path.write_text("\ufeff" + json.dumps(plan), encoding="utf-8")
    assert plan_review.main(["--fail-on-stop", str(path)]) == 3, "deleting a resource group is on the stop list"
    assert plan_review.main(["--json", str(path)]) == 0
    assert HIDDEN not in capsys.readouterr().out


@pytest.mark.parametrize("content", ["", "not json", "[]", '{"values": {}}', '{"resource_changes": [], "errored": true}'])
def test_unreadable_plan_says_the_check_did_not_run(tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str) -> None:
    path = tmp_path / "plan.json"
    path.write_text(content, encoding="utf-8")
    assert plan_review.main([str(path)]) == 2
    assert "Replacement check NOT performed" in capsys.readouterr().err
    assert plan_review.main([str(tmp_path / "missing.json")]) == 2


def test_stop_list_matches_the_reference() -> None:
    text = (SKILL / "references/azurerm-provider.md").read_text(encoding="utf-8")
    section = text[text.index("## Stop list") :]
    section = section[: section.index("\n## ", 3)]
    documented = set(re.findall(r"`(azurerm_\w+)`", section))
    in_script = set().union(*plan_review.STOP_LIST.values())
    assert documented == in_script, f"only in the reference: {sorted(documented - in_script)}; only in the script: {sorted(in_script - documented)}"
