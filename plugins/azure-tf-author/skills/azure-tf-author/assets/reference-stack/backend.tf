# Environment values come from a backend file at init time, for example
# terraform init -backend-config=environments/dev.backend.hcl
terraform {
  backend "azurerm" {
    use_azuread_auth = true
  }
}
