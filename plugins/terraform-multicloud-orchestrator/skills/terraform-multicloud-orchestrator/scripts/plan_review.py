#!/usr/bin/env python3
"""Read a Terraform plan in JSON and report what it deletes, replaces, moves, imports and forgets.

Read-only. It prints addresses, types, actions, reasons and attribute paths. It never prints an
attribute value, because plan JSON holds secrets in clear text.

Usage:
    terraform show -json tfplan | plan_review.py [--fail-on-stop | --fail-on-delete] [--json] -
    plan_review.py [options] PLAN.json

For each deletion or replacement it names the attributes that force it and says whether the type is
on the stop list in references/azurerm-provider.md.

Exit codes: 0 by default; 3 with --fail-on-stop when a stop-list resource is deleted or replaced, or
with --fail-on-delete when anything is; 2 on a usage or read error.
"""

from __future__ import annotations

import argparse
import json
import sys

# The stop list in references/azurerm-provider.md. A test keeps the two in step.
STOP_LIST = {
    "holds data": {
        "azurerm_storage_account", "azurerm_key_vault", "azurerm_mssql_server", "azurerm_mssql_database",
        "azurerm_postgresql_flexible_server", "azurerm_mysql_flexible_server", "azurerm_cosmosdb_account",
        "azurerm_container_registry", "azurerm_log_analytics_workspace", "azurerm_recovery_services_vault", "azurerm_managed_disk",
        "azurerm_resource_group",
    },
    "slow or disruptive to rebuild": {
        "azurerm_kubernetes_cluster", "azurerm_api_management", "azurerm_virtual_network_gateway", "azurerm_firewall",
        "azurerm_application_gateway", "azurerm_app_service_environment_v3", "azurerm_virtual_network", "azurerm_subnet",
    },
    "others depend on its address or identity": {
        "azurerm_public_ip", "azurerm_private_endpoint", "azurerm_user_assigned_identity", "azurerm_private_dns_zone",
    },
}


def stop_reason(kind: str) -> str | None:
    return next((reason for reason, kinds in STOP_LIST.items() if kind in kinds), None)


def label(value: object) -> str:
    """Addresses, types and reasons are strings. Anything else is not printed, in case it holds a value."""
    return value if isinstance(value, str) and value else "?"


def path_text(path: list) -> str:
    """["network_profile", 0, "network_plugin"] -> network_profile[0].network_plugin"""
    text = ""
    for part in path:
        if isinstance(part, bool) or not isinstance(part, (int, str)):
            continue
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else part)
    return text


def review(plan: dict) -> dict:
    changes, notes = [], []
    counts = {"create": 0, "update": 0, "delete": 0, "replace": 0}
    listed = plan.get("resource_changes")
    for item in listed if isinstance(listed, list) else []:
        if not isinstance(item, dict):
            continue
        change = item.get("change") if isinstance(item.get("change"), dict) else {}
        actions = [action for action in change["actions"] if isinstance(action, str)] if isinstance(change.get("actions"), list) else []
        address, kind = label(item.get("address")), label(item.get("type"))
        if item.get("previous_address"):
            notes.append({"note": "moved", "address": address, "detail": f'from {label(item["previous_address"])}'})
        if change.get("importing"):
            notes.append({"note": "import", "address": address, "detail": "brought into state"})
        if "forget" in actions:
            notes.append({"note": "forget", "address": address, "detail": "removed from state, not destroyed"})
        if item.get("mode") == "data" or actions in (["no-op"], ["read"], ["forget"]):
            continue
        if "delete" in actions:
            action = "replace" if "create" in actions else "delete"
        elif "create" in actions:
            action = "create"
        elif "update" in actions:
            action = "update"
        else:
            notes.append({"note": "unknown", "address": address, "detail": "unrecognised action; read the plan"})
            continue
        counts[action] += 1
        if action in ("delete", "replace"):
            paths = change.get("replace_paths")
            changes.append({
                "action": action,
                "address": address,
                "type": kind,
                "stop": stop_reason(kind),
                # A deposed object is the old copy that a create-before-destroy replacement left behind.
                "deposed": bool(item.get("deposed")),
                "forced_by": [path_text(path) for path in paths if isinstance(path, list)] if isinstance(paths, list) else [],
                "reason": label(item.get("action_reason") or change.get("action_reason")).replace("?", ""),
            })
    changes.sort(key=lambda entry: (entry["stop"] is None, entry["address"]))
    return {"counts": counts, "deletions": changes, "notes": notes, "stopped": sum(entry["stop"] is not None for entry in changes)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report what a Terraform plan deletes or replaces. Read-only; prints no values.")
    parser.add_argument("plan", help="plan JSON from `terraform show -json`, or - for standard input")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    gate = parser.add_mutually_exclusive_group()
    gate.add_argument("--fail-on-stop", action="store_true", help="exit 3 when a stop-list resource is deleted or replaced")
    gate.add_argument("--fail-on-delete", action="store_true", help="exit 3 when anything is deleted or replaced")
    arguments = parser.parse_args(argv)
    try:
        text = sys.stdin.read() if arguments.plan == "-" else open(arguments.plan, encoding="utf-8-sig").read()
        plan = json.loads(text.lstrip("\ufeff"))
        if not isinstance(plan, dict):
            raise ValueError("the top level is not an object")
    except (OSError, ValueError) as error:
        print(f"Error: could not read plan JSON: {error}. Replacement check NOT performed.", file=sys.stderr)
        return 2
    if "resource_changes" not in plan and "planned_values" not in plan:
        print("Error: this is not plan JSON from `terraform show -json`. Replacement check NOT performed.", file=sys.stderr)
        return 2
    if plan.get("errored"):
        print("Error: Terraform marked this plan as errored, so it is incomplete. Replacement check NOT performed.", file=sys.stderr)
        return 2
    try:
        report = review(plan)
    except (AttributeError, KeyError, TypeError) as error:
        print(f"Error: the plan JSON has an unexpected shape ({type(error).__name__}). Replacement check NOT performed.", file=sys.stderr)
        return 2
    if plan.get("complete") is False:
        print("Warning: Terraform marked this plan as incomplete, for example a targeted plan. Changes outside it are not shown.", file=sys.stderr)
    if arguments.json:
        print(json.dumps(report, indent=2))
    else:
        for entry in report["deletions"]:
            marker = "STOP" if entry["stop"] else "    "
            suffix = f'  ({entry["stop"]})' if entry["stop"] else ""
            deposed = " (deposed object)" if entry["deposed"] else ""
            print(f'{marker}  {entry["action"]:<8}{entry["address"]}{deposed}  [{entry["type"]}]{suffix}')
            if entry["forced_by"]:
                print(f'          forced by: {", ".join(entry["forced_by"])}')
            if entry["reason"]:
                print(f'          reason: {entry["reason"]}')
        for note in report["notes"]:
            print(f'note  {note["note"]:<8}{note["address"]}  {note["detail"]}')
        counts = report["counts"]
        total = counts["delete"] + counts["replace"]
        print(f'{total} to delete or replace ({report["stopped"]} on the stop list). Create {counts["create"]}, update {counts["update"]}, '
              f'delete {counts["delete"]}, replace {counts["replace"]}.')
        if report["stopped"]:
            print("Stop: confirm each STOP line with the user before any hand-off that leads to apply.")
    if (arguments.fail_on_stop and report["stopped"]) or (arguments.fail_on_delete and report["deletions"]):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
