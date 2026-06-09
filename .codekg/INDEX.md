# CodeKG Agent Index — codeKG
_Generated 2026-06-09 20:27 UTC · commit `83750ea` · kept current by git commit triggers_

## ⚠ STOP — read this before doing anything

Do **NOT** use `find`, `ls`, `grep`, or open source files to understand this codebase.
The files in `.codekg/` contain complete, pre-computed intelligence — use them instead.
They include every class, every method with full parameter and return type signatures,
blast radius, hygiene grades, architectural rules, and session insights.

**Required reading before writing any code:**
1. `.codekg/policies/active.md` — rules you must not violate
2. `.codekg/modules/<name>.md` — every class and method for the module you're working in
3. `.codekg/architecture/hotspots.md` — before touching any high-blast-radius class
4. `.codekg/insights/index.md` — non-obvious facts from previous sessions

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
| Architectural rules | `.codekg/policies/active.md` |
| Current violations | `.codekg/policies/violations.md` |
| Session insights | `.codekg/insights/index.md` |
| Recent commits & index changes | `.codekg/architecture/recent_changes.md` |
| Classes & methods in a module | `.codekg/modules/<name>.md` |

## Available files

### root/
- `AGENTS.md` ⚠ stale — Snippet to paste into repo root AGENTS.md (Codex / OpenAI Codex agents) · updated 2026-06-09 20:27 UTC
- `CLAUDE.md` ⚠ stale — Snippet to paste into repo root CLAUDE.md · updated 2026-06-09 20:27 UTC
- `INDEX.md` — Master navigation file — read first · updated 2026-06-08 18:37 UTC

### architecture/
- `datastores.md` ⚠ stale — All data stores (Neo4j, SQLite DBs) — schemas and which modules use them · updated 2026-06-09 20:27 UTC
- `dependencies.md` ⚠ stale — Cross-module dependencies and high blast-radius classes · updated 2026-06-09 20:27 UTC
- `hotspots.md` ⚠ stale — High blast-radius, low hygiene classes to approach carefully · updated 2026-06-09 20:27 UTC
- `modules.md` ⚠ stale — Module map with class counts and summaries · updated 2026-06-09 20:27 UTC
- `patterns.md` ⚠ stale — Detected design patterns and anti-patterns · updated 2026-06-09 20:27 UTC
- `recent_changes.md` ⚠ stale — Recent git commits and index file changes — read to understand what changed · updated 2026-06-09 20:27 UTC
- `screens.md` ⚠ stale — All pages/screens — URL, template, nav links, API calls, data access · updated 2026-06-09 20:27 UTC

### insights/
- `index.md` ⚠ stale — Index of all captured insights by area · updated 2026-06-09 20:27 UTC

### modules/
- `combined.md` ⚠ stale — All modules inlined — used when total repo LOC < 2,500 · updated 2026-06-09 20:27 UTC
- `services--api.md` ⚠ stale — Classes and structure for module `services/api` · updated 2026-06-09 20:27 UTC
- `services--console.md` ⚠ stale — Classes and structure for module `services/console` · updated 2026-06-09 20:27 UTC
- `services--ingestion.md` ⚠ stale — Classes and structure for module `services/ingestion` · updated 2026-06-09 20:27 UTC
- `services--mcp.md` ⚠ stale — Classes and structure for module `services/mcp` · updated 2026-06-09 20:27 UTC
- `services--watcher.md` ⚠ stale — Classes and structure for module `services/watcher` · updated 2026-06-09 20:27 UTC

### policies/
- `active.md` ⚠ stale — Active architectural policies — read before making changes · updated 2026-06-09 20:27 UTC
- `violations.md` ⚠ stale — Current policy violations by class · updated 2026-06-09 20:27 UTC

## Modules in this repo
- `services/api` — services/api
- `services/console` — services/console
- `services/ingestion` — services/ingestion
- `services/mcp` — services/mcp
- `services/watcher` — services/watcher

## Recent changes

**Index files updated this cycle:**
- `agents_md` — regenerated 2026-06-09 20:27 UTC
- `architecture/datastores` — regenerated 2026-06-09 20:27 UTC
- `architecture/dependencies` — regenerated 2026-06-09 20:27 UTC
- `architecture/hotspots` — regenerated 2026-06-09 20:27 UTC
- `architecture/modules` — regenerated 2026-06-09 20:27 UTC
- `architecture/patterns` — regenerated 2026-06-09 20:27 UTC
- `architecture/recent_changes` — regenerated 2026-06-09 20:27 UTC
- `architecture/screens` — regenerated 2026-06-09 20:27 UTC
- `claude_md` — regenerated 2026-06-09 20:27 UTC
- `insights/index` — regenerated 2026-06-09 20:27 UTC
- `modules/combined` — regenerated 2026-06-09 20:27 UTC
- `modules/services/api` — regenerated 2026-06-09 20:27 UTC
- `modules/services/console` — regenerated 2026-06-09 20:27 UTC
- `modules/services/ingestion` — regenerated 2026-06-09 20:27 UTC
- `modules/services/mcp` — regenerated 2026-06-09 20:27 UTC
- `modules/services/watcher` — regenerated 2026-06-09 20:27 UTC
- `policies/active` — regenerated 2026-06-09 20:27 UTC
- `policies/violations` — regenerated 2026-06-09 20:27 UTC

**Recent repo commits:**
- `3198875f` 2026-06-09 Jens Schutt — docs: fix MCP transport references — SSE is the default, not stdio
- `7f0247d7` 2026-06-09 Jens Schutt — docs: update README and onboarding to reflect Get Started wizard
- `2f4f9cb1` 2026-06-09 Jens Schutt — feat: full production C++ language support
- `caf4a15f` 2026-06-09 Jens Schutt — chore: track require_telemetry.py stop hook
- `16c16b73` 2026-06-09 Jens Schutt — fix: remove redundant step 6D from wizard
- `b2fca8a4` 2026-06-09 Jens Schutt — feat: wizard improvements — Ollama detection, SSE MCP, memory setup
- `1b512802` 2026-06-09 Jens Schutt — feat: add Get Started wizard for first-time users
- `349182f5` 2026-06-08 Jens Schutt — docs: add console screenshots to README
- `4458de70` 2026-06-08 Jens Schutt — SS for docs
- `6c102f05` 2026-06-08 Jens Schutt — chore: remove internal open-source release checklist from public repo
- `8f72c638` 2026-06-08 Jens Schutt — fix: resolve all ruff lint errors so CI passes
- `09a6aaad` 2026-06-08 Jens Schutt — fix: rename shared/logging → shared/codekg_logging to avoid stdlib shadow
- `1114a3af` 2026-06-08 Jens Schutt — docs: rewrite README for external audience
- `53fc30d6` 2026-06-08 Jens Schutt — test
- `b3a69148` 2026-06-08 Jens Schutt — chore: open-source release prep
