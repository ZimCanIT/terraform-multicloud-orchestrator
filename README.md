# Terraform Authoring Companion for Azure

A plan-only agent skill that writes, reviews and refactors Terraform for **Microsoft Azure** (`azurerm` and `azapi`) to a stated standard.

It works the way a senior platform engineer pairs on infrastructure code. It reads the repository first and decides which stack and module a change belongs to. It writes typed, validated HCL with Azure naming, managed identities, private networking and secure defaults. It checks every argument against the provider version you pin, reviews its own output against a checklist, and validates with plan-only commands.

`apply` and `destroy` are restricted. The skill never runs them and never pre-approves them. See [Safety](#safety).

> Formerly `terraform-multicloud-orchestrator`: the skill was refocused on Azure and renamed to `azure-tf-author`. GitHub redirects the old repository URL, and existing installs of the old name keep working, but new installs should use the new name. AWS, GCP and OCI are out of scope.

This repository ships three things:

- **A Claude Code plugin marketplace.** Add it once, then install the plugin.
- **A Codex plugin package.** The plugin includes `.codex-plugin/plugin.json` and a bundled `skills/` folder.
- **A portable Agent Skill.** The `skills/azure-tf-author/` folder is self-contained: `SKILL.md`, references, scripts and assets.

## Install

### Claude Code

Run these inside Claude Code:

```text
/plugin marketplace add ZimCanIT/azure-tf-author
/plugin install azure-tf-author@zimcanit-marketplace
```

Restart Claude Code after installing. To get later releases, run `/plugin marketplace update zimcanit-marketplace`.

In a terminal, outside Claude Code, run these two commands:

```bash
claude plugin marketplace add ZimCanIT/azure-tf-author
claude plugin install azure-tf-author@zimcanit-marketplace
```

Inside Claude Code, use the `/plugin` commands above instead. Typing `claude plugin` at the Claude Code prompt sends it to the model as plain text, not a command.

For a local checkout, replace `ZimCanIT/azure-tf-author` with the path to the repository root, for example `~/src/azure-tf-author`.

### Codex

```bash
codex plugin marketplace add ZimCanIT/azure-tf-author
codex plugin install azure-tf-author@zimcanit-marketplace
```

### Other Agent Skills agents

If your agent can load a skill from a URL, give it the skill folder:

```text
load this skill https://github.com/ZimCanIT/azure-tf-author/tree/main/plugins/azure-tf-author/skills/azure-tf-author
```

Otherwise, copy that folder into the agent's skills directory. For Claude Code, that is `~/.claude/skills/`. Skill paths change between agent releases, so check your agent's documentation.

## How it works

- **A standard with rule IDs.** `SKILL.md` §3 lists 26 rules in four groups: structure and state, modules and interfaces, language, and the Azure platform. The code it writes follows them, and a review cites them by ID.
- **References by task.** Ten reference files load only when the task needs them: HCL standards, module design, naming and tagging, the secure baseline by resource type, networking, identity and secrets, state and environments, the providers, adopting and refactoring existing resources, and testing and delivery.
- **Checked against the provider.** Argument names change between `azurerm` majors. The skill uses the version the repository pins and checks arguments against the registry page for that version.
- **A reference stack.** `assets/reference-stack/` is a small root module with three reusable modules (a storage account, a Key Vault and a virtual network) written to the standard. CI runs `terraform validate` and the modules' plan-mode tests on it.
- **Reads first, asks little.** It follows the conventions already in the repository and asks only for what blocks correct code, once.
- **Plan-only.** It runs only the exact permitted forms: `init`, `validate`, `fmt -check -recursive`, `plan -out=tfplan`, `show -json tfplan`, `providers` and `state list`. Reading plan JSON with `jq` needs your approval. A planned deletion or replacement of a resource on its stop list makes it stop and ask.
- **Automatic.** It triggers when a request matches its description.

## Try it

- "Add a private storage account for the orders workload in UK South, with diagnostics."
- "Review `modules/network` against your standard. Blockers first."
- "Bring the resources in `rg-legacy-prod` under Terraform without replacing anything."
- "Upgrade this stack from azurerm 4 to 5."

## Safety

`apply` and `destroy` are restricted, and so is every other `terraform` or `tofu` subcommand that is not on the permitted list.

- The permitted commands are exact forms: `init`, `validate`, `fmt -check -recursive`, `plan -out=tfplan`, `show -json tfplan`, `providers`, and `state list`. Reading plan JSON with `jq` needs your approval.
- The skill never runs `terraform apply` or `terraform destroy`, never uses `-auto-approve`, and refuses named extras such as `test`, `taint`, `refresh` and `state rm`.
- `az` commands and REST calls that create, update, delete or set resources are forbidden.
- If asked to deploy, it replies that apply and destroy are restricted, then tells you to review the plan and run apply yourself.
- An operator can lift any of these restrictions by editing the skill's guardrails. Requests in a session or in a standards document don't override them.

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
      "Bash(tofu untaint:*)",
      "Bash(terraform test:*)",
      "Bash(terraform refresh:*)",
      "Bash(terraform workspace:*)",
      "Bash(terraform login:*)",
      "Bash(terraform state replace-provider:*)",
      "Bash(terraform providers mirror:*)",
      "Bash(terraform init -migrate-state:*)",
      "Bash(terraform init -reconfigure:*)",
      "Bash(terraform init -from-module:*)",
      "Bash(terraform plan -generate-config-out:*)",
      "Bash(terraform plan -lock=false:*)",
      "Bash(terraform plan -destroy:*)",
      "Bash(terraform plan -target:*)",
      "Bash(terraform plan -replace:*)",
      "Bash(tofu test:*)",
      "Bash(tofu refresh:*)",
      "Bash(tofu workspace:*)",
      "Bash(tofu login:*)",
      "Bash(tofu state replace-provider:*)",
      "Bash(tofu providers mirror:*)",
      "Bash(tofu init -migrate-state:*)",
      "Bash(tofu init -reconfigure:*)",
      "Bash(tofu init -from-module:*)",
      "Bash(tofu plan -generate-config-out:*)",
      "Bash(tofu plan -lock=false:*)",
      "Bash(tofu plan -destroy:*)",
      "Bash(tofu plan -target:*)",
      "Bash(tofu plan -replace:*)",
      "Bash(terragrunt run-all:*)"
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
agentskills validate plugins/azure-tf-author/skills/azure-tf-author
python scripts/validate_codex_plugin.py
python scripts/validate_skill_frontmatter.py
python scripts/validate_versions.py
```

CI runs `agentskills validate` (`.github/workflows/skill-validation.yml`) and the full pre-commit set (`.github/workflows/pre-commit.yml`) on every push to `main` and on every pull request.

On Windows, run `scripts/validate.sh` and the pre-commit hooks from Git Bash or WSL — they are bash scripts. The `terraform` and `tofu` CLIs run natively on Windows; install `jq` with `winget install jqlang.jq` (or `scoop install jq`) and make sure everything is on the `PATH` that Git Bash sees.

Releases are automated with release-please, so write commit messages in Conventional Commit style. See [CONTRIBUTING.md](CONTRIBUTING.md) for the rest.

## Layout

```text
.claude-plugin/marketplace.json      Claude Code marketplace catalog
.agents/plugins/marketplace.json     Codex marketplace catalog
plugins/azure-tf-author/
├── .claude-plugin/plugin.json
├── .codex-plugin/plugin.json
└── skills/azure-tf-author/
    ├── SKILL.md                     workflow, guardrails, the authoring standard
    ├── references/                  10 task references for Azure
    ├── assets/                      review checklist, hand-off template, reference stack
    └── scripts/validate.sh          static and plan validation chain
scripts/                             repository validators
tests/                               validator tests and the CI fixture
```

## Pair it with provider docs

The skill checks arguments against the provider's documentation, so give it a live source. The [Microsoft Learn MCP server](https://learn.microsoft.com) gives access to current Azure and `azurerm` documentation. [This article](https://medium.com/@zimcanit/grounding-claude-code-with-the-microsoft-learn-mcp-server-9b2f2d517fb7) covers setup.

## Licence and attribution

The diagnose-before-generate idea came from [TerraShark](https://github.com/LukasNiessen/terrashark) (MIT) and [Anton Babenko's terraform-skill](https://github.com/antonbabenko/terraform-skill) (Apache-2.0). The reference content is original. Licensed under [MIT](LICENSE).
