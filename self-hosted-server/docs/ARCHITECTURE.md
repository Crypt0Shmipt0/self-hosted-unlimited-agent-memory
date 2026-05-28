# Architecture

## The problem

AI assistants are stateless across sessions. Vendor "memory" features
(ChatGPT Memory, Claude Projects, etc.) keep your context in their
walled gardens and don't share across tools. If you use multiple AI
assistants — or even multiple sessions of the same one across devices
— you re-explain context every time.

## The shape of the solution

A single, self-hosted vector DB that every AI tool you use can
read and write to. One source of truth.

```
   ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
   │Claude  │ │Codex   │ │Cursor  │ │Sandbox │
   │ Code   │ │ CLI    │ │ MCP    │ │ Claude │
   └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘
       │          │          │          │
       │ HTTP via Tailscale (or LAN)     │
       └──────────┼──────────┼──────────┘
                  ▼          ▼
              ┌────────────────────┐
              │   Chroma 1.5.x     │  ← server-side embedding
              │   HTTP API :8000   │    (no client ML needed)
              └─────────┬──────────┘
                        ▼
              ┌────────────────────┐
              │  /share/personal-  │  ← persistent on host disk
              │  memory-server/    │    survives HA add-on rebuilds
              │  chroma.sqlite3    │    captured by HA daily backup
              │  + HNSW segments   │
              └────────────────────┘
                        │
                        ▼
              ┌────────────────────┐
              │ HA daily backup    │  ← daily, retained N copies
              │ → Nabu Casa Cloud  │    encrypted, offsite
              └────────────────────┘
```

## Layered design

### Layer 1: storage

A single Chroma vector DB. Why Chroma:
- HTTP API, no proprietary client required
- Server-side embedding (no ONNX or sentence-transformers on each
  client — important for musl/Alpine/Termux clients)
- Mature, well-documented metadata filtering with full-text + vector
  hybrid
- File-based persistence (one SQLite + segment dirs) — trivial to
  backup, restore, inspect
- Active development, large community, multiple language clients

We pin **Chroma 1.5.x** because:
- It's where the wire protocol settled (1.x is the rewrite from 0.x)
- The upstream `thedotmack/claude-mem` plugin pins `chromadb>=1.0.16`
- 0.5.x is incompatible at the `_type` metadata level

### Layer 2: host

A Home Assistant OS add-on for ease of:
- Container management (Supervisor restarts on crash, boots on start)
- Persistent storage at `/share/` (survives add-on updates and reinstalls)
- Backup integration (HA captures `/share/` in daily backups)
- Web UI for add-on options if we ever add any
- Already running 24/7 in most users' setups

For users without HA: plain Docker works identically. See `INSTALL-FOR-AGENTS.md`
Phase 2-ALT.

### Layer 3: network

Two access patterns we support:

**LAN-only**: simplest. Endpoint is `http://<lan-ip>:8000`. Works on
your home network, nothing else.

**Tailscale**: same endpoint reachable from anywhere on your tailnet.
Free for personal use (up to 100 devices). No port forwarding, no
public DNS, no certificates to manage. Endpoint becomes
`<host>.<tailnet>.ts.net:8000`.

For sandboxes that can't join the tailnet, two fallbacks:

- **Tailscale ephemeral keys** — short-lived containers grab an
  ephemeral, reusable, tagged auth key, join the tailnet for one
  session, then auto-disappear. See `extensions/tailscale-sandbox/`.
- **Git-handoff** — sandboxes with literally no network egress
  (only git push to a known remote) append session digests to a repo
  file. The user's primary machine ingests them post-hoc. See
  `extensions/git-handoff/`.

### Layer 4: client

The HTTP API is the canonical interface — anything that speaks HTTP
can read/write. On top of that:

- **`claude-mem` bash CLI** (`client/skill/claude-mem`) — wraps
  `chromadb` Python client via `uvx`. Exposes the 7 common operations
  (health, search, get-session, list-decisions, list-blockers,
  add-narrative, add-fact). Drop-in for any AI tool that can shell out.
- **`SKILL.md`** (`client/skill/SKILL.md`) — universal documentation
  in the Anthropic "skill" format, also readable by any AI that
  consumes markdown. Triggers on memory-shaped queries; documents the
  schema and example calls. Symlink into `~/.claude/skills/` for
  Claude Code; reference from other tools' rules/config files.

## Schema

Two `field_type`s:

- **`narrative`** — one per session, prose 60-150 words. The "what we
  did and why" summary.
- **`fact`** — atomic claims, many per session. Each is a single
  statement that can stand alone in a search result. Special fact
  flavors:
  - `concepts: "blocker"` — what we couldn't do
  - `concepts: "open_decision"` — what we deferred

The narrative + facts pattern came from the upstream
`thedotmack/claude-mem` plugin and survives because it works well in
practice: narratives give context, facts give precision. Search
returns the right granularity depending on the query.

## IDs

```
<tool>_<topic>_<epoch>_narrative
<tool>_<topic>_<epoch>_fact_<idx>
<tool>_<topic>_<epoch>_blocker_<idx>
<tool>_<topic>_<epoch>_decision_<idx>
```

