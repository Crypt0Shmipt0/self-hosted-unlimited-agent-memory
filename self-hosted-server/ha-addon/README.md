# Home Assistant Add-on: Personal Memory Server

A local HA add-on that runs Chroma 1.5.9 with persistent storage on
`/share/` so the data survives add-on rebuilds and gets captured by
your daily HA backups.

## What this add-on does

- Runs a single Chroma vector DB instance on port 8000
- Persists data to `/share/personal-memory-server/` (NOT the per-add-on
  `/data/` which gets wiped on uninstall)
- Boot-on-start, restart-on-crash via Supervisor
- AMD64 + ARM64 supported

## What this add-on does NOT do

- No authentication (intra-LAN/tailnet only — don't expose to internet
  without a reverse proxy doing auth)
- No TLS (terminate at a reverse proxy if you need it)
- No client (use the `client/` dir of this repo for that)

## Install

Two paths:

### Option A: Drop the files in `/addons/`

```bash
ssh root@<your-ha-host>
mkdir -p /addons/personal_memory_server
# Copy config.yaml and Dockerfile from this dir into /addons/personal_memory_server/
mkdir -p /share/personal-memory-server
```

Then in the HA UI: Settings → Add-ons → Add-on Store → ⋮ → Check for updates.
The "Personal Memory Server" add-on appears under "Local add-ons". Click
Install. First install builds the Docker image (~3-5 min).

After install, set **Start on boot** → ON, then click Start.

### Option B: Via the Supervisor API (scripted)

See [`INSTALL-FOR-AGENTS.md`](../INSTALL-FOR-AGENTS.md) Phase 2.3 for the
Python snippet that automates this via the HA WebSocket API.

## Verify

```bash
curl -sS http://<your-ha-host>:8000/api/v2/heartbeat
# → {"nanosecond heartbeat":<int>}
```

## Configuration

None. The add-on is intentionally simple — no options to misconfigure.

If you need different behavior (auth, TLS, alternative data path), fork
the Dockerfile and edit the `ENTRYPOINT`.

## Backup integration

Add `share` to your HA backup config so the Chroma data is included:

```python
# Once per HA install; via the backup/config/update WS API
{"create_backup": {"include_folders": ["share", "addons/local"]}}
```

If you have a Nabu Casa subscription, daily backups auto-replicate
offsite (encrypted). Retention is configurable in Settings → System →
Backups → Settings.

## Restore from backup

1. Stop the add-on
2. Decrypt the backup tar with the password from `backup/config/info`
3. Extract `share.tar.gz` and copy `personal-memory-server/*` into
   `/share/personal-memory-server/` on the HA box
4. Start the add-on
5. Verify count matches what was in the backup

See [`../docs/BACKUP-RESTORE.md`](../docs/BACKUP-RESTORE.md) for the
full restore script.

## Image source

Upstream: `chromadb/chroma:1.5.9` from Docker Hub.

Why pinned: claude-mem's chroma-mcp 0.2.6 (the upstream Claude Code
plugin) needs `chromadb>=1.0.16`. Server-side, 1.5.9 is the last stable
non-dev tag as of 2026-05. Newer versions should work but haven't been
verified against the upstream plugin's client.

## Resource usage

Idle: ~150 MB RAM, ~0% CPU. Per-write: brief spike during embedding.
Disk grows roughly 1-5 KB per stored observation (vector + metadata +
HNSW index entries). A 10,000-observation pool sits around 25-50 MB.
