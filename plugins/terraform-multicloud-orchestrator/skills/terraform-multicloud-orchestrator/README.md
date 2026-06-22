# Terraform Multi-Cloud Orchestrator (Agent Skill)

Plan-only, failure-mode-first Terraform orchestrator for **AWS, Azure, GCP and OCI**. It diagnoses the failure modes most likely to bite — identity churn, blast radius, state migration, compliance gates — *before* writing HCL, asks once for the target cloud(s) and provider-pinning strategy, then loads only the relevant per-cloud reference.

**Strictly plan-only: it never runs `apply` or `destroy`.**

- Version: `0.0.1` · License: MIT
- Authoritative spec: [`SKILL.md`](./SKILL.md)

## When it activates

Whenever Terraform, HCL, `.tf` files, IaC modules, provider upgrades, or state migration/refactors come up — generating, reviewing, validating or refactoring infrastructure code across AWS, Azure, GCP or OCI — even if the skill is not named. See the `description` in [`SKILL.md`](./SKILL.md) frontmatter.

## Safety (plan-only)

- **Permitted:** `init`, `validate`, `plan`, `show`, `state list`, `fmt`, `get`, `providers` (terraform and tofu).
- **Forbidden:** `apply`, `destroy`, any auto-approve flag, and state-mutating CLI operations (`import`, `state mv`/`rm`/`push`, `force-unlock`) — the skill *proposes* these; you run them manually.
- In Claude Code the `allowed-tools` frontmatter is scoped to the permitted commands. `allowed-tools` grants, it does not block — add `deny` rules in your settings for hard enforcement (see the repository README).

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

Install the parent plugin (Claude Code or Codex marketplace) per the repository README, then prompt with any Terraform task. The skill establishes the session config once, loads only the in-scope per-cloud reference, generates modular HCL, runs a security pass, and validates with the plan-only chain:

```bash
terraform init -backend=false -input=false
terraform validate
terraform fmt -check
terraform plan -input=false -out=tfplan
terraform show -json tfplan > plan_output.json
```

`scripts/validate.sh` runs the same chain for humans and CI.

## Compatibility

Designed for Claude Code, Codex, and Agent Skills-compatible coding agents. Requires the Terraform or OpenTofu CLI for validation, internet access for provider/module downloads, and cloud credentials only when plan commands need them.

## Validating this skill

```bash
python -m pip install skills-ref==0.1.1   # provides the `agentskills` CLI
agentskills validate .
```

See the repository [`CONTRIBUTING.md`](../../../../CONTRIBUTING.md) for the full publish gate.
