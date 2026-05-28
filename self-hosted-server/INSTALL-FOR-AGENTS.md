# Installation Manual for AI Agents

You are an AI assistant (Claude, Codex, Antigravity, Cursor, Continue, etc.)
helping a user deploy their **Personal Memory Server**. Follow this manual
in order. Each phase has explicit verification gates — do not move on until
the gate passes.

## Your job, in one sentence

Stand up a single Chroma vector DB on the user's always-on machine,
configure that machine for off-LAN access via Tailscale, point the user's
AI tools at it, and verify a write→read round-trip works.

## Decision tree before you start

Ask the user these questions in order. Don't assume.

```
1. Do you have a Home Assistant OS / Supervised install?
   ├── Yes → Phase 2 (Server: HA add-on path). Easiest.
   └── No → Do you have an always-on Linux box (Synology, NAS, mini-PC, Pi)?
            ├── Yes → Phase 2-ALT (Server: plain Docker path).
            └── No  → Stop. This project requires an always-on host. Tell
                      the user to set one up first. Cheapest path:
                      $30 used mini-PC + Ubuntu Server.

2. Do you want off-LAN access (sync from cellular, friend's WiFi, cloud sandboxes)?
   ├── Yes → You'll also do Phase 5 (Tailscale).
   └── No  → LAN-only is fine; skip Phase 5.

3. What AI tools does the user run?
   Collect the list. Drives Phase 4 (client wiring) — you'll touch each one.
```

---

## Phase 1: Prerequisites check

Gate: All of the following must be true before Phase 2.

- [ ] Always-on host identified (HA box, NAS, mini-PC, etc.)
- [ ] You have SSH access to the host, OR the HA Supervisor WS API
  token (if HA path)
- [ ] Host has Docker available (HA does; for plain Linux, install
  Docker)
- [ ] Host has at least 1 GB free disk for Chroma data + 1 GB for the
  container image
- [ ] If Tailscale path: user already has a Tailscale account, with the
  host already joined to the tailnet OR willing to install Tailscale on
  the host

If any of those fail, stop and unblock first. Don't try to work around
missing prerequisites.

---

## Phase 2: Deploy the server (HA add-on path)

Use this if the host is Home Assistant OS / Supervised.

### 2.1 SSH key authorization (skip if you already have shell access)

If the user has the `core_ssh` add-on installed but you don't have
key-based access, you can add a key via the Supervisor API:

```python
# Run locally; needs WebSocket + a long-lived user token from HA.
# Token has admin role → can proxy to /addons/core_ssh/options.
import asyncio, json, pathlib, websockets

TOKEN = pathlib.Path("~/.homeassistant/token").expanduser().read_text().strip()
HA_HOST = "<your-ha-ip>:8123"                          # e.g. 10.0.0.X:8123
PUBKEY = pathlib.Path("~/.ssh/id_ed25519.pub").expanduser().read_text().strip()

async def main():
    async with websockets.connect(f"ws://{HA_HOST}/api/websocket") as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        assert json.loads(await ws.recv())["type"] == "auth_ok"

        # Read current options
        await ws.send(json.dumps({"id": 1, "type": "supervisor/api",
                                  "endpoint": "/addons/core_ssh/info", "method": "get"}))
        info = json.loads(await ws.recv())["result"]
        opts = info["options"]

        # Append key (de-dup)
        keys = list(opts.get("authorized_keys", []))
        if PUBKEY not in keys:
            keys.append(PUBKEY)
        new_opts = {**opts, "authorized_keys": keys}

        await ws.send(json.dumps({"id": 2, "type": "supervisor/api",
                                  "endpoint": "/addons/core_ssh/options",
                                  "method": "post", "data": {"options": new_opts}}))
        print("set:", json.loads(await ws.recv()).get("success"))

        await ws.send(json.dumps({"id": 3, "type": "supervisor/api",
                                  "endpoint": "/addons/core_ssh/restart",
                                  "method": "post", "data": {}}))
        print("restart:", json.loads(await ws.recv()).get("success"))

asyncio.run(main())
```

**Gate**: `ssh root@<your-ha-ip>` succeeds.

### 2.2 Install the add-on files

From the user's Mac/Linux, SSH into HA and write the add-on files:

