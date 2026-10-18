"""Behavioural tests for the release, Agent Skill and Codex validators.

Each case builds a small repository tree under tmp_path, runs one validator with
that tree as its working directory, and asserts on the exit status and output.
The scripts come from this repository's scripts/ directory unless
VALIDATOR_SCRIPTS_DIR names another directory, so the same cases can be run
against an older copy of the scripts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(os.environ.get("VALIDATOR_SCRIPTS_DIR") or REPO_ROOT / "scripts")
PLUGIN = "terraform-multicloud-orchestrator"
SKILL_DIR = f"plugins/{PLUGIN}/skills/{PLUGIN}"
RELEASE_FILES = [
    f"plugins/{PLUGIN}/.claude-plugin/plugin.json",
    f"plugins/{PLUGIN}/.codex-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    f"{SKILL_DIR}/SKILL.md",
    f"{SKILL_DIR}/README.md",
]
SKILL_MD = """\
---
name: terraform-multicloud-orchestrator
description: Use when testing the validators.
license: MIT
metadata:
  version: "0.1.1" # x-release-please-version
allowed-tools: Read Grep Glob
---

# Skill
"""
README_MD = """\
# Skill

- Version: `0.1.1` <!-- x-release-please-version --> · License: MIT
"""
CODEX_MANIFEST = {
    "name": PLUGIN,
    "version": "0.1.1",
    "description": "Codex copy of the description.",
    "author": {"name": "Test Author"},
    "interface": {
        "displayName": "Test",
        "shortDescription": "Short.",
        "longDescription": "Long.",
        "developerName": "Test Author",
        "category": "Developer Tools",
        "capabilities": ["Write"],
        "defaultPrompt": ["Write a module."],
    },
}


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def write_json(root: Path, rel: str, payload: object) -> None:
    write(root, rel, json.dumps(payload, indent=2) + "\n")


def run(root: Path, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def write_config(root: Path, paths: list[str]) -> None:
    extra = [{"type": "generic", "path": path} for path in paths]
    write_json(root, "release-please-config.json", {"packages": {".": {"extra-files": extra}}})


def write_release_tree(root: Path) -> None:
    write_json(root, ".release-please-manifest.json", {".": "0.1.1"})
    write_config(root, RELEASE_FILES)
    write_json(
        root,
        ".claude-plugin/marketplace.json",
        {
            "name": "zimcanit-marketplace",
            "version": "0.1.1",
            "metadata": {"version": "0.1.1"},
            "plugins": [{"name": PLUGIN, "source": f"./plugins/{PLUGIN}"}],
        },
    )
    write_json(root, f"plugins/{PLUGIN}/.claude-plugin/plugin.json", {"name": PLUGIN, "version": "0.1.1"})
    write_json(root, f"plugins/{PLUGIN}/.codex-plugin/plugin.json", {"name": PLUGIN, "version": "0.1.1"})
    write(root, f"{SKILL_DIR}/SKILL.md", SKILL_MD)
    write(root, f"{SKILL_DIR}/README.md", README_MD)


# --- validate_versions.py -------------------------------------------------


def test_release_tree_passes(tmp_path):
    write_release_tree(tmp_path)
    assert run(tmp_path, "validate_versions.py").returncode == 0


def test_skill_version_without_marker_fails(tmp_path):
    write_release_tree(tmp_path)
    write(tmp_path, f"{SKILL_DIR}/SKILL.md", SKILL_MD.replace(" # x-release-please-version", ""))
    result = run(tmp_path, "validate_versions.py")
    assert result.returncode == 1
    assert "x-release-please-version" in result.stdout


def test_readme_version_without_marker_fails(tmp_path):
    write_release_tree(tmp_path)
    write(tmp_path, f"{SKILL_DIR}/README.md", README_MD.replace(" <!-- x-release-please-version -->", ""))
    assert run(tmp_path, "validate_versions.py").returncode == 1


def test_wrong_skill_version_fails(tmp_path):
    write_release_tree(tmp_path)
    write(tmp_path, f"{SKILL_DIR}/SKILL.md", SKILL_MD.replace('"0.1.1"', '"0.1.0"'))
    assert run(tmp_path, "validate_versions.py").returncode == 1


def test_bom_skill_with_wrong_version_fails(tmp_path):
    write_release_tree(tmp_path)
    text = "﻿" + SKILL_MD.replace('"0.1.1"', '"0.1.0"')
    write(tmp_path, f"{SKILL_DIR}/SKILL.md", text)
    result = run(tmp_path, "validate_versions.py")
    assert result.returncode == 1
    assert "0.1.0" in result.stdout


def test_crlf_skill_with_matching_version_passes(tmp_path):
    write_release_tree(tmp_path)
    write(tmp_path, f"{SKILL_DIR}/SKILL.md", SKILL_MD.replace("\n", "\r\n"))
    assert run(tmp_path, "validate_versions.py").returncode == 0


def test_crlf_skill_with_wrong_version_fails(tmp_path):
    write_release_tree(tmp_path)
    text = SKILL_MD.replace('"0.1.1"', '"0.1.0"').replace("\n", "\r\n")
    write(tmp_path, f"{SKILL_DIR}/SKILL.md", text)
    result = run(tmp_path, "validate_versions.py")
    assert result.returncode == 1
    assert "0.1.0" in result.stdout


def test_corrupt_marketplace_fails(tmp_path):
    write_release_tree(tmp_path)
    write(tmp_path, ".claude-plugin/marketplace.json", '{"version": "0.1.1",')
    assert run(tmp_path, "validate_versions.py").returncode == 1


def test_missing_marketplace_fails(tmp_path):
    write_release_tree(tmp_path)
    (tmp_path / ".claude-plugin" / "marketplace.json").unlink()
    assert run(tmp_path, "validate_versions.py").returncode == 1


def test_corrupt_plugin_manifest_fails(tmp_path):
    write_release_tree(tmp_path)
    write(tmp_path, f"plugins/{PLUGIN}/.codex-plugin/plugin.json", '{"version": ')
    assert run(tmp_path, "validate_versions.py").returncode == 1


@pytest.mark.parametrize(
    "marketplace",
    [
        {"metadata": {"version": "0.1.1"}, "plugins": []},
        {"version": "0.1.1", "plugins": []},
    ],
    ids=["no-top-level-version", "no-metadata-version"],
)
def test_marketplace_missing_version_field_fails(tmp_path, marketplace):
    write_release_tree(tmp_path)
    write_json(tmp_path, ".claude-plugin/marketplace.json", marketplace)
    result = run(tmp_path, "validate_versions.py")
    assert result.returncode == 1
    assert "is required" in result.stdout


def test_extra_file_the_script_does_not_check_fails(tmp_path):
    write_release_tree(tmp_path)
    write(tmp_path, "docs/VERSION.md", "Version: `0.1.1`\n")
    write_config(tmp_path, RELEASE_FILES + ["docs/VERSION.md"])
    result = run(tmp_path, "validate_versions.py")
    assert result.returncode == 1
    assert "docs/VERSION.md" in result.stdout


def test_listed_extra_file_that_is_missing_fails(tmp_path):
    write_release_tree(tmp_path)
    write_config(tmp_path, RELEASE_FILES + ["docs/MISSING.md"])
    result = run(tmp_path, "validate_versions.py")
    assert result.returncode == 1
    assert "docs/MISSING.md" in result.stdout


# --- validate_skill_frontmatter.py ----------------------------------------


def write_skill(root: Path, text: str) -> None:
    write(root, f"{SKILL_DIR}/SKILL.md", text)


def test_frontmatter_base_skill_passes(tmp_path):
    write_skill(tmp_path, SKILL_MD)
    assert run(tmp_path, "validate_skill_frontmatter.py").returncode == 0


def test_yaml_block_scalar_description_passes(tmp_path):
    text = SKILL_MD.replace(
        "description: Use when testing the validators.\n",
        "description: >\n  Use when testing the validators.\n  Folded over two lines.\n",
    )
    write_skill(tmp_path, text)
    assert run(tmp_path, "validate_skill_frontmatter.py").returncode == 0


@pytest.mark.parametrize(
    ("token", "allowed"),
    [
        ("Bash(terraform plan -input=false -out=tfplan)", True),
        ("Bash(terraform fmt -check -recursive)", True),
        ("Bash(tofu state list)", True),
        ("WebFetch(domain:docs.oracle.com)", True),
        ("Bash(jq -r '.version' tfplan.json)", True),
        ("Bash(jq -r .version tfplan.json)", True),
        ("Bash(terraform apply:*)", False),
        ("Bash(terraform destroy)", False),
        ("Bash(terraform import:*)", False),
        ("Bash(terraform plan -auto-approve)", False),
        ("Bash(terraform state rm:*)", False),
        ("Bash(terraform fmt:*)", False),
        ("Bash(terraform fmt)", False),
        ("Bash(jq:*)", False),
        ("Bash(jq)", False),
        ("WebFetch", False),
        ("WebSearch", False),
    ],
)
def test_allowed_tools_policy(tmp_path, token, allowed):
    write_skill(tmp_path, SKILL_MD.replace("allowed-tools: Read Grep Glob", f"allowed-tools: Read {token}"))
    result = run(tmp_path, "validate_skill_frontmatter.py")
    assert (result.returncode == 0) is allowed, result.stdout
    if not allowed:
        assert token in result.stdout


def test_missing_body_path_fails(tmp_path):
    write_skill(tmp_path, SKILL_MD + "\nSee `references/missing.md` for details.\n")
    result = run(tmp_path, "validate_skill_frontmatter.py")
    assert result.returncode == 1
    assert "references/missing.md" in result.stdout


def test_placeholder_body_path_is_skipped(tmp_path):
    write_skill(tmp_path, SKILL_MD + "\nLoad `references/<cloud>.md` for the chosen cloud.\n")
    assert run(tmp_path, "validate_skill_frontmatter.py").returncode == 0


def test_name_not_matching_folder_fails(tmp_path):
    write(tmp_path, f"plugins/{PLUGIN}/skills/other-name/SKILL.md", SKILL_MD)
    result = run(tmp_path, "validate_skill_frontmatter.py")
    assert result.returncode == 1
    assert "other-name" in result.stdout


def test_name_longer_than_64_characters_fails(tmp_path):
    long_name = "a" * 65
    text = SKILL_MD.replace(f"name: {PLUGIN}", f"name: {long_name}")
    write(tmp_path, f"plugins/{PLUGIN}/skills/{long_name}/SKILL.md", text)
    result = run(tmp_path, "validate_skill_frontmatter.py")
    assert result.returncode == 1
    assert "64" in result.stdout


# Runs the validator with `import yaml` forced to fail.
NO_YAML_SHIM = (
    "import runpy, sys\n"
    "sys.modules['yaml'] = None  # makes `import yaml` raise ImportError\n"
    "sys.argv = sys.argv[1:]\n"
    "runpy.run_path(sys.argv[0], run_name='__main__')\n"
)


def test_missing_pyyaml_fails_with_install_hint(tmp_path):
    write_skill(tmp_path, SKILL_MD)
    result = subprocess.run(
        [sys.executable, "-c", NO_YAML_SHIM, str(SCRIPTS_DIR / "validate_skill_frontmatter.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "install pyyaml" in (result.stdout + result.stderr).lower()


# --- validate_codex_plugin.py ---------------------------------------------


def write_codex_tree(root: Path, claude_name: str = PLUGIN, claude_version: str = "0.1.1") -> None:
    # The Claude manifest deliberately has a different description from the Codex one.
    write_json(
        root,
        f"plugins/{PLUGIN}/.claude-plugin/plugin.json",
        {"name": claude_name, "version": claude_version, "description": "Claude copy."},
    )
    write_json(root, f"plugins/{PLUGIN}/.codex-plugin/plugin.json", CODEX_MANIFEST)
    write_json(
        root,
        ".agents/plugins/marketplace.json",
        {
            "name": "zimcanit-marketplace",
            "plugins": [{"name": PLUGIN, "source": {"source": "local", "path": f"./plugins/{PLUGIN}"}}],
        },
    )


def test_codex_tree_passes_with_different_descriptions(tmp_path):
    write_codex_tree(tmp_path)
    assert run(tmp_path, "validate_codex_plugin.py").returncode == 0


def test_codex_corrupt_marketplace_fails(tmp_path):
    write_codex_tree(tmp_path)
    write(tmp_path, ".agents/plugins/marketplace.json", '{"plugins": [')
    assert run(tmp_path, "validate_codex_plugin.py").returncode == 1


def test_codex_missing_marketplace_fails(tmp_path):
    write_codex_tree(tmp_path)
    (tmp_path / ".agents" / "plugins" / "marketplace.json").unlink()
    result = run(tmp_path, "validate_codex_plugin.py")
    assert result.returncode == 1
    assert "marketplace" in result.stdout


def test_codex_marketplace_without_plugin_entry_fails(tmp_path):
    write_codex_tree(tmp_path)
    write_json(tmp_path, ".agents/plugins/marketplace.json", {"name": "zimcanit-marketplace", "plugins": []})
    result = run(tmp_path, "validate_codex_plugin.py")
    assert result.returncode == 1
    assert PLUGIN in result.stdout


def test_codex_name_mismatch_with_claude_fails(tmp_path):
    write_codex_tree(tmp_path, claude_name="other-plugin")
    result = run(tmp_path, "validate_codex_plugin.py")
    assert result.returncode == 1
    assert "other-plugin" in result.stdout


def test_codex_version_mismatch_with_claude_fails(tmp_path):
    write_codex_tree(tmp_path, claude_version="0.1.0")
    assert run(tmp_path, "validate_codex_plugin.py").returncode == 1


def test_codex_plugin_without_claude_manifest_fails(tmp_path):
    write_codex_tree(tmp_path)
    (tmp_path / f"plugins/{PLUGIN}/.claude-plugin/plugin.json").unlink()
    assert run(tmp_path, "validate_codex_plugin.py").returncode == 1
