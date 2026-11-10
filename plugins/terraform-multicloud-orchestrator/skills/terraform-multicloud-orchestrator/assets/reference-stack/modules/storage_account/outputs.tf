output "id" {
  description = "Resource ID of the storage account. Use it as the scope of role assignments."
  value       = azurerm_storage_account.this.id
}

output "name" {
  description = "Name of the storage account."
  value       = azurerm_storage_account.this.name
}

output "primary_blob_endpoint" {
  description = "Blob service endpoint. Callers sign in with Entra ID; the module exposes no key."
  value       = azurerm_storage_account.this.primary_blob_endpoint
}
