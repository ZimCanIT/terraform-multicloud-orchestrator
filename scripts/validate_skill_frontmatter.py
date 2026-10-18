#!/usr/bin/env python3
"""Validate Agent Skill frontmatter and the relative paths a SKILL.md body names."""

from __future__ import annotations

import re
from pathlib import Path

try:
    import yaml
except ImportError:  # reported by main() so the failure says what to install
    yaml = None


ALLOWED_FIELDS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}
NAME_MAX_LENGTH = 64
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# A tool token is a tool name with an optional `(...)` permission qualifier.
# Spaces are allowed inside the parentheses so scoped Bash commands such as
# `Bash(terraform plan:*)` are valid; commas and nested parentheses are not.
TOOL_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(?:\([^(),]+\))?$")
# Policy checks for allowed-tools tokens that already pass TOOL_TOKEN_RE.
FORBIDDEN_WORDS = ("apply", "destroy", "import", "-auto-approve")
STATE_WRITE_RE = re.compile(r"\bstate\s+(?:rm|mv|push)\b")
JQ_TOKEN_RE = re.compile(r"^(?:Bash\(\s*)?jq\b")
# jq is only allowed as `Bash(jq [flags] <filter> [file])`, with a non-empty filter and no wildcard.
JQ_EXACT_RE = re.compile(
    r"^Bash\(jq(?:\s+--?[A-Za-z][A-Za-z-]*)*"
    r"\s+(?:'[^'*]+'|\"[^\"*]+\"|[^\s'\"*()]+)"
    r"(?:\s+[^\s'\"*()]+)?\)$"
)
FMT_TOKEN_RE = re.compile(r"^Bash\((?:terraform|tofu)\s+(?:-\S+\s+)*fmt(?=[\s:)]|$)")
# Relative paths named in the body. Tokens containing these characters are
# placeholders such as `references/<cloud>.md` and are not checked.
BODY_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])((?:scripts|references|assets)/[^\s`'\"()\[\]|,;]+)"
)
PLACEHOLDER_CHARS = "<*{}"


def main() -> int:
    if yaml is None:
        print(
            "PyYAML is required to validate SKILL.md frontmatter; "
            "install pyyaml with `python -m pip install pyyaml`."
        )
        return 1

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
    # Same normalisation as validate_versions.py: drop a byte-order mark, use LF.
    lines = skill_file.read_bytes().decode("utf-8-sig").replace("\r\n", "\n").split("\n")

    if lines[0] != "---":
        return [f"{rel_path}: missing opening YAML frontmatter marker"]
    if "---" not in lines[1:]:
        return [f"{rel_path}: missing closing YAML frontmatter marker"]
    end = lines.index("---", 1)

    try:
        frontmatter = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        return [f"{rel_path}: invalid YAML frontmatter: {exc}"]
    if frontmatter is None:
        frontmatter = {}
    if not isinstance(frontmatter, dict):
        return [f"{rel_path}: frontmatter must be a YAML mapping"]

    unexpected = sorted(str(field) for field in frontmatter if field not in ALLOWED_FIELDS)
    for field in unexpected:
        errors.append(f"{rel_path}: unexpected frontmatter field `{field}`")

    name = frontmatter.get("name")
    if not isinstance(name, str) or not name:
        errors.append(f"{rel_path}: `name` is required")
    elif len(name) > NAME_MAX_LENGTH:
        errors.append(f"{rel_path}: `name` must be at most {NAME_MAX_LENGTH} characters")
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

    if "allowed-tools" in frontmatter:
        validate_allowed_tools(frontmatter["allowed-tools"], rel_path, errors)

    body = "\n".join(lines[end + 1 :])
    errors.extend(validate_body_paths(skill_file, body, rel_path))
    return errors


def validate_allowed_tools(value: object, rel_path: str, errors: list[str]) -> None:
    if value is None or (isinstance(value, str) and not value.strip()):
        errors.append(f"{rel_path}: `allowed-tools` must not be empty")
        return
    if not isinstance(value, str):
        errors.append(f"{rel_path}: `allowed-tools` must be a space-separated string")
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
            continue
        problem = policy_problem(token)
        if problem:
            errors.append(f"{rel_path}: `allowed-tools` token `{token}` {problem}")


def policy_problem(token: str) -> str | None:
    """Return why a well-formed allowed-tools token is not allowed, or None."""
    lowered = token.lower()
    if any(word in lowered for word in FORBIDDEN_WORDS) or STATE_WRITE_RE.search(lowered):
        return "must not grant apply, destroy, import, -auto-approve or state rm/mv/push"
    if JQ_TOKEN_RE.match(token) and not JQ_EXACT_RE.match(token):
        return "must scope jq to an exact filter without wildcards, e.g. `Bash(jq -r '.version' file.json)`"
    name, _, qualifier = token.partition("(")
    if name == "WebFetch" and not qualifier.startswith("domain:"):
        return "must be scoped to a domain, e.g. `WebFetch(domain:example.com)`"
    if name == "WebSearch" and not qualifier:
        return "must not be bare"
    if FMT_TOKEN_RE.match(token) and "-check" not in token:
        return "must be a `fmt` form with `-check`"
    return None


def validate_body_paths(skill_file: Path, body: str, rel_path: str) -> list[str]:
    skill_dir = skill_file.parent.resolve()
    errors: list[str] = []
    seen: set[str] = set()
    for match in BODY_PATH_RE.finditer(body):
        path = match.group(1).split("#", 1)[0].rstrip(".:!?")
        if not path or path in seen or any(char in path for char in PLACEHOLDER_CHARS):
            continue
        seen.add(path)
        target = (skill_dir / path).resolve()
        if not target.is_relative_to(skill_dir) or not target.exists():
            errors.append(
                f"{rel_path}: `{path}` is named in the body but does not exist "
                "inside the skill directory"
            )
    return errors


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
