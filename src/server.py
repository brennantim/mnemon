#!/usr/bin/env python3
"""Mnemon - Persistent Memory MCP Server for Claude Code.

A self-learning memory system with SQLite + FTS5 full-text search.
Provides 7 tools: remember, recall, correct, forget, list_memories, memory_stats, relate.
"""

import sqlite3
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from fastmcp import FastMCP

DB_PATH = Path.cwd() / ".claude" / "memory" / "mnemon.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    context TEXT,
    project TEXT,
    confidence REAL DEFAULT 0.8,
    importance REAL DEFAULT 0.5,
    access_count INTEGER DEFAULT 0,
    last_accessed TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source_session TEXT,
    superseded_by INTEGER,
    FOREIGN KEY (superseded_by) REFERENCES memories(id)
);

CREATE TABLE IF NOT EXISTS tags (
    memory_id INTEGER NOT NULL,
    tag TEXT NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    PRIMARY KEY (memory_id, tag)
);

CREATE TABLE IF NOT EXISTS relations (
    from_id INTEGER NOT NULL,
    to_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    FOREIGN KEY (from_id) REFERENCES memories(id),
    FOREIGN KEY (to_id) REFERENCES memories(id),
    PRIMARY KEY (from_id, to_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memories_active ON memories(superseded_by) WHERE superseded_by IS NULL;
CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
"""

FTS_SETUP = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content, context, category,
    content='memories',
    content_rowid='id'
);
"""

FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, context, category)
    VALUES (new.id, new.content, new.context, new.category);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, context, category)
    VALUES ('delete', old.id, old.content, old.context, old.category);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, context, category)
    VALUES ('delete', old.id, old.content, old.context, old.category);
    INSERT INTO memories_fts(rowid, content, context, category)
    VALUES (new.id, new.content, new.context, new.category);
END;
"""

MCP_INSTRUCTIONS = """Mnemon is a persistent memory system. Memories survive across sessions.
You are the ONLY mechanism for storing memories. There is no background extraction.
If you don't store it, it's lost.

WHEN TO STORE (mcp__mnemon__remember):
- User explicitly corrects you ("No, I prefer X" / "Actually, do it this way")
- A technical decision is made with rationale
- You discover a user preference through their feedback or behavior
- A procedure or workflow proves successful
- You learn a fact about the user, their projects, tools, or environment
- User says "remember this" or similar
- A project convention or pattern becomes clear
- You make a mistake and get corrected (store the correction, not the mistake)

Be proactive. Don't wait for "/remember". If something is worth knowing next session, store it now.

WHEN TO SEARCH (mcp__mnemon__recall):
- Starting work on a project (recall project-specific knowledge)
- User references past decisions or conversations
- You need user preferences for a task
- Something feels like prior knowledge exists

WHEN TO CORRECT (mcp__mnemon__correct):
- A stored fact turns out to be wrong
- User preferences change

Keep stored content concise: 1-2 sentences max. Write as reusable facts, not narrative.
Do NOT announce memory operations unless directly relevant to conversation."""

mcp = FastMCP("mnemon", instructions=MCP_INSTRUCTIONS)


def get_db() -> sqlite3.Connection:
    """Get database connection with WAL mode. Auto-initializes schema."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.row_factory = sqlite3.Row
    # Auto-initialize
    db.executescript(SCHEMA_SQL)
    # FTS requires separate handling (can't use IF NOT EXISTS check easily)
    try:
        db.executescript(FTS_SETUP)
        db.executescript(FTS_TRIGGERS)
    except sqlite3.OperationalError:
        pass  # Already exists
    return db


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


VALID_CATEGORIES = {
    "preferences", "facts", "corrections", "decisions",
    "project-knowledge", "relationships", "procedures"
}


