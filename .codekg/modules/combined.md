# Full Codebase Index — codeKG
_Generated 2026-06-09 20:27 UTC · all modules inlined (repo LOC below 2500 threshold)_

This file contains complete class and method detail for every module.
No additional file reads needed — everything is here.

# Module: services/api
_Generated 2026-06-09 20:27 UTC · commit `unpublished`_

**Path:** `/host-home/Documents/projects/codeKG/services/api`  **Classes:** 41

## Data stores

_Detected from source file imports and connection patterns:_

- **agent_index.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `agent_index/generator.py`
  - `agent_index/store.py`
  - `tests/test_agent_index_generator.py`
  - `tests/test_agent_index_store.py`
- **llm_audit.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `agent_index/generator.py`
  - `llm_audit.py`
  - `nl_query.py`
  - `tests/test_llm_audit.py`
- **mcp_audit.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `agent_index/generator.py`
- **Neo4j** (graph) — see `.codekg/architecture/datastores.md` for schema
  - `agent_index/generator.py`
  - `impact/engine.py`
  - `main.py`
  - `nl_query.py`
  - `renderers/template_renderer.py`
  - `tests/test_api.py`
- **scan_log.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `agent_index/generator.py`
- **telemetry.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `agent_index/generator.py`
  - `main.py`

## ⚡ Insights from previous sessions

_Non-obvious facts from engineering sessions — treat as expert hints._

- **services.api.main** (100%): The `except Exception: pass` audit produced three distinct fix categories, not just one. Silent swallows in infrastructure code (Neo4j, Docker, SQLite, HTTP) need `log.warning(..., exc=e)` so operators see failures. Data-shape fallbacks (JSON decode, file I/O) should narrow to `ValueError` / `OSError`. Plugin/SDK boundaries (classifier rules, gitpython, LLM SDK version shims) should keep broad `except Exception` with an explanatory comment. Two intentional broad excepts remain with documented comments: `api/main.py` snapshot cache miss (fall through to live queries) and `shared/llm.py` Older SDK shim. Every bare except without a log call or narrowing is a debugging black hole in production.
- **services.api.agent_index.generator** (100%): CLAUDE.md and AGENTS.md are written by separate file_key entries (`claude_md` and `agents_md`) that generate different content — they are NOT the same generator output. `claude_md` injects MCP tool references (`capture_insight`, `get_change_impact`), while `agents_md` uses shell commands (`cat .codekg/INDEX.md`) because Codex has no MCP support. The publish dispatch in `api/main.py` checks `f["file_key"] in ("claude_md", "agents_md")` and routes each to its own target file independently:
```python
target_name = "CLAUDE.md" if f["file_key"] == "claude_md" else "AGENTS.md"
root_file = Path(repo_path) / target_name
```
Always add both file_keys to `_INDEX_FILES` when you want both — writing one function and mapping it to both names produces wrong content in at least one file.
- **services.api.main** (100%): The telemetry DB stores tool_calls with input_json (serialised tool input) and step_tokens (per-inference-step cost). Rows before the input_json column was added have NULL there — the question text for those CodeKG calls is permanently unrecoverable, which limits query plan reconstruction quality for old sessions.
- **services.api.main** (100%): The KG stores start_line and end_line per Class node, not LOC per file. File LOC must be derived as max(end_line) across all Class nodes with that file_path. This only covers .py files with at least one indexed class — HTML templates and non-Python files are absent from the KG and need disk-size fallback.
- **services.api.agent_index.generator** (100%): Module index files grew from ~40 lines (class table only) to 230-300 lines per module by pulling full method signatures, parameter types, return types, and LOC from object_model on each Class node. The object_model JSON blob contains a 'methods' array with name, return_type, parameters, and modifiers — this is richer than the separate Method nodes which lack a 'signature' property.
- **services.api.main** (100%): The agent index publish is a two-step process: POST /agent-index/regen writes to SQLite store, then POST /agent-index/publish writes from store to disk and commits to git. Calling only regen leaves disk files stale. The publish endpoint returns 'files_written' (not 'written'), and returns 0 if the store has no visible files for that repo_id.
- **services.api.agent_index.generator** (100%): When total repo LOC (sum of max end_line per file) is below 2500, the generator produces a combined.md with all modules inlined and CLAUDE.md directs agents to read only that one file. Above the threshold, separate per-module files are used. codeKG itself is at 7236 LOC so uses per-module mode.
- **services.api.agent_index.generator** (100%): The insight query in generate_insights_module used CONTAINS $module_id where module_id is 'services/console' (slash-separated) but TribalKnowledge.applies_to stores dot-separated FQNs like 'services.console.main'. The fix is to also match against module_id.replace('/', '.') as module_dot. Both forms must be passed as separate Cypher parameters.
- **services.api.main** (100%): _content_is_empty scans the full body for sentinel phrases like 'not found'. This causes false positives when actual insight text contains those words (e.g. 'FastAPI route registration... path-parameter catch-all... not found'). Fix: only scan the first 200 chars of body, where empty-file sentinels always appear.
- **services.api.agent_index.generator** (100%): The cross-module dependency query required BOTH source and target classes to belong to a Module node. Since shared/logging/codekg_logger.py is outside all modules, all imports resolved to zero rows. Fix: use OPTIONAL MATCH for the target module and fall back to the filename for display.

## Classes

### `ApiTokenMiddleware` — class
**File:** `services/api/main.py`  **LOC:** 12  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.main.ApiTokenMiddleware`

Enforce bearer-token authentication when API_TOKEN is configured. /health is always permitted.

### `ImpactEngine` — class
**File:** `services/api/impact/engine.py`  **LOC:** 254  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.impact.engine.ImpactEngine`

All graph traversals are done in Cypher — purely deterministic, no LLM. Max traversal depth is bounded to prevent runaway queries on large graphs.

