variable "subscription_id" {
  description = "Subscription to deploy into. Supplied per environment, never written into code."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$", var.subscription_id))
    error_message = "subscription_id must be a lower-case GUID."
  }
}

variable "workload" {
  description = "Short workload name used in resource names and tags."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,7}$", var.workload))
    error_message = "workload must be 2 to 8 lower-case letters or digits and start with a letter, so that every derived name fits its limit."
  }
}

variable "environment" {
  description = "Deployment environment. Used in names and tags."
  type        = string
  nullable    = false

  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "environment must be one of: dev, test, prod."
  }
}

variable "location" {
  description = "Azure region. Must be a region that the naming map in locals.tf knows."
  type        = string
  nullable    = false

  validation {
    condition     = contains(["northeurope", "uksouth", "ukwest", "westeurope"], var.location)
    error_message = "location must be one of: northeurope, uksouth, ukwest, westeurope."
  }
}

variable "instance" {
  description = "Three-digit number that distinguishes copies of the workload in one environment and region."
  type        = string
  default     = "001"
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]{3}$", var.instance))
    error_message = "instance must be three digits, for example 001."
  }
}

variable "storage_replication_type" {
  description = "Replication for the workload storage account."
  type        = string
  default     = "ZRS"
  nullable    = false
}

variable "log_analytics_workspace_id" {
  description = "ID of the central Log Analytics workspace. The platform stack owns it; this stack only receives the ID."
  type        = string
  nullable    = false
}

variable "storage_private_endpoint" {
  description = "Subnet and private DNS zones for the blob private endpoint. The network stack owns both. Null creates no endpoint."
  type = object({
    subnet_id            = string
    private_dns_zone_ids = list(string)
  })
  default = null
}

variable "tags" {
  description = "Extra tags. The mandatory keys are added in locals.tf and cannot be overridden."
  type        = map(string)
  default     = {}
  nullable    = false
}
