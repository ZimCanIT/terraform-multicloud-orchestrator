output "id" {
  description = "Resource ID of the virtual network."
  value       = azurerm_virtual_network.this.id
}

output "name" {
  description = "Name of the virtual network."
  value       = azurerm_virtual_network.this.name
}

output "subnet_ids" {
  description = "Subnet IDs keyed by the same names as the subnets input."
  value       = { for key, subnet in azurerm_subnet.this : key => subnet.id }
}
