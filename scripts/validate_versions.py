#!/usr/bin/env python3
"""Validate that every release version field agrees with the release-please manifest."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any


SEMVER = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?"
MARKER = "x-release-please-version"
MANIFEST = ".release-please-manifest.json"
CONFIG = "release-please-config.json"
MARKETPLACE = ".claude-plugin/marketplace.json"
# Patterns run one line at a time. `[ \t]` is used instead of `\s` so that a
# match can never run across a line break.
FRONTMATTER_VERSION_KEY_RE = re.compile(r"^[ \t]+version:")
FRONTMATTER_VERSION_RE = re.compile(rf'^[ \t]+version:[ \t]*"?({SEMVER})"?[ \t]*(?:#.*)?$')
README_VERSION_RE = re.compile(rf"Version: `({SEMVER})`")


def main() -> int:
    root = Path.cwd()
    expected = read_manifest_version(root / MANIFEST)
    if expected is None:
        print(f"{MANIFEST}: missing or invalid root version `.`")
        return 1

    listed, errors = read_extra_files(root)
    checked: set[str] = set()
    errors.extend(check_plugin_manifests(root, expected, listed, checked))
    errors.extend(check_marketplace(root, expected, checked))
    errors.extend(check_skills(root, expected, checked))
    errors.extend(check_extra_files(root, listed, checked))

    if errors:
        print(f"Release version validation failed against the release-please manifest ({expected}):")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"All release version fields match the release-please manifest ({expected}).")
    return 0


def read_manifest_version(path: Path) -> str | None:
    payload, _ = load_json(path)
    version = payload.get(".") if payload is not None else None
    if isinstance(version, str) and re.fullmatch(SEMVER, version):
        return version
    return None


def read_extra_files(root: Path) -> tuple[list[str], list[str]]:
    """Return the paths release-please rewrites, plus any problem reading the config."""
    config, problem = load_json(root / CONFIG)
    if config is None:
        return [], [f"{CONFIG}: {problem}"]
    packages = config.get("packages")
    package = packages.get(".") if isinstance(packages, dict) else None
    extra_files = package.get("extra-files") if isinstance(package, dict) else None
    if not isinstance(extra_files, list):
        return [], [f'{CONFIG}: packages["."]["extra-files"] must be a list']

    paths: list[str] = []
    errors: list[str] = []
    for entry in extra_files:
        path = extra_file_path(entry)
        if path:
            paths.append(PurePosixPath(path).as_posix())
        else:
            errors.append(f"{CONFIG}: extra-files entry {entry!r} has no `path`")
    return paths, errors


def extra_file_path(entry: Any) -> str | None:
    # release-please accepts either a bare path or an object with a `path` key.
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict) and isinstance(entry.get("path"), str):
        return entry["path"]
    return None


def check_plugin_manifests(
    root: Path, expected: str, listed: list[str], checked: set[str]
) -> list[str]:
    paths = set(root.glob("plugins/*/.claude-plugin/plugin.json"))
    paths.update(root.glob("plugins/*/.codex-plugin/plugin.json"))
    paths.update(root / item for item in listed if PurePosixPath(item).name == "plugin.json")

    errors: list[str] = []
    for path in sorted(paths):
        rel_path = rel(root, path)
        checked.add(rel_path)
        payload, problem = load_json(path)
        if payload is None:
            errors.append(f"{rel_path}: {problem}")
        else:
            errors.extend(compare(root, path, "version", payload.get("version"), expected))
    return errors


def check_marketplace(root: Path, expected: str, checked: set[str]) -> list[str]:
    path = root / MARKETPLACE
    rel_path = rel(root, path)
    checked.add(rel_path)
    payload, problem = load_json(path)
    if payload is None:
        return [f"{rel_path}: {problem}"]

    errors: list[str] = []
    if "version" in payload:
        errors.extend(compare(root, path, "version", payload["version"], expected))
    else:
        errors.append(f"{rel_path}: `version` is required")

    metadata = payload.get("metadata")
    if isinstance(metadata, dict) and "version" in metadata:
        errors.extend(compare(root, path, "metadata.version", metadata["version"], expected))
    else:
        errors.append(f"{rel_path}: `metadata.version` is required")

    plugins = payload.get("plugins", [])
    for index, entry in enumerate(plugins if isinstance(plugins, list) else []):
        if isinstance(entry, dict) and "version" in entry:
            errors.append(
                f"{rel_path}: plugins[{index}].version must not be set; "
                "plugin.json is the single source and Claude Code ignores the entry value"
            )
    return errors


def check_skills(root: Path, expected: str, checked: set[str]) -> list[str]:
    errors: list[str] = []
    for skill_file in sorted(root.glob("plugins/*/skills/*/SKILL.md")):
        errors.extend(check_skill_file(root, skill_file, expected, checked))
    for readme in sorted(root.glob("plugins/*/skills/*/README.md")):
        errors.extend(check_readme(root, readme, expected, checked))
    return errors


def check_skill_file(root: Path, skill_file: Path, expected: str, checked: set[str]) -> list[str]:
    rel_path = rel(root, skill_file)
    checked.add(rel_path)
    text, problem = load_text(skill_file)
    if text is None:
        return [f"{rel_path}: {problem}"]
    lines = frontmatter_lines(text)
    if lines is None:
        return [f"{rel_path}: missing YAML frontmatter"]

    version_lines = [line for line in lines if FRONTMATTER_VERSION_KEY_RE.match(line)]
    if not version_lines:
        return [f"{rel_path}: frontmatter has no indented `version:` line under `metadata`"]

    errors: list[str] = []
    for line in version_lines:
        match = FRONTMATTER_VERSION_RE.match(line)
        actual = match.group(1) if match else line.strip()
        errors.extend(compare(root, skill_file, "metadata.version", actual, expected))
        if MARKER not in line:
            errors.append(f"{rel_path}: metadata.version line lacks `{MARKER}` on the same line")
    return errors


def check_readme(root: Path, readme: Path, expected: str, checked: set[str]) -> list[str]:
    rel_path = rel(root, readme)
    checked.add(rel_path)
    text, problem = load_text(readme)
    if text is None:
        return [f"{rel_path}: {problem}"]

    matches: list[tuple[str, str]] = []
    for line in text.split("\n"):
        match = README_VERSION_RE.search(line)
        if match:
            matches.append((line, match.group(1)))
    if not matches:
        return [f"{rel_path}: no line of the form Version: `<semver>`"]

    errors: list[str] = []
    for line, actual in matches:
        errors.extend(compare(root, readme, "Version", actual, expected))
        if MARKER not in line:
            errors.append(f"{rel_path}: Version line lacks `{MARKER}` on the same line")
    return errors


def check_extra_files(root: Path, listed: list[str], checked: set[str]) -> list[str]:
    errors: list[str] = []
    for path in listed:
        if not (root / path).is_file():
            errors.append(f"{CONFIG}: extra-files path `{path}` does not exist")
        elif path not in checked:
            errors.append(
                f"{CONFIG}: extra-files path `{path}` is not checked by validate_versions.py"
            )
    return errors


def frontmatter_lines(text: str) -> list[str] | None:
    """Return the lines between the opening and closing `---` lines, or None."""
    lines = text.split("\n")
    if lines[0] != "---" or "---" not in lines[1:]:
        return None
    return lines[1 : lines.index("---", 1)]


def load_text(path: Path) -> tuple[str | None, str | None]:
    """Read UTF-8 text, dropping a byte-order mark and normalising CRLF line endings."""
    if not path.is_file():
        return None, "missing file"
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"unreadable ({exc})"
    return text.replace("\r\n", "\n"), None


def load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Return the JSON object in `path`, or None with the reason it cannot be used."""
    text, problem = load_text(path)
    if text is None:
        return None, problem
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON ({exc})"
    if not isinstance(payload, dict):
        return None, "must be a JSON object"
    return payload, None


def compare(root: Path, path: Path, field: str, actual: Any, expected: str) -> list[str]:
    if actual == expected:
        return []
    return [f"{rel(root, path)}: {field} is {actual!r}, expected {expected!r}"]


def rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:  # a config path that points outside the repository
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
