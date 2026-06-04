# CodeKG Agent Index — codeKG
_Generated 2026-06-04 20:39 UTC · kept current by git commit triggers_

## ⚠ STOP — read this before doing anything

Do **NOT** use `find`, `ls`, `grep`, or open source files to understand this codebase.
The files in `.codekg/` contain complete, pre-computed intelligence — use them instead.
They include every class, every method with full parameter and return type signatures,
blast radius, hygiene grades, architectural rules, and session insights.

**Required reading before writing any code:**
1. `.codekg/modules/<name>.md` — every class and method for the module you're working in
2. `.codekg/architecture/hotspots.md` — before touching any high-blast-radius class
3. `.codekg/insights/index.md` — non-obvious facts from previous sessions

**Only call CodeKG MCP tools directly for:**
- Live impact analysis on files you just changed (`get_change_impact`)
- Searching for a class when you don't know its module (`search_classes`)
- Submitting session telemetry (`capture_insight`) — always do this at the end

| When you need to... | Read this file |
|---|---|
| Understand repo structure | `.codekg/architecture/modules.md` |
| Cross-module dependencies | `.codekg/architecture/dependencies.md` |
| Data stores & schemas | `.codekg/architecture/datastores.md` |
| Pages/screens, routes, nav links | `.codekg/architecture/screens.md` |
| Design patterns in use | `.codekg/architecture/patterns.md` |
| Identify risky classes | `.codekg/architecture/hotspots.md` |
| Session insights | `.codekg/insights/index.md` |
| Classes & methods in a module | `.codekg/modules/<name>.md` |

## Available files

### root/
- `CLAUDE.md` ⚠ stale — Snippet to paste into repo root CLAUDE.md
- `INDEX.md` ⚠ stale — Master navigation file — read first

### architecture/
- `datastores.md` ⚠ stale — All data stores (Neo4j, SQLite DBs) — schemas and which modules use them
- `dependencies.md` ⚠ stale — Cross-module dependencies and high blast-radius classes
- `hotspots.md` ⚠ stale — High blast-radius, low hygiene classes to approach carefully
- `modules.md` ⚠ stale — Module map with class counts and summaries
- `patterns.md` ⚠ stale — Detected design patterns and anti-patterns
- `screens.md` ⚠ stale — All pages/screens — URL, template, nav links, API calls, data access

### insights/
- `index.md` ⚠ stale — Index of all captured insights by area

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