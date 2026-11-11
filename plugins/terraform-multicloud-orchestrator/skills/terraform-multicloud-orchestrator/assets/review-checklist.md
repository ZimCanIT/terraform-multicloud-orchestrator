# Review checklist

Walk this list over your own output before showing it (`SKILL.md` §4, step 5) and over a user's code when asked for a review (§6). Rule IDs refer to `SKILL.md` §3. Report only what fails.

## Blockers

Stop and fix, or report first.

- [ ] No secret in code, in a variable default, in a committed `.tfvars` file, in an output, in a tag or in a command line (AZ2).
- [ ] Production and non-production do not share a state. State is remote and reached with Entra ID, not an access key (ST2).
- [ ] Nothing is public that the request did not ask to be public: public network access, public IPs, ports 22 and 3389, anonymous blob access, registry admin user or anonymous pull (AZ3).
- [ ] No resource on the stop list is deleted or replaced without the user's confirmation (`references/azurerm-provider.md`).
- [ ] No resource address changed without a `moved` block (HC4).
- [ ] No `apply`, `destroy`, `import` or state-changing command (`state mv`, `state rm`, `state push`, `force-unlock`) was run or proposed for pre-approval. `state list` is the only state subcommand permitted (`SKILL.md` §2).

## Structure and modules

- [ ] `provider` blocks and the backend are only in root modules; reusable modules state minimum provider versions (ST1).
- [ ] Environments differ by inputs, with no `terraform.workspace` conditionals and no copied code (ST3).
- [ ] Stacks exchange values through inputs or data sources in the root, not `terraform_remote_state` (ST4).
- [ ] Each module owns one capability with one lifecycle; none is a pass-through over one resource or over a registry module (MD1, MD6).
- [ ] Modules receive IDs; they do not look up their surroundings or create the resource group and network they use (MD2).
- [ ] Every variable has a type and a description; no `any`; collections are maps with stable keys; secrets are `sensitive` (MD3).
- [ ] Inputs that Azure would reject late have `validation`; assumptions between resources have a `precondition` (MD4).
- [ ] Outputs are IDs, names and connection facts, each with a description; no whole resource and no secret (MD5).

## Language

- [ ] Plural resources use `for_each` over a map whose keys are known at plan time; `count` appears only as a zero-or-one switch (HC1).
- [ ] No literal subscription, tenant or object ID, region, SKU, address range or name inside a resource (HC2).
- [ ] Names and tags are built once in `locals` (HC3).
- [ ] Data-holding resources have `prevent_destroy`, or the hand-off says that nothing stops Terraform from destroying them. A lock in the same configuration does not count. Every `ignore_changes` is narrow and commented (HC5).
- [ ] No provisioner, `null_resource` or `local-exec` calling `az` (HC6).
- [ ] Every `depends_on` covers a dependency Terraform cannot see and says why (HC7).
- [ ] Standard files, `snake_case`, `this` for the primary resource, block order, formatted, `terraform.tfvars.example` instead of `terraform.tfvars` (HC8).

## Azure

- [ ] Access uses managed identities and role assignments at the narrowest scope with a least-privilege built-in role; key and local authentication are off where the service allows (AZ1).
- [ ] Public network access is off, private endpoints have DNS, every subnet that supports one has a security group, outbound traffic has an explicit path (AZ3).
- [ ] TLS 1.2 or later, HTTPS only, host or infrastructure encryption where offered (AZ4).
- [ ] Zone redundancy where the SKU supports it; soft delete, purge protection and backups on data services (AZ5).
- [ ] Each resource that emits logs has a diagnostic setting to Log Analytics (AZ6).
- [ ] Every taggable resource takes the merged tags; policy-managed tag keys are in `ignore_changes` (AZ7).

## Versions

- [ ] Every argument was checked against the registry page for the pinned provider version, including arguments copied from this skill (AZ8).
- [ ] No deprecated argument or removed resource type remains.
- [ ] Runtime, providers and modules are pinned as `SKILL.md` §7 says, and `.terraform.lock.hcl` is committed.

## Validation

- [ ] `terraform validate` and `terraform fmt -check -recursive` pass, or the hand-off says they were not run.
- [ ] A state-backed plan was read for deletions and replacements, or the hand-off says "Replacement check NOT performed".
- [ ] The audit script reports no blocker and no major finding, or the hand-off explains each one that remains. No suppression was added without the user's agreement.
- [ ] The hand-off names what was not checked here: lint, scanner, tests, Azure Policy.
