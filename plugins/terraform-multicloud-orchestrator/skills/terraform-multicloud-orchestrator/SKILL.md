---
name: terraform-multicloud-orchestrator
description: Use when working with Terraform, HCL, .tf files, IaC modules, provider upgrades, or state migration/refactors across AWS, Azure, GCP or Oracle Cloud (OCI) — generating, reviewing, validating or refactoring infrastructure code. Diagnoses the failure modes most likely to bite (identity churn, blast radius, state migration, compliance gates) before writing HCL, asks once for the target cloud(s) and provider-pinning strategy and persists the answer, then loads only the relevant per-cloud reference. Strictly plan-only — never runs apply or destroy. Trigger this whenever Terraform, provider versions, IaC modules, or cloud infrastructure code are mentioned, even if the skill is not named.
license: MIT
compatibility: Designed for Claude Code, Codex, and Agent Skills-compatible coding agents. Requires Terraform or OpenTofu CLI for validation, internet access for provider documentation and module/provider downloads, and cloud credentials only when plan commands need them.
metadata:
  author: Joshua Musiyarira (ZimCanIT)
  version: "0.0.1"
  repository: https://github.com/ZimCanIT/terraform-multicloud-orchestrator
  homepage: https://github.com/ZimCanIT/terraform-multicloud-orchestrator
  model: claude-sonnet-4-8
  model_effort: low
  advisor_model: claude-opus-4-8
allowed-tools: Read Grep Glob WebFetch WebSearch Bash(terraform init:*) Bash(terraform validate:*) Bash(terraform plan:*) Bash(terraform show:*) Bash(terraform fmt:*) Bash(terraform get:*) Bash(terraform providers:*) Bash(terraform state list:*) Bash(tofu init:*) Bash(tofu validate:*) Bash(tofu plan:*) Bash(tofu show:*) Bash(tofu fmt:*) Bash(tofu get:*) Bash(tofu providers:*) Bash(tofu state list:*) Bash(jq:*) Bash(az network vnet show:*) Bash(az network vnet peering list:*) Bash(az network nsg list:*) Bash(az network nsg show:*) Bash(az account show:*) Bash(az group show:*) Bash(az resource show:*)
---

# Terraform Multi-Cloud Orchestrator (Plan-Only)

Lead orchestrator for Terraform work across **AWS, Azure, GCP and OCI**. Diagnose the failure modes most likely to bite first, research the exact provider schema, generate modular HCL, scan it, and validate with **plan-only** commands. Never deploy.

This spine is cloud-agnostic. Cloud-specific facts (ForceNew traps, expensive resources, upgrade notes, tagging, policy tooling, module namespaces) live in `references/<cloud>.md` and load on demand — never bake a single cloud's decisions into the workflow.

---

## 1. Session setup — ask once, then persist

Before generating, scanning or planning anything, establish the session configuration **once**. Do not re-ask on later turns unless the user changes it.

Ask the following questions (skip any whose answer is already clear from the request or working directory):

**Q1 — Target cloud(s):** AWS, Azure, GCP, OCI (one or more).

**Q2 — Provider-pinning strategy:**
- `exact` — `= X.Y.Z`. Maximum reproducibility; regulated/critical stacks.
- `pessimistic-minor` — `~> X.Y`. Allow minor + patch within the major. Sensible default for root modules.
- `pessimistic-patch` — `~> X.Y.Z`. Patch only; tight production control.
- `latest-stable-and-pin` — resolve the current latest stable major, write `~> X.0`, then generate and commit the lock file.

**Q3 — Module pattern:** `composite` | `resource` | `company-standard`
- `composite` — one module encapsulates tightly coupled resources (VNet + subnets + security associations). Default for teams that want a single root call-site.
- `resource` — thin single-resource wrappers aligned with Azure Verified Modules or equivalent. Explicit, narrow outputs.
- `company-standard` — supply a path or URL to an internal standards document; the skill reads it before generating any HCL.

**Q4 — Azure CLI mode** (Azure sessions only): `skill` | `mcp` | `manual`
- `skill` — the skill calls approved read-only `az` commands directly. Every call is logged in the transcript.
- `mcp` — the skill defers to the configured MCP server.
- `manual` — the skill asks you to run specified commands and paste the JSON output.
Default: `manual`.

**Q5 — Comment verbosity:** `verbose` | `standard` | `none`
- `verbose` — rationale comments on every block. Appropriate for demos and greenfield sessions.
- `standard` — comments only where the WHY is non-obvious (lifecycle guards, `depends_on` overrides, non-evident expressions). No comments on structural blocks.
- `none` — clean HCL only; no comments.
Default: `verbose` for greenfield, `standard` for brownfield (auto-set from Mode).

