# Reference stack

A small root module and three reusable modules written to the standard in `SKILL.md` §3. Copy the patterns, not the files: a real stack has its own resources, names and inputs.

CI runs `terraform init -backend=false`, `terraform validate` and `terraform fmt -check -recursive` on this directory, then validates each module on its own and runs its tests (`.github/workflows/terraform-fixture.yml`). The arguments here are therefore valid for the provider version that `versions.tf` pins. The stack is never planned against Azure or applied, and no lock file is committed because it is not a deployment.

## What it shows

| Where | Rule | Pattern |
|---|---|---|
| `versions.tf`, `providers.tf`, `backend.tf` | ST1, ST2, AZ8 | Pins, provider configuration and an Entra ID backend live in the root only; the subscription is an input |
| `modules/storage_account/versions.tf` | ST1 | A reusable module states a minimum provider version and configures nothing |
| `variables.tf` | MD3, MD4 | Typed inputs with descriptions and validation; an optional feature as an object that may be null |
| `locals.tf` | HC2, HC3, AZ7 | Names and tags built once; mandatory tags cannot be overridden |
| `main.tf` | MD2, AZ1 | The stack creates the resource group and the identity, passes IDs down, and grants the role itself |
| `modules/storage_account/main.tf` | AZ1, AZ3, AZ4, AZ5, AZ6 | Shared keys off, public access off, TLS floor, soft delete and versioning, logs to Log Analytics; a private endpoint when the caller supplies a subnet |
| `modules/storage_account/main.tf` | HC5 | `prevent_destroy` on the account, so Terraform cannot destroy or replace it; a lock as the separate guard against deletion from outside Terraform |
| `modules/storage_account/main.tf` | HC1 | `count` only as a zero-or-one switch |
| `modules/storage_account/outputs.tf`, `outputs.tf` | MD5 | IDs, names and an endpoint; no keys |
| `modules/storage_account/tests/` | MD4 | Tests in plan mode with a mocked provider: the secure defaults, the optional endpoint, the name validation |
| `main.tf` | AZ2, HC2, HC7 | A generated value written to Key Vault through a write-only argument, so it is in neither state nor plan; the tenant and deployer read from `azurerm_client_config`; a `depends_on` with its reason |
| `modules/key_vault/main.tf` | AZ1, AZ3, AZ5, AZ6, HC5 | Role-based access, purge protection, public access off, audit logs, `prevent_destroy`; a private endpoint when the caller supplies a subnet |
| `modules/key_vault/tests/` | MD4 | The secure defaults, the optional endpoint, rejection of a name with consecutive hyphens |
| `modules/virtual_network/variables.tf` | MD3, MD4 | A map of objects with `optional()` defaults and nested rules; validation of CIDR ranges and enumerations |
| `modules/virtual_network/main.tf` | HC1, AZ3 | `for_each` over the input map for subnets, security groups and associations; private subnets; a `dynamic` block for an optional delegation; a final deny rule |
| `modules/virtual_network/locals.tf` | HC1 | Nested rules flattened into one map with a composite key |
| `modules/virtual_network/tests/` | MD4 | One security group per subnet, the rule keys, rejection of an invalid prefix |

## What it leaves out

The root is a workload stack. The virtual network module belongs to a network stack with its own state (ST2), so the root does not call it; the workload receives a subnet ID as an input instead. Also left out: a pipeline, policy-managed tag keys and a second environment. `references/testing-and-delivery.md`, `references/naming-and-tagging.md` and `references/state-and-environments.md` cover them.
