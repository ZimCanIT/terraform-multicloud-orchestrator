resource "azurerm_resource_group" "this" {
  name     = local.names.resource_group
  location = var.location
  tags     = local.tags
}

# Created before anything uses it, so that access can be granted first.
resource "azurerm_user_assigned_identity" "workload" {
  name                = local.names.identity
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = local.tags
}

module "storage" {
  source = "./modules/storage_account"

  name                       = local.names.storage_account
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  account_replication_type   = var.storage_replication_type
  log_analytics_workspace_id = var.log_analytics_workspace_id
  private_endpoint           = var.storage_private_endpoint
  tags                       = local.tags
}

# The stack sees both the identity and the account, so it grants the access.
resource "azurerm_role_assignment" "workload_reads_blobs" {
  scope                = module.storage.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.workload.principal_id
  principal_type       = "ServicePrincipal"
}
