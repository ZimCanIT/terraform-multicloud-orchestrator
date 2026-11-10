locals {
  # One entry per rule, keyed "<subnet>/<rule>", so that adding or removing a rule touches only that rule.
  security_rules = merge([
    for subnet_key, subnet in var.subnets : {
      for rule_key, rule in subnet.security_rules : "${subnet_key}/${rule_key}" => merge(rule, {
        subnet_key = subnet_key
        name       = rule_key
      })
    }
  ]...)
}
