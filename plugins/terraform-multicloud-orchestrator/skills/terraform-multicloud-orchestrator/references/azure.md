# Azure — Terraform reference

Structure reviewed 2026-10-18. Provider facts here are not verified against provider docs unless marked.

Providers: `hashicorp/azurerm` (primary) and `azapi` (preview/uncovered resources). Read alongside the cloud-agnostic mechanism files.

## Provider & pinning
- Resolve the current major at research time and pin `~> <major>.0`. The v4 notes below still apply to v4 estates.
- Unverified (2026-10-18): v4 made `subscription_id` **required** (via the `subscription_id` argument or `ARM_SUBSCRIPTION_ID`), removed long-deprecated resources, and added provider-defined functions.
- The provider block requires a `features {}` block (even if empty); omitting it fails `terraform validate`.
- Handle `resource_provider_registrations = "none"` where the subscription pre-registers resource providers out of band.
- Before any major-version transition, read the release notes and upgrade guide for the target major (`github.com/hashicorp/terraform-provider-azurerm/releases`).

## Provider configuration safety
- Unverified (2026-10-18): check the current provider schema. The `azurerm` provider `features {}` block carries destroy-safety settings (for example `resource_group` `prevent_deletion_if_contains_resources` and `key_vault` `purge_soft_delete_on_destroy`).
- azapi manages resources through the Azure REST API; its schema is separate from azurerm. Unverified (2026-10-18).

## ForceNew traps (identity churn)
- Most `azurerm_*` resources force replacement when `name`, `location` or `resource_group_name` changes, so a rename or a move is a replacement: check the plan. That includes storage accounts, Key Vaults and SQL servers.
- `azurerm_subnet` — `name`, `resource_group_name`, `virtual_network_name` are ForceNew.
- Unverified (2026-10-18): `azurerm_linux_virtual_machine` / `azurerm_windows_virtual_machine` — `name`, `location`, `resource_group_name`, `zone`, OS-disk and image-reference changes, `vtpm_enabled`. `vm_agent_platform_updates_enabled` is read-only (v4.26.0+).
- `azurerm_*_virtual_machine_scale_set` — `upgrade_mode` and several profile fields.
- Unverified (2026-10-18): `azurerm_mobile_network_packet_core_control_plane` — `site_ids` marked ForceNew (v4.36.0+).
- Unverified (2026-10-18): `azurerm_postgresql_flexible_server` — downgrading version or `storage_mb` forces recreation (v4.27.0+).
- Unverified (2026-10-18): `azurerm_management_group_policy_set_definition` / `azurerm_policy_set_definition` — decreasing parameter count forces new resource creation (v4.35.0+).
- Public-IP / subnet / VM pinning is the classic Azure churn source. Monitor CHANGELOG for resource-specific force-new changes.

## Expensive-to-recreate table
Rows are the input to the stop-and-confirm gate; match on the resource type printed by the plan.

| Resource type | Why costly | ForceNew triggers | Protection flag | Disruptive in-place changes |
|---|---|---|---|---|
| `azurerm_api_management` | Unverified (2026-10-18): recreate takes 30–45 min | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `azurerm_virtual_network_gateway` | VPN and ExpressRoute gateway; listed as expensive to recreate; no reason recorded | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `azurerm_firewall` | Azure Firewall; listed as expensive to recreate; no reason recorded | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `azurerm_app_service_environment_v3` | App Service Environment; listed as expensive to recreate; no reason recorded | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `azurerm_kubernetes_cluster` | Long outage on recreate, often with a new public IP | `network_data_plane` (except the in-place azure → cilium reimage); availability zones | Unverified (2026-10-18) | The azure → cilium `network_data_plane` change is an in-place reimage |
| `azurerm_mssql_server` | Holds data; a recreate is a long outage and loses data unless restored | `name`, `location`, `resource_group_name` (general rule for most azurerm resources, including SQL servers) | Unverified (2026-10-18) | Not recorded |
| `azurerm_postgresql_flexible_server` | Holds data; a recreate is a long outage and loses data unless restored | Unverified (2026-10-18): downgrading version or `storage_mb` (file cites v4.27.0+) | Unverified (2026-10-18) | Not recorded |
| `azurerm_mysql_flexible_server` | Holds data; a recreate is a long outage and loses data unless restored | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `azurerm_cosmosdb_account` | Holds data; a recreate is a long outage and loses data unless restored | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `azurerm_storage_account` | Holds data; a recreate is a long outage and loses data unless restored | `name`, `location`, `resource_group_name` (general rule for most azurerm resources, including storage accounts) | Unverified (2026-10-18) | Not recorded |
| `azurerm_key_vault` | Holds keys and secrets; the name stays reserved after deletion until it is purged | `name`, `location`, `resource_group_name` (general rule for most azurerm resources, including Key Vaults) | Unverified (2026-10-18) | Not recorded |
| `azurerm_application_gateway` | Unverified (2026-10-18): front end for application traffic; recreating it interrupts that traffic | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |

