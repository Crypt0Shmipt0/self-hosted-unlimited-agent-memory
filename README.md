# Self-Hosted Unlimited Agent Memory

**Cross-LLM · Cross-device · Cross-environment · You own the data**

A self-hosted shared-memory backend so every AI you talk to — Claude Code,
Claude Desktop, Codex, Cursor, Antigravity, Continue.dev, Cline, Cowork
sandboxes, your phone, Windows, Linux, Android — reads and writes to the
*same* pool of memories. No vendor lock-in. No cloud dependency. Runs on
your home server.

```
   ┌────────────┐    ┌────────────┐    ┌────────────┐    ┌────────────┐
   │ Claude Code│    │   Codex /  │    │ Antigravity│    │ Cowork /   │
   │  on macOS  │    │   Cursor   │    │  on Linux  │    │  sandbox   │
   └─────┬──────┘    └─────┬──────┘    └─────┬──────┘    └─────┬──────┘
         │           HTTP / Tailscale          │          git-handoff
         └─────────────────┬───────────────────┘                │
                           ▼                                     │
              ┌─────────────────────┐                           │
              │  Your always-on box │  ◄────────────────────────┘
              │  (HA add-on or      │   Chroma 1.5.x vector DB
              │   plain Docker)     │   data on local disk
              │  + Tailscale mesh   │   HA-backed up daily
              └─────────────────────┘
```

---

## What's in this repo

This repo has two layers:

