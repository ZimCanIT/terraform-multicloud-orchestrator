# Changelog

All notable changes are documented here. Versions follow [Semantic Versioning](https://semver.org/); releases are generated automatically by [release-please](https://github.com/googleapis/release-please) from [Conventional Commits](https://www.conventionalcommits.org/).

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
