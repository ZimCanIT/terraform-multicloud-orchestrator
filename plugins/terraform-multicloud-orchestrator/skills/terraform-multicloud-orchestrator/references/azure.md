# Azure — Terraform reference

Providers: `hashicorp/azurerm` (primary) and `azapi` (preview/uncovered resources). Read alongside the cloud-agnostic mechanism files.

## Provider & pinning
- Current major: **v4.x**. Latest stable = v4.x; resolve the exact latest patch at research time. Use `version = "~> 4.0"`.
- v4 made `subscription_id` **required** (via the `subscription_id` argument or `ARM_SUBSCRIPTION_ID`), removed long-deprecated resources, and added provider-defined functions.
- The provider block requires a `features {}` block (even if empty); omitting it fails `terraform validate`.
- Handle `resource_provider_registrations = "none"` where the subscription pre-registers resource providers out of band.
- v5.0 is in development with breaking changes planned; monitor CHANGELOG and HashiCorp's upgrade guide before major-version transitions.

## ForceNew traps (identity churn)
- `azurerm_subnet` — `resource_group_name`, `virtual_network_name` are ForceNew.
- `azurerm_linux_virtual_machine` / `azurerm_windows_virtual_machine` — `name`, `location`, `resource_group_name`, `zone`, OS-disk and image-reference changes, `vtpm_enabled`. `vm_agent_platform_updates_enabled` is read-only (v4.26.0+).
- `azurerm_*_virtual_machine_scale_set` — `upgrade_mode` and several profile fields.
- `azurerm_mobile_network_packet_core_control_plane` — `site_ids` marked ForceNew (v4.36.0+).
- `azurerm_postgresql_flexible_server` — downgrading version or `storage_mb` forces recreation (v4.27.0+).
- `azurerm_management_group_policy_set_definition` / `azurerm_policy_set_definition` — decreasing parameter count forces new resource creation (v4.35.0+).
- Public-IP / subnet / VM pinning is the classic Azure churn source. Monitor CHANGELOG for resource-specific force-new changes.

## Expensive / slow-to-recreate — STOP and confirm
API Management (APIM — 30–45 min recreate), VPN Gateway, ExpressRoute Gateway, Azure Firewall, App Service Environment, AKS clusters. Changing AKS `network_data_plane` (except the in-place azure → cilium reimage) or availability zones forces entire cluster replacement with significant downtime. A recreate of any of these is a long outage and often a new public IP.

## Provider major-upgrade notes (state migration)
- v3→v4: set `subscription_id`; remove the resources dropped in v4. Some resources (e.g. `azurerm_kusto_cluster`) have specific state-migration fixes — upgrade directly to the current version rather than stepping through.
- v4→v5: Breaking changes pending include removal of deprecated `virtual_machines.graceful_shutdown` feature flag (deprecated v4.26.0), renaming of `enable_rbac_authorization` to `rbac_authorization_enabled` on Key Vault, and archival of legacy CAF Enterprise Scale resources. CDN Classic and Front Door Classic resources block new creations as of v4.35.0; migrate to newer services. Review HashiCorp's v5.0 upgrade guide and resource-specific release notes.
- Private Link DNS zone names follow `privatelink.<service-suffix>` conventions (e.g. `privatelink.blob.core.windows.net`).

## Tagging
- `tags` map on most resources, generally updatable in place (rarely ForceNew).
- Tag names are case-insensitive for Azure operations; tag values are case-sensitive.
- There is no provider-level default-tags equivalent — apply tags via a shared `locals` map, a tagging module (e.g. Claranet's `tagging/azurerm` v2.0.0+), or a wrapper module. Perpetual diff issues can occur on tag-related properties; upgrade to v4.35.0+ to access fixes for specific resources.

## Policy-as-code & sovereignty (compliance gates)
- Sentinel is HashiCorp's Policy as Code framework (HCP Terraform / Terraform Enterprise) that evaluates the plan in a policy-check gate between plan and apply.
- Azure Policy (audit / deny / deployIfNotExists), Management Groups (hierarchical cascade), Microsoft Defender for Cloud / Compliance Manager.
- Azure Blueprints deprecated July 11, 2026. Migrate new implementations to Template Specs and Deployment Stacks per Microsoft Learn.
- EU Data Boundary is the residency construct. Management-group policy **cascades** down the hierarchy — model inheritance deliberately.
- For data sovereignty: implement Sentinel policies; use Azure Policy assignments; encrypt sensitive data with customer-managed keys (CMK) in Key Vault or HSM; apply data classification and tagging per region. Azure Sovereign Landing Zone provides Bicep and Terraform reference implementations.
- Enterprise Policy As Code (EPAC) framework integrates with Azure Landing Zones for large-scale governance.

## Module ecosystem
- **Azure Verified Modules (AVM)** is the primary recommendation: resource modules `Azure/avm-res-<provider>-<resource>/azurerm`, pattern modules `Azure/avm-ptn-*/azurerm`. WAF-aligned secure defaults and a consistent interface (`name`, `location`, `tags`, `managed_identities`, `diagnostic_settings`, `role_assignments`, `private_endpoints`, `lock`). Available via `registry.terraform.io/namespaces/Azure` and `azure.github.io/Azure-Verified-Modules`. Many modules are still pre-1.0 (`0.y.z` — anything may change), so pin exact versions.
- Legacy CAF Enterprise Scale module transitioned to extended support and archives 1 August 2026; new deployments should use AVM.
- `aztfmod/caf/azurerm` for Cloud Adoption Framework patterns.

## Doc sources
- **Terraform Registry**: `registry.terraform.io/providers/hashicorp/azurerm/latest/docs` — official resource / data source documentation.
- **Microsoft Learn**: `learn.microsoft.com/en-us/azure/developer/terraform` — Azure-native Terraform guides, provider version history, authentication, and best practices.
- **HashiCorp Developer**: `developer.hashicorp.com/terraform` — general Terraform patterns, Sentinel policy, and validated patterns.
- **GitHub**: `github.com/hashicorp/terraform-provider-azurerm` — CHANGELOG, issue tracking, contribution guidelines.
- **Azure Verified Modules portal**: `azure.github.io/Azure-Verified-Modules` — module catalog, implementation guidance, and design principles.
- **AzAPI provider**: `registry.terraform.io/providers/Azure/azapi/latest/docs` — documentation for resources not yet in azurerm (including provider functions `build_resource_id`, `parse_resource_id`).
