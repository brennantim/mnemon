# Changelog

## 0.1.0 (2026-02-01)

Initial release.

- MCP server with 7 tools: remember, recall, correct, forget, list_memories, memory_stats, relate
- SQLite + FTS5 full-text search
- Auto-extraction from session transcripts via Claude Haiku
- Auto-surfacing of top memories at session start
- Auto-consolidation: decay, retirement, deduplication
- Slash commands: /remember, /forget, /memory-status, /memory
- Memory scoring: importance * confidence * frequency * time_decay
- Memory relations: supports, contradicts, refines, supersedes
- Project-aware memory tagging and surfacing
- Claude Code plugin packaging with marketplace support