```bash
ssh root@<your-ha-ip> 'mkdir -p /addons/personal_memory_server'

# Copy this repo's ha-addon/ files to the HA box
scp ha-addon/config.yaml ha-addon/Dockerfile \
    root@<your-ha-ip>:/addons/personal_memory_server/

# Create the persistent data dir on /share/ (survives add-on rebuilds + is
# captured by HA backups)
ssh root@<your-ha-ip> 'mkdir -p /share/personal-memory-server'
```

### 2.3 Install and start the add-on via Supervisor

```python
# Same WS auth as 2.1. Reload store, install local add-on, start it.
# Install build can take 3-5 min on first run (Chroma image pull).
async def install():
    async with websockets.connect(f"ws://{HA_HOST}/api/websocket") as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        assert json.loads(await ws.recv())["type"] == "auth_ok"

        async def call(mid, ep, method="get", data=None):
            p = {"id": mid, "type": "supervisor/api", "endpoint": ep, "method": method}
            if data is not None: p["data"] = data
            await ws.send(json.dumps(p))
            return json.loads(await ws.recv())

        await call(1, "/store/reload", "post", {})
        await call(2, "/store/addons/local_personal_memory_server/install", "post", {})
        # Install returns False but build runs async — poll for state==started
        # via /addons/local_personal_memory_server/info.

        # After build finishes:
        await call(3, "/addons/local_personal_memory_server/start", "post", {})
```

Poll add-on state. When build finishes (~3-5 min), start succeeds.

**Gate**: `curl http://<your-ha-ip>:8000/api/v2/heartbeat` returns
`{"nanosecond heartbeat":<int>}`.

---

## Phase 2-ALT: Deploy the server (plain Docker path)

Use this if the host is NOT Home Assistant.

```bash
ssh user@<your-host>

# One-shot. Persists at $HOME/personal-memory-data on the host.
docker run -d \
  --name personal-memory-server \
  --restart unless-stopped \
  -p 8000:8000 \
  -v $HOME/personal-memory-data:/data \
  chromadb/chroma:1.5.9 \
  chroma run --host 0.0.0.0 --port 8000 --path /data

docker logs personal-memory-server | tail -20
curl -sS http://localhost:8000/api/v2/heartbeat
```

**Gate**: heartbeat returns JSON.

---

## Phase 3: Initialize the collection

Run this once from any machine that can reach the server. It creates
the `personal_memory` collection with the schema all clients expect.

```bash
HOST=<your-server-host>
PORT=8000
uvx --with chromadb==1.0.16 python3 <<'PY'
import os, chromadb
c = chromadb.HttpClient(host=os.environ["HOST"], port=int(os.environ["PORT"]))
# Server-side embedding via default function — no client ML needed
col = c.get_or_create_collection(
    name="personal_memory",
    metadata={"description": "Personal cross-tool memory pool"},
)
print(f"collection ready: name={col.name} id={col.id} count={col.count()}")
PY
```

**Gate**: prints `count=0` (or whatever; just no error).

---

## Phase 4: Client setup

For each AI tool the user runs, wire it to the server. Default
endpoint is `http://<your-server-host>:8000`.

### 4.1 Drop the universal SKILL.md + CLI

```bash
# Pick a stable location the user can edit/version-control
mkdir -p ~/personal-memory-server
cp -r client/skill/* ~/personal-memory-server/

# Edit ~/personal-memory-server/SKILL.md and replace the
# <your-server-host> placeholder with the real endpoint
sed -i.bak "s/<your-server-host>/your-actual-host/g" ~/personal-memory-server/SKILL.md
# Same in the bash CLI
sed -i.bak "s/<your-server-host>/your-actual-host/g" ~/personal-memory-server/claude-mem
chmod +x ~/personal-memory-server/claude-mem
```

### 4.2 Per-tool wiring

