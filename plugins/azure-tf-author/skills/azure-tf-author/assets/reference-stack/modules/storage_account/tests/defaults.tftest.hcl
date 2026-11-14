# Plan-mode tests with a mocked provider: no credentials are needed and nothing is deployed.
mock_provider "azurerm" {}

variables {
  name                       = "stordersdevuks001"
  resource_group_name        = "rg-orders-dev-uks-001"
  location                   = "uksouth"
  log_analytics_workspace_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-logging-prod-uks-001/providers/Microsoft.OperationalInsights/workspaces/log-platform-prod-uks-001"
}

run "secure_defaults" {
  command = plan

  assert {
    condition     = azurerm_storage_account.this.shared_access_key_enabled == false
    error_message = "Shared key access must be off."
  }

  assert {
    condition     = azurerm_storage_account.this.public_network_access == "Disabled"
    error_message = "Public network access must be off."
  }

  assert {
    condition     = length(azurerm_private_endpoint.blob) == 0
    error_message = "No private endpoint is expected when the input is null."
  }

  assert {
    condition     = length(azurerm_management_lock.this) == 1
    error_message = "The account must be locked by default."
  }
}

run "private_endpoint_when_requested" {
  command = plan

  variables {
    private_endpoint = {
      subnet_id            = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-network-dev-uks-001/providers/Microsoft.Network/virtualNetworks/vnet-spoke-dev-uks-001/subnets/snet-endpoints-spoke-dev-uks-001"
      private_dns_zone_ids = ["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-dns-prod-uks-001/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"]
    }
  }

  assert {
    condition     = length(azurerm_private_endpoint.blob) == 1
    error_message = "A private endpoint is expected when the input is set."
  }
}

run "rejects_an_invalid_name" {
  command = plan

  variables {
    name = "Not-Valid"
  }

  expect_failures = [var.name]
}
