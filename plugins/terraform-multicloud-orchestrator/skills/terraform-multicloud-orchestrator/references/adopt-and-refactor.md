# Adopt and refactor

Bringing existing Azure resources under Terraform, restructuring code without replacing anything, splitting state, and upgrading the provider (HC4). Every change here shows in a plan before it happens. The agent writes the blocks and reads the plan; the user runs anything that changes state (`SKILL.md` §2).

## Adopt existing resources

1. **Decide where they belong** before writing anything: which stack and state (ST2), which module.
2. **Write the resource blocks to the standard**, with variables, names from `locals` and the module's interface. Generated configuration is raw material, not the result.
3. **Add `import` blocks** next to the resources:

   ```hcl
   import {
     to = azurerm_resource_group.this
     id = "/subscriptions/${var.subscription_id}/resourceGroups/rg-orders-prod-uks-001"
   }

   import {
     for_each = var.subnets

     to = azurerm_subnet.this[each.key]
     id = "${azurerm_virtual_network.this.id}/subnets/snet-${each.key}-${local.name_suffix}"
   }
   ```

   Expressions in `id` need Terraform 1.6 and `for_each` needs 1.7. To import into a module, address it in full: `to = module.network.azurerm_virtual_network.this`.
4. **Plan, and work the plan down to imports only.** The target is "N to import, 0 to add, 0 to change, 0 to destroy". For each proposed change, either make the code match what is deployed, or leave the difference for a separate, deliberate pull request. Never accept a replacement while adopting.
5. After the user has applied, the `import` blocks can stay for a release as a record, then be removed.

Things that go wrong:

- **ID casing.** The provider parses IDs strictly. Use the form shown in the "Import" section of the resource's registry page, for example `resourceGroups`, not the lower-case form some tools print.
- **Composite IDs.** A diagnostic setting is `<resource id>|<setting name>`; a Key Vault secret is its versioned URL; associations and role assignments have their own forms. Read the "Import" section each time.
- **Defaults that differ from reality.** An argument you leave out takes the provider's default, which may not be what is deployed. Set it explicitly to the deployed value.
- **Secrets.** Imported resources bring their sensitive attributes into state.

Tools the user can run to get raw material: `aztfexport` (Azure Export for Terraform) for a resource group or a query, and `terraform plan -generate-config-out=generated.tf` for resources that have `import` blocks. Both write code with literal IDs and no structure. Refactor it to the standard before it is committed.

## Rename and restructure with `moved`

```hcl
# Into a module
moved {
  from = azurerm_storage_account.main
  to   = module.storage.azurerm_storage_account.this
}

# count to for_each: one block per instance
moved {
  from = azurerm_subnet.this[0]
  to   = azurerm_subnet.this["app"]
}
```

- The plan must report each one as moved, with nothing to add or destroy.
- `moved` works inside one state only.
- Changing the resource type with `moved` works only where the provider documents support for that pair (Terraform 1.8 or later). Otherwise use `removed` and `import`.
- In a shared module, keep `moved` blocks until every consumer has applied them. Removing them early turns the rename back into a destroy and create for whoever is behind.
- Renaming the Azure resource itself is different: `name` forces a replacement (`azurerm-provider.md`). A `moved` block changes the Terraform address, not the Azure name.

## Stop managing a resource without deleting it

```hcl
removed {
  from = azurerm_log_analytics_workspace.legacy

  lifecycle {
    destroy = false
  }
}
```

The plan must say the resource will no longer be managed, not that it will be destroyed. Needs Terraform 1.7.

## Move resources between states

There is no `moved` across states. Use two pull requests:

1. In the source stack, replace the resource with a `removed` block with `destroy = false`. The user applies it. The resource is now unmanaged but untouched.
2. In the destination stack, add the resource and an `import` block. The plan shows an import and no change. The user applies it.

Do it in that order so that two states never manage one resource. Freeze other changes to both stacks while the move is in flight, and move related resources together (a network with its subnets and associations).

`terraform state mv` and `terraform state rm` do the same job by hand, without a plan to review. Prefer the blocks; the commands are for the user and only when blocks cannot express the move.

## Before any refactor: what would be replaced

- A changed address without a `moved` block: a renamed resource, a renamed module, a changed `for_each` key, `count` converted to `for_each`.
- A changed `name`, `location` or `resource_group_name`. Azure can move a resource between resource groups, but Terraform then sees a new ID: use `removed` and `import` after the Azure move.
- Any attribute in the replacement list in `azurerm-provider.md`.

Read every line marked `# forces replacement`, and apply the stop-and-confirm rule.

## Upgrade the provider by a major version

1. On the current major, move to its last release and clear every deprecation warning. Plan must be clean before you start.
2. Read the upgrade guide for the target major in the registry's guides. List the renamed arguments, removed resources and changed defaults that this repository uses. For the move to `azurerm` 5, `scripts/tf_audit.py` finds the removed resource types and arguments for you (rule AZ8); changed defaults still need the guide.
3. In a pull request that contains nothing else: raise the constraint to the newest release of the target major, and fix the code. The user runs `terraform init -upgrade`, which rewrites the lock file.
4. Plan. The target is no changes. Every proposed change is either a rename you missed or a changed default: set the old value explicitly to keep behaviour, and change behaviour later in its own pull request.
5. One major at a time, one stack at a time, least critical stack first. Reusable modules widen their minimum only after every root that uses them has moved.

Renames to expect are listed in `azurerm-provider.md`.
