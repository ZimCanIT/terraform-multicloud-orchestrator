---
description: "Trigger positive: eval_queries.json train-05"
tags: [gate, capability, trigger]
runs: 3
model: claude-sonnet-5-5
max_turns: 2
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
disallowed_tools: [Write]
---

Plan an OCI compartment and VCN layout with provider version pins and no apply step.