### `ImpactReport` — class
**File:** `services/api/impact/engine.py`  **LOC:** 41  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.impact.engine.ImpactReport`

Aggregates the full deterministic blast-radius report for a change. Watch out for the summary totals here, because several endpoints serialize this object directly for UI and MCP clients.

### `ImpactedEndpoint` — class
**File:** `services/api/impact/engine.py`  **LOC:** 9  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.impact.engine.ImpactedEndpoint`

Describes an API endpoint exposed by impacted code. Watch out for handler metadata here, because UI and MCP callers use it to connect HTTP surface area back to classes and methods.

### `ImpactedNode` — class
**File:** `services/api/impact/engine.py`  **LOC:** 10  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.impact.engine.ImpactedNode`

Describes a graph node pulled into an impact-analysis result. Watch out for `hop_distance` and `reason`, because downstream ranking and explanations depend on both fields staying meaningful.

### `ImpactedPolicy` — class
**File:** `services/api/impact/engine.py`  **LOC:** 7  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.impact.engine.ImpactedPolicy`

Captures a policy that becomes relevant to a change set. Watch out for `is_violated`, because callers use it to separate general blast radius from already-known architectural debt.

### `RequestLogMiddleware` — class
**File:** `services/api/main.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.main.RequestLogMiddleware`

Logs API requests with latency and status details. Watch out for noisy paths here, because this middleware runs on every request except the health check.

### `SuggestedTest` — class
**File:** `services/api/impact/engine.py`  **LOC:** 6  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.impact.engine.SuggestedTest`

Represents a test that probably covers impacted code. Watch out for the human-readable `reason`, because suggestions are heuristic and need enough context to be trusted.

### `TestAggregateStats` — class
**File:** `services/api/tests/test_llm_audit.py`  **LOC:** 23  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_llm_audit.TestAggregateStats`

Exercises aggregate stats behavior in the llm audit test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestClassContext` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 51  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestClassContext`

Exercises class context behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestComputeCost` — class
**File:** `services/api/tests/test_llm_audit.py`  **LOC:** 14  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_llm_audit.TestComputeCost`

Exercises compute cost behavior in the llm audit test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestDetectLanguage` — class
**File:** `services/api/tests/test_template_renderer.py`  **LOC:** 23  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_template_renderer.TestDetectLanguage`

Exercises detect language behavior in the template renderer test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestFeatureContext` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 15  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestFeatureContext`

Exercises feature context behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestGenerateIndex` — class
**File:** `services/api/tests/test_agent_index_generator.py`  **LOC:** 39  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_agent_index_generator.TestGenerateIndex`

Exercises generate index behavior in the agent index generator test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestGetFile` — class
**File:** `services/api/tests/test_agent_index_store.py`  **LOC:** 19  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_agent_index_store.TestGetFile`

Exercises get file behavior in the agent index store test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestImpactFiles` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 46  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestImpactFiles`

Exercises impact files behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestInitDb` — class
**File:** `services/api/tests/test_agent_index_store.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_agent_index_store.TestInitDb`

Exercises init database behavior in the agent index store test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestListFiles` — class
**File:** `services/api/tests/test_agent_index_store.py`  **LOC:** 16  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_agent_index_store.TestListFiles`

Exercises list files behavior in the agent index store test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestLogCallContext` — class
**File:** `services/api/tests/test_llm_audit.py`  **LOC:** 44  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_llm_audit.TestLogCallContext`

Exercises log call context behavior in the llm audit test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestLogCallSimple` — class
**File:** `services/api/tests/test_llm_audit.py`  **LOC:** 18  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_llm_audit.TestLogCallSimple`

Exercises log call simple behavior in the llm audit test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestMarkPublished` — class
**File:** `services/api/tests/test_agent_index_store.py`  **LOC:** 23  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_agent_index_store.TestMarkPublished`

Exercises mark published behavior in the agent index store test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestModuleContext` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 27  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestModuleContext`

Exercises module context behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestPatterns` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 32  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestPatterns`

Exercises patterns behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestPolicies` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 26  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestPolicies`

Exercises policies behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestProvenance` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 20  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestProvenance`

Exercises provenance behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestRenderClass` — class
**File:** `services/api/tests/test_agent_index_generator.py`  **LOC:** 66  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_agent_index_generator.TestRenderClass`

Exercises render class behavior in the agent index generator test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestRenderTemplate` — class
**File:** `services/api/tests/test_template_renderer.py`  **LOC:** 23  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_template_renderer.TestRenderTemplate`

Exercises render template behavior in the template renderer test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestRepos` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 30  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestRepos`

Exercises repos behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestSearchClass` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 35  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestSearchClass`

Exercises search class behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestShortenFp` — class
**File:** `services/api/tests/test_agent_index_generator.py`  **LOC:** 41  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_agent_index_generator.TestShortenFp`

Exercises shorten file-path behavior in the agent index generator test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestTemplate` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestTemplate`

Exercises template behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestToggleHidden` — class
**File:** `services/api/tests/test_agent_index_store.py`  **LOC:** 22  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_agent_index_store.TestToggleHidden`

Exercises toggle hidden behavior in the agent index store test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestUpdateManualAdditions` — class
**File:** `services/api/tests/test_agent_index_store.py`  **LOC:** 18  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_agent_index_store.TestUpdateManualAdditions`

Exercises update manual additions behavior in the agent index store test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestUpsertFile` — class
**File:** `services/api/tests/test_agent_index_store.py`  **LOC:** 58  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_agent_index_store.TestUpsertFile`

Exercises upsert file behavior in the agent index store test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestValidateTable` — class
**File:** `services/api/tests/test_agent_index_store.py`  **LOC:** 29  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_agent_index_store.TestValidateTable`

Exercises validate table behavior in the agent index store test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestViolations` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 28  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestViolations`

Exercises violations behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `_AnswerRequest` — class
**File:** `services/api/main.py`  **LOC:** 4  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.main._AnswerRequest`

Validates the payload for natural-language answer generation. Watch out for optional repo scoping here, because the same endpoint supports both global and repository-specific questions.

