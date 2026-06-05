# Screen & Page Catalog — codeKG
_Generated 2026-06-05 20:15 UTC_

Complete map of every user-facing page and API endpoint.
Covers URL patterns, templates, navigation links, downstream calls, and data access.
Read this before adding, renaming, or linking pages.

## Technology stack

| Concern | Detail |
|---------|--------|
| **Framework** | FastAPI (Python) |
| **Templating** | Jinja2 — server-side rendered HTML, no JS framework |
| **Styling** | Inline `<style>` blocks per template — CSS custom properties from base.html :root |
| **Fonts** | Inter (UI), JetBrains Mono (code/numbers) via Google Fonts |
| **Nav** | Sticky top nav defined in base.html; all pages extend base.html via `{% extends %}` |
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
| Insights | `/insights` | path starts with `/insights` |
| Telemetry | `/telemetry` | path starts with `/telemetry` |
| Agent Indexing | `/agent-index` | path starts with `/agent-index` |
| Health | `/system-health` | path starts with `/system-health` |

## Pages (HTML responses)

_27 page endpoint(s) detected._

### Service: `console`

#### `GET /`
**Template:** `dashboard.html`  **Route file:** `services/console/routes/dashboard.py`
**Description:** Dashboard — repo overview, class counts, KG stats, token savings summary

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `repo_stats`, `gc`, `recent_events`, `token_savings`, `tk_total`, `tk_by_repo`

**Links to:** `/hygiene/{{ r.repo_id }}`, `/insights`, `/policies/{{ ev.policy_id }}`, `/repos`, `/repos/{{ ev.repo_id }}`, `/repos/{{ r.repo_id }}`

**Data access:** Neo4j (via `run_query`)

#### `GET /agent-index`
**Template:** `agent_index_overview.html`  **Route file:** `services/console/routes/agent_index.py`
**Description:** Agent Index — browse, regenerate, and publish the .codekg/ index files

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `files`, `standard_grouped`, `module_files`, `modules`, `has_files`

**Linked from:** `/agent-index/file/{file_key:path}`

**Links to:** `/agent-index/file/{{ f.file_key }}`, `/agent-index/file/{{ mod_key }}`

**Data access:** Neo4j (via `run_query`)

#### `GET /agent-index/file/{file_key:path}`
**Template:** `agent_index_file.html`  **Route file:** `services/console/routes/agent_index.py`
**Description:** Agent index file viewer — rendered content of one .codekg/ index file

**Parameters:** `file_key: str`

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `file`, `file_key`, `content_html`

**Linked from:** `/agent-index`

**Links to:** `/agent-index`

**Data access:** SQLite (direct connection)

#### `GET /ask`
**Template:** `ask.html`  **Route file:** `services/console/routes/ask.py`
**Description:** Ask — natural language Q&A over the knowledge graph using Claude

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `result`

**Linked from:** `/ask`

**Form actions (POST):** `/ask`

#### `POST /ask`
**Template:** `ask.html`  **Route file:** `services/console/routes/ask.py`
**Description:** Ask — natural language Q&A over the knowledge graph using Claude

**Parameters:** `question: str` = `Form(...`

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `question`, `repo_id`, `result`

**Linked from:** `/ask`

**Form actions (POST):** `/ask`

**Calls API (`http://api:8000`):**
  - `/answer`

#### `GET /audit`
**Template:** `audit.html`  **Route file:** `services/console/routes/audit_log.py`
**Description:** LLM Audit — log of every Claude API call: tokens, cost, cache rate, latency

**Parameters:** `source: str` = `""`, `limit: int` = `200`, `hours: int` = `24`

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `calls`, `stats`, `source_filter`, `limit`, `hours`

**Links to:** `/audit`

#### `GET /classes`
**Template:** `classes.html`  **Route file:** `services/console/routes/classes.py`
**Description:** Class browser — searchable/sortable class list with hygiene grade and blast radius

**Parameters:** `q: str` = `""`, `role: str` = `""`, `repo_id: str` = `""`, `sort: str` = `"coupling"`, `has_summary: str` = `"false"`, `page: int` = `1`

**Template context:** `effective_repo (via _template_ctx)`, `current_path (via _template_ctx)`, `classes`, `total`, `page`, `pages`, `page_size`, `q`, `role`, `repo_id`, `sort`, `has_summary`, `summary_total`, `class_total`, `roles`, `repos`

**Linked from:** `/classes/summarise/{job_id}`, `/classes/{fqn:path}`, `/hygiene/{repo_id:path}`, `/modules/{module_id:path}`

**Links to:** `/classes`, `/modules/{{ cls.module_id }}`

**Form actions (POST):** `/classes/summarise`

**Data access:** Neo4j (via `run_query`)

#### `POST /classes/summarise`
**Template:** `—`  **Route file:** `services/console/routes/classes.py`
**Description:** /classes/summarise

**Parameters:** `repo_id: str` = `Form(...`

