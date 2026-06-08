# API Service

> FastAPI service that is the operational core of codeKG — it handles impact analysis, agent index generation and publishing, natural language queries, policy evaluation, and all write operations across the system.

---

## Responsibilities

The API is the **only service that writes** to:
- `agent_index.db` — generates and stores agent index file content
- The repo's `.codekg/` directory — publishes files via git commit
- `telemetry.db` — records MCP tool call sessions

The console and MCP server are read-oriented and proxy writes to the API via HTTP.

**Base URL:** `http://api:8000` (internal) or `http://localhost:8001` (host-exposed)

---

## Startup sequence

```python
# services/api/main.py

@app.on_event("startup")
async def _startup():
    _init_neo4j()          # connect to Neo4j, store driver in module-level var
    _init_agent_index()    # wire run_query into generator, init SQLite schema
    _init_telemetry()      # create telemetry.db tables
```

The Neo4j driver is a module-level singleton. `run_query` is injected into `agent_index/generator.py` after startup — this is why the generator can be imported without a live driver (it falls back to a no-op).

---

## Endpoints

### Impact analysis

```
POST /change-impact
```

Given a list of changed files and a repo ID, returns a full blast radius report.

```python
# Request
{
  "repo_id": "codeKG",
  "changed_files": ["services/api/impact/engine.py"],
  "commit_sha": "abc123"
}

# Response
{
  "repo_id": "codeKG",
  "changed_files": ["services/api/impact/engine.py"],
  "directly_affected": [
    {"fqn": "services.api.impact.engine.ImpactEngine", "blast_size": 0, "grade": "A"}
  ],
  "transitive_dependents": [],
  "exposed_endpoints": [],
  "affected_modules": ["services/api"],
  "impacted_policies": [],
  "suggested_tests": [
    {"fqn": "services.api.tests.test_api.TestClassContext"}
  ],
  "risk_score": 0.2
}
```

The `ImpactEngine` (in `services/api/impact/engine.py`) runs several Cypher queries in sequence:

1. `_directly_affected` — classes whose `file_path` matches the changed files
2. `_transitive_dependents` — classes that import any directly affected class
3. `_callers` — methods that call methods in directly affected classes
4. `_exposed_endpoints` — API endpoints served by affected classes
5. `_affected_modules` — modules containing any affected class
6. `_relevant_policies` — active policies applicable to affected modules
7. `_suggested_tests` — test classes that cover directly affected classes
8. `_risk_score` — weighted float combining blast size, grade, and endpoint exposure

```python
# Calling impact from Claude Code via MCP tool:
result = get_change_impact(
    repo_id="codeKG",
    changed_files=["services/api/main.py"]
)
# Returns JSON matching the structure above
```

---

### Agent index

```
POST /agent-index/regen          # regenerate one or all files for a repo
POST /agent-index/publish        # write files to disk and git commit
```

**Regen one file:**
```python
POST /agent-index/regen
{"repo_id": "codeKG", "file_key": "modules/services--api"}
# → {"ok": true, "file_key": "modules/services--api", "chars": 8432}
```

**Regen all files:**
```python
POST /agent-index/regen
{"repo_id": "codeKG"}
# Regenerates all 19 files, auto-hides empty ones
# → {"ok": true, "generated": 19, "hidden_empty": 3}
```

**Publish:**
```python
POST /agent-index/publish
{"repo_id": "codeKG"}
# Writes .codekg/ to disk, deletes ghost files for hidden entries,
# creates git commit, updates published_at / published_sha in DB
# → {"ok": true, "files_written": 16, "sha": "d4e8f21", "deleted": []}
```

The publish flow in detail:
```
1. Load all visible (hidden=0) files from agent_index.db
2. For claude_md / agents_md keys: write to repo root CLAUDE.md / AGENTS.md
   (upsert codekg:start…codekg:end section if the file exists, create in .codekg/ if not)
3. For all other keys: write to <repo_path>/.codekg/<directory>/<filename>
4. Build expected_paths set (excludes CLAUDE.md / AGENTS.md from ghost cleanup)
5. Delete any .codekg/ file on disk NOT in expected_paths (orphan cleanup)
6. git add .codekg/ CLAUDE.md AGENTS.md (whichever exist)
7. git commit -m "chore: update CodeKG agent index [skip ci]"
8. store.mark_published(repo_id, sha) → sets status='current', published_at, published_sha
```

---

### Natural language queries

```
POST /nl-query
```

Translates a natural language question into a Cypher query via LLM, executes it, and returns results.

```python
POST /nl-query
{"repo_id": "codeKG", "question": "Which classes have blast radius over 5?"}
# → {"query": "MATCH (c:Class {repo_id: 'codeKG'}) WHERE c.blast_size > 5 ...", "results": [...]}
```

