# Screen & Page Catalog — codeKG
_Generated 2026-06-04 20:39 UTC_

Complete map of every user-facing page and API endpoint.
Covers URL patterns, templates, navigation links, downstream calls, and data access.
Read this before adding, renaming, or linking pages.

## Technology stack

| Concern | Detail |
|---------|--------|
| **Framework** | FastAPI (Python) |
| **Templating** | Jinja2 — server-side rendered HTML, no JS framework |
| **Styling** | Inline <style> blocks per template — CSS custom properties from base.html :root |
| **Fonts** | Inter (UI), JetBrains Mono (code/numbers) via Google Fonts |
| **Nav** | Sticky top nav defined in base.html; all pages extend base.html via {% extends %} |
| **Forms** | Standard HTML forms with method=GET/POST — no AJAX except where noted |
| **Http Client** | httpx.Client (sync) for console → API calls; all calls to http://api:8000 |
| **Hot Reload** | None — templates baked into Docker image at build time; changes require docker compose up --build console |
| **Css Tokens** | --bg, --surface, --surface-2, --border, --text, --text-2, --text-3, --primary, --success, --warning, --danger, --info, --purple, --radius, --radius-lg, --shadow |

## Navigation graph

_Top-level nav links defined in `base.html` — all pages extend this template._

| Label | URL | Active when |
|-------|-----|-------------|
| Dashboard | `/` | path == `/` |
| Repositories | `/repos` | path starts with `/repos` |
| Modules | `/modules` | path starts with `/modules` |
| Classes | `/classes` | path starts with `/classes` |
| Patterns | `/patterns` | path starts with `/pattern` |
| Hygiene | `/hygiene` | path starts with `/hygiene` |
| Policies | `/policies` | path starts with `/policies` |
| Ask | `/ask` | path starts with `/ask` |
| LLM Audit | `/audit` | path starts with `/audit` |
| MCP Audit | `/mcp-audit` | path starts with `/mcp-audit` |
| Insights | `/tribal-knowledge` | path starts with `/tribal-knowledge` |
| Telemetry | `/telemetry` | path starts with `/telemetry` |
| Agent Indexing | `/agent-index` | path starts with `/agent-index` |
| Health | `/system-health` | path starts with `/system-health` |

## Pages (HTML responses)

_26 page endpoint(s) detected._

### Service: `console`

#### `GET /`
**Template:** `dashboard.html`  **Route file:** `services/console/routes/dashboard.py`
**Description:** Dashboard — repo overview, class counts, KG stats, token savings summary

**Links to:** `/hygiene/{{ r.repo_id }}`, `/policies/{{ ev.policy_id }}`, `/repos`, `/repos/{{ ev.repo_id }}`, `/repos/{{ r.repo_id }}`, `/tribal-knowledge`

**Data access:** Neo4j (via `run_query`)

#### `GET /agent-index`
**Template:** `agent_index_overview.html`  **Route file:** `services/console/routes/agent_index.py`
**Description:** Agent Index — browse, regenerate, and publish the .codekg/ index files

**Linked from:** `/agent-index/file/{file_key:path}`

**Links to:** `/agent-index/file/{{ f.file_key }}`, `/agent-index/file/{{ mod_key }}`

**Data access:** Neo4j (via `run_query`)

#### `GET /agent-index/file/{file_key:path}`
**Template:** `agent_index_file.html`  **Route file:** `services/console/routes/agent_index.py`
**Description:** Agent index file viewer — rendered content of one .codekg/ index file

**Linked from:** `/agent-index`

**Links to:** `/agent-index`

**Data access:** SQLite (direct connection)

#### `GET /ask`
**Template:** `ask.html`  **Route file:** `services/console/routes/ask.py`
**Description:** Ask — natural language Q&A over the knowledge graph using Claude

**Linked from:** `/ask`

**Form actions (POST):** `/ask`

#### `POST /ask`
**Template:** `ask.html`  **Route file:** `services/console/routes/ask.py`
**Description:** Ask — natural language Q&A over the knowledge graph using Claude

**Linked from:** `/ask`

