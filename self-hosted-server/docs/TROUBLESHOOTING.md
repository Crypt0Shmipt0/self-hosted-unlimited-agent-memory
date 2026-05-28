# Troubleshooting

Known failure modes, ordered by frequency.

## "Process died during startup" but the worker is actually running

**Symptom**: Upstream `claude-mem` worker-cli.js says `Failed to start: Process died during startup` but `ps -ef | grep worker-service` shows it alive on some port.

**Cause**: CLI's readiness probe hits port 37777, but `worker-service.cjs`
binds `37700 + (uid % 100)`. The CLI assumes the wrong port and gives
up.

**Fix**: Trust the PID file, not the CLI.

```bash
cat ~/.claude-mem/worker.pid
# → {"pid": 12345, "port": 37714, ...}
curl -sS http://127.0.0.1:37714/api/health
# → {"status":"ok","mcpReady":true,...}
```

If the worker really IS dead, the PID file would be stale (referring
to a PID that's not running). Verify with `kill -0 $PID`.

---

## "Memory upload failed due to the server-beta runtime configuration missing credentials"

**Symptom**: Upstream `claude-mem` errors with the message above on
some device but works fine on others.

**Cause**: `~/.claude-mem/settings.json` has `"CLAUDE_MEM_RUNTIME": "server-beta"`.
The server-beta runtime requires OAuth credentials that are only
available on the device where they were originally set up (usually the
user's primary Mac, via Claude Code's keychain integration).

**Fix**: Change to `"worker"` (which works everywhere):

```bash
sed -i 's/"CLAUDE_MEM_RUNTIME": "server-beta"/"CLAUDE_MEM_RUNTIME": "worker"/' \
  ~/.claude-mem/settings.json
bun ~/.claude/plugins/cache/thedotmack/claude-mem/*/scripts/worker-cli.js restart
```

The error message says "revert to the chroma runtime" — that's a
misleading label inside the plugin. The actual constant value is
`"worker"`.

---

## `KeyError('_type')` from Chroma

**Symptom**: `col.list_collections()` or `col.query()` returns 500 from
the server with `KeyError('_type')` in the server logs.

**Cause**: Version mismatch between client and server. Specifically,
data on disk was written by Chroma 1.x but the server you're running is
0.5.x (or vice versa).

**Fix**: Pin to Chroma 1.5.x server. Don't downgrade — the data
format is forward-only.

```bash
# In the HA add-on Dockerfile:
FROM chromadb/chroma:1.5.9   # not 0.5.x
```

---

## chroma-mcp won't install on Alpine / musl (onnxruntime wheel mismatch)

**Symptom**:
```
× No solution found when resolving dependencies:
  ╰─▶ onnxruntime>=1.20.0 has no wheels with a matching platform tag
     (e.g., `linux_aarch64`). Wheels are available on:
     manylinux_2_27_aarch64, manylinux_2_28_aarch64, ...
```

**Cause**: `chroma-mcp 0.2.6` depends on `onnxruntime>=1.20`, which only
ships manylinux (glibc) aarch64 wheels. Alpine is musl; `gcompat`
doesn't fix this because uv detects musl as the platform tag.

**Fix options**:

1. **Use the HTTP API directly, skip chroma-mcp** — the `claude-mem`
   CLI in `client/skill/` does exactly this. No onnxruntime needed.
2. **Write a thin MCP shim** that translates MCP tool calls to Chroma
   HTTP REST calls. Sketch in `extensions/` (TODO — open PR welcome).
3. **Use a glibc proot** (Debian/Ubuntu) instead of Alpine. Forks the
   runtime environment.
4. **Build onnxruntime from source for musl-aarch64**. Multi-hour
   build, brittle. Don't recommend unless you have no other option.

---

## Tailscale MagicDNS doesn't resolve inside a proot

**Symptom**: `curl http://your-host.tailnet-XXXX.ts.net:8000/api/v2/heartbeat`
works from your shell but fails inside a Termux+Alpine proot or
similar with "name resolution failed".

**Cause**: `/etc/resolv.conf` inside the proot is a snapshot from
container creation, not a live view of the host's DNS. Tailscale's
MagicDNS resolver (`100.100.100.100`) isn't in the proot's resolver
list.

**Fix options** (best to worst):

1. **Use the raw Tailscale IP** (`100.X.Y.Z`) instead of the FQDN. No
   DNS dependency.
2. **Bind-mount the host's resolv.conf** into the proot at startup.
3. **Add `100.100.100.100` to the proot's `/etc/resolv.conf`**.

The CLI's `HOSTS=(...)` array handles this by listing the FQDN and
the raw IP as fallbacks; the script picks whichever works.

---

## `col.get(where={k1: v1, k2: v2})` errors with "Expected where to have exactly one operator"

**Symptom**:
```
ValueError: Expected where to have exactly one operator, got {'concepts': 'open_decision', 'project': 'my-app'} in get.
```

**Cause**: Chroma 1.5+ requires multi-key filters to be wrapped in
`$and` or `$or`. The 0.x-era flat `{k: v, k: v}` shorthand is no longer
accepted.

**Fix**:

```python
# WRONG (Chroma 1.5+):
where = {"concepts": "open_decision", "project": "my-app"}

# RIGHT:
where = {"$and": [
    {"concepts": "open_decision"},
    {"project": "my-app"}
]}
```

Single-key filters still work without the wrapper.

---

## Worker spawns chroma-mcp with `--client-type persistent` after I set `CLAUDE_MEM_CHROMA_MODE: "remote"`

**Symptom**: `ps -ef | grep chroma-mcp` shows
`--client-type persistent --data-dir /Users/.../chroma` instead of
`--client-type http --host <server>`.

**Cause**: Either:
- The worker didn't pick up the new settings (didn't restart fully)
- Settings file has the wrong JSON shape (e.g. wrapped in an extra `env: {...}`)
- The plugin version is old enough to not honor `CHROMA_MODE`

