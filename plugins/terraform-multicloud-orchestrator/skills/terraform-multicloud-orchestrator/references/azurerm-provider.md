# The azurerm and azapi providers

Provider configuration, names that changed between majors, when to use `azapi`, what forces a replacement, and the stop list for `SKILL.md` §2.

## Versions

On 10 November 2026 the registry listed `hashicorp/azurerm` 5.13.0, `Azure/azapi` 2.13.0, `hashicorp/azuread` 3.10.0 and Terraform 1.17.1. That line is a snapshot: resolve the versions again, and in an existing repository use the ones in `.terraform.lock.hcl`.

## Root configuration

```hcl
terraform {
  required_version = "~> 1.13"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.13"
    }
  }
}

provider "azurerm" {
  features {}

  subscription_id     = var.subscription_id
  storage_use_azuread = true
}
```

- The `features {}` block is required, even when empty.
- `subscription_id` is needed for `plan` and `apply`, from the argument or `ARM_SUBSCRIPTION_ID`. `terraform validate` works without it. Never write the ID as a literal (HC2).
- From 5.0 the provider registers no Azure resource providers by default (`resource_provider_registrations` defaults to `none`). List what the configuration needs in `resource_providers_to_register`, or confirm that the platform team registers them, or the first apply of a new service fails with a registration error.
- From 5.0 the provider no longer checks `location` values and resource provider names at plan time by default, so a mistyped region fails at apply. Validate regions in variables (MD4), or turn the check back on with `features { enhanced_validation { locations = true, resource_providers = true } }`. The same block has `preflight_enabled`, which asks Azure to validate a few supported resource types during plan and needs credentials.
- `storage_use_azuread = true` makes storage data-plane calls with Entra ID. It is required once shared keys are off on a storage account.
- Credentials come from the environment (`identity-and-secrets.md`), never from the provider block.

## Names that changed

Old code, old answers and old examples use the earlier names. The left column is what the 5.x documentation shows.

| Resource | 5.x documentation | Earlier name |
|---|---|---|
| `azurerm_storage_account` | `public_network_access = "Disabled"` | `public_network_access_enabled = false` |
| `azurerm_storage_account` | the `azurerm_storage_account_static_website` and `azurerm_storage_account_queue_properties` resources | inline `static_website` and `queue_properties` blocks (removed in 5.0) |
| `azurerm_storage_container` | `storage_account_id` | `storage_account_name` (removed in 5.0) |
| `azurerm_storage_account` | `https_traffic_only_enabled` | `enable_https_traffic_only` (3.x) |
| `azurerm_key_vault` | `rbac_authorization_enabled`, now required | `enable_rbac_authorization` (removed in 5.0) |
| `azurerm_monitor_diagnostic_setting` | `enabled_metric` | `metric` (removed in 5.0) |
| `azurerm_cosmosdb_account` | `local_authentication_enabled = false` | `local_authentication_disabled = true` (removed in 5.0) |
| `azurerm_log_analytics_workspace` | `local_authentication_enabled = false` | `local_authentication_disabled = true` (removed in 5.0) |
| `azurerm_cosmosdb_account` | `automatic_failover_enabled` | `enable_automatic_failover` (3.x) |
| `azurerm_kubernetes_cluster` | `automatic_upgrade_channel`, `node_os_upgrade_channel` | `automatic_channel_upgrade`, `node_os_channel_upgrade` (3.x) |
| `azurerm_kubernetes_cluster` node pools | `auto_scaling_enabled` | `enable_auto_scaling` (3.x) |
| `azurerm_kubernetes_cluster` | a `node_provisioning_profile` block, now required | not required before 5.0 |
| `azurerm_subnet` | `private_endpoint_network_policies` (a string) | `private_endpoint_network_policies_enabled` (a boolean, 3.x) |
| `azurerm_subnet` | `service_endpoint` blocks | the `service_endpoints` list (removed in 5.0) |
| `azurerm_federated_identity_credential` | `user_assigned_identity_id` | `parent_id` (removed in 5.0) |
| provider block | `resource_provider_registrations` | `skip_provider_registration` (3.x) |

Resource types that old code still uses and that no longer exist:

- Removed in 5.0: `azurerm_app_service`, `azurerm_app_service_plan` and `azurerm_function_app` (use the `azurerm_linux_*` and `azurerm_windows_*` web and function app types with `azurerm_service_plan`); `azurerm_postgresql_server` and its child resources (use `azurerm_postgresql_flexible_server`); `azurerm_static_site` (use `azurerm_static_web_app`).
- Removed in 4.0: `azurerm_sql_server` and `azurerm_sql_database` (use `azurerm_mssql_server` and `azurerm_mssql_database`).

This table is not complete. The rule is AZ8: read the page for the pinned version.

## When to use `azapi` (HC6)

Use `azapi` when `azurerm` at the pinned version cannot express a resource type or a property, typically a preview feature. Do not use it by default, and never shell out to `az` instead.