| Tool | Action |
|---|---|
| **Claude Code (CLI)** | Symlink `~/personal-memory-server/` into `~/.claude/skills/personal-memory-server/`. Claude Code auto-discovers it. |
| **Claude Desktop** | Add an MCP server pointing at Chroma's HTTP API, OR just let the model read `SKILL.md` when prompted. |
| **Codex / Cursor** | In `.cursor/rules/`, add a one-liner: `Read /path/to/SKILL.md before any "remember"/"recall"/"prior decision" question.` |
| **Continue.dev** | Define a custom slash command that shells out to the `claude-mem` CLI. See `docs/CLIENT-INTEGRATIONS.md`. |
| **Cline** | Same — custom tool definition pointing at `claude-mem search`. |
| **Antigravity** | Point its rules file at the SKILL.md path. HTTP API works directly. |
| **Anything that runs bash** | Just call the `claude-mem` CLI directly. |

### 4.3 (Optional) upstream worker

If the user already runs [thedotmack/claude-mem][claude-mem] as a Claude
Code plugin and wants to keep using it: just point its settings at the
new server. Edit `~/.claude-mem/settings.json`:

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

Restart the worker:
```bash
bun ~/.claude/plugins/cache/thedotmack/claude-mem/*/scripts/worker-cli.js restart
```

**Critical**: don't set `CLAUDE_MEM_RUNTIME: "server-beta"` unless the
user has Claude Code OAuth working in that environment. `worker` is the
safe default everywhere else.

**Note**: the upstream plugin uses collection name `cm__claude-mem`
internally, not `personal_memory`. Either:
- Use **only** the upstream plugin (keep `cm__claude-mem`), or
- Use **only** this project's CLI (use `personal_memory`), or
- Run both — they share the host but use different collections.

Choose one with the user.

[claude-mem]: https://github.com/thedotmack/claude-mem

### 4.4 Verify

```bash
~/personal-memory-server/claude-mem health
# → endpoint reachable, count printed

~/personal-memory-server/claude-mem add-fact \
  --project "setup-test" --title "Install verification" \
  --doc "First write from $(hostname) at $(date)"

~/personal-memory-server/claude-mem search "install verification" --n 1
# → finds the doc you just wrote
```

**Gate**: search returns the just-written doc.

---

## Phase 5: Tailscale for off-LAN access (optional)

Skip this if the user is fine with LAN-only.

### 5.1 Server side

If the server box already has Tailscale, skip. Otherwise:

- HA: install the official Tailscale add-on, sign in.
- Plain Linux: `curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up`

### 5.2 Note the Tailscale endpoint

```bash
# From any tailnet-joined machine:
tailscale status | head -10
# Look for the line with the server's hostname; note the 100.X.Y.Z IP
# and the MagicDNS name (something like servername.tailnet-XXXX.ts.net).
```

### 5.3 Update clients to use Tailscale FQDN

Re-run Phase 4.1's `sed`, but replace `<your-server-host>` with the
Tailscale MagicDNS name (preferred — works on LAN AND off-LAN
identically).

If you hit DNS resolution issues inside containers/proots that don't
inherit Tailscale's resolver, fall back to the raw `100.X.Y.Z` IP.

**Gate**: from any tailnet-joined client (turn off WiFi, use cellular
to verify):
```bash
~/personal-memory-server/claude-mem health
```
returns the same pool count as on LAN.

---

## Phase 6: Backup (HA path only — automated)

If you used the HA path, configure backup to include `/share/`:

```python
async with websockets.connect(f"ws://{HA_HOST}/api/websocket") as ws:
    await ws.recv()
    await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
    assert json.loads(await ws.recv())["type"] == "auth_ok"

    await ws.send(json.dumps({
        "id": 1,
        "type": "backup/config/update",
        "create_backup": {
            "include_folders": ["share", "addons/local"],
        },
    }))
    print(json.loads(await ws.recv()))
```

HA's daily backup will now include the Chroma data dir. If the user has
a Nabu Casa subscription or any HA backup target, those backups
auto-replicate offsite.

**Gate**: trigger a manual backup (`backup/generate_with_automatic_settings`),
wait for completion, verify the tar contains `share.tar.gz` with
`personal-memory-server/chroma.sqlite3` inside.

For plain Docker hosts, set up your own backup job (cron + rsync or
borg or restic — out of scope here).

---

## Phase 7: Extensions (optional)

### 7.1 Git-handoff for sandboxed agents

Some AI agents run in sandboxes with no network egress to the user's
home (typical: Cowork sandboxes, certain CI environments, browser-based
ChatGPT/Claude with code interpreter only).

