#!/usr/bin/env python3
"""Mnemon extraction hook -- auto-extracts memories from session transcripts.

Fires on Stop and PreCompact events. Reads the session transcript,
calls Haiku to identify knowledge worth remembering, stores in mnemon.db.
Cost: ~$0.002 per extraction.

Requires ANTHROPIC_API_KEY to be set. Without it, extraction is silently skipped.
"""

import sys
import json
import sqlite3
import os
from datetime import datetime, timezone
from pathlib import Path

EXTRACTION_PROMPT = """Analyze this Claude Code session transcript excerpt.
Extract ONLY genuinely useful knowledge worth remembering across future sessions.

Categories (pick the best fit):
- preferences: User's explicit likes, dislikes, or preferences for how things should work
- corrections: When the user corrected an assumption, behavior, or mistake
- decisions: Technical or design decisions made, with rationale if available
- facts: Important facts about the user, their projects, tools, or environment
- procedures: Workflows, steps, or techniques that worked well
- project-knowledge: Architecture, patterns, conventions, or structure for a specific project
- relationships: Connections between concepts, people, tools, or projects

For each item extract, provide a JSON object with:
- content: Concise statement (1-2 sentences MAX). Write as a reusable fact, not as a narrative.
- category: One of the categories above
- importance: 0.0-1.0 (preferences/corrections: 0.7-0.9, decisions: 0.5-0.8, facts: 0.3-0.7)
- confidence: 0.0-1.0 (explicit statement: 0.9+, inferred: 0.6-0.8)
- tags: Array of 1-3 relevant keyword strings

Return ONLY a JSON array. If nothing worth remembering, return [].

Be HIGHLY selective. Only extract knowledge that would meaningfully help in a future session.
Do NOT extract:
- Routine file operations or code edits
- Temporary state or in-progress work
- Things obvious from project files (like file paths already in CLAUDE.md)
- Implementation details of code just written (the code itself is the record)
- Greetings, acknowledgments, or conversational filler

Transcript:
---
{transcript}
---"""


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

    # Fallback: use the immediate directory name
    resolved = Path(cwd).resolve()
    if resolved != home:
        return resolved.name
    return None


def get_db_path(cwd: str) -> Path:
    """Get the database path for the given project directory."""
    return Path(cwd) / ".claude" / "memory" / "mnemon.db"


def extract(transcript_path: str, session_id: str, cwd: str):
    """Run extraction on the last portion of the transcript."""
    try:
        import anthropic
    except ImportError:
        sys.exit(0)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit(0)

    db_path = get_db_path(cwd)
    if not db_path.exists():
        sys.exit(0)

    # Read transcript
    try:
        with open(transcript_path, "r") as f:
            content = f.read()
    except (FileNotFoundError, PermissionError, OSError):
        sys.exit(0)

    # Take last ~4000 chars to keep Haiku cost low
    excerpt = content[-4000:] if len(content) > 4000 else content
    if len(excerpt.strip()) < 200:
        sys.exit(0)

    client = anthropic.Anthropic()

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": EXTRACTION_PROMPT.format(transcript=excerpt),
            }],
        )

        text = response.content[0].text.strip()
        # Handle markdown code fences
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        items = json.loads(text)
        if not isinstance(items, list) or not items:
            sys.exit(0)

        project = detect_project(cwd)
        ts = datetime.now(timezone.utc).isoformat()

        # Store in database
        db = sqlite3.connect(str(db_path))
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")

        stored = 0
        for item in items[:5]:  # Cap at 5 per extraction
            content_text = item.get("content", "").strip()
            if not content_text or len(content_text) < 10:
                continue

            category = item.get("category", "facts")
            if category not in {
                "preferences", "facts", "corrections", "decisions",
                "project-knowledge", "relationships", "procedures",
            }:
                category = "facts"

            cursor = db.execute(
                """INSERT INTO memories
                   (content, category, project, importance, confidence, context,
                    created_at, updated_at, source_session)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    content_text,
                    category,
                    project,
                    max(0.0, min(1.0, item.get("importance", 0.5))),
                    max(0.0, min(1.0, item.get("confidence", 0.8))),
                    "Auto-extracted",
                    ts, ts, session_id,
                ),
            )
            memory_id = cursor.lastrowid
            for tag in item.get("tags", [])[:5]:
                if isinstance(tag, str) and tag.strip():
                    db.execute(
                        "INSERT OR IGNORE INTO tags VALUES (?, ?)",
                        (memory_id, tag.strip().lower()),
                    )
            stored += 1

        db.commit()
        db.close()

    except Exception:
        pass  # Silent failure -- extraction is best-effort


if __name__ == "__main__":
    try:
        hook_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    extract(
        transcript_path=hook_data.get("transcript_path", ""),
        session_id=hook_data.get("session_id", "unknown"),
        cwd=hook_data.get("cwd", ""),
    )
