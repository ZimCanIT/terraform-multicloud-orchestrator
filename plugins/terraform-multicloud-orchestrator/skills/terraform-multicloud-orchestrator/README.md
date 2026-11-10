# Terraform Authoring Companion for Azure (Agent Skill)

Plan-only skill that writes, reviews and refactors Terraform for **Azure** (`azurerm` and `azapi`) to a stated standard: module and state boundaries, typed interfaces, Azure naming and tagging, managed identities, private networking and secure defaults. It checks arguments against the provider version the repository pins.

**Strictly plan-only: it never runs `apply` or `destroy`.**

- Version: `0.1.1` <!-- x-release-please-version --> · License: MIT
- Authoritative spec: [`SKILL.md`](./SKILL.md)

The skill keeps the name `terraform-multicloud-orchestrator` so that existing installs keep working. It covers Azure only.

## When it activates

Whenever Terraform or OpenTofu for Azure comes up: writing, reviewing, refactoring or importing `.tf` code that uses `azurerm` or `azapi`, Azure Verified Modules, the `azurerm` backend, or a provider upgrade. See the `description` in the [`SKILL.md`](./SKILL.md) frontmatter.

## Safety (plan-only)

- **Permitted (exact forms, terraform and tofu):** `init -backend=false -input=false`, `init -input=false`, `validate`, `fmt -check -recursive`, `plan -input=false -out=tfplan`, `show -json tfplan`, `providers`, `providers schema -json`, `state list`. Reading plan JSON with `jq` needs your approval.
- **Forbidden:** any other `terraform` or `tofu` subcommand, including `apply`, `destroy`, any auto-approve flag, `test`, `taint`, `refresh`, and state-mutating operations (`import`, `state mv`/`rm`/`push`, `force-unlock`). The skill *proposes* these; you run them manually.
- In Claude Code the `allowed-tools` frontmatter is scoped to the permitted commands. `allowed-tools` grants, it does not block. `deny` rules in your settings are a guard rail that matches only the command text; for a stop that holds, use credentials that cannot write, a hook or a sandbox (see the repository README).

## Layout

```
SKILL.md                     # workflow, guardrails and the authoring standard (authoritative)
references/
  hcl-standards.md  module-design.md  naming-and-tagging.md        # how the code is written
  secure-baseline.md  networking.md  identity-and-secrets.md       # Azure platform
  state-and-environments.md  azurerm-provider.md                   # state and providers
  adopt-and-refactor.md  testing-and-delivery.md                   # change and delivery
assets/
  review-checklist.md  handoff-template.md
  reference-stack/           # a root and a module written to the standard, validated in CI
scripts/validate.sh          # the plan-only validation chain for humans and CI
```

## Usage

Install the parent plugin (Claude Code or Codex marketplace) per the repository README, then prompt with any Terraform task for Azure. The skill reads the repository, writes or reviews code against the standard in `SKILL.md` §3, and validates with two plan-only steps. The static checks need no state or credentials:

```bash
terraform init -backend=false -input=false
terraform validate
terraform fmt -check -recursive
```

The state-backed plan reads real state, so it is the only step that can see a replacement. It lists every resource the plan deletes or replaces. The `jq` step is not pre-approved, so approve it once:

```bash
terraform init -input=false
terraform plan -input=false -out=tfplan
terraform show -json tfplan | jq -r '.resource_changes[]? | select(.change.actions | index("delete")) | "\(.address)\t\(.change.actions | join("+"))"'
```

`scripts/validate.sh` runs the same two steps for humans and CI. Pass `--static` or `--plan` to run just one, `--fail-on-delete` to exit with status 3 when anything is deleted or replaced, and `--keep-json` to keep `plan_output.json` (it is otherwise removed on exit). `tfplan` holds plan values in cleartext, so keep it out of version control.

## Compatibility

Designed for Claude Code, Codex, and Agent Skills-compatible coding agents. Requires the Terraform or OpenTofu CLI and jq for validation, internet access for provider/module downloads, and Azure credentials only when plan commands need them.

## Validating this skill

```bash
python -m pip install skills-ref==0.1.1   # provides the `agentskills` CLI
agentskills validate .
```

See the repository [`CONTRIBUTING.md`](../../../../CONTRIBUTING.md) for the full publish gate.
