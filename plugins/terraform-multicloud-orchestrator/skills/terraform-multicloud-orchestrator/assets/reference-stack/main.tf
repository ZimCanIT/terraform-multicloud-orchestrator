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

# The tenant and the deploying identity are read, never written into code.
data "azurerm_client_config" "current" {}

module "vault" {
  source = "./modules/key_vault"

  name                       = local.names.vault
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  log_analytics_workspace_id = var.log_analytics_workspace_id
  private_endpoint           = var.vault_private_endpoint
  tags                       = local.tags
}

resource "azurerm_role_assignment" "workload_reads_vault" {
  scope                = module.vault.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.workload.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "deployer_writes_vault" {
  scope                = module.vault.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Generated on every run and never stored. An ephemeral value can reach Azure only through a
# write-only argument, so it is in neither the state nor the plan file.
ephemeral "random_password" "webhook" {
  length = 32
}

resource "azurerm_key_vault_secret" "webhook" {
  name             = "webhook-signing"
  key_vault_id     = module.vault.id
  value_wo         = ephemeral.random_password.webhook.result
  value_wo_version = var.webhook_value_version

  # Terraform cannot see that writing to the vault needs the deployer's role assignment first.
  depends_on = [azurerm_role_assignment.deployer_writes_vault]
}
