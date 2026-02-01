# mnemon

Persistent memory for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Remembers what matters across sessions.

Mnemon stores knowledge in a local SQLite database, auto-extracts insights from your sessions, surfaces relevant context at startup, and quietly retires stale memories over time. No Docker, no embeddings server, no external services. Just Python and SQLite.

## Features

- **7 MCP tools** for storing, searching, correcting, and relating memories
- **Auto-extraction** pulls knowledge from session transcripts via Claude Haiku (~$0.002/call, opt-in)
- **Auto-surfacing** regenerates a context file at session start with your top-scored memories
- **Auto-maintenance** decays old memories, retires forgotten ones, deduplicates
- **Slash commands** `/remember`, `/forget`, `/memory-status`, `/memory`
- **Project-aware** tags memories by project and surfaces project-specific context
- **Full-text search** via SQLite FTS5 with support for AND, OR, NOT, and phrase queries
- **Memory relations** link memories that support, contradict, refine, or supersede each other

## Install

### Via Plugin Marketplace (recommended)

```bash
claude plugin marketplace add brennantim/mnemon
claude plugin install mnemon@mnemon-marketplace
```

### Local Development

```bash
git clone https://github.com/brennantim/mnemon.git
claude --plugin-dir ./mnemon
```

## Prerequisites

- **Python 3.10+**
- **Claude Code 1.0.33+** (plugin support)
- **fastmcp** Python package (`pip install fastmcp`)
- **anthropic** Python package (`pip install anthropic`) -- only needed for auto-extraction
- **ANTHROPIC_API_KEY** environment variable -- only needed for auto-extraction

Without the API key, the core memory tools still work. You just lose the auto-learning from session transcripts.

## Commands

| Command | What it does |
|---|---|
| `/remember <thing>` | Store knowledge in persistent memory |
| `/forget <thing>` | Search and remove memories |
| `/memory-status` | View stats, breakdowns, and top memories |
| `/memory <query>` | Advanced search with filters |
| `/memory --browse` | Browse memories by score, recency, or access count |
| `/memory --maintain` | Health check for duplicates and decay candidates |

## How It Works

```
Session Start
  |-- surface.py regenerates mnemon-memories.md with top-scored memories
  |
During Session
  |-- 7 MCP tools available: remember, recall, correct, forget,
  |   list_memories, memory_stats, relate
  |-- Claude proactively stores corrections, preferences, and decisions
  |
Session Stop
  |-- extract.py reads last 4000 chars of transcript
  |-- Calls Haiku to identify knowledge worth keeping
  |-- Stores up to 5 items per extraction
  |
Session End
  |-- consolidate.py decays 30+ day old unaccessed memories
  |-- Retires memories below 0.1 importance after 90 days
  |-- Deduplicates exact content matches
```

### Memory Scoring

Each memory has a composite score: `importance * confidence * (1 + access_count * 0.1) * time_decay`

- **importance** (0.0-1.0): How critical this knowledge is
- **confidence** (0.0-1.0): How certain the information is
- **access_count**: How often the memory has been retrieved
- **time_decay**: Gentle exponential decay (0.998^hours)

### Categories

| Category | Typical Importance | Use |
|---|---|---|
| preferences | 0.7-1.0 | How you like things done |
| corrections | 0.8-1.0 | Mistakes to never repeat |
| decisions | 0.5-0.8 | Technical choices with rationale |
| facts | 0.3-0.7 | Info about you, your projects, environment |
| procedures | 0.5-0.8 | Workflows that work |
| project-knowledge | 0.4-0.7 | Project-specific patterns and conventions |
| relationships | 0.3-0.5 | How things connect |

### Storage

All data stays local. The database lives at `.claude/memory/mnemon.db` in your project directory. Nothing is sent anywhere except the Haiku extraction call (which only sends the last 4000 characters of your session transcript, and only if you have `ANTHROPIC_API_KEY` set).

Memories are never truly deleted. "Forgetting" marks a memory as superseded, preserving the audit trail. The consolidation hook retires low-value memories after 90 days of zero access.

## Configuration

### Disable auto-extraction
Unset `ANTHROPIC_API_KEY` or remove the `Stop` and `PreCompact` hooks.

### Adjust decay rates
Edit `src/consolidate.py`:
- Decay multiplier (default 0.9 per cycle for 30+ day old memories)
- Retirement threshold (default 0.1 importance, 90+ days, zero access)

### Adjust surfacing
Edit `src/surface.py`:
- `MAX_LINES` controls the size of the generated rules file (default 120)
- Section limits control how many memories per category are surfaced

## Uninstall

```bash
claude plugin uninstall mnemon@mnemon-marketplace
```

Your memory database (`.claude/memory/mnemon.db`) is preserved. Delete it manually if you want to remove all stored memories.

## License

MIT
