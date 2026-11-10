locals {
  location_short = {
    northeurope = "neu"
    uksouth     = "uks"
    ukwest      = "ukw"
    westeurope  = "weu"
  }[var.location]

  # <type>-<workload>-<environment>-<region>-<instance>
  name_suffix = join("-", [var.workload, var.environment, local.location_short, var.instance])

  names = {
    resource_group  = "rg-${local.name_suffix}"
    identity        = "id-${local.name_suffix}"
    vault           = "kv-${local.name_suffix}"
    storage_account = "st${replace(local.name_suffix, "-", "")}"
  }

  # Mandatory keys come last so that a caller cannot override them.
  tags = merge(var.tags, {
    environment = var.environment
    managed_by  = "terraform"
    workload    = var.workload
  })
}
