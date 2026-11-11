# Troubleshooting plan and apply errors

Read the whole error before you touch the code: the error code, the message and the resource address it names. Find the cause before changing anything, because the same code can come from a wrong input, a missing role or a rule the platform team set. Never fix an error by widening access, removing a guard or deleting state. The agent runs only the permitted commands in `SKILL.md` §2, so every other command in this file ("ask the user to run ...") is for the user.

## Before Azure is called: Terraform itself

These fail in `validate`, `init` or `plan`. No Azure write has happened yet.

| Error (as it appears) | What it means | Fix |
|---|---|---|
| `Invalid for_each argument` | The map keys or set values come from resource attributes that are unknown until apply. | Key the map by static names from an input and move the unknown value into the resource body (HC1). Never suggest `-target`. |
| `Invalid count argument` | `count` depends on a value that is unknown until apply. | Drive `count` from an input, for example a `bool` variable, not from another resource's attribute (HC1). |
| `Unsupported argument`, `Unsupported block type`, `Invalid resource type` | The name does not exist in the pinned provider. After an upgrade it was renamed or removed in `azurerm` 5. | Look it up in `azurerm-provider.md`, then read the registry page for the pinned version (AZ8). `terraform providers schema -json` shows what the installed provider accepts. |
| `Cycle:` | Two or more resources refer to each other, directly or through module outputs. | Break the loop with a separate association resource, for example `azurerm_subnet_network_security_group_association`, or let the caller create the role assignment (`module-design.md`). Do not add `depends_on`. |
| `Provider configuration not present` | A resource is still in state, but its code and its aliased `provider` block were removed in one change. Terraform needs that provider to destroy it. | Keep the `provider` block until the plan that destroys the resource has been applied, then remove it in a second change. If the resource must stay in Azure, add a `removed` block with `destroy = false` in the first change (HC4). |
| `Error acquiring the state lock` | Another run holds the blob lease on the state. The message gives the lock ID, who took it and when. | Change no code. Report the holder, wait for that run to finish, then plan again. If the holder is dead, the user runs `force-unlock`. Never plan with `-lock=false`. |
| `Backend configuration changed`, `Backend initialization required` | The backend block or its settings differ from what `.terraform` recorded. | Check whether the backend change was meant, and revert it if not. `terraform init -input=false` covers a first initialisation. Anything that needs `init -reconfigure` or `init -migrate-state` is for the user. |
| `subscription_id is a required provider property` | `azurerm` needs a subscription for `plan` and `apply`. `validate` works without one. | Set `subscription_id = var.subscription_id` in the root's provider block, or ask the user to set `ARM_SUBSCRIPTION_ID`. Never write a literal (AZ8, HC2). |
| `Inconsistent dependency lock file` | `.terraform.lock.hcl` has no entry for a provider the code requires, or the locked version is outside the version constraint. | `terraform init -input=false` adds a missing entry. A locked version outside the constraint needs `terraform init -upgrade`, which the user runs in its own pull request (`adopt-and-refactor.md`). |
| `(known after apply)` where a plan-time value is needed | The value comes from a resource that does not exist yet, or a `depends_on` on a module or data source pushed its read to apply. | Build names and keys from inputs and `locals` (HC3), pass IDs in as inputs (MD2), and remove blanket `depends_on` (HC7). |

The `for_each` fix keeps the keys static and puts the unknown value in the body:

```hcl
resource "azurerm_role_assignment" "reader" {
  for_each = var.identities # keyed by a stable name, never by principal ID

  scope                = var.storage_account_id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.this[each.key].principal_id
  principal_type       = "ServicePrincipal"
}
```

## Identity and access

Work out which plane refused the call. A management-plane role such as Contributor grants no data access (`identity-and-secrets.md`). The agent proposes the role and scope; the user or the platform team grants it.

