---
description: "Trigger positive: eval_queries.json train-04"
tags: [gate, capability, trigger]
runs: 3
model: claude-sonnet-5-5
max_turns: 2
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
disallowed_tools: [Write]
---

Generate HCL for a GCP project network with labels, firewall rules, and least-privilege service accounts.
