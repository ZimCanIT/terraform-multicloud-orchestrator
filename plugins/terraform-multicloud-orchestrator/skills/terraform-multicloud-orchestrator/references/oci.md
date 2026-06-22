# OCI — Terraform reference (Oracle Cloud Infrastructure)

Provider: `oracle/oci`. No upstream multi-cloud skill covers OCI — rely on Oracle docs and the OCI Landing Zones org. Read alongside the cloud-agnostic mechanism files.

## Provider & pinning
- Current major: **v8.x** (`oracle/oci`, published by `tf-oci-pub`). Verify the exact latest patch at research time.
- Use `required_providers` block with `source = "oracle/oci"` and `version = "~> 8.0"` to allow minor and patch updates while locking the major version.
- Commit `.terraform.lock.hcl` (dependency lock file) to version control for consistency across all runs.
- For root modules, specify a maximum version constraint (e.g. `>= 8.0, < 9.0`) to prevent accidental upgrades to incompatible major versions.

## ForceNew traps (identity churn)
- `oci_core_instance` (compute) — forces replacement when changed: `availability_domain`, `cluster_placement_group_id`, `compute_cluster_id`, `compute_host_group_id`, `hostname_label`, `image` (deprecated), `ipxe_script`, `subnet_id` (deprecated).
- `oci_database_db_system` — forces replacement on non-updatable properties. Add non-updatable attributes (e.g. `admin_password`) to `lifecycle.ignore_changes` to prevent false diffs on subsequent applies. `hostname` may also need ignoring.
- General rule: any attribute not marked (Updatable) in the resource documentation forces replacement. Always run `terraform plan` before apply.

## Expensive / slow-to-recreate — STOP and confirm
Autonomous Database, Exadata / ExaCS, DRG (Dynamic Routing Gateway), DB Systems, File Storage Service (FSS), and `oci_core_instance` with dependent workloads. Recreating any of these is slow and breaks attached workloads.

- Mitigation: use `lifecycle.create_before_destroy` to spin up replacement before tearing down dependents, or `lifecycle.prevent_destroy` to block accidental deletion.
- Always review `terraform plan` output before apply to identify affected resources.

## Provider major-upgrade notes (state migration)
- v8.0.0 released February 4, 2026. **Breaking change**: `oci_globally_distributed_database` resource removed — any configurations using this resource must be migrated or removed before upgrading from v7.x.
- Migration path: remove GDD resource references from state/configuration and validate all non-updatable resource properties post-upgrade.

## Tagging
- Two tag types: `freeform_tags` (simple key-value, user-defined) and `defined_tags` (namespace-scoped, predefined keys using dot notation `namespace.key`).
- **Tag propagation**: OCI auto-propagates primary resource tags to secondary resources (e.g. compute instance tags → VNIC tags). Explicitly define all tags on secondary resources in configuration to avoid perpetual drift.
- **Oracle-managed namespace trap**: Default tags in the `Oracle-Tags` namespace (`CreatedBy`, `CreatedOn`, etc.) cause false diffs on subsequent applies. Suppress using provider block `ignore_defined_tags = ["Oracle-Tags.CreatedBy", "Oracle-Tags.CreatedOn"]` or `lifecycle.ignore_changes`.

## Secure defaults
- Private subnets: set `prohibit_public_ip_on_vnic = true` and `prohibit_internet_ingress = true`.
- On `oci_core_vcn` use `cidr_blocks` (list); the singular `cidr_block` is deprecated in v8.

## Policy-as-code & sovereignty (compliance gates)
- **Compartments**: Logical containers for resources; segregate access by function, team, or workload. IAM policies enforce role-based access control (RBAC) via policy statements using `oci_identity_policy` resource.
- **Regional policies**: Restrict service access by region to enforce data residency requirements.
- **Compliance**: OCI Landing Zones (CIS-aligned Terraform code in `oci-landing-zones` GitHub org) provide pre-built patterns: functional compartments (Network, Security, Database, AppDev), role-based groups, Cloud Guard monitoring, encryption keys, logging/alerting.
- **Realms & data residency**: Commercial, government, and sovereign realms provide fully isolated environments. No built-in tenant isolation or multi-cloud policy federation beyond OCI native controls.

## Module ecosystem
- **Official modules**: `oracle-terraform-modules/<name>/oci` namespace (e.g. `oracle-terraform-modules/oke/oci`, `oracle-terraform-modules/base/oci`, `oracle-terraform-modules/compute-instance/oci`).
  - OKE module v5.4.3+ (April 2026) actively maintained with 130+ versions.
  - IAM, base VCN, and compute modules recommended for production use.
- **Landing Zones**: `oci-landing-zones` GitHub org provides governance modules (Tags, Budgets, CIS benchmark alignment).
  - Main: `terraform-oci-core-landingzone` (successor to retired `oci-cis-landingzone-quickstart` as of May 2025).

## Doc sources
- Main OCI Terraform landing page: `https://docs.oracle.com/en-us/iaas/Content/dev/terraform/`
- Latest provider docs (version-agnostic, redirects to current stable): `https://docs.oracle.com/en-us/iaas/tools/terraform-provider-oci/latest/`
- Resource/datasource docs: `https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/terraform.htm` (redirects to version-specific)
- GitHub source & releases: `https://github.com/oracle/terraform-provider-oci`
- Terraform Registry: `https://registry.terraform.io/providers/oracle/oci`
