# Naming and tagging

Azure names are mostly immutable: changing one replaces the resource. Get the convention right before the first apply, and build every name in one place (HC3).

## Convention

Follow the repository's convention if it has one. Otherwise use the Cloud Adoption Framework pattern:

```text
<type>-<workload>-<environment>-<region>-<instance>      rg-orders-prod-uks-001
<type><workload><environment><region><instance>          stordersproduks001   (where hyphens are not allowed)
```

Build names once:

```hcl
locals {
  location_short = {
    uksouth     = "uks"
    ukwest      = "ukw"
    northeurope = "neu"
    westeurope  = "weu"
  }[var.location]

  name_suffix = join("-", [var.workload, var.environment, local.location_short, var.instance])

  names = {
    resource_group  = "rg-${local.name_suffix}"
    virtual_network = "vnet-${local.name_suffix}"
    key_vault       = "kv-${local.name_suffix}"
    storage_account = "st${replace(local.name_suffix, "-", "")}"
  }
}
```

- Validate the parts so that the longest name still fits. For the pattern above, a workload of at most 8 lower-case letters or digits keeps a storage account name inside 24 characters. Do not truncate with `substr`: two long names can collapse into the same short one.
- For a globally unique name, add a short suffix that is stable and known at plan time, for example `substr(sha1("${var.subscription_id}/${local.name_suffix}"), 0, 4)`. A `random_string` works too, but its value lives only in state.
- A reusable module takes the finished name, or the parts, as inputs. It does not invent a second convention.

## Common resource types

Limits are from Microsoft Learn ("Naming rules and restrictions for Azure resources") and abbreviations from the Cloud Adoption Framework. Confirm a limit on Learn before relying on it for a type you have not deployed before.

| Resource | Prefix | Unique within | Length | Characters |
|---|---|---|---|---|
| Resource group | `rg-` | subscription | 1–90 | letters, digits, `-`, `_`, `.`, parentheses; cannot end with `.` |
| Virtual network | `vnet-` | resource group | 2–64 | letters, digits, `-`, `_`, `.` |
| Subnet | `snet-` | virtual network | 1–80 | letters, digits, `-`, `_`, `.` |
| Network security group | `nsg-` | resource group | 1–80 | letters, digits, `-`, `_`, `.` |
| Route table | `rt-` | resource group | 1–80 | letters, digits, `-`, `_`, `.` |
| Public IP address | `pip-` | resource group | 1–80 | letters, digits, `-`, `_`, `.` |
| Private endpoint | `pep-` | resource group | 2–64 | letters, digits, `-`, `_`, `.` |
| Storage account | `st` | global | 3–24 | lower-case letters and digits only |
| Key Vault | `kv-` | global | 3–24 | letters, digits, `-`; starts with a letter; no consecutive hyphens |
| Container registry | `cr` | global | 5–50 | letters and digits only |
| AKS cluster | `aks-` | resource group | 1–63 | letters, digits, `-`, `_` |
| Log Analytics workspace | `log-` | resource group | 4–63 | letters, digits, `-` |
| User-assigned identity | `id-` | resource group | 3–128 | letters, digits, `-`, `_` |
| Web app | `app-` | global | 2–60 | letters, digits, `-` |
| Function app | `func-` | global | 2–60 | letters, digits, `-` |
| SQL server | `sql-` | global | 1–63 | lower-case letters, digits, `-` |
| PostgreSQL flexible server | `psql-` | global | 3–63 | lower-case letters, digits, `-` |
| Cosmos DB account | `cosmos-` | global | 3–44 | lower-case letters, digits, `-` |
| Service Bus namespace | `sbns-` | global | 6–50 | letters, digits, `-`; starts with a letter |
| Virtual machine | `vm-` | resource group | 1–15 Windows, 1–64 Linux | letters, digits, `-` |

Some names are fixed by Azure and must not follow the convention: `GatewaySubnet`, `AzureFirewallSubnet`, `AzureBastionSubnet`, `RouteServerSubnet`, and private DNS zones such as `privatelink.blob.core.windows.net`.

Validate a name where the rule is easy to get wrong:

```hcl
variable "storage_account_name" {
  description = "Globally unique storage account name."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.storage_account_name))
    error_message = "Use 3 to 24 lower-case letters and digits."
  }
}
```

## Tags (AZ7)

Merge tags once in the root and pass the map to every module. Put the mandatory keys last so that a caller cannot override them:

```hcl
locals {
  tags = merge(var.tags, {
    workload    = var.workload
    environment = var.environment
    managed_by  = "terraform"
  })
}
```

- Resources do not inherit tags from their resource group or subscription. Each taggable resource takes `tags = var.tags` (or `local.tags` in a root).
- Do not assume the provider can set default tags for every resource: check the provider page for the pinned version before relying on that.
- Not every resource has tags: subnets, role assignments and diagnostic settings do not.
- Tag names are case-insensitive, tag values are case-sensitive. Azure allows 50 tags on a resource. Never put a secret in a tag: tags are readable by anyone with reader access.

### Tags that Azure Policy manages

A policy with the `modify` effect, such as "inherit a tag from the resource group", writes tags after Terraform does. Terraform then plans to remove them on every run. Ask which keys policy manages, and ignore exactly those keys on each resource that sets `tags`:

```hcl
lifecycle {
  # Azure Policy stamps these keys from the resource group.
  ignore_changes = [tags["cost_centre"], tags["owner"]]
}
```

Do this when the code is written, not after the first noisy plan. If nobody knows which keys policy manages, say so in the hand-off and do not guess.
