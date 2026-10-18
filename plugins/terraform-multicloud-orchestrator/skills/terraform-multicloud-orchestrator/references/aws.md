# AWS — Terraform reference

Structure reviewed 2026-10-18. Provider facts here are not verified against provider docs unless marked.

Provider: `hashicorp/aws`. Read alongside the cloud-agnostic mechanism files.

## Provider & pinning
- Resolve the current major at research time; the upgrade notes below cover v5 to v6.
- Unverified (2026-10-18): Pin versions using `required_providers` block and `.terraform.lock.hcl` dependency lock file. Use `~> <major>.N.0` (pessimistic-patch, N = the resolved minor) to fix major and minor; use `~> <major>.N` (pessimistic-minor) to allow minor and patch to change; avoid deprecated `version` argument in provider blocks.
- Example: `required_providers { aws = { source = "hashicorp/aws", version = "~> <major>.N.0" } }`.
- Unverified (2026-10-18): v6 introduced per-resource `region` argument (most resources accept a top-level `region`; global services — IAM, CloudFront, Route 53 — do not), removed OpsWorks / SimpleDB / Worklink, retyped launch-template booleans, and removed the `aws_eip` `vpc` argument (use `domain`).

## ForceNew traps (identity churn)
- **`aws_rds_cluster`**: `cluster_identifier`, `cluster_identifier_prefix`, `engine`, `db_subnet_group_name`, `snapshot_identifier` are ForceNew. Changes trigger full resource recreation and downtime.
- `aws_rds_cluster_instance`: `identifier`, `identifier_prefix`, `engine`, `db_subnet_group_name`, `cluster_identifier` all force replacement.
- Unverified (2026-10-18): `aws_db_instance`: `engine`, `availability_zone`, `character_set_name`, `snapshot_identifier` are ForceNew (`identifier` is modifiable). Reviewer flagged this ForceNew list; check the provider schema before relying on it.
- `aws_instance` — `ami`, `subnet_id`, certain `root_block_device` changes.
- `aws_s3_bucket` — `bucket` name; deleting a non-empty bucket needs `force_destroy = true`.
- Empty-string module defaults have historically forced replacement — pass `null`, not `""`.

## Expensive-to-recreate table
Rows are the input to the stop-and-confirm gate; match on the resource type printed by the plan.

| Resource type | Why costly | ForceNew triggers | Protection flag | Disruptive in-place changes |
|---|---|---|---|---|
| `aws_db_instance` | Listed as expensive to recreate; engine and snapshot changes force recreation (not an in-place update) | `engine`, `availability_zone`, `character_set_name`, `snapshot_identifier` | Unverified (2026-10-18) | `apply_immediately` causes a brief downtime reboot during modifications |
| `aws_rds_cluster` | Listed as expensive to recreate; changes trigger full recreation and downtime | `cluster_identifier`, `cluster_identifier_prefix`, `engine`, `db_subnet_group_name`, `snapshot_identifier` | Unverified (2026-10-18) | Not recorded |
| `aws_rds_cluster_instance` | Listed as expensive to recreate (RDS instances and clusters) | `identifier`, `identifier_prefix`, `engine`, `db_subnet_group_name`, `cluster_identifier` | Unverified (2026-10-18) | Not recorded |
| `aws_eks_cluster` | Unverified (2026-10-18): listed as expensive to recreate; no reason recorded | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `aws_nat_gateway` | Unverified (2026-10-18): listed as expensive to recreate; no reason recorded | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `aws_cloudfront_distribution` | Unverified (2026-10-18): listed as expensive to recreate; no reason recorded | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `aws_ec2_transit_gateway` | Unverified (2026-10-18): listed as expensive to recreate; no reason recorded | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `aws_elasticache_cluster` | Unverified (2026-10-18): listed as expensive to recreate; no reason recorded | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `aws_redshift_cluster` | Unverified (2026-10-18): listed as expensive to recreate; no reason recorded | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `aws_opensearch_domain` | Unverified (2026-10-18): listed as expensive to recreate; no reason recorded | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `aws_dynamodb_table` | Unverified (2026-10-18): holds table data; recreating it without a restore loses the items | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `aws_kms_key` | Unverified (2026-10-18): data encrypted under the key cannot be read once the key is gone | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `aws_route53_zone` | Unverified (2026-10-18): a new zone gets new name servers, so the parent delegation must be updated | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |
| `aws_eip` | Unverified (2026-10-18): recreating it changes the public IP that DNS records and allow-lists depend on | Unverified (2026-10-18) | Unverified (2026-10-18) | Not recorded |

- **RDS downtime**: `apply_immediately` causes a brief downtime reboot during modifications. Engine / snapshot changes force recreation (not in-place update). Replacing an RDS instance with the same identifier cannot run alongside the old instance, because identifiers are unique; plan a maintenance window and a snapshot-based migration instead.
- Unverified (2026-10-18): S3 global endpoint support deprecated in v6 (removal planned for v7); `s3_us_east_1_regional_endpoint = "regional"` in us-east-1 requires migration.

