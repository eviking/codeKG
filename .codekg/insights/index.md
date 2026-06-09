# All Insights — codeKG
_Generated 2026-06-09 20:27 UTC_

Non-obvious facts captured from previous coding sessions.
These are also inlined at the top of each module file.
**Total:** 1 insights

## `services.api.main`

**[system]** _100% confidence_
The `except Exception: pass` audit produced three distinct fix categories, not just one. Silent swallows in infrastructure code (Neo4j, Docker, SQLite, HTTP) need `log.warning(..., exc=e)` so operators see failures. Data-shape fallbacks (JSON decode, file I/O) should narrow to `ValueError` / `OSError`. Plugin/SDK boundaries (classifier rules, gitpython, LLM SDK version shims) should keep broad `except Exception` with an explanatory comment. Two intentional broad excepts remain with documented comments: `api/main.py` snapshot cache miss (fall through to live queries) and `shared/llm.py` Older SDK shim. Every bare except without a log call or narrowing is a debugging black hole in production.
