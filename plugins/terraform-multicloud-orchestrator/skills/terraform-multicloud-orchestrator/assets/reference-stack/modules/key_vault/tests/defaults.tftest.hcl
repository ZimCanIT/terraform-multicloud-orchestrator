# Plan-mode tests with a mocked provider: no credentials are needed and nothing is deployed.
mock_provider "azurerm" {}

variables {
  name                       = "kv-orders-dev-uks-001"
  resource_group_name        = "rg-orders-dev-uks-001"
  location                   = "uksouth"
  tenant_id                  = "00000000-0000-0000-0000-000000000000"
  log_analytics_workspace_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-logging-prod-uks-001/providers/Microsoft.OperationalInsights/workspaces/log-platform-prod-uks-001"
}

run "secure_defaults" {
  command = plan

  assert {
    condition     = azurerm_key_vault.this.rbac_authorization_enabled == true
    error_message = "The vault must use role-based access control, not access policies."
  }

  assert {
    condition     = azurerm_key_vault.this.purge_protection_enabled == true
    error_message = "Purge protection must be on."
  }

  assert {
    condition     = azurerm_key_vault.this.public_network_access_enabled == false
    error_message = "Public network access must be off."
  }

  assert {
    condition     = length(azurerm_private_endpoint.vault) == 0
    error_message = "No private endpoint is expected when the input is null."
  }
}

run "private_endpoint_when_requested" {
  command = plan

  variables {
    private_endpoint = {
      subnet_id            = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-network-dev-uks-001/providers/Microsoft.Network/virtualNetworks/vnet-spoke-dev-uks-001/subnets/snet-endpoints-spoke-dev-uks-001"
      private_dns_zone_ids = ["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-dns-prod-uks-001/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net"]
    }
  }

  assert {
    condition     = length(azurerm_private_endpoint.vault) == 1
    error_message = "A private endpoint is expected when the input is set."
  }
}

run "rejects_consecutive_hyphens" {
  command = plan

  variables {
    name = "kv--orders"
  }

  expect_failures = [var.name]
}