| Layer | What it is | Where |
|---|---|---|
| **claude-mem plugin** | The upstream Claude Code plugin by [@thedotmack](https://github.com/thedotmack/claude-mem) that captures session observations, compresses them with Claude, and injects context into future sessions. | (root — upstream code) |
| **Self-hosted server** | Everything needed to replace the per-machine local Chroma DB with a shared, always-on, self-hosted Chroma backend accessible from every device and every AI tool. | [`self-hosted-server/`](self-hosted-server/) |

You can use either layer independently:

- **Plugin only** — great if you just need per-machine memory for Claude Code.
- **Self-hosted server only** — use the CLI and SKILL.md with any AI tool, no claude-mem plugin required.
- **Both together** — the full setup: plugin generates observations automatically, self-hosted server makes them available everywhere.

---

## Why this exists

The default for AI assistants today: every session is a blank slate. You
re-explain context, restate conventions, repeat decisions. Vendor "memory"
features lock you to one platform and ship your data to their servers.

This project gives you the other path:

- **One pool, every tool.** Anything that speaks HTTP can read and write memories.
- **You own the host.** A Home Assistant add-on, or any always-on Linux box. Data stays on your disk.
- **Cross-device by default.** Tailscale (free for personal use) makes the endpoint reachable from anywhere on your tailnet — phone, laptop, cloud sandbox, all see the same memories.
- **Cross-environment.** Sandboxed AI sessions that can't reach your network sync via git instead.
- **Cross-LLM, cross-vendor.** The schema is plain Chroma metadata. No Anthropic-, OpenAI-, or Google-specific assumptions. Any AI that can execute a bash script or hit an HTTP endpoint can use it.
- **Survives outages.** Daily Home Assistant backups capture the Chroma data (HNSW segments + SQLite index) and can replicate to any HA-compatible remote backup target.

---

## Tool compatibility

| AI Tool | How it connects | What it gets |
|---|---|---|
| **Claude Code** | SKILL.md loaded by plugin, bash CLI | Auto-injected context + search |
| **Claude Desktop** | bash CLI via `run_bash_tool` / shell | search + add |
| **Codex / OpenAI Assistants** | bash CLI via code interpreter | search + add |
| **Cursor** | Cursor rules call bash CLI | search on file open |
| **Continue.dev** | `claude-mem` CLI as a slash command | search + add |
| **Cline** | SKILL.md + bash CLI | full read/write |
| **Antigravity** | SKILL.md loaded from iCloud/git | full read/write |
| **Cowork (no-egress sandbox)** | git-handoff extension | async write; read on next Mac session |
| **Any HTTP client** | Chroma REST API directly | full Chroma API |
| **Android / Termux** | bash CLI + Alpine proot | search + add |
| **Windows (PowerShell)** | bash CLI via WSL or git-bash | search + add |

---

## Components

### Home Assistant add-on

`self-hosted-server/ha-addon/` — a local HA add-on that runs Chroma 1.5.x as a
Supervisor-managed container. Data lands on `/share/claude-mem-chroma/` so it
survives add-on rebuilds and is captured by native HA backups.

Alternatively, use plain Docker — any Linux host with `docker run` works.

### Universal skill + CLI

`self-hosted-server/client/` contains two pieces:

- **`SKILL.md`** — a skill file your AI tool reads to learn how to use the
  memory server. Works with Claude Code skills, Codex system prompts, Cursor
  rules, Continue.dev slash commands, Cline tool definitions, or any
  prompt-injection surface that supports markdown files.

- **`claude-mem`** — a bash CLI with 7 subcommands:
  `health` · `search` · `get-session` · `list-decisions` · `list-blockers` ·
  `add-narrative` · `add-fact`

  Uses `uvx + chromadb` — no Node, no Go, no compiled binary. Runs anywhere
  Python 3.10+ and `uv` are available.

### Git-handoff extension

`self-hosted-server/extensions/git-handoff/` — for sandboxed AI agents with no
network egress. The agent appends a structured `## Session` block to a git
repo, commits and pushes. A Mac/Linux ingester (`ingest-session.py`) pulls the
repo and writes the session data to the shared Chroma pool.

Solves: "my cloud AI sandbox can't reach my home network."

### Tailscale sandbox extension

`self-hosted-server/extensions/tailscale-sandbox/` — ephemeral auth-key recipe
so disposable cloud containers can join your tailnet for the duration of one
session, reach the memory server directly, then auto-expire.

### Architecture docs

`self-hosted-server/docs/`:

| Doc | What it covers |
|---|---|
| `ARCHITECTURE.md` | Full design rationale, component diagram, data flow |
| `SCHEMA.md` | Chroma collection schema — every field, filter patterns, query examples |
| `BACKUP-RESTORE.md` | HA backup structure, decryption steps, restore runbook |
| `TROUBLESHOOTING.md` | Common failures (Chroma version, ENTRYPOINT, musl, multi-key where filters) |
| `CLIENT-INTEGRATIONS.md` | Per-tool integration guide for every AI tool in the compatibility table |

---

## Quickstart

### Human setup

1. **Read [`self-hosted-server/docs/ARCHITECTURE.md`](self-hosted-server/docs/ARCHITECTURE.md)** — understand the design before deploying.
2. **Deploy the server** — [`self-hosted-server/ha-addon/`](self-hosted-server/ha-addon/) for Home Assistant, or `docker run chromadb/chroma:1.5.9` for plain Docker.
3. **Wire Tailscale** — install on your server and every client device.
4. **Install the client** — copy `self-hosted-server/client/claude-mem` to your PATH and drop `self-hosted-server/client/skill/SKILL.md` where your AI tool loads skills.
5. **Configure each AI tool** — see [`self-hosted-server/docs/CLIENT-INTEGRATIONS.md`](self-hosted-server/docs/CLIENT-INTEGRATIONS.md).

### AI agent setup

Read [`self-hosted-server/INSTALL-FOR-AGENTS.md`](self-hosted-server/INSTALL-FOR-AGENTS.md) end-to-end first.
It's an 8-phase runbook with prerequisite checks, decision trees, and
verification gates written for autonomous agent execution.

---

## Status

Built and battle-tested in personal use. The reference deployment runs across:

- macOS (Claude Code, Claude Desktop, native CLI)
- Linux (Cowork / cloud sandboxes via git-handoff)
- Windows 11 (Claude Code, PowerShell)
- Android (Termux + Alpine proot)

Memory pool on the reference deployment: 5000+ observations across multiple
project tags. Daily backups include the full vector index + HNSW segments,
encrypted, replicated offsite.

---

## Upstream plugin

The Claude Code plugin in this repo is [@thedotmack/claude-mem](https://github.com/thedotmack/claude-mem).
It handles automatic observation capture (6 lifecycle hooks), AI-powered
compression, and context injection for Claude Code sessions. Plugin docs and
installation: see the upstream repo.

The self-hosted server layer in `self-hosted-server/` is an independent
addition that replaces the per-machine local Chroma DB with a shared backend.

---

## Architecture in one sentence

Every AI session writes structured observations to a Chroma vector DB you
host; every future session queries it via semantic search and gets relevant
past context injected automatically — across all your devices, all your AI
tools, forever.

---

## License

MIT — see [LICENSE](LICENSE).

## Contributing

PRs welcome. High-leverage contributions:

1. **Adapter configs** for specific AI tools (Cursor rules, Continue.dev YAML,
   Cline tool defs) — see [`self-hosted-server/docs/CLIENT-INTEGRATIONS.md`](self-hosted-server/docs/CLIENT-INTEGRATIONS.md).
2. **MCP server wrapper** so MCP-capable clients (Claude Desktop, Cursor MCP)
   can use the memory pool as a first-class tool without the bash CLI layer.
3. **Docker Compose recipe** for non-HA Linux deployments.
