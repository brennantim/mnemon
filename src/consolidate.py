#!/usr/bin/env python3
"""Mnemon consolidation hook -- background maintenance at SessionEnd.

Performs:
1. Decay: reduces importance of old, never-accessed memories
2. Retirement: soft-deletes memories that decayed below threshold
3. Deduplication: merges exact content duplicates
"""

import sys
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path


def get_db_path(cwd: str) -> Path:
    """Get the database path for the given project directory."""
    return Path(cwd) / ".claude" / "memory" / "mnemon.db"


def consolidate(cwd: str):
    """Run maintenance tasks on the memory store."""
    db_path = get_db_path(cwd)
    if not db_path.exists():
        return

    db = sqlite3.connect(str(db_path))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.row_factory = sqlite3.Row

    now = datetime.now(timezone.utc)
    cutoff_30d = (now - timedelta(days=30)).isoformat()
    cutoff_90d = (now - timedelta(days=90)).isoformat()

    # 1. Decay: reduce importance of 30+ day old memories with zero access
    db.execute("""
        UPDATE memories
        SET importance = importance * 0.9,
            updated_at = ?
        WHERE superseded_by IS NULL
          AND access_count = 0
          AND created_at < ?
          AND importance > 0.1
    """, (now.isoformat(), cutoff_30d))

    # 2. Retire: soft-delete memories below 0.1 importance with no access, 90+ days old
    db.execute("""
        UPDATE memories
        SET superseded_by = -1,
            updated_at = ?
        WHERE superseded_by IS NULL
          AND importance < 0.1
          AND access_count = 0
          AND created_at < ?
    """, (now.isoformat(), cutoff_90d))

    # 3. Dedup: find exact content matches among active memories
    dupes = db.execute("""
        SELECT content, GROUP_CONCAT(id) as ids, COUNT(*) as cnt
        FROM memories
        WHERE superseded_by IS NULL
        GROUP BY LOWER(TRIM(content))
        HAVING cnt > 1
    """).fetchall()

    for dupe in dupes:
        ids = sorted([int(x) for x in dupe["ids"].split(",")])
        # Keep the one with highest (access_count, importance), supersede rest
        rows = db.execute(
            f"SELECT id, access_count, importance FROM memories WHERE id IN ({','.join('?' * len(ids))})",
            ids,
        ).fetchall()
        keeper = max(rows, key=lambda r: (r["access_count"], r["importance"]))
        for row in rows:
            if row["id"] != keeper["id"]:
                db.execute(
                    "UPDATE memories SET superseded_by = ?, updated_at = ? WHERE id = ?",
                    (keeper["id"], now.isoformat(), row["id"]),
                )

    db.commit()
    db.close()


if __name__ == "__main__":
    try:
        hook_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_data = {}
    consolidate(cwd=hook_data.get("cwd", ""))
