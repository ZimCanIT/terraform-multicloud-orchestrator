---
description: "Authoring: GCP with pessimistic-patch pinning writes a pinned, documented, modular root"
tags: [authoring, capability, gcp]
runs: 3
model: claude-sonnet-5-5
max_turns: 25
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write]
---

Use the terraform-multicloud-orchestrator skill for this request.

Clouds: GCP. Pinning: pessimistic-patch.

Generate HCL for a GCP project network with labels, firewall rules, and least-privilege service accounts.

Write the Terraform files into the current working directory now (main.tf, variables.tf, outputs.tf and versions.tf at the root; put shared building blocks under modules/). Do not wait for review and do not run any commands.
