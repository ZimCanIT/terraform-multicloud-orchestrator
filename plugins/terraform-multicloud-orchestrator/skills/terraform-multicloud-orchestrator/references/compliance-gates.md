# Compliance gates — policy, residency, evidence

Advisory only: the agent never runs apply; these checks belong to the pipeline owner.

For regulated/sovereign workloads, the plan is the control point. Gate the **plan**, never auto-apply.

## Policy-as-code on the plan
- Run policy checks against the JSON plan (`terraform show -json tfplan`) with OPA/Conftest or the cloud-native engine; Sentinel runs as a gated check in HCP Terraform/TFE between plan and apply. Fail the pipeline on a policy violation; the apply remains a separate, manual, approved step.
- Static IaC scanning (checkov/trivy/tfsec-style) catches insecure configuration before plan.

Example for the pipeline owner:

```sh
terraform show -json tfplan > plan.json
conftest test plan.json --policy policy/
```

```rego
package main # example only
deny contains msg if { some rc in input.resource_changes; rc.type == "aws_db_instance"; "delete" in rc.change.actions; msg := rc.address }
```

Treat `plan.json` as secret-bearing, as SKILL.md §5 does for `tfplan`.

## Data residency & sovereignty
- Pin regions explicitly; never rely on a provider default region for regulated data.
- Each cloud has a residency/sovereignty construct and a guardrail engine — and the IAM/guardrail mental models are **NOT** portable: AWS SCPs only restrict, GCP org policy also only restricts (GCP IAM is additive), Azure management groups cascade. Read the compliance section of `references/<cloud>.md`.

## Approvals & evidence
- Require human approval between plan and apply (environment protection).
- Retain the plan artefact and policy results as audit evidence. Apply the reviewed artefact — do not re-plan inside the apply job.