## Provider major-upgrade notes (v5 to v6)
Upgrade one major at a time; read the provider upgrade guide on the registry first.
- **Breaking changes**:
  - Unverified (2026-10-18): `aws_kinesis_analytics_application` (SQL) is deprecated in v6 (removal planned). Migrate to `aws_kinesisanalyticsv2_application`.
  - Unverified (2026-10-18): `aws_simpledb_domain` removed entirely (AWS SDK v2 dropped support).
  - Unverified (2026-10-18): EC2 `user_data` now stored clear-text (no longer hashed). Remove embedded secrets before upgrading.
  - Unverified (2026-10-18): `cpu_core_count` / `cpu_threads_per_core` removed from `aws_instance` — use `cpu_options` block instead.
  - Unverified (2026-10-18): `data.aws_ami` with `most_recent = true` now requires explicit `owner` or `image_id` filter (was silent-fail warning in v5).
  - Unverified (2026-10-18): S3 global endpoint support deprecated; configure per-resource regional endpoints.
- Unverified (2026-10-18): **Recommendation**: Upgrade to latest v5 first, run `terraform plan` to identify issues, then upgrade to v6.
- Unverified (2026-10-18): **Previous migrations** (v4→v5): Split `aws_s3_bucket` into sub-resources (`aws_s3_bucket_versioning`, `aws_s3_bucket_server_side_encryption_configuration`, etc.) and changed `default_tags` precedence.

## Tagging
- Resource `tags` map plus provider-level `default_tags` (merged into every resource). Read the effective set via computed `tags_all`.
- **Trap**: Partial overlap between `default_tags` and a resource's own `tags` causes perpetual diff. Keep keys disjoint or manage centrally.
- Unverified (2026-10-18): **Mitigation**: Use `lifecycle.ignore_changes = [tags_all]` or `lifecycle.ignore_changes = ["tags.SpecificKey"]` to suppress external tag modifications. Check the current lifecycle and tagging docs.
- **Auto Scaling Group limitation**: `default_tags` cannot reach dynamically-created EC2 instances (AWS manages them). Use `aws_default_tags` data source as workaround.
- Unverified (2026-10-18): **Comparison**: External systems modifying tags will trigger perpetual diffs on `tags_all` — compare `tags` instead, or ignore `tags_all` entirely. Check the current lifecycle and tagging docs.

## Policy-as-code & sovereignty (compliance gates)
- **AWS Control Tower guardrails** (multi-account governance):
  - **Preventive controls** via Service Control Policies (SCPs): block unauthorised actions before provisioning (e.g., enforce data residency, prevent public access). SCPs only restrict — they never grant permissions.
  - **Detective controls** via AWS Config rules: audit and report post-provisioning violations.
  - **Proactive controls** via CloudFormation hooks: scan resources before provisioning, fail non-compliant templates. (verify against current AWS Control Tower documentation).
- **HashiCorp Sentinel**: Policy-as-code enforcement in HCP Terraform for additional governance layers.
- **Data residency / sovereignty**:
  - Unverified (2026-10-18): AWS European Sovereign Cloud: Independent EU cloud infrastructure, stringent data-residency requirements, EU-only operations. Recommended for organisations subject to EU regulations.
  - Deploy with Terraform + Control Tower + CloudTrail for centralised governance and audit logs.

## Module ecosystem
- `terraform-aws-modules/<name>/aws` (e.g. `terraform-aws-modules/vpc/aws`, `.../eks/aws`, `.../rds/aws`): Community-maintained, de-facto standard. NOT official HashiCorp modules.
  - Modules exist for VPC, EKS, EC2 instances and RDS; resolve current module majors at research time.
  - Maintained by community (lead: Anton Babenko).
- Unverified (2026-10-18): No official provider-maintained modules in v6; rely on community or validated-design modules.

## Doc sources
- **Canonical provider docs**: `https://registry.terraform.io/providers/hashicorp/aws/latest/docs`
- **Provider guides**:
  - v6 upgrade: `https://registry.terraform.io/providers/hashicorp/aws/latest/docs/guides/version-6-upgrade`
  - Enhanced region support: `https://registry.terraform.io/providers/hashicorp/aws/latest/docs/guides/enhanced-region-support`
  - Resource tagging: `https://registry.terraform.io/providers/hashicorp/aws/latest/docs/guides/resource-tagging`
  - Tag policy compliance: `https://registry.terraform.io/providers/hashicorp/aws/latest/docs/guides/tag-policy-compliance`
- **HashiCorp Developer tutorials**:
  - Provider versioning: `https://developer.hashicorp.com/terraform/tutorials/configuration-language/provider-versioning`
  - Default tags: `https://developer.hashicorp.com/terraform/tutorials/aws/aws-default-tags`
- `docs.aws.amazon.com` (incl. the prescriptive-guidance Terraform best-practices guide)
