# Self-hosted server companion

This fork of `thedotmack/claude-mem` adds a complete **self-hosted
Chroma server architecture** that turns claude-mem from a per-machine
plugin into a **cross-device, cross-LLM, cross-environment personal
shared-memory server**.

Every AI assistant you use — Claude Code, Claude Desktop, Codex,
Cursor, Antigravity, Continue.dev, Cline, Cowork sandboxes, your phone
— reads and writes to the same memory pool. You own the host. Data
lives in your house.

## What's in [`self-hosted-server/`](./self-hosted-server/)

- **`ha-addon/`** — Home Assistant add-on package (Chroma 1.5.x, /share/
  persistent, HA-backup integrated)
- **`client/`** — Universal `SKILL.md` + `claude-mem` CLI that any AI
  tool can use (Claude Code via skill discovery, others via shell out
  or rules files)
- **`extensions/git-handoff/`** — For sandboxed agents with no network
  egress: append a session log to a repo, push, ingester writes it to
  Chroma on your always-on machine
- **`extensions/tailscale-sandbox/`** — Ephemeral Tailscale auth-key
  recipe for disposable cloud containers
- **`docs/`** — Architecture, schema, backup/restore, troubleshooting,
  client integrations

## Quick start

**For humans**: read [`self-hosted-server/README.md`](./self-hosted-server/README.md)
then [`self-hosted-server/docs/ARCHITECTURE.md`](./self-hosted-server/docs/ARCHITECTURE.md)
then [`self-hosted-server/ha-addon/README.md`](./self-hosted-server/ha-addon/README.md).

**For AI agents helping a user deploy this**: read
[`self-hosted-server/INSTALL-FOR-AGENTS.md`](./self-hosted-server/INSTALL-FOR-AGENTS.md)
end-to-end first. It's a phased runbook with verification gates,
prerequisite checks, and failure-mode tables designed for autonomous
execution.

## Relationship to upstream `thedotmack/claude-mem`

The upstream plugin in the rest of this repo is fully unmodified and
keeps working as-is. The self-hosted server layer is **additive**:

- Point upstream's worker at the self-hosted Chroma instead of running
  Chroma locally on every machine
- One config change in `~/.claude-mem/settings.json` per machine
  (template in `self-hosted-server/client/settings-template.json`)

You can also use the self-hosted server **without** the upstream plugin
— the universal CLI in `self-hosted-server/client/skill/claude-mem`
covers the core operations (search, add-narrative, add-fact, list-
decisions, list-blockers, get-session, health) without any plugin
dependency.

## License

MIT, same as upstream.
