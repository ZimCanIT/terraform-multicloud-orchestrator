# Changelog

All notable changes are documented here. Versions follow [Semantic Versioning](https://semver.org/); releases are generated automatically by [release-please](https://github.com/googleapis/release-please) from [Conventional Commits](https://www.conventionalcommits.org/).

## [0.0.2](https://github.com/ZimCanIT/terraform-multicloud-orchestrator/compare/terraform-multicloud-orchestrator-v0.0.1...terraform-multicloud-orchestrator-v0.0.2) (2026-06-22)


### Features

* add terraform-multicloud-orchestrator skill at v0.0.1 ([0fba665](https://github.com/ZimCanIT/terraform-multicloud-orchestrator/commit/0fba66589a7de5a212b38a6db7c6e6a32cad4ab8))
* add terraform-multicloud-orchestrator skill at v0.0.1 ([64977ad](https://github.com/ZimCanIT/terraform-multicloud-orchestrator/commit/64977ad7c3ccd6da5b813eed45f8b0beaa4b6b4f))


### Bug Fixes

* correct release-please type and clear manual changelog for 0.0.1 ([82d821c](https://github.com/ZimCanIT/terraform-multicloud-orchestrator/commit/82d821c378ffd879e88034b15f7a38187032d5e7))
* correct release-please type and clear manual changelog for 0.0.1 ([f66a2d1](https://github.com/ZimCanIT/terraform-multicloud-orchestrator/commit/f66a2d116f13e59958730bc7c64e607ef8e29873))
* disable MD012 in markdownlint to handle CRLF blank line counting ([4043296](https://github.com/ZimCanIT/terraform-multicloud-orchestrator/commit/4043296ea8885e6b21fe992f8bfb6d7d263b8e11))
* disable MD012 in markdownlint to handle CRLF blank line counting ([279517e](https://github.com/ZimCanIT/terraform-multicloud-orchestrator/commit/279517e2b5b77876256d10b22de3f341febc64b3))

## 0.0.1 (2026-06-22)

### Features

* Plan-only, failure-mode-first Terraform orchestrator for AWS, Azure, GCP and OCI with per-cloud reference files loaded on demand.
* Ask-once session setup, provider-pinning strategies, response contract, and stop-and-confirm replacement gate.
* Read-only Azure CLI command pool with `azure_cli_mode` config field; tag drift suppression via `lifecycle { ignore_changes }` at generation time.
* Comment verbosity control (`verbose` / `standard` / `none`) auto-set from session mode.
* Module shape pinning (`composite` / `resource` / `company-standard`) with HashiCorp style enforcement.
* Model architecture pinned: Sonnet 4.8 low effort as primary, Opus 4.8 as advisor with fan-out for parallel architectural decisions.
* `allowed-tools` scoped to plan-only `terraform` / `tofu` subcommands; `deny` rules documented for hard enforcement.
* Packaged for Claude Code (`.claude-plugin/`), Codex (`.codex-plugin/` and `.agents/plugins/marketplace.json`), and as a portable Agent Skill.
* Trigger eval set, output templates, and a reusable plan-only validation script.
* Refreshed AWS, Azure, GCP and OCI reference files against mid-2026 provider releases (aws v6.51, azurerm v4.77, google v7.37, oci v8.19) with adversarial live verification.
* CI: pre-commit hooks, skill frontmatter validation, and release-please scaffold.
