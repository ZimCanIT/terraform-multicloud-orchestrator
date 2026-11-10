# State and environments

Where state lives, how it is divided, and how environments stay the same shape (ST2 to ST4). Backend argument names were checked against the Terraform backend documentation on 10 November 2026.

## The `azurerm` backend

Keep the backend block free of environment values and supply them per environment:

```hcl
# backend.tf
terraform {
  backend "azurerm" {
    use_azuread_auth = true
  }
}
```

```hcl
# environments/prod.backend.hcl
storage_account_name = "sttfstateproduks001"
container_name       = "tfstate"
key                  = "network.tfstate"
```

The user initialises with `terraform init -backend-config=environments/prod.backend.hcl`. That is not one of the agent's permitted `init` forms (`SKILL.md` §2), so ask the user to run it.

- `use_azuread_auth = true` signs in to the blob with Entra ID. The identity needs **Storage Blob Data Contributor** on the state container. In a pipeline add `use_oidc = true`, or set `ARM_USE_OIDC`, with the tenant and client IDs.
- No `access_key`, no `sas_token` and no `ARM_ACCESS_KEY`. An access key gives full control of every state in the account and cannot be traced to a person.
- The blob lease is the state lock. Clearing a stuck lock is `force-unlock`, which only the user runs.

## The state storage account

State holds every attribute of every resource, secrets included. Treat the account as the most sensitive store in the estate:

- its own resource group, in a platform subscription where one exists;
- shared keys off, public access restricted to the networks that run Terraform, TLS 1.2;
- blob versioning, blob soft delete and container soft delete, so that a bad write can be undone;
- zone-redundant or geo-redundant replication;
- a `CanNotDelete` lock, and diagnostic logs to Log Analytics;
- access granted per container, so that a workload pipeline cannot read platform state.

The account is created once by a small bootstrap stack that the user applies. Do not put the state account in the stack whose state it holds.

## Dividing state (ST2)

One state is one unit of failure, of locking and of permission. Typical layout:

| Layer | Example contents | Changes |
|---|---|---|
| Platform | management groups, policy, central logging | rarely |
| Connectivity | hub network, firewall, gateways, private DNS zones | rarely |
| Shared services, per environment | container registry, shared Key Vault, monitoring | monthly |
| Workload, per environment | application resources, their identities and role assignments | daily |
| Workload data, per environment | databases and storage that outlive deployments | rarely |

Use one container per environment and one key per stack, for example container `prod`, key `connectivity.tfstate`.

Signs that a state should be split: a plan for an application change lists network or database resources; teams wait for each other's lock; a plan takes minutes; the pipeline identity needs broad rights only because of a few resources in the state. Split with `removed` and `import` blocks (`adopt-and-refactor.md`).

These never share a state: production with non-production; a data store with compute that is redeployed often; platform role assignments with workloads.

## Environments (ST3)

- Same code, different inputs. Each environment has an input file and a backend file; the difference between development and production is visible in two small files.
- Each environment is its own subscription where the landing zone provides one. `subscription_id` is an input, so the same root plans against either.
- Do not branch on `terraform.workspace`, and do not use CLI workspaces to separate long-lived environments: they share one backend configuration and one set of credentials, and the selected workspace is invisible in the code. They suit short-lived review environments only.
- Promote by applying the same commit and the same module versions to each environment in turn. A change that cannot be expressed as an input difference is a structural difference: give that environment its own root (`module-design.md`).

A root that also manages resources in another subscription declares a second provider configuration:

```hcl
provider "azurerm" {
  alias = "connectivity"
  features {}

  subscription_id = var.connectivity_subscription_id
}
```

## Passing values between stacks (ST4)

In order of preference:

1. **An input.** Names follow the convention, so IDs are predictable; put the hub network ID or the DNS zone IDs in the environment's input file.
2. **A data source in the root** that reads the real resource by name, for example `data "azurerm_virtual_network"`. Never inside a reusable module (MD2).
3. **`terraform_remote_state`**, only when the two above cannot work. The reader needs access to the whole of the other state, secrets included, and the two stacks are coupled to each other's outputs.

## Recovery

Blob versioning keeps earlier versions of the state. Restoring one is a manual step that the user takes with the lock held. Never edit state by hand and never propose `state push`. Change what state records with `moved`, `import` and `removed` blocks, which a plan can show before anything happens.
