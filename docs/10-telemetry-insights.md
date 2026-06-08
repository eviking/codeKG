# Telemetry & Insights

> Two systems that make the codebase smarter over time: telemetry captures what agents do and what it costs, insights capture what agents discover and make it available to every future session.

---

## The two systems

**Telemetry** answers: *What did the agent do? How much did it cost? What tools did it call?*

**Insights (Tribal Knowledge)** answers: *What non-obvious things did the agent learn that future agents should know?*

They are complementary. Telemetry is observability — it helps you understand agent behavior and cost. Insights are memory — they make future sessions better.

---

# Telemetry

## What gets recorded

Every MCP tool call is recorded in `telemetry.db` with:

```sql
-- sessions table
CREATE TABLE sessions (
    session_id      TEXT PRIMARY KEY,
    client          TEXT,         -- "claude-code", "cursor", "unknown"
    started_at      TEXT,
    ended_at        TEXT,
    total_tokens    INTEGER,
    tool_call_count INTEGER
);

-- tool_calls table
CREATE TABLE tool_calls (
    id          INTEGER PRIMARY KEY,
    session_id  TEXT,
    tool_name   TEXT,
    input_json  TEXT,             -- full JSON input to the tool
    result_summary TEXT,          -- first 500 chars of result
    step_tokens INTEGER,          -- token cost for this call
    created_at  TEXT
);
```

> **Rows before `input_json` was added have NULL there.** The question text for those calls is permanently unrecoverable. This limits query plan reconstruction for old sessions.

---

## Token cost calculation

Token counting from the Anthropic API is non-obvious:

```
input_tokens         = incremental uncached-only tokens per message (usually 1–3 in a cached conversation)
cache_read_tokens    = tokens served from cache (cheap)
cache_creation_tokens = tokens written to cache (expensive first time)
output_tokens        = tokens in the response

Full step cost = Δcache_read + Δcache_creation + output_tokens

Important: cache_read_input_tokens and cache_creation_input_tokens are
cumulative high-water marks for the whole conversation — NOT per-message.
To get per-step cost, diff consecutive assistant messages.
```

```python
# Correct per-step token calculation:
prev = messages[i-1].usage
curr = messages[i].usage

step_tokens = (
    (curr.cache_read_input_tokens - prev.cache_read_input_tokens) +
    (curr.cache_creation_input_tokens - prev.cache_creation_input_tokens) +
    curr.output_tokens
)
```

---

## Console telemetry views

### Session list — `GET /telemetry`

All sessions ordered by recency. Shows:
- Session ID (8-char UUID prefix)
- Client name (Claude Code, Cursor, etc.)
- Duration
- Total tool calls
- Total token cost

```
Session         | Client       | Duration | Tools | Tokens
a3f9c1b2       | Claude Code  | 47m      | 23    | 89,412
8b2d4e7f       | Claude Code  | 12m      | 7     | 31,203
```

### Session detail — `GET /telemetry/{session_id}`

Full timeline of a session:

| Time | Tool | Target | Tokens | Action |
|------|------|--------|--------|--------|
| 20:34:11 | `capture_insight` | `services.api.agent_index.generator` | 1,240 | Saved insight |
| 20:33:45 | `get_change_impact` | `services/api/agent_index/store.py` | 892 | Impact analysis |
| 20:32:18 | `get_class` | `services.api.agent_index.store` | 445 | Class lookup |

The **Target** column shows the meaningful identifier from the tool input:
```python
# Priority order:
target = (inp.get("applies_to")      # capture_insight
       or inp.get("fqn")             # get_class, get_class_context
       or inp.get("class_name")
       or inp.get("module_id")
       or inp.get("repo_id")
       or inp.get("insight", "")[:80])

# File paths are shortened to last 3 segments:
# "/host-home/code/my-service/services/api/main.py"
# → "my-service/services/api/main.py"
```

---

## MCP audit log

The `mcp_audit.db` (separate from `telemetry.db`) stores the raw MCP protocol calls including full input and output. Accessible at `/mcp-audit` in the console.

```sql
CREATE TABLE mcp_calls (
    id             INTEGER PRIMARY KEY,
    session_id     TEXT,
    tool_name      TEXT,
    input_json     TEXT,
    result_summary TEXT,
    step_tokens    INTEGER,
    created_at     TEXT
);
```

---

# Insights (Tribal Knowledge)

## What an insight is

A `TribalKnowledge` node is a structured, queryable fact about the codebase captured by an agent during a session. It answers the question: *"What non-obvious thing did you learn that the next engineer working in this area should know?"*

Examples of good insights:

