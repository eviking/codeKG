# Insights — services/console
_Generated 2026-06-04 16:25 UTC_

Non-obvious facts discovered from previous coding sessions.
Treat as strong hints from engineers who have worked in this code.

## System-level insights

**`services.console`** (confidence 100%)
The console container does not hot-reload. All files (templates, routes, requirements.txt) are baked at build time via COPY in the Dockerfile. Any change to services/console/ requires: docker compose up -d --build console

**`services.console.routes.classes.start_summarise`** (confidence 100%)
Ollama runs on the Mac host, not inside Docker. From any container the correct URL is http://host.docker.internal:11434 — never localhost:11434 which resolves to the container loopback. The console UI and summarise_classes.py default both use host.docker.internal.

**`services.console`** (confidence 100%)
The console UI uses CSS custom properties defined in base.html :root (--bg, --surface, --primary, --success, --danger etc). All page templates must use these tokens — raw hex values in a template are a design bug. There is no external CSS file or build pipeline; all styles are inline in HTML templates.

**`services.console`** (confidence 100%)
The Stop hook is the correct event for enforcing submit_session_telemetry. It fires when Claude finishes a response turn and can block with a decision:block + reason that gets injected back into model context, forcing the model to complete the missing telemetry call.

**`services.console`** (confidence 100%)
Always use the turn_id from the FIRST codeKG opener call in a turn, not a later one. The protocol says: save the turn_id from the first opener and use that for submit_session_telemetry. Using a turn_id from a second call in the same turn orphans the first call from the telemetry record.

**`services.console`** (confidence 100%)
Hook scripts use relative paths (python3 .claude/hooks/require_codekg.py) rather than absolute paths so they work for any engineer who clones the repo, regardless of where it lives on their machine. Absolute paths only work for the original developer.

**`services.console`** (confidence 100%)
The registered repos registry lives at ${REPOS_PATH}/repos.json on the host (./repos/repos.json by default). The API /repos endpoint returns repo_id and path but the path field is null — the actual paths are only in the flat JSON file, not stored in Neo4j.

**`services.console`** (confidence 98%)
All styling in this app is inline in each HTML template — there is no shared CSS file or static asset pipeline. Every template has its own <style> block. To make global design changes, you must either update base.html tokens or touch each template individually.

**`services.console`** (confidence 95%)
The PreToolUse hook fires on every tool call including Read/Write/Edit, but skill invocations (via the Skill tool) run in a sub-context whose tool calls do NOT appear as assistant tool_use blocks in the main session JSONL. This means a codeKG call made through a skill is invisible to the require_codekg.py hook, causing false blocks on subsequent Read/Write calls even though codeKG was consulted.

