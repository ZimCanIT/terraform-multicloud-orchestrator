# Migration playbooks — refactors, imports, provider upgrades

All moves are plan-verified and reversible. Never apply a "move" you have not first read in the plan.

## Rename / restructure (within one state)
- Unverified (2026-10-18): Add a `moved` block (TF 1.1+):
  ```hcl
  moved {
    from = aws_db_instance.old
    to   = aws_db_instance.new
  }
  ```
  The plan should show a move, not a destroy+create. Never use `moved` across state files. Across resource types it works only where the target provider supports it (Terraform 1.8+); otherwise use `removed` + `import`.
- `count`↔`for_each` conversion: use one `moved` per element to map old indexes to new keys.

## Import existing resources
- Unverified (2026-10-18): Config-driven `import` block (TF 1.5+):
  ```hcl
  import {
    to = aws_s3_bucket.this
    id = "my-bucket"
  }
  ```
  Run `plan` to confirm the import and surface drift before applying. `terraform plan -generate-config-out=generated.tf` scaffolds HCL for imported resources.

## Remove without destroying
- Unverified (2026-10-18): `removed` block (TF 1.7+) with `lifecycle { destroy = false }` drops a resource from state while leaving the real infrastructure intact.

## Cross-state moves
- Unverified (2026-10-18): Prefer `removed` + `import` blocks for cross-state moves; `terraform state mv -state-out=...` still works but `-state`/`-state-out` are legacy (there is no `moved`-block equivalent across files). `terraform state mv` is a proposed command for you to run; the agent never runs it.

## Provider major upgrades
- One major at a time. Read the provider's upgrade guide on the registry first.
- Pin the new major, run `init -upgrade`, then `plan` and diff carefully — major bumps often re-type attributes or change defaults. `init -upgrade` is a proposed command for you to run; the agent never runs it.
- Keep the upgrade in its own PR, separate from functional change. Per-cloud upgrade specifics: `references/<cloud>.md`.