**Form actions (POST):** `/ask`

**Calls API (`http://api:8000`):**
  - `/answer`

#### `GET /audit`
**Template:** `audit.html`  **Route file:** `services/console/routes/audit_log.py`
**Description:** LLM Audit — log of every Claude API call: tokens, cost, cache rate, latency

**Links to:** `/audit`

#### `GET /classes`
**Template:** `classes.html`  **Route file:** `services/console/routes/classes.py`
**Description:** Class browser — searchable/sortable class list with hygiene grade and blast radius

**Linked from:** `/classes/summarise/{job_id}`, `/classes/{fqn:path}`, `/hygiene/{repo_id:path}`, `/modules/{module_id:path}`

**Links to:** `/classes`, `/modules/{{ cls.module_id }}`

**Form actions (POST):** `/classes/summarise`

**Data access:** Neo4j (via `run_query`)

#### `POST /classes/summarise`
**Template:** `—`  **Route file:** `services/console/routes/classes.py`
**Description:** /classes/summarise

**Linked from:** `/classes`

#### `GET /classes/summarise/{job_id}`
**Template:** `summarise_progress.html`  **Route file:** `services/console/routes/classes.py`
**Description:** Summarise Progress page

**Linked from:** `/classes`

**Links to:** `/classes`, `/classes{% if request.query_params.get(`

#### `GET /classes/{fqn:path}`
**Template:** `class_detail.html`  **Route file:** `services/console/routes/classes.py`
**Description:** Class detail — full method signatures, javadoc, summary, policy violations

**Linked from:** `/classes`, `/classes/summarise/{job_id}`, `/hygiene/{repo_id:path}`, `/modules/{module_id:path}`

**Links to:** `/classes`, `/classes/{{ d.fqn }}`, `/classes/{{ dep.fqn }}`, `/classes/{{ e.fqn }}`, `/classes/{{ step.fqn }}`, `/modules/{{ om.module_id }}`

**Data access:** Neo4j (via `run_query`)

#### `GET /hygiene`
**Template:** `hygiene_overview.html`  **Route file:** `services/console/routes/hygiene.py`
**Description:** Hygiene overview — per-repo grade distribution and worst offenders

**Linked from:** `/`, `/hygiene/{repo_id:path}`

**Links to:** `/hygiene/{{ r.repo_id }}`

**Data access:** Neo4j (via `run_query`)

#### `GET /hygiene/{repo_id:path}`
**Template:** `hygiene_detail.html`  **Route file:** `services/console/routes/hygiene.py`
**Description:** Hygiene detail — per-class grades, scores, and method counts for one repo

**Linked from:** `/`, `/hygiene`

**Links to:** `/classes/{{ c.fqn }}`, `/hygiene`, `/modules/{{ c.module_id }}`

**Data access:** Neo4j (via `run_query`)

#### `GET /mcp-audit`
**Template:** `mcp_audit.html`  **Route file:** `services/console/routes/mcp_audit.py`
**Description:** MCP Audit — log of every MCP tool call from Claude Code sessions

#### `GET /modules`
**Template:** `modules.html`  **Route file:** `services/console/routes/modules.py`
**Description:** Module list — all logical modules for the selected repo with class counts

**Linked from:** `/classes`, `/classes/{fqn:path}`, `/hygiene/{repo_id:path}`, `/modules/{module_id:path}`, `/repos/{repo_id:path}`

**Form actions (POST):** `/modules`

**Data access:** Neo4j (via `run_query`)

#### `GET /modules/{module_id:path}`
**Template:** `module_detail.html`  **Route file:** `services/console/routes/modules.py`
**Description:** Module detail — classes, methods, dependencies, insights for one module

**Linked from:** `/classes`, `/classes/{fqn:path}`, `/hygiene/{repo_id:path}`, `/modules`, `/repos/{repo_id:path}`

**Links to:** `/classes/{{ c.fqn }}`, `/modules`, `/modules/{{ d.dep_module }}`, `/repos/{{ mod.repo_id }}`

**Data access:** Neo4j (via `run_query`)

