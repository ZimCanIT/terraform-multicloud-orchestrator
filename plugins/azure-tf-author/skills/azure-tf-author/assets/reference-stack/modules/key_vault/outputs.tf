output "id" {
  description = "Resource ID of the vault. Use it as the scope of role assignments."
  value       = azurerm_key_vault.this.id
}

output "name" {
  description = "Name of the vault."
  value       = azurerm_key_vault.this.name
}

output "uri" {
  description = "URI of the vault. Callers sign in with Entra ID and a data role on the vault."
  value       = azurerm_key_vault.this.vault_uri
}
