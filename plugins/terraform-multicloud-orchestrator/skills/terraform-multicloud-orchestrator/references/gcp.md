# GCP — Terraform reference

Structure reviewed 2026-10-18. Provider facts here are not verified against provider docs unless marked.

Providers: `hashicorp/google` and `hashicorp/google-beta` (use beta for preview fields; keep them in lockstep). Read alongside the cloud-agnostic mechanism files.

## Provider & pinning
- Resolve the current major at research time.
- Unverified (2026-10-18): v7 tightened validation and continues HTTP migration of compute resources in v7.32.0+; ephemeral resources and write-only attributes arrived earlier (v6.13.0 and v6.23.0 respectively).
- Pinning strategy: the same `~> <major>.0` constraint for both `google` and `google-beta`. Lock files (`.terraform.lock.hcl`) must be committed to version control for team consistency.
- Each provider dependency must have an explicit version constraint.

## ForceNew traps (identity churn)
- `google_compute_instance` — zone and boot_disk changes force recreation; machine_type changes update in place when allow_stopping_for_update = true (the instance is stopped and started).
- `google_compute_instance_group` — recreation on resource policy changes; use `lifecycle.create_before_destroy` to avoid resource-in-use errors.
- Unverified (2026-10-18): `google_sql_database_instance` — name is ForceNew and reserved for ~weeks after deletion; requires `deletion_protection = false` before destruction. private_network cannot be removed after initial setting (update-only constraint).
- `google_container_node_pool` — node_config.labels, .metadata, .tags, workload_metadata_config, and name are ForceNew. NAP-created pools force replacement on import.
- `google_container_cluster` — several fields force full cluster recreate.
- Unverified (2026-10-18): `guest_accelerator` — empty blocks ([] syntax) no longer valid in v6.0+; requires careful migration path.

## Expensive-to-recreate table
Rows are the input to the stop-and-confirm gate; match on the resource type printed by the plan.

| Resource type | Why costly | ForceNew triggers | Protection flag | Disruptive in-place changes |
|---|---|---|---|---|
| `google_sql_database_instance` | Recreation causes service downtime and endpoint changes (`psa_write_endpoint`, `private_ip_address` may point to different instances after failover) | `name` | `deletion_protection` must be false before destruction | Promoting a read replica to stand-alone requires an instance restart |
| `google_container_cluster` | Slow and disruptive to recreate; plan a maintenance window | Several fields force full cluster recreation (not named in this file) | Unverified (2026-10-18) | Not recorded |
| `google_container_node_pool` | Slow and disruptive to recreate; plan a maintenance window | `node_config` labels, metadata and tags; `workload_metadata_config`; `name` | Unverified (2026-10-18) | Not recorded |
| `google_composer_environment` | Unverified (2026-10-18): listed as slow and disruptive to recreate; resource type taken from the service name | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `google_bigtable_instance` | Unverified (2026-10-18): listed as slow and disruptive to recreate; resource type taken from the service name | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `google_filestore_instance` | Unverified (2026-10-18): listed as slow and disruptive to recreate; resource type taken from the service name | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `google_project` | Unverified (2026-10-18): holds the resources and IAM bindings inside it; recreating it discards them | Unverified (2026-10-18) | Unverified (2026-10-18): `deletion_protection`, per the v5→v6 note | Not recorded |
| `google_kms_key_ring` | Unverified (2026-10-18): holds the keys that encrypt data; data encrypted under the old keys cannot be read through a new key ring | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |

## Provider major-upgrade notes (state migration)
- Unverified (2026-10-18): v7→v8: read the upgrade guide, linked from the release notes (`github.com/hashicorp/terraform-provider-google/releases/tag/v8.0.0`), before upgrading; upgrade `google` and `google-beta` together.
- Unverified (2026-10-18): v6→v7: validation tightening, HTTP compute migration (v7.32.0+). Upgrade `google` and `google-beta` together.
- Unverified (2026-10-18): v5→v6 (2024): (1) `goog-terraform-provisioned` attribution label added by default (introduced 5.16.0, default in 6.0.0; opt-out via `add_terraform_attribution_label=false`); (2) deletion_protection defaults to true on Cloud Run, Cloud Domains, Redis, Folders, Projects; (3) removal of `require_ssl` from Cloud SQL (use `ssl_mode`); (4) removal of guest_accelerator and secondary_ip_range empty-block syntax. (The three-field label model is v5.0.0 — see Tagging.) Reviewer flagged this bullet; check the google v6 upgrade guide before relying on it.

## Tagging
- Three distinct systems: `labels` (key/value) for billing/filtering, network `tags` (firewall targeting), and resource-manager **tags** (IAM-condition bindings) — these are NOT the same.
- Unverified (2026-10-18): v5.0.0+ redesigned label handling to prevent perpetual diffs: labels field manages only declared keys in config (non-authoritative); `terraform_labels` output-only shows merged labels (user + provider defaults); `effective_labels` output-only shows all labels including system-managed. Annotations reworked identically — manages only configured keys.
- System labels like `goog-terraform-provisioned` applied by default; exclude via `add_terraform_attribution_label=false`.
- On GKE `node_config`, labels/metadata/tags are ForceNew — changing them replaces the node pool.
- Provider-level `default_labels` apply globally.

## Policy-as-code & sovereignty (compliance gates)
- Unverified (2026-10-18): Terraform policy validation: `gcloud beta terraform vet` with Rego-based constraints (Terraform-based and CAI Cloud Asset Inventory models); it was preview/Pre-GA when last checked, so confirm its status first.
- Organization Policy constraints: hierarchical restrictions on service configurations (not IAM — IAM is who, Org Policy is what; inherited by descendants, can be merged or overridden per constraint). Use official `terraform-google-modules/org-policy`.
- VPC Service Controls: managed via official `terraform-google-modules/vpc-service-controls` for data exfiltration control and service perimeters.
- EU data residency: set the `gcp.resourceLocations` org-policy constraint to `in:eu-locations` (Assured Workloads packages this as EU Data Boundary).
- Unverified (2026-10-18): Assured Workloads and Sovereign Controls by Partners provide data residency + encryption/key-management guardrails (subject to Pre-GA terms).
- Security Command Center for threat and vulnerability detection.

## Module ecosystem
- Unverified (2026-10-18): Official verified modules: `terraform-google-modules/` namespace (part of Cloud Foundation Toolkit, actively maintained). Key modules: `kubernetes-engine` (GKE), `vpc-service-controls` (service perimeters), `org-policy` (organization constraints), `gcloud` (CLI wrapper).
- GoogleCloudPlatform namespace: `cloud-functions`, `cloud-armor`.

## Doc sources
- Provider docs & resources: `registry.terraform.io/providers/hashicorp/google/latest/docs`
- Upgrade guides & configuration: `registry.terraform.io/providers/hashicorp/google/latest/docs/guides/`
- Releases & changelog: `github.com/hashicorp/terraform-provider-google`
- Policy validation & Rego constraints: `docs.cloud.google.com/docs/terraform/policy-validation`
- Terraform provider versioning reference: `developer.hashicorp.com/terraform/tutorials/configuration-language/provider-versioning`
