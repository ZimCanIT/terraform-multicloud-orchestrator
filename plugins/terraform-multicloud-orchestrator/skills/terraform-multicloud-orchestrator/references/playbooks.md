# Playbooks

The steps and the finish line for each common kind of request. `SKILL.md` §4 is the general workflow; a playbook says what it means for one task. Every step honours the guardrails in `SKILL.md` §2: the agent runs the permitted commands, runs the skill's own scripts only after the user approves the command, and names every other command for the user to run.

## A new module

Load `module-design.md` and `hcl-standards.md`, plus the reference for what the module builds (`secure-baseline.md`, `networking.md`, `identity-and-secrets.md`).

1. Read the repository. Is there already a module for this? Note the conventions and the pinned provider version.
2. Write the design note: what the module owns (MD1), its inputs and outputs (MD2, MD5), and which settings are decisions the module makes, not variables.
3. Check every argument against the registry page for the pinned version (AZ8).
4. Write `versions.tf` with minimums only, typed and validated `variables.tf`, `main.tf`, `outputs.tf`, a `README.md` and plan-mode tests. The modules under `assets/reference-stack/modules/` show the shape.
5. Call the module from a stack or an example, so that it can be validated.
6. Review it against `assets/review-checklist.md`, with the audit script if the user allows it.
7. Run the static checks and hand off.

Done when `validate` and `fmt -check` pass, the audit is clean or each finding is explained, tests exist, and nothing inside the module looks up its surroundings.

## A change to an existing stack

Load `secure-baseline.md` for a new resource type and `azurerm-provider.md` for what forces a replacement.

1. Read the stack and its lock file. The locked provider version is the one the change must satisfy.
2. Decide where the change belongs. A resource with another owner or lifecycle goes in another stack (ST2).
3. Write the change in the style of the code around it (`SKILL.md` §1).
4. Ask what the change does to resources that already exist: a changed `name`, a changed `for_each` key or a moved block is a replacement unless a `moved` block says otherwise (HC4).
5. Run the static checks. Run the state-backed plan if credentials exist; otherwise ask the user to run it and paste the output.
6. Read the plan for deletions and replacements, and apply the stop-and-confirm rule. `scripts/plan_review.py` names the attribute that forces each replacement, which is where the fix starts.

Done when the plan shows the intended changes and nothing else, and every deletion or replacement has been confirmed by the user.

## A new stack or environment

Load `state-and-environments.md`, `module-design.md` and `naming-and-tagging.md`.

1. Decide the state boundary first: which layer this is, and what must not share its state (ST2).
2. Write the backend block with Entra ID authentication, and a backend file and an input file for each environment (ST3).
3. Write the provider block with the subscription as an input, the pins in `versions.tf`, and names and tags in `locals.tf`.
4. Compose modules. Take what other stacks own as inputs (ST4).
5. Add `terraform.tfvars.example`. Offer `assets/pipeline/terraform.yml` if the repository has no pipeline.

Done when a second environment needs only a new input file and a new backend file.

## A review or an audit

Load `assets/review-checklist.md`, and other references as the findings need them.

1. State the audit command and wait for approval: `python3 <skill directory>/scripts/tf_audit.py <directory>`.
2. Confirm each finding in the code. The script reads text: it can be wrong about a value that is set elsewhere, and it says nothing about values that are expressions.
3. Walk the checklist for what a script cannot see: state and module boundaries, interfaces, naming, what the code is for. The script has no checks for MD1, MD4, MD6, HC3 and HC4.
4. Report as `SKILL.md` §6 describes. Do not rewrite the code, and do not add suppressions.

Done when every finding has a rule ID, a location, a consequence and a fix, and the report says what was not checked.

## Adopting existing resources

Load `adopt-and-refactor.md` and `naming-and-tagging.md`.

1. Decide which stack and module the resources belong to before writing anything.
2. Write the resource blocks to the standard, then the `import` blocks.
3. Plan, or ask the user to plan. Work the plan down to imports only by making the code match what is deployed.
4. Stop if the plan replaces anything. A replacement during adoption is never acceptable.

Done when the plan reads "N to import, 0 to add, 0 to change, 0 to destroy".

## Upgrading azurerm to 5

Load `azurerm-provider.md` and `adopt-and-refactor.md`.

1. Audit for what breaks. State the command and wait for approval: `python3 <skill directory>/scripts/tf_audit.py --rules AZ8 <directory>`. It lists removed resource types, removed and renamed arguments, and values that are no longer accepted.
2. On the current major, move to its last release and clear every deprecation warning. The plan must be clean before the upgrade starts.
3. In a pull request that contains nothing else, raise the constraint and fix the names. Read the registry page for each one; `assets/azurerm-5-changes.json` gives the new name where there is one.
4. Handle the provider-level changes: resource provider registration, and location validation at plan time (`azurerm-provider.md`).
5. The user runs `terraform init -upgrade`. Then plan. The target is no changes; a proposed change is a missed rename or a changed default, so set the old value explicitly.
6. One stack at a time, least critical first.

Done when the plan shows no changes on the new major and the audit reports no AZ8 finding.

## A failed plan or apply

Load `troubleshooting.md`.

1. Get the whole error: the code, the message and the resource address. Ask for it if the user pasted a fragment.
2. Find the row in `troubleshooting.md`, then confirm the cause in the code or with a permitted command.
3. Fix it in code, or hand the user the exact command when the fix is not in code.
4. Plan again and read the result.

Done when the cause is named, and the fix neither widens access nor removes a guard.
