# CodeKG Agent Index — codeKG
_Generated 2026-06-05 20:34 UTC · commit `5185bf1` · kept current by git commit triggers_

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
| Recent commits & index changes | `.codekg/architecture/recent_changes.md` |
| Classes & methods in a module | `.codekg/modules/<name>.md` |

## Available files

### root/
- `CLAUDE.md` — Snippet to paste into repo root CLAUDE.md · updated 2026-06-05 20:34 UTC
- `INDEX.md` — Master navigation file — read first · updated 2026-06-05 20:16 UTC

### architecture/
- `datastores.md` ⚠ stale — All data stores (Neo4j, SQLite DBs) — schemas and which modules use them · updated 2026-06-05 20:34 UTC
- `dependencies.md` ⚠ stale — Cross-module dependencies and high blast-radius classes · updated 2026-06-05 20:34 UTC
- `hotspots.md` ⚠ stale — High blast-radius, low hygiene classes to approach carefully · updated 2026-06-05 20:34 UTC
- `modules.md` ⚠ stale — Module map with class counts and summaries · updated 2026-06-05 20:34 UTC
- `patterns.md` ⚠ stale — Detected design patterns and anti-patterns · updated 2026-06-05 20:34 UTC
- `recent_changes.md` ⚠ stale — Recent git commits and index file changes — read to understand what changed · updated 2026-06-05 20:34 UTC
- `screens.md` ⚠ stale — All pages/screens — URL, template, nav links, API calls, data access · updated 2026-06-05 20:34 UTC

### insights/
- `index.md` ⚠ stale — Index of all captured insights by area · updated 2026-06-05 20:34 UTC

### modules/
- `combined.md` ⚠ stale — All modules inlined — used when total repo LOC < 2,500 · updated 2026-06-05 20:34 UTC
- `services--api.md` ⚠ stale — Classes and structure for module `services/api` · updated 2026-06-05 20:34 UTC
- `services--console.md` ⚠ stale — Classes and structure for module `services/console` · updated 2026-06-05 20:34 UTC
- `services--ingestion.md` ⚠ stale — Classes and structure for module `services/ingestion` · updated 2026-06-05 20:34 UTC
- `services--mcp.md` ⚠ stale — Classes and structure for module `services/mcp` · updated 2026-06-05 20:34 UTC
- `services--watcher.md` ⚠ stale — Classes and structure for module `services/watcher` · updated 2026-06-05 20:34 UTC

## Modules in this repo
- `services/api` — services/api
- `services/console` — services/console
- `services/ingestion` — services/ingestion
- `services/mcp` — services/mcp
- `services/watcher` — services/watcher

## Recent changes

**Index files updated this cycle:**
- `architecture/datastores` — regenerated 2026-06-05 20:34 UTC
- `architecture/dependencies` — regenerated 2026-06-05 20:34 UTC
- `architecture/hotspots` — regenerated 2026-06-05 20:34 UTC
- `architecture/modules` — regenerated 2026-06-05 20:34 UTC
- `architecture/patterns` — regenerated 2026-06-05 20:34 UTC
- `architecture/recent_changes` — regenerated 2026-06-05 20:34 UTC
- `architecture/screens` — regenerated 2026-06-05 20:34 UTC
- `claude_md` — regenerated 2026-06-05 20:34 UTC
- `insights/index` — regenerated 2026-06-05 20:34 UTC
- `modules/combined` — regenerated 2026-06-05 20:34 UTC
- `modules/services/api` — regenerated 2026-06-05 20:34 UTC
- `modules/services/console` — regenerated 2026-06-05 20:34 UTC
- `modules/services/ingestion` — regenerated 2026-06-05 20:34 UTC
- `modules/services/mcp` — regenerated 2026-06-05 20:34 UTC
- `modules/services/watcher` — regenerated 2026-06-05 20:34 UTC

**Recent repo commits:**
- `fe6d6519` 2026-06-05 CodeKG — chore: update CodeKG agent index [skip ci]
- `5185bf17` 2026-06-05 CodeKG — chore: update CodeKG agent index [skip ci]
- `50dee651` 2026-06-05 CodeKG — chore: update CodeKG agent index [skip ci]
- `0e944219` 2026-06-04 CodeKG — chore: update CodeKG agent index [skip ci]
- `cef3b0bb` 2026-06-04 CodeKG — chore: update CodeKG agent index [skip ci]
- `53839ca8` 2026-06-04 CodeKG — chore: update CodeKG agent index [skip ci]
- `ddb10dc9` 2026-06-04 CodeKG — chore: update CodeKG agent index [skip ci]
- `653c077a` 2026-06-04 CodeKG — chore: update CodeKG agent index [skip ci]
- `de0417d0` 2026-06-04 CodeKG — chore: update CodeKG agent index [skip ci]
- `2a7fac46` 2026-06-04 CodeKG — chore: update CodeKG agent index [skip ci]
- `d5ec98d8` 2026-06-04 CodeKG — chore: update CodeKG agent index [skip ci]
- `85a8c7b5` 2026-06-04 CodeKG — chore: update CodeKG agent index [skip ci]
- `72ff715b` 2026-06-04 CodeKG — chore: update CodeKG agent index [skip ci]
- `ffba8b54` 2026-06-04 CodeKG — chore: update CodeKG agent index [skip ci]
- `3519c2b3` 2026-06-04 CodeKG — chore: update CodeKG agent index [skip ci]
