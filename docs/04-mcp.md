# MCP Server & Tools

> The MCP (Model Context Protocol) server exposes the codeKG knowledge graph as 15 structured tools that AI coding agents can call natively — giving Claude Code, Cursor, and Codex direct access to impact analysis, class discovery, architectural policies, and session insight capture.

---

## What MCP is

MCP is an open protocol for AI agents to call structured tools. The codeKG MCP server runs as a persistent SSE (Server-Sent Events) service on port 8002.

```
Claude Code
    │  calls tool: get_change_impact(repo_id="codeKG", changed_files=["..."])
    ▼
codekg-mcp  (SSE server at http://localhost:8002/sse — persistent, shared)
    │  proxies to: POST http://api:8000/change-impact
    ▼
codekg-api  (returns JSON)
    │
    ▼
codekg-mcp  (formats result, returns TextContent)
    │
    ▼
Claude Code (receives structured result, uses it without touching source files)
```

> **Note:** The MCP server does not currently write to `mcp_audit.db`. Tool calls are logged to Docker stdout only. Telemetry (tokens, tool call counts, user prompts) is submitted separately by the Claude Code stop hook to `POST /telemetry/session`.

---

## Configuration in Claude Code

The default transport is **SSE**. Add codeKG once with:

```bash
claude mcp add codekg --transport sse http://localhost:8002/sse
```

Or add it to `.mcp.json` in any repo that should use codeKG:

```json
{
  "mcpServers": {
    "codekg": {
      "type": "sse",
      "url": "http://localhost:8002/sse"
    }
  }
}
```

Verify it's registered:

```bash
claude mcp list   # should show: codekg  sse  http://localhost:8002/sse
```

> The Get Started wizard at `http://localhost:8080/getstarted` (Step 5) shows this command pre-filled and ready to copy.

---

## Tool reference

### `answer_question`

Natural-language question answered from the knowledge graph. The API translates to Cypher via LLM, executes it, and returns formatted results.

```python
answer_question(
    repo_id="codeKG",
    question="Which classes have the highest blast radius?"
)
# → "The top classes by blast radius are: codekg_logger (blast=8), ..."
```

**When to use:** Open-ended structural questions where you don't know the exact Cypher query. Slower than direct tools — involves an LLM call.

---

### `get_module_context`

Full context for a logical module: class list, method signatures, dependencies, insights.

```python
get_module_context(
    repo_id="codeKG",
    module_id="services/api"
)
# → Full markdown text of the module file (same as .codekg/modules/services--api.md)
```

**When to use:** Prefer reading `.codekg/modules/<name>.md` directly — it's the same content without an HTTP call. Use this tool only when you need the live version mid-session after a regen.

---

### `get_class_context`

Detailed context for a single class: description, methods with signatures, callers, callees, insights.

```python
get_class_context(
    repo_id="codeKG",
    fqn="services.api.impact.engine.ImpactEngine"
)
# → Structured text with methods, blast radius, grade, callers
```

---

### `get_class`

Object model snapshot for a class — the raw `object_model` JSON enriched with blast radius and hygiene data. Most precise class data available.

```python
get_class(
    repo_id="codeKG",
    fqn="services.api.impact.engine.ImpactEngine"
)
# → {
#     "fqn": "services.api.impact.engine.ImpactEngine",
#     "kind": "class",
#     "hygiene_grade": "A",
#     "blast_size": 0,
#     "methods": [
#       {"name": "compute", "return_type": "ImpactReport",
#        "parameters": ["str repo_id", "list[str] changed_files", "Optional[str] commit_sha"]}
#     ]
#   }
```

---

### `search_class` / `search_classes`

Find classes by name pattern. `search_class` returns a brief summary; `search_classes` returns full snapshots for each match.

```python
search_classes(
    repo_id="codeKG",
    name_pattern="Writer"
)
# → [
#     {"fqn": "services.ingestion.kg.writer.KGWriter", "grade": "C", "blast_size": 0, ...},
#     {"fqn": "services.ingestion.kg.writer.TribalKnowledgeWriter", ...}
#   ]
```

**When to use:** When you know the class name but not its module. If you know the module, read the module file directly instead.

---

### `get_change_impact`

Blast radius analysis for a set of changed files. Returns directly affected classes, transitive dependents, exposed endpoints, relevant policies, and suggested tests.

```python
get_change_impact(
    repo_id="codeKG",
    changed_files=["services/api/agent_index/store.py"],
    commit_sha="abc123"   # optional
)
# → {
#     "directly_affected": [{"fqn": "services.api.agent_index.store", "grade": "?"}],
#     "transitive_dependents": [],
#     "exposed_endpoints": [],
#     "affected_modules": ["services/api"],
#     "impacted_policies": [],
#     "suggested_tests": [],
#     "risk_score": 0.1
#   }
```

**When to use:** After making any change. Call this before finalising your work to confirm the blast radius matches your expectations.

---

### `list_arch_policies`

Returns all active architectural policies for a repo with their Cypher constraints, severity, and current violator counts.