**Linked from:** `/classes`

#### `GET /classes/summarise/{job_id}`
**Template:** `summarise_progress.html`  **Route file:** `services/console/routes/classes.py`
**Description:** Summarise Progress page

**Parameters:** `job_id: str`

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `job_id`, `status`, `done`, `total`, `log`

**Linked from:** `/classes`

**Links to:** `/classes`, `/classes{% if request.query_params.get(`

#### `GET /classes/{fqn:path}`
**Template:** `class_detail.html`  **Route file:** `services/console/routes/classes.py`
**Description:** Class detail — full method signatures, javadoc, summary, policy violations

**Parameters:** `fqn: str`

**Linked from:** `/classes`, `/classes/summarise/{job_id}`, `/hygiene/{repo_id:path}`, `/modules/{module_id:path}`

**Links to:** `/classes`, `/classes/{{ d.fqn }}`, `/classes/{{ dep.fqn }}`, `/classes/{{ e.fqn }}`, `/classes/{{ step.fqn }}`, `/modules/{{ om.module_id }}`

**Data access:** Neo4j (via `run_query`)

#### `GET /hygiene`
**Template:** `hygiene_overview.html`  **Route file:** `services/console/routes/hygiene.py`
**Description:** Hygiene overview — per-repo grade distribution and worst offenders

**Template context:** `effective_repo (via _template_ctx)`, `current_path (via _template_ctx)`, `repos`

**Linked from:** `/`, `/hygiene/{repo_id:path}`, `/hygiene/{repo_id}/refactor`

**Links to:** `/hygiene/{{ r.repo_id }}`

**Data access:** Neo4j (via `run_query`)

#### `GET /hygiene/{repo_id:path}`
**Template:** `hygiene_detail.html`  **Route file:** `services/console/routes/hygiene.py`
**Description:** Hygiene detail — per-class grades, scores, and method counts for one repo

**Parameters:** `repo_id: str`

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `repo_id`, `repo_score`, `classes`, `stats`

**Linked from:** `/`, `/hygiene`, `/hygiene/{repo_id}/refactor`

**Links to:** `/classes/{{ c.fqn }}`, `/hygiene`, `/hygiene/{{ repo_id }}/refactor`, `/modules/{{ c.module_id }}`

**Data access:** Neo4j (via `run_query`)

#### `GET /hygiene/{repo_id}/refactor`
**Template:** `hygiene_refactor.html`  **Route file:** `services/console/routes/hygiene.py`
**Description:** Hygiene Refactor page

**Parameters:** `repo_id: str`

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `repo_id`, `classes`

**Linked from:** `/`, `/hygiene`, `/hygiene/{repo_id:path}`

**Links to:** `/hygiene/{{ repo_id }}`

**Data access:** Neo4j (via `run_query`)

#### `GET /insights`
**Template:** `insights.html`  **Route file:** `services/console/routes/insights.py`
**Description:** Insights — non-obvious facts captured from coding sessions

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `sections`, `total`, `include_hidden`

**Linked from:** `/`

**Links to:** `/insights`