The LLM call is logged to `llm_audit.db`. The schema file (`.codekg/architecture/schema.md`) is passed as context so the LLM knows available node types and properties without probing the graph.

---

### MCP telemetry

```
POST /telemetry/session
POST /telemetry/tool-call
GET  /telemetry/sessions
GET  /telemetry/session/{session_id}
```

Records every MCP tool invocation with:
- Session ID (8-char UUID prefix, stable per MCP process)
- Tool name, input JSON, result summary
- Per-step token cost (cached + uncached + output)
- Timestamps

```python
# What gets logged for a capture_insight call:
{
  "session_id": "a3f9c1b2",
  "tool_name": "capture_insight",
  "input_json": "{\"repo_id\": \"codeKG\", \"applies_to\": \"services.api.main\", \"insight\": \"...\"}",
  "step_tokens": 1240,
  "created_at": "2026-06-05T20:34:11Z"
}
```

> **Token counting note:** `input_tokens` from the Anthropic API is incremental uncached-only tokens per message, not total context. Full step cost = `cache_read_input_tokens` + `cache_creation_input_tokens` + `output_tokens` — computed as deltas between consecutive assistant messages.

---

### Class and module lookups

```
GET  /class/{fqn}           # full class detail including object_model
GET  /module/{module_id}    # module summary with class list
GET  /repo-summary          # high-level stats for all registered repos
POST /search-classes        # fuzzy class name search
```

These back the MCP tools and the console UI. All read directly from Neo4j.

---

### Policy endpoints

```
GET  /policies/{repo_id}         # list active policies
POST /check-violations           # evaluate policies against given files
GET  /arch-patterns/{repo_id}    # architectural patterns detected
```

---

### Template / CLAUDE.md / AGENTS.md

```
GET /template/{repo_id}    # returns the full pre-computed intelligence document
GET /sync-claude-md/{repo_id}  # returns latest CLAUDE.md snippet content
```

Used by `sync_claude_md` MCP tool to push fresh CLAUDE.md content to the agent on demand.

The publish flow writes two separate files using different generated content:
- `CLAUDE.md` (for Claude Code) — includes MCP tool references (`capture_insight`, `get_change_impact`, `search_classes`)
- `AGENTS.md` (for Codex / OpenAI agents) — uses shell command equivalents (`cat .codekg/INDEX.md`) since Codex has no MCP support

If `CLAUDE.md` exists in the repo root, codeKG updates the `<!-- codekg:start -->…<!-- codekg:end -->` section in place. Same for `AGENTS.md`. Both can coexist in the same repo.

---

## Middleware

`RequestLogMiddleware` logs every request with method, path, status code, and duration to the structured logger. All logs are JSON via `codekg_logger`.

```python
class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        log.info("request", method=request.method, path=request.url.path,
                 status=response.status_code, ms=int((time.time()-start)*1000))
        return response
```

---

## Error handling

All endpoints return consistent error shapes:
```json
{"detail": "repo_id required"}
```

HTTP 400 for bad input, 404 for missing resources, 500 for unexpected failures. The MCP server and console both handle these and surface them as toast messages or tool errors.

---

## Configuration (environment variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `NEO4J_URI` | `bolt://neo4j:7687` | Neo4j connection |
| `NEO4J_USER` | `neo4j` | Neo4j auth |
| `NEO4J_PASSWORD` | `codekg_dev` | Neo4j auth |
| `ANTHROPIC_API_KEY` | — | LLM calls for NL query and summarisation |
| `REPOS_REGISTRY` | `/repos/repos.json` | Path to repo registry JSON |
| `AGENT_INDEX_DB` | `/repos/agent_index.db` | SQLite for agent index store |
| `HOME_MOUNT` | — | Host home directory mount point |
| `API_TOKEN` | _(empty)_ | Bearer token for all API endpoints — leave empty for single-user localhost mode |
| `NL_QUERY_MODEL` | `claude-haiku-4-5` | LLM model for NL → Cypher translation |
| `NL_ANSWER_MODEL` | `claude-sonnet-4-5` | LLM model for answering complex questions |

---

## Adding a new endpoint

```python
# 1. Add route to services/api/main.py (or a sub-router)
@app.get("/my-endpoint/{repo_id}")
async def my_endpoint(repo_id: str):
    rows = run_query("""
        MATCH (c:Class {repo_id: $repo_id})
        RETURN c.fqn, c.hygiene_grade
        ORDER BY c.hygiene_grade
        LIMIT 20
    """, repo_id=repo_id)
    return {"classes": rows}

# 2. Add a proxy in services/console/routes/ if it needs a UI
# 3. Optionally expose via MCP tool in services/mcp/main.py
```

`run_query` is the module-level function wired to the Neo4j driver at startup. Always include `repo_id` in the Cypher WHERE clause.
