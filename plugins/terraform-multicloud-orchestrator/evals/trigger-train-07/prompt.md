---
description: "Trigger negative: eval_queries.json train-07"
tags: [gate, capability, trigger]
runs: 3
model: claude-sonnet-5-5
max_turns: 2
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
disallowed_tools: [Write]
---

Write Kubernetes manifests for a Deployment and Service.
