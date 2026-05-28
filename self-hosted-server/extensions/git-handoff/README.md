# Git-handoff extension

For AI agents running in sandboxes that **can't reach your memory server
directly** (no LAN, no Tailscale, no HTTP egress to your home network).

Common cases:
- Cowork / cowork.dev sandboxes pinned to a single git repo
- Browser-based AI tools with no shell or restricted network
- CI runners with no outbound to private networks
- Cloud sandboxes with strict egress policies

## How it works

```
   ┌──────────────────────┐                    ┌────────────────────┐
   │  Sandboxed agent     │   appends to repo  │  Your always-on    │
   │  (Cowork-Claude,     │  ───────────────►  │  machine (cron or  │
   │   etc.) — git only   │                    │  manual)           │
   └──────────────────────┘                    │                    │
                                                │  ingest-session.py │
                                                │  pulls + writes to │
                                                │  Personal Memory   │
                                                │  Server            │
                                                └────────────────────┘
```

1. **Sandboxed agent** appends a structured session log to
   `.claude/cowork-session-log.md` in the repo it's working on
2. Commits + pushes to its working branch
3. **Your always-on machine** runs `ingest-session.py <repo>`. It:
   - `git fetch && git pull --ff-only` the repo
   - Parses unprocessed `## Session …` blocks
   - Writes 1 narrative + N facts + M blockers + K decisions to your
     Chroma server with `project=<tag>` and proper metadata
   - Inserts `<!-- INGESTED ... -->` markers (idempotent)
   - Commits + pushes the markers back

## Setup on your always-on machine

```bash
cp -r extensions/git-handoff/ingest-session.py ~/personal-memory-server/
chmod +x ~/personal-memory-server/ingest-session.py
```

Edit the script to point at your endpoint (top of file, `DEFAULT_HOST`).

## Setup for the sandboxed agent

Drop a brief in the repo so the agent knows the format:

```bash
mkdir -p .claude
cp extensions/git-handoff/SESSION-LOG-FORMAT.md .claude/
```

Or just tell the agent inline: "When you're done, append a session
block to `.claude/cowork-session-log.md` matching the format in this
project's git-handoff README, commit, push, and reply with the SHA."

## Session block skeleton

```markdown
## Session YYYY-MM-DD — Short title

- **Container:** <hostname of the sandbox>
- **Branch:** <git branch>
- **Workspace mount:** none (vanilla sandbox, git-only)
- **Transport used:** git-only
- **Worker:** not present
- **Memory session UUID:** <uuidgen output>
- **ID prefix:** <tool>_<topic>_<epoch>_*
- **Project tag:** <your-project-slug>

### Narrative
60-150 words. First-person plural. What you did, why it mattered, what
changed. Specific, no fluff.

### Facts
- Atomic claim
- Another atomic claim
- 5-20 total

### Blockers (if any)
- Optional, what you couldn't do and why

### Open decisions (if any)
- Optional, decisions deferred to future sessions

### Files touched
- path — what changed (informational, not ingested)

### Final commit on branch
`<sha>` — commit message
```

The parser recognizes these section headings:

- `### Narrative` → one narrative doc
- `### Facts` → one fact doc per bullet
- `### Blockers` (or `### Blockers (if any)`) → one fact-with-concept=blocker per bullet
- `### Open decisions` (or `### Decisions`, `### Open Questions`, `### Open Decisions (if any)`) → one fact-with-concept=open_decision per bullet
- `### Files touched` → ignored (informational only)
- `### Final commit on branch` → SHA extracted into metadata

## Run the ingester

```bash
# One-shot
~/personal-memory-server/ingest-session.py /path/to/repo

# Dry-run (parse + show, don't write)
~/personal-memory-server/ingest-session.py /path/to/repo --dry-run

# Don't push markers back (e.g. on a feature branch you don't want to dirty)
~/personal-memory-server/ingest-session.py /path/to/repo --no-commit

# Skip git pull (operate on what's already checked out)
~/personal-memory-server/ingest-session.py /path/to/repo --no-pull
```

## Wrap as cron

Run every 15 min, no auto-commit (so your branches don't get marker
spam):

```cron
*/15 * * * * /usr/bin/env uvx --quiet --with chromadb==1.0.16 python3 \
  $HOME/personal-memory-server/ingest-session.py /path/to/repo --no-commit \
  >> $HOME/personal-memory-server/cron.log 2>&1
```

For full autopilot (with marker commits, useful on dedicated branches):
drop `--no-commit`.

## Branch handling

By default the script operates on whatever branch is checked out. To
process a different branch:

```bash
cd /path/to/repo
git fetch && git checkout claude/session-branch
~/personal-memory-server/ingest-session.py /path/to/repo
```

The marker commits go back to the same branch (unless `--no-commit`).

## Idempotency rules

- Each `## Session …` block gets a `<!-- INGESTED YYYY-MM-DD HH:MM:SSZ -->`
  marker inserted on the line after the heading
- Re-runs skip already-marked blocks
- To force re-ingest, delete the marker AND delete the existing docs from
  Chroma (otherwise `add()` errors on duplicate IDs):
  ```python
  import chromadb
  c = chromadb.HttpClient(host="<your-host>", port=8000)
  col = c.get_collection("personal_memory")
  col.delete(where={"memory_session_id": "<the-uuid-from-the-block>"})
  ```

## Race conditions

If the sandbox force-pushes its branch (e.g. rebases after the
ingester has committed markers), the ingester's marker commit becomes
local-only. The data in Chroma is fine; only the markers diverge. The
next run will detect the missing markers and re-ingest unless you
manually delete the duplicate docs first.

If this happens often, run with `--no-commit` and accept that re-runs
will silently process the same block again. The dedup guarantee in
Chroma (unique IDs) protects against duplicate writes — `add()` errors,
which the script catches and logs.

## Schema mapping

| Section | Becomes | Chroma metadata |
|---|---|---|
| `## Session ... — Title` | (header, not ingested as a doc) | `title` (becomes `subtitle` is first 200 chars of narrative) |
| `### Narrative` | 1 doc, `id=<prefix>_narrative` | `field_type: "narrative"` |
| `### Facts` bullets | N docs, `id=<prefix>_fact_<i>` | `field_type: "fact", fact_index: <i>` |
| `### Blockers` bullets | M docs, `id=<prefix>_blocker_<i>` | `field_type: "fact", concepts: "blocker"` |
| `### Open decisions` bullets | K docs, `id=<prefix>_decision_<i>` | `field_type: "fact", concepts: "open_decision"` |
| `### Final commit on branch` `\`SHA\`` | (extracted) | `cowork_commit_sha: "<sha>"` |
| `- **Container:**` etc. metadata bullets | (extracted) | various: `cowork_container`, `cowork_branch` |