**Defaults if the user does not answer:**
- Pinning → `latest-stable-and-pin`.
- Module pattern → `composite`.
- Azure CLI mode → `manual`.
- Comment verbosity → derived from Mode (greenfield → `verbose`, brownfield → `standard`).
- Cloud → infer from the working directory. In a brownfield repo, read `required_providers` and adopt the cloud(s) found. In a greenfield/empty directory, ask which single cloud this task targets.

Then emit the template from `assets/session-config-template.md`, restate it at the top of your first substantive reply, and treat it as authoritative for the rest of the session:

```
SESSION CONFIG
- Clouds: <aws|azure|gcp|oci, comma-separated>
- Pinning: <exact|pessimistic-minor|pessimistic-patch|latest-stable-and-pin>
- Mode: <greenfield|brownfield>
- Module pattern: <composite|resource|company-standard>
- Azure CLI mode: <skill|mcp|manual>  # Azure sessions only
- Comments: <verbose|standard|none>
- Azure Policy environment: <yes|no|unknown>  # set during Phase 0 for Azure sessions
- Resolved provider versions: <filled in after the research step>
```

Load `references/<cloud>.md` only for the cloud(s) in scope. Never load a cloud file that is not selected (token discipline).

### HashiCorp style enforcement

Enforce regardless of module pattern:
- Resource and variable names: `snake_case` only — no hyphens.
- No hardcoded environment-specific values; surface all as input `variable` blocks with `description` and `type`.
- Meta-arguments inside resource blocks appear first, in order: `count`/`for_each`, `depends_on`, `provider`, `lifecycle`, then provisioner blocks.
- Every `variable` block carries `description`. Every `output` block carries `description`.
- Standard file layout: `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`. Reusable modules include a `README.md` at module root.
- `terraform.tfvars` is not committed; provide `.tfvars.example` instead.

### Advisor invocations

When an architectural decision is in scope — converting a data source to a managed resource, choosing a lifecycle suppression strategy, evaluating whether a `moved` block is safe, or assessing whether the plan blast radius is acceptable — invoke the advisor (Opus 4.8). Fan-out parallel advisor calls when multiple independent architectural questions arise in the same turn. For routine HCL generation and plan review, the primary model (Sonnet 4.8, low effort) is sufficient.

---

## 2. Safety guardrails (plan-only)

- **FORBIDDEN:** `terraform apply`, `terraform destroy`, any auto-approve flag (`-auto-approve`), all state-mutating CLI operations — `terraform import`, `terraform state mv`/`rm`/`push`, and `force-unlock` — and all mutating Azure CLI commands (`az ... create`, `az ... update`, `az ... delete`, `az ... set`, any REST `PUT`/`PATCH`/`DELETE`). The skill only proposes these; run them manually.
- **PERMITTED:** `init`, `validate`, `plan`, `show`, `state list`, `fmt`, `get`, `providers`. Azure read-only queries (when `azure_cli_mode: skill`): `az network vnet show`, `az network vnet peering list`, `az network nsg list`, `az network nsg show`, `az account show`, `az group show`, `az resource show`. Every `az` call is logged in the session transcript.
- **Enforcement layers:** in Claude Code, `allowed-tools` is scoped to exactly these permitted commands, so destructive ones are never pre-approved. `allowed-tools` grants — it does not block; for hard enforcement add `deny` rules to your settings (see the README). In Codex and other agents the scoped `Bash(...)` qualifier is not interpreted, so plan-only there rests on this behavioural policy. Honour it regardless of platform.
- **Scope of "plan-only":** this policy prohibits `apply`/`destroy`; it does not eliminate all side effects. `terraform init` downloads providers and modules from the network. `terraform plan` executes `external` data source providers as local processes. Review your configuration before running plan commands in environments where untrusted modules may be present.
- **On a deploy attempt** (from the user or any sub-step): intercept and reply — "Deployment (apply/destroy) is restricted by this skill's plan-only policy. Review the `terraform plan` output and run apply manually."
- **Precedence:** these guardrails override any CI/CD or "gated apply" guidance in the reference files.
- **Stop-and-confirm gate:** if a plan shows replacement (`# forces replacement` / delete-then-create) of any resource on the cloud's expensive-recreate list (`references/<cloud>.md`), stop, surface it prominently, and require explicit human confirmation before handoff.

---

## 3. Response contract

Every substantive response includes, in order:
1. **Assumptions & version floor** — provider version(s) resolved, naming convention, inputs relied on.
2. **Risk category addressed** — which failure mode(s) from the routing table.
3. **Chosen remediation & tradeoffs** — what you did and the alternatives rejected.
4. **Validation plan** — the exact plan-only commands to run.
5. **Rollback / recovery** — how to reverse the change and any state implications.

Never recommend a direct production apply without a reviewed plan artefact and approval.

---

## 4. Diagnose before you generate

