---
name: personal-memory-server
description: Query and write to a self-hosted shared memory pool that lives across every AI tool and device the user has wired up. Use when the user asks about prior decisions, project history, what some past Claude/Codex/Antigravity/etc. did, technical context across past sessions, or anything resembling "do you remember when…" / "what did we figure out about X" / "what's our policy on Y". Triggers also on "personal memory", "shared memory", "memory pool", "chroma", or any explicit reference to the cross-session memory store. The pool is hosted on the user's own Home Assistant or Linux box — all data is local-first, owned by the user, never sent to a vendor.
---

# Personal Memory Server

A self-hosted Chroma vector DB that every AI tool the user runs reads
and writes to. Local-first, multi-device, cross-LLM, cross-environment.

This skill is **universal**: it documents the HTTP API and metadata
schema. Any AI tool that can run shell commands or HTTP requests can
use it. No vendor lock-in.

## Endpoint

The user configures their own endpoint. Default in this template:
`http://<your-server-host>:8000`. Replace with whatever the user wired
up (e.g. `homeassistant.local:8000`, `10.0.0.X:8000`,
`<tailnet>.ts.net:8000`, or a Tailscale 100.x IP).

If unsure which to use, ask the user. Common fallback order:

1. Tailscale MagicDNS FQDN (works LAN + off-LAN)
2. Tailscale raw 100.x IP (works around proot DNS issues)
3. LAN IP (works on home network only)

## Heartbeat / liveness

```bash
curl -sS http://<your-server-host>:8000/api/v2/heartbeat
# → {"nanosecond heartbeat":<int>}
```

If that fails, try the alternates in the order above.

## Single collection

