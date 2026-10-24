variable "name" {
  description = "Name recorded in both resources."
  type        = string
}

resource "terraform_data" "first" {
  input = var.name
}

resource "terraform_data" "second" {
  input = terraform_data.first.output
}
