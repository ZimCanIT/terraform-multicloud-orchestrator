# Contributing

Run these checks before publishing a skill or plugin change.

## Local pre-commit

Install and run the full hook suite before opening a PR:

```bash
python -m pip install pre-commit
pre-commit install
pre-commit run --all-files
```

The hook suite covers whitespace, EOF, JSON/YAML syntax, large files, private keys, secret detection, Markdown linting, shell linting/formatting, Codex plugin manifest validation, Agent Skill frontmatter validation, skill eval case validation, and release version consistency.

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

## Skill evals

`plugins/terraform-multicloud-orchestrator/evals/` holds the cases that `claude plugin eval` runs against the skill: a `gate` suite of 12 cases (trigger probes and plan-only guardrails) and an `authoring` suite of 4 cases (AWS, Azure, GCP and OCI) whose output also gets `terraform validate`. The [evals README](plugins/terraform-multicloud-orchestrator/evals/README.md) has the rules for a case and every classification and reason code.

`.github/workflows/skill-evals.yml` runs them in two tiers. Each job ends with one classification (`PASS`, `FAIL`, `ERROR`, `INCONCLUSIVE` or `SKIPPED`) in its job summary and in a `classification.json` artifact, and every live record also classifies each case and each attempt.

- `skill-evals-offline` needs no secret and runs on every pull request, every push to `main` and the weekly schedule. It installs the Claude Code release that the npm `stable` dist-tag names and asserts that this is the version installed. It then validates the cases, tests the eval tooling, lints the workflow with actionlint and zizmor, runs `claude plugin validate`, and confirms that both suites load.
- `skill-evals-live-<suite>-<channel>` calls the model. A same-repository pull request that touches the plugin or the eval tooling runs the gate suite on `stable`. The weekly schedule runs both suites on `stable`, plus the gate suite on `latest` as a canary that reports drift and never fails the run. A manual dispatch picks the suite, the channel and, optionally, a full model ID.

Run the checks that need no API key before you push. The `validate-evals` pre-commit hook runs the first command:

```bash
python scripts/validate_evals.py
python -m pytest tests/test_validate_evals.py tests/test_classify_eval_run.py tests/test_grade_eval_workspaces.py tests/test_eval_graders.py tests/test_skill_evals_workflow.py -q
```

The evals README shows how to run a suite and classify it locally. A paid run uses your own Claude Code login and cost about $2.10 for the gate suite and $2.20 for the authoring suite when measured. Terraform must be installed for the five tests that run the real binary, and Node.js for the grader-pattern tests; without them those tests are skipped, and CI runs them. `scripts/grade_eval_workspaces.py` runs `terraform validate` on model-written code, so it refuses to start while `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` is set. Unset them for that command.

What the evals do not show:

- They sample the skill's behaviour. A passing run bounds how often a guardrail is violated; it does not rule violations out, and preventing `apply` and `destroy` rests on the tool grants, not on these results.
- They check that provider pins have the right shape and that `terraform validate` accepts the code. They do not check that a pinned version is the newest one, or that a plan would succeed against a real account.
- A judged grader is one model voting three times. Read the reply before trusting a single judged failure.
- One run covers one Claude Code release, the one the `stable` dist-tag named that day.

Setup for the repository owner, not applied by this repository:

- Add a dedicated `ANTHROPIC_API_KEY` repository secret with a spend limit. Without it the live tier is skipped on pull requests, and a scheduled or manual run ends `ERROR` with `no_credential`.
- To require a human approval before each paid run, put the secret in a GitHub environment with required reviewers and name that environment in the `live` job.
- The classification tags (`EVAL_DATA_CLASSIFICATION`, `EVAL_CRITICALITY`, `EVAL_SERVICE_LEVEL`) are set in the workflow's top-level `env`. Foundry fixes the `DataClassification` values; the `Criticality` and `ServiceLevel` values are a proposal for you to change.

## Conventional Commits

Commit and PR titles use a type: feat, fix, docs, ci, chore, test or refactor. release-please reads them to choose the next version. While the version is below 1.0:

- feat and fix bump the patch version.
- A `!` after the type (for example `feat!:`) marks a breaking change and bumps the minor version.
- docs, ci, chore and test do not bump the version.

## Branch protection (recommended, not applied by this repository)

Protect `main` with these settings. The repository owner applies them in the GitHub settings; this repository does not change them.

- Require the `pre-commit`, `agentskills-validate` and `skill-evals-offline` status checks. Do not require the `skill-evals-live-*` checks: they need a secret, cost money and are skipped for fork and bot pull requests.
- Require pull requests before merging.
- Allow squash merges only.
