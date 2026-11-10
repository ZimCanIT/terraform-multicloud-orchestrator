# Hand-off

## What changed

<Files created or changed, as a short tree or list, with one line each on what and why.>

## Decisions

- <Decision, the reason for it, and what was rejected.>

## Assumptions

- Provider versions: <from `.terraform.lock.hcl` | resolved from the registry on DATE>
- <Inputs relied on, the naming convention, policy-managed tag keys, anything the user has not confirmed.>

## Standard

- Rules not met: <none | rule ID and reason>
- Secrets in state: <none | which, and why it could not be avoided>

## Validation

- Static checks: <commands run and their result | not run, and why>
- Plan kind: <state-backed | none>
- Command: <exact plan command run, or "none">
- Add / change / destroy: <counts>
- Deletions and replacements: <none | "Replacement check NOT performed" | address, type, action and reason for each>
- Not checked here: <lint, static scanner, module tests, Azure Policy: what the user or the pipeline still has to run>

## Rollback

<Only when state is affected: how to undo the moves, imports, removals or upgrade.>

## Next step

<One of: "Code is staged and validated. Manual `terraform apply tfplan` is required." | "Stopped: the plan deletes or replaces a resource on the stop list; awaiting confirmation." | "Replacement check NOT performed; run the state-backed plan before apply." Use `tofu apply` for OpenTofu.>
