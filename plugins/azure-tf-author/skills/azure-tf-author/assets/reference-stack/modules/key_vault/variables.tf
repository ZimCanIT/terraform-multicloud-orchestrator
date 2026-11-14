variable "name" {
  description = "Globally unique vault name: 3 to 24 lower-case letters, digits and hyphens, starting with a letter."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,22}[a-z0-9]$", var.name)) && !strcontains(var.name, "--")
    error_message = "name must be 3 to 24 lower-case letters, digits and hyphens, start with a letter, end with a letter or digit, and have no consecutive hyphens."
  }
}

variable "resource_group_name" {
  description = "Resource group to deploy into. The caller owns it."
  type        = string
  nullable    = false
}

variable "location" {
  description = "Azure region for the vault and its private endpoint."
  type        = string
  nullable    = false
}

variable "tenant_id" {
  description = "Entra ID tenant that authenticates requests to the vault. The caller reads it from azurerm_client_config."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$", var.tenant_id))
    error_message = "tenant_id must be a lower-case GUID."
  }
}

variable "log_analytics_workspace_id" {
  description = "ID of the Log Analytics workspace that receives the vault's audit logs."
  type        = string
  nullable    = false
}

variable "private_endpoint" {
  description = "Private endpoint for the vault. Null creates none. Public network access is off either way."
  type = object({
    subnet_id            = string
    private_dns_zone_ids = list(string)
  })
  default = null
}

variable "tags" {
  description = "Tags for every taggable resource in the module."
  type        = map(string)
  default     = {}
  nullable    = false
}
