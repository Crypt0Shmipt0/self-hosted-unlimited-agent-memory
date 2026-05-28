# Client install (per-device)

Run this on every machine that should read/write memories.

## 1. Drop the skill + CLI

```bash
mkdir -p ~/personal-memory-server
cp -r client/skill/* ~/personal-memory-server/
chmod +x ~/personal-memory-server/claude-mem
```

## 2. Edit endpoints

Open `~/personal-memory-server/claude-mem` (the bash CLI) and edit the
`HOSTS=( ... )` array near the top. Replace `<your-server-host>` with
your actual endpoint(s). Recommended shape:

```bash
HOSTS=(
    "your-host.tailnet-XXXX.ts.net"   # 1st choice: Tailscale FQDN
    "10.0.0.X"                         # 2nd: LAN IP
    "100.X.Y.Z"                        # 3rd: Tailscale raw IP (DNS-free fallback)
)
```

The script tries each in order and uses the first that responds to
`/api/v2/heartbeat`.

Also open `~/personal-memory-server/SKILL.md` and find/replace
`<your-server-host>` with the same set of values (so AI tools reading
the skill see the right examples).

## 3. Test

```bash
~/personal-memory-server/claude-mem health
# → endpoint reachable, count=<N>

~/personal-memory-server/claude-mem add-fact \
  --project "setup-test" \
  --title "Install verification on $(hostname)" \
  --doc "First write from $(hostname) at $(date)"

~/personal-memory-server/claude-mem search "install verification" --n 1
# → returns the just-written doc
```

## 4. Wire your AI tool(s)

### Claude Code (CLI)

```bash
ln -sfn ~/personal-memory-server ~/.claude/skills/personal-memory-server
```

Claude Code auto-discovers it on next session start. Verify by asking
something memory-shaped ("do you remember anything about X?") — the
skill should activate.

### Claude Desktop

Either:
- Add `~/personal-memory-server/SKILL.md` to a project's Knowledge
  Base, or
- (If you have MCP set up) wire a `chromadb-mcp` server pointing at
  your endpoint, or
- Just paste the SKILL.md content when you need it

### Codex / Cursor

Add a one-liner to `.cursor/rules/personal-memory.md`:

```
For any question about prior decisions, project history, or "do you
remember...", first read ~/personal-memory-server/SKILL.md and use the
HTTP API or the claude-mem CLI to query the memory pool.
```

### Continue.dev / Cline

Define a custom slash command / tool that shells out to:
```
~/personal-memory-server/claude-mem search "{{input}}" --n 5
```

See [`../docs/CLIENT-INTEGRATIONS.md`](../docs/CLIENT-INTEGRATIONS.md)
for a worked example per tool.

### Antigravity (Google)

Antigravity's project rules support pointing at external docs. Add
`~/personal-memory-server/SKILL.md` to the project's instructions list.

### Anything else with bash access

Just call the CLI directly. No integration needed.

## 5. Optional: upstream `thedotmack/claude-mem` plugin

If you already use the [claude-mem][cm] Claude Code plugin and want to
keep the per-session observation auto-generation: configure it to use
this server's endpoint as its Chroma backend.

Edit `~/.claude-mem/settings.json` (copy from
[`settings-template.json`](settings-template.json) in this dir):

```json
{
  "CLAUDE_MEM_RUNTIME": "worker",
  "CLAUDE_MEM_CHROMA_MODE": "remote",
  "CLAUDE_MEM_CHROMA_HOST": "<your-server-host>",
  "CLAUDE_MEM_CHROMA_PORT": "8000",
  "CLAUDE_MEM_CHROMA_SSL": "false",
  "CLAUDE_MEM_CHROMA_TENANT": "default_tenant",
  "CLAUDE_MEM_CHROMA_DATABASE": "default_database"
}
```

Then `bun ~/.claude/plugins/cache/thedotmack/claude-mem/*/scripts/worker-cli.js restart`.

**Notes:**
- The upstream plugin uses collection name `cm__claude-mem` (not
  `personal_memory`). Either swap to that, or keep both collections
  on the same server.
- `CLAUDE_MEM_RUNTIME: "worker"` is correct for almost everyone. Don't
  use `"server-beta"` unless you have Claude Code OAuth configured on
  this device.
- `worker-cli.js status` has a known bug — it probes the wrong port
  and prints "Process died" while the worker is actually fine. Trust
  the PID file at `~/.claude-mem/worker.pid` and probe
  `http://127.0.0.1:<port>/api/health` directly.

[cm]: https://github.com/thedotmack/claude-mem
