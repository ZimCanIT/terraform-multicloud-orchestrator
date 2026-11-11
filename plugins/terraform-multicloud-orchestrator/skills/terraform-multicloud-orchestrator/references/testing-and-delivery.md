# Testing and delivery

How Terraform for Azure is checked before anyone applies it, and the pipeline shape to recommend. The agent itself runs only the commands in `SKILL.md` §2; everything else here is for the user or the pipeline.

## The validation ladder

Cheapest first. Each step catches what the one before cannot.

| Step | Catches | Who runs it |
|---|---|---|
| `terraform fmt -check -recursive` | formatting | agent |
| `terraform validate` after `init -backend=false` | unknown arguments, wrong types, missing required values | agent |
| `scripts/tf_audit.py` | breaches of the authoring standard: literal secrets in code and variable files, public access, missing guards, names removed in `azurerm` 5 | agent, once the user approves the command; pipeline with `--fail-on major` |
| `tflint` with the `azurerm` rule set | invalid SKUs and sizes, deprecated syntax, unused declarations | user or pipeline |
| A static scanner such as Checkov or Trivy | insecure settings (public access, missing encryption) | user or pipeline |
| `terraform test` in plan mode | the module's contract: defaults, validation, optional features | user or pipeline |
| State-backed plan and the replacement check (`scripts/plan_review.py` reads it) | what will really change, deletions and replacements, and what forces each one | agent, with credentials |
| Policy on the plan JSON (Conftest or Sentinel) | organisation rules, before apply | pipeline |
| Azure Policy at deployment | whatever slipped through; a `deny` effect fails the apply | Azure |

`terraform validate` passing means the code matches the provider schema. It does not mean Azure will accept it: names in use, SKUs not offered in a region, quota and `deny` policies show up only at plan or apply. Say which steps ran and which did not.

A scanner finding is fixed in code. A skip is a decision: write it inline with the reason, for example `#checkov:skip=<check id>: reason`.

## Module tests in plan mode

`terraform test` creates real resources unless every `run` block uses `command = plan`. With `mock_provider` the test needs no credentials and nothing is deployed:

```hcl
# tests/defaults.tftest.hcl
mock_provider "azurerm" {}

variables {
  name                       = "stordersdevuks001"
  resource_group_name        = "rg-orders-dev-uks-001"
  location                   = "uksouth"
  account_replication_type   = "ZRS"
  log_analytics_workspace_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-logging-prod-uks-001/providers/Microsoft.OperationalInsights/workspaces/log-platform-prod-uks-001"
}

run "secure_defaults" {
  command = plan

  assert {
    condition     = azurerm_storage_account.this.shared_access_key_enabled == false
    error_message = "Shared key access must be off."
  }

  assert {
    condition     = length(azurerm_private_endpoint.blob) == 0
    error_message = "No private endpoint is expected when the input is null."
  }
}

run "rejects_an_invalid_name" {
  command = plan

  variables {
    name = "Not-Valid"
  }

  expect_failures = [var.name]
}
```

Test the contract, not the provider: the secure defaults hold; validation rejects bad input; an optional feature creates nothing when it is off; names follow the convention. `mock_provider` needs Terraform 1.7.

A mocked provider still checks arguments against the real schema, so IDs in test inputs must be well formed. `assets/reference-stack/modules/storage_account/tests/` holds a working copy of this pattern, and CI runs it.

## Pipeline shape

`assets/pipeline/terraform.yml` is a GitHub Actions workflow of this shape to adapt. It leaves out lint, a scanner and module tests, and it writes the list of deletions to the job summary; it does not comment on the pull request. Offer it when a repository has no pipeline; do not install it unasked.

1. **Pull request:** format check, validate, lint, scan, tests, then a plan with a read-only identity. Post the plan summary and the list of deletions and replacements on the pull request.
2. **Approval:** a person reviews the plan. Use the platform's environment protection (required reviewers) so that the approval is recorded.
3. **Apply:** apply the saved plan file from step 1. Do not plan again inside the apply job: what was reviewed is what runs. If the plan is stale, Terraform refuses it, and the pipeline starts again.

Details that matter on Azure:

- **Sign in with workload identity federation**, not a client secret (`identity-and-secrets.md`). Scope each federated credential to one environment or branch.
- **Two identities per environment.** The plan identity has Reader on the scope and Storage Blob Data Contributor on the state container (planning takes the lock), plus read access to any data plane the configuration reads. The apply identity has the write roles, and only it can run from the protected environment.
- **One run per state at a time.** Use the pipeline's concurrency control per stack and environment, and `-lock-timeout` so that a queued run waits instead of failing.
- **Plan files and plan JSON hold secrets.** Store them as short-lived, access-controlled artefacts. Never print them in logs.
- **Drift:** a scheduled `terraform plan -detailed-exitcode` (exit code 2 means changes) on each stack, reported to the owning team.

This skill never applies. When the user has no pipeline, the hand-off tells them to review the plan and run the apply themselves.

## Policy and compliance

- Find out which Azure Policy assignments apply to the target scope before writing code. A `deny` policy decides what valid code looks like: allowed regions, required tags, no public network access, allowed SKUs. Ask the user, or read the assignments in the repository's platform stack.
- Encode the same rules early as variable validation, for example an allowed list of regions, so that a mistake fails at `validate` and not at apply.
- Pin the region explicitly for regulated data. Never rely on a default location.
- Policy definitions and assignments belong in the platform stack (`azurerm_policy_definition` and the assignment resource for each scope), not in workload stacks. Management-group assignments apply to everything below them.
- Keep the plan, the policy results and the approval as evidence, with the retention the organisation requires.
