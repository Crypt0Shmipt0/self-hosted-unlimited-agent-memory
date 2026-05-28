# Schema reference

## Collection

| Field | Value | Notes |
|---|---|---|
| Name | `personal_memory` (suggested) | Pick any; just be consistent across clients |
| Tenant | `default_tenant` | Chroma default |
| Database | `default_database` | Chroma default |
| Embedding function | `{type: "known", name: "default"}` | Server-side; clients send raw text |
| Distance metric | cosine | Chroma default for the default embedding |

## ID conventions

Always use a deterministic prefix so multiple writers don't collide:

```
<tool>_<topic>_<epoch>_narrative          # exactly 1 per session
<tool>_<topic>_<epoch>_fact_<idx>         # 0..N per session
<tool>_<topic>_<epoch>_blocker_<idx>      # 0..M per session
<tool>_<topic>_<epoch>_decision_<idx>     # 0..K per session
```

- `<tool>`: short name of the writing tool (`claude`, `codex`, `cursor`,
  `cli`, etc.)
- `<topic>`: optional slug describing what this session was about
  (`auth-flow`, `bug-fix-401`, `data-room-rewrite`)
- `<epoch>`: Unix epoch in **seconds** when the session started
- `_narrative`, `_fact_N`, `_blocker_N`, `_decision_N`: the specific
  doc type within the session

Examples:

```
claude_dataroom_1779889232_narrative
claude_dataroom_1779889232_fact_0
claude_dataroom_1779889232_fact_1
claude_dataroom_1779889232_blocker_0
claude_dataroom_1779889232_decision_0
codex_authflow_1779890000_narrative
cursor_refactor_1779891111_fact_0
```

## Metadata fields

### Required

| Key | Type | Semantics |
|---|---|---|
| `field_type` | `"narrative"` \| `"fact"` | Distinguishes prose synthesis from atomic claims |
| `created_at_epoch` | int (ms since 1970) | Time-ordering, recency filters |
| `project` | str slug | Top-level filter — almost all queries use this |

### Highly recommended

| Key | Type | Semantics |
|---|---|---|
| `title` | str (≤140 chars) | Short headline for human display |
| `subtitle` | str (≤200 chars) | One-line synthesis; often first 200 chars of narrative |
| `memory_session_id` | UUID str | Groups all docs from one writing session |
| `source` | str | Writing tool identifier (`claude-code`, `cli`, `cursor-rules`, etc.) |
| `doc_type` | `"observation"` \| `"session_summary"` \| `"user_prompt"` | Higher-level category |

### Optional

| Key | Type | Semantics |
|---|---|---|
| `fact_index` | int | Ordinal within session (only for facts/blockers/decisions) |
| `concepts` | str or comma-list | Tags. Special values: `"blocker"`, `"open_decision"` |
| `type` | same as `doc_type` | Legacy alias; populate both for compatibility |

### Cowork-specific (only set by the git-handoff ingester)

| Key | Type | Semantics |
|---|---|---|
| `cowork_container` | str | Sandbox hostname at write time |
| `cowork_branch` | str | Git branch where the session log lives |
| `cowork_commit_sha` | str | HEAD SHA at the time of the session |

## Filter cheat sheet

### Single-key `where`

```python
where = {"project": "my-app"}
where = {"field_type": "narrative"}
where = {"concepts": "blocker"}
where = {"memory_session_id": "abc-123"}
where = {"created_at_epoch": {"$gte": 1779800000000}}  # last few days
```

### Multi-key `where` (Chroma 1.5+ requires `$and` / `$or`)

```python
where = {"$and": [
    {"project": "my-app"},
    {"field_type": "narrative"},
    {"created_at_epoch": {"$gte": 1779800000000}}
]}
```

```python
where = {"$or": [
    {"concepts": "blocker"},
    {"concepts": "open_decision"}
]}
```

### Full-text on the document body

```python
where_document = {"$contains": "MiCAR"}
where_document = {"$not_contains": "deprecated"}
```

Use `where` and `where_document` together to combine metadata + content
filters.

## Query patterns

| Goal | Code |
|---|---|
| Semantic search, one project | `col.query(query_texts=[q], n_results=5, where={"project":"P"})` |
| List all open decisions | `col.get(where={"concepts":"open_decision"})` |
| Fetch one session's full content | `col.get(where={"memory_session_id":"UUID"})` |
| Recent narratives across projects | `col.query(query_texts=[q], where={"$and":[{"field_type":"narrative"},{"created_at_epoch":{"$gte":<7d_ago>}}]})` |
| Find facts containing a specific string | `col.get(where={"field_type":"fact"}, where_document={"$contains":"specific term"})` |
| All facts in a session, ordered | `col.get(where={"memory_session_id":"UUID"})` then sort by `fact_index` in client code |

## Write patterns

### Minimal viable write (one fact, no session context)

```python
col.add(
    ids=[f"cli_{int(time.time())}_fact_0"],
    documents=["Decided to use Postgres over MongoDB for the auth schema."],
    metadatas=[{
        "field_type": "fact",
        "created_at_epoch": int(time.time() * 1000),
        "project": "my-app",
        "title": "Auth DB choice",
        "source": "cli",
    }]
)
```

### Full session write (narrative + facts + blockers + decisions)

See `client/skill/SKILL.md` "Writing: add observations" for the
canonical pattern.

## Things to never put in metadata

- Raw secrets (API keys, tokens, passwords) — Chroma metadata isn't
  encrypted at rest
- Multi-megabyte blobs — keep metadata to short strings and ints; put
  long content in `documents`
- Nested objects — Chroma metadata is flat key→primitive only; use
  `__`-separated keys if you need namespacing (`oauth__provider`,
  `oauth__expires_at`)
- Lists or dicts — same; flatten to comma-separated strings or
  multiple keys