**Fix**:

```bash
# 1. Validate the settings file
cat ~/.claude-mem/settings.json | python3 -m json.tool

# 2. Confirm the keys are at the top level, not nested under "env"

# 3. Full restart
bun ~/.claude/plugins/cache/thedotmack/claude-mem/*/scripts/worker-cli.js stop
pkill -9 -f chroma-mcp
pkill -9 -f worker-service.cjs
sleep 2
bun ~/.claude/plugins/cache/thedotmack/claude-mem/*/scripts/worker-cli.js start

# 4. Verify
sleep 4
ps -ef | grep chroma-mcp | grep -v grep
# → should show --client-type http --host <your-server-host>
```

---

## Backup restore: chroma.sqlite3 is fine but no documents return on query

**Symptom**: `col.count()` returns 0 (or some unexpected number) after a
fresh restore, despite the sqlite file being the right size.

**Causes & fixes**:

1. **Collection name mismatch**. The restored data was written under
   collection name `cm__claude-mem` but you're querying `personal_memory`.
   Use `c.list_collections()` to see what's actually there.

2. **Segment dir not restored**. The vector index lives in
   `<segment-uuid>/*.bin` next to the sqlite. If you only restored the
   sqlite, queries return nothing. Restore the full data dir.

3. **Embedding function mismatch**. If the restored collection was
   created with a different embedding function (e.g. custom OpenAI vs.
   default Sentence Transformers), queries via the new function won't
   find anything. Recreate the collection with the original embedding
   function declaration.

4. **Chroma started fresh because path was wrong**. Check the chroma
   logs:
   ```
   docker logs personal-memory-server | grep -i path
   # → "Saving data to: /data"   ← server fell back to default!
   ```
   If you see `/data` instead of `/share/personal-memory-server`, the
   ENTRYPOINT didn't take effect. Rebuild the add-on image.

---

## Git-handoff ingester: "remote contains work that you do not have locally"

**Symptom**: After running the ingester, the marker commit push fails
with this error.

**Cause**: The sandboxed agent force-pushed its branch (e.g. rebased
after our local commit). My local marker commit is now on an
ancestor that doesn't exist on the remote.

**Fix**:

- The data is fine — it's already written to Chroma
- The marker commit being local-only just means the next ingester run
  will see the block as unprocessed again
- To avoid double-ingestion: either delete the duplicate docs first
  (`col.delete(where={"memory_session_id": "..."})`) and re-ingest, or
  `git push --force-with-lease` your marker commit (if you trust your
  local marker over the sandbox's force-push)
- Long-term: run with `--no-commit` if the sandbox rebases often. The
  data stays consistent in Chroma; only the markers get lossy.

---

## "No transport reachable" from a sandbox running the bootstrap

**Symptom**: `bootstrap.sh` says `NO TRANSPORT WORKED` and drops a note
in `cowork-blocked/`.

**Cause**: The sandbox doesn't have:
- Direct network egress to your home (no LAN)
- Tailscale daemon capability + a valid auth key in expected location
- Any other configured fallback

**Fix**: Either fix the transport (most likely: Tailscale not installed
or auth key missing) or accept the sandbox can't sync directly and
use the git-handoff extension instead.

---

## "Insert into INI value with embedded null byte"

**Symptom**: chromadb operations error with messages about null bytes.

**Cause**: A document text field contains a literal `\x00` (NUL byte),
often from binary content accidentally passed as text.

**Fix**: Strip control characters before writing:

```python
def safe_doc(text: str) -> str:
    return text.replace("\x00", "").strip()
```

Wrap every `col.add(documents=[...])` call with this.
