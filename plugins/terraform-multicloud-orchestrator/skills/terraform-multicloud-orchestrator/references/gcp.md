# GCP — Terraform reference

Providers: `hashicorp/google` and `hashicorp/google-beta` (use beta for preview fields; keep them in lockstep). Read alongside the cloud-agnostic mechanism files.

## Provider & pinning
- Current major: **v7.x**. Resolve the exact latest patch at research time.
- v7 tightened validation and continues HTTP migration of compute resources in v7.32.0+; ephemeral resources and write-only attributes arrived earlier (v6.13.0 and v6.23.0 respectively).
- Pinning strategy: `version = "~> 7.0"` for both `google` and `google-beta`. Lock files (`.terraform.lock.hcl`) must be committed to version control for team consistency.
- Each provider dependency must have an explicit version constraint.

## ForceNew traps (identity churn)
- `google_compute_instance` — recreation triggered by zone, machine_type, or boot_disk changes (immutable at creation time).
- `google_compute_instance_group` — recreation on resource policy changes; use `lifecycle.create_before_destroy` to avoid resource-in-use errors.
- `google_sql_database_instance` — name is ForceNew and reserved for ~weeks after deletion; requires `deletion_protection = false` before destruction. private_network cannot be removed after initial setting (update-only constraint).
- `google_container_node_pool` — node_config.labels, .metadata, .tags, workload_metadata_config, and name are ForceNew. NAP-created pools force replacement on import.
- `google_container_cluster` — several fields force full cluster recreate.
- `guest_accelerator` — empty blocks ([] syntax) no longer valid in v6.0+; requires careful migration path.

## Expensive / slow-to-recreate — STOP and confirm
- Cloud SQL instances: recreation causes service downtime and endpoint changes (psa_write_endpoint, private_ip_address may point to different instances post-failover); promoting read replicas to stand-alone requires instance restart.
- GKE clusters and node pools, Cloud Composer environments, Bigtable instances, Filestore: all slow and disruptive to recreate. Plan for maintenance windows.

## Provider major-upgrade notes (state migration)
- v6→v7: validation tightening, HTTP compute migration (v7.32.0+). Upgrade `google` and `google-beta` together.
- v5→v6 (2024): (1) `goog-terraform-provisioned` attribution label added by default (introduced 5.16.0, default in 6.0.0; opt-out via `add_terraform_attribution_label=false`); (2) deletion_protection defaults to true on Cloud Run, Cloud Domains, Redis, Folders, Projects; (3) removal of `require_ssl` from Cloud SQL (use `ssl_mode`); (4) removal of guest_accelerator and secondary_ip_range empty-block syntax. (The three-field label model is v5.0.0 — see Tagging.)

## Tagging
- Three distinct systems: `labels` (key/value) for billing/filtering, network `tags` (firewall targeting), and resource-manager **tags** (IAM-condition bindings) — these are NOT the same.
- v5.0.0+ redesigned label handling to prevent perpetual diffs: labels field manages only declared keys in config (non-authoritative); `terraform_labels` output-only shows merged labels (user + provider defaults); `effective_labels` output-only shows all labels including system-managed. Annotations reworked identically — manages only configured keys.
- System labels like `goog-terraform-provisioned` applied by default; exclude via `add_terraform_attribution_label=false`.
- On GKE `node_config`, labels/metadata/tags are ForceNew — changing them replaces the node pool.
- Provider-level `default_labels` apply globally.

## Policy-as-code & sovereignty (compliance gates)
- Terraform policy validation: `gcloud beta terraform vet` with Rego-based constraints (Terraform-based and CAI Cloud Asset Inventory models); status as of June 2026: preview/Pre-GA.
- Organization Policy constraints: hierarchical restrictions on service configurations (not IAM — IAM is who, Org Policy is what; inherited by descendants, can be merged or overridden per constraint). Use official `terraform-google-modules/org-policy`.
- VPC Service Controls: managed via official `terraform-google-modules/vpc-service-controls` (updated April 2026) for data exfiltration control and service perimeters.
- EU data residency: set the `gcp.resourceLocations` org-policy constraint to `in:eu-locations` (Assured Workloads packages this as EU Data Boundary).
- Assured Workloads and Sovereign Controls by Partners provide data residency + encryption/key-management guardrails (subject to Pre-GA terms).
- Security Command Center for threat and vulnerability detection.

## Module ecosystem
- Official verified modules: `terraform-google-modules/` namespace (part of Cloud Foundation Toolkit, actively maintained). Key modules: `kubernetes-engine` (GKE; updated Jan 2026), `vpc-service-controls` (service perimeters; updated April 2026), `org-policy` (organization constraints), `gcloud` (CLI wrapper).
- GoogleCloudPlatform namespace: `cloud-functions` (v0.9.0, April 2026), `cloud-armor` (v8.1.0, March 2026).
- 1383+ verified modules available in registry.

## Doc sources
- Provider docs & resources: `registry.terraform.io/providers/hashicorp/google/latest/docs`
- Upgrade guides & configuration: `registry.terraform.io/providers/hashicorp/google/latest/docs/guides/`
- Releases & changelog: `github.com/hashicorp/terraform-provider-google`
- Policy validation & Rego constraints: `docs.cloud.google.com/docs/terraform/policy-validation`
- Terraform provider versioning reference: `developer.hashicorp.com/terraform/tutorials/configuration-language/provider-versioning`
