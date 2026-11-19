# Forge Setup and Maintenance

Forge provides this project’s shared AI skills and development workflow.

## Plugin Setup

The shared skills live in `agents/plugins/forge/skills/` and are packaged as one plugin named `forge` for Codex and Claude Code. Each provider manifest lives inside `agents/plugins/forge/`; repository catalogs point to that same source. Initialization prepares these files; installation, enablement, and loading into a session are separate host steps. Forge never runs provider commands or edits home configuration.

Each newly generated catalog is named `forge-` plus the first 16 SHA-256 characters of the real absolute project path. Read its exact `name` from `.agents/plugins/marketplace.json` or `.claude-plugin/marketplace.json`. Existing user catalogs keep their identity and unrelated entries.

For Codex desktop or CLI, register this repository through the host marketplace flow (`codex plugin marketplace add <absolute-project-root>`), install `forge@<catalog-name>` from that source (`codex plugin add forge@<catalog-name>`), and start a new thread. Use the Forge skills shown by the host. The Codex IDE extension does not support plugins. Codex enablement is user-level: select the current project's Forge source and disable conflicting Forge variants through the host UI. Distinct catalogs separate sources; automatic project isolation is not established.

For Claude Code, register the repository with `claude plugin marketplace add <absolute-project-root>`, then run `claude plugin install forge@<catalog-name> --scope project`. Open a trusted project session and invoke `/forge:initialize-project`, `/forge:create-task`, or the other Forge skills. These are setup commands for the user; Forge does not execute them.

After editing a skill or creating one through `create-project-skill`, refresh the installed copy before testing. For Codex, use the installed `plugin-creator` skill's `scripts/update_plugin_cachebuster.py` on this project's plugin, reinstall from the confirmed local marketplace, then start a new thread. For Claude, increment the version in `agents/plugins/forge/.claude-plugin/plugin.json`, update `forge@<catalog-name>` with project scope, then use `/reload-plugins` or start a new session. Provider versions are independent; a Codex cache suffix does not prove Claude refreshed. Keep local version changes when resolving a Forge update conflict.

Project-created skills belong in this plugin and remain project-owned. Resolve skill helpers from the loaded skill directory, pass this repository root explicitly, and edit project sources rather than an installed cache. Bootstrap helper commands can run directly from this checkout before host activation. Host discovery, cache refresh, and switching between two project sources still require live verification; filesystem validation alone cannot prove those behaviors.

See the official [Codex packaging](https://developers.openai.com/plugins/build/plugins), [Codex plugin usage](https://learn.chatgpt.com/docs/plugins), and [Claude plugin documentation](https://code.claude.com/docs/en/plugins) for host setup details.

## Methodology Maintenance

Projects created by Forge include `.forge/managed-files.json`, which records fingerprints only for Forge-managed skills, helper scripts, plugin manifests and catalogs, and the exact Forge-owned GitHub workflows. From the repository root, `forge init --existing --dry-run` previews safe methodology updates. Running without `--dry-run` refreshes unchanged managed content and restores missing entries while reporting local customizations as conflicts. Other project workflows remain unmanaged.

## Branch Cleanup

The pull-request workflow deletes merged branches from this repository except `development`, `main`, and the repository's default branch. Keep GitHub's native **Automatically delete head branches** setting disabled so the workflow remains the single branch-deletion policy.
