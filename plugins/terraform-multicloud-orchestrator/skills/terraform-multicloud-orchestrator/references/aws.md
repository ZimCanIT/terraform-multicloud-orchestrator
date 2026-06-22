# AWS — Terraform reference

Provider: `hashicorp/aws`. Read alongside the cloud-agnostic mechanism files.

## Provider & pinning
- Current major: **v6.x**. Verify the exact latest patch at research time.
- Pin versions using `required_providers` block and `.terraform.lock.hcl` dependency lock file. Use `~> 6.51.0` (pessimistic-patch) to fix major and minor; use `~> 6.51` (pessimistic-minor) to allow minor and patch to change; avoid deprecated `version` argument in provider blocks.
- Example: `required_providers { aws = { source = "hashicorp/aws", version = "~> 6.51.0" } }`.
- v6 introduced per-resource `region` argument (most resources accept a top-level `region`; global services — IAM, CloudFront, Route 53 — do not), removed OpsWorks / SimpleDB / Worklink, retyped launch-template booleans, and removed the `aws_eip` `vpc` argument (use `domain`).

## ForceNew traps (identity churn)
- **`aws_rds_cluster`**: `cluster_identifier`, `cluster_identifier_prefix`, `engine`, `db_subnet_group_name`, `snapshot_identifier` are ForceNew. Changes trigger full resource recreation and downtime.
- `aws_rds_cluster_instance`: `identifier`, `identifier_prefix`, `engine`, `db_subnet_group_name`, `cluster_identifier` all force replacement.
- `aws_db_instance`: `engine`, `availability_zone`, `character_set_name`, `snapshot_identifier` are ForceNew (`identifier` is modifiable).
- `aws_instance` — `ami`, `subnet_id`, certain `root_block_device` changes.
- `aws_s3_bucket` — `bucket` name; deleting a non-empty bucket needs `force_destroy = true`.
- Empty-string module defaults have historically forced replacement — pass `null`, not `""`.

## Expensive / slow-to-recreate — STOP and confirm
RDS instances / clusters, NAT Gateway, CloudFront distributions, Transit Gateway, ElastiCache, Redshift, OpenSearch / Elasticsearch domains.
- **RDS downtime**: `apply_immediately` causes a brief downtime reboot during modifications. Engine / snapshot changes force recreation (not in-place update). Use `create_before_destroy` lifecycle rule to minimise downtime during upgrades.
- S3 global endpoint support deprecated in v6 (removal planned for v7); `s3_us_east_1_regional_endpoint = "regional"` in us-east-1 requires migration.

## Provider major-upgrade notes (v5 to v6)
Upgrade one major at a time; read the provider upgrade guide on the registry first.
- **Breaking changes**:
  - `aws_kinesis_analytics_application` (SQL) is deprecated in v6 (removal planned) — AWS service EOL 27 January 2026. Migrate to `aws_kinesisanalyticsv2_application`.
  - `aws_simpledb_domain` removed entirely (AWS SDK v2 dropped support).
  - EC2 `user_data` now stored clear-text (no longer hashed). Remove embedded secrets before upgrading.
  - `cpu_core_count` / `cpu_threads_per_core` removed from `aws_instance` — use `cpu_options` block instead.
  - `data.aws_ami` with `most_recent = true` now requires explicit `owner` or `image_id` filter (was silent-fail warning in v5).
  - S3 global endpoint support deprecated; configure per-resource regional endpoints.
- **Recommendation**: Upgrade to latest v5 first, run `terraform plan` to identify issues, then upgrade to v6.
- **Previous migrations** (v4→v5): Split `aws_s3_bucket` into sub-resources (`aws_s3_bucket_versioning`, `aws_s3_bucket_server_side_encryption_configuration`, etc.) and changed `default_tags` precedence.

## Tagging
- Resource `tags` map plus provider-level `default_tags` (merged into every resource). Read the effective set via computed `tags_all`.
- **Trap**: Partial overlap between `default_tags` and a resource's own `tags` causes perpetual diff. Keep keys disjoint or manage centrally.
- **Mitigation**: Use `lifecycle.ignore_changes = [tags_all]` or `lifecycle.ignore_changes = ["tags.SpecificKey"]` to suppress external tag modifications.
- **Auto Scaling Group limitation**: `default_tags` cannot reach dynamically-created EC2 instances (AWS manages them). Use `aws_default_tags` data source as workaround.
- **Comparison**: External systems modifying tags will trigger perpetual diffs on `tags_all` — compare `tags` instead, or ignore `tags_all` entirely.

## Policy-as-code & sovereignty (compliance gates)
- **AWS Control Tower guardrails** (multi-account governance):
  - **Preventive controls** via Service Control Policies (SCPs): block unauthorised actions before provisioning (e.g., enforce data residency, prevent public access). SCPs only restrict — they never grant permissions.
  - **Detective controls** via AWS Config rules: audit and report post-provisioning violations.
  - **Proactive controls** via CloudFormation hooks: scan resources before provisioning, fail non-compliant templates.
- **HashiCorp Sentinel**: Policy-as-code enforcement in HCP Terraform for additional governance layers.
- **Data residency / sovereignty**:
  - AWS European Sovereign Cloud (2026): Independent EU cloud infrastructure, stringent data-residency requirements, EU-only operations. Recommended for organisations subject to EU regulations.
  - Deploy with Terraform + Control Tower + CloudTrail for centralised governance and audit logs.

## Module ecosystem
- `terraform-aws-modules/<name>/aws` (e.g. `terraform-aws-modules/vpc/aws`, `.../eks/aws`, `.../rds/aws`): Community-maintained, de-facto standard. NOT official HashiCorp modules.
  - **VPC module** v6.x, **EKS module** v21.x, **EC2-Instance module** v6.x, **RDS submodules** available; verify latest patches at research time.
  - Maintained by community (lead: Anton Babenko).
- **Official**: HashiCorp publishes Terraform Enterprise HVD module on AWS (April 17, 2026).
- No official provider-maintained modules in v6; rely on community or validated-design modules.

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