## Provider major-upgrade notes (state migration)
- Unverified (2026-10-18): v3→v4: set `subscription_id`; remove the resources dropped in v4. Some resources (e.g. `azurerm_kusto_cluster`) have specific state-migration fixes — go straight to the latest release of the target major rather than stepping through its intermediate releases (still one major at a time).
- Unverified (2026-10-18): v4→v5: read the upgrade guide, linked from the release notes (`github.com/hashicorp/terraform-provider-azurerm/releases/tag/v5.0.0`), before upgrading. CDN Classic and Front Door Classic resources block new creations as of v4.35.0; migrate to newer services.
- Private Link DNS zone names follow `privatelink.<service-suffix>` conventions (e.g. `privatelink.blob.core.windows.net`).

## Tagging
- `tags` map on most resources, generally updatable in place (rarely ForceNew).
- Tag names are case-insensitive for Azure operations; tag values are case-sensitive.
- There is no provider-level default-tags equivalent — apply tags via a shared `locals` map, a tagging module, or a wrapper module. Perpetual diff issues can occur on tag-related properties; upgrade to a current provider release for fixes to specific resources.

## Policy-managed tags (ask before generating)
- Ask the user to paste `az account show` to confirm the active subscription; this skill does not pre-approve `az`, so run it yourself only if the user's settings allow it. That output cannot show whether Azure Policy modifies tags, so also ask whether it does and which tag keys it manages.
- If Policy is active or unknown, wherever you set `tags` on an `azurerm_*` resource, also add a `lifecycle` block with `ignore_changes` covering all tag keys managed by Policy (typically `environment`, `cost_centre`, `owner`, or whatever the tenant standard prescribes — ask the user if unsure). This prevents tag drift from causing spurious plan noise or blocked applies. Do this at generation time, not reactively.

## Policy-as-code & sovereignty (compliance gates)
- Sentinel is HashiCorp's Policy as Code framework (HCP Terraform / Terraform Enterprise) that evaluates the plan in a policy-check gate between plan and apply.
- Azure Policy (audit / deny / deployIfNotExists), Management Groups (hierarchical cascade), Microsoft Defender for Cloud / Compliance Manager.
- Unverified (2026-10-18): Azure Blueprints is deprecated; use Template Specs and Deployment Stacks instead. Check Microsoft Learn for current status.
- EU Data Boundary is the residency construct. Management-group policy **cascades** down the hierarchy — model inheritance deliberately.
- For data sovereignty: implement Sentinel policies; use Azure Policy assignments; encrypt sensitive data with customer-managed keys (CMK) in Key Vault or HSM; apply data classification and tagging per region. Azure Sovereign Landing Zone provides Bicep and Terraform reference implementations.
- Enterprise Policy As Code (EPAC) framework integrates with Azure Landing Zones for large-scale governance.

## Module ecosystem
- Unverified (2026-10-18): **Azure Verified Modules (AVM)** is the primary recommendation: resource modules `Azure/avm-res-<provider>-<resource>/azurerm`, pattern modules `Azure/avm-ptn-*/azurerm`. WAF-aligned secure defaults and a consistent interface (`name`, `location`, `tags`, `managed_identities`, `diagnostic_settings`, `role_assignments`, `private_endpoints`, `lock`). Available via `registry.terraform.io/namespaces/Azure` and `azure.github.io/Azure-Verified-Modules`. Many modules are still pre-1.0 (`0.y.z` — anything may change), so pin exact versions.
- Unverified (2026-10-18): the legacy CAF Enterprise Scale module (`Azure/caf-enterprise-scale/azurerm`) is deprecated and receives no further updates; new deployments should use Azure Verified Modules for Platform Landing Zones (`aka.ms/alz/tf`).
- `aztfmod/caf/azurerm` for Cloud Adoption Framework patterns.

## Doc sources
- **Terraform Registry**: `registry.terraform.io/providers/hashicorp/azurerm/latest/docs` — official resource / data source documentation.
- **Microsoft Learn**: `learn.microsoft.com/en-us/azure/developer/terraform` — Azure-native Terraform guides, provider version history, authentication, and best practices.
- **HashiCorp Developer**: `developer.hashicorp.com/terraform` — general Terraform patterns, Sentinel policy, and validated patterns.
- **GitHub**: `github.com/hashicorp/terraform-provider-azurerm` — CHANGELOG, issue tracking, contribution guidelines.
- **Azure Verified Modules portal**: `azure.github.io/Azure-Verified-Modules` — module catalog, implementation guidance, and design principles.
- **AzAPI provider**: `registry.terraform.io/providers/Azure/azapi/latest/docs` — documentation for resources not yet in azurerm (including provider functions `build_resource_id`, `parse_resource_id`).
