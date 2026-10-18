terraform { required_version = ">= 1.5" }

variable "v" {
  type        = string
  default     = "1"
  description = "Changing this value replaces the resource."
}

resource "terraform_data" "r" {
  triggers_replace = var.v
}

output "r" {
  value = terraform_data.r.id
}