The `<tool>_<topic>_<epoch>` prefix is deliberately namespaced so:
- Multiple tools writing concurrently don't collide on IDs
- You can grep the pool by tool name
- Epoch makes it trivially time-orderable

## Metadata

Required fields:
- `field_type` ("narrative" | "fact")
- `created_at_epoch` (ms)
- `project` (slug for filtering)

Optional but recommended:
- `title`, `subtitle`
- `memory_session_id` (UUID linking all docs from one session)
- `concepts` (tags)
- `source` (tool name)

See `docs/SCHEMA.md` for the full field list with semantics.

## Why server-side embedding

Chroma 1.5 ships with a default embedding function (Sentence
Transformers, 384-dim, MiniLM-L6-v2). When you `add()` with
`documents=[...]` (no `embeddings=[...]`), the server embeds. When you
`query()` with `query_texts=[...]` (no `query_embeddings=[...]`), the
server embeds.

This matters because:
- Many client environments can't install ONNX or sentence-transformers
  (Alpine musl, Termux, browser-only AI tools, sandboxes without
  numpy/torch)
- Embedding model versions stay consistent across clients (no client
  drift)
- Cuts client install size from ~500 MB (with all ML deps) to ~5 MB
  (just `chromadb` core)

The cost: every read/write incurs server-side embedding latency
(~10-50ms per text on a Raspberry Pi 4, sub-10ms on x86). For
interactive memory queries this is negligible.

## Why HA-native (vs. systemd or k8s)

If the user already runs HA, the add-on path costs nothing extra and
gets:
- Container lifecycle for free (Supervisor restarts, boot-on-start)
- Backup integration that "just works"
- Web UI for one-click start/stop/logs
- A standard place where similar always-on services already live

For users without HA, plain Docker is fine. We don't take a dependency
on HA features beyond what's in `/addons/` and `/share/`.

## Trust boundaries

- **No auth on the Chroma HTTP API.** The server assumes anything that
  can reach :8000 is trusted. This is fine because:
  - LAN reach implies you're on the user's WiFi (already trusted)
  - Tailscale reach implies you're on the user's tailnet (already
    trusted via Tailscale's identity layer)
- **If exposing to the public internet** (e.g. Cloudflare Tunnel):
  - Put a reverse proxy (Caddy, nginx, Cloudflare Access) in front
  - Add API-key auth via Chroma's `CHROMA_SERVER_AUTHN_CREDENTIALS`
  - Don't do this without understanding the data sensitivity tradeoff

- **Backup encryption**: HA backups are AES-encrypted with a password
  in `backup/config/info`. Keep that password safe — without it the
  Nabu Casa cloud copy is useless to anyone (including you).

## Failure modes we designed around

| Failure | Handling |
|---|---|
| Server box reboots | HA auto-starts the add-on (`startup: services`, `boot: auto`) |
| Chroma add-on crashes | HA Supervisor auto-restarts |
| Server-side disk corruption | Restore from yesterday's HA backup (10 sec downtime) |
| Network outage / off-LAN | Tailscale FQDN keeps working as long as both ends have internet |
| Cowork-style sandbox with no network egress | Git-handoff async path |
| Musl/Alpine clients can't run ONNX | Server-side embedding makes client ML unnecessary |
| Client running on Android Termux | Same — pure HTTP, no native deps |
| Multiple writers race-conditioning on the same ID | Chroma `add()` errors on duplicates; the script catches and logs |
| Pool grows beyond client memory | `query()` paginates; `get(limit=N, offset=K)` for bulk reads |

## What this design intentionally doesn't do

- **No real-time streaming.** Memory writes are individual HTTP POSTs.
  If you need pub/sub, add NATS or Redis on the side.
- **No multi-tenancy.** One Chroma instance, one user. Run separate
  instances per person if you share a household server.
- **No fine-grained access control.** The whole pool is read/write by
  anything that can reach the endpoint. If you need per-project read
  isolation, use separate collections.
- **No automatic dedup.** If a tool writes the same fact twice from
  two sessions, you'll see it twice in search. Use the ID-prefix
  convention to make per-session writes unique; manual dedup if
  needed via `col.delete(where={...})`.
- **No graph relationships.** Docs are flat. If you need
  entity-relationship modeling, layer that on top via the `concepts`
  metadata field.

## File layout on the server

```
/share/personal-memory-server/
├── chroma.sqlite3                  # collection registry + metadata + WAL
└── <segment-uuid>/                  # per-collection HNSW index
    ├── header.bin                   # dim, distance metric, etc.
    ├── length.bin                   # vector count
    ├── link_lists.bin              # HNSW graph edges
    ├── data_level0.bin             # vector data
    └── index_metadata.*            # per-segment metadata (Chroma internal)
```

Total size scales ~linearly with doc count. 1k docs ≈ 5 MB; 100k docs ≈
500 MB. The HNSW index is rebuilt incrementally on each insert (no
batch index step needed).

## Versioning policy

We pin major.minor of Chroma (e.g. 1.5.9) because patch upgrades have
been compatible but minor upgrades occasionally change the wire
protocol. Bump deliberately, test with a search + write round-trip,
keep the prior tag pinned in git in case rollback is needed.