| Error (as it appears) | What it means | Fix |
|---|---|---|
| `AuthorizationFailed` | Management plane. The identity that runs Terraform has no role that allows the named action at the named scope. | Check the scope first: a wrong `subscription_id` gives the same error. Then name the built-in role with the fewest permissions and the narrowest scope in the hand-off. Never propose Owner (AZ1). |
| 403 `AuthorizationPermissionMismatch` (storage) | The token was accepted, but the identity holds no data role on the account. | Grant a data role such as Storage Blob Data Contributor with `azurerm_role_assignment`, and set `storage_use_azuread = true` in the provider block (AZ1). Do not turn shared keys back on. |
| `KeyBasedAuthenticationNotPermitted` (storage) | The provider used a shared key against an account with `shared_access_key_enabled = false`. | Set `storage_use_azuread = true` in the provider block. For the state account, set `use_azuread_auth = true` in the backend (`state-and-environments.md`). |
| 403 `AuthorizationFailure` (storage), `ForbiddenByFirewall` (Key Vault) | The network refused the call. Public network access is off and the runner has no private path. | Do not open the firewall (AZ3). The run needs a runner with a private path. For storage, `secure-baseline.md` describes the `data_plane_available` feature switch. |
| 403 `Forbidden` (Key Vault): `does not have secrets get permission`, or `ForbiddenByRbac` | The caller has no data-plane access to the vault. The first message comes from access policies, the second from RBAC. | With `rbac_authorization_enabled = true`, grant Key Vault Secrets Officer to the identity that writes secrets and Key Vault Secrets User to readers, scoped to the vault (AZ1). Add `depends_on` on the assignment (HC7). |
| `PrincipalNotFound` | The identity was created seconds ago and has not replicated in Entra ID. | Set `principal_type = "ServicePrincipal"` on the `azurerm_role_assignment`. Adding it to an assignment that already exists replaces that assignment. |
| 409 `RoleAssignmentExists` | An assignment with the same scope, role and principal already exists, made outside this state or by another block. | Write an `import` block for it (HC4). Do not create a duplicate under another name, and check that two blocks do not declare the same assignment. |
| `RoleAssignmentUpdateNotPermitted` | An assignment with this `name` (a GUID) exists for another principal or scope. Azure does not update those fields. | Leave `name` unset so that the provider generates one (check the registry page for the pinned version). Common after an identity was recreated and got a new principal ID. |
| `LinkedAuthorizationFailed` | The identity may write the resource but lacks an action on a linked resource, often in another subscription: a subnet, a private DNS zone, a hub network. | Check the linked ID first: a wrong ID gives the same error. Then name the role on the other side in the hand-off, for example Network Contributor on the subnet or Private DNS Zone Contributor on the zone. |
| `ScopeLocked` | A management lock on the resource or a parent blocks the write or delete. | Do not remove the lock in code to get past it. Ask why the plan touches a locked resource: it is usually an unintended replacement, so apply the stop-and-confirm rule (`SKILL.md` §2). |
| `AADSTS70021`: `No matching federated identity record found` | OIDC sign-in. The token's issuer, subject or audience matches no federated credential. The subject is the usual mismatch. | Compare the subject in the error with `subject` on `azurerm_federated_identity_credential`. Branch, environment and pull request runs each present a different subject, and the match is case-sensitive. |
| `AADSTS700016`: `Application with identifier ... was not found in the directory` | `ARM_CLIENT_ID` or `ARM_TENANT_ID` is wrong, or the application or identity was deleted. | A pipeline setting, not a code fix. Output the identity's `client_id` from the stack that creates it, and ask the user to correct the setting. |

## Policy, registration and quota

Plan cannot see most of these. Azure checks them when the apply sends the request.

| Error (as it appears) | What it means | Fix |
|---|---|---|
| `RequestDisallowedByPolicy` | An Azure Policy assignment with a deny effect refused the request. The message names the assignment and the definition. | Read the policy name and change the code to comply: required tags, allowed region, public network access off, allowed SKU, minimum TLS. An exemption is never the first fix. Add a `validation` so that the same mistake fails at plan (MD4). |
| `MissingSubscriptionRegistration`: `The subscription is not registered to use namespace` | The resource provider for the service is not registered in the subscription. `azurerm` 5 registers nothing by default. | Add the namespace to `resource_providers_to_register` in the provider block, or confirm that the platform team registers it (`azurerm-provider.md`). |
| A message that a feature such as `Microsoft.Compute/EncryptionAtHost` is not enabled for the subscription | A subscription feature flag is off. | Not a code fix: the user enables the feature. Keep the secure setting; do not turn it off to get past the error (AZ4). |
| `LocationNotAvailableForResourceType` | The service is not offered in that region, or the region is mistyped. `azurerm` 5 does not check `location` at plan by default. | Validate regions in the variable (MD4), or turn the check back on with `enhanced_validation` (`azurerm-provider.md`). Choose a region from the list in the message. |
| `SkuNotAvailable` | The size or tier is not available in that region or zone for this subscription. | Make the SKU and zones inputs, not literals (HC2), and choose a size the region offers. The user can list sizes with `az vm list-skus`. |
| `QuotaExceeded`, or `OperationNotAllowed` naming a cores quota | The request exceeds the subscription's quota for that family and region. The message gives the limit, the usage and the amount required. | Check whether the size or count in the inputs is larger than needed. If it is right, the user requests a quota increase. Do not retry, and do not change region without asking. |
| `InvalidResourceLocation` | A resource with this name already exists in the resource group, in another region. | Do not delete it. Set `location` to the deployed region and write an `import` block, or build a new name that carries the region (HC3). |

