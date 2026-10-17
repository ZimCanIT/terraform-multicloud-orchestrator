# Example session — Azure VNet (greenfield)

A walkthrough of one full orchestration, from prompt to plan-only handoff, for a
small greenfield Azure network. It shows what the skill produces at each phase; it
is **not** runnable Terraform you should copy verbatim — provider schemas move,
so the orchestrator re-researches them at run time, and the versions below are
illustrative.

This skill is **plan-only**. Nothing here runs `apply` or `destroy`.

---

## User prompt

> Stand up a new private network for a dev environment: three private subnets
> (app, data, management), no public IPs. Keep it modular.

The working directory is empty, so this is greenfield, and the prompt names no
cloud.

---

## Phase 0 — Session setup and context discovery

The orchestrator asks the two setup questions once: target cloud and provider
pinning. The user picks Azure and accepts the default pinning strategy. Only
`references/azure.md` is loaded — never the other cloud files — and it adds two
Azure-specific questions. The provider needs a subscription, and Azure Policy may
add or modify tags outside Terraform. The skill does not pre-approve `az`, so it
asks instead of running it:

> Please paste the output of `az account show`, and tell me whether Azure Policy in
> this tenant adds or modifies tags and which keys it manages.

The user pastes the output and answers that Policy adds the tags `environment` and
`owner`. The subscription ID becomes an input variable, never a hard-coded value.
The orchestrator emits SESSION CONFIG and treats it as authoritative for the rest
of the session:

```
SESSION CONFIG
- Clouds: azure
- Pinning: latest-stable-and-pin
- Mode: greenfield
- Resolved provider versions: <filled in after research>
```

## Phase 1 — Research (Doc-Specialist)

Schema for `azurerm_resource_group`, `azurerm_virtual_network`, `azurerm_subnet`,
`azurerm_network_security_group` and
`azurerm_subnet_network_security_group_association` is verified against
`registry.terraform.io/providers/hashicorp/azurerm/latest/docs`. The current latest
stable azurerm major resolves to **v5.x**, written as `~> 5.0`, with
`required_version = "~> 1.13"` for the Terraform runtime. The provider block needs a
`features {}` block and a `subscription_id`. SESSION CONFIG is updated:

```
- Resolved provider versions: hashicorp/azurerm ~> 5.0; terraform ~> 1.13
```

## Phase 2 — Generation (HCL-Architect)

A modular layout is scaffolded — a root calling a composite `network` module:

```
azure-vnet/
├── versions.tf
├── providers.tf       # azurerm provider, features {}, subscription_id
├── main.tf            # calls module "network"
├── variables.tf
├── outputs.tf
├── terraform.tfvars.example
└── modules/
    └── network/
        ├── main.tf    # resource group + VNet + subnets + NSG + associations
        ├── variables.tf
        └── outputs.tf
```

Two Azure-specific controls shape the code:

- Subnets use `for_each` over a name→CIDR map (not `count`). `azurerm_subnet` takes
  `resource_group_name` and `virtual_network_name` as ForceNew arguments, so stable
  keys keep a change to one subnet from shifting the others.
- Because Policy adds tags, every resource that sets `tags` also carries a
  `lifecycle` block that ignores those keys, so Policy-added tags never show as
  drift. `azurerm_subnet` and the NSG association have no `tags` argument, so they
  get none: Terraform rejects `ignore_changes` on an attribute that does not exist.

The core of the module looks like this:

```hcl
resource "azurerm_virtual_network" "this" {
  name                = "vnet-${var.workload}-${var.environment}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  address_space       = var.address_space
  tags                = var.tags

  lifecycle {
    # Azure Policy adds these tags outside Terraform.
    ignore_changes = [tags["environment"], tags["owner"]]
  }
}

resource "azurerm_subnet" "private" {
  for_each = var.private_subnets # name => CIDR

  name                 = each.key
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [each.value]
}

resource "azurerm_subnet_network_security_group_association" "private" {
  for_each = azurerm_subnet.private

  subnet_id                 = each.value.id
  network_security_group_id = azurerm_network_security_group.private.id
}
```

Code is presented for review before any `.tf` file is written.

## Phase 3 — Validation (State-Validator)

The plan-only steps run directly (these are the exact commands scoped in
`allowed-tools`). Static checks first, then the plan, then the `jq` filter that
lists anything the plan deletes or replaces:

```bash
terraform init -backend=false -input=false
terraform validate
terraform fmt -check -recursive

terraform init -input=false
terraform plan -input=false -out=tfplan
terraform show -json tfplan | jq -r '.resource_changes[]? | select(.change.actions | index("delete")) | "\(.address)\t\(.change.actions | join("+"))"'
```

The state-backed plan uses the user's Azure credentials (for example from
`az login`) to read state and refresh; it creates nothing. Every line of the plan
is `+ create` and the `jq` filter prints nothing, so the stop-and-confirm gate
(§2 of `SKILL.md`) does not trigger. That is expected in a greenfield: with no
existing state there is nothing to replace. In a brownfield, a replaced AKS cluster
or Azure Firewall would be listed here and would stop the handoff.

---

## Phase 4 — Handoff (final report)

```
# Final Report

## Modular Map
azure-vnet/
├── versions.tf
├── providers.tf
├── main.tf
├── variables.tf
├── outputs.tf
├── terraform.tfvars.example
└── modules/network/{main,variables,outputs}.tf

## Plan Summary
- Add: 9        # 1 resource group, 1 VNet, 3 subnets, 1 NSG, 3 NSG associations
- Change: 0
- Destroy: 0
- Replacements: none

## Output Contract
- Assumptions and version floor: hashicorp/azurerm ~> 5.0, terraform ~> 1.13;
  subscription_id supplied as an input; for_each keyed on subnet name; three
  private subnets, no public IPs; Azure Policy adds the tags environment and owner,
  so resources that set tags ignore those keys.
- Failure modes addressed: identity churn (for_each over count).
- Tradeoffs: composite network module of plain azurerm resources over Azure
  Verified Modules, to keep the wiring explicit in a small example; one NSG shared
  by the three subnets with default rules only; no NAT gateway or firewall yet (no
  egress requirement stated).
- Rollback / recovery: discard the branch before apply; no state exists yet,
  so there is nothing to import or move.

## Handoff
Code is staged and validated. Manual `terraform apply tfplan` is required.
```

The user reviews `tfplan` and runs the apply themselves —
the skill never does.