#### `GET /mcp-audit`
**Template:** `mcp_audit.html`  **Route file:** `services/console/routes/mcp_audit.py`
**Description:** MCP Audit — log of every MCP tool call from Claude Code sessions

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`

#### `GET /modules`
**Template:** `modules.html`  **Route file:** `services/console/routes/modules.py`
**Description:** Module list — all logical modules for the selected repo with class counts

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `modules`, `module_tree`, `edges`

**Linked from:** `/classes`, `/classes/{fqn:path}`, `/hygiene/{repo_id:path}`, `/modules/{module_id:path}`, `/repos/{repo_id:path}`

**Form actions (POST):** `/modules`

**Data access:** Neo4j (via `run_query`)

#### `GET /modules/{module_id:path}`
**Template:** `module_detail.html`  **Route file:** `services/console/routes/modules.py`
**Description:** Module detail — classes, methods, dependencies, insights for one module

**Parameters:** `module_id: str`

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `mod`, `module_id`, `stat`

**Linked from:** `/classes`, `/classes/{fqn:path}`, `/hygiene/{repo_id:path}`, `/modules`, `/repos/{repo_id:path}`

**Links to:** `/classes/{{ c.fqn }}`, `/modules`, `/modules/{{ d.dep_module }}`, `/repos/{{ mod.repo_id }}`

**Data access:** Neo4j (via `run_query`)

#### `GET /pattern-catalog`
**Template:** `pattern_catalog.html`  **Route file:** `services/console/routes/patterns.py`
**Description:** Pattern catalog — manage which patterns are active and their config

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `patterns`, `patterns_json`

**Linked from:** `/patterns`

**Links to:** `/patterns`

#### `GET /patterns`
**Template:** `patterns.html`  **Route file:** `services/console/routes/patterns.py`
**Description:** Pattern detector — run detection and view results for the selected repo

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `repo_id`, `results`

**Linked from:** `/pattern-catalog`, `/patterns`

**Links to:** `/pattern-catalog`

**Form actions (POST):** `/patterns`

#### `POST /patterns`
**Template:** `patterns.html`  **Route file:** `services/console/routes/patterns.py`
**Description:** Pattern detector — run detection and view results for the selected repo

**Parameters:** `repo_id: str` = `Form(""`

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `repo_id`, `results`

**Linked from:** `/pattern-catalog`, `/patterns`

**Links to:** `/pattern-catalog`

**Form actions (POST):** `/patterns`

#### `GET /policies`
**Template:** `policies.html`  **Route file:** `services/console/routes/policies.py`
**Description:** Policy list — active architectural policies with severity and violation counts

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `policies`, `modules`

**Linked from:** `/`, `/policies/{policy_id}`, `/repos/{repo_id:path}`

**Links to:** `/policies/{{ pol.policy_id }}`

**Form actions (POST):** `/policies`, `/policies/{{ pol.policy_id }}/activate`

**Data access:** Neo4j (via `run_query`)

#### `GET /policies/{policy_id}`
**Template:** `policy_detail.html`  **Route file:** `services/console/routes/policies.py`
**Description:** Policy detail — full policy definition, targets, and current violations

**Parameters:** `policy_id: str`

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `policy`, `violations`, `violations_run`

**Linked from:** `/`, `/policies`, `/repos/{repo_id:path}`

**Form actions (POST):** `/policies/{{ policy.policy_id }}/activate`, `/policies/{{ policy.policy_id }}/run`

**Data access:** Neo4j (via `run_query`)

#### `GET /repos`
**Template:** `repos.html`  **Route file:** `services/console/routes/repos.py`
**Description:** Repository list — registered repos with scan status and last commit

**Template context:** `effective_repo (via _template_ctx)`, `current_path (via _template_ctx)`, `repos`, `repos_path`

**Linked from:** `/`, `/modules/{module_id:path}`, `/repos/{repo_id:path}`

**Links to:** `/repos/{{ r.repo_id }}`

**Form actions (POST):** `/repos`, `/repos/{{ r.repo_id }}/remove`, `/repos/{{ r.repo_id }}/scan`

#### `GET /repos/{repo_id:path}`
**Template:** `repo_detail.html`  **Route file:** `services/console/routes/repos.py`
**Description:** Repository detail — scan history, module breakdown, quick-scan trigger

**Parameters:** `repo_id: str`

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `repo_id`, `repo_path`, `git`, `kg`, `provenance`, `stats`, `in_registry`, `scanning`, `api_url`

**Linked from:** `/`, `/modules/{module_id:path}`, `/repos`

**Links to:** `/modules`, `/policies`, `/repos`

**Form actions (POST):** `/repos/{{ repo_id }}/remove`, `/repos/{{ repo_id }}/scan`

**Data access:** Neo4j (via `run_query`)

#### `GET /system-health`
**Template:** `system_health.html`  **Route file:** `services/console/routes/system_health.py`
**Description:** System health — service status, DB connectivity, scan log summary

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`

#### `GET /telemetry`
**Template:** `telemetry.html`  **Route file:** `services/console/routes/telemetry.py`
**Description:** Telemetry — Claude Code session list with token counts and cache hit rates

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `sessions`

**Linked from:** `/telemetry/{session_id}`

**Links to:** `/telemetry/{{ s.session_id }}`

**Calls API (`http://api:8000`):**
  - `/telemetry/sessions`

#### `GET /telemetry/{session_id}`
**Template:** `telemetry_detail.html`  **Route file:** `services/console/routes/telemetry.py`
**Description:** Telemetry detail — per-turn tool calls, token breakdown, CodeKG savings, query plan

**Parameters:** `session_id: str`

**Template context:** `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `detail`, `query_plan`

**Linked from:** `/telemetry`

**Links to:** `/telemetry`

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
| `POST` | `/api/insights/analyse` | `services/console/routes/insights.py` | — |
| `POST` | `/api/insights/apply-finding` | `services/console/routes/insights.py` | — |
| `PATCH` | `/api/insights/{tk_id}` | `services/console/routes/insights.py` | — |
| `DELETE` | `/api/insights/{tk_id}` | `services/console/routes/insights.py` | — |
| `GET` | `/api/mcp-audit` | `services/console/routes/mcp_audit.py` | — |
| `GET` | `/api/mcp-audit/call/{call_id}` | `services/console/routes/mcp_audit.py` | SQLite |
| `GET` | `/api/mcp-audit/sessions/analysed` | `services/console/routes/mcp_audit.py` | — |
| `GET` | `/api/repos/{repo_id:path}/scan-status` | `services/console/routes/repos.py` | — |
| `GET` | `/api/system-health` | `services/console/routes/system_health.py` | SQLite |
| `POST` | `/api/system-health/cancel-scan` | `services/console/routes/system_health.py` | — |
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