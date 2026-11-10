# Identity and secrets

How Terraform signs in, how workloads get access, and how to keep secrets out of code and state (AZ1, AZ2). Argument names were checked against the `azurerm` 5.x documentation on 10 November 2026; check the pinned version before writing them (AZ8).

## Provider authentication

The provider block carries no credentials:

```hcl
provider "azurerm" {
  features {}

  subscription_id     = var.subscription_id
  storage_use_azuread = true
}
```

| Where | How | Settings |
|---|---|---|
| A developer's machine | Azure CLI sign-in | none; `use_cli` is on by default |
| A pipeline | Workload identity federation (OIDC) | `ARM_USE_OIDC=true`, `ARM_CLIENT_ID`, `ARM_TENANT_ID`, `ARM_SUBSCRIPTION_ID` |
| A runner hosted in Azure | Managed identity | `ARM_USE_MSI=true`, plus `ARM_CLIENT_ID` for a user-assigned identity |

Never write `client_secret` into a provider block, a variable default or a `.tfvars` file. If a repository authenticates with a client secret, say that federation removes the secret and offer the change; do not rewrite the pipeline unasked.

## Managed identities

- **System-assigned** lives and dies with its resource. Use it when one resource needs access and nothing must exist before that resource starts.
- **User-assigned** is created first and granted access before anything uses it. Use it when access must already work at creation (customer-managed keys, image pulls when a cluster is created, Key Vault references at first start) or when several resources share one identity.

```hcl
resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${local.name_suffix}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "app_reads_secrets" {
  scope                = module.key_vault.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
  principal_type       = "ServicePrincipal"
}
```

For a workload in AKS, use `azurerm_federated_identity_credential` with the cluster's OIDC issuer URL and the subject `system:serviceaccount:<namespace>:<service account>`. No secret is mounted in the pod.

## Role assignments

- Scope to the narrowest thing that works: the resource, then the resource group. A subscription-scope assignment needs a reason in a comment.
- Pick the built-in role with the fewest permissions. Management-plane roles do not grant data access: Contributor cannot read a blob or a secret when the service uses Entra ID authorization. Use the data roles, for example Storage Blob Data Reader, Key Vault Secrets User, AcrPull, Azure Service Bus Data Sender.
- Set `principal_type = "ServicePrincipal"` for managed identities and service principals. It avoids a failure while a new identity is still replicating, and it is required when the deploying identity is limited by a condition on principal type. Changing it later replaces the assignment.
- Key `for_each` by a static name (`reader`, `app`), never by a principal ID, which is unknown until apply (HC1).
- The module that owns a resource outputs its `id` and its identity's `principal_id`. The caller, which sees both sides, creates the assignment (`module-design.md`).
- Assignments take time to take effect. A data-plane call straight afterwards can fail with 403. Add `depends_on` so that the order is right (HC7); add a delay only if the failure repeats.
- The identity that applies the code needs `Microsoft.Authorization/roleAssignments/write`. Give it Role Based Access Control Administrator with a condition that limits which roles it may assign, not Owner or User Access Administrator. Management locks need `Microsoft.Authorization/locks/*`, which that role and Contributor do not carry: add a custom role with those actions, or let the platform stack own the locks.
- An assignment that already exists fails with a conflict. Import it; do not create a duplicate under another name.

## Secrets, in order of preference

1. **No secret at all.** Turn on Entra-only authentication and there is nothing to store:

   | Resource | Setting |
   |---|---|
   | `azurerm_mssql_server` | `azuread_administrator { azuread_authentication_only = true }` |
   | `azurerm_postgresql_flexible_server` | `authentication { active_directory_auth_enabled = true, password_auth_enabled = false }` |
   | `azurerm_storage_account` | `shared_access_key_enabled = false` |
   | `azurerm_cosmosdb_account` | `local_authentication_enabled = false` |
   | `azurerm_servicebus_namespace` | `local_auth_enabled = false` |
   | `azurerm_container_registry` | `admin_enabled = false` |
   | `azurerm_kubernetes_cluster` | `local_account_disabled = true` |

2. **Terraform never sees the value.** Someone else puts the secret in Key Vault. The application reads it through a Key Vault reference or the Key Vault SDK with its managed identity. Terraform handles only the secret's ID. Do not read the value with the `azurerm_key_vault_secret` data source: a data source stores what it reads in state.

3. **Terraform sets the value but does not store it.** Use a write-only argument, which needs Terraform 1.11 or later. The value is sent to Azure and is not written to state or to the plan file:

   ```hcl
   ephemeral "random_password" "database" {
     length = 32
   }

   resource "azurerm_key_vault_secret" "database" {
     name             = "orders-database-admin"
     key_vault_id     = var.key_vault_id
     value_wo         = ephemeral.random_password.database.result
     value_wo_version = var.database_credential_version
   }
   ```

   A write-only value is sent only when its `_version` argument changes, and an ephemeral value is new on every run. Give the same value to every resource that needs it in the same run, and raise their versions together to rotate. Write-only arguments checked so far: `value_wo` on `azurerm_key_vault_secret`, `administrator_login_password_wo` on `azurerm_mssql_server`, `administrator_password_wo` on `azurerm_postgresql_flexible_server`.

4. **Last resort: the value is in state.** A `sensitive` variable or a `random_password` resource hides the value in output only. It is still in state and in plan files in clear text. Limit who can read the state, and say in the hand-off that the secret is there.

Whatever the option: no secret in an output, a tag, a resource name or a `local-exec` command line. To pass a secret between stacks, store it in Key Vault and pass the secret's ID.