```python
list_arch_policies(repo_id="codeKG")
# → [
#     {
#       "policy_id": "auto-403ee21d",
#       "title": "Untested Package",
#       "severity": "warning",
#       "natural_language": "Every production package with 3+ classes should have at least one test class",
#       "violator_count": 8
#     }
#   ]
```

---

### `check_violations`

Evaluate architectural policies against a specific set of files or classes.

```python
check_violations(
    repo_id="codeKG",
    file_paths=["services/api/main.py"]
)
# → {"violations": [], "files_checked": 1}
```

---

### `get_arch_patterns`

Architectural patterns and anti-patterns detected in the codebase, with match counts and representative classes.

```python
get_arch_patterns(repo_id="codeKG")
# → [
#     {"name": "Test Case", "category": "Testing", "match_count": 34, "anti_pattern": false},
#     {"name": "Repository", "category": "Data Access", "match_count": 12, "anti_pattern": false}
#   ]
```

---

### `get_repo_summary`

High-level summary of all registered repositories: class counts, hygiene scores, module counts, last commit.

```python
get_repo_summary()
# → [
#     {"repo_id": "codeKG", "class_count": 75, "hygiene_grade": "B",
#      "hygiene_score": 74.4, "module_count": 5, "last_commit": "5185bf1"}
#   ]
```

---

### `get_feature_context`

Aggregate context for a set of classes — useful when a feature spans multiple classes across modules.

```python
get_feature_context(
    repo_id="codeKG",
    class_fqns=[
        "services.api.agent_index.generator",
        "services.api.agent_index.store"
    ]
)
# → Combined context with methods, relationships, and insights for all named classes
```

---

### `get_codebase_template`

Returns the full pre-computed intelligence document for a repo — the same content as the combined agent index. Useful for seeding context at session start.

```python
get_codebase_template(repo_id="codeKG")
# → Full markdown text covering all modules, policies, and insights
```

---

### `sync_claude_md`

Fetches the latest CLAUDE.md snippet from codeKG and returns it. Used to update the agent's instructions mid-session if the repo's CLAUDE.md changed.

```python
sync_claude_md(repo_id="codeKG")
# → "## CodeKG Agent Index\n_Auto-maintained...\n..."
```

---

### `capture_insight`

**The most important tool.** Records a non-obvious fact discovered during the session into the knowledge graph as a `TribalKnowledge` node. These insights are surfaced at the top of every future module file and insight index.

```python
capture_insight(
    repo_id="codeKG",
    insight="The wire_edges method has a 90-second timeout added to prevent Neo4j lock on large repos — do not remove without load testing.",
    applies_to="services.ingestion.kg.writer.KGWriter",   # FQN of class or module
    scope="method",       # "system" | "module" | "class" | "method"
    confidence=0.9
)
# → {"ok": true, "tk_id": "tk_a3b9f1c2d4e5"}
```

**Always call this at the end of a session** if you discovered anything non-obvious. This is how the codebase learns.

---

## Session identity

Each MCP process gets an 8-character session ID at startup (`SESSION_ID = str(uuid4())[:8]`). This ID appears in:
- All `capture_insight` calls (links insights to the session that captured them)
- The console telemetry view (via stop hook submission)

```python
# In SSE mode: per-connection context vars (_cv_session_id) are used
# Each client connection gets its own session ID — the server is shared
```

---

## Audit logging

MCP tool calls are logged to Docker stdout (structured JSON). They are **not** currently written to `mcp_audit.db` — the MCP server has no audit logging code.

Telemetry is collected separately via the Claude Code stop hook (`require_telemetry.py`), which reads the session transcript and posts token usage and tool call records to `POST /telemetry/session` on the API. This data is surfaced in the console `/telemetry` and `/telemetry/{session_id}` pages.

The `/mcp-audit` console page shows only the older `submit_session_telemetry` MCP calls that pre-date the switch to the stop hook pattern.

---

## Adding a new tool

```python
# In services/mcp/main.py, add to _list_tools():
Tool(
    name="my_new_tool",
    description="What it does and when to use it",
    inputSchema={
        "type": "object",
        "properties": {
            "repo_id": {"type": "string", "description": "Repository ID"},
            "my_param": {"type": "string", "description": "..."}
        },
        "required": ["repo_id", "my_param"]
    }
)

# Add handler in _call_tool():
elif name == "my_new_tool":
    r = http.post("/my-api-endpoint", json={"repo_id": args["repo_id"], ...})
    return [TextContent(type="text", text=r.text)]
```

The tool will appear in Claude Code's tool list on next MCP server restart.

---

## Common mistakes

| Mistake | Consequence | Fix |
|---------|------------|-----|
| Not calling `capture_insight` | Session knowledge lost forever | Call it at end of every session |
| Calling `get_change_impact` before making changes | Stale results | Call it *after* editing files |
| Using `search_classes` when you know the module | Unnecessary call | Read `.codekg/modules/<name>.md` instead |
| Calling `get_module_context` when `.codekg/` is fresh | Duplicate work | Prefer reading the static file |
| Forgetting `repo_id` | Wrong data or 400 error | Always pass `repo_id` |