#### `GET /pattern-catalog`
**Template:** `pattern_catalog.html`  **Route file:** `services/console/routes/patterns.py`
**Description:** Pattern catalog — manage which patterns are active and their config

**Linked from:** `/patterns`

**Links to:** `/patterns`

#### `GET /patterns`
**Template:** `patterns.html`  **Route file:** `services/console/routes/patterns.py`
**Description:** Pattern detector — run detection and view results for the selected repo

**Linked from:** `/pattern-catalog`, `/patterns`

**Links to:** `/pattern-catalog`

**Form actions (POST):** `/patterns`

#### `POST /patterns`
**Template:** `patterns.html`  **Route file:** `services/console/routes/patterns.py`
**Description:** Pattern detector — run detection and view results for the selected repo

**Linked from:** `/pattern-catalog`, `/patterns`

**Links to:** `/pattern-catalog`

**Form actions (POST):** `/patterns`

#### `GET /policies`
**Template:** `policies.html`  **Route file:** `services/console/routes/policies.py`
**Description:** Policy list — active architectural policies with severity and violation counts

**Linked from:** `/`, `/policies/{policy_id}`, `/repos/{repo_id:path}`

**Links to:** `/policies/{{ pol.policy_id }}`

**Form actions (POST):** `/policies`, `/policies/{{ pol.policy_id }}/activate`

**Data access:** Neo4j (via `run_query`)

#### `GET /policies/{policy_id}`
**Template:** `policy_detail.html`  **Route file:** `services/console/routes/policies.py`
**Description:** Policy detail — full policy definition, targets, and current violations

**Linked from:** `/`, `/policies`, `/repos/{repo_id:path}`

**Form actions (POST):** `/policies/{{ policy.policy_id }}/activate`, `/policies/{{ policy.policy_id }}/run`

**Data access:** Neo4j (via `run_query`)

#### `GET /repos`
**Template:** `repos.html`  **Route file:** `services/console/routes/repos.py`
**Description:** Repository list — registered repos with scan status and last commit

**Linked from:** `/`, `/modules/{module_id:path}`, `/repos/{repo_id:path}`

**Links to:** `/repos/{{ r.repo_id }}`

**Form actions (POST):** `/repos`, `/repos/{{ r.repo_id }}/remove`, `/repos/{{ r.repo_id }}/scan`

#### `GET /repos/{repo_id:path}`
**Template:** `repo_detail.html`  **Route file:** `services/console/routes/repos.py`
**Description:** Repository detail — scan history, module breakdown, quick-scan trigger

**Linked from:** `/`, `/modules/{module_id:path}`, `/repos`

**Links to:** `/modules`, `/policies`, `/repos`

**Form actions (POST):** `/repos/{{ repo_id }}/remove`, `/repos/{{ repo_id }}/scan`

**Data access:** Neo4j (via `run_query`)

#### `GET /system-health`
**Template:** `system_health.html`  **Route file:** `services/console/routes/system_health.py`
**Description:** System health — service status, DB connectivity, scan log summary

#### `GET /telemetry`
**Template:** `telemetry.html`  **Route file:** `services/console/routes/telemetry.py`
**Description:** Telemetry — Claude Code session list with token counts and cache hit rates

**Linked from:** `/telemetry/{session_id}`

**Links to:** `/telemetry/{{ s.session_id }}`

**Calls API (`http://api:8000`):**
  - `/telemetry/sessions`

#### `GET /telemetry/{session_id}`
**Template:** `telemetry_detail.html`  **Route file:** `services/console/routes/telemetry.py`
**Description:** Telemetry detail — per-turn tool calls, token breakdown, CodeKG savings, query plan

**Linked from:** `/telemetry`

**Links to:** `/telemetry`

#### `GET /tribal-knowledge`
**Template:** `tribal_knowledge.html`  **Route file:** `services/console/routes/tribal_knowledge.py`
**Description:** Insights (tribal knowledge) — non-obvious facts captured from coding sessions

**Linked from:** `/`

**Links to:** `/tribal-knowledge`

## API endpoints (non-HTML)

_29 JSON/plain-text endpoint(s) — consumed by the console UI, MCP server, or CI._

