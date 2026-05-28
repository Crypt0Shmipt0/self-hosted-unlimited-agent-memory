# Tailscale-sandbox extension

For ephemeral sandboxes (Cowork, cloud containers, CI runners) that
**can** install kernel-mode VPN but only for the duration of one session.

This extension covers two things:

1. How to mint an **ephemeral, reusable, tagged Tailscale auth key**
   so disposable sandboxes can join your tailnet for one session then
   auto-clean
2. How to bring up `tailscaled` inside a sandbox that may not have
   `CAP_NET_ADMIN` or `/dev/net/tun`, falling back to userspace-networking
   mode with a SOCKS5 proxy

## When to use this vs git-handoff

| Situation | Pick |
|---|---|
| Sandbox has internet egress but no LAN access to your home | This (Tailscale) |
| Sandbox only has git push/pull, nothing else | `../git-handoff/` |
| Sandbox is your phone running Termux | This — but install the regular Tailscale Android app, not the CLI dance |
| Sandbox is a Docker container you launched locally | Just expose the port directly, no Tailscale needed |

## One-time Tailscale setup

In the Tailscale admin console:

1. **ACL** → add a tag for sandboxes:
   ```jsonc
   {
     "tagOwners": {
       "tag:ephemeral-sandbox": ["your-email@example.com"]
     },
     "acls": [
       // Sandboxes need to reach your memory server only
       {
         "action": "accept",
         "src":    ["tag:ephemeral-sandbox"],
         "dst":    ["<your-server-host-in-tailnet>:8000"]
       }
     ]
   }
   ```

2. **Settings → Keys** → "Generate auth key":
   - **Reusable**: ON
   - **Ephemeral**: ON (critical — auto-removes node when offline)
   - **Pre-approved**: ON
   - **Tags**: `tag:ephemeral-sandbox`
   - **Expiry**: 90 days

3. Save the key somewhere your sandbox can read at startup. Common
   paths:
   - `~/.config/tailscale/sandbox-authkey` on your machine, then
     mount or copy into the sandbox at session start
   - A secret in your CI / sandbox provider's secrets store
   - For Cowork-style mounted-workspace sandboxes:
     `<workspace>/secrets/tailscale-authkey` (chmod 600)

## Per-session bootstrap (inside the sandbox)

```sh
#!/usr/bin/env bash
set -uo pipefail

# 1. Load the auth key
TS_KEY=$(cat /path/to/your/tailscale-authkey | tr -d '[:space:]')
[ -z "$TS_KEY" ] && { echo "no auth key — bailing"; exit 1; }

# 2. Install Tailscale CLI + daemon
if ! command -v tailscaled >/dev/null 2>&1; then
    curl -fsSL https://tailscale.com/install.sh | sh
fi

# 3. Bring up the daemon. Try kernel-mode first; fall back to userspace.
for MODE in auto userspace-networking; do
    pkill tailscaled 2>/dev/null || true
    sleep 1

    if [ "$MODE" = "userspace-networking" ]; then
        sudo tailscaled \
            --tun=userspace-networking \
            --socket=/tmp/tailscaled.sock \
            --state=/tmp/tailscaled.state \
            --socks5-server=localhost:1055 \
            > /tmp/tailscaled.log 2>&1 &
    else
        sudo tailscaled \
            --socket=/tmp/tailscaled.sock \
            --state=/tmp/tailscaled.state \
            > /tmp/tailscaled.log 2>&1 &
    fi
    sleep 3

    if sudo tailscale --socket=/tmp/tailscaled.sock up \
            --authkey="$TS_KEY" \
            --hostname="sandbox-$(date +%s)" \
            --ephemeral \
            --accept-routes 2>&1; then
        echo "✓ tailscale up in mode=$MODE"

        # Verify the server is reachable through whichever mode worked
        if [ "$MODE" = "userspace-networking" ]; then
            # Must use SOCKS5 proxy for everything network-related
            export ALL_PROXY=socks5h://localhost:1055
            curl --socks5-hostname localhost:1055 \
                 --max-time 5 -sS \
                 http://<your-server-host>:8000/api/v2/heartbeat && break
        else
            # Kernel mode — routing is in place
            curl --max-time 5 -sS \
                 http://<your-server-host>:8000/api/v2/heartbeat && break
        fi
    fi
done
```

## Userspace mode caveats

If the sandbox can't run kernel mode (most containers without
`CAP_NET_ADMIN` can't), userspace mode is your fallback but has
important constraints:

- **Other processes don't see the routes**. Tailscale's tun device
  doesn't exist; the daemon proxies through a SOCKS5 server it spins
  up on `localhost:1055`.
- **You must set `ALL_PROXY=socks5h://localhost:1055`** before running
  any client that needs to reach the tailnet. The `socks5h` (vs `socks5`)
  matters — it does DNS through the proxy too.
- **DNS may not resolve MagicDNS names** unless the client uses the
  SOCKS5h proxy. Use raw `100.X.Y.Z` Tailscale IPs as a fallback.
- **Performance**: ~30-50% slower than kernel mode. Fine for a memory
  server (small payloads); painful for bulk transfers.

## Tear-down

Ephemeral nodes auto-disappear within ~5 min of disconnect. To force
immediate cleanup:

```sh
sudo tailscale --socket=/tmp/tailscaled.sock logout
sudo pkill tailscaled
```

If you forget, no harm done — the ephemeral flag means the node
disappears from the tailnet automatically.

## Combining with `--accept-routes`

The bootstrap above uses `--accept-routes` so the sandbox honors any
subnet routes your tailnet advertises (e.g. if your home router is an
exit node or subnet relay, you can reach LAN-only services through it).

If the sandbox should NOT use the tailnet for outbound internet
(e.g. you want it on its own cloud egress for speed/cost), drop
`--accept-routes` and add `--exit-node=` to explicitly opt out.
