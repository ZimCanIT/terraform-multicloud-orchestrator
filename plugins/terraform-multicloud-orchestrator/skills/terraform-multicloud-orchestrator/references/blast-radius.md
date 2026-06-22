# Blast radius — limiting what one apply can break

Blast radius = the set of resources a single `apply` can change or destroy. Smaller is safer.

## State boundaries
- One state file = one failure and permission domain. A monolithic state holding prod and non-prod means a bad plan can take out both.
- Split state by environment (prod/stage/dev) and by lifecycle/ownership (networking vs app vs data). Use separate root modules and backends.
- Hub-and-spoke / landing-zone topologies map naturally onto separate states per spoke.

## Limiting impact
- Keep long-lived, expensive resources (databases, gateways, clusters) in their own state, separate from fast-moving app config, so routine changes never put them at risk.
- Use `-target` only for break-glass, never as a routine workflow.
- Read the cloud's expensive-recreate list in `references/<cloud>.md` and treat any planned replacement of those as stop-and-confirm.

## Procedure
1. Before a wide change, check how many resources the plan touches and whether prod and non-prod share the state.
2. If the stack is monolithic, propose a split (see `migration-playbooks.md` → state split) rather than applying broadly.

## Gotchas
- Avoid: shared prod/non-prod state.
- Avoid: local state for teams or production.
- Prefer: remote state with locking; one concern per state.