```hcl
provider "azurerm" {
  features {}

  subscription_id                = var.subscription_id
  storage_use_azuread            = true
  resource_providers_to_register = ["Microsoft.App", "Microsoft.OperationalInsights"]
}
```

## Names and soft delete

| Error (as it appears) | What it means | Fix |
|---|---|---|
| `StorageAccountAlreadyTaken` | Storage account names are global, and another subscription or tenant holds this one. | Add a short suffix that is stable and known at plan time to the name in `locals` (HC3, `naming-and-tagging.md`). If the account is the user's own, write an `import` block. |
| `VaultAlreadyExists`, or a message that the vault `already exists in deleted state` | The name belongs to another vault, or to a soft-deleted vault that has not been purged. | With the provider's `recover_soft_deleted_key_vaults` feature on, the create brings the deleted vault back with its old contents: say so in the hand-off. Otherwise use a new name, or the user purges the vault. Purge protection blocks a purge until retention ends (AZ5). |
| A message that a Cognitive Services account, API Management service or App Configuration store of that name is soft-deleted | These services reserve a deleted resource's name for a retention period. A create under that name fails until the old one is recovered or purged. | The `features` block has recover and purge switches for some services: check the registry page for the pinned version. Otherwise the user purges the deleted resource, or the code takes a new name. |
| `A resource with the ID ... already exists - to be managed via Terraform this resource needs to be imported into the State` | Azure has the resource and state does not. It was made by hand, by another state, or by an apply that failed before it saved. | Write an `import` block and plan until it shows an import and no change (`adopt-and-refactor.md`, HC4). Do not delete the resource. Check that two blocks do not create the same object. |
| `AccountNameInvalid`, `VaultNameNotValid`, `InvalidResourceName` at apply | A name built from inputs breaks the service's length or character rules. Plan could not check it because part of the name was unknown. | Build names once in `locals` from plan-time values (HC3), and add a `validation` on the inputs with the limits in `naming-and-tagging.md` (MD4). |

## Networking

| Error (as it appears) | What it means | Fix |
|---|---|---|
| `InUseSubnetCannotBeDeleted` | The plan deletes or replaces a subnet that still holds network interfaces, private endpoints or a service link. | Find why the subnet is going: a changed `for_each` key, a changed `name`, or prefixes derived from list position. Keep the address with a `moved` block (HC4) and revert the rename. A subnet in use is on the stop list. |
| `SubnetMissingRequiredDelegation`, `PrivateEndpointCreationNotAllowedAsSubnetIsDelegated`, or another message that the subnet is delegated | The service needs a subnet delegated to it, or the subnet is delegated to a different service. | Give each service its own subnet with the `delegation` block its registry page names. Put private endpoints in a subnet with no delegation (`networking.md`). |
| `NetworkSecurityGroupNotCompliantForAzureBastionSubnet` | The security group on `AzureBastionSubnet` lacks the inbound and outbound rules that Bastion requires. | Add the full rule set from the Bastion documentation, modelled as an input for that subnet (`networking.md`). Do not remove the security group (AZ3). |
| `PrivateEndpointCannotBeCreatedInSubnetThatHasNetworkPoliciesEnabled` | Older API versions refused a private endpoint in a subnet with network policies on. | Set `private_endpoint_network_policies` on `azurerm_subnet` explicitly. It is a string in 5.x (`azurerm-provider.md`). If the error persists, check the provider version in the lock file. |
| No error: the private endpoint exists, but the name resolves to the public IP | The endpoint has no DNS record, or the `privatelink` zone is not linked to the network that resolves the name. | Add `private_dns_zone_group` with the zone for that subresource and check the zone's virtual network link (`networking.md`). If Azure Policy manages DNS, leave the block out and add `ignore_changes = [private_dns_zone_group]` with a comment. |
| `AnotherOperationInProgress`, `RetryableError` | Azure allows one write at a time on a virtual network and its subnets. Two writes collided: two runs, two states, or inline and separate subnet resources. | Give the network one owner: one state (ST2), `azurerm_subnet` resources only, and references that make the real order visible. Do not add blanket `depends_on` (HC7). The next apply continues where this one stopped. |
| `cannot be peered because their address spaces overlap` | The two networks share address space. Peering needs ranges that do not overlap. | Take address ranges from the IP plan as inputs and validate them (MD4). Changing the range of a network that holds workloads is a rebuild: stop and confirm. |

