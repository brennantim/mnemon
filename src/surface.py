#!/usr/bin/env python3
"""Mnemon surface hook -- regenerates .claude/rules/mnemon-memories.md at SessionStart.

Reads the memory store, scores each memory, and generates a concise
rules file (~120 lines) organized by category. Project-aware:
surfaces project-specific memories when in a project directory.

Writes to rules/ instead of CLAUDE.md so the user can freely edit
CLAUDE.md for their own instructions.
"""

import sys
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MAX_LINES = 120

HEADER = """# Mnemon Memory System
# Auto-generated at session start. Do not edit manually.
# Store: mcp__mnemon__remember | Search: mcp__mnemon__recall
# Commands: /remember, /forget, /memory-status

"""


def get_db_path(cwd: str) -> Path:
    """Get the database path for the given project directory."""
    return Path(cwd) / ".claude" / "memory" / "mnemon.db"


def get_output_path(cwd: str) -> Path:
    """Get the output rules file path for the given project directory."""
    return Path(cwd) / ".claude" / "rules" / "mnemon-memories.md"


def score_memory(row: dict) -> float:
    """Composite score: importance * confidence * frequency_boost * time_decay."""
    importance = row["importance"] or 0.5
    confidence = row["confidence"] or 0.8
    access = row["access_count"] or 0
    freq_boost = 1.0 + (access * 0.1)

    try:
        created = datetime.fromisoformat(row["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        hours_old = (datetime.now(timezone.utc) - created).total_seconds() / 3600
        decay = 0.998 ** max(hours_old, 0)  # Gentler decay than 0.995
    except (ValueError, TypeError):
        decay = 0.5

    return importance * confidence * freq_boost * decay


def detect_project(cwd: str) -> str | None:
    """Detect project name from working directory.

    Walks up from cwd looking for .claude/ or CLAUDE.md to find the project root,
    then uses that directory's name. Falls back to basename of cwd.
    """
    current = Path(cwd).resolve()
    home = Path.home()

    while current != current.parent and current != home:
        if (current / ".claude").is_dir() or (current / "CLAUDE.md").exists():
            return current.name
        current = current.parent

    resolved = Path(cwd).resolve()
    if resolved != home:
        return resolved.name
    return None


def build_section(title: str, items: list[dict], max_items: int = 8) -> list[str]:
    """Build a markdown section from scored memory items."""
    if not items:
        return []
    lines = [f"## {title}\n"]
    for m in items[:max_items]:
        lines.append(f"- {m['content']}\n")
    lines.append("\n")
    return lines


def surface(cwd: str):
    """Regenerate mnemon-memories.md with top-scored memories."""
    db_path = get_db_path(cwd)
    output_path = get_output_path(cwd)

    if not db_path.exists():
        return

    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row

    rows = db.execute(
        "SELECT * FROM memories WHERE superseded_by IS NULL"
    ).fetchall()

    if not rows:
        db.close()
        return

    project = detect_project(cwd)

    # Score and convert to dicts
    scored = []
    for r in rows:
        d = dict(r)
        d["_score"] = score_memory(d)
        scored.append(d)

    scored.sort(key=lambda x: x["_score"], reverse=True)

    # Build sections
    lines = [HEADER]

    # Preferences (global, always show first)
    prefs = [m for m in scored if m["category"] == "preferences"]
    lines.extend(build_section("Preferences", prefs, 8))

    # Corrections (critical -- prevent repeated mistakes)
    corrections = [m for m in scored if m["category"] == "corrections"]
    lines.extend(build_section("Corrections (Do Not Repeat)", corrections, 5))

    # Key facts
    facts = [m for m in scored if m["category"] == "facts"]
    lines.extend(build_section("Key Facts", facts, 6))

    # Current project knowledge
    if project:
        proj_items = [
            m for m in scored
            if m["project"] == project
            and m["category"] not in ("preferences", "corrections")
        ]
        if proj_items:
            lines.append(f"## Current Project: {project}\n")
            for m in proj_items[:8]:
                lines.append(f"- [{m['category']}] {m['content']}\n")
            lines.append("\n")

    # Decisions
    decisions = [m for m in scored if m["category"] == "decisions"]
    lines.extend(build_section("Past Decisions", decisions, 5))

    # Procedures
    procs = [m for m in scored if m["category"] == "procedures"]
    lines.extend(build_section("Known Procedures", procs, 5))

    # Relationships
    rels = [m for m in scored if m["category"] == "relationships"]
    lines.extend(build_section("Relationships", rels, 4))

    # Footer with stats
    total = db.execute(
        "SELECT count(*) FROM memories WHERE superseded_by IS NULL"
    ).fetchone()[0]
    lines.append(f"---\n*Mnemon: {total} memories stored. Use `mcp__mnemon__recall` to search the full store.*\n")

    db.close()

    # Respect line limit
    content = "".join(lines)
    output_lines = content.split("\n")[:MAX_LINES]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(output_lines) + "\n")


if __name__ == "__main__":
    try:
        hook_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_data = {}

    surface(cwd=hook_data.get("cwd", ""))
