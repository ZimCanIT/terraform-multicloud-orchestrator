# Final Report

## Modular Map
<Tree of files created or updated.>

## Plan Summary
- Plan kind: <static only | state-backed>
- Command: <exact plan command run, or "none">
- Add: <count>
- Change: <count>
- Destroy: <count>
- Replacements: <none | "Replacement check NOT performed" | address, type, action and reason for each>
- Gate: <clear | stopped, awaiting confirmation>

## Output Contract
- Assumptions and version floor: <provider versions, naming convention, inputs relied on>
- Failure modes addressed: <identity churn|blast radius|state migration|compliance gates|none>
- Tradeoffs: <chosen remediation and alternatives rejected>
- Rollback / recovery: <state and code recovery path>

## Handoff
<One of: "Code is staged and validated. Manual `terraform apply tfplan` is required." | "Stopped at the gate; awaiting confirmation." | "Replacement check NOT performed; run the state-backed plan before apply." Use `tofu apply` for OpenTofu.>