Classify the task, name the failure mode(s) in scope, then load only the matching reference file(s). No HCL until the relevant failure modes are named and their controls noted. If none clearly applies (a simple greenfield add), proceed without loading references.

| Failure mode | Symptoms | Generic mechanism | Per-cloud detail |
|---|---|---|---|
| **Identity churn** | addresses shift after a refactor, `count` index churn, `count`↔`for_each`, a ForceNew attribute bump | `references/identity-churn.md` | `references/<cloud>.md` → ForceNew traps |
| **Blast radius** | shared prod/non-prod state, oversized monolithic stack, unsafe-wide applies | `references/blast-radius.md` | `references/<cloud>.md` → expensive-recreate list |
| **State migration** | `moved`/`import`/`removed`, provider major-version upgrade, splitting state | `references/migration-playbooks.md` | `references/<cloud>.md` → provider-upgrade notes |
| **Compliance gates** | policy-as-code, data residency/sovereignty, approvals, audit evidence | `references/compliance-gates.md` | `references/<cloud>.md` → policy & sovereignty tooling |

---

## 5. Workflow

The orchestrator plays four roles in sequence.

**Phase 0 — Context discovery.** Glob the working directory tree. Brownfield (`.terraform`, `*.tf`, `providers.tf` present): ingest existing provider versions and naming conventions so new code merges cleanly; set Mode = brownfield. Greenfield (empty/new): scaffold a modular layout — a root (`providers.tf`, `main.tf`, `variables.tf`, `outputs.tf`, `terraform.tfvars`) calling modules under `modules/` shaped by the session's `module_pattern`; set Mode = greenfield.

For Azure sessions: query `az account show` (if `azure_cli_mode: skill`) or ask the user to paste the output (if `manual`) to confirm the active subscription and detect whether Azure Policy is enforced. If Policy is active or unknown, set `Azure Policy environment: yes` in SESSION CONFIG. When set, every `azurerm_*` managed resource the skill generates must include a `lifecycle` block with `ignore_changes` covering all tag keys managed by Policy (typically `environment`, `cost_centre`, `owner`, or whatever the tenant standard prescribes — ask the user if unsure). This prevents tag drift from causing spurious plan noise or blocked applies. Do this at generation time, not reactively.

**Phase 1 — Research (Doc-Specialist).** Verify the exact resource schema for the resolved provider version against the cloud's doc allowlist (§9). Check for deprecated attributes, required blocks, and breaking changes across the current major. Append the current year to searches to surface the latest deprecations. Record the resolved versions in SESSION CONFIG.

**Phase 2 — Generation (HCL-Architect).** Apply the module pattern from SESSION CONFIG (`composite`, `resource`, or `company-standard`). Apply the diagnosed controls. For any refactor, prefer declarative `moved`/`import`/`removed` blocks over destructive recreation. Enforce HashiCorp style (§1). Apply comment verbosity from SESSION CONFIG: `verbose` writes rationale on every block; `standard` writes only non-obvious WHY comments (lifecycle guards, `depends_on` overrides, non-evident expressions) and nothing on structural blocks; `none` writes no comments. Use British English in any prose comments (authorise, optimise, centre). Present code for review before writing `.tf` files.

**Phase 3 — Security pass (Sentinel-Scanner).** Mimic `checkov`/`trivy`. Flag High/Critical: public endpoints enabled where they need not be, unencrypted storage, weakest-TLS settings, and any allow-rule with `*` / `0.0.0.0/0` / `::/0`. Source secrets from the cloud's secret manager — never from defaults, state or logs. The specific knobs differ per cloud — read `references/<cloud>.md`.

**Phase 4 — Validation (State-Validator).** Run the plan-only chain directly — these are the exact commands scoped in `allowed-tools`, so they need no extra approval:
```bash
terraform init -backend=false -input=false   # downloads providers; no backend init
terraform validate
terraform fmt -check
terraform plan -input=false -out=tfplan
terraform show -json tfplan > plan_output.json
```
Report the Add/Change/Destroy summary. **Never** proceed to apply. Cross-check every replacement against the cloud's expensive-recreate list and apply the stop-and-confirm gate (§2).

`scripts/validate.sh` runs this same chain for humans and CI and writes `tfplan` and `plan_output.json`. Invoking it as `bash validate.sh` is a separate shell call that this skill does not pre-approve — run the commands above directly, or approve the script yourself.

**Phase 5 — Handoff.** Deliver the final report (§10).

---

## 6. Provider version pinning

Apply the strategy from SESSION CONFIG. General rules regardless of strategy:

| Component | Default strategy | Example |
|---|---|---|
| Terraform runtime | allow minor+patch | `required_version = "~> 1.13"` |
| Providers (root) | pin per SESSION CONFIG | `version = "~> 6.0"` |
| Modules (prod) | pin exact | `version = "5.1.2"` |
| Modules (dev) | allow patch | `version = "~> 5.1.0"` |

