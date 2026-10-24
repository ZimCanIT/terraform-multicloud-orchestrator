---
description: "Capability: a bare Terraform request gets the cloud and pinning questions before any HCL"
tags: [gate, capability, session-setup]
runs: 3
model: claude-sonnet-5-5
max_turns: 6
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
disallowed_tools: [Write]
---

Use the terraform-multicloud-orchestrator skill for this request.

Write Terraform for a VPC.
