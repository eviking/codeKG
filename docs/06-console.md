# Console UI

> A FastAPI + Jinja2 web interface for browsing the knowledge graph, managing agent index files, monitoring MCP tool calls, and inspecting ingestion health — running at `http://localhost:8080`.

---

## Architecture

The console is a server-rendered web app. No frontend build step. No JavaScript framework. All styles are CSS custom properties defined inline in `base.html`. All templates are Jinja2.

```
services/console/
├── main.py              # FastAPI app, startup, middleware
├── deps.py              # Neo4j driver, run_query, template context helper
├── routes/
│   ├── dashboard.py     # GET /
│   ├── classes.py       # GET /classes, /classes/{fqn}
│   ├── modules.py       # GET /modules
│   ├── hygiene.py       # GET /hygiene
│   ├── agent_index.py   # GET /agent-index, POST /api/agent-index/*
│   ├── telemetry.py     # GET /telemetry, /telemetry/{session_id}
│   ├── mcp_audit.py     # GET /mcp-audit
│   ├── policies.py      # GET /policies
│   ├── insights.py      # GET /insights
│   ├── repos.py         # GET /repos, POST /repos (register)
│   ├── patterns.py      # GET /patterns (architectural patterns)
│   ├── config.py        # GET /config, POST /api/config (env/settings UI)
│   ├── ask.py           # POST /api/ask (natural language query proxy)
│   ├── audit_log.py     # GET /audit-log (LLM audit log)
│   └── system_health.py # GET /system-health, GET /api/system-health
├── templates/
│   ├── base.html        # shared layout, nav, CSS tokens
│   └── *.html           # one template per page
└── agent_index/
    ├── store.py         # thin shim re-exporting shared/agent_index/store.py
    └── generator.py     # display-only summary generator (not used for actual index generation)
```

> **The console does not hot-reload.** All templates and routes are baked into the Docker image at build time. Any change to `services/console/` requires `docker compose up -d --build console`.

---

## Design system

The console uses CSS custom properties defined in `base.html`:

```css
:root {
  --bg:         #0f1117;    /* page background */
  --surface:    #1a1d27;    /* card background */
  --surface-2:  #232636;    /* elevated surface */
  --border:     #2d3148;    /* borders */
  --border-2:   #3d4268;    /* stronger border */
  --text:       #e2e8f0;    /* primary text */
  --text-2:     #94a3b8;    /* secondary text */
  --text-3:     #64748b;    /* muted text */
  --primary:    #16a34a;    /* green — actions */
  --success:    #22c55e;    /* green — success states */
  --warning:    #f59e0b;    /* amber — warnings */
  --danger:     #ef4444;    /* red — destructive actions */
  --radius:     6px;
  --radius-lg:  10px;
  --shadow:     0 1px 3px rgba(0,0,0,.4);
}
```

**Rule:** All templates must use these tokens. Raw hex values in a template are a design bug. There is no external CSS file or build pipeline.

---

## The `_template_ctx` helper

Every route calls `_template_ctx(request)` to populate the shared template context:

```python
# deps.py
def _template_ctx(request: Request) -> dict:
    return {
        "current_path": request.url.path,
        "repos": load_repos(),              # all registered repos
        "selected_repo": get_selected_repo(request),  # from cookie
    }
```

The selected repo is stored in a cookie (`selected_repo`). Switching repos via the top-right dropdown sets this cookie and reloads the page. All data queries are scoped to `selected_repo`.

---

## Route reference

### Dashboard — `GET /`

```python
# What it shows:
repo_stats   = class count, method count, hygiene grade, last commit
gc           = global stats across all repos
recent_events = last 10 scan events
token_savings = estimated tokens saved by using pre-computed index vs live KG calls
tk_total     = total tribal knowledge entries
```

### Classes — `GET /classes`

Searchable, filterable table of all classes for the selected repo. Supports:
- Full-text search on class name and FQN
- Filter by `role` (CLASS, INTERFACE, ENUM, TEST, GENERATED)
- Sort by coupling, blast radius, LOC, hygiene grade
- Pagination (50 per page)
- Summarise button — triggers LLM summarisation job for unsummarised classes

```python
# Query:
MATCH (c:Class {repo_id: $repo_id})
WHERE NOT c.kind IN ['module']
  AND ($q = '' OR toLower(c.name) CONTAINS toLower($q))
  AND ($role = '' OR c.role = $role)
RETURN c
ORDER BY c.coupling DESC
SKIP $skip LIMIT 50
```

> **Route registration order matters.** `GET /classes/summarise/{job_id}` MUST be registered before `GET /classes/{fqn:path}` or the catch-all path parameter swallows it, producing a 404 with body "Class summarise/\<id\> not found".

### Class detail — `GET /classes/{fqn}`

Full detail for a single class: description, methods table, callers, callees, hygiene breakdown, insights, test coverage.

### Hygiene — `GET /hygiene/{repo_id}`

Per-class hygiene scorecard. Shows grade distribution (A–F), top offenders, and a refactor prioritisation view at `/hygiene/{repo_id}/refactor`.

```
Grade distribution for codeKG:
A (90-100): 12 classes
B (75-89):  45 classes
C (60-74):  14 classes
D (40-59):   4 classes
F (<40):     0 classes
```

### Agent Index — `GET /agent-index`

Management UI for the pre-computed agent index files. See [Agent Index System](./05-agent-index.md) for full details.

Sections:
1. **Publish bar** — one-click publish to repo with git commit
2. **Standard files** — card grid grouped by directory (architecture/, policies/, insights/)
3. **Per-module table** — status row per registered module

