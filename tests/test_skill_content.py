"""Offline consistency checks for the skill's own files: rule IDs, file references and the reference stack."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "plugins/terraform-multicloud-orchestrator/skills/terraform-multicloud-orchestrator"
SKILL_MD = SKILL / "SKILL.md"
STACK = SKILL / "assets/reference-stack"

RULE_DEFINITION_RE = re.compile(r"^- \*\*((?:ST|MD|HC|AZ)\d)\*\* ", re.MULTILINE)
RULE_CITATION_RE = re.compile(r"\b((?:ST|MD|HC|AZ)\d)\b")
SKILL_PATH_RE = re.compile(r"`((?:references|assets|scripts)/[^`<>*{}\s]+)`")
SIBLING_RE = re.compile(r"`([a-z][a-z-]*\.md)`")


def markdown_files() -> list[Path]:
    return sorted(path for path in SKILL.rglob("*.md"))


def defined_rules() -> list[str]:
    return RULE_DEFINITION_RE.findall(SKILL_MD.read_text(encoding="utf-8"))


def test_rule_ids_are_unique_and_grouped() -> None:
    rules = defined_rules()
    assert len(rules) == len(set(rules)), "a rule ID is defined twice in SKILL.md"
    for prefix in ("ST", "MD", "HC", "AZ"):
        numbers = [int(rule[2:]) for rule in rules if rule.startswith(prefix)]
        assert numbers == list(range(1, len(numbers) + 1)), f"{prefix} rules must be numbered from 1 without gaps"


def test_readme_states_the_real_rule_count() -> None:
    match = re.search(r"lists (\d+) rules", (REPO / "README.md").read_text(encoding="utf-8"))
    assert match, "README.md no longer states how many rules SKILL.md lists"
    assert int(match.group(1)) == len(defined_rules())


@pytest.mark.parametrize("path", markdown_files(), ids=lambda path: path.relative_to(SKILL).as_posix())
def test_cited_rule_ids_exist(path: Path) -> None:
    known = set(defined_rules())
    cited = set(RULE_CITATION_RE.findall(path.read_text(encoding="utf-8")))
    assert cited <= known, f"{path.name} cites rule IDs that SKILL.md does not define: {sorted(cited - known)}"


@pytest.mark.parametrize("path", markdown_files(), ids=lambda path: path.relative_to(SKILL).as_posix())
def test_named_skill_paths_exist(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    missing = [name for name in SKILL_PATH_RE.findall(text) if not (SKILL / name.rstrip(".,;:")).exists()]
    assert not missing, f"{path.name} names paths that do not exist in the skill: {missing}"


@pytest.mark.parametrize("path", sorted((SKILL / "references").glob("*.md")), ids=lambda path: path.name)
def test_sibling_references_exist(path: Path) -> None:
    names = set(SIBLING_RE.findall(path.read_text(encoding="utf-8"))) - {"README.md"}
    missing = sorted(name for name in names if not (path.parent / name).exists())
    assert not missing, f"{path.name} names reference files that do not exist: {missing}"


def test_every_reference_is_routed_and_listed() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    routing = text[text.index("## 5. What to load") : text.index("## 6. ")]
    listing = text[text.index("## Files in this skill") :]
    for reference in sorted((SKILL / "references").glob("*.md")):
        name = f"references/{reference.name}"
        assert name in routing, f"{name} is not in the routing table in SKILL.md section 5"
        assert name in listing, f"{name} is not in the file list at the end of SKILL.md"


def test_every_reference_module_has_tests() -> None:
    modules = sorted(path for path in (STACK / "modules").iterdir() if path.is_dir())
    assert modules, "the reference stack has no modules"
    for module in modules:
        assert list(module.glob("*.tf")), f"{module.name} has no Terraform files"
        assert list((module / "tests").glob("*.tftest.hcl")), f"{module.name} has no plan-mode tests"


def test_reference_stack_tests_never_apply() -> None:
    """CI runs these with `terraform test`, which creates real resources unless every run block plans."""
    for test_file in sorted(STACK.rglob("*.tftest.hcl")):
        text = test_file.read_text(encoding="utf-8")
        runs = len(re.findall(r'^run "', text, re.MULTILINE))
        plans = len(re.findall(r"^\s*command\s*=\s*plan\s*$", text, re.MULTILINE))
        assert runs > 0 and runs == plans, f"{test_file.name}: every run block must set `command = plan`"
        assert re.search(r'^mock_provider "azurerm" \{\}', text, re.MULTILINE), f"{test_file.name} must mock the provider"
