# Personal Memory Server

**One memory pool. All your AI assistants. All your devices.**

A self-hosted shared-memory backend so every AI you talk to — Claude Code,
Claude Desktop, Codex/Cursor, Antigravity, Continue.dev, Cline, Cowork
sandboxes, your phone — reads and writes to the *same* set of memories.
You own the data. It lives in your house.

```
   ┌────────────┐    ┌────────────┐    ┌────────────┐
   │   Claude   │    │   Codex    │    │ Antigravity│  …any AI tool
   │   on Mac   │    │ on Windows │    │ on Linux   │   that can hit HTTP
   └─────┬──────┘    └─────┬──────┘    └─────┬──────┘
         │  HTTP / Tailscale │                │
         └─────────┬─────────┴────────────────┘
                   ▼
        ┌─────────────────────┐
        │   Your HA / Linux   │   self-hosted Chroma 1.5.x
        │   box on your LAN   │   as an HA add-on (or plain docker)
        │   + Tailscale       │   data on local disk, backed up by HA
        └─────────────────────┘
```

## Why this exists

The default for AI assistants today: every session is a blank slate. You
re-explain context, restate conventions, repeat decisions. Vendor
"memory" features lock you to one platform and ship your data to their
servers.

This project gives you the other path:

- **One pool, every tool.** Anything that speaks HTTP can read/write.
- **You own the host.** A Home Assistant add-on, or any always-on Linux
  box. Data sits on your disk.
- **Cross-device by default.** Tailscale (free for personal use) makes
  the endpoint reachable from anywhere on your tailnet — phone, laptop,
  cloud sandbox, all see the same memories.
- **Cross-environment.** Sandboxed AI sessions (Cowork, ChatGPT
  Projects, etc.) that can't reach your network sync via git instead.
- **Cross-LLM, cross-vendor.** The schema is plain Chroma metadata. No
  Anthropic-, OpenAI-, or Google-specific assumptions.
- **Survives outages.** Daily Home Assistant backups capture the
  Chroma data and replicate to Nabu Casa Cloud (or any HA-compatible
  remote backup target).

## What you get

| Component | What it is |
|---|---|
| **Home Assistant add-on** (`ha-addon/`) | A local add-on that runs Chroma 1.5.x as a Supervisor-managed container with the data dir on `/share/` so it survives add-on rebuilds and is captured by HA backups. |
| **Universal skill + CLI** (`client/`) | A `SKILL.md` your AI tool reads to know how to use the server, plus a `claude-mem` bash CLI any tool can shell out to (`search`, `add-narrative`, `add-fact`, `list-decisions`, `list-blockers`, `get-session`, `health`). |
| **Git-handoff extension** (`extensions/git-handoff/`) | For sandboxed AI agents with no network egress: append a structured session log to a repo, push, and a Mac/Linux-side ingester pulls + writes to the shared pool. Solves the "Cowork-Claude can't reach your home network" problem. |
| **Tailscale-sandbox extension** (`extensions/tailscale-sandbox/`) | Ephemeral auth-key recipe so disposable cloud containers can join your tailnet for the duration of one session, then auto-clean. |
| **Architecture docs** (`docs/`) | The full design + schema + backup-restore runbook + troubleshooting. |

## Quickstart

If you're a **human** reading this and want to set it up yourself, jump to
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the rationale and
then [`ha-addon/README.md`](ha-addon/README.md) for the deploy steps.

If you're an **AI agent** helping a user deploy this, read
[`INSTALL-FOR-AGENTS.md`](INSTALL-FOR-AGENTS.md) end-to-end first. It's
a step-by-step runbook with decision points, prerequisite checks, and
verification gates designed for autonomous setup.

## What it isn't

- Not a replacement for short-term context inside one session. Your
  AI tool's built-in conversation memory still does that.
- Not a hosted service. There's no SaaS to subscribe to. You run it.
- Not a vector DB tutorial. It assumes a working network + a Home
  Assistant box (or any Linux box with Docker).
- Not magic. It's plain Chroma + plain HTTP + plain bash + plain
  Python. Every component is replaceable.

## Status

Built and battle-tested in personal use. The original deployment runs
across:

- macOS (Claude Code, Claude Desktop, native CLI)
- Linux (Cowork / cloud sandboxes)
- Windows 11 (Claude Code, Codex)
- Android (Termux + Alpine proot — handheld emulation device)

Pool size on the reference deployment: 5000+ observations across
multiple project tags. Daily backups include the full vector index +
HNSW segments, encrypted, replicated offsite.

## Inspired by

The architecture builds on [thedotmack/claude-mem][claude-mem] (the
Claude Code plugin that generates observations from session
transcripts). This project takes that as one possible client and adds:

- A self-hosted Chroma backend (replacing the per-machine local DB)
- Multi-device sync via Tailscale / LAN
- A vendor-neutral client surface (CLI + SKILL.md)
- A git-based async path for sandboxed environments
- HA-native backup integration

You can use this with or without the upstream plugin. Many users find
the CLI alone (just `claude-mem add-fact` and `claude-mem search`)
covers 80% of what they need.

[claude-mem]: https://github.com/thedotmack/claude-mem

## License

MIT. See [LICENSE](LICENSE).

## Contributing

PRs welcome. The two highest-leverage contributions right now:

1. Adapters for specific AI tools (Cursor rules, Continue.dev config,
   Cline tool definitions) — see [`docs/CLIENT-INTEGRATIONS.md`](docs/CLIENT-INTEGRATIONS.md).
2. A native MCP server wrapper so MCP-capable clients (Claude Desktop,
   Cursor MCP, etc.) can use the memory pool as a first-class tool.
