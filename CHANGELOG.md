# Changelog

All notable changes are documented here. Versions follow [Semantic Versioning](https://semver.org/); releases are generated automatically by [release-please](https://github.com/googleapis/release-please) from [Conventional Commits](https://www.conventionalcommits.org/).

## [0.1.0](https://github.com/ZimCanIT/terraform-multicloud-orchestrator/compare/terraform-multicloud-orchestrator-v0.0.2...terraform-multicloud-orchestrator-v0.1.0) (2026-10-17)


### ⚠ BREAKING CHANGES

* the skill no longer pre-approves `az` commands or offers an Azure CLI mode. It asks the user to paste `az account show` instead. Allow specific `az` commands in your own settings if you want them run for you.
* module pattern and comment verbosity are no longer session settings, and generated comments are no longer forced into British English. Put those preferences in your own CLAUDE.md or AGENTS.md.
* the skill no longer names a primary or advisor model. Configure model, effort and advisor in your own settings.
* the skill no longer runs a security pass or emits a Security Verdict. The final report has four sections instead of five.

### Features

* move Azure-only logic out of the skill spine ([bc7746a](https://github.com/ZimCanIT/terraform-multicloud-orchestrator/commit/bc7746a7854cbd246d0df7267c5a337e38c55451))
* remove model pinning and advisor invocations ([cae45ab](https://github.com/ZimCanIT/terraform-multicloud-orchestrator/commit/cae45abcad95608ecbaf52d2a0b7253b877de3af))
* remove security analysis from the skill workflow ([f162ec1](https://github.com/ZimCanIT/terraform-multicloud-orchestrator/commit/f162ec1057a2cba602ee234bc3ac3aa73f1ee67a))
* slim session setup to cloud and provider pinning ([14ef9ea](https://github.com/ZimCanIT/terraform-multicloud-orchestrator/commit/14ef9ea92d72dc5907a899ed2cac53946592faeb))


### Bug Fixes

* add EKS and OKE clusters to the stop-and-confirm lists ([8969505](https://github.com/ZimCanIT/terraform-multicloud-orchestrator/commit/8969505e5b89c7cad893546b6fe775f7bc84d797))
* correct outdated provider majors and moved-block limits ([3693928](https://github.com/ZimCanIT/terraform-multicloud-orchestrator/commit/36939284fc29b3260748b9d1f1a433d52916ca54))
* correct the plan-only enforcement guidance ([03ff968](https://github.com/ZimCanIT/terraform-multicloud-orchestrator/commit/03ff968b9f92f52969004228bdf2a61b46e79ac2))
* keep release version fields in sync with release-please ([8a6fdf8](https://github.com/ZimCanIT/terraform-multicloud-orchestrator/commit/8a6fdf8243385de339ebc598cf498586989dd0f3))
* remove dated and version-pinned facts from the cloud references ([a767ac4](https://github.com/ZimCanIT/terraform-multicloud-orchestrator/commit/a767ac4cc58a047e60eaef98ccb65e97fcb8d130))
* split plan-only validation into static checks and a state-backed plan ([fb9e815](https://github.com/ZimCanIT/terraform-multicloud-orchestrator/commit/fb9e81553523b93c364acd95a3de5b1a802c6c6a))

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
