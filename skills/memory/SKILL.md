---
name: memory
description: Advanced memory operations -- search, browse, maintain, and analyze the persistent memory store
argument-hint: [search query] [--category TYPE] [--project NAME] [--maintain] [--browse]
allowed-tools: mcp__mnemon__remember, mcp__mnemon__recall, mcp__mnemon__correct, mcp__mnemon__forget, mcp__mnemon__list_memories, mcp__mnemon__memory_stats, mcp__mnemon__relate
---

# Memory Management Skill

Advanced operations on the Mnemon persistent memory store.

## Operations

### Search (default)
Search memories with optional filters.
- `/memory deployment process` -- search for deployment-related memories
- `/memory --category preferences` -- list all stored preferences
- `/memory --project my-app` -- show all project-specific knowledge

### Browse (--browse)
List memories sorted by different criteria.
- `/memory --browse` -- top memories by score
- `/memory --browse --sort recency` -- most recent memories
- `/memory --browse --sort accessed` -- most frequently accessed

### Maintain (--maintain)
Run manual maintenance operations.
- `/memory --maintain` -- check for duplicates, show decay candidates, report health

## Implementation

Parse the user's arguments:
- If `--maintain`: call `memory_stats`, then `list_memories` with sort=accessed, identify any issues
- If `--browse`: call `list_memories` with specified sort and filters
- If `--category` or `--project`: call `list_memories` with those filters
- Otherwise: call `recall` with the query text

Display results in a clear, readable format.
