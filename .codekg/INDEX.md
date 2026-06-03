# CodeKG Agent Index — codeKG
_Generated 2026-06-03 19:47 UTC · kept current by git commit triggers_

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
- `dependencies.md` — Cross-module dependencies and high blast-radius classes
- `hotspots.md` — High blast-radius, low hygiene classes to approach carefully
- `modules.md` — Module map with class counts and summaries
- `patterns.md` — Detected design patterns and anti-patterns

### insights/
- `index.md` — Index of all captured insights by area
- `services--api.md` — Captured insights for module `services/api`
- `services--console.md` — Captured insights for module `services/console`
- `services--ingestion.md` — Captured insights for module `services/ingestion`
- `services--mcp.md` — Captured insights for module `services/mcp`
- `services--watcher.md` — Captured insights for module `services/watcher`

### modules/
- `services--api.md` — Classes and structure for module `services/api`
- `services--console.md` — Classes and structure for module `services/console`
- `services--ingestion.md` — Classes and structure for module `services/ingestion`
- `services--mcp.md` — Classes and structure for module `services/mcp`
- `services--watcher.md` — Classes and structure for module `services/watcher`

### policies/
- `active.md` — Active architectural policies — read before making changes
- `violations.md` — Current policy violations by class

## Modules in this repo
- `services/api` — services/api
- `services/console` — services/console
- `services/ingestion` — services/ingestion
- `services/mcp` — services/mcp
- `services/watcher` — services/watcher