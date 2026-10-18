# OpenTofu

OpenTofu uses the `tofu` binary with the same HCL as Terraform. SKILL.md's `allowed-tools` pre-approves the `tofu` forms of the plan-only commands: `init` (with `-backend=false` or `-input=false`), `validate`, `plan`, `show`, `fmt`, `get`, `providers` and `state list`. The plan-only rule applies to `tofu` as well: never run `tofu apply` or `tofu destroy`.

- Unverified (2026-10-18): state encryption is available in OpenTofu, and some language features differ from Terraform.
- Check the OpenTofu docs for feature parity before relying on a Terraform-only feature.
- Unverified (2026-10-18): which features exist depends on the OpenTofu release; confirm that the release you pin supports each one.
- Terragrunt is not covered by the plan commands in SKILL.md.
- Unverified (2026-10-18): `tofu show -json` is intended to produce plan JSON that the jq filter in SKILL.md §5 can read; confirm the output format before reusing that filter for the stop-and-confirm gate.
- Unverified (2026-10-18): confirm that each provider you use is available from the OpenTofu registry before you switch a project to `tofu`.
- Apply the same stop-and-confirm rule to `tofu` plans as to `terraform` plans: a planned replacement of an expensive-to-recreate resource still needs explicit human confirmation.
- OpenTofu state can contain secrets just as Terraform state can; see `state-and-secrets.md`.
