---
description: "Authoring: OCI with latest-stable-and-pin pinning writes a pinned, documented, modular root"
tags: [authoring, capability, oci]
runs: 3
model: claude-sonnet-5-5
max_turns: 25
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write]
---

Use the terraform-multicloud-orchestrator skill for this request.

Clouds: OCI. Pinning: latest-stable-and-pin.

Plan an OCI compartment and VCN layout with provider version pins and no apply step.

Write the Terraform files into the current working directory now (main.tf, variables.tf, outputs.tf and versions.tf at the root; put shared building blocks under modules/). Do not wait for review and do not run any commands.
