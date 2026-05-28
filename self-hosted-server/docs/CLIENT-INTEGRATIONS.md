# Client integrations

Tool-by-tool guidance for wiring each AI assistant to the memory server.

The two universal building blocks every integration uses:

1. **`SKILL.md`** (at `~/personal-memory-server/SKILL.md` after install)
   — markdown the AI can read to understand the API and schema
2. **`claude-mem` CLI** (at `~/personal-memory-server/claude-mem`) — bash
   wrapper exposing the 7 common operations

Tools differ in HOW they discover the skill and HOW they invoke the CLI.

## Claude Code (CLI)

The simplest. Symlink the dir into Claude Code's skill discovery path:

```bash
ln -sfn ~/personal-memory-server ~/.claude/skills/personal-memory-server
```

Claude Code auto-loads skills from `~/.claude/skills/` on every session.
The skill's `description` (top of `SKILL.md`) drives autonomous
activation when you ask memory-shaped questions.

Test:
```
You: "Do you remember anything we decided about auth?"
Claude: <activates the personal-memory-server skill, runs claude-mem search>
```

## Claude Desktop

Two paths depending on whether you've set up MCP:

### Without MCP

Paste `SKILL.md` contents into a project's Knowledge Base, or attach
the file when you start a chat that needs memory access. Claude Desktop
reads it as project context.

### With MCP (cleaner)

Set up a `chromadb-mcp` server pointing at your endpoint. There's no
official one yet; the closest is to write a tiny custom MCP server
exposing `search`, `add_narrative`, `add_fact` tools that proxy to the
HTTP API.

(If you write one, please open a PR to add it to this repo's
`extensions/mcp-server/`.)

## Codex / Cursor

Cursor reads `.cursor/rules/` from each project. Add:

```bash
# In any project where you want memory access:
mkdir -p .cursor/rules
cat > .cursor/rules/personal-memory.md <<'EOF'
# Personal Memory Server

For any question about prior decisions, project history, or
"do you remember..." style queries:

1. Read ~/personal-memory-server/SKILL.md
2. Use the claude-mem CLI to search the pool:
   ~/personal-memory-server/claude-mem search "<query>" --project <slug>
3. Or call the Chroma HTTP API directly (see SKILL.md for endpoints)

Endpoint: http://<your-server-host>:8000
Collection: personal_memory

When writing new memories, tag them with the current project's slug
and use a deterministic ID prefix per session.
EOF
```

Cursor's AI surfaces this rule whenever memory-related queries come up.

## Continue.dev

Continue supports custom tools via its config. Add a tool definition:

```json
{
  "tools": [
    {
      "name": "search_memory",
      "description": "Search the personal memory pool for prior context, decisions, and facts.",
      "command": "/Users/<you>/personal-memory-server/claude-mem",
      "args": ["search", "{{query}}", "--n", "5"]
    },
    {
      "name": "add_memory_fact",
      "description": "Save an atomic fact to the personal memory pool.",
      "command": "/Users/<you>/personal-memory-server/claude-mem",
      "args": ["add-fact",
               "--project", "{{project}}",
               "--title", "{{title}}",
               "--doc", "{{doc}}"]
    }
  ]
}
```

Continue's model can call `search_memory` and `add_memory_fact`
autonomously when relevant.

## Cline (VS Code)

Cline supports custom commands via its settings. Add:

```jsonc
{
  "cline.customCommands": [
    {
      "name": "memSearch",
      "description": "Search the personal memory pool",
      "shellCommand": "~/personal-memory-server/claude-mem search \"$ARGS\" --n 5"
    },
    {
      "name": "memAdd",
      "description": "Save a fact to the memory pool",
      "shellCommand": "~/personal-memory-server/claude-mem add-fact --project shared --title \"$TITLE\" --doc \"$DOC\""
    }
  ]
}
```

## Antigravity

Antigravity supports project-level rules files (similar to Cursor).
Drop the same `personal-memory.md` rule as the Cursor example into the
project's rules dir.

If Antigravity supports custom tool invocation via shell: define a tool
calling `~/personal-memory-server/claude-mem search ...`.

If not: the rule + SKILL.md path is enough for the model to know how to
shell out manually.

## Aider

Aider reads markdown context files passed via `--read`. Drop:

```bash
aider --read ~/personal-memory-server/SKILL.md ...
```

Or add to `.aider.conf.yml`:

```yaml
read:
  - ~/personal-memory-server/SKILL.md
```

## ChatGPT (with code interpreter)

Code interpreter can do HTTP requests. Paste the SKILL.md content into
the conversation, then it can call:

```python
import requests
r = requests.post(
    "http://<your-server-host>:8000/api/v2/tenants/default_tenant/databases/default_database/collections/<id>/query",
    json={"query_texts": ["..."], "n_results": 5, ...}
)
```

The catch: ChatGPT's code interpreter is sandboxed without egress to
your home network. You'd need a public HTTPS endpoint (Cloudflare
Tunnel etc.) for this to work, or the git-handoff async pattern.

## Generic shell-based agent

Any agent that runs shell commands can just call the CLI:

```bash
~/personal-memory-server/claude-mem search "what did we decide about X" --n 5
~/personal-memory-server/claude-mem add-fact --project myapp \
    --title "Decided X" --doc "Decided to use approach Y because Z."
```

The CLI prints human-readable output to stdout. For agents that want
structured output, modify the CLI to add a `--json` flag (PR welcome).

## When in doubt

The HTTP API is the canonical surface. Anything from `curl` to a
custom 100-line script can use it. Everything else is convenience.
