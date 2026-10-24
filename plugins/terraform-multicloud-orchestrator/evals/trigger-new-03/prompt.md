---
description: "Trigger negative: eval_queries.json new-03"
tags: [gate, capability, trigger]
runs: 3
model: claude-sonnet-5-5
max_turns: 2
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Skill]
disallowed_tools: [Write]
---

Write an AWS CDK stack in TypeScript that creates a VPC with two public and two private subnets.