@mcp.tool()
def remember(
    content: str,
    category: str = "facts",
    project: str | None = None,
    importance: float = 0.5,
    confidence: float = 0.8,
    tags: list[str] | None = None,
    context: str | None = None,
) -> str:
    """Store a new memory.

    Args:
        content: The knowledge to store (1-2 sentences, concise).
        category: One of: preferences, facts, corrections, decisions, project-knowledge, relationships, procedures.
        project: Project name if project-specific, or None for global.
        importance: 0.0-1.0 how critical this is. Preferences/corrections: 0.7-1.0. Facts: 0.3-0.7.
        confidence: 0.0-1.0 how certain this knowledge is.
        tags: Optional keyword tags for flexible categorization.
        context: Optional note about where/when this was learned.
    """
    if category not in VALID_CATEGORIES:
        return f"Invalid category '{category}'. Use one of: {', '.join(sorted(VALID_CATEGORIES))}"

    importance = max(0.0, min(1.0, importance))
    confidence = max(0.0, min(1.0, confidence))
    ts = now_iso()

    db = get_db()
    try:
        cursor = db.execute(
            """INSERT INTO memories
               (content, category, project, importance, confidence, context,
                created_at, updated_at, source_session)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (content, category, project, importance, confidence, context,
             ts, ts, os.environ.get("SESSION_ID")),
        )
        memory_id = cursor.lastrowid
        if tags:
            for tag in tags:
                db.execute(
                    "INSERT OR IGNORE INTO tags VALUES (?, ?)",
                    (memory_id, tag.strip().lower()),
                )
        db.commit()
        return f"Stored memory #{memory_id} [{category}] (importance={importance}, confidence={confidence})"
    finally:
        db.close()


@mcp.tool()
def recall(
    query: str,
    category: str | None = None,
    project: str | None = None,
    limit: int = 10,
    include_superseded: bool = False,
) -> str:
    """Search memories by text query using full-text search.

    Args:
        query: Search terms (supports FTS5 syntax: AND, OR, NOT, "exact phrase").
        category: Filter by category (optional).
        project: Filter by project name. Also includes global memories (optional).
        limit: Max results to return (default 10).
        include_superseded: If true, also search retired/superseded memories (default false).
    """
    db = get_db()
    try:
        conditions: list[str] = []
        if not include_superseded:
            conditions.append("m.superseded_by IS NULL")
        params: list = []

        if category:
            conditions.append("m.category = ?")
            params.append(category)
        if project:
            conditions.append("(m.project = ? OR m.project IS NULL)")
            params.append(project)

        where = (" AND " + " AND ".join(conditions)) if conditions else ""

        # FTS search with ranking
        rows = db.execute(
            f"""SELECT m.id, m.content, m.category, m.project, m.importance,
                       m.confidence, m.access_count, m.created_at,
                       m.superseded_by,
                       rank AS relevance
                FROM memories_fts fts
                JOIN memories m ON m.id = fts.rowid
                WHERE memories_fts MATCH ?{where}
                ORDER BY rank
                LIMIT ?""",
            [query] + params + [limit],
        ).fetchall()

        # Update access counts
        ts = now_iso()
        for row in rows:
            db.execute(
                "UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                (ts, row["id"]),
            )
        db.commit()

        if not rows:
            return "No memories found matching that query."

        results = []
        for r in rows:
            entry = {
                "id": r["id"],
                "content": r["content"],
                "category": r["category"],
                "project": r["project"],
                "importance": r["importance"],
                "confidence": r["confidence"],
                "access_count": r["access_count"],
                "created_at": r["created_at"],
            }
            if include_superseded and r["superseded_by"] is not None:
                entry["superseded"] = True
            results.append(entry)
        return json.dumps(results, indent=2)
    finally:
        db.close()


@mcp.tool()
def correct(
    old_memory_id: int,
    new_content: str,
    reason: str | None = None,
) -> str:
    """Correct or supersede an existing memory. The old memory is preserved but marked as superseded.

    Args:
        old_memory_id: ID of the memory to correct.
        new_content: The corrected knowledge.
        reason: Why this correction was made (optional).
    """
    db = get_db()
    try:
        old = db.execute(
            "SELECT * FROM memories WHERE id = ?", (old_memory_id,)
        ).fetchone()
        if not old:
            return f"Memory #{old_memory_id} not found."

        ts = now_iso()
        cursor = db.execute(
            """INSERT INTO memories
               (content, category, project, importance, confidence, context,
                created_at, updated_at, source_session)
               VALUES (?, ?, ?, ?, 0.9, ?, ?, ?, ?)""",
            (new_content, old["category"], old["project"],
             max(old["importance"], 0.7),
             reason or f"Correction of #{old_memory_id}",
             ts, ts, os.environ.get("SESSION_ID")),
        )
        new_id = cursor.lastrowid

        db.execute(
            "UPDATE memories SET superseded_by = ? WHERE id = ?",
            (new_id, old_memory_id),
        )
        db.execute(
            "INSERT OR IGNORE INTO relations VALUES (?, ?, 'supersedes')",
            (new_id, old_memory_id),
        )
        # Copy tags from old to new
        db.execute(
            "INSERT OR IGNORE INTO tags (memory_id, tag) SELECT ?, tag FROM tags WHERE memory_id = ?",
            (new_id, old_memory_id),
        )
        db.commit()
        return f"Memory #{old_memory_id} superseded by #{new_id}: {new_content}"
    finally:
        db.close()


@mcp.tool()
def forget(memory_id: int) -> str:
    """Soft-delete a memory by marking it as superseded.

    Args:
        memory_id: ID of the memory to forget.
    """
    db = get_db()
    try:
        existing = db.execute(
            "SELECT content FROM memories WHERE id = ? AND superseded_by IS NULL",
            (memory_id,),
        ).fetchone()
        if not existing:
            return f"Memory #{memory_id} not found or already forgotten."
        db.execute(
            "UPDATE memories SET superseded_by = id WHERE id = ?", (memory_id,)
        )
        db.commit()
        return f"Forgotten memory #{memory_id}: {existing['content']}"
    finally:
        db.close()


@mcp.tool()
def list_memories(
    category: str | None = None,
    project: str | None = None,
    limit: int = 20,
    sort: str = "score",
) -> str:
    """List active memories sorted by score, recency, importance, or access count.

    Args:
        category: Filter by category (optional).
        project: Filter by project name. Also includes global memories (optional).
        limit: Max results (default 20).
        sort: Sort order: 'score' (default), 'recency', 'importance', 'accessed'.
    """
    db = get_db()
    try:
        conditions = ["superseded_by IS NULL"]
        params: list = []
        if category:
            conditions.append("category = ?")
            params.append(category)
        if project:
            conditions.append("(project = ? OR project IS NULL)")
            params.append(project)

        where = " AND ".join(conditions)
        order_map = {
            "score": "importance * confidence * (1.0 + access_count * 0.1) DESC",
            "recency": "created_at DESC",
            "importance": "importance DESC",
            "accessed": "access_count DESC",
        }
        order = order_map.get(sort, order_map["score"])

        rows = db.execute(
            f"SELECT * FROM memories WHERE {where} ORDER BY {order} LIMIT ?",
            params + [limit],
        ).fetchall()

        if not rows:
            return "No memories found."

        results = []
        for r in rows:
            results.append({
                "id": r["id"],
                "content": r["content"],
                "category": r["category"],
                "project": r["project"],
                "importance": r["importance"],
                "confidence": r["confidence"],
                "access_count": r["access_count"],
                "created_at": r["created_at"],
            })
        return json.dumps(results, indent=2)
    finally:
        db.close()


@mcp.tool()
def memory_stats() -> str:
    """Get statistics about the memory store: totals, breakdowns by category and project."""
    db = get_db()
    try:
        stats = {}
        stats["total_active"] = db.execute(
            "SELECT count(*) FROM memories WHERE superseded_by IS NULL"
        ).fetchone()[0]
        stats["total_superseded"] = db.execute(
            "SELECT count(*) FROM memories WHERE superseded_by IS NOT NULL"
        ).fetchone()[0]
        stats["by_category"] = {
            row[0]: row[1]
            for row in db.execute(
                "SELECT category, count(*) FROM memories WHERE superseded_by IS NULL GROUP BY category"
            ).fetchall()
        }
        stats["by_project"] = {
            (row[0] or "global"): row[1]
            for row in db.execute(
                "SELECT project, count(*) FROM memories WHERE superseded_by IS NULL GROUP BY project"
            ).fetchall()
        }
        stats["most_accessed"] = []
        for row in db.execute(
            "SELECT id, content, access_count FROM memories WHERE superseded_by IS NULL ORDER BY access_count DESC LIMIT 5"
        ).fetchall():
            stats["most_accessed"].append({
                "id": row[0], "content": row[1], "access_count": row[2]
            })
        return json.dumps(stats, indent=2)
    finally:
        db.close()


@mcp.tool()
def relate(
    from_id: int,
    to_id: int,
    relation: str = "supports",
) -> str:
    """Create a relationship between two memories.

    Args:
        from_id: Source memory ID.
        to_id: Target memory ID.
        relation: Type: 'contradicts', 'supports', 'refines', 'supersedes'.
    """
    valid_relations = {"contradicts", "supports", "refines", "supersedes"}
    if relation not in valid_relations:
        return f"Invalid relation '{relation}'. Use one of: {', '.join(sorted(valid_relations))}"

    db = get_db()
    try:
        # Verify both exist
        for mid in (from_id, to_id):
            if not db.execute("SELECT 1 FROM memories WHERE id = ?", (mid,)).fetchone():
                return f"Memory #{mid} not found."
        db.execute(
            "INSERT OR IGNORE INTO relations VALUES (?, ?, ?)",
            (from_id, to_id, relation),
        )
        db.commit()
        return f"Linked #{from_id} --{relation}--> #{to_id}"
    finally:
        db.close()


if __name__ == "__main__":
    mcp.run(transport="stdio")