Status badges per file:
```html
<!-- status-current: green pill -->
<span class="status-badge status-current">current</span>

<!-- status-stale: amber pill, also shows "⚠ needs republish" in meta row -->
<span class="status-badge status-stale">stale</span>

<!-- status-empty: amber pill, 🈳 icon, excluded from publish -->
<span class="status-badge status-empty">empty</span>

<!-- status-hidden: grey pill, 🙈 icon, excluded from publish -->
<span class="status-badge status-hidden">hidden</span>
```

### Agent Index File detail — `GET /agent-index/file/{file_key}`

Preview of a single agent index file rendered as markdown using `marked.js` (CDN, v9).

```javascript
// Markdown rendering via CDN:
const _MD_RAW = {{ file.content | tojson }};  // embedded as JS string via tojson filter

function renderMarkdown() {
    const el = document.getElementById('md-preview');
    if (!el || typeof _MD_RAW === 'undefined') return;
    marked.use({ gfm: true, breaks: false });  // v9 API — NOT marked.setOptions()
    el.innerHTML = marked.parse(_MD_RAW);
}
```

Actions available:
- **Copy** — copies raw markdown to clipboard
- **Regenerate** — POSTs to `/api/agent-index/regen`, reloads after 1.2s
- **Hide / Show** — toggles `hidden` flag in `agent_index.db`
- **Manual additions** — text saved to `manual_additions` field, appended on publish

### Telemetry — `GET /telemetry`

List of all MCP sessions with agent type, duration, and total token cost.

```
Session list:
a3f9c1b2 | Claude Code | 2026-06-05 20:34 | 47 tool calls | 142K tokens
8b2d4e7f | Claude Code | 2026-06-04 15:20 | 23 tool calls | 89K tokens
```

### Telemetry detail — `GET /telemetry/{session_id}`

Full session timeline: every tool call, its target (FQN or file), token cost, and result.

The `codekg_target` column extracts the meaningful identifier from tool input:
```python
# Priority order for target extraction:
target = (inp.get('applies_to')      # capture_insight
       or inp.get('fqn')             # get_class, get_class_context
       or inp.get('class_name')
       or inp.get('module_id')
       or inp.get('repo_id')
       or inp.get('insight', '')[:80])
```

### MCP Audit — `GET /mcp-audit`

Raw log of all MCP tool calls across all sessions. Useful for debugging which tools the agent is calling and with what inputs.

### Insights — `GET /insights`

All captured `TribalKnowledge` entries, grouped by module area. Confidence-sorted within each group.

### System Health — `GET /system-health`

Shows:
- Neo4j connection status and node counts
- Docker container states (CPU, memory, network I/O per container)
- Active and recent ingestion scans with live pipeline progress
- LLM audit stats (last 24h: call count, cost, error rate by source)
- Pipeline stage progress tracker — shows each stage (parse → wire_edges → hygiene → CLAUDE.md → AGENTS.md) with running/done status

### Policies — `GET /policies`

List of active architectural policies with violator counts and Cypher constraints.

Policy detail at `/policies/{policy_id}` shows all current violators with their blast radius and grade.

---

## API proxying

The console doesn't write directly — it proxies through the API for all write operations:

```python
# services/console/routes/agent_index.py
_http = httpx.Client(base_url="http://api:8000", timeout=120.0)

def _api_post(path: str, body: dict) -> dict:
    r = _http.post(path, json=body)
    r.raise_for_status()
    return r.json()

@router.post("/api/agent-index/regen")
async def api_regen_file(request: Request):
    body = await request.json()
    return _api_post("/agent-index/regen", body)
```

This ensures:
- All writes go through a single authoritative service
- The console doesn't need write access to the repo filesystem
- Errors from the API are surfaced cleanly via HTTP status codes

---

## Summarisation jobs

Class summarisation runs as a background thread in the console container. It loads `tools/summarise_classes.py` from the host-home mount at runtime via `importlib`:

```python
# The tool lives at: /host-home/<path-to-codeKG>/tools/summarise_classes.py
# It is NOT copied into the container — it's loaded from the HOME_MOUNT at runtime

spec = importlib.util.spec_from_file_location("summarise_classes", tool_path)
mod = importlib.util.module_from_spec(spec)
exec(compiled_source, mod.__dict__)
```

> **Ollama runs on the Mac host, not in Docker.** The URL must be `http://host.docker.internal:11434`, never `localhost:11434`.

Jobs report progress via a `/classes/summarise/{job_id}` SSE stream shown in the UI.

---

## Adding a new page

```python
# 1. Create services/console/routes/my_page.py
router = APIRouter()

@router.get("/my-page", response_class=HTMLResponse)
async def my_page(request: Request):
    ctx = _template_ctx(request)
    repo_id = ctx["selected_repo"]
    data = run_query("MATCH ...", repo_id=repo_id) if repo_id else []
    return templates.TemplateResponse("my_page.html", {**ctx, "data": data})

# 2. Create services/console/templates/my_page.html
{% extends "base.html" %}
{% block title %}My Page{% endblock %}
{% block content %}
<style>
  /* Use CSS tokens: var(--bg), var(--surface), var(--primary), etc. */
  /* Never use raw hex values */
</style>
...
{% endblock %}

# 3. Register router in services/console/main.py
from routes.my_page import router as my_router
app.include_router(my_router)

# 4. Add nav link in base.html

# 5. Rebuild:
docker compose up -d --build console
```
