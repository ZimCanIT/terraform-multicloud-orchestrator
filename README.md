# Terraform Multi-Cloud Orchestrator

A plan-only, failure-mode-first Terraform agent skill for **AWS, Azure, GCP and Oracle Cloud (OCI)**.

The skill diagnoses the failure modes most likely to bite — identity churn, blast radius, state migration, compliance gates — before it writes any HCL. It asks once which cloud(s) you are targeting and how you want provider versions pinned, persists that answer for the session, then loads only the per-cloud reference it actually needs. It never runs `apply` or `destroy`.

This repository is three things at once:

1. A **Claude Code plugin marketplace** — add it once, install the plugin, done.
2. A **Codex-compatible plugin package** — the plugin root includes `.codex-plugin/plugin.json` and a bundled `skills/` directory.
3. A **portable Agent Skill** — the `skills/terraform-multicloud-orchestrator/` folder is a self-contained `SKILL.md` plus references, scripts, assets, and eval queries that drops into any agent that supports the Agent Skills standard.

---

## Quick install

Use one of these paths.

### Direct skill load

Use this when your agent supports loading an Agent Skill directly from a public repository URL:

```text
load this skill https://github.com/ZimCanIT/terraform-multicloud-orchestrator/tree/main/plugins/terraform-multicloud-orchestrator/skills/terraform-multicloud-orchestrator
```

This loads only the portable skill folder.

### Claude Code plugin install

Use this when you want the marketplace-backed Claude Code plugin:

```text
/plugin marketplace add ZimCanIT/terraform-multicloud-orchestrator
/plugin install terraform-multicloud-orchestrator@zimcanit-marketplace
```

Run those as Claude Code slash commands inside Claude Code itself.

If you are in a normal terminal window instead of inside Claude Code, use the CLI equivalent:

```bash
claude plugin marketplace add ZimCanIT/terraform-multicloud-orchestrator
claude plugin install terraform-multicloud-orchestrator@zimcanit-marketplace
```

Do not paste `claude plugin ...` as plain chat text inside Claude Code. That only sends the text to the model; it does not execute the command.

For local development from a checkout:

```text
/plugin marketplace add C:\Users\sumjsaniso\Documents\projects\terraform-orchestrator-skill
/plugin install terraform-multicloud-orchestrator@zimcanit-marketplace
```

Terminal equivalent:

```bash
claude plugin marketplace add C:\Users\sumjsaniso\Documents\projects\terraform-orchestrator-skill
claude plugin install terraform-multicloud-orchestrator@zimcanit-marketplace
```

After install, restart Claude Code so the newly installed skill is loaded at startup.

Update later inside Claude Code with:

```text
/plugin marketplace update zimcanit-marketplace
```

### Codex marketplace install

```bash
codex plugin marketplace add ZimCanIT/terraform-multicloud-orchestrator
codex plugin install terraform-multicloud-orchestrator@zimcanit-marketplace
```

For local development from a checkout:

```bash
codex plugin marketplace add C:\Users\sumjsaniso\Documents\projects\terraform-orchestrator-skill
codex plugin install terraform-multicloud-orchestrator@zimcanit-marketplace
```

## What it does

- **Cloud-agnostic spine, per-cloud leaves.** The workflow, safety policy, pinning logic and state mechanics are cloud-neutral. Cloud-specific facts (ForceNew traps, expensive-to-recreate resources, provider-upgrade notes, tagging semantics, policy tooling, module namespaces) live in `references/aws.md`, `azure.md`, `gcp.md`, `oci.md` and load on demand.
- **Ask once, then persist.** On first use it asks for target cloud(s) and a pinning strategy (`exact` / `pessimistic-minor` / `pessimistic-patch` / `latest-stable-and-pin`), emits a `SESSION CONFIG` block, and treats it as authoritative for the rest of the session.
- **Plan-only by policy.** `apply`, `destroy` and `-auto-approve` are forbidden. The agent runs only `init`, `validate`, `plan`, `show`, `state list`, `fmt`, `get`, `providers`. Any planned replacement of an expensive resource triggers a stop-and-confirm gate.
- **Structured output.** Every response carries a response contract: assumptions and version floor, risk category addressed, remediation and tradeoffs, a validation plan, and rollback notes.

## Authoring with provider MCP servers (fix-forward)

