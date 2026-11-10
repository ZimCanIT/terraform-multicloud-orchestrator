# Networking

Virtual networks, subnets, security groups, private endpoints and DNS (AZ3). Argument names were checked against the `azurerm` 5.x documentation on 10 November 2026; check the pinned version before writing them (AZ8).

## Address plan

- Address spaces and prefixes are inputs with validation (`hcl-standards.md`). Ask for the ranges; do not invent them. An overlap with the hub or with on-premises ranges cannot be fixed later without rebuilding the network.
- State prefixes explicitly per subnet key. If the repository derives them with `cidrsubnet()`, give each key a fixed network number: deriving from list position renumbers subnets when one is removed.
- Azure reserves five addresses in every subnet. Sizes that are fixed by the platform: `GatewaySubnet` /27 or larger, `AzureFirewallSubnet` /26, `AzureBastionSubnet` /26 or larger.

## Virtual network and subnets

```hcl
resource "azurerm_subnet" "this" {
  for_each = var.subnets

  name                 = "snet-${each.key}-${var.name_suffix}"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = each.value.address_prefixes

  default_outbound_access_enabled   = false
  private_endpoint_network_policies = each.value.private_endpoint_network_policies
}
```

- Declare subnets as `azurerm_subnet` resources. Never mix them with inline `subnet` blocks on `azurerm_virtual_network`: the two fight over the same objects.
- `default_outbound_access_enabled = false` makes the subnet private. Provide outbound connectivity explicitly, with a NAT gateway or a route to a firewall, before a workload needs the internet.
- `private_endpoint_network_policies` accepts `Disabled` (the default), `Enabled`, `NetworkSecurityGroupEnabled` and `RouteTableEnabled`. Set `Enabled` on subnets that hold private endpoints so that security groups and routes apply to them.
- A delegated subnet serves one service and cannot hold anything else.

## Network security groups

- Every subnet gets a security group through `azurerm_subnet_network_security_group_association`. The exceptions are fixed by Azure: `GatewaySubnet` and `AzureFirewallSubnet` take none, and `AzureBastionSubnet` needs the rule set that the Bastion documentation lists. Model the exception as an input, not as a missing association.
- Declare rules either inline or as `azurerm_network_security_rule` resources keyed by name, not both for one group.
- The default rules allow all traffic inside the virtual network. Add an explicit deny for inbound traffic at a low priority (a high number such as 4096) and allow only what each tier needs.
- No rule allows `*` or `Internet` to ports 22 or 3389. Use Bastion or a private path.
- Prefer service tags and application security groups to lists of addresses. Leave gaps between priorities.
- For traffic logs use virtual network flow logs; flow logs on security groups are being retired.

## Routing and outbound traffic

- `azurerm_route_table` with `azurerm_subnet_route_table_association`. In a hub-and-spoke network the spoke's default route points at the firewall (`next_hop_type = "VirtualAppliance"`), and gateway route propagation is usually off on that table.
- A NAT gateway needs `azurerm_nat_gateway`, a public IP association and `azurerm_subnet_nat_gateway_association`.
- Do not attach a public IP to a workload's network interface unless the request says so.

## Private endpoints and DNS

```hcl
resource "azurerm_private_endpoint" "blob" {
  count = var.private_endpoint == null ? 0 : 1

  name                = "pep-${var.name}-blob"
  resource_group_name = var.resource_group_name
  location            = var.location
  subnet_id           = var.private_endpoint.subnet_id

  private_service_connection {
    name                           = "psc-${var.name}-blob"
    private_connection_resource_id = azurerm_storage_account.this.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = var.private_endpoint.private_dns_zone_ids
  }

  tags = var.tags
}
```

One endpoint per sub-resource in use. Common sub-resources and their zones:

| Service | `subresource_names` | Private DNS zone |
|---|---|---|
| Storage blob | `blob` | `privatelink.blob.core.windows.net` |
| Storage file | `file` | `privatelink.file.core.windows.net` |
| Data Lake Storage | `dfs` | `privatelink.dfs.core.windows.net` |
| Key Vault | `vault` | `privatelink.vaultcore.azure.net` |
| Azure SQL | `sqlServer` | `privatelink.database.windows.net` |
| PostgreSQL flexible server | `postgresqlServer` | `privatelink.postgres.database.azure.com` |
| Container Registry | `registry` | `privatelink.azurecr.io` |
| App Service and Functions | `sites` | `privatelink.azurewebsites.net` |
| Service Bus | `namespace` | `privatelink.servicebus.windows.net` |
| Cosmos DB for NoSQL | `Sql` | `privatelink.documents.azure.com` |

- In a landing zone the `privatelink` zones are central and linked to the hub. A workload stack takes their IDs as inputs (MD2). Do not create a second copy of a zone in the spoke: names then resolve differently depending on which network asks.
- If Azure Policy attaches endpoints to DNS zones in this tenant, leave `private_dns_zone_group` out and add `ignore_changes = [private_dns_zone_group]` with a comment. Ask before assuming either way.
- Link zones to networks with `azurerm_private_dns_zone_virtual_network_link` and `registration_enabled = false`.
- A private endpoint does not close the public endpoint. Turn off public network access on the service as well (`secure-baseline.md`).

## Peering

`azurerm_virtual_network_peering` is one resource per direction, each created with the provider configuration for its own subscription (`module-design.md` shows the alias pattern). `use_remote_gateways` on the spoke needs the hub gateway to exist and `allow_gateway_transit` on the hub side.

## Before the hand-off

- Every subnet has a security group, or is one of the documented exceptions.
- No public IP that the request did not ask for, and no management port open to the internet.
- Outbound traffic has an explicit path.
- Every private endpoint has DNS, from a zone group or from policy, and the service's public access is off.