```hcl
# Shape only: azurerm_container_app_environment already manages this type. Use azapi only for a
# type or property that the pinned azurerm lacks, and name that gap in a comment like this one.
resource "azapi_resource" "container_environment" {
  type      = "Microsoft.App/managedEnvironments@2024-03-01"
  name      = local.names.container_environment
  parent_id = azurerm_resource_group.this.id
  location  = azurerm_resource_group.this.location

  body = {
    properties = {
      zoneRedundant = true
      vnetConfiguration = {
        infrastructureSubnetId = var.infrastructure_subnet_id
      }
    }
  }

  tags = local.tags
}
```

- State the API version in `type` and take it from the Azure REST documentation for that resource. In `azapi` 2.x `body` is an HCL object, not a JSON string.
- `azapi_update_resource` changes one property of a resource that `azurerm` manages. Two providers then own one resource: add a narrow `ignore_changes` on the `azurerm` side if it reports drift, with a comment.
- Leave a comment naming the `azurerm` gap. When the provider closes it, move the resource with `removed` and `import` blocks (`adopt-and-refactor.md`).

## What forces a replacement

A replacement is a delete followed by a create. For anything that holds data or takes long to build, that is an outage or a loss.

- **Almost every resource:** `name`, `location` and `resource_group_name`. A rename or a move is a replacement.
- **`azurerm_subnet`:** `name` and `virtual_network_name`.
- **Virtual machines:** `name`, `zone`, the SSH key, `secure_boot_enabled`, `vtpm_enabled`, and OS disk and image changes.
- **`azurerm_storage_account`:** `infrastructure_encryption_enabled`, `is_hns_enabled`, `nfsv3_enabled`, some changes to `account_kind`, and `account_replication_type` when it crosses between non-zonal (`LRS`, `GRS`, `RAGRS`) and zonal (`ZRS`, `GZRS`, `RAGZRS`) types. The pairs `LRS`/`ZRS`, `GRS`/`GZRS` and `RAGRS`/`RAGZRS` convert in place, through a migration that can take days.
- **`azurerm_key_vault`:** `name`. A deleted vault's name stays reserved until the vault is purged, and creating a vault of the same name can recover the deleted one (`secure-baseline.md`).
- **`azurerm_container_registry`:** `zone_redundancy_enabled`.
- **`azurerm_kubernetes_cluster`:** `private_cluster_enabled`; turning the OIDC issuer off; changing `network_data_plane` (the in-place move from `azure` to `cilium` is the exception). Changes to the default node pool's `vm_size`, `zones`, `vnet_subnet_id` and the other properties its page lists are rolled through a temporary pool and need `temporary_name_for_rotation` (`secure-baseline.md`).
- **`azurerm_postgresql_flexible_server`:** lowering the version or `storage_mb`. `zone` changes after a failover, so ignore it (`secure-baseline.md`).
- **`azurerm_role_assignment`:** the scope, the principal, the role and `principal_type`. Cheap to recreate, but access is lost for a moment.
- **Policy set definitions:** removing a parameter.

Providers change these between releases. The plan is the authority: read every line marked `# forces replacement`.

## Stop list: stop and confirm before a replacement or deletion

When a state-backed plan deletes or replaces one of these types, stop as `SKILL.md` §2 describes.

- **Holds data:** `azurerm_storage_account`, `azurerm_key_vault`, `azurerm_mssql_server`, `azurerm_mssql_database`, `azurerm_postgresql_flexible_server`, `azurerm_mysql_flexible_server`, `azurerm_cosmosdb_account`, `azurerm_container_registry`, `azurerm_log_analytics_workspace`, `azurerm_recovery_services_vault`, managed disks.
- **Slow or disruptive to rebuild:** `azurerm_kubernetes_cluster`, `azurerm_api_management` (30 to 45 minutes), `azurerm_virtual_network_gateway`, `azurerm_firewall`, `azurerm_application_gateway`, `azurerm_app_service_environment_v3`, `azurerm_virtual_network` and `azurerm_subnet` when anything is deployed in them.
- **Changes an address or identity that others depend on:** `azurerm_public_ip`, `azurerm_private_endpoint`, `azurerm_user_assigned_identity`, `azurerm_private_dns_zone`.

Fix-forward options to offer: revert the attribute that forces the replacement; add a `moved` block if only the address changed; add `create_before_destroy` if two copies can exist at once; restore the data after a planned recreate, with the user's agreement.

## Major upgrades

- Move to the last release of the current major first and clear every deprecation warning there. Those warnings are the list of what the next major removes.
- Read the upgrade guide for the target major in the registry's guides before changing the pin, and expect changed defaults as well as changed names. The 5.0 guide removes 39 resource types and lists breaking changes in 134 others; the change to resource provider registration is one of them.
- Front Door (classic) and CDN (classic) resources have blocked new creations since 4.35.0. Move to the current services before or with the upgrade.
- Go to the newest release of the target major, not its first: later releases carry fixes to state migrations.
- The procedure is in `adopt-and-refactor.md`.
