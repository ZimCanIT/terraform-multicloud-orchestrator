---
description: "Authoring: Azure with exact pinning writes a pinned, documented, modular root"
tags: [authoring, capability, azure]
runs: 3
model: claude-sonnet-5-5
max_turns: 25
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write]
---

Use the terraform-multicloud-orchestrator skill for this request.

Clouds: Azure. Pinning: exact.

Add Terraform for an Azure storage account with private endpoints, encryption, and policy-safe defaults.

Write the Terraform files into the current working directory now (main.tf, variables.tf, outputs.tf and versions.tf at the root; put shared building blocks under modules/). Do not wait for review and do not run any commands.
