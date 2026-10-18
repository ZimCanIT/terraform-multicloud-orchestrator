# OCI — Terraform reference (Oracle Cloud Infrastructure)

Structure reviewed 2026-10-18. Provider facts here are not verified against provider docs unless marked.

Provider: `oracle/oci`. Read alongside the cloud-agnostic mechanism files.

## Provider & pinning
- Resolve the current major at research time (`oracle/oci`, published by `tf-oci-pub`).
- Use `required_providers` block with `source = "oracle/oci"` and `version = "~> <major>.0"` to allow minor and patch updates while locking the major version.
- Commit `.terraform.lock.hcl` (dependency lock file) to version control for consistency across all runs.
- For root modules, specify a maximum version constraint (e.g. `>= <major>.0, < <next-major>.0`) to prevent accidental upgrades to incompatible major versions.

## ForceNew traps (identity churn)
- Unverified (2026-10-18): `oci_core_instance` (compute) — forces replacement when changed: `availability_domain`, `cluster_placement_group_id`, `compute_cluster_id`, `compute_host_group_id`, `hostname_label`, `image` (deprecated), `ipxe_script`, `subnet_id` (deprecated).
- `oci_database_db_system` — forces replacement on non-updatable properties. Add non-updatable attributes (e.g. `admin_password`) to `lifecycle.ignore_changes` to prevent false diffs on subsequent applies. `hostname` may also need ignoring.
- General rule: any attribute not marked (Updatable) in the resource documentation forces replacement. Always run `terraform plan` before apply.

## Expensive-to-recreate table
Rows are the input to the stop-and-confirm gate; match on the resource type printed by the plan.

| Resource type | Why costly | ForceNew triggers | Protection flag | Disruptive in-place changes |
|---|---|---|---|---|
| `oci_database_autonomous_database` | Unverified (2026-10-18): Autonomous Database; resource type taken from the service name. Slow to recreate and breaks attached workloads | Unverified (2026-10-18) | `lifecycle.prevent_destroy` (mitigation below) | Not recorded |
| `oci_database_cloud_exadata_infrastructure` | Unverified (2026-10-18): Exadata / ExaCS; resource type taken from the service name. Slow to recreate and breaks attached workloads | Unverified (2026-10-18) | `lifecycle.prevent_destroy` (mitigation below) | Not recorded |
| `oci_core_drg` | Unverified (2026-10-18): Dynamic Routing Gateway; resource type taken from the service name. Slow to recreate and breaks attached workloads | Unverified (2026-10-18) | `lifecycle.prevent_destroy` (mitigation below) | Not recorded |
| `oci_database_db_system` | Slow to recreate and breaks attached workloads | Non-updatable properties, for example `admin_password` (see ForceNew traps) | `lifecycle.prevent_destroy` (mitigation below) | Not recorded |
| `oci_containerengine_cluster` | Unverified (2026-10-18): OKE cluster; resource type taken from the service name. Slow to recreate and breaks attached workloads | Unverified (2026-10-18) | `lifecycle.prevent_destroy` (mitigation below) | Not recorded |
| `oci_file_storage_file_system` | Unverified (2026-10-18): File Storage Service; resource type taken from the service name. Slow to recreate and breaks attached workloads | Unverified (2026-10-18) | `lifecycle.prevent_destroy` (mitigation below) | Not recorded |
| `oci_core_instance` | Recreating it breaks dependent workloads | `availability_domain`, `cluster_placement_group_id`, `compute_cluster_id`, `compute_host_group_id`, `hostname_label`, `ipxe_script`; Unverified (2026-10-18): `image` and `subnet_id` are marked deprecated | `lifecycle.prevent_destroy` (mitigation below) | Not recorded |
| `oci_kms_key` | Unverified (2026-10-18): data encrypted with the key cannot be read without it | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `oci_objectstorage_bucket` | Unverified (2026-10-18): holds object data; recreating the bucket does not bring its objects back | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |

- Mitigation: use `lifecycle.prevent_destroy` to block accidental deletion. create_before_destroy is not a downtime fix for database systems; plan a maintenance window (unverified per resource).
- Always review `terraform plan` output before apply to identify affected resources.

## Provider major-upgrade notes (state migration)
- Unverified (2026-10-18): v9: read the release notes (`github.com/oracle/terraform-provider-oci/releases`) before upgrading.
- Unverified (2026-10-18): v8.0.0 **Breaking change**: `oci_globally_distributed_database` resource removed — any configurations using this resource must be migrated or removed before upgrading from v7.x.
- Migration path: remove GDD resource references from state/configuration and validate all non-updatable resource properties post-upgrade.

## Tagging
- Two tag types: `freeform_tags` (simple key-value, user-defined) and `defined_tags` (namespace-scoped, predefined keys using dot notation `namespace.key`).
- **Tag propagation**: OCI auto-propagates primary resource tags to secondary resources (e.g. compute instance tags → VNIC tags). Explicitly define all tags on secondary resources in configuration to avoid perpetual drift.
- **Oracle-managed namespace trap**: Default tags in the `Oracle-Tags` namespace (`CreatedBy`, `CreatedOn`, etc.) cause false diffs on subsequent applies. Suppress using provider block `ignore_defined_tags = ["Oracle-Tags.CreatedBy", "Oracle-Tags.CreatedOn"]` or `lifecycle.ignore_changes`.

## Secure defaults
- Private subnets: set `prohibit_public_ip_on_vnic = true` and `prohibit_internet_ingress = true`.
- Unverified (2026-10-18): On `oci_core_vcn` use `cidr_blocks` (list); the singular `cidr_block` is deprecated in v8.

## Policy-as-code & sovereignty (compliance gates)
- **Compartments**: Logical containers for resources; segregate access by function, team, or workload. IAM policies enforce role-based access control (RBAC) via policy statements using `oci_identity_policy` resource.
- **Regional policies**: Restrict service access by region to enforce data residency requirements.
- **Compliance**: OCI Landing Zones (CIS-aligned Terraform code in `oci-landing-zones` GitHub org) provide pre-built patterns: functional compartments (Network, Security, Database, AppDev), role-based groups, Cloud Guard monitoring, encryption keys, logging/alerting.
- **Realms & data residency**: Commercial, government, and sovereign realms provide fully isolated environments. No built-in tenant isolation or multi-cloud policy federation beyond OCI native controls.

## Module ecosystem
- **Official modules**: `oracle-terraform-modules/<name>/oci` namespace (e.g. `oracle-terraform-modules/oke/oci`, `oracle-terraform-modules/base/oci`, `oracle-terraform-modules/compute-instance/oci`).
  - IAM, base VCN, and compute modules recommended for production use.
- **Landing Zones**: `oci-landing-zones` GitHub org provides governance modules (Tags, Budgets, CIS benchmark alignment).
  - Unverified (2026-10-18): Main: `terraform-oci-core-landingzone` (successor to the retired `oci-cis-landingzone-quickstart`).

## Doc sources
- Main OCI Terraform landing page: `https://docs.oracle.com/en-us/iaas/Content/dev/terraform/`
- Latest provider docs (version-agnostic, redirects to current stable): `https://docs.oracle.com/en-us/iaas/tools/terraform-provider-oci/latest/`
- Resource/datasource docs: `https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/terraform.htm` (redirects to version-specific)
- GitHub source & releases: `https://github.com/oracle/terraform-provider-oci`
- Terraform Registry: `https://registry.terraform.io/providers/oracle/oci`
