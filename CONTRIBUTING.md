# Contributing

Run these checks before publishing a skill or plugin change.

## Local pre-commit

Install and run the full hook suite before opening a PR:

```bash
python -m pip install pre-commit
pre-commit install
pre-commit run --all-files
```

The hook suite covers whitespace, EOF, JSON/YAML syntax, large files, private keys, secret detection, Markdown linting, shell linting/formatting, Codex plugin manifest validation, and Agent Skill frontmatter validation.

`shellcheck` and `shfmt` must be installed on developer machines for the shell hooks. CI installs them automatically.

If `pre-commit` cannot write to your default user cache, use a repo-local cache:

```bash
PRE_COMMIT_HOME=.pre-commit-cache pre-commit run --all-files
```

On PowerShell:

```powershell
$env:PRE_COMMIT_HOME=".pre-commit-cache"; pre-commit run --all-files
```

## Agent Skill validation

Install the official Agent Skills reference validator. It is published to PyPI as the [`skills-ref`](https://pypi.org/project/skills-ref/) package (source: [`agentskills/agentskills`](https://github.com/agentskills/agentskills)); note that release `0.1.1` installs a CLI named `agentskills`, not `skills-ref`:

```bash
python -m pip install skills-ref==0.1.1
```

Then validate the skill:

```bash
agentskills validate plugins/terraform-multicloud-orchestrator/skills/terraform-multicloud-orchestrator
```

This validates Agent Skills frontmatter, naming, and portable package structure. CI runs the same pinned check on every push and pull request (`.github/workflows/skill-validation.yml`), so the gate is enforced, not just documented.

The package name (`skills-ref`) and the installed CLI name (`agentskills`) differ, and the upstream `main` branch renames the CLI back to `skills-ref`. Re-check the command name whenever you bump the pinned version.

Do not use Codex's minimal `skill-creator/scripts/quick_validate.py` as the only gate for this project. The current bundled validator does not yet accept the Agent Skills `compatibility` field, which this skill intentionally uses.

## Codex plugin validation

```bash
python scripts/validate_codex_plugin.py
```

This validates the Codex plugin manifest and bundled skill shape.

## Agent Skill frontmatter validation

```bash
python scripts/validate_skill_frontmatter.py
```

This validates frontmatter fields, skill naming, `compatibility`, metadata shape, and space-separated `allowed-tools`.

## Terraform validation script smoke test

Run from a Terraform root directory:

```bash
bash /path/to/plugins/terraform-multicloud-orchestrator/skills/terraform-multicloud-orchestrator/scripts/validate.sh
```
