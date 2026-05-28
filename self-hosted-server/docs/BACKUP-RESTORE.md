# Backup & restore

## What's at stake

The Chroma data dir contains:

- `chroma.sqlite3` — collection registry, document text, metadata
- `<segment-uuid>/*.bin` — HNSW vector index (rebuildable from sqlite if
  necessary, but very slow at scale)

Losing this means losing the cross-session memory pool. Backup is
not optional.

## HA-native (preferred)

If the server runs as the Home Assistant add-on, you already have
incremental backup with offsite replication via Nabu Casa Cloud (if
subscribed) or any HA backup target you've configured.

### Configure include_folders once

```python
import asyncio, json, pathlib, websockets
TOKEN = pathlib.Path("~/.homeassistant/token").expanduser().read_text().strip()
HA_HOST = "<your-ha-ip>:8123"

async def main():
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

asyncio.run(main())
```

This makes HA's daily auto-backup include `/share/` (where the Chroma
data lives) and `addons/local` (where the add-on definition lives).

### Trigger a manual backup

```python
async def trigger():
    async with websockets.connect(f"ws://{HA_HOST}/api/websocket") as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        assert json.loads(await ws.recv())["type"] == "auth_ok"
        await ws.send(json.dumps({
            "id": 1,
            "type": "backup/generate_with_automatic_settings",
        }))
        print(json.loads(await ws.recv()))
```

State machine: idle → `create_backup` → idle. Poll
`sensor.backup_backup_manager_state` to detect completion.

### Verify a backup contains the data

```bash
# Pull the latest backup to your Mac
scp root@<your-ha-ip>:/backup/Automatic_backup_*.tar /tmp/

# Extract just the share component
cd /tmp
tar -xf Automatic_backup_*.tar share.tar.gz backup.json
```

`backup.json` contains the encryption metadata. If `"protected": true`,
the inner tarballs are encrypted with the password in
`backup/config/info` → `create_backup.password`.

### Decrypt + inspect

```bash
# Read password from HA via WS API
PASSWORD=$(python3 -c "
import asyncio, json, pathlib, websockets
async def m():
    t = pathlib.Path('~/.homeassistant/token').expanduser().read_text().strip()
    async with websockets.connect('ws://<your-ha-ip>:8123/api/websocket') as ws:
        await ws.recv()
        await ws.send(json.dumps({'type':'auth','access_token':t}))
        await ws.recv()
        await ws.send(json.dumps({'id':1,'type':'backup/config/info'}))
        r = await ws.recv()
        print(json.loads(r)['result']['config']['create_backup']['password'])
asyncio.run(m())
")

# Use securetar to decrypt
uvx --from securetar python3 - <<PY
from securetar import SecureTarFile
import tarfile
with SecureTarFile(name='/tmp/share.tar.gz', gzip=True, password='$PASSWORD') as tf:
    for member in tf:
        if member.name == 'personal-memory-server/chroma.sqlite3':
            f = tf.extractfile(member)
            with open('/tmp/restored-chroma.sqlite3', 'wb') as out:
                out.write(f.read())
            print(f"extracted: {member.size} bytes")
            break
PY

# Sanity-check the extracted SQLite
sqlite3 /tmp/restored-chroma.sqlite3 "SELECT COUNT(*) FROM embeddings;"
```

## Restore procedure

### From an HA backup

```bash
# 1. Stop the add-on (Supervisor API or HA UI)

# 2. SSH into HA
ssh root@<your-ha-ip>

# 3. Move existing data aside (don't delete in case restore fails)
mv /share/personal-memory-server /share/personal-memory-server.broken

# 4. Restore the share.tar.gz contents into /share/
#    (Inside the encrypted tar, the structure is:
#     personal-memory-server/chroma.sqlite3
#     personal-memory-server/<segment-uuid>/*.bin )
mkdir -p /share/personal-memory-server
# (Either use securetar locally then scp the files in,
#  OR use HA's "Restore from backup" UI which handles this end-to-end)

# 5. Start the add-on

# 6. Verify
curl -sS http://localhost:8000/api/v2/heartbeat
uvx --with chromadb==1.0.16 python3 -c "
import chromadb
c = chromadb.HttpClient(host='localhost', port=8000)
for col in c.list_collections():
    print(f'{col.name}={col.count()}')
"
```

If the count matches what you expect, delete the `.broken` dir to
reclaim space.

### From a plain Docker host (your own cron+rsync)

```bash
# Stop container
docker stop personal-memory-server

# Restore
rsync -a /path/to/yesterday/personal-memory-data/ ~/personal-memory-data/

# Restart
docker start personal-memory-server

# Verify
curl -sS http://localhost:8000/api/v2/heartbeat
```

## Quick disaster-recovery checklist

If you suspect data loss:

- [ ] STOP writes immediately (stop the worker / the upstream plugin)
- [ ] `ls -la /share/personal-memory-server/` — is the dir intact?
- [ ] `curl /api/v2/heartbeat` — is the server up?
- [ ] `sqlite3 chroma.sqlite3 "SELECT COUNT(*) FROM embeddings"` — does
      the count match what you expect (or what your most recent backup
      shows)?
- [ ] If count is much lower than expected: restore from yesterday's
      backup and figure out what wiped things
- [ ] If count looks fine but queries return nothing: collection name
      mismatch? embeddings rebuilt with a different model? hit
      `/api/v2/tenants/.../collections` to see what's actually there

## Backup verification cron (recommended)

Every Sunday, run an end-to-end backup→restore test against a throwaway
Chroma instance to confirm backups actually work:

```bash
#!/usr/bin/env bash
# verify-backup.sh — Sunday cron
set -euo pipefail

LATEST=$(ssh root@<your-ha-ip> 'ls -t /backup/*.tar | head -1')
scp "root@<your-ha-ip>:$LATEST" /tmp/test-backup.tar

# Spin up a throwaway Chroma
docker rm -f chroma-verify 2>/dev/null
docker run -d --name chroma-verify -p 8001:8000 chromadb/chroma:1.5.9 \
    chroma run --host 0.0.0.0 --port 8000 --path /data

# Extract share.tar.gz, decrypt, drop into the throwaway
# (left as exercise; full script in this file's git history if needed)

# Probe the throwaway
sleep 5
curl -sS http://localhost:8001/api/v2/heartbeat

# Cleanup
docker rm -f chroma-verify
rm /tmp/test-backup.tar
```

If this fails any Sunday, you have time to fix backups before you
actually need them.
