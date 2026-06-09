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
