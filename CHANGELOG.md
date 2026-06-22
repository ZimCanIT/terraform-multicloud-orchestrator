# Changelog

All notable changes are documented here. This project has not been published yet; the first release will be `0.0.1`.

## [0.0.1] — Unreleased

- Plan-only, failure-mode-first Terraform orchestrator for AWS, Azure, GCP and OCI, with per-cloud reference files loaded on demand.
- Ask-once session setup, provider-pinning strategies, response contract, and stop-and-confirm replacement gate.
- `allowed-tools` scoped to plan-only `terraform`/`tofu` subcommands; optional `deny` rules documented for hard enforcement.
- Packaged for Claude Code (`.claude-plugin/`) and Codex (`.codex-plugin/` plus `.agents/plugins/marketplace.json`), and as a portable Agent Skill.
- Trigger eval set, output templates, and a reusable plan-only validation script.
- Refreshed the AWS, Azure, GCP and OCI reference files against mid-2026 provider releases (aws v6.51, azurerm v4.77, google v7.37, oci v8.19), with adversarial live verification of version, ForceNew and security claims.
- Strict plan-only safety: no `apply`, `destroy`, or `-auto-approve`.