**`services.console.main`** (confidence 80%)
The base.html CSS already uses green (#16a34a) as --primary. The blue appearance likely comes from hardcoded #2563eb values in individual templates (patterns.html, class_detail.html, pattern_catalog.html) and --info (#0284c7) token, not from the global theme.

## Module-level insights

**`services.console.routes.classes`** (confidence 100%)
summarise_classes.py is NOT copied into any Docker container — it lives only in tools/ on the host. The console loads it at runtime via importlib from /host-home/Documents/projects/codeKG/tools/summarise_classes.py through the host-home mount. If that path is wrong or the mount is missing, the job errors immediately.

**`services.console.routes.classes`** (confidence 100%)
summarise_classes.py has a self-bootstrap block that creates a .venv and re-execs itself. When loaded via importlib from inside the console container it runs against the read-only host-home mount and crashes with exit status 1. Fix: strip the bootstrap block from the source string before exec()-ing it. All deps (neo4j, requests) must be pre-installed in the container image.

**`services.console.routes.classes`** (confidence 100%)
FastAPI route registration order is critical when a path-parameter catch-all exists. GET /classes/{fqn:path} greedily matches everything under /classes/. More-specific routes like /classes/summarise/{job_id} MUST be registered before the catch-all or they are swallowed. Symptom: 404 with body: Class summarise/<id> not found.

**`services.console`** (confidence 100%)
requests is not installed in the console container by default (FastAPI uses httpx). summarise_classes.py imports requests to call Ollama — it must be listed in services/console/requirements.txt or the job fails immediately with: No module named requests.

**`services.console.routes.classes.start_summarise`** (confidence 100%)
summarise_classes.py skips TEST and GENERATED role classes by default (_SKIP_ROLES). For large repos like ElasticSearch this is ~16k classes. If resume=True and all remaining unsummarised classes are TEST/GENERATED, the job exits with 0 written — looks like failure but is correct. The console shows a Nothing to summarise warning. Use include_skip_roles=True or force=True to override.

**`services.console.routes.mcp_audit`** (confidence 100%)
The MCP audit page had two setInterval calls (10s for calls, 30s for session analysis) that caused constant background polling. Removing them and replacing with a manual Refresh button is the right UX for an audit trail — you want a stable view, not one that jumps while you're reading it.

**`services.console.main`** (confidence 100%)
Templates are baked into Docker images at build time — there is no volume mount for the console or api service templates. Any template change requires docker compose up --build to take effect. This is a common source of confusion when edits appear not to apply.

**`services.console.main`** (confidence 100%)
Jinja2 set inside an if block does not escape that block's scope within the same loop iteration for outer-scope variables. Always set loop-scoped variables (like turn_idx) unconditionally at the top of the for block, not inside a nested if — otherwise the variable is unset or stale for turns where the if condition is false.

**`services.console.routes.mcp_audit`** (confidence 95%)
renderCalls and loadSessionAnalysis run concurrently — analysis data (_analysedSessions) is not available when calls first render, so a second renderCalls call after analysis loads is needed to fill in turn prompts.

**`services.console.main`** (confidence 95%)
The base.html template defines the navigation, layout shell, and all shared component styles. Page templates extend it and add their own <style> blocks. CSS custom properties (--bg, --surface, --primary etc.) set in base.html :root are the right abstraction point for theming — all page styles should reference these vars, not raw hex values.

**`services.console.routes.mcp_audit`** (confidence 90%)
The MCP audit template already had '(24h)' on the Calls label but not on the other 6 stat boxes — a reader scanning the page would not realise all stats are 24h-scoped, making the error count appear to be all-time.

**`services.console.routes.dashboard`** (confidence 90%)
The dashboard summary chips section in dashboard.html is the right place to surface cross-cutting KG metrics — it already contains repo counts, policy counts, violations, and token savings chips all in one row. New system-wide metrics should be added here as conditional chips.

**`services.console.routes.classes`** (confidence 90%)
summarise_classes.py is a standalone CLI script in tools/ that is NOT copied into the console container (Dockerfile only copies services/console/ and shared/). To invoke it from the console it must be imported dynamically by path from the host-home mount (/host-home/Documents/projects/codeKG/tools/). It is self-bootstrapping and safe to re-exec via importlib.

## Method-level insights

**`services.console.llm_audit.aggregate_stats`** (confidence 100%)
aggregate_stats accepted a `days` parameter and computed a `cutoff` timestamp but never passed it to the SQL query — stats were always all-time regardless of the argument. Fixed by passing cutoff as a bound parameter in the WHERE clause.

**`services.console.routes.classes.classes_list`** (confidence 100%)
summary_total in classes_list() is now correctly scoped to effective_repo (fixed 2026-06-02). It uses: MATCH (c:Class) WHERE c.repo_id = $repo_id AND NOT c.kind IN ["module"] AND c.summary IS NOT NULL. A separate class_total query provides the denominator (total non-module classes for the repo). Previously it counted across ALL repos with no filter, inflating the progress bar. The filtered `total` variable must never be used as the denominator — it reflects the current search filter, not the full repo size.

**`services.console.routes.mcp_audit._query`** (confidence 95%)
The _query() stats and tool_breakdown queries in mcp_audit.py are both hard-filtered to the last 24 hours — errors older than that are silently excluded from the summary stats, which can make the system appear healthier than it is.
