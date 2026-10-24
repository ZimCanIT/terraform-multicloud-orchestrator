---
description: "Trigger positive: eval_queries.json validation-01"
tags: [gate, capability, trigger]
runs: 3
model: claude-sonnet-5-5
max_turns: 2
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
disallowed_tools: [Write]
---

Add Terraform for an Azure storage account with private endpoints, encryption, and policy-safe defaults.
