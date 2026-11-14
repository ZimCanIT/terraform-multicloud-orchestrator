# Secure baseline by resource type

The arguments that make each common resource private, identity-based and recoverable (AZ1 to AZ6). In a module these are literals, not variables (`module-design.md`).

Argument names were checked against the `azurerm` 5.x documentation on 10 November 2026. Where 4.x used another name it is noted. Check the registry page for the version the repository pins before you write any of them (AZ8).

## Storage account

```hcl
resource "azurerm_storage_account" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location

  account_kind             = "StorageV2"
  account_tier             = "Standard"
  account_replication_type = var.account_replication_type

  https_traffic_only_enabled        = true
  min_tls_version                   = "TLS1_2"
  shared_access_key_enabled         = false
  default_to_oauth_authentication   = true
  allow_nested_items_to_be_public   = false
  cross_tenant_replication_enabled  = false
  local_user_enabled                = false
  public_network_access             = "Disabled" # earlier releases: public_network_access_enabled = false
  infrastructure_encryption_enabled = true       # changing this later replaces the account

  blob_properties {
    versioning_enabled = true

    delete_retention_policy {
      days = 30
    }

    container_delete_retention_policy {
      days = 30
    }
  }

  tags = var.tags
}
```

- With shared keys off, the provider needs `storage_use_azuread = true`, which covers the Blob and Queue data planes, and the deploying identity needs a data-plane role such as Storage Blob Data Contributor. `azurerm_storage_container` takes `storage_account_id` and is created through the management plane; check the page of any other storage resource for the plane it uses.
- With public network access off, the machine that runs Terraform needs a private path to the account for any data-plane call. The provider's `storage` feature has a `data_plane_available` switch: on a runner with no private path, set `features { storage { data_plane_available = false } }` in the root and say so in the hand-off.
- Use either the inline `network_rules` block or `azurerm_storage_account_network_rules`, never both.
- Reach the account through private endpoints, one per service in use (`networking.md`).
- Log categories are on the service, not the account: target `"${azurerm_storage_account.this.id}/blobServices/default"` in the diagnostic setting.

## Key Vault

```hcl
resource "azurerm_key_vault" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  tenant_id           = var.tenant_id
  sku_name            = "standard"

  rbac_authorization_enabled    = true # earlier releases: enable_rbac_authorization
  purge_protection_enabled      = true
  soft_delete_retention_days    = 90
  public_network_access_enabled = false

  network_acls {
    bypass         = "AzureServices"
    default_action = "Deny"
  }

  tags = var.tags
}
```

- Purge protection cannot be turned off, and the retention period cannot be changed after creation. A deleted vault keeps its name reserved until it is purged, and purge protection blocks purging for the retention period. With the provider's `recover_soft_deleted_key_vaults` feature on, creating a vault of the same name brings the deleted vault back with its old contents instead of making a new one.
- Grant access with roles, not access policies: Key Vault Secrets User to read secrets, Key Vault Secrets Officer to manage them, Key Vault Crypto Service Encryption User for customer-managed keys.
- Write secrets with `value_wo` and `value_wo_version` so that the value stays out of state (`identity-and-secrets.md`).

## Azure SQL

```hcl
resource "azurerm_mssql_server" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  version             = "12.0"

  minimum_tls_version           = "1.2"
  public_network_access_enabled = false

  azuread_administrator {
    login_username              = var.entra_admin.login
    object_id                   = var.entra_admin.object_id
    azuread_authentication_only = true # no SQL logins, so no administrator password exists
  }

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}
```

Put `prevent_destroy = true` on `azurerm_mssql_database`, set its backup retention blocks explicitly, and send audit logs to Log Analytics.

## PostgreSQL flexible server

```hcl
resource "azurerm_postgresql_flexible_server" "this" {
  # ...
  public_network_access_enabled = false

  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = false
    tenant_id                     = var.tenant_id
  }

  lifecycle {
    prevent_destroy = true

    # Azure swaps the zones after a failover. Do not let Terraform move the server back.
    ignore_changes = [zone, high_availability[0].standby_availability_zone]
  }
}
```

If password authentication is unavoidable, use `administrator_password_wo` with `administrator_password_wo_version`.

## App Service and Functions

```hcl
resource "azurerm_linux_web_app" "this" {
  # ...
  https_only                      = true
  public_network_access_enabled   = false
  virtual_network_subnet_id       = var.integration_subnet_id
  key_vault_reference_identity_id = var.identity_id

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  site_config {
    minimum_tls_version    = "1.2"
    ftps_state             = "Disabled"
    http2_enabled          = true
    vnet_route_all_enabled = true
  }
}
```

- Application settings that need a secret hold a Key Vault reference, `@Microsoft.KeyVault(SecretUri=<secret id>)`, never the value.
- The identity named in `key_vault_reference_identity_id` must also be listed in the `identity` block.
- Old code may use `azurerm_app_service`, `azurerm_app_service_plan` or `azurerm_function_app`. Those types were removed in 5.0; the replacements are `azurerm_linux_web_app` or `azurerm_windows_web_app`, `azurerm_service_plan`, and `azurerm_linux_function_app` or `azurerm_windows_function_app`.

