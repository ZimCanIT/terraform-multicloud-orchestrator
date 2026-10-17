# Terraform Multi-Cloud Orchestrator (Agent Skill)

Plan-only, failure-mode-first Terraform orchestrator for **AWS, Azure, GCP and OCI**. It diagnoses the failure modes most likely to bite — identity churn, blast radius, state migration, compliance gates — *before* writing HCL, asks once for the target cloud(s) and provider-pinning strategy, then loads only the relevant per-cloud reference.

**Strictly plan-only: it never runs `apply` or `destroy`.**

- Version: `0.1.0` <!-- x-release-please-version --> · License: MIT
- Authoritative spec: [`SKILL.md`](./SKILL.md)

## When it activates

Whenever Terraform, HCL, `.tf` files, IaC modules, provider upgrades, or state migration/refactors come up — generating, reviewing, validating or refactoring infrastructure code across AWS, Azure, GCP or OCI — even if the skill is not named. See the `description` in [`SKILL.md`](./SKILL.md) frontmatter.

## Safety (plan-only)

- **Permitted:** `init`, `validate`, `plan`, `show`, `state list`, `fmt`, `get`, `providers` (terraform and tofu), plus `jq` to read plan JSON.
- **Forbidden:** `apply`, `destroy`, any auto-approve flag, and state-mutating CLI operations (`import`, `state mv`/`rm`/`push`, `force-unlock`) — the skill *proposes* these; you run them manually.
- In Claude Code the `allowed-tools` frontmatter is scoped to the permitted commands. `allowed-tools` grants, it does not block. `deny` rules in your settings are a guard rail that matches only the command text; for a stop that holds, use credentials that cannot write, a hook or a sandbox (see the repository README).

## Layout

```
SKILL.md                     # cloud-agnostic spine (authoritative)
eval_queries.json            # trigger regression set
assets/                      # session-config + final-report templates
scripts/validate.sh          # the plan-only validation chain for humans/CI
references/
  identity-churn.md  blast-radius.md  migration-playbooks.md  compliance-gates.md   # mechanisms
  aws.md  azure.md  gcp.md  oci.md                                                   # per-cloud (load on demand)
```

## Usage

Install the parent plugin (Claude Code or Codex marketplace) per the repository README, then prompt with any Terraform task. The skill establishes the session config once, loads only the in-scope per-cloud reference, generates modular HCL, and validates with two plan-only steps. The static checks need no state or credentials:

```bash
terraform init -backend=false -input=false
terraform validate
terraform fmt -check -recursive
```

The state-backed plan reads real state, so it is the only step that can see a replacement. It lists every resource the plan deletes or replaces:

```bash
terraform init -input=false
terraform plan -input=false -out=tfplan
terraform show -json tfplan | jq -r '.resource_changes[]? | select(.change.actions | index("delete")) | "\(.address)\t\(.change.actions | join("+"))"'
```

`scripts/validate.sh` runs the same two steps for humans and CI. Pass `--static` or `--plan` to run just one. The plan step also writes `plan_output.json`; like `tfplan`, it holds plan values in cleartext, so keep both out of version control.

## Compatibility

Designed for Claude Code, Codex, and Agent Skills-compatible coding agents. Requires the Terraform or OpenTofu CLI and jq for validation, internet access for provider/module downloads, and cloud credentials only when plan commands need them.

## Validating this skill

```bash
python -m pip install skills-ref==0.1.1   # provides the `agentskills` CLI
agentskills validate .
```

See the repository [`CONTRIBUTING.md`](../../../../CONTRIBUTING.md) for the full publish gate.