| Method | URL | Route file | Notes |
|--------|-----|------------|-------|
| `POST` | `/api/agent-index/manual-additions` | `services/console/routes/agent_index.py` | — |
| `POST` | `/api/agent-index/publish` | `services/console/routes/agent_index.py` | — |
| `POST` | `/api/agent-index/regen` | `services/console/routes/agent_index.py` | — |
| `POST` | `/api/agent-index/regen-all` | `services/console/routes/agent_index.py` | — |
| `POST` | `/api/agent-index/toggle-hidden` | `services/console/routes/agent_index.py` | — |
| `POST` | `/api/ask` | `services/console/routes/ask.py` | → api: /answer |
| `GET` | `/api/mcp-audit` | `services/console/routes/mcp_audit.py` | — |
| `GET` | `/api/mcp-audit/call/{call_id}` | `services/console/routes/mcp_audit.py` | SQLite |
| `GET` | `/api/mcp-audit/sessions/analysed` | `services/console/routes/mcp_audit.py` | — |
| `GET` | `/api/repos/{repo_id:path}/scan-status` | `services/console/routes/repos.py` | — |
| `GET` | `/api/system-health` | `services/console/routes/system_health.py` | SQLite |
| `POST` | `/api/system-health/cancel-scan` | `services/console/routes/system_health.py` | — |
| `POST` | `/api/tribal-knowledge/analyse` | `services/console/routes/tribal_knowledge.py` | — |
| `POST` | `/api/tribal-knowledge/apply-finding` | `services/console/routes/tribal_knowledge.py` | — |
| `PATCH` | `/api/tribal-knowledge/{tk_id}` | `services/console/routes/tribal_knowledge.py` | — |
| `DELETE` | `/api/tribal-knowledge/{tk_id}` | `services/console/routes/tribal_knowledge.py` | — |
| `GET` | `/classes/summarise/{job_id}/stream` | `services/console/routes/classes.py` | — |
| `POST` | `/modules` | `services/console/routes/modules.py` | — |
| `PATCH` | `/pattern-catalog/{pattern_id}` | `services/console/routes/patterns.py` | — |
| `POST` | `/pattern-catalog/{pattern_id}/toggle` | `services/console/routes/patterns.py` | — |
| `POST` | `/policies` | `services/console/routes/policies.py` | — |
| `POST` | `/policies/{policy_id}/activate` | `services/console/routes/policies.py` | Neo4j |
| `POST` | `/policies/{policy_id}/run` | `services/console/routes/policies.py` | Neo4j |
| `POST` | `/repos` | `services/console/routes/repos.py` | — |
| `POST` | `/repos/clone` | `services/console/routes/repos.py` | — |
| `GET` | `/repos/clone/status/{job_id}` | `services/console/routes/repos.py` | — |
| `POST` | `/repos/{repo_id:path}/remove` | `services/console/routes/repos.py` | — |
| `POST` | `/repos/{repo_id:path}/scan` | `services/console/routes/repos.py` | — |
| `POST` | `/repos/{repo_id:path}/scan/cancel` | `services/console/routes/repos.py` | — |

## Key patterns & conventions

- **URL parameters**: FastAPI path params use `{name}` or `{name:path}` (`:path` allows slashes)
- **Repo context**: selected repo tracked via `?repo_id=` query param, stored in session cookie `repo_id`
- **Template context**: every page receives `current_path`, `repos`, `effective_repo` via `_template_ctx()`
- **Error pages**: 404 and 500 errors rendered inline — no separate error templates
- **Console → API**: all cross-service calls use `httpx.Client` at `http://api:8000` (env: `API_URL`)
- **No hot reload**: any template or route change requires `docker compose up --build console`
- **CSS**: all styles inline per template — use `var(--token)` from base.html, never raw hex
- **Forms**: standard HTML `<form>` — POST actions re-render the same template or redirect
- **HTMX / JS**: minimal vanilla JS only (toggle visibility, expand rows) — no framework
- **Nav active state**: set via Jinja2 `{{ 'active' if condition }}` in base.html nav links