## AKS

```hcl
resource "azurerm_kubernetes_cluster" "this" {
  # ...
  sku_tier                  = "Standard"
  local_account_disabled    = true
  oidc_issuer_enabled       = true
  workload_identity_enabled = true
  private_cluster_enabled   = true
  azure_policy_enabled      = true
  automatic_upgrade_channel = "patch"
  node_os_upgrade_channel   = "NodeImage"

  azure_active_directory_role_based_access_control {
    azure_rbac_enabled     = true
    admin_group_object_ids = var.admin_group_object_ids
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [var.cluster_identity_id]
  }

  node_provisioning_profile {
    mode = "Manual"
  }

  default_node_pool {
    name                         = "system"
    vm_size                      = var.system_pool.vm_size
    vnet_subnet_id               = var.node_subnet_id
    zones                        = ["1", "2", "3"]
    auto_scaling_enabled         = true
    min_count                    = 3
    max_count                    = 5
    only_critical_addons_enabled = true
    temporary_name_for_rotation  = "systemtmp"
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_data_plane  = "cilium"
    network_policy      = "cilium"
    outbound_type       = "userDefinedRouting"
  }

  lifecycle {
    # The cluster autoscaler owns the node count.
    ignore_changes = [default_node_pool[0].node_count]
  }
}
```

- Without `temporary_name_for_rotation`, a change to the system pool's size, zones or subnet cannot be rolled and fails or replaces.
- Changing `private_cluster_enabled` replaces the cluster, and the OIDC issuer cannot be turned off once on.
- Add user node pools as `azurerm_kubernetes_cluster_node_pool` with `for_each`.
- Let the kubelet identity pull images with an AcrPull role assignment; do not enable the registry's admin user.
- From 5.0 the `node_provisioning_profile` block is required. `mode = "Manual"` keeps node pools under Terraform's control; `Auto` hands node provisioning to AKS.

## Other services

| Resource | Baseline arguments |
|---|---|
| `azurerm_container_registry` | `admin_enabled = false`, `public_network_access_enabled = false`, `anonymous_pull_enabled = false`, `zone_redundancy_enabled = true` (Premium only; changing it replaces the registry) |
| `azurerm_cosmosdb_account` | `local_authentication_enabled = false` (4.x: `local_authentication_disabled = true`), `public_network_access_enabled = false`, `automatic_failover_enabled = true`, `minimal_tls_version = "Tls12"` |
| `azurerm_servicebus_namespace` | `local_auth_enabled = false`, `public_network_access_enabled = false`, `minimum_tls_version = "1.2"` |

Private endpoints need the Premium tier on Container Registry and Service Bus. Say so when a cheaper SKU is requested, and do not quietly raise the SKU.

## Linux virtual machine

```hcl
resource "azurerm_linux_virtual_machine" "this" {
  # ...
  disable_password_authentication = true
  encryption_at_host_enabled      = true
  secure_boot_enabled             = true
  vtpm_enabled                    = true
  patch_mode                      = "AutomaticByPlatform"
  zone                            = var.zone

  admin_ssh_key {
    username   = var.admin_username
    public_key = var.admin_ssh_public_key
  }

  identity {
    type = "SystemAssigned"
  }

  boot_diagnostics {}
}
```

No public IP on the network interface: reach the machine through Bastion or a private path. Changing `zone`, `secure_boot_enabled`, `vtpm_enabled` or the SSH key replaces the machine. Encryption at host must be enabled for the subscription before the first apply.

## Diagnostic settings (AZ6)

```hcl
resource "azurerm_monitor_diagnostic_setting" "this" {
  name                       = "diag-${var.name}"
  target_resource_id         = azurerm_key_vault.this.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category_group = "allLogs"
  }

  enabled_metric { # earlier releases: metric
    category = "AllMetrics"
  }
}
```

Categories differ by resource type. Read them from the resource's documentation or from the `azurerm_monitor_diagnostic_categories` data source in a root; do not copy a list from another type.

## Locks (AZ5)

Use `azurerm_management_lock` with `lock_level = "CanNotDelete"` on resources whose deletion is an incident: the state storage account, hub networking, production data stores. Avoid `ReadOnly`: it blocks operations that are reads in name only, such as listing storage keys.

A lock stops deletion from outside Terraform: the portal, the CLI, another pipeline. It does not stop the run that manages it. On `destroy` or a replacement, Terraform removes the lock first, because the lock depends on the resource. To stop Terraform itself use `prevent_destroy` (HC5), or keep the lock in a separate stack that the workload pipeline cannot run. Say in the hand-off which protection applies.

Creating and deleting locks needs `Microsoft.Authorization/locks/*`, which Contributor and Role Based Access Control Administrator do not carry. Give the apply identity a custom role with those actions, or let the platform stack own the locks.
