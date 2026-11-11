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

The shell hooks run `shellcheck` and `shfmt` from pinned pre-commit repositories, so developers need no separate install. `gitleaks` scans staged changes locally; CI scans the whole tree with `detect-secrets`.

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

## Reference stack

`plugins/terraform-multicloud-orchestrator/skills/terraform-multicloud-orchestrator/assets/reference-stack/` is real Terraform that the skill points to as its worked example. The `reference-stack` job in `.github/workflows/terraform-fixture.yml` copies it to a scratch directory and runs `terraform init -backend=false`, `terraform validate` and `terraform fmt -check -recursive` against the provider version it pins. It then validates each module on its own and runs its tests with `terraform test`; they use plan mode and a mocked provider, so they need no credentials and create nothing. The stack is never planned against Azure or applied. When you change an argument in a reference file, make the same change in the stack so that CI checks it.

To run the same checks locally, from a copy of that directory:

```bash
bash /path/to/plugins/terraform-multicloud-orchestrator/skills/terraform-multicloud-orchestrator/scripts/validate.sh --static
```

## Audit script and upgrade data

`plugins/terraform-multicloud-orchestrator/skills/terraform-multicloud-orchestrator/scripts/tf_audit.py` is a read-only audit of `.tf` files against the rules in `SKILL.md` section 3. It uses only the Python standard library. `tests/test_tf_audit.py` covers it:

```bash
python -m pytest tests/test_tf_audit.py -q
```

- The reference stack must pass the audit with no findings. A test fails if it does not, so a new rule that the stack breaks means the rule or the stack is wrong.
- When you add a check, add the code that breaks it to the bad configuration in the test file and the finding to `EXPECTED`.
- The script judges literal values only. Do not make it guess at expressions: a wrong finding costs more trust than a missed one.
- `plugins/terraform-multicloud-orchestrator/skills/terraform-multicloud-orchestrator/scripts/plan_review.py` reads plan JSON and must never print an attribute value. `tests/test_plan_review.py` checks that, and that its stop list matches the one in `references/azurerm-provider.md`.

`plugins/terraform-multicloud-orchestrator/skills/terraform-multicloud-orchestrator/assets/azurerm-5-changes.json` lists the resource types and arguments that the `azurerm` 5.0 upgrade guide removes or renames. It holds names only. To rebuild it for a later release, download the guide at the release tag and run the extractor:

```bash
curl -sSLo guide.md https://raw.githubusercontent.com/hashicorp/terraform-provider-azurerm/v5.13.0/website/docs/guides/5.0-upgrade-guide.html.markdown
python scripts/extract_azurerm_changes.py guide.md plugins/terraform-multicloud-orchestrator/skills/terraform-multicloud-orchestrator/assets/azurerm-5-changes.json v5.13.0
```

The extractor prints how many bullets it could not classify. Read those in the guide: they are behaviour changes that a name check cannot find.

## Conventional Commits

Commit and PR titles use a type: feat, fix, docs, ci, chore, test or refactor. release-please reads them to choose the next version. While the version is below 1.0:

- feat and fix bump the patch version.
- A `!` after the type (for example `feat!:`) marks a breaking change and bumps the minor version.
- docs, ci, chore and test do not bump the version.

## Branch protection (recommended, not applied by this repository)

Protect `main` with these settings. The repository owner applies them in the GitHub settings; this repository does not change them.

- Require the `pre-commit`, `agentskills-validate`, `terraform-fixture` and `reference-stack` status checks.
- Require pull requests before merging.
- Allow squash merges only.
