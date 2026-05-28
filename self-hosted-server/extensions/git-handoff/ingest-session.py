#!/usr/bin/env python3
"""ingest-cowork-session.py

Mac-side ingester for Cowork-Claude session digests handed off via git.

USAGE:
  uvx --with chromadb==1.0.16 python3 ingest-cowork-session.py <repo-path>

  # Dry run (parse + show what would be written, don't push to Chroma)
  uvx --with chromadb==1.0.16 python3 ingest-cowork-session.py <repo-path> --dry-run

  # Don't commit/push the INGESTED markers back (e.g. on a feature branch you
  # haven't merged yet and don't want to dirty)
  uvx --with chromadb==1.0.16 python3 ingest-cowork-session.py <repo-path> --no-commit

WHAT IT DOES:
  1. git pull --ff-only the repo (or skip with --no-pull)
  2. Parse `.claude/cowork-session-log.md` for session blocks not yet marked
     `<!-- INGESTED ... -->`
  3. For each unprocessed block: write 1 narrative + N facts + M blockers to
     the shared Chroma collection at <your-server-host>:8000.
     Server-side embedding (the collection's `default` embedding function)
     handles vectorization — no onnxruntime / heavy ML needed client-side.
  4. Insert `<!-- INGESTED ... -->` markers in the log after the heading line
     so re-runs are idempotent
  5. commit + push the markers back (unless --no-commit)

INGESTION SCHEMA:
  Every doc gets:
    title              from "## Session DATE — Title"
    subtitle           first 200 chars of narrative
    project            from "Project tag" metadata bullet
    doc_type           "observation"
    type               "observation"
    field_type         "narrative" | "fact"
    memory_session_id  from "Memory session UUID" metadata bullet
    created_at_epoch   now in ms
    source             "cowork-session-log"
    cowork_container   from "Container" metadata bullet
    cowork_branch      from "Branch" metadata bullet

  IDs:  <id_prefix>_narrative
        <id_prefix>_fact_0, _fact_1, …
        <id_prefix>_blocker_0, _blocker_1, …
  where id_prefix comes from the "ID prefix" metadata bullet (strip trailing _*).

REQUIRES:
  - chromadb python client (provided via uvx --with)
  - The remote Chroma collection `cm__claude-mem` to be reachable
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    import chromadb
except ImportError:
    sys.stderr.write(
        "chromadb not installed. Run via:\n"
        "  uvx --with chromadb==1.0.16 python3 " + sys.argv[0] + " <repo>\n"
    )
    sys.exit(2)


COLLECTION = "personal_memory"
INGESTED_MARKER = "<!-- INGESTED "
LOG_RELPATH = ".claude/cowork-session-log.md"


# ─────────────────────────────────────────────────────────────────────────
# Parsing
# ─────────────────────────────────────────────────────────────────────────


def find_unprocessed_blocks(log_path: Path) -> list[tuple[int, str]]:
    """Return list of (heading_line_index, block_text) for blocks lacking the
    INGESTED marker on the line immediately after the heading."""
    text = log_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    blocks: list[tuple[int, str]] = []
    cur_start: int | None = None
    cur_lines: list[str] = []
    cur_processed: bool = False

    def flush():
        if cur_start is not None and not cur_processed and cur_lines:
            blocks.append((cur_start, "\n".join(cur_lines)))

    for i, ln in enumerate(lines):
        if ln.startswith("## Session "):
            flush()
            cur_start = i
            cur_lines = [ln]
            cur_processed = False
        elif cur_start is not None:
            if INGESTED_MARKER in ln:
                cur_processed = True
            cur_lines.append(ln)
    flush()

    return blocks


def parse_block(block_text: str) -> dict:
    """Parse a session block markdown into a structured dict."""
    lines = block_text.split("\n")
    heading = lines[0]
    m = re.match(r"^##\s+Session\s+(\S+)\s*[-—]+\s*(.+)$", heading)
    if not m:
        raise ValueError(f"Heading doesn't match `## Session DATE — Title`: {heading!r}")
    session_date = m.group(1).strip()
    title = m.group(2).strip()

    meta: dict[str, str] = {}
    section: str | None = None
    narrative_lines: list[str] = []
    facts: list[str] = []
    blockers: list[str] = []
    open_decisions: list[str] = []
    files_touched: list[str] = []
    final_sha: str | None = None

    for ln in lines[1:]:
        stripped = ln.strip()
        if stripped.startswith("### "):
            section = stripped[4:].strip().lower()
            # Normalize "blockers (if any)" → "blockers"
            section = re.sub(r"\s*\(.*?\)\s*$", "", section).strip()
            continue
        if stripped.startswith("- **") and section is None:
            mm = re.match(r"^- \*\*([^*]+):\*\*\s*(.*)$", stripped)
            if mm:
                key = mm.group(1).strip().lower().replace(" ", "_")
                val = mm.group(2).strip()
                meta[key] = val
            continue
        if section == "narrative":
            if stripped:
                narrative_lines.append(stripped)
        elif section == "facts":
            if stripped.startswith("- "):
                facts.append(stripped[2:].strip())
        elif section == "blockers":
            if stripped.startswith("- "):
                blockers.append(stripped[2:].strip())
        elif section in ("open decisions", "decisions", "open decisions for next session", "open questions"):
            if stripped.startswith("- "):
                open_decisions.append(stripped[2:].strip())
        elif section == "files touched":
            if stripped.startswith("- "):
                files_touched.append(stripped[2:].strip())
        elif section and section.startswith("final commit"):
            mm = re.search(r"`([0-9a-f]{6,40})`", stripped)
            if mm and not final_sha:
                final_sha = mm.group(1)

    id_prefix = meta.get("id_prefix", f"cowork_{int(time.time())}").replace("*", "").rstrip("_")
    memory_session_id = meta.get("memory_session_uuid") or str(uuid.uuid4())

    return {
        "date": session_date,
        "title": title,
        "id_prefix": id_prefix,
        "project": meta.get("project_tag", "general"),
        "memory_session_id": memory_session_id,
        "container": meta.get("container", ""),
        "branch": meta.get("branch", ""),
        "narrative": " ".join(narrative_lines).strip(),
        "facts": facts,
        "blockers": blockers,
        "open_decisions": open_decisions,
        "files_touched": files_touched,
        "final_sha": final_sha,
        "raw_meta": meta,
    }


# ─────────────────────────────────────────────────────────────────────────
# Chroma writes
# ─────────────────────────────────────────────────────────────────────────


def ingest_block(col, parsed: dict) -> dict:
    """Push narrative + facts + blockers to chroma. Returns counts."""
    now_ms = int(time.time() * 1000)
    subtitle = (parsed["narrative"][:200] or parsed["title"]).strip()

    base_metadata = {
        "title": parsed["title"],
        "subtitle": subtitle,
        "project": parsed["project"],
        "doc_type": "observation",
        "type": "observation",
        "memory_session_id": parsed["memory_session_id"],
        "created_at_epoch": now_ms,
        "source": "cowork-session-log",
        "cowork_container": parsed["container"],
        "cowork_branch": parsed["branch"],
    }
    if parsed["final_sha"]:
        base_metadata["cowork_commit_sha"] = parsed["final_sha"]

    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict] = []

    if parsed["narrative"]:
        ids.append(f"{parsed['id_prefix']}_narrative")
        docs.append(parsed["narrative"])
        metas.append({**base_metadata, "field_type": "narrative"})

    for i, fact in enumerate(parsed["facts"]):
        ids.append(f"{parsed['id_prefix']}_fact_{i}")
        docs.append(fact)
        metas.append({**base_metadata, "field_type": "fact", "fact_index": i})

    base_idx = len(parsed["facts"])
    for j, blk in enumerate(parsed["blockers"]):
        ids.append(f"{parsed['id_prefix']}_blocker_{j}")
        docs.append(blk)
        metas.append({
            **base_metadata,
            "field_type": "fact",
            "fact_index": base_idx + j,
            "concepts": "blocker",
        })

    base_idx2 = len(parsed["facts"]) + len(parsed["blockers"])
    for k, dec in enumerate(parsed.get("open_decisions", [])):
        ids.append(f"{parsed['id_prefix']}_decision_{k}")
        docs.append(dec)
        metas.append({
            **base_metadata,
            "field_type": "fact",
            "fact_index": base_idx2 + k,
            "concepts": "open_decision",
        })

    if not ids:
        return {"narrative": 0, "facts": 0, "blockers": 0, "open_decisions": 0, "total": 0}

    col.add(ids=ids, documents=docs, metadatas=metas)
    return {
        "narrative": 1 if parsed["narrative"] else 0,
        "facts": len(parsed["facts"]),
        "blockers": len(parsed["blockers"]),
        "open_decisions": len(parsed.get("open_decisions", [])),
        "total": len(ids),
    }


# ─────────────────────────────────────────────────────────────────────────
# Marker management
# ─────────────────────────────────────────────────────────────────────────


def mark_ingested(log_path: Path, block_start_line: int, summary: str) -> None:
    """Insert `<!-- INGESTED ... -->` marker on the line right after the
    `## Session …` heading. Idempotent — won't add a duplicate if one
    already exists immediately after."""
    text = log_path.read_text(encoding="utf-8")
    lines = text.split("\n")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    marker = f"{INGESTED_MARKER}{ts}Z — {summary} -->"

    # Skip if next line already a marker
    if block_start_line + 1 < len(lines) and INGESTED_MARKER in lines[block_start_line + 1]:
        return

    lines.insert(block_start_line + 1, marker)
    log_path.write_text("\n".join(lines), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────
# Git helpers
# ─────────────────────────────────────────────────────────────────────────


def git_pull(repo: Path) -> None:
    print(f"[git] pulling {repo}")
    subprocess.run(["git", "-C", str(repo), "fetch"], check=False)
    subprocess.run(["git", "-C", str(repo), "pull", "--ff-only"], check=False)


def git_current_branch(repo: Path) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"],
        capture_output=True, text=True, check=False,
    )
    return r.stdout.strip()


def git_commit_and_push(repo: Path, count: int) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "add", LOG_RELPATH],
        check=False,
    )
    # Only commit if there are staged changes
    diff = subprocess.run(
        ["git", "-C", str(repo), "diff", "--cached", "--quiet"],
        check=False,
    )
    if diff.returncode == 0:
        print("[git] no marker changes to commit")
        return
    msg = f"chore: mark {count} cowork session block(s) ingested"
    subprocess.run(["git", "-C", str(repo), "commit", "-m", msg], check=False)
    branch = git_current_branch(repo)
    if branch:
        subprocess.run(["git", "-C", str(repo), "push", "origin", branch], check=False)
        print(f"[git] pushed marker commit to {branch}")


# ─────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", help="Path to repo containing .claude/cowork-session-log.md")
    ap.add_argument("--host", default="<your-server-host>")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-pull", action="store_true", help="Skip git pull")
    ap.add_argument("--no-commit", action="store_true", help="Skip commit/push of INGESTED markers")
    ap.add_argument("--dry-run", action="store_true", help="Parse + show, don't write to Chroma")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    log_path = repo / LOG_RELPATH
    if not log_path.exists():
        print(f"No log at {log_path}")
        sys.exit(1)

    if not args.no_pull:
        git_pull(repo)

    blocks = find_unprocessed_blocks(log_path)
    print(f"Found {len(blocks)} unprocessed block(s) in {log_path}")
    if not blocks:
        return

    if not args.dry_run:
        client = chromadb.HttpClient(host=args.host, port=args.port)
        col = client.get_collection(COLLECTION)
        start_count = col.count()
        print(f"Connected to {args.host}:{args.port} → {COLLECTION} (start count: {start_count})")
    else:
        col = None
        start_count = None

    processed = 0
    for start_line, block_text in blocks:
        try:
            parsed = parse_block(block_text)
        except Exception as e:
            print(f"  ✗ skip block at line {start_line}: {e}")
            continue

        print(f"\nBlock @ line {start_line}: {parsed['date']} — {parsed['title']}")
        print(f"  id_prefix:           {parsed['id_prefix']}")
        print(f"  project:             {parsed['project']}")
        print(f"  memory_session_id:   {parsed['memory_session_id']}")
        print(f"  narrative chars:     {len(parsed['narrative'])}")
        print(f"  facts:               {len(parsed['facts'])}")
        print(f"  blockers:            {len(parsed['blockers'])}")
        print(f"  open_decisions:      {len(parsed.get('open_decisions', []))}")

        if args.dry_run:
            n = (1 if parsed["narrative"] else 0) + len(parsed["facts"]) + len(parsed["blockers"]) + len(parsed.get("open_decisions", []))
            print(f"  (dry-run) would write {n} docs")
            continue

        result = ingest_block(col, parsed)
        print(f"  ✓ wrote: {result}")
        summary = f"{parsed['id_prefix']} n={result['narrative']} f={result['facts']} b={result['blockers']} d={result['open_decisions']}"
        mark_ingested(log_path, start_line, summary)
        processed += 1

    if not args.dry_run and col is not None:
        end_count = col.count()
        print(f"\nPool count: {start_count} → {end_count} (Δ +{end_count - start_count})")

    if processed and not args.dry_run and not args.no_commit:
        git_commit_and_push(repo, processed)


if __name__ == "__main__":
    main()
