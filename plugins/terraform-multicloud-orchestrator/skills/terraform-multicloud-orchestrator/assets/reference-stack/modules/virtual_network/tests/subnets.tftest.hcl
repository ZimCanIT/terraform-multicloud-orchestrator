# Plan-mode tests with a mocked provider: no credentials are needed and nothing is deployed.
mock_provider "azurerm" {}

variables {
  name_suffix         = "orders-dev-uks-001"
  resource_group_name = "rg-network-dev-uks-001"
  location            = "uksouth"
  address_space       = ["10.20.0.0/22"]
  subnets = {
    app = {
      address_prefixes = ["10.20.0.0/24"]
      security_rules = {
        allow-https-from-gateway = {
          priority                   = 100
          direction                  = "Inbound"
          access                     = "Allow"
          protocol                   = "Tcp"
          source_address_prefix      = "10.20.3.0/24"
          destination_address_prefix = "10.20.0.0/24"
          destination_port_range     = "443"
        }
      }
    }
    endpoints = {
      address_prefixes = ["10.20.1.0/24"]
    }
  }
}

run "one_security_group_per_subnet" {
  command = plan

  assert {
    condition     = length(azurerm_subnet.this) == 2 && length(azurerm_network_security_group.this) == 2
    error_message = "Every subnet must get its own network security group."
  }

  assert {
    condition     = length(azurerm_subnet_network_security_group_association.this) == 2
    error_message = "Every subnet must be associated with its network security group."
  }

  assert {
    condition     = alltrue([for subnet in azurerm_subnet.this : subnet.default_outbound_access_enabled == false])
    error_message = "Subnets must be private: default outbound access off."
  }

  assert {
    condition     = contains(keys(azurerm_network_security_rule.this), "app/allow-https-from-gateway")
    error_message = "Rules must be keyed by subnet and rule name."
  }

  assert {
    condition     = length(azurerm_network_security_rule.deny_inbound) == 2
    error_message = "Every network security group must end with a rule that denies inbound traffic."
  }
}

run "rejects_an_invalid_prefix" {
  command = plan

  variables {
    subnets = {
      app = {
        address_prefixes = ["10.20.0.0/33"]
      }
    }
  }

  expect_failures = [var.subnets]
}
