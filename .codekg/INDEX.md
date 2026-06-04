# CodeKG Agent Index — codeKG
_Generated 2026-06-04 16:25 UTC · kept current by git commit triggers_

## How to use this index
These files are **always current** — regenerated automatically on every git commit.
Treat them as the primary source of truth for this codebase.
Read the files relevant to your task **before writing any code**.

**Before starting any task, read:**
1. `policies/active.md` — rules you must not violate
2. The relevant `modules/<name>.md` — classes, structure, key entry points
3. `architecture/hotspots.md` — if you plan to touch high-blast-radius classes
4. `insights/<name>.md` — non-obvious facts from previous sessions in this area

**Only call CodeKG MCP tools directly for:**
- Live impact analysis on files you just changed (`get_change_impact`)
- Full method-level class detail not in the module file (`get_class`)
- Searching for a class when you don't know its module (`search_classes`)
- Submitting session telemetry at the end of your task

| When you need to... | Read |
|---|---|
| Understand the repo structure | `architecture/modules.md` |
| Find key dependencies | `architecture/dependencies.md` |
| Check design patterns | `architecture/patterns.md` |
| Identify risky classes before changing | `architecture/hotspots.md` |
| Know the rules before making changes | `policies/active.md` |
| Check current violations | `policies/violations.md` |
| Work on a specific module | `modules/<name>.md` |
| Get non-obvious facts about a module | `insights/<name>.md` |

## Available files

### root/
- `CLAUDE.md` — Snippet to paste into repo root CLAUDE.md
- `INDEX.md` — Master navigation file — read first

### architecture/
- `dependencies.md` ⚠ stale — Cross-module dependencies and high blast-radius classes
- `hotspots.md` ⚠ stale — High blast-radius, low hygiene classes to approach carefully
- `modules.md` ⚠ stale — Module map with class counts and summaries
- `patterns.md` ⚠ stale — Detected design patterns and anti-patterns
- `schema.md` ⚠ stale — Neo4j graph schema — node labels, properties, relationships, query patterns

### insights/
- `index.md` ⚠ stale — Index of all captured insights by area
- `services--api.md` ⚠ stale — Captured insights for module `services/api`
- `services--console.md` ⚠ stale — Captured insights for module `services/console`
- `services--ingestion.md` ⚠ stale — Captured insights for module `services/ingestion`
- `services--mcp.md` ⚠ stale — Captured insights for module `services/mcp`

### modules/
- `combined.md` ⚠ stale — All modules inlined — used when total repo LOC < 2,500
- `services--api.md` ⚠ stale — Classes and structure for module `services/api`
- `services--console.md` ⚠ stale — Classes and structure for module `services/console`
- `services--ingestion.md` ⚠ stale — Classes and structure for module `services/ingestion`
- `services--mcp.md` ⚠ stale — Classes and structure for module `services/mcp`
- `services--watcher.md` ⚠ stale — Classes and structure for module `services/watcher`

## Modules in this repo
- `services/api` — services/api
- `services/console` — services/console
- `services/ingestion` — services/ingestion
- `services/mcp` — services/mcp
- `services/watcher` — services/watcher