For those, install `extensions/git-handoff/`:

```bash
cp -r extensions/git-handoff/ ~/personal-memory-server/git-handoff/
```

Workflow:
1. The sandboxed agent appends a structured session block to
   `.claude/cowork-session-log.md` in whatever repo it's working on
2. It commits + pushes
3. The user (or a cron on their always-on machine) runs
   `ingest-session.py <repo-path>` which fetches, parses, writes to
   the shared pool

Format spec in `extensions/git-handoff/README.md`.

### 7.2 Tailscale ephemeral keys for short-lived sandboxes

For sandboxes that CAN install kernel-mode VPNs, install
`extensions/tailscale-sandbox/`. Documents:
- How to mint an ephemeral, reusable, tagged auth key in the Tailscale
  admin console
- How to bring up `tailscaled --tun=userspace-networking` for sandboxes
  without `CAP_NET_ADMIN`
- How to swap to SOCKS5 proxy mode when the host's stack can't take
  routes

---

## Phase 8: Hand off to the user

When all gates pass, summarize:

```
Personal Memory Server is live.

Server:    http://<your-server-host>:8000  (LAN)
           http://<tailscale-fqdn>:8000    (off-LAN, if configured)
Collection:  personal_memory
Backup:    daily HA backup, includes /share/personal-memory-server/
           (or: configure your own cron+rsync if Docker path)

Client CLI:  ~/personal-memory-server/claude-mem
Skill doc:   ~/personal-memory-server/SKILL.md  (read by Claude Code et al.)

Tools wired:
  - <list each one>

Current pool size: <N>

Try it:
  ~/personal-memory-server/claude-mem search "topic"
  ~/personal-memory-server/claude-mem add-fact --project P --title T --doc D
```

---

## Common failure modes (read this before starting)

| Symptom | Likely cause | Fix |
|---|---|---|
| HA add-on install returns `success: False` but `info` shows nothing | Build is running async; the API returned before completion. Wait 3-5 min, then check `info.state`. | Patience |
| `chroma run` fails with "unrecognized subcommand 'chroma'" | The chromadb 1.x image's entrypoint hard-codes `/data`. Override via `ENTRYPOINT` not `CMD`. | Use the Dockerfile in this repo — it already does the override |
| Worker errors `KeyError('_type')` | Wrong Chroma server version vs client. Server must be 1.x; older client metadata isn't readable by 0.5.x server (and vice versa). | Use Chroma 1.5.x server |
| Tailscale MagicDNS doesn't resolve inside a proot | Proot's `/etc/resolv.conf` is a snapshot, not live | Use the raw `100.X.Y.Z` IP instead of the FQDN |
| `worker-cli.js status` reports "Process died" but worker is running | Known bug — CLI probes port 37777, worker binds 37700 (or 37700+UID%100) | Trust the PID file + `/api/health` instead |
| `col.get(where={...})` returns "Expected where to have exactly one operator" | Chroma 1.5.x requires `$and` for multi-key filters | Wrap multi-key filters: `{"$and": [{"k1":"v1"}, {"k2":"v2"}]}` |
| Setting `CLAUDE_MEM_RUNTIME: "server-beta"` errors on every device except the user's primary Mac | server-beta needs OAuth credentials only present on the source machine | Use `"worker"` everywhere else |
| `git pull` after Cowork-Claude push gets "remote contains work that you do not have locally" | Sandboxes sometimes force-push. The ingester's marker commit and the sandbox's rebase race. | Re-run with `--no-commit`, or rebase locally |

## Pre-flight checklist before declaring "done"

- [ ] `curl http://<endpoint>:8000/api/v2/heartbeat` from at least 3 different devices/networks, all return JSON
- [ ] The `personal_memory` collection exists and `count > 0` after at least one test write
- [ ] At least one AI tool successfully wrote a doc via the SKILL.md / CLI path (not just curl)
- [ ] At least one AI tool successfully searched and got back its own write
- [ ] Backups run (HA daily, or your cron) and include the data dir
- [ ] If Tailscale: a client on a different network can hit the endpoint
- [ ] User has the host info (endpoint, collection name, CLI path) and the SKILL.md location in their notes

If all 7 pass, you're done. Hand off to the user with the summary
template in Phase 8.
