# Example session — AWS VPC (greenfield)

A walkthrough of one full orchestration, from prompt to plan-only handoff, for a
small greenfield AWS network. It shows what the skill produces at each phase; it
is **not** runnable Terraform you should copy verbatim — provider schemas move,
so the orchestrator re-researches them at run time.

This skill is **plan-only**. Nothing here runs `apply` or `destroy`.

---

## User prompt

> Stand up a new VPC for a dev environment in eu-west-1: three private subnets
> across AZs, no public subnets yet. Keep it modular.

The working directory is empty, so this is greenfield and the target cloud is not
yet known from context.

---

## Phase 0 — Session setup

The orchestrator asks the two setup questions once. The user picks AWS and accepts
the default pinning strategy. It then emits SESSION CONFIG and treats it as
authoritative for the rest of the session:

```
SESSION CONFIG
- Clouds: aws
- Pinning: latest-stable-and-pin
- Mode: greenfield
- Resolved provider versions: <filled in after research>
```

Only `references/aws.md` is loaded — never the other cloud files.

## Phase 1 — Research (Doc-Specialist)

Schema for `aws_vpc`, `aws_subnet` and `aws_route_table` is verified against
`registry.terraform.io/providers/hashicorp/aws/latest/docs`. The current latest
stable AWS provider major resolves to **v6.x**, written as `~> 6.0`, with
`required_version = "~> 1.13"` for the Terraform runtime. SESSION CONFIG is updated:

```
- Resolved provider versions: hashicorp/aws ~> 6.0; terraform ~> 1.13
```

## Phase 2 — Generation (HCL-Architect)

A modular layout is scaffolded — a root calling a composite `network` module:

```
aws-vpc/
├── providers.tf
├── main.tf            # calls module "network"
├── variables.tf
├── outputs.tf
├── terraform.tfvars
└── modules/
    └── network/
        ├── main.tf    # aws_vpc + private subnets + route table
        ├── variables.tf
        └── outputs.tf
```

Subnets use `for_each` over an AZ→CIDR map (not `count`) so an AZ change never
churns the index of unrelated subnets. Prose comments use British English
(authorise, optimise). Code is presented for review before any `.tf` file is written.

## Phase 3 — Security pass (Sentinel-Scanner)

The generated HCL is scanned the way `checkov`/`trivy` would. For private subnets
with no internet gateway the surface is small; the scanner confirms there are no
`0.0.0.0/0` ingress rules, no public IP auto-assignment, and that no secrets are
sourced from defaults or state.

## Phase 4 — Validation (State-Validator)

The plan-only chain runs directly (these are the exact commands scoped in
`allowed-tools`):

```bash
terraform init -backend=false -input=false
terraform validate
terraform fmt -check
terraform plan -input=false -out=tfplan
terraform show -json tfplan > plan_output.json
```

Every line of the plan is `+ create`; nothing forces replacement, so the
stop-and-confirm gate (§2 of `SKILL.md`) does not trigger.

---

## Phase 5 — Handoff (final report)

```
# Final Report

## Modular Map
aws-vpc/
├── providers.tf
├── main.tf
├── variables.tf
├── outputs.tf
├── terraform.tfvars
└── modules/network/{main,variables,outputs}.tf

## Security Verdict
| ID | Severity | Issue | Resolution |
|---|---|---|---|
| — | — | No High/Critical findings | Private-only subnets; no wide-open rules |

## Plan Summary
- Add: 5        # 1 VPC, 3 subnets, 1 route table
- Change: 0
- Destroy: 0
- Replacements: none

## Output Contract
- Assumptions and version floor: hashicorp/aws ~> 6.0, terraform ~> 1.13;
  for_each keyed on AZ; three private subnets, no public subnets.
- Failure modes addressed: identity churn (for_each over count).
- Tradeoffs: composite network module over inline resources for reuse;
  no NAT gateway yet (no egress requirement stated).
- Rollback / recovery: discard the branch before apply; no state exists yet,
  so there is nothing to import or move.

## Handoff
Code is staged and validated. Manual `terraform apply tfplan` is required.
```

The user reviews `tfplan` / `plan_output.json` and runs the apply themselves —
the skill never does.