- **Tenant:** `default_tenant`
- **Database:** `default_database`
- **Collection:** `personal_memory` (or the user's custom name)
- **Embedding function:** `{type: "known", name: "default"}` — server-side
  embedding (Sentence Transformers, 384-dim). **You can send raw text and
  the server vectorizes for you. No ONNX / no client-side ML.**

## Document schema

Every doc is one of two `field_type`s:

- **`narrative`** — one per session, 1-3 paragraph prose synthesis
- **`fact`** — atomic single-claim string; many per session

ID conventions (use the same shape for your writes):

```
<tool>_<topic>_<epoch>_narrative
<tool>_<topic>_<epoch>_fact_<idx>
<tool>_<topic>_<epoch>_blocker_<idx>
<tool>_<topic>_<epoch>_decision_<idx>
```

Where `<tool>` is your tool name (`claude`, `codex`, `cursor`,
`antigravity`, `cline`, etc.) and `<topic>` is a short slug.

Metadata keys (all optional except `created_at_epoch`):

```
title              short headline
subtitle           one-line synthesis (first 200 chars of narrative is fine)
project            short slug for this project ("my-app", "writing", etc.)
doc_type           "observation" | "session_summary" | "user_prompt"
type               same as doc_type for legacy reasons
field_type         "narrative" | "fact"
fact_index         int, index of fact within session
concepts           "blocker" | "open_decision" | comma-list of tags
memory_session_id  UUID — groups all docs from one session
created_at_epoch   ms since epoch
source             tool name + role ("claude-code", "codex-cli", "cline", …)
```

## Reading: semantic search

Pure HTTP, no SDK needed.

```bash
# 1. Get the collection id (cache; same id for the life of the collection)
COLL=$(curl -sS \
  "http://<your-server-host>:8000/api/v2/tenants/default_tenant/databases/default_database/collections" \
  | jq -r '.[] | select(.name=="personal_memory") | .id')

# 2. Query
curl -sS -X POST \
  "http://<your-server-host>:8000/api/v2/tenants/default_tenant/databases/default_database/collections/$COLL/query" \
  -H "Content-Type: application/json" \
  -d '{
    "query_texts": ["what did we decide about X?"],
    "n_results": 5,
    "where": {"project": "my-app"},
    "include": ["documents","metadatas","distances"]
  }' | jq .
```

The server embeds `query_texts` automatically and returns matches with
`distances` (cosine, lower is better).

**Python (chromadb client) — recommended if you have it:**

```python
import chromadb
c = chromadb.HttpClient(host="<your-server-host>", port=8000)
col = c.get_collection("personal_memory")
results = col.query(
    query_texts=["what did we decide about X?"],
    n_results=5,
    where={"project": "my-app"},
)
for doc, meta, dist in zip(results["documents"][0],
                            results["metadatas"][0],
                            results["distances"][0]):
    print(f"[{dist:.3f}] {meta.get('title','')[:60]}\n  {doc[:200]}\n")
```

**Multi-key `where` filters** (Chroma 1.5+ requires `$and`):

```python
where = {"$and": [{"project": "my-app"}, {"field_type": "narrative"}]}
```

**Useful query patterns:**

| Goal | Filter |
|---|---|
| Recent context (last week) | `where={"created_at_epoch": {"$gte": <epoch_ms_7d_ago>}}` |
| Decisions only | `where={"concepts": "open_decision"}` |
| Blockers only | `where={"concepts": "blocker"}` |
| One project | `where={"project": "my-app"}` |
| Narratives only (high-level) | `where={"field_type": "narrative"}` |
| One session's full content | `where={"memory_session_id": "<uuid>"}` |

`where` supports `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte`, `$in`,
`$nin`, `$and`, `$or`. `where_document` supports `$contains`, `$not_contains`.

## Writing: add observations

**Critical**: include enough metadata that future queries can find your
docs. At minimum `project`, `field_type`, `created_at_epoch`, `title`.

```python
import chromadb, time, uuid
c = chromadb.HttpClient(host="<your-server-host>", port=8000)
col = c.get_collection("personal_memory")

session_uuid = str(uuid.uuid4())
epoch_ms = int(time.time() * 1000)
id_prefix = f"<your-tool>_<topic>_{int(time.time())}"

base_meta = {
    "title": "Short headline of what was decided/done",
    "subtitle": "One-line synthesis (becomes ≤200 chars).",
    "project": "my-app",                # project tag for filtering
    "doc_type": "observation",
    "type": "observation",
    "memory_session_id": session_uuid,
    "created_at_epoch": epoch_ms,
    "source": "<your-tool>",            # codex | antigravity | continue | cline | …
}

# Narrative — one per session
col.add(
    ids=[f"{id_prefix}_narrative"],
    documents=["A 60-150 word paragraph describing what was done and why."],
    metadatas=[{**base_meta, "field_type": "narrative"}],
)

# Facts — many per session
facts = [
    "Decision/fact #1 as a single atomic statement.",
    "Decision/fact #2 with specific values, paths, version numbers.",
    "Decision/fact #3 — focus on things future-You needs to know.",
]
col.add(
    ids=[f"{id_prefix}_fact_{i}" for i in range(len(facts))],
    documents=facts,
    metadatas=[{**base_meta, "field_type": "fact", "fact_index": i}
               for i in range(len(facts))],
)
```

**Pure HTTP (no Python):** POST `/collections/<id>/add` with JSON body
`{"ids":[...], "documents":[...], "metadatas":[...]}`.

## When to use semantic search vs metadata filter

- **Search** ("what did X figure out about Y?") → `query_texts` with optional `where`
- **Browse** ("list all decisions still open") → `get` with `where={"concepts":"open_decision"}` (no `query_texts`)
- **Specific entry** ("read this exact session's docs") → `get` with `where={"memory_session_id":"<uuid>"}`

Use `n_results=5` to start; bump to 10-20 if results feel narrow. Queries
that don't filter by `project` can return cross-project noise.

## Project tags

Each user defines their own. Common pattern: short slug per major project
(`my-app`, `blog`, `client-x`, `home-automation`, etc.). Plus one catchall
like `general` or `notes` for cross-project memory.

**Always tag** when working in a specific project context, so future
search facets stay clean. New projects: just add a new slug, no
registration needed.

## Off-LAN access

If you're NOT on the user's tailnet and need access, three options:

1. **Join the tailnet** — install Tailscale, sign in with the user's
   account. After they approve, MagicDNS resolves and you're in.
2. **Public HTTPS endpoint** (if the user set one up via Cloudflare
   Tunnel or similar). Credentials at whatever path the user gave you.
3. **Git-based async ingest** — for sandboxes with NO direct egress,
   append a session-log block to a repo file and the user's primary
   machine ingests it post-hoc via the `extensions/git-handoff/`
   tooling.

## Backup / disaster recovery

If the host is HA OS, daily backup captures the data dir and replicates
to Nabu Casa Cloud (encrypted). For plain Docker hosts, the user runs
their own cron/rsync.

## Anti-patterns / footguns

- **Don't write with empty/missing `created_at_epoch`** — most queries
  filter or sort by it. Set it to `int(time.time() * 1000)`.
- **Don't reuse IDs.** Chroma's `add()` errors on duplicate IDs. Use
  `update()` to overwrite.
- **Don't put PII in plaintext docs.** The pool is shared across tools
  and gets backed up to whatever offsite the user configured.
- **Don't bypass the metadata schema.** Tools downstream parse `title`,
  `subtitle`, `field_type`, `project`, etc. Empty/missing fields = silent
  search misses.
- **Don't query without `project` filter** on cross-project tools. You'll
  get matches from unrelated work and waste tokens.
- **Don't `delete` without filters.** `col.delete()` with no args can
  wipe the whole collection.
- **Don't use multi-key `where` without `$and`** on Chroma 1.5+. Wrap
  in `{"$and": [{"k":"v"}, …]}`.

## Quick health-check before any real write

```bash
HOST=http://<your-server-host>:8000
curl -sS $HOST/api/v2/heartbeat || echo "DOWN — try fallback endpoints"
curl -sS "$HOST/api/v2/tenants/default_tenant/databases/default_database/collections" \
  | jq '.[] | select(.name=="personal_memory") | {name, id}'
```

If the heartbeat works but the collection isn't listed, you're hitting a
different Chroma instance or the collection was reset — STOP and ping
the user before writing anything.

## Companion CLI

A `claude-mem` bash wrapper ships next to this `SKILL.md`. It exposes
the common operations without needing Python imports each time. From
any shell:

```sh
./claude-mem health
./claude-mem search "topic" [--project P] [--n N] [--type narrative|fact]
./claude-mem get-session <memory_session_id>
./claude-mem list-decisions [--project P]
./claude-mem list-blockers  [--project P]
./claude-mem add-narrative --project P --title T --doc D
./claude-mem add-fact      --project P --title T --doc D [--concept blocker|open_decision]
```

It auto-detects the endpoint by trying the alternates in order. Edit
the `HOSTS=(…)` array at the top to match your deployment.

## Tool-specific setup pointers

Reference this skill from each tool's config:

- **Claude Code (CLI):** symlink this dir into `~/.claude/skills/`.
- **Claude Desktop:** add the Chroma HTTP API as an MCP resource, OR
  let the model read this SKILL.md when prompted.
- **Antigravity:** point your project's rules file at this SKILL.md.
- **Codex / Cursor:** drop a one-line pointer in `.cursor/rules/` →
  `Read SKILL at /path/to/this/file before any "remember"/"prior" query`.
- **Continue.dev / Cline:** their custom tool definitions support
  `fetch()` — point a custom tool at the heartbeat URL for a sanity
  probe, then at `/query` for the search.

## What this skill is NOT

- Not a chat memory for inside one session — your AI tool already has
  that. This is for cross-session, cross-tool, cross-device memory.
- Not a knowledge graph — relationships between docs aren't first-class
  citizens. Use semantic search + metadata filters.
- Not a database for arbitrary structured data — keep documents textual
  and atomic. Use a real DB if you need joins/transactions.
