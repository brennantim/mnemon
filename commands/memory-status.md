---
description: Show memory system status and statistics
---

Show the current state of the Mnemon memory system:

1. Call `mcp__mnemon__memory_stats` to get overall statistics
2. Display:
   - Total active memories and total superseded
   - Breakdown by category
   - Breakdown by project
   - Top 5 most accessed memories
3. Call `mcp__mnemon__list_memories` with limit=10 and sort=score to show the top 10 memories by composite score
4. Note any potential issues (e.g., very large store, many superseded, categories with no entries)
