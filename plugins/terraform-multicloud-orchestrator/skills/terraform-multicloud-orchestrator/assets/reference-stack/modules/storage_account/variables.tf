variable "name" {
  description = "Globally unique storage account name: 3 to 24 lower-case letters and digits."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.name))
    error_message = "name must be 3 to 24 lower-case letters and digits."
  }
}

variable "resource_group_name" {
  description = "Resource group to deploy into. The caller owns it."
  type        = string
  nullable    = false
}

variable "location" {
  description = "Azure region for the account and its private endpoint."
  type        = string
  nullable    = false
}

variable "account_replication_type" {
  description = "Replication for the account. Changing between a zonal and a non-zonal type can replace the account."
  type        = string
  default     = "ZRS"
  nullable    = false

  validation {
    condition     = contains(["LRS", "ZRS", "GRS", "GZRS", "RAGRS", "RAGZRS"], var.account_replication_type)
    error_message = "account_replication_type must be one of: LRS, ZRS, GRS, GZRS, RAGRS, RAGZRS."
  }
}

variable "log_analytics_workspace_id" {
  description = "ID of the Log Analytics workspace that receives the blob service logs."
  type        = string
  nullable    = false
}

variable "private_endpoint" {
  description = "Private endpoint for the blob service. Null creates none. Public network access is off either way."
  type = object({
    subnet_id            = string
    private_dns_zone_ids = list(string)
  })
  default = null
}

variable "lock_enabled" {
  description = "Whether a CanNotDelete lock guards the account against deletion from outside Terraform, such as the portal or another pipeline."
  type        = bool
  default     = true
  nullable    = false
}

variable "tags" {
  description = "Tags for every taggable resource in the module."
  type        = map(string)
  default     = {}
  nullable    = false
}
