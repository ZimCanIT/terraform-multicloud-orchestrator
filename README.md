# Terraform Multi-Cloud Orchestrator

A plan-only, failure-mode-first Terraform agent skill for **AWS, Azure, GCP and Oracle Cloud (OCI)**.

Before it writes any HCL, the skill checks the failure modes most likely to bite: identity churn, blast radius, state migration and compliance gates. On first use it asks which clouds you target and how you want provider versions pinned. It keeps those answers for the session and loads only the reference files for the clouds you named.

`apply` and `destroy` are restricted. The skill never runs them and never pre-approves them. See [Safety](#safety).

This repository ships three things:

- **A Claude Code plugin marketplace.** Add it once, then install the plugin.
- **A Codex plugin package.** The plugin includes `.codex-plugin/plugin.json` and a bundled `skills/` folder.
- **A portable Agent Skill.** The `skills/terraform-multicloud-orchestrator/` folder is self-contained: `SKILL.md`, references, scripts, assets and eval queries.

## Install

### Claude Code

Run these inside Claude Code:

```text
/plugin marketplace add ZimCanIT/terraform-multicloud-orchestrator
/plugin install terraform-multicloud-orchestrator@zimcanit-marketplace
```

Restart Claude Code after installing. To get later releases, run `/plugin marketplace update zimcanit-marketplace`.

In a terminal, use `claude plugin marketplace add` and `claude plugin install` with the same arguments. Pasting `claude plugin` commands into a chat only sends them to the model as text, so they don't run.

For a local checkout, pass the checkout path to `marketplace add` instead of the GitHub name.

### Codex

```bash
codex plugin marketplace add ZimCanIT/terraform-multicloud-orchestrator
codex plugin install terraform-multicloud-orchestrator@zimcanit-marketplace
```

### Other Agent Skills agents

If your agent can load a skill from a URL, give it the skill folder:

```text
load this skill https://github.com/ZimCanIT/terraform-multicloud-orchestrator/tree/main/plugins/terraform-multicloud-orchestrator/skills/terraform-multicloud-orchestrator
```

Otherwise, copy that folder into the agent's skills directory. For Claude Code, that is `~/.claude/skills/`. Skill paths change between agent releases, so check your agent's documentation.

## How it works

- **Shared spine, per-cloud references.** The workflow, guardrails, pinning rules and state handling are cloud-neutral. Cloud facts live in `references/aws.md`, `azure.md`, `gcp.md` and `oci.md`: ForceNew traps, resources that are expensive to recreate, provider upgrade notes, tagging and policy tooling. Each file loads only when needed.
- **Ask once.** It asks for target clouds and a pinning strategy (`exact`, `pessimistic-minor`, `pessimistic-patch` or `latest-stable-and-pin`), then records both in a `SESSION CONFIG` block it follows for the rest of the session.
- **Plan-only.** It runs `init`, `validate`, `plan`, `show`, `state list`, `fmt`, `get` and `providers`, plus `jq` to read plan JSON. A planned replacement of an expensive resource triggers a stop-and-confirm gate.
- **Automatic.** It triggers when a request matches its description. There is no slash command.
- **A fixed response shape.** Each answer gives its assumptions and version floor, the risk it addresses, remediation and tradeoffs, a validation plan, and rollback notes.

## Safety

`apply` and `destroy` are restricted.

- The skill never runs `terraform apply` or `terraform destroy`, and never uses `-auto-approve`.
- It also refuses state-changing commands (`import`, `state mv`, `state rm`, `state push`, `force-unlock`) and cloud CLI or API calls that create, update or delete resources.
- If asked to deploy, it replies that apply and destroy are restricted, then tells you to review the plan and run apply yourself.
- Only the operator can lift the restriction, by editing the skill's guardrails. Requests in a session or in a standards document don't override them.

"Plan-only" doesn't mean offline. `terraform init` downloads providers, and `terraform plan` runs `external` data sources as local processes. Review a configuration before you plan against a module you don't trust. Plan files can contain secrets: add `tfplan` and `plan_output.json` to `.gitignore`, and never paste them.

### Enforce it in Claude Code (optional)

The skill's `allowed-tools` grants commands rather than blocking them. To block the restricted commands outright, add these deny rules to `.claude/settings.json`:

```json
{
  "permissions": {
    "deny": [
      "Bash(terraform apply:*)",
      "Bash(terraform destroy:*)",
      "Bash(terraform import:*)",
      "Bash(terraform state rm:*)",
      "Bash(terraform state mv:*)",
      "Bash(terraform state push:*)",
      "Bash(terraform force-unlock:*)",
      "Bash(terraform taint:*)",
      "Bash(terraform untaint:*)",
      "Bash(tofu apply:*)",
      "Bash(tofu destroy:*)",
      "Bash(tofu import:*)",
      "Bash(tofu state rm:*)",
      "Bash(tofu state mv:*)",
      "Bash(tofu state push:*)",
      "Bash(tofu force-unlock:*)",
      "Bash(tofu taint:*)",
      "Bash(tofu untaint:*)"
    ]
  }
}
```

Treat these as a guard rail, not a security boundary. Deny rules match the command text, so `terraform -chdir=envs/prod apply` and `sh -c 'terraform apply'` can get past them. For a hard stop, give the agent credentials that can read and plan but not write, or add a PreToolUse hook that inspects the full command. Codex and other agents don't read `Bash(...)` rules, so there plan-only rests on the skill's instructions and the credentials you supply.

## Validation

Install the hooks once, then run them before you publish:

```bash
python -m pip install pre-commit
pre-commit install
pre-commit run --all-files
```

[CONTRIBUTING.md](CONTRIBUTING.md) covers the shell tools the hooks need, and the repo-local cache to use if pre-commit can't write to your default one. The minimum gates are:

```bash
python -m pip install skills-ref==0.1.1   # provides the agentskills CLI
agentskills validate plugins/terraform-multicloud-orchestrator/skills/terraform-multicloud-orchestrator
python scripts/validate_codex_plugin.py
python scripts/validate_skill_frontmatter.py
python scripts/validate_versions.py
```

CI runs `agentskills validate` (`.github/workflows/skill-validation.yml`) and the full pre-commit set (`.github/workflows/pre-commit.yml`) on every push to `main` and on every pull request.

Releases are automated with release-please, so write commit messages in Conventional Commit style. See [CONTRIBUTING.md](CONTRIBUTING.md) for the rest.

## Layout

```text
.claude-plugin/marketplace.json      Claude Code marketplace catalog
.agents/plugins/marketplace.json     Codex marketplace catalog
plugins/terraform-multicloud-orchestrator/
├── .claude-plugin/plugin.json
├── .codex-plugin/plugin.json
└── skills/terraform-multicloud-orchestrator/
    ├── SKILL.md                     workflow, guardrails, response contract
    ├── eval_queries.json            trigger regression set
    ├── assets/                      session config and report templates
    ├── scripts/validate.sh          static and plan validation chain
    └── references/                  4 mechanism files and 4 per-cloud files
examples/                            sample sessions for AWS, Azure and GCP
scripts/                             repository validators
```

## Pair it with provider docs

The skill favours fix-forward: correct the HCL and re-plan, rather than destroy and recreate. That only works if the HCL matches the provider's current schema, so connect the documentation MCP server for each cloud you target. For Azure, the [Microsoft Learn MCP server](https://learn.microsoft.com) gives live access to current Azure and `azurerm` documentation. [This article](https://medium.com/@zimcanit/grounding-claude-code-with-the-microsoft-learn-mcp-server-9b2f2d517fb7) covers setup.

## Licence and attribution

The failure-mode-first method is inspired by [TerraShark](https://github.com/LukasNiessen/terrashark) (MIT). The diagnose-first routing and response contract are inspired by [Anton Babenko's terraform-skill](https://github.com/antonbabenko/terraform-skill) (Apache-2.0). The reference content is original. Licensed under [MIT](LICENSE).
