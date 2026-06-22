# Identity churn — keeping addresses stable

Churn = Terraform plans a destroy+create (or a wholesale address change) when you intended an in-place update. Two causes: address instability from refactors, and ForceNew attributes.

## Address stability
- A resource's address (`module.x.aws_db_instance.this`) is its identity in state. Change the address and Terraform sees a delete + create unless you tell it the resource moved.
- `count` indexes by position: removing the middle element renumbers everything after it, churning all of them. **Prefer `for_each`** (keyed by a stable string) for sets of similar resources so additions/removals touch only the affected key.
- When you rename or restructure, add a `moved` block (see `migration-playbooks.md`) so the change is a no-op in the plan.

## ForceNew attributes
- Some attributes cannot change in place; the provider marks them ForceNew and the plan shows `# forces replacement`. This is provider- and resource-specific and occasionally changes between provider versions.
- Before changing any attribute on a stateful or expensive resource, check whether it is ForceNew in the **current** provider version (registry docs) and consult the cloud's ForceNew table in `references/<cloud>.md`.

## Procedure
1. Read the plan for `# forces replacement` / `-/+`.
2. If the replacement is unintended, locate the triggering attribute; revert it, or use `moved`/`import` to preserve identity.
3. For ForceNew on an expensive resource, apply the stop-and-confirm gate before any handoff.

## Gotchas
- Avoid: passing `""` instead of `null` to an optional argument — this can force replacement on some providers (notably AWS).
- Avoid: reordering `count` elements, as it renumbers them; reordering `for_each` keys is safe.
- Prefer: human-stable keys (names, not indexes).