### `_DefaultZero` — class
**File:** `services/api/agent_index/generator.py`  **LOC:** 3  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.agent_index.generator._DefaultZero`

Dictionary that falls back to zero for missing counters. Watch out for silent key creation here, because summary math relies on absent buckets behaving like empty counts.

### `_Entry` — class
**File:** `services/api/llm_audit.py`  **LOC:** 56  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.llm_audit._Entry`

Represents one stored LLM audit event. Watch out for field naming here, because audit pages and API responses read these entries back verbatim.

### `_PublishRequest` — class
**File:** `services/api/main.py`  **LOC:** 3  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.main._PublishRequest`

Validates requests that publish reviewed agent-index content. Watch out for versioning assumptions here, because publishing mutates state that other services may already be reading.

### `_RegenRequest` — class
**File:** `services/api/main.py`  **LOC:** 4  **Grade:** ?  **Blast:** 0
**FQN:** `services.api.main._RegenRequest`

Validates requests to regenerate derived content. Watch out for identifier fields here, because regeneration targets existing stored artifacts rather than raw source files.

---

# Module: services/console
_Generated 2026-06-09 20:27 UTC · commit `unpublished`_

**Path:** `/host-home/Documents/projects/codeKG/services/console`  **Classes:** 34

## Data stores

_Detected from source file imports and connection patterns:_

- **agent_index.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `agent_index/store.py`
  - `tests/test_config_routes.py`
- **llm_audit.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `llm_audit.py`
  - `nl_query.py`
  - `routes/audit_log.py`
  - `routes/system_health.py`
- **mcp_audit.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `main.py`
  - `routes/mcp_audit.py`
- **Neo4j** (graph) — see `.codekg/architecture/datastores.md` for schema
  - `deps.py`
  - `nl_query.py`
  - `pattern_detector.py`
  - `routes/system_health.py`
  - `tests/test_config_routes.py`
  - `tests/test_console.py`
- **scan_log.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `routes/system_health.py`
  - `scan_launcher.py`
  - `tests/test_scan_launcher.py`

## Routes

_FastAPI route handlers in this module — what each renders, its template, and template context._

| Method | URL | Template | Parameters | Template context |
|--------|-----|----------|------------|-----------------|
| `GET` | `/` | `dashboard.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `repo_stats`, `gc`, `recent_events`, `token_savings`, `tk_total`, `tk_by_repo` |
| `GET` | `/agent-index` | `agent_index_overview.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `files`, `standard_grouped`, `module_files`, `modules`, `has_files` |
| `GET` | `/agent-index/file/{file_key:path}` | `agent_index_file.html` | `file_key: str` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `file`, `file_key`, `content_html` |
| `GET` | `/ask` | `ask.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `result` |
| `POST` | `/ask` | `ask.html` | `question: str` = `Form(...` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `question`, `repo_id`, `result` |
| `GET` | `/audit` | `audit.html` | `source: str` = `""`, `limit: int` = `200`, `hours: int` = `24` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `calls`, `stats`, `source_filter`, `limit`, `hours` |
| `GET` | `/auth/callback` | `—` | `code: str` = `""`, `state: str` = `""`, `error: str` = `""` | — |
| `GET` | `/classes` | `classes.html` | `q: str` = `""`, `role: str` = `""`, `repo_id: str` = `""`, `sort: str` = `"coupling"`, `has_summary: str` = `"false"`, `page: int` = `1` | `effective_repo (via _template_ctx)`, `current_path (via _template_ctx)`, `classes`, `total`, `page`, `pages`, `page_size`, `q`, `role`, `repo_id`, `sort`, `has_summary`, `summary_total`, `class_total`, `roles`, `repos` |
| `POST` | `/classes/summarise` | `—` | `repo_id: str` = `Form(...` | — |
| `GET` | `/classes/summarise/{job_id}` | `summarise_progress.html` | `job_id: str` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `job_id`, `status`, `done`, `total`, `log` |
| `GET` | `/classes/{fqn:path}` | `class_detail.html` | `fqn: str` | — |
| `GET` | `/config` | `config.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `sections`, `env_file_exists`, `env_file_path` |
| `GET` | `/getstarted` | `getstarted.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)` |
| `GET` | `/hygiene` | `hygiene_overview.html` | — | `effective_repo (via _template_ctx)`, `current_path (via _template_ctx)`, `repos` |
| `GET` | `/hygiene/{repo_id:path}` | `hygiene_detail.html` | `repo_id: str` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `repo_id`, `repo_score`, `classes`, `stats` |
| `GET` | `/hygiene/{repo_id}/refactor` | `hygiene_refactor.html` | `repo_id: str` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `repo_id`, `classes`, `module_index_path` |
| `GET` | `/insights` | `insights.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `sections`, `total`, `include_hidden`, `q`, `sort`, `pending_count` |
| `GET` | `/mcp-audit` | `mcp_audit.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)` |
| `GET` | `/modules` | `modules.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `modules`, `module_tree`, `edges` |
| `GET` | `/modules/{module_id:path}` | `module_detail.html` | `module_id: str` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `mod`, `module_id`, `stat` |
| `GET` | `/pattern-catalog` | `pattern_catalog.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `patterns`, `patterns_json` |
| `GET` | `/patterns` | `patterns.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `repo_id`, `results` |
| `POST` | `/patterns` | `patterns.html` | `repo_id: str` = `Form(""` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `repo_id`, `results` |
| `GET` | `/policies` | `policies.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `policies`, `modules` |
| `GET` | `/policies/{policy_id}` | `policy_detail.html` | `policy_id: str` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `policy`, `violations`, `violations_run`, `run_error`, `run_error_msg`, `recompiled`, `has_valid_cypher`, `saved` |
| `GET` | `/repos` | `repos.html` | — | `effective_repo (via _template_ctx)`, `current_path (via _template_ctx)`, `repos`, `repos_path` |
| `GET` | `/repos/{repo_id:path}` | `repo_detail.html` | `repo_id: str` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `repo_id`, `repo_path`, `git`, `kg`, `provenance`, `stats`, `in_registry`, `scanning`, `api_url` |
| `GET` | `/system-health` | `system_health.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)` |
| `GET` | `/telemetry` | `telemetry.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `sessions` |
| `GET` | `/telemetry/{session_id}` | `telemetry_detail.html` | `session_id: str` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `detail` |

## ⚡ Insights from previous sessions

_Non-obvious facts from engineering sessions — treat as expert hints._

- **services.console.routes.classes** (100%): FastAPI route registration order is critical when a path-parameter catch-all exists. GET /classes/{fqn:path} greedily matches everything under /classes/. More-specific routes like /classes/summarise/{job_id} MUST be registered before the catch-all or they are swallowed. Symptom: 404 with body: Class summarise/<id> not found.
- **services.console.routes.classes.start_summarise** (100%): summarise_classes.py skips TEST and GENERATED role classes by default (_SKIP_ROLES). For large repos like ElasticSearch this is ~16k classes. If resume=True and all remaining unsummarised classes are TEST/GENERATED, the job exits with 0 written — looks like failure but is correct. The console shows a Nothing to summarise warning. Use include_skip_roles=True or force=True to override.
- **services.console.routes.classes** (100%): When summarise_classes.py is loaded via importlib from inside the console container, the self-bootstrap block must be stripped from the source string before exec()-ing it, since it would run against the read-only host-home mount and crash. All deps (neo4j, requests) must be pre-installed in the container image.
- **services.console.routes.classes** (100%): summarise_classes.py is NOT copied into any Docker container — it lives only in tools/ on the host. The console loads it at runtime via importlib from /host-home/Documents/projects/codeKG/tools/summarise_classes.py through the host-home mount. If that path is wrong or the mount is missing, the job errors immediately.
- **services.console.routes.classes.start_summarise** (100%): Ollama runs on the Mac host, not inside Docker. From any container the correct URL is http://host.docker.internal:11434 — never localhost:11434 which resolves to the container loopback. The console UI and summarise_classes.py default both use host.docker.internal.
- **services.console** (100%): requests is not installed in the console container by default (FastAPI uses httpx). summarise_classes.py imports requests to call Ollama — it must be listed in services/console/requirements.txt or the job fails immediately with: No module named requests.
- **services.console.routes.classes.classes_list** (100%): summary_total in classes_list() is correctly scoped to effective_repo using: MATCH (c:Class) WHERE c.repo_id = $repo_id AND NOT c.kind IN ["module"] AND c.summary IS NOT NULL. A separate class_total query provides the denominator (total non-module classes for the repo). The filtered `total` variable must never be used as the denominator — it reflects the current search filter, not the full repo size.
- **services.console.llm_audit.aggregate_stats** (100%): aggregate_stats correctly accepts a `days` parameter, computes a `cutoff` timestamp, and passes it to the SQL query via a bound parameter in the WHERE clause, ensuring stats are scoped to the requested timeframe rather than all-time.
- **services.console** (100%): The console container does not hot-reload. All files (templates, routes, requirements.txt) are baked at build time via COPY in the Dockerfile. Any change to services/console/ requires: docker compose up -d --build console
- **services.console** (100%): The console UI uses CSS custom properties defined in base.html :root (--bg, --surface, --primary, --success, --danger etc). All page templates must use these tokens — raw hex values in a template are a design bug. There is no external CSS file or build pipeline; all styles are inline in HTML templates.

## Classes

### `AuthMiddleware` — class
**File:** `services/console/main.py`  **LOC:** 21  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.main.AuthMiddleware`

Gate all console pages behind GitHub OAuth when AUTH_ENABLED. Bypassed for the auth routes themselves and /health. When auth is disabled (GITHUB_CLIENT_ID not set) every request passes through.

### `RequestLogMiddleware` — class
**File:** `services/console/main.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.main.RequestLogMiddleware`

Logs console requests along with response timing. Watch out for static-asset noise here, because the middleware intentionally skips those paths.

### `TestAnnotationRequired` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 15  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestAnnotationRequired`

TestAnnotationRequired is a class that includes methods for testing various aspects of annotation processing. The `test_without_at_prefix` method checks if annotations can be processed correctly when they do not start with the '@' symbol, ensuring flexibility in how annotations are applied. The `test_basic_match` method evaluates whether the system accurately identifies and matches annotations bas

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_without_at_prefix` | — | — |  |
| `public test_basic_match` | — | — |  |
| `public test_case_insensitive` | — | — |  |

### `TestAsk` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 28  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestAsk`

Exercises ask behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestCancelScan` — class
**File:** `services/console/tests/test_scan_launcher.py`  **LOC:** 29  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_scan_launcher.TestCancelScan`

Exercises cancel scan behavior in the scan launcher test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestCheckAccess` — class
**File:** `services/console/tests/test_auth.py`  **LOC:** 97  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_auth.TestCheckAccess`

Exercises check access behavior in the auth test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestClassesPage` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 54  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestClassesPage`

Exercises classes page behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestConfigRoutes` — class
**File:** `services/console/tests/test_config_routes.py`  **LOC:** 35  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_config_routes.TestConfigRoutes`

Exercises config routes behavior in the config routes test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_save_valid_key` | `console_client` | — |  |
| `public test_save_unknown_key_returns_400` | `console_client` | — |  |
| `public test_current_returns_redacted_secrets` | `console_client` | — |  |

### `TestControllerRepoRestriction` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 11  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestControllerRepoRestriction`

The `TestControllerRepoRestriction` class includes methods for testing API endpoints without direct access and for standard phrasing in tests. The `test_without_directly()` method ensures that certain API calls can be made even when not authenticated directly, verifying the system's ability to handle such scenarios gracefully. Meanwhile, the `test_standard_phrasing()` method checks that all respon

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_without_directly` | — | — |  |
| `public test_standard_phrasing` | — | — |  |

### `TestCurrentUser` — class
**File:** `services/console/tests/test_auth.py`  **LOC:** 19  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_auth.TestCurrentUser`

Exercises current user behavior in the auth test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestDashboard` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 29  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestDashboard`

Exercises dashboard behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestLaunchScan` — class
**File:** `services/console/tests/test_scan_launcher.py`  **LOC:** 80  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_scan_launcher.TestLaunchScan`

Exercises launch scan behavior in the scan launcher test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestLayerMustNotDependOn` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 14  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestLayerMustNotDependOn`

TestLayerMustNotDependOn is a class that includes methods for testing various aspects of FQN (Fully Qualified Name) handling. The `test_returns_fqn` method checks if the class correctly returns the FQN, ensuring that it adheres to naming conventions. The `test_quoted_names` method evaluates how the class handles names that require quoting, verifying that special characters are managed appropriatel

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_returns_fqn` | — | — |  |
| `public test_quoted_names` | — | — |  |
| `public test_basic_match` | — | — |  |

### `TestLoadEnvFile` — class
**File:** `services/console/tests/test_config_routes.py`  **LOC:** 54  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_config_routes.TestLoadEnvFile`

Exercises load env file behavior in the config routes test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_skips_comment_lines` | `config_routes` | — |  |
| `public test_strips_quotes_from_values` | `config_routes` | — |  |
| `public test_skips_blank_lines` | `config_routes` | — |  |
| `public test_parses_key_value_pairs` | `config_routes` | — |  |
| `public test_returns_empty_when_file_missing` | `config_routes` | — |  |

### `TestMcpAudit` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 26  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestMcpAudit`

Exercises mcp audit behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestModuleMustNotCall` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 20  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestModuleMustNotCall`

TestModuleMustNotCall ensures that no service tests are called directly, promoting isolation. It validates FQN (Fully Qualified Name) column handling through test_returns_fqn_column. test_basic_match checks for basic matching functionality, while test_directly_variant assesses variant handling without direct calls.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_services_in_prefix` | — | — |  |
| `public test_returns_fqn_column` | — | — |  |
| `public test_basic_match` | — | — |  |
| `public test_directly_variant` | — | — |  |

### `TestModulesPage` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 41  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestModulesPage`

Exercises modules page behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestOutputSafety` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 9  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestOutputSafety`

TestOutputSafety ensures that curly braces within input data do not lead to a key error by implementing a robust validation mechanism. The method `test_curly_braces_in_input_do_not_cause_key_error` specifically checks how the system handles unexpected characters in input, thereby enhancing the safety and reliability of output generation.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_curly_braces_in_input_do_not_cause_key_error` | — | — |  |

### `TestPatternCatalog` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 50  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestPatternCatalog`

Exercises pattern catalog behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestPatternsPage` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 19  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestPatternsPage`

Exercises patterns page behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestPoliciesPage` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 79  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestPoliciesPage`

Exercises policies page behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestPublicMethodAnnotation` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 23  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestPublicMethodAnnotation`

TestPublicMethodAnnotation is a class that includes several methods to validate the behavior of public method annotations in Java. The `test_must_annotated_variant` method checks if a method must be annotated with a specific annotation, ensuring compliance with coding standards. The `test_module_keyword_in_phrase_is_not_matched` method tests whether the module keyword within phrases is correctly i

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_must_annotated_variant` | — | — |  |
| `public test_module_keyword_in_phrase_is_not_matched` | — | — |  |
| `public test_basic_match` | — | — |  |
| `public test_without_at_prefix` | — | — |  |

### `TestRedact` — class
**File:** `services/console/tests/test_config_routes.py`  **LOC:** 29  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_config_routes.TestRedact`

Exercises redact behavior in the config routes test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_leaves_non_secret_unchanged` | `config_routes` | — |  |
| `public test_replaces_secret_with_dots` | `config_routes` | — |  |
| `public test_returns_empty_for_unset_secret` | `config_routes` | — |  |

### `TestReposPage` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 92  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestReposPage`

Exercises repos page behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestSaveEnvFile` — class
**File:** `services/console/tests/test_config_routes.py`  **LOC:** 35  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_config_routes.TestSaveEnvFile`

Exercises save env file behavior in the config routes test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_merges_with_existing_values` | `config_routes` | — |  |
| `public test_creates_file_with_correct_content` | `config_routes` | — |  |
| `public test_removes_keys_with_empty_values` | `config_routes` | — |  |

### `TestServiceMustNotExtend` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 6  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestServiceMustNotExtend`

TestServiceMustNotExtend is a class that includes a method named `test_basic_match`. This method does not take any parameters and does not return any value, indicated by its signature `void test_basic_match()`. The purpose of this method is to perform basic matching tests within the TestServiceMustNotExtend class.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_basic_match` | — | — |  |

### `TestSessionCookie` — class
**File:** `services/console/tests/test_auth.py`  **LOC:** 51  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_auth.TestSessionCookie`

Exercises session cookie behavior in the auth test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestSystemHealth` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 16  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestSystemHealth`

Exercises system health behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestToContainerPath` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 22  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestToContainerPath`

Exercises to container path behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestUnknownPolicy` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 18  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestUnknownPolicy`

TestUnknownPolicy is a class that includes several methods to validate the behavior of placeholder text in various scenarios. The method `test_placeholder_has_fqn_comment()` checks if the placeholder contains a fully qualified name (FQN) comment, ensuring it adheres to naming conventions. The method `test_empty_string_returns_placeholder()` verifies that an empty string input results in a default 

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_placeholder_has_fqn_comment` | — | — |  |
| `public test_empty_string_returns_placeholder` | — | — |  |
| `public test_gibberish_returns_placeholder` | — | — |  |
| `public test_placeholder_contains_original_text` | — | — |  |

### `TestValidateRepoPath` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 24  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestValidateRepoPath`

Exercises validate repo path behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `_AttrProxy` — class
**File:** `services/console/main.py`  **LOC:** 5  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.main._AttrProxy`

### `_DefaultZero` — class
**File:** `services/console/agent_index/generator.py`  **LOC:** 3  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.agent_index.generator._DefaultZero`

Dictionary that treats missing counters as zero during console summaries. Watch out for accidental writes here, because absent keys become real buckets once touched.

### `_Entry` — class
**File:** `services/console/llm_audit.py`  **LOC:** 51  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.llm_audit._Entry`

Represents one LLM audit row as rendered by the console. Watch out for schema alignment here, because UI filters and exports assume stable field names.

---

# Module: services/ingestion
_Generated 2026-06-09 20:27 UTC · commit `unpublished`_

**Path:** `/host-home/Documents/projects/codeKG/services/ingestion`  **Classes:** 39

## Depends on

_External files/modules this module imports from:_

- `codeKG/shared/config.py` — 1 import(s)

## Data stores

_Detected from source file imports and connection patterns:_

- **Neo4j** (graph) — see `.codekg/architecture/datastores.md` for schema
  - `kg/call_chain.py`
  - `kg/enrichment.py`
  - `kg/hygiene.py`
  - `kg/object_model.py`
  - `kg/writer.py`
  - `pattern_detector.py`
  - `policy_scanner.py`

## ⚡ Insights from previous sessions

_Non-obvious facts from engineering sessions — treat as expert hints._

- **services.ingestion** (100%): The codeKG protocol text exists in three separate places that must be kept in sync: (1) services/ingestion/claude_md_writer.py — written to repos at ingestion time, (2) services/api/renderers/template_renderer.py — served by GET /template/{repo_id} which powers both sync_claude_md and get_codebase_template, (3) .claude/CLAUDE.md — the live file for this repo. Changing the protocol in one place does not update the others.
- **services.ingestion.policy_scanner** (95%): Policy detectors in policy_scanner.py only fire against the *running* container's code — seeding new detectors requires either a container rebuild or manually calling `_save_policy()` via cypher. The 6 new open-source-checklist policies (undocumented-module, undocumented-high-blast, public-method-no-doc, console-imports-ingestion, mcp-imports-neo4j, duplicate-class-names) were seeded directly into Neo4j as `status='active'` with `source='manual'` so they are visible in the console and agent index immediately. On the next `docker compose up --build ingestion`, the auto-scan will MERGE over them (policy_id stable via sha1 hash), so the manual seed is safe to leave.

```python
# policy_scanner.py _stable_id()
def _stable_id(repo_id: str, key: str) -> str:
    h = hashlib.sha1(f"{repo_id}:{key}".encode()).hexdigest()[:8]
    return f"auto-{h}"
# BUT manually seeded policies use "policy-<name>" ids, not "auto-<hash>"
# so they will NOT be overwritten by auto-scan — they persist as separate nodes
```

When a manually seeded policy and an auto-scan policy cover the same concern, the KG will have two nodes. Use the same `_stable_id()` key when seeding manually, or accept the duplicate and delete the manual one after first auto-scan.
- **services.ingestion.kg.writer.KGWriter** (90%): KGWriter wire_edges has a 90s timeout added to prevent large repos from pinning Neo4j indefinitely — do not remove without load testing.

## Classes

### `ApiEndpoint` — class
**File:** `services/ingestion/parser/api_extractor.py`  **LOC:** 12  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.api_extractor.ApiEndpoint`

Describes an HTTP endpoint inferred from source annotations or route declarations. Watch out for the handler fields here, because later graph edges rely on them to join endpoints back to code.

### `ApiExtractor` — class
**File:** `services/ingestion/parser/api_extractor.py`  **LOC:** 157  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.api_extractor.ApiExtractor`

Extracts API surface area from supported source trees. Watch out for framework-specific heuristics here, because false positives here become durable endpoint nodes in the graph.

### `AsyncMethod` — class
**File:** `services/ingestion/parser/concurrency_extractor.py`  **LOC:** 8  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.concurrency_extractor.AsyncMethod`

Captures a method that appears to run asynchronously. Watch out for heuristic detection here, because async behavior is often inferred from framework annotations rather than explicit syntax alone.

### `BuildExtractor` — class
**File:** `services/ingestion/parser/build_extractor.py`  **LOC:** 287  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.build_extractor.BuildExtractor`

Inspects repository build files and test layouts to infer tooling. Watch out for mixed-language repos here, because this extractor is optimized for Java conventions and falls back heuristically elsewhere.

### `BuildInfo` — class
**File:** `services/ingestion/parser/build_extractor.py`  **LOC:** 8  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.build_extractor.BuildInfo`

Summarizes the build and test stack discovered for a repository. Watch out for default values here, because downstream prompts assume these fields are always populated sensibly.

### `ConcurrencyExtractor` — class
**File:** `services/ingestion/parser/concurrency_extractor.py`  **LOC:** 175  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.concurrency_extractor.ConcurrencyExtractor`

Scans source trees for concurrency patterns and hazards. Watch out for framework bias here, because different languages expose async behavior through very different idioms.

### `ConcurrencyFact` — class
**File:** `services/ingestion/parser/concurrency_extractor.py`  **LOC:** 7  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.concurrency_extractor.ConcurrencyFact`

Normalizes one concurrency-related signal before it is written to the graph. Watch out for confidence and source details here, because many of these facts are best-effort inferences.

### `CppParser` — class
**File:** `services/ingestion/parser/cpp_parser.py`  **LOC:** 397  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.cpp_parser.CppParser`

Parses C++ source files using Tree-sitter and extracts structural facts ready for writing into Neo4j. Output schema is compatible with JavaParser.

### `DirectoryEntry` — class
**File:** `services/ingestion/parser/repo_structure.py`  **LOC:** 6  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.repo_structure.DirectoryEntry`

Represents one directory discovered while classifying repository structure. Watch out for recursive expansion here, because callers use these entries to decide what parts of a repo deserve deeper parsing.

### `IngestionEngine` — class
**File:** `services/ingestion/ingestion_engine.py`  **LOC:** 361  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.ingestion_engine.IngestionEngine`

Coordinates repository scans from parsing through graph writes. Watch out for batch sizing and timeout behavior here, because this class is where large-repo performance problems tend to surface first.

### `JavaParser` — class
**File:** `services/ingestion/parser/java_parser.py`  **LOC:** 224  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.java_parser.JavaParser`

Parses Java source files using Tree-sitter and extracts structural facts ready for writing into Neo4j.

### `KGWriter` — class
**File:** `services/ingestion/kg/writer.py`  **LOC:** 860  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.kg.writer.KGWriter`

Writes parsed facts into Neo4j as CodeKG nodes and edges. Watch out for idempotency and batching here, because this class sits on the boundary between noisy source code and durable graph state.

### `ModuleInfo` — class
**File:** `services/ingestion/parser/build_extractor.py`  **LOC:** 7  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.build_extractor.ModuleInfo`

Represents one discovered module or service directory. Watch out for name and path normalization here, because later index generation uses this object to build stable file names.

### `ParsedFile` — class
**File:** `services/ingestion/parser/java_parser.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.java_parser.ParsedFile`

Holds all extracted facts from a single .java file.

### `ParsedFile` — class
**File:** `services/ingestion/parser/python_parser.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.python_parser.ParsedFile`

Holds all extracted facts from a single .py file.

### `ParsedFile` — class
**File:** `services/ingestion/parser/cpp_parser.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.cpp_parser.ParsedFile`

Holds all extracted facts from a single C++ file.

### `ProjectIdentity` — class
**File:** `services/ingestion/parser/repo_structure.py`  **LOC:** 12  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.repo_structure.ProjectIdentity`

Describes the high-level identity of a scanned project. Watch out for naming stability here, because several downstream artifacts use this object to label generated summaries.

### `PythonParser` — class
**File:** `services/ingestion/parser/python_parser.py`  **LOC:** 343  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.python_parser.PythonParser`

Parses Python source files using Tree-sitter and extracts structural facts ready for writing into Neo4j. Output schema is compatible with JavaParser.

### `RelationshipKind` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 3  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.RelationshipKind`

Names supported relationship kinds in emitted SCIP symbol information. Watch out for spelling changes here, because consumers treat these strings as wire-format values.

### `RepoRequest` — class
**File:** `services/ingestion/main.py`  **LOC:** 4  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.main.RepoRequest`

Validates ingestion requests for a repository path and identifier. Watch out for trust boundaries here, because these values come from external callers and drive filesystem access.

### `SCIPDocument` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPDocument`

SCIP representation of one source file. Produced by language plugins; consumed by the KG writer.

### `SCIPEmitter` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 98  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPEmitter`

Converts a ParsedFile (Java parser output) to a SCIPDocument. All language plugins must produce SCIPDocument — this is the contract.

### `SCIPOccurrence` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 5  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPOccurrence`

A use of a symbol at a specific location in the file.

### `SCIPRange` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 6  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPRange`

Represents a source range in SCIP coordinates. Watch out for line and character indexing here, because off-by-one errors make downstream navigation frustrating fast.

### `SCIPRelationship` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 5  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPRelationship`

Represents a relationship attached to symbol information. Watch out for directionality here, because consumers use these links to reconstruct hierarchy and inheritance.

### `SCIPSymbolInformation` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 15  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPSymbolInformation`

Metadata about a symbol defined in this document.

### `TestBlastScoring` — class
**File:** `services/ingestion/tests/test_hygiene.py`  **LOC:** 23  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.tests.test_hygiene.TestBlastScoring`

Exercises blast scoring behavior in the hygiene test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_no_dependents_full_score` | — | — |  |
| `public test_high_blast_zero_score` | — | — |  |
| `public test_moderate_blast_partial_score` | — | — |  |

### `TestBuildExtractorDetection` — class
**File:** `services/ingestion/tests/test_build_extractor.py`  **LOC:** 67  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.tests.test_build_extractor.TestBuildExtractorDetection`

Exercises build extractor detection behavior in the build extractor test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestCategory` — class
**File:** `services/ingestion/parser/build_extractor.py`  **LOC:** 6  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.build_extractor.TestCategory`

Groups tests by annotation or base-class signal. Watch out for the description text here, because it is surfaced directly in generated onboarding material.

### `TestClassExtraction` — class
**File:** `services/ingestion/tests/test_python_parser.py`  **LOC:** 194  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.tests.test_python_parser.TestClassExtraction`

Exercises class extraction behavior in the python parser test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestClassScore` — class
**File:** `services/ingestion/tests/test_hygiene.py`  **LOC:** 28  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.tests.test_hygiene.TestClassScore`

Exercises class score behavior in the hygiene test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_score_clamped_to_valid_range` | — | — |  |
| `public test_god_class_scores_low` | — | — |  |
| `public test_perfect_class_scores_100` | — | — |  |

### `TestCouplingScoring` — class
**File:** `services/ingestion/tests/test_hygiene.py`  **LOC:** 17  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.tests.test_hygiene.TestCouplingScoring`

Exercises coupling scoring behavior in the hygiene test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_high_coupling_zero_score` | — | — |  |
| `public test_low_coupling_full_score` | — | — |  |

### `TestDocsScoring` — class
**File:** `services/ingestion/tests/test_hygiene.py`  **LOC:** 15  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.tests.test_hygiene.TestDocsScoring`

Exercises docs scoring behavior in the hygiene test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_with_docstring_scores_25` | — | — |  |
| `public test_without_docstring_scores_0` | — | — |  |

### `TestExtractModules` — class
**File:** `services/ingestion/tests/test_build_extractor.py`  **LOC:** 48  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.tests.test_build_extractor.TestExtractModules`

Exercises extract modules behavior in the build extractor test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestFullScan` — class
**File:** `services/ingestion/tests/test_ingestion_engine.py`  **LOC:** 82  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.tests.test_ingestion_engine.TestFullScan`

Exercises full scan behavior in the ingestion engine test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestJavaClassExtraction` — class
**File:** `services/ingestion/tests/test_java_parser.py`  **LOC:** 167  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.tests.test_java_parser.TestJavaClassExtraction`

Exercises java class extraction behavior in the java parser test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_interface_kind` | — | — |  |
| `public test_simple_class_methods` | — | — |  |
| `public test_javadoc_extracted` | — | — |  |
| `public test_enum_kind` | — | — |  |
| `public test_empty_source_no_crash` | — | — |  |
| `public test_package_and_imports` | — | — |  |
| `public test_constructor_in_methods` | — | — |  |
| `public test_annotated_class` | — | — |  |

### `TestLetterGrade` — class
**File:** `services/ingestion/tests/test_hygiene.py`  **LOC:** 27  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.tests.test_hygiene.TestLetterGrade`

Exercises letter grade behavior in the hygiene test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_grade_f_boundary` | — | — |  |
| `public test_grade_d_boundary` | — | — |  |
| `public test_grade_c_boundary` | — | — |  |
| `public test_grade_a_boundary` | — | — |  |
| `public test_grade_b_boundary` | — | — |  |

### `TestSizeScoring` — class
**File:** `services/ingestion/tests/test_hygiene.py`  **LOC:** 33  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.tests.test_hygiene.TestSizeScoring`

Exercises size scoring behavior in the hygiene test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_small_class_full_score` | — | — |  |
| `public test_medium_class_partial_score` | — | — |  |
| `public test_large_class_low_score` | — | — |  |
| `public test_god_class_zero_score` | — | — |  |

### `ThreadPoolDeclaration` — class
**File:** `services/ingestion/parser/concurrency_extractor.py`  **LOC:** 8  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.concurrency_extractor.ThreadPoolDeclaration`

Captures a discovered thread-pool declaration. Watch out for sizing fields here, because downstream analysis uses them to flag hidden concurrency hotspots.

---

# Module: services/mcp
_Generated 2026-06-09 20:27 UTC · commit `unpublished`_

**Path:** `/host-home/Documents/projects/codeKG/services/mcp`  **Classes:** 9

## ⚡ Insights from previous sessions

_Non-obvious facts from engineering sessions — treat as expert hints._

- **services.mcp** (100%): codekg_request_id in the MCP response footer was previously the JSON-RPC request_id — a different value for every single tool call. This is why using the 'first call's request_id' was so fragile: any mistake in tracking which call was first gave a wrong value. Fixed by making codekg_request_id equal to turn_id in the footer, so both values are always the same stable string and there is no ambiguity about which to use.
- **services.mcp.main** (95%): sync_claude_md must return content to Claude Code rather than writing server-side — server-side writes break remote usage where the codeKG server and the engineer's filesystem are on different machines. The correct pattern is: tool returns content, Claude Code calls Write.
- **services.mcp.main** (85%): The sync_claude_md tool includes a save_as comment header in the response so Claude Code knows what filename to use without needing to infer it from context.

## Classes

### `TestCaptureInsight` — class
**File:** `services/mcp/tests/test_mcp_tools.py`  **LOC:** 37  **Grade:** ?  **Blast:** 0
**FQN:** `services.mcp.tests.test_mcp_tools.TestCaptureInsight`

Exercises capture insight behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestErrorHandling` — class
**File:** `services/mcp/tests/test_mcp_tools.py`  **LOC:** 22  **Grade:** ?  **Blast:** 0
**FQN:** `services.mcp.tests.test_mcp_tools.TestErrorHandling`

Exercises error handling behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestGetChangeImpact` — class
**File:** `services/mcp/tests/test_mcp_tools.py`  **LOC:** 16  **Grade:** ?  **Blast:** 0
**FQN:** `services.mcp.tests.test_mcp_tools.TestGetChangeImpact`

Exercises get change impact behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestGetClass` — class
**File:** `services/mcp/tests/test_mcp_tools.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.mcp.tests.test_mcp_tools.TestGetClass`

Exercises get class behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestGetCodebaseTemplate` — class
**File:** `services/mcp/tests/test_mcp_tools.py`  **LOC:** 14  **Grade:** ?  **Blast:** 0
**FQN:** `services.mcp.tests.test_mcp_tools.TestGetCodebaseTemplate`

Exercises get codebase template behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestGetRepoSummary` — class
**File:** `services/mcp/tests/test_mcp_tools.py`  **LOC:** 14  **Grade:** ?  **Blast:** 0
**FQN:** `services.mcp.tests.test_mcp_tools.TestGetRepoSummary`

Exercises get repo summary behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestListArchPolicies` — class
**File:** `services/mcp/tests/test_mcp_tools.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.mcp.tests.test_mcp_tools.TestListArchPolicies`

Exercises list arch policies behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestSearchClasses` — class
**File:** `services/mcp/tests/test_mcp_tools.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.mcp.tests.test_mcp_tools.TestSearchClasses`

Exercises search classes behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestSessionId` — class
**File:** `services/mcp/tests/test_mcp_tools.py`  **LOC:** 12  **Grade:** ?  **Blast:** 0
**FQN:** `services.mcp.tests.test_mcp_tools.TestSessionId`

Exercises session id behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

---

# Module: services/watcher
_Generated 2026-06-09 20:27 UTC · commit `unpublished`_

**Path:** `/host-home/Documents/projects/codeKG/services/watcher`  **Classes:** 3

## Classes

### `TestIsScanRunning` — class
**File:** `services/watcher/tests/test_watcher.py`  **LOC:** 27  **Grade:** ?  **Blast:** 0
**FQN:** `services.watcher.tests.test_watcher.TestIsScanRunning`

Exercises is scan running behavior in the watcher test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestLaunchScan` — class
**File:** `services/watcher/tests/test_watcher.py`  **LOC:** 79  **Grade:** ?  **Blast:** 0
**FQN:** `services.watcher.tests.test_watcher.TestLaunchScan`

Exercises launch scan behavior in the watcher test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestLoadRepos` — class
**File:** `services/watcher/tests/test_watcher.py`  **LOC:** 46  **Grade:** ?  **Blast:** 0
**FQN:** `services.watcher.tests.test_watcher.TestLoadRepos`

Exercises load repos behavior in the watcher test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

---
