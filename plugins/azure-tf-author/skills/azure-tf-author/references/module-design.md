# Module design

Where code lives and what its interface looks like. Rule IDs refer to `SKILL.md` §3.

## Two kinds of module (ST1)

A **root module** (a stack) is what `terraform plan` runs in. It owns the backend, the provider configuration, the version pins and the inputs for each environment, and it composes reusable modules.

A **reusable module** implements one capability. It has no backend and no `provider` block. It states the minimum provider versions it works with and lets the root choose the version:

```hcl
terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 5.0"
    }
  }
}
```

When a module needs a second provider configuration, for example to create a DNS record in the connectivity subscription, declare the alias and let the root pass it in:

```hcl
# modules/spoke_network/versions.tf
terraform {
  required_providers {
    azurerm = {
      source                = "hashicorp/azurerm"
      version               = ">= 5.0"
      configuration_aliases = [azurerm.connectivity]
    }
  }
}

# stacks/network/main.tf
module "spoke_network" {
  source = "../../modules/spoke_network"

  providers = {
    azurerm              = azurerm
    azurerm.connectivity = azurerm.connectivity
  }

  # ...
}
```

## Repository layout

```text
modules/
  spoke_network/       main.tf  variables.tf  outputs.tf  versions.tf  README.md  tests/
  storage_account/
stacks/
  network/             versions.tf  providers.tf  backend.tf  main.tf  variables.tf  outputs.tf  locals.tf
    environments/      dev.tfvars  prod.tfvars  dev.backend.hcl  prod.backend.hcl
  workload_orders/
```

- Per-environment input files (`environments/prod.tfvars`) hold no secrets and are committed. `terraform.tfvars` and `*.auto.tfvars` load automatically and are often local, so commit `terraform.tfvars.example` instead (HC8, AZ2). If the repository ignores every `*.tfvars` file, follow it and ask how environments receive their inputs.
- One root with an input file per environment suits environments that have the same shape (ST3). Use a separate root per environment only when the environments differ structurally, for example when production alone has a second region. Do not model that difference with conditionals.
- A new empty repository starts as one stack and its modules. Split into more stacks when the boundaries below appear, not in advance.

## Choosing a boundary (ST2, MD1)

Resources that change together and are deleted together belong in one module. Split a stack when any of these differ:

- **Owner:** another team approves changes to it.
- **Rate of change:** application settings change daily, a hub network yearly.
- **Blast radius:** a database must not be in the plan when a web app changes.
- **Permissions:** deploying it needs rights the workload pipeline should not have, such as role assignments at subscription scope.

Typical Azure layers, each with its own state: platform (management groups, policy, central logging), connectivity (hub network, firewall, private DNS zones), shared services for an environment, then one stack per workload. Long-lived data stores sit in their own stack when the workload around them is redeployed often.

The root, or a small dedicated module, creates resource groups and passes `resource_group_name` and `location` down. A reusable module does not create the resource group it deploys into (MD2).

## Interface design (MD2 to MD5)

A module encodes decisions. An argument with one right answer in the organisation is a literal inside the module: the TLS floor, public access off, shared keys off. Add a variable only where callers have a real reason to differ. A module that exposes every provider argument is a thin wrapper with extra maintenance (MD1).

Model an optional feature as an object that is null when the feature is off, not as a flag with loose companions:

```hcl
variable "private_endpoint" {
  description = "Private endpoint for the blob service. Null creates none."
  type = object({
    subnet_id            = string
    private_dns_zone_ids = list(string)
  })
  default = null
}

resource "azurerm_private_endpoint" "blob" {
  count = var.private_endpoint == null ? 0 : 1

  # ...
}
```

Checklist for an interface:

- Inputs every module takes: the name or the parts that build it, `location`, `resource_group_name`, `tags`.
- Dependencies arrive as IDs: `subnet_id`, `log_analytics_workspace_id`, `key_vault_id`, `private_dns_zone_ids`. No data source inside the module finds them (MD2).
- Role assignments the module's resource needs on other resources are created by the caller, which knows both sides. The module outputs `principal_id`.
- Outputs: `id`, `name`, and what a caller needs to connect or grant access (`principal_id`, an endpoint host name). No whole resource, no keys, no connection strings (MD5).
- A change that removes or renames an input or output is a breaking change. Version the module, and keep `moved` blocks for renamed resources until every consumer has applied them.

Pin a registry module with an exact `version`. Pin a Git source to a tag: `source = "git::https://example.com/org/modules.git//storage_account?ref=v1.4.0"`.

## Azure Verified Modules (MD6)

Azure Verified Modules (AVM) are Microsoft-maintained modules with a common interface. Resource modules are named `Azure/avm-res-<provider>-<resource>/azurerm` and pattern modules `Azure/avm-ptn-<name>/azurerm`. Most accept `name`, `location`, `resource_group_name`, `tags`, `lock`, `role_assignments`, `diagnostic_settings`, `private_endpoints`, `managed_identities` and `enable_telemetry`.

Use one when the resource is standard, you need its cross-cutting features, and the team has no module of its own. Platform landing zones should start from the AVM pattern modules (`aka.ms/alz/tf`). Before adopting one:

- Read its `required_providers`. A module that constrains `azurerm` to an older major cannot be used in a root that pins a newer one, and many AVM modules also require `azapi`.
- Many are still `0.y.z`, where any release may break. Pin exactly and read the release notes before every bump.
- `enable_telemetry` defaults to on. Set it according to the organisation's policy.
- Call the module from the stack. Do not wrap it in a module that passes every input through.

Write a native module instead when the AVM interface is far larger than the need, when it lags the provider major the repository uses, or when the organisation's baseline differs from the module's defaults in many places.

## Documentation and tests

Each reusable module has a `README.md` with its purpose, one usage example and its inputs and outputs (`terraform-docs` generates the tables), an `examples/` directory that doubles as a test fixture, and plan-mode tests under `tests/` (`testing-and-delivery.md`).

`assets/reference-stack/` in this skill is a small stack with three modules written to these rules.
