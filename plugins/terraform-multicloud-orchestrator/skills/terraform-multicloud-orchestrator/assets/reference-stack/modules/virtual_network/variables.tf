variable "name_suffix" {
  description = "Suffix shared by every name in the module, for example orders-dev-uks-001."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z0-9-]{3,40}$", var.name_suffix))
    error_message = "name_suffix must be 3 to 40 lower-case letters, digits and hyphens."
  }
}

variable "resource_group_name" {
  description = "Resource group to deploy into. The caller owns it."
  type        = string
  nullable    = false
}

variable "location" {
  description = "Azure region for the network and its security groups."
  type        = string
  nullable    = false
}

variable "address_space" {
  description = "Address ranges of the virtual network in CIDR notation. Agree them with whoever owns the address plan."
  type        = list(string)
  nullable    = false

  validation {
    condition     = length(var.address_space) > 0 && alltrue([for range in var.address_space : can(cidrhost(range, 0))])
    error_message = "address_space must hold at least one valid CIDR range, for example 10.20.0.0/22."
  }
}

variable "subnets" {
  description = "Subnets keyed by a short stable name. The key becomes part of the subnet name and of the resource address, so it must not change."
  type = map(object({
    address_prefixes                  = list(string)
    private_endpoint_network_policies = optional(string, "Enabled")
    delegation = optional(object({
      name    = string
      service = string
      actions = optional(list(string))
    }))
    security_rules = optional(map(object({
      priority                   = number
      direction                  = string
      access                     = string
      protocol                   = string
      source_address_prefix      = string
      destination_address_prefix = string
      destination_port_range     = string
    })), {})
  }))
  nullable = false

  validation {
    condition = alltrue(flatten([
      for subnet in var.subnets : [for prefix in subnet.address_prefixes : can(cidrhost(prefix, 0))]
    ]))
    error_message = "Every subnet address prefix must be a valid CIDR range, for example 10.20.1.0/24."
  }

  validation {
    condition = alltrue([
      for subnet in var.subnets : contains(["Disabled", "Enabled", "NetworkSecurityGroupEnabled", "RouteTableEnabled"], subnet.private_endpoint_network_policies)
    ])
    error_message = "private_endpoint_network_policies must be one of: Disabled, Enabled, NetworkSecurityGroupEnabled, RouteTableEnabled."
  }
}

variable "tags" {
  description = "Tags for every taggable resource in the module."
  type        = map(string)
  default     = {}
  nullable    = false
}
