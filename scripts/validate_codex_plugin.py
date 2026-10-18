#!/usr/bin/env python3
"""Validate Codex plugin manifests, the Codex marketplace and the shared manifest fields."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
REQUIRED_INTERFACE_FIELDS = {
    "displayName",
    "shortDescription",
    "longDescription",
    "developerName",
    "category",
    "capabilities",
}
UNSUPPORTED_FIELDS = {"hooks"}
CODEX_MARKETPLACE = ".agents/plugins/marketplace.json"
# Fields that must agree between a plugin's Claude and Codex manifests.
# `description` is left out on purpose: the two manifests carry different copy.
SHARED_FIELDS = ("name", "version")


def main() -> int:
    repo_root = Path.cwd()
    manifests = sorted(repo_root.glob("plugins/*/.codex-plugin/plugin.json"))
    if not manifests:
        print("No Codex plugin manifests found under plugins/*/.codex-plugin/plugin.json")
        return 1

    errors: list[str] = []
    for manifest_path in manifests:
        errors.extend(validate_manifest(manifest_path))
    errors.extend(validate_marketplace(repo_root, manifests))
    errors.extend(validate_shared_fields(repo_root))

    if errors:
        print("Codex plugin validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Validated {len(manifests)} Codex plugin manifest(s).")
    return 0


def validate_manifest(manifest_path: Path) -> list[str]:
    errors: list[str] = []
    plugin_root = manifest_path.parent.parent
    rel_manifest = manifest_path.as_posix()

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{rel_manifest}: invalid JSON: {exc}"]

    if not isinstance(manifest, dict):
        return [f"{rel_manifest}: manifest must be a JSON object"]

    for field in sorted(UNSUPPORTED_FIELDS.intersection(manifest)):
        errors.append(f"{rel_manifest}: unsupported field `{field}`")

    name = require_string(manifest, "name", rel_manifest, errors)
    if name and name != plugin_root.name:
        errors.append(
            f"{rel_manifest}: name `{name}` must match plugin folder `{plugin_root.name}`"
        )

    version = require_string(manifest, "version", rel_manifest, errors)
    if version and not SEMVER_RE.fullmatch(version):
        errors.append(f"{rel_manifest}: version `{version}` must be semantic versioning")

    require_string(manifest, "description", rel_manifest, errors)
    validate_author(manifest.get("author"), rel_manifest, errors)
    validate_skills_path(plugin_root, manifest, rel_manifest, errors)
    validate_interface(manifest.get("interface"), rel_manifest, errors)
    reject_todo_markers(manifest, rel_manifest, "$", errors)

    return errors


def require_string(
    payload: dict[str, Any],
    field: str,
    rel_manifest: str,
    errors: list[str],
) -> str | None:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{rel_manifest}: `{field}` must be a non-empty string")
        return None
    return value


def validate_author(value: Any, rel_manifest: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{rel_manifest}: `author` must be an object")
        return
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{rel_manifest}: `author.name` must be a non-empty string")


def validate_skills_path(
    plugin_root: Path,
    manifest: dict[str, Any],
    rel_manifest: str,
    errors: list[str],
) -> None:
    raw_path = manifest.get("skills")
    if raw_path is None:
        return
    if raw_path != "./skills/":
        errors.append(f"{rel_manifest}: `skills` must be `./skills/` when present")
        return
    if not (plugin_root / "skills").is_dir():
        errors.append(f"{rel_manifest}: `skills` points to missing ./skills/ directory")


def validate_interface(value: Any, rel_manifest: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{rel_manifest}: `interface` must be an object")
        return

    missing = REQUIRED_INTERFACE_FIELDS - set(value)
    for field in sorted(missing):
        errors.append(f"{rel_manifest}: `interface.{field}` is required")

    for field in REQUIRED_INTERFACE_FIELDS - {"capabilities"}:
        if field in missing:
            continue
        field_value = value.get(field)
        if not isinstance(field_value, str) or not field_value.strip():
            errors.append(f"{rel_manifest}: `interface.{field}` must be a non-empty string")

    capabilities = value.get("capabilities")
    if not isinstance(capabilities, list) or not all(
        isinstance(item, str) and item.strip() for item in capabilities
    ):
        errors.append(f"{rel_manifest}: `interface.capabilities` must be string array")

    if "default_prompt" in value and "defaultPrompt" not in value:
        errors.append(
            f"{rel_manifest}: use `interface.defaultPrompt` (camelCase), not `default_prompt`"
        )
    default_prompt = value.get("defaultPrompt")
    if not isinstance(default_prompt, list) or not all(
        isinstance(item, str) and item.strip() for item in default_prompt
    ):
        errors.append(f"{rel_manifest}: `interface.defaultPrompt` must be string array")


def validate_marketplace(repo_root: Path, manifests: list[Path]) -> list[str]:
    """Each Codex plugin must be listed by name in the Codex marketplace."""
    marketplace_path = repo_root / CODEX_MARKETPLACE
    rel_marketplace = marketplace_path.as_posix()
    if not marketplace_path.is_file():
        return [f"{rel_marketplace}: missing Codex marketplace file"]
    try:
        payload = json.loads(marketplace_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"{rel_marketplace}: invalid JSON: {exc}"]
    if not isinstance(payload, dict):
        return [f"{rel_marketplace}: marketplace must be a JSON object"]
    plugins = payload.get("plugins")
    if not isinstance(plugins, list):
        return [f"{rel_marketplace}: `plugins` must be an array"]

    listed = {
        entry["name"]
        for entry in plugins
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }
    errors: list[str] = []
    for manifest_path in manifests:
        manifest, _ = read_object(manifest_path)
        name = manifest.get("name") if manifest is not None else None
        if isinstance(name, str) and name not in listed:
            errors.append(f"{rel_marketplace}: no `plugins` entry names `{name}`")
    return errors


def validate_shared_fields(repo_root: Path) -> list[str]:
    """A plugin's Claude and Codex manifests must agree on SHARED_FIELDS."""
    plugin_dirs = {
        path.parent.parent
        for pattern in (".claude-plugin", ".codex-plugin")
        for path in repo_root.glob(f"plugins/*/{pattern}/plugin.json")
    }

    errors: list[str] = []
    for plugin_dir in sorted(plugin_dirs):
        claude_path = plugin_dir / ".claude-plugin" / "plugin.json"
        codex_path = plugin_dir / ".codex-plugin" / "plugin.json"
        claude, problem = read_object(claude_path)
        if claude is None:
            errors.append(f"{claude_path.as_posix()}: {problem}; cannot compare with Codex")
            continue
        if not codex_path.is_file():
            errors.append(f"{codex_path.as_posix()}: missing; cannot compare with Claude")
            continue
        codex, _ = read_object(codex_path)
        if codex is None:
            continue  # validate_manifest reports an unreadable Codex manifest

        for field in SHARED_FIELDS:
            if claude.get(field) != codex.get(field):
                errors.append(
                    f"{codex_path.as_posix()}: `{field}` is {codex.get(field)!r}, "
                    f"but {claude_path.as_posix()} has {claude.get(field)!r}"
                )
    return errors


def read_object(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Return the JSON object in `path`, or None with the reason it cannot be used."""
    if not path.is_file():
        return None, "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "manifest must be a JSON object"
    return payload, None


def reject_todo_markers(
    value: Any,
    rel_manifest: str,
    path: str,
    errors: list[str],
) -> None:
    if isinstance(value, str):
        if "[TODO:" in value:
            errors.append(f"{rel_manifest}: {path} contains a TODO placeholder")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            reject_todo_markers(item, rel_manifest, f"{path}[{index}]", errors)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            reject_todo_markers(item, rel_manifest, f"{path}.{key}", errors)


if __name__ == "__main__":
    raise SystemExit(main())