```
"The wire_edges method has a 90-second timeout — do not remove without load testing on large repos."

"Route registration order is critical when a path-parameter catch-all exists. GET /classes/{fqn:path} 
must be registered AFTER more-specific routes or they get swallowed. Symptom: 404 with body 
'Class summarise/<id> not found'."

"object_model JSON on Class nodes contains a 'methods' array with return_type, parameters, and 
modifiers — this is richer than the separate Method nodes which lack a 'signature' property."

"Ollama runs on the Mac host, not inside Docker. From any container the correct URL is 
http://host.docker.internal:11434 — never localhost:11434."
```

These facts are:
- Non-obvious (can't be derived from reading the code)
- Specific (attached to a class or module FQN)
- Actionable (the next agent can use them to avoid a mistake or make a better decision)

---

## Capturing insights

```python
# Via MCP tool (the right way — call this at the end of every session):
capture_insight(
    repo_id="codeKG",
    insight="The _content_is_empty check should only scan the first 200 chars of body, "
            "not the full content — later paragraphs legitimately contain empty-file sentinel phrases.",
    applies_to="services.api.main",    # dot-separated FQN — module, class, or method
    scope="module",                    # "system" | "module" | "class" | "method"
    confidence=0.9                     # 0.0–1.0
)
# → {"ok": true, "tk_id": "tk_f9fd11a79a1d"}
```

The `applies_to` field must be a dot-separated FQN. For module-level insights, use the module path with dots (`services.api.agent_index.generator`). For class-level, use the full class FQN. For method-level, use `ClassName#methodName`.

---

## Where insights surface

Insights appear in three places:

### 1. Module files (most visible)

At the top of every `.codekg/modules/<name>.md` file, pinned before the class inventory:

```markdown
## ⚡ Insights from previous sessions

_Non-obvious facts from engineering sessions — treat as expert hints._

- **services.api.main** (100%): The agent index publish is a two-step process: 
  POST /agent-index/regen writes to SQLite store, then POST /agent-index/publish 
  writes from store to disk and commits to git. Calling only regen leaves disk files stale.

- **services.api.agent_index.generator** (100%): object_model JSON on Class nodes 
  contains a 'methods' array — richer than the separate Method nodes.
```

### 2. Insights index — `.codekg/insights/index.md`

The complete reference of all insights, grouped by module area, ordered by confidence.

### 3. Console insights page — `GET /insights`

Browse all insights by module, filter by scope, see confidence levels and session metadata.

---

## Staleness

When a file that an insight references is changed in a commit, the insight's `staleness` score increases:

```python
# On each ingestion scan, KGWriter updates staleness:
def update_tribal_staleness(self, changed_files: list[str], commit_sha: str):
    # Find insights whose applies_to matches any changed file's FQN
    # Increase staleness proportional to how central the change is
    ...
```

Highly stale insights (staleness > 0.7) are shown with a warning indicator in the console and are excluded from module file headers.

---

## Insight quality guide

| ✅ Good insight | ❌ Not useful |
|----------------|--------------|
| "The `wire_edges` 90s timeout prevents Neo4j lock — don't remove it" | "KGWriter writes to Neo4j" |
| "Route `/classes/summarise` must be registered BEFORE `/classes/{fqn:path}`" | "There are routes in this module" |
| "Ollama URL must be `host.docker.internal:11434` not `localhost`" | "Ollama is used for summarisation" |
| "object_model.methods is richer than Method nodes — use it for agent index" | "There is an object_model field" |
| "`applies_to` stores dot-separated FQNs, module IDs use slash-separated — match both" | "FQNs are dot-separated" |

**The test:** Would a senior engineer who already knows the codebase be surprised by this fact? If yes, capture it. If it's just what the code obviously does, skip it.

---

## Confidence levels

| Confidence | When to use |
|------------|-------------|
| `1.0` | Verified — you tested it, it's definitely true |
| `0.9` | High confidence — you understand why it works this way |
| `0.7` | Reasonably confident — observed behavior, not fully verified |
| `0.5` | Uncertain — hypothesis worth flagging, may be wrong |

Only insights with confidence ≥ 0.7 appear in module files. Lower-confidence insights are stored but not surfaced prominently.

---

## The compounding value

The value of insights is superlinear with session count. Each session that captures 3–5 good insights means the next session:
- Spends less time diagnosing the same non-obvious behavior
- Avoids the same mistakes
- Has context that would otherwise require hours of reading code to reconstruct

After 20 sessions on a module, the insights file for that module is itself a complete informal specification of how the module actually behaves in production — the kind of knowledge that normally takes months to accumulate.

**Call `capture_insight` at the end of every session. It is the most important thing you can do for future agents.**
