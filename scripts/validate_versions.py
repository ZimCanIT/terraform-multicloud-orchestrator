#!/usr/bin/env python3
"""Validate that every release version field agrees with the release-please manifest."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SEMVER = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?"
FRONTMATTER_VERSION_RE = re.compile(rf'^\s+version:\s*"?({SEMVER})"?', re.MULTILINE)
README_VERSION_RE = re.compile(rf"Version: `({SEMVER})`")


def main() -> int:
    root = Path.cwd()
    expected = read_manifest_version(root / ".release-please-manifest.json")
    if expected is None:
        print(".release-please-manifest.json: missing or invalid root version `.`")
        return 1

    errors: list[str] = []
    errors.extend(check_plugin_manifests(root, expected))
    errors.extend(check_marketplace(root, expected))
    errors.extend(check_skills(root, expected))

    if errors:
        print(f"Release version fields disagree with the release-please manifest ({expected}):")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"All release version fields match the release-please manifest ({expected}).")
    return 0


def read_manifest_version(path: Path) -> str | None:
    payload = load_json(path)
    version = payload.get(".") if isinstance(payload, dict) else None
    if isinstance(version, str) and re.fullmatch(SEMVER, version):
        return version
    return None


def check_plugin_manifests(root: Path, expected: str) -> list[str]:
    errors: list[str] = []
    paths = sorted(root.glob("plugins/*/.claude-plugin/plugin.json"))
    paths += sorted(root.glob("plugins/*/.codex-plugin/plugin.json"))
    for path in paths:
        payload = load_json(path)
        errors.extend(compare(root, path, "version", payload.get("version"), expected))
    return errors


def check_marketplace(root: Path, expected: str) -> list[str]:
    path = root / ".claude-plugin" / "marketplace.json"
    if not path.is_file():
        return []

    payload = load_json(path)
    errors: list[str] = []
    if "version" in payload:
        errors.extend(compare(root, path, "version", payload["version"], expected))

    metadata = payload.get("metadata")
    if isinstance(metadata, dict) and "version" in metadata:
        errors.extend(compare(root, path, "metadata.version", metadata["version"], expected))

    for index, entry in enumerate(payload.get("plugins", [])):
        if isinstance(entry, dict) and "version" in entry:
            errors.append(
                f"{rel(root, path)}: plugins[{index}].version must not be set; "
                "plugin.json is the single source and Claude Code ignores the entry value"
            )
    return errors


def check_skills(root: Path, expected: str) -> list[str]:
    errors: list[str] = []
    for skill_file in sorted(root.glob("plugins/*/skills/*/SKILL.md")):
        match = FRONTMATTER_VERSION_RE.search(frontmatter(skill_file.read_text(encoding="utf-8")))
        if match:
            errors.extend(compare(root, skill_file, "metadata.version", match.group(1), expected))

    for readme in sorted(root.glob("plugins/*/skills/*/README.md")):
        match = README_VERSION_RE.search(readme.read_text(encoding="utf-8"))
        if match:
            errors.extend(compare(root, readme, "Version", match.group(1), expected))
    return errors


def frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---", 4)
    return text[4:end] if end != -1 else ""


def compare(root: Path, path: Path, field: str, actual: Any, expected: str) -> list[str]:
    if actual == expected:
        return []
    return [f"{rel(root, path)}: {field} is {actual!r}, expected {expected!r}"]


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
