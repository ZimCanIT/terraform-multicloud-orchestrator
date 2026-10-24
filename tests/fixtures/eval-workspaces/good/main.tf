variable "name" {
  description = "Name recorded in the resource."
  type        = string
  default     = "example"
}

resource "terraform_data" "this" {
  input = var.name
}

output "name" {
  description = "Name recorded by the resource."
  value       = terraform_data.this.output
}
