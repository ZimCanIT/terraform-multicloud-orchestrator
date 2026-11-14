output "resource_group_name" {
  description = "Name of the workload resource group."
  value       = azurerm_resource_group.this.name
}

output "storage_account_id" {
  description = "Resource ID of the workload storage account."
  value       = module.storage.id
}

output "vault_uri" {
  description = "URI of the workload Key Vault. The application reads its values from here with its managed identity."
  value       = module.vault.uri
}

output "workload_identity_client_id" {
  description = "Client ID of the workload's user-assigned identity, for the application's configuration."
  value       = azurerm_user_assigned_identity.workload.client_id
}
