# Example session — GCP VPC (greenfield)

A walkthrough of one full orchestration, from prompt to plan-only handoff, for a
small greenfield GCP network. It shows what the skill produces at each phase; it
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
pinning. The user picks GCP and accepts the default pinning strategy. It then emits
SESSION CONFIG and treats it as authoritative for the rest of the session:

```
SESSION CONFIG
- Clouds: gcp
- Pinning: latest-stable-and-pin
- Mode: greenfield
- Resolved provider versions: <filled in after research>
```

Only `references/gcp.md` is loaded — never the other cloud files. The project ID
and region are inputs the user supplies, not values the skill invents.

## Phase 1 — Research (Doc-Specialist)

Schema for `google_compute_network`, `google_compute_subnetwork` and
`google_compute_firewall` is verified against
`registry.terraform.io/providers/hashicorp/google/latest/docs`. The current latest
stable `google` major resolves to **v8.x**, written as `~> 8.0`, with
`required_version = "~> 1.13"` for the Terraform runtime. No preview fields are
needed, so `google-beta` is not added; if it ever is, it takes the same constraint
and is upgraded together with `google`. SESSION CONFIG is updated:

```
- Resolved provider versions: hashicorp/google ~> 8.0; terraform ~> 1.13
```

## Phase 2 — Generation (HCL-Architect)

A modular layout is scaffolded — a root calling a composite `network` module:

```
gcp-vpc/
├── versions.tf
├── providers.tf       # google provider, project and region
├── main.tf            # calls module "network"
├── variables.tf
├── outputs.tf
├── terraform.tfvars.example
└── modules/
    └── network/
        ├── main.tf    # VPC + subnets + firewall rules
        ├── variables.tf
        └── outputs.tf
```

Three GCP-specific controls shape the code:

- The VPC is custom mode (`auto_create_subnetworks = false`), so no default subnet
  is created in every region. Subnets use `for_each` over a name→CIDR map (not
  `count`), so adding or removing a subnet never shifts the others.
- `private_ip_google_access = true` lets instances without external IPs reach
  Google APIs.
- GCP has three tagging systems that are not interchangeable: labels, network
  tags and resource-manager tags. VPC networks, subnetworks and firewall rules
  take no `labels`, so there is nothing to label here. Firewall rules target
  instances by **network tag** (`target_tags`).

The core of the module looks like this:

```hcl
resource "google_compute_network" "this" {
  name                    = "vpc-${var.workload}-${var.environment}"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "private" {
  for_each = var.private_subnets # name => CIDR

  name                     = each.key
  ip_cidr_range            = each.value
  region                   = var.region
  network                  = google_compute_network.this.id
  private_ip_google_access = true
}

resource "google_compute_firewall" "allow_iap_ssh" {
  name      = "fw-${var.workload}-allow-iap-ssh"
  network   = google_compute_network.this.name
  direction = "INGRESS"

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["35.235.240.0/20"] # Identity-Aware Proxy TCP forwarding
  target_tags   = ["ssh-iap"]
}
```

A second rule allows traffic between instances inside the VPC. Code is presented
for review before any `.tf` file is written.

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

The state-backed plan uses the user's Google credentials (for example Application
Default Credentials) to read state and refresh; it creates nothing. Every line of
the plan is `+ create` and the `jq` filter prints nothing, so the stop-and-confirm
gate (§2 of `SKILL.md`) does not trigger. That is expected in a greenfield: with no
existing state there is nothing to replace. In a brownfield, a replaced GKE cluster
or Cloud SQL instance would be listed here and would stop the handoff.

---

## Phase 4 — Handoff (final report)

```
# Final Report

## Modular Map
gcp-vpc/
├── versions.tf
├── providers.tf
├── main.tf
├── variables.tf
├── outputs.tf
├── terraform.tfvars.example
└── modules/network/{main,variables,outputs}.tf

## Plan Summary
- Add: 6        # 1 VPC, 3 subnets, 2 firewall rules
- Change: 0
- Destroy: 0
- Replacements: none

## Output Contract
- Assumptions and version floor: hashicorp/google ~> 8.0, terraform ~> 1.13;
  project ID and region supplied as inputs; Compute Engine API already enabled in
  the project; for_each keyed on subnet name; three private subnets, no external
  IPs.
- Failure modes addressed: identity churn (for_each over count).
- Tradeoffs: composite network module over inline resources for reuse; IAP range
  for SSH instead of an external IP or bastion; no Cloud NAT or Cloud Router yet
  (no egress requirement stated).
- Rollback / recovery: discard the branch before apply; no state exists yet,
  so there is nothing to import or move.

## Handoff
Code is staged and validated. Manual `terraform apply tfplan` is required.
```

The user reviews `tfplan` and runs the apply themselves —
the skill never does.