## During and after apply

The user ran the apply. Ask for the full error and plan again before proposing a fix: the plan shows what state recorded.

| Error (as it appears) | What it means | Fix |
|---|---|---|
| `Provider produced inconsistent result after apply`, `Root object was present, but now absent` | The provider read the resource back after the write and found it missing or changed. Causes: eventual consistency, or a policy that modifies the resource. | Plan again. If Azure has the resource and state does not, write an `import` block. If a policy changes the same attribute every time, set that value in code or add a narrow `ignore_changes` with a comment (HC5). |
| The same diff on every plan: tags | Azure Policy adds or rewrites tags after apply. | `ignore_changes` on those tag keys only (AZ7). |
| The same diff on every plan: `node_count` | The AKS autoscaler owns the node count. | `ignore_changes = [default_node_pool[0].node_count]` with a comment (HC5). |
| The same diff on every plan: `zone` | A PostgreSQL flexible server swapped zones in a failover. | `ignore_changes = [zone, high_availability[0].standby_availability_zone]` (`secure-baseline.md`). |
| The same diff on every plan: an ID that differs only in case | A hand-built or pasted ID has different casing from the one Azure returns. | Reference the resource's `id` attribute. For a literal, use the casing in the "Import" section of the registry page. |
| The same diff on every plan: a value the code never set | Azure filled in a default that differs from the provider's. | Set the argument to the deployed value. Never use `ignore_changes = all` (HC5). |
| `context deadline exceeded` | The operation ran longer than the resource's timeout. Azure may still be working on it. | Add a `timeouts` block sized to the operation; the registry page lists the defaults. Do not ask for a blind re-run: the user checks the operation in Azure first, because a second attempt can collide with the first. |
| Next plan says `is tainted, so must be replaced` | A create failed part-way. Terraform saved the resource as tainted, and tainted means delete and create. | Fix the cause in code first. If the type is on the stop list (`azurerm-provider.md`), stop and confirm. If the resource is healthy in Azure, the user can run `terraform untaint`. |
| 403 or 409 `Conflict` on a storage or Key Vault operation straight after a role assignment | A 403 means the new assignment is not in effect yet. A 409 means the resource is still busy with an earlier operation. | Add `depends_on` on the role assignment with a comment (HC7). The next apply creates what is left. Add a delay only if the failure repeats (`identity-and-secrets.md`). |

```hcl
lifecycle {
  # Azure Policy sets these tags; the cluster autoscaler owns the node count.
  ignore_changes = [tags["cost_centre"], default_node_pool[0].node_count]
}
```

```hcl
timeouts {
  create = "3h" # longer than the default on the registry page; say why in the hand-off
}
```

## When the fix is not in code

Hand these to the user. The hand-off names the exact command and says why it is needed. After the user has acted, plan again and read the result.

- Clear a stuck state lock: `terraform force-unlock <LOCK_ID>`, once it is certain that no run still holds the lock.
- Re-point or migrate the backend: `terraform init -reconfigure` or `terraform init -migrate-state`.
- Import by command: `terraform import <address> <id>`. Prefer an `import` block, which a plan can show first.
- Purge a soft-deleted vault: `az keyvault purge --name <vault>`. Purge protection blocks it until retention ends.
- Request quota: a quota increase in the Azure portal, with the family, region and new limit from the error.
- Register a resource provider: `az provider register --namespace <namespace>`, when Terraform should not register it.
- Change a policy assignment or grant an exemption: the policy owner decides. Give the policy name and the resource it blocked.
- Grant a role to the identity that runs Terraform: give the role, the scope and the action from the error.
