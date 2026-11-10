# HCL standards

How the code itself should read. Rule IDs refer to `SKILL.md` §3.

## Variables (MD3, MD4)

Type every input. Group related settings in one object, use `optional()` for defaults, and key collections by a stable name so that they can feed `for_each`.

```hcl
variable "subnets" {
  description = "Subnets to create, keyed by a short stable name. The key becomes part of the resource address."
  type = map(object({
    address_prefixes                  = list(string)
    private_endpoint_network_policies = optional(string, "Enabled")
    delegation = optional(object({
      name    = string
      service = string
      actions = optional(list(string), [])
    }))
  }))
  nullable = false

  validation {
    condition = alltrue(flatten([
      for subnet in var.subnets : [for prefix in subnet.address_prefixes : can(cidrhost(prefix, 0))]
    ]))
    error_message = "Every address prefix must be a valid CIDR range, for example 10.20.1.0/24."
  }
}

variable "environment" {
  description = "Deployment environment. Used in names and tags."
  type        = string

  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "environment must be one of: dev, test, prod."
  }
}
```

- Give a default only when it is safe in every environment. A region, an address space and a name have no default.
- Set `nullable = false` unless null means something, as it does for an optional feature object (see `module-design.md`).
- Name booleans `<thing>_enabled`. Avoid negatives such as `disable_x`.
- Mark secrets `sensitive = true`. On Terraform 1.10 or later, add `ephemeral = true` to an input that must never reach state or a plan file, and pass it only to write-only arguments.
- Validate what Azure would otherwise reject late: name patterns and lengths, CIDR ranges, SKU names, allowed regions. A validation may refer to other variables on Terraform 1.9 or later.
- Do not use `any`, and do not hide a missing required key with `lookup(map, key, default)` or `try()`. Use `try()` only for structure that is truly optional; prefer `optional()` in the type.

## Locals (HC2, HC3)

Use `locals` for names, tags and values derived from several inputs. Do not create a local that only renames a variable.

```hcl
locals {
  name_suffix = join("-", [var.workload, var.environment, var.location_short, var.instance])

  tags = merge(var.tags, {
    workload    = var.workload
    environment = var.environment
    managed_by  = "terraform"
  })
}
```

Never put `timestamp()` or another value that changes on every run into a tag or a name: it produces a diff on every plan.

## `for_each` and `count` (HC1)

```hcl
resource "azurerm_subnet" "this" {
  for_each = var.subnets

  name                 = "snet-${each.key}-${local.name_suffix}"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = each.value.address_prefixes
}

# A zero-or-one switch is the only use for count.
resource "azurerm_management_lock" "this" {
  count = var.lock_enabled ? 1 : 0

  name       = "lock-${local.name_suffix}"
  scope      = azurerm_virtual_network.this.id
  lock_level = "CanNotDelete"
}
```

- `count = length(var.names)` indexes by position, so removing one element renumbers and replaces every later one. Use a map.
- Keys must be known at plan time. `for_each = toset(azurerm_subnet.this[*].id)` fails with "known only after apply"; key by the input instead and read the ID from `each.value`.
- Turn a list of objects into a map with a stable unique key: `{ for rule in var.rules : rule.name => rule }`.
- For nested collections, `flatten` into a list of objects in `locals`, then build a map with a composite key such as `"${vnet_key}/${subnet_key}"`.

## `dynamic` blocks

Use `dynamic` only for a nested block that is optional or repeated by input. For an optional single block:

```hcl
dynamic "delegation" {
  for_each = each.value.delegation == null ? [] : [each.value.delegation]

  content {
    name = delegation.value.name

    service_delegation {
      name    = delegation.value.service
      actions = delegation.value.actions
    }
  }
}
```

Do not use `dynamic` to make a fixed structure configurable "just in case".

## Lifecycle, conditions and checks (MD4, HC5)

```hcl
resource "azurerm_key_vault" "this" {
  # ...

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = var.environment != "prod" || var.purge_protection_enabled
      error_message = "Production key vaults must have purge protection."
    }

    # Azure Policy sets these tag keys after deployment.
    ignore_changes = [tags["cost_centre"], tags["owner"]]
  }
}

check "key_vault_private" {
  assert {
    condition     = !azurerm_key_vault.this.public_network_access_enabled
    error_message = "The key vault accepts traffic from public networks."
  }
}
```

- `prevent_destroy` takes a literal, so a shared module cannot switch it per environment. Put it in roots and modules that are never torn down. Where the same module also serves disposable environments, protect production with a management lock behind a variable instead.
- `precondition` and `postcondition` stop the run. A `check` block only warns, which suits conditions you want to see after apply without blocking it.
- `ignore_changes = all` is never acceptable. List attributes, and say in a comment who else changes them.
- Use `create_before_destroy = true` where a replacement would otherwise cause an outage and the name allows two copies to exist at once.

## Dependencies (HC7)

Terraform orders resources by the references between them. Add `depends_on` only when the dependency is real but invisible in the arguments. The common Azure case is a role assignment that must exist before a data-plane operation:

```hcl
resource "azurerm_key_vault_secret" "this" {
  # ...

  # The deploying identity needs its data-plane role before it can write a secret.
  depends_on = [azurerm_role_assignment.deployer_secrets_officer]
}
```

Do not put `depends_on` on a module "to be safe": every data source inside it is then read during apply, and values that were known at plan time become unknown.

## Style (HC8)

- Order inside a block: `count` or `for_each`, a blank line, arguments, nested blocks, then `lifecycle`, then `depends_on`. The examples in this skill keep `tags` as the last argument before `lifecycle`; follow the repository's habit where it has one.
- Do not repeat the type in the name: `azurerm_virtual_network.hub`, not `azurerm_virtual_network.hub_vnet`. A module's single primary resource is `this`.
- Write `var.name`, not `"${var.name}"`.
- Use `#` comments, and only where the reason is not obvious from the code.
- Bare `terraform fmt` rewrites files and is not a permitted command for the agent (`SKILL.md` §2). Write code that is already formatted, check it with `terraform fmt -check -recursive`, and ask the user to run `terraform fmt -recursive` if the check reports a file.

## Patterns to remove on sight

| Pattern | Why it hurts | Replace with |
|---|---|---|
| `count` over a list of names | Removing one item replaces the rest | `for_each` over a map |
| A literal subscription, tenant or object ID | Wrong in every other environment; leaks tenant layout | Variables and `data.azurerm_client_config` |
| `null_resource` or `local-exec` running `az` | Invisible to plan, not idempotent, needs the CLI on every runner | A native resource or `azapi` |
| A data source reading a resource this configuration creates | Hides the dependency and reads stale values | A direct reference |
| `ignore_changes = all` | Terraform stops managing the resource | A narrow list with a comment |
| A secret in a variable default or committed `.tfvars` | It is in version control for good | Entra ID authentication, or a Key Vault reference |
| An output that returns a whole resource | Callers couple to every attribute | Named outputs for what callers need |
| Nested ternaries choosing between environments | Environments drift inside one file | Inputs per environment (ST3) |
