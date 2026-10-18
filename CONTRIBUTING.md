# Contributing

Run these checks before publishing a skill or plugin change.

## Local pre-commit

Install and run the full hook suite before opening a PR:

```bash
python -m pip install pre-commit
pre-commit install
pre-commit run --all-files
```

The hook suite covers whitespace, EOF, JSON/YAML syntax, large files, private keys, secret detection, Markdown linting, shell linting/formatting, Codex plugin manifest validation, Agent Skill frontmatter validation, and release version consistency.

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

This validates Agent Skills frontmatter, naming, and portable package structure. CI runs the same pinned check on pull requests and on pushes to main (`.github/workflows/skill-validation.yml`), so the gate is enforced, not just documented.

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

## Release version fields

Versions are owned by release-please, and the manifest (`.release-please-manifest.json`) is the source of truth. On each release it rewrites both `plugin.json` files, `.claude-plugin/marketplace.json` (`version` and `metadata.version`), and the version lines in the skill's `SKILL.md` (`metadata.version`) and `README.md`, using the `extra-files` in `release-please-config.json` and the `x-release-please-version` markers. Do not edit those fields by hand, and do not set a `version` on the marketplace plugin entry: Claude Code reads the plugin version from `plugin.json` and ignores the entry value.

```bash
python scripts/validate_versions.py
```

This checks that every version field matches the manifest, so a field that release-please does not rewrite fails the pre-commit hook and CI instead of drifting silently.

## Terraform validation script smoke test

Run from a Terraform root directory. `--static` runs the checks that need no state or credentials, `--plan` runs the state-backed plan and lists anything it deletes or replaces, and no flag runs both:

```bash
bash /path/to/plugins/terraform-multicloud-orchestrator/skills/terraform-multicloud-orchestrator/scripts/validate.sh --static
```

## Conventional Commits

Commit and PR titles use a type: feat, fix, docs, ci, chore, test or refactor. release-please reads them to choose the next version. While the version is below 1.0:

- feat and fix bump the patch version.
- A `!` after the type (for example `feat!:`) marks a breaking change and bumps the minor version.
- docs, ci, chore and test do not bump the version.

## Branch protection (recommended, not applied by this repository)

Protect `main` with these settings. The repository owner applies them in the GitHub settings; this repository does not change them.

- Require the `pre-commit` and `agentskills-validate` status checks.
- Require pull requests before merging.
- Allow squash merges only.
