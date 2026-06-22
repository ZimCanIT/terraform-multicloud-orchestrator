#!/usr/bin/env python3
"""Validate Agent Skill frontmatter."""

from __future__ import annotations

import re
from pathlib import Path


ALLOWED_FIELDS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# A tool token is a tool name with an optional `(...)` permission qualifier.
# Spaces are allowed inside the parentheses so scoped Bash commands such as
# `Bash(terraform plan:*)` are valid; commas and nested parentheses are not.
TOOL_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(?:\([^(),]+\))?$")


def main() -> int:
    skill_files = sorted(Path.cwd().glob("plugins/*/skills/*/SKILL.md"))
    if not skill_files:
        print("No SKILL.md files found under plugins/*/skills/*/SKILL.md")
        return 1

    errors: list[str] = []
    for skill_file in skill_files:
        errors.extend(validate_skill(skill_file))

    if errors:
        print("Agent Skill frontmatter validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Validated {len(skill_files)} Agent Skill frontmatter file(s).")
    return 0


def validate_skill(skill_file: Path) -> list[str]:
    errors: list[str] = []
    rel_path = skill_file.as_posix()
    text = skill_file.read_text(encoding="utf-8")

    if not text.startswith("---\n"):
        return [f"{rel_path}: missing opening YAML frontmatter marker"]

    end = text.find("\n---", 4)
    if end == -1:
        return [f"{rel_path}: missing closing YAML frontmatter marker"]

    frontmatter_text = text[4:end]
    try:
        frontmatter = parse_frontmatter(frontmatter_text)
    except ValueError as exc:
        return [f"{rel_path}: {exc}"]

    unexpected = sorted(set(frontmatter) - ALLOWED_FIELDS)
    for field in unexpected:
        errors.append(f"{rel_path}: unexpected frontmatter field `{field}`")

    name = frontmatter.get("name")
    if not isinstance(name, str) or not name:
        errors.append(f"{rel_path}: `name` is required")
    elif not NAME_RE.fullmatch(name):
        errors.append(
            f"{rel_path}: `name` must be lowercase kebab-case without repeated hyphens"
        )
    elif name != skill_file.parent.name:
        errors.append(f"{rel_path}: `name` must match skill folder `{skill_file.parent.name}`")

    description = frontmatter.get("description")
    if not isinstance(description, str) or not description:
        errors.append(f"{rel_path}: `description` is required")
    elif len(description) > 1024:
        errors.append(f"{rel_path}: `description` exceeds 1024 characters")

    compatibility = frontmatter.get("compatibility")
    if compatibility is not None and (
        not isinstance(compatibility, str) or not 1 <= len(compatibility) <= 500
    ):
        errors.append(f"{rel_path}: `compatibility` must be 1-500 characters")

    metadata = frontmatter.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        errors.append(f"{rel_path}: `metadata` must be a key-value mapping")

    allowed_tools = frontmatter.get("allowed-tools")
    if allowed_tools is not None:
        validate_allowed_tools(str(allowed_tools), rel_path, errors)

    return errors


def parse_frontmatter(raw: str) -> dict[str, object]:
    result: dict[str, object] = {}
    active_mapping: str | None = None

    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue

        if line.startswith("  "):
            if active_mapping is None:
                raise ValueError(f"unexpected indented line {line_number}")
            key, value = split_key_value(line.strip(), line_number)
            mapping = result.setdefault(active_mapping, {})
            if not isinstance(mapping, dict):
                raise ValueError(f"`{active_mapping}` cannot contain nested values")
            mapping[key] = clean_scalar(value)
            continue

        key, value = split_key_value(line, line_number)
        if value == "":
            result[key] = {}
            active_mapping = key
        else:
            result[key] = clean_scalar(value)
            active_mapping = None

    return result


def split_key_value(line: str, line_number: int) -> tuple[str, str]:
    if ":" not in line:
        raise ValueError(f"frontmatter line {line_number} is not `key: value`")
    key, value = line.split(":", 1)
    key = key.strip()
    if not key:
        raise ValueError(f"frontmatter line {line_number} has an empty key")
    return key, value.strip()


def clean_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def validate_allowed_tools(value: str, rel_path: str, errors: list[str]) -> None:
    if not value.strip():
        errors.append(f"{rel_path}: `allowed-tools` must not be empty")
        return
    if "," in value:
        errors.append(
            f"{rel_path}: `allowed-tools` must be space-separated, not comma-separated"
        )
        return
    for token in split_tool_tokens(value):
        if not TOOL_TOKEN_RE.fullmatch(token):
            errors.append(
                f"{rel_path}: invalid `allowed-tools` token `{token}`; "
                "use space-separated entries, e.g. `Read` or `Bash(terraform plan:*)`"
            )


def split_tool_tokens(value: str) -> list[str]:
    """Split on whitespace, but keep `(...)` qualifiers intact so a scoped
    command such as `Bash(terraform plan:*)` stays a single token."""
    tokens: list[str] = []
    current = ""
    depth = 0
    for char in value:
        if char == "(":
            depth += 1
            current += char
        elif char == ")":
            depth = max(0, depth - 1)
            current += char
        elif char.isspace() and depth == 0:
            if current:
                tokens.append(current)
                current = ""
        else:
            current += char
    if current:
        tokens.append(current)
    return tokens


if __name__ == "__main__":
    raise SystemExit(main())