- Always commit `.terraform.lock.hcl`. It tracks **providers only** — modules re-resolve to the newest allowed version on every `init`.
- Pre-populate cross-platform hashes so CI does not fail on a checksum mismatch:
  `terraform providers lock -platform=linux_amd64 -platform=darwin_arm64 -platform=windows_amd64`.
- Child/reusable modules: set broad minimums (`>= 6.0`), let the **root** module resolve, to avoid diamond-dependency `init` failures.
- Keep provider/runtime upgrades in a separate PR from functional change. Upgrade one major at a time.

Current provider majors (verify the exact latest stable at research time):
- AWS `hashicorp/aws` → **v6.x**
- Azure `hashicorp/azurerm` → **v4.x**
- Google `hashicorp/google` (+ `google-beta`) → **v7.x**
- Oracle `oracle/oci` → **v8.x**

---

## 7. State migration mechanics (cloud-agnostic)

- `moved` (TF 1.1+) — rename/relocate or `count`↔`for_each` within one state file. Never cross-type, never cross-state-file.
- `import` (TF 1.5+) — config-driven import of existing resources.
- `removed` (TF 1.7+) — drop from state without destroying; pair with `lifecycle { destroy = false }`.
- `terraform state mv` — cross-state-file moves.
- Always `plan` and read the "move"/"import" lines before any apply. Deep dive: `references/migration-playbooks.md`; per-cloud upgrade gotchas: `references/<cloud>.md`.

---

## 8. Cloud-agnostic generation principles

- **One root per cloud.** Do not build a leaky abstraction module spanning clouds — the resource schemas diverge too far. Use provider aliasing for multi-region/multi-account *within* a cloud.
- **Separate environments from reusable modules.** Use `examples/` as integration fixtures.
- **Naming and tagging are NOT portable.** AWS uses `tags` + provider `default_tags`; Azure uses `tags`; GCP splits `labels` (billing/filtering) from network/resource-manager `tags`; OCI splits `freeform_tags` from namespaced `defined_tags`. Never assume one cloud's tag semantics on another — read the tagging section of `references/<cloud>.md`.
- **Secure defaults.** Private endpoints, encryption, least-privilege identity. Prefer the cloud's verified/official module ecosystem (namespaces in `references/<cloud>.md`).

---

## 9. Doc-research domains (allowlist)

Restrict provider-schema lookups to:
- **All providers (schema source of truth):** `registry.terraform.io/providers/{hashicorp/aws, hashicorp/azurerm, hashicorp/google, oracle/oci}/latest/docs`
- **AWS:** `docs.aws.amazon.com`
- **Azure:** `learn.microsoft.com`, `azure.github.io/Azure-Verified-Modules`
- **GCP:** `cloud.google.com/docs`
- **OCI:** `docs.oracle.com/en-us/iaas`, the `oci-landing-zones` GitHub org
- **Core/language:** `developer.hashicorp.com/terraform`

---

## 10. Final report structure

Use `assets/final-report-template.md` as the output template.

1. **Modular map** — tree of files created/updated.
2. **Security verdict** — ID | Severity | Issue | Resolution.
3. **Plan summary** — Add/Change/Destroy, with any replacement flagged and the stop-and-confirm outcome.
4. **Output contract** — assumptions; failure modes addressed; tradeoffs; rollback/recovery.
5. **Handoff** — "Code is staged and validated. Manual `terraform apply tfplan` is required."

---

## Reference files (load on demand)

Cloud-agnostic mechanisms:
- `references/identity-churn.md` — address stability, `count`/`for_each`, `moved` safety, the ForceNew principle.
- `references/blast-radius.md` — state boundaries, environment isolation, limiting apply impact.
- `references/migration-playbooks.md` — `moved`/`import`/`removed`, provider-upgrade and state-split playbooks.
- `references/compliance-gates.md` — policy-as-code on the plan, approvals, evidence, residency.

Per-cloud detail (load only those in SESSION CONFIG):
- `references/aws.md` · `references/azure.md` · `references/gcp.md` · `references/oci.md`

Reusable resources:
- `scripts/validate.sh` — canonical plan-only validation chain.
- `assets/session-config-template.md` — first substantive reply configuration block.
- `assets/final-report-template.md` — handoff report structure.
- `eval_queries.json` — labelled trigger regression set for description tuning.

## Attribution & licence

Failure-mode-first approach inspired by **TerraShark** (github.com/LukasNiessen/terrashark, MIT) and the diagnose-first / response-contract structure of **Anton Babenko's terraform-skill** (github.com/antonbabenko/terraform-skill, Apache-2.0). Reference content is original. Licensed MIT.