The skill favours a **fix-forward** approach: rather than destroying and recreating, you author a corrective change and re-plan. That only works when the HCL matches the provider's *current* schema, so pair the skill with the relevant cloud provider's registered [MCP](https://modelcontextprotocol.io) server. The skill drives failure-mode diagnosis, generation and plan-only validation; the MCP server grounds it in live, authoritative provider documentation so generated and corrected resources stay accurate against the latest API.

For example, the [Microsoft Learn MCP server](https://learn.microsoft.com) gives the agent live access to current Azure and `azurerm` documentation. Installation instructions: [Grounding Claude Code with the Microsoft Learn MCP Server](https://medium.com/@zimcanit/grounding-claude-code-with-the-microsoft-learn-mcp-server-9b2f2d517fb7). Register the equivalent provider MCP server for whichever cloud(s) you target.

## Portable skill path

The skill lives at:

```
plugins/terraform-multicloud-orchestrator/skills/terraform-multicloud-orchestrator/
├── SKILL.md
├── eval_queries.json
├── assets/
├── scripts/
└── references/
    ├── identity-churn.md   blast-radius.md   migration-playbooks.md   compliance-gates.md
    └── aws.md   azure.md   gcp.md   oci.md
```

If direct URL loading is unavailable, copy that folder into the agent's skills directory. Common locations are listed below — verify against your agent's current documentation, as paths change between versions:

| Agent | Typical skills directory |
|---|---|
| Claude Code (manual) | `~/.claude/skills/terraform-multicloud-orchestrator/` |
| Cursor / other agents | `.agents/skills/` or the agent's configured skills path |
| Gemini CLI | `.gemini/skills/terraform-multicloud-orchestrator/` |

The skill triggers automatically when its description matches your task — no slash command required.

---

## Layout

```
terraform-orchestrator-skill/              # repository root
├── .agents/
│   └── plugins/
│       └── marketplace.json               # Codex marketplace catalog
├── .claude-plugin/
│   └── marketplace.json                   # Claude Code marketplace catalog
├── plugins/
│   └── terraform-multicloud-orchestrator/
│       ├── .codex-plugin/
│       │   └── plugin.json                # Codex plugin manifest
│       ├── .claude-plugin/
│       │   └── plugin.json                # plugin manifest
│       └── skills/
│           └── terraform-multicloud-orchestrator/
│               ├── SKILL.md               # cloud-agnostic spine (authoritative copy)
│               ├── eval_queries.json       # trigger regression set
│               ├── assets/                 # output templates
│               ├── scripts/                # reusable validation chain
│               └── references/            # 4 mechanism + 4 per-cloud files
├── examples/
│   └── aws-vpc/README.md                  # sample session walkthrough
├── README.md
├── CONTRIBUTING.md
├── CHANGELOG.md
└── LICENSE
```

## Validation

Before publishing, run the checks in [`CONTRIBUTING.md`](./CONTRIBUTING.md).

Install local pre-commit hooks:

```bash
python -m pip install pre-commit
pre-commit install
pre-commit run --all-files
```

On Windows, install the shell lint tools used by pre-commit:

```powershell
choco install shellcheck shfmt -y
refreshenv
```

If `pre-commit` cannot write to your default user cache, use a repo-local cache:

```powershell
$env:PRE_COMMIT_HOME=".tmp/pre-commit-cache"
pre-commit run --all-files
```

The minimum publish gates are:

```bash
# install once: python -m pip install skills-ref==0.1.1 (the package's CLI is named `agentskills`)
agentskills validate plugins/terraform-multicloud-orchestrator/skills/terraform-multicloud-orchestrator
python scripts/validate_codex_plugin.py
python scripts/validate_skill_frontmatter.py
```

The first gate runs in CI on every push and pull request (`.github/workflows/skill-validation.yml`); see [`CONTRIBUTING.md`](./CONTRIBUTING.md) for details.

---

## Safety

Plan-only. The skill stages and validates Terraform but never deploys; the `apply` step is always manual and out of scope. Note that "plan-only" means no `apply`/`destroy` — `terraform init` still downloads providers from the network and `terraform plan` executes `external` data source providers as local processes. Review your configuration before running plan commands against untrusted modules.

### Hard enforcement (optional)

In Claude Code the skill's `allowed-tools` is scoped to the plan-only commands, so `apply`/`destroy` are never auto-approved. Because `allowed-tools` grants rather than blocks, add `deny` rules to your own `.claude/settings.json` for a hard stop that holds regardless of permission mode:

```json
{
  "permissions": {
    "deny": [
      "Bash(terraform apply:*)",
      "Bash(terraform destroy:*)",
      "Bash(terraform state rm:*)",
      "Bash(terraform state mv:*)",
      "Bash(terraform state push:*)",
      "Bash(terraform import:*)",
      "Bash(terraform taint:*)",
      "Bash(terraform untaint:*)",
      "Bash(tofu apply:*)",
      "Bash(tofu destroy:*)"
    ]
  }
}
```

Codex and other agents do not interpret these `Bash(...)` qualifiers; on those platforms plan-only rests on the skill's behavioural policy.

## Attribution and licence

The failure-mode-first methodology is inspired by [TerraShark](https://github.com/LukasNiessen/terrashark) (MIT). The diagnose-first routing and response-contract structure are inspired by [Anton Babenko's terraform-skill](https://github.com/antonbabenko/terraform-skill) (Apache-2.0). All reference content here is original. Licensed under [MIT](./LICENSE).
