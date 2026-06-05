# All Insights — codeKG
_Generated 2026-06-05 20:14 UTC_

Non-obvious facts captured from previous coding sessions.
These are also inlined at the top of each module file.
**Total:** 50 insights

## `.claude.hooks.require_telemetry`

**[module]** _100% confidence_
input_tokens in the Anthropic API is incremental uncached-only tokens per assistant message, not total context. In a cached conversation it is literally 1-3 tokens. Total context cost = cache_read_tokens + input_tokens + cache_creation_tokens. The stop hook was taking max() across messages which silently discarded the real numbers.

**[module]** _100% confidence_
cache_read_input_tokens and cache_creation_input_tokens in the Anthropic transcript are cumulative high-water marks for the whole conversation, not per-message deltas. To get per-step token cost you must diff consecutive assistant messages: Δcache_read + Δcache_creation + output_tokens = step cost.

## `services.api.agent_index.generator`

**[module]** _100% confidence_
Module index files grew from ~40 lines (class table only) to 230-300 lines per module by pulling full method signatures, parameter types, return types, and LOC from object_model on each Class node. The object_model JSON blob contains a 'methods' array with name, return_type, parameters, and modifiers — this is richer than the separate Method nodes which lack a 'signature' property.

**[module]** _100% confidence_
When total repo LOC (sum of max end_line per file) is below 2500, the generator produces a combined.md with all modules inlined and CLAUDE.md directs agents to read only that one file. Above the threshold, separate per-module files are used. codeKG itself is at 7236 LOC so uses per-module mode.

**[module]** _100% confidence_
The insight query in generate_insights_module used CONTAINS $module_id where module_id is 'services/console' (slash-separated) but TribalKnowledge.applies_to stores dot-separated FQNs like 'services.console.main'. The fix is to also match against module_id.replace('/', '.') as module_dot. Both forms must be passed as separate Cypher parameters.

**[module]** _100% confidence_
The cross-module dependency query required BOTH source and target classes to belong to a Module node. Since shared/logging/codekg_logger.py is outside all modules, all imports resolved to zero rows. Fix: use OPTIONAL MATCH for the target module and fall back to the filename for display.

**[module]** _100% confidence_
Class-level "Used by" comes from blast_radius (array of dependent FQNs stored on each Class node). Module-level "Used by" comes from intra-repo IMPORTS edges. In this repo, blast_radius is only non-empty on codekg_logger (blast=8) in shared/ — all service module classes have blast=0 because the ingestion hasn't resolved deeper Python import chains beyond direct class imports.

**[system]** _100% confidence_
The repo registry stores paths as '/host-home/Documents/projects/codeKG' (uppercase K) but the container filesystem has it as '/host-home/Documents/projects/codekg' (lowercase). macOS is case-insensitive so host-side code works, but container-side code (Linux) gets FileNotFoundError. Always normalise the last path component to lowercase when checking isdir() in container code.

**[module]** _100% confidence_
Data store detection scans source files for known import/connection patterns (_DS_SIGNATURES). The .venv and site-packages directories must be explicitly excluded from the walk or the neo4j package files themselves trigger false positives for every service. Exclude dirs: __pycache__, .git, node_modules, .codekg, .venv, venv, .venv-test, site-packages.

**[module]** _100% confidence_
generate_screens_index requires repo_path (the on-disk repo root) just like generate_datastores_index — it walks the filesystem for route files and templates. It is registered in FILE_REGISTRY with generator=None and handled as a special case in _ai_regen_file alongside the datastores branch. If you add more filesystem-dependent generators, follow this same pattern.

**[module]** _100% confidence_
The screens index parser splits route source by `@router.` decorator boundaries using regex, not AST — this means it works on any FastAPI route file without importing it, but it will miss routes defined programmatically (e.g. router.add_api_route()). All current console routes use decorator syntax so this is fine, but any future programmatic route registration will need a separate detection pass.

**[module]** _100% confidence_
The screens index parser extracts template context variables from the TemplateResponse dict literal using _CTX_KEY_RE (matches "key": patterns) and detects **_template_ctx / **ctx spreads to inject the standard trio (current_path, repos, effective_repo). It also parses the handler function signature for query/path params, skipping FastAPI internals (request, response, body). Both are regex-based — they work on the raw source block between @router. decorators without importing the module.

**[module]** _100% confidence_
generate_modules switches to index mode when a repo has >100 modules. Index mode groups non-empty modules by top-level path segment, one bullet per module with NL description (first sentence of summary) + hotspot flag + class count + link to the per-module detail file. 0-class modules are filtered from both modes — they're empty directory nodes with no useful content. The threshold is _LARGE_REPO_THRESHOLD = 100, defined inside generate_modules.

## `services.api.main`

**[module]** _100% confidence_
The telemetry DB stores tool_calls with input_json (serialised tool input) and step_tokens (per-inference-step cost). Rows before the input_json column was added have NULL there — the question text for those CodeKG calls is permanently unrecoverable, which limits query plan reconstruction quality for old sessions.

**[system]** _100% confidence_
The KG stores start_line and end_line per Class node, not LOC per file. File LOC must be derived as max(end_line) across all Class nodes with that file_path. This only covers .py files with at least one indexed class — HTML templates and non-Python files are absent from the KG and need disk-size fallback.

**[module]** _100% confidence_
The agent index publish is a two-step process: POST /agent-index/regen writes to SQLite store, then POST /agent-index/publish writes from store to disk and commits to git. Calling only regen leaves disk files stale. The publish endpoint returns 'files_written' (not 'written'), and returns 0 if the store has no visible files for that repo_id.

**[module]** _100% confidence_
_content_is_empty scans the full body for sentinel phrases like 'not found'. This causes false positives when actual insight text contains those words (e.g. 'FastAPI route registration... path-parameter catch-all... not found'). Fix: only scan the first 200 chars of body, where empty-file sentinels always appear.

**[module]** _100% confidence_
The publish cleanup only deleted files that were hidden in the store — it missed files removed from the store entirely (e.g. deprecated per-module insight files). Fix: build the expected_paths set from visible store entries, then delete any .codekg/ file on disk not in that set using rglob.

**[module]** _100% confidence_
At publish time, _validate_index_refs() scans all file content for .codekg/ path references and checks them against the bundle of visible (non-hidden) files being published. Placeholder tokens like `<name>` are excluded. The result is returned as a `warnings` list in the publish response — publish still succeeds, but dangling refs are surfaced. This caught three real problems: policies/active.md referenced while hidden, policies/violations.md referenced while hidden, and modules.md using slash-separated module IDs (services/console) instead of the double-dash filenames (services--console.md) actually written to disk.

**[system]** _90% confidence_
TribalKnowledge nodes use applies_to as a plain string FQN (not a required relationship) — the APPLIES_TO edge to the target node is optional and may not exist if the FQN wasn't found in the KG at write time. Always query by tk.applies_to string, not by traversing the edge.

## `services.console`

**[system]** _100% confidence_
The console container does not hot-reload. All files (templates, routes, requirements.txt) are baked at build time via COPY in the Dockerfile. Any change to services/console/ requires: docker compose up -d --build console

**[module]** _100% confidence_
requests is not installed in the console container by default (FastAPI uses httpx). summarise_classes.py imports requests to call Ollama — it must be listed in services/console/requirements.txt or the job fails immediately with: No module named requests.

**[system]** _100% confidence_
The console UI uses CSS custom properties defined in base.html :root (--bg, --surface, --primary, --success, --danger etc). All page templates must use these tokens — raw hex values in a template are a design bug. There is no external CSS file or build pipeline; all styles are inline in HTML templates.

**[system]** _100% confidence_
The Stop hook is the correct event for enforcing submit_session_telemetry. It fires when Claude finishes a response turn and can block with a decision:block + reason that gets injected back into model context, forcing the model to complete the missing telemetry call.

**[system]** _100% confidence_
Always use the turn_id from the FIRST codeKG opener call in a turn, not a later one. The protocol says: save the turn_id from the first opener and use that for submit_session_telemetry. Using a turn_id from a second call in the same turn orphans the first call from the telemetry record.

**[system]** _100% confidence_
Hook scripts use relative paths (python3 .claude/hooks/require_codekg.py) rather than absolute paths so they work for any engineer who clones the repo, regardless of where it lives on their machine. Absolute paths only work for the original developer.

**[system]** _100% confidence_
The registered repos registry lives at ${REPOS_PATH}/repos.json on the host (./repos/repos.json by default). The API /repos endpoint returns repo_id and path but the path field is null — the actual paths are only in the flat JSON file, not stored in Neo4j.

**[system]** _98% confidence_
All styling in this app is inline in each HTML template — there is no shared CSS file or static asset pipeline. Every template has its own <style> block. To make global design changes, you must either update base.html tokens or touch each template individually.

**[system]** _95% confidence_
The PreToolUse hook fires on every tool call including Read/Write/Edit, but skill invocations (via the Skill tool) run in a sub-context whose tool calls do NOT appear as assistant tool_use blocks in the main session JSONL. This means a codeKG call made through a skill is invisible to the require_codekg.py hook, causing false blocks on subsequent Read/Write calls even though codeKG was consulted.

## `services.console.llm_audit.aggregate_stats`

**[method]** _100% confidence_
aggregate_stats correctly accepts a `days` parameter, computes a `cutoff` timestamp, and passes it to the SQL query via a bound parameter in the WHERE clause, ensuring stats are scoped to the requested timeframe rather than all-time.

## `services.console.main`

**[module]** _100% confidence_
Templates are baked into Docker images at build time — there is no volume mount for the console or api service templates. Any template change requires docker compose up --build to take effect. This is a common source of confusion when edits appear not to apply.

**[module]** _100% confidence_
Jinja2 set inside an if block does not escape that block's scope within the same loop iteration for outer-scope variables. Always set loop-scoped variables (like turn_idx) unconditionally at the top of the for block, not inside a nested if — otherwise the variable is unset or stale for turns where the if condition is false.

**[module]** _95% confidence_
The base.html template defines the navigation, layout shell, and all shared component styles. Page templates extend it and add their own <style> blocks. CSS custom properties (--bg, --surface, --primary etc.) set in base.html :root are the right abstraction point for theming — all page styles should reference these vars, not raw hex values.

**[system]** _80% confidence_
The base.html CSS already uses green (#16a34a) as --primary. The blue appearance likely comes from hardcoded #2563eb values in individual templates (patterns.html, class_detail.html, pattern_catalog.html) and --info (#0284c7) token, not from the global theme.

## `services.console.routes.classes`

**[module]** _100% confidence_
summarise_classes.py is NOT copied into any Docker container — it lives only in tools/ on the host. The console loads it at runtime via importlib from /host-home/Documents/projects/codeKG/tools/summarise_classes.py through the host-home mount. If that path is wrong or the mount is missing, the job errors immediately.

**[module]** _100% confidence_
When summarise_classes.py is loaded via importlib from inside the console container, the self-bootstrap block must be stripped from the source string before exec()-ing it, since it would run against the read-only host-home mount and crash. All deps (neo4j, requests) must be pre-installed in the container image.

**[module]** _100% confidence_
FastAPI route registration order is critical when a path-parameter catch-all exists. GET /classes/{fqn:path} greedily matches everything under /classes/. More-specific routes like /classes/summarise/{job_id} MUST be registered before the catch-all or they are swallowed. Symptom: 404 with body: Class summarise/<id> not found.

**[module]** _90% confidence_
summarise_classes.py is a standalone CLI script in tools/ that is NOT copied into the console container (Dockerfile only copies services/console/ and shared/). To invoke it from the console it must be imported dynamically by path from the host-home mount (/host-home/Documents/projects/codeKG/tools/). It is self-bootstrapping and safe to re-exec via importlib.

## `services.console.routes.classes.classes_list`

**[method]** _100% confidence_
summary_total in classes_list() is correctly scoped to effective_repo using: MATCH (c:Class) WHERE c.repo_id = $repo_id AND NOT c.kind IN ["module"] AND c.summary IS NOT NULL. A separate class_total query provides the denominator (total non-module classes for the repo). The filtered `total` variable must never be used as the denominator — it reflects the current search filter, not the full repo size.

## `services.console.routes.classes.start_summarise`

**[system]** _100% confidence_
Ollama runs on the Mac host, not inside Docker. From any container the correct URL is http://host.docker.internal:11434 — never localhost:11434 which resolves to the container loopback. The console UI and summarise_classes.py default both use host.docker.internal.

**[module]** _100% confidence_
summarise_classes.py skips TEST and GENERATED role classes by default (_SKIP_ROLES). For large repos like ElasticSearch this is ~16k classes. If resume=True and all remaining unsummarised classes are TEST/GENERATED, the job exits with 0 written — looks like failure but is correct. The console shows a Nothing to summarise warning. Use include_skip_roles=True or force=True to override.

## `services.console.routes.dashboard`

**[module]** _90% confidence_
The dashboard summary chips section in dashboard.html is the right place to surface cross-cutting KG metrics — it already contains repo counts, policy counts, violations, and token savings chips all in one row. New system-wide metrics should be added here as conditional chips.

## `services.console.routes.mcp_audit`

**[module]** _100% confidence_
The MCP audit page had two setInterval calls (10s for calls, 30s for session analysis) that caused constant background polling. Removing them and replacing with a manual Refresh button is the right UX for an audit trail — you want a stable view, not one that jumps while you're reading it.

**[module]** _95% confidence_
renderCalls and loadSessionAnalysis run concurrently — analysis data (_analysedSessions) is not available when calls first render, so a second renderCalls call after analysis loads is needed to fill in turn prompts.

## `services.console.routes.mcp_audit._query`

**[method]** _95% confidence_
The _query() stats and tool_breakdown queries in mcp_audit.py are both hard-filtered to the last 24 hours — errors older than that are silently excluded from the summary stats, which can make the system appear healthier than it is.

## `services.ingestion`

**[system]** _100% confidence_
The codeKG protocol text exists in three separate places that must be kept in sync: (1) services/ingestion/claude_md_writer.py — written to repos at ingestion time, (2) services/api/renderers/template_renderer.py — served by GET /template/{repo_id} which powers both sync_claude_md and get_codebase_template, (3) .claude/CLAUDE.md — the live file for this repo. Changing the protocol in one place does not update the others.

## `services.ingestion.kg.writer.KGWriter`

**[method]** _90% confidence_
KGWriter wire_edges has a 90s timeout added to prevent large repos from pinning Neo4j indefinitely — do not remove without load testing.

## `services.mcp`

**[system]** _100% confidence_
codekg_request_id in the MCP response footer was previously the JSON-RPC request_id — a different value for every single tool call. This is why using the 'first call's request_id' was so fragile: any mistake in tracking which call was first gave a wrong value. Fixed by making codekg_request_id equal to turn_id in the footer, so both values are always the same stable string and there is no ambiguity about which to use.

## `services.mcp.main`

**[system]** _95% confidence_
sync_claude_md must return content to Claude Code rather than writing server-side — server-side writes break remote usage where the codeKG server and the engineer's filesystem are on different machines. The correct pattern is: tool returns content, Claude Code calls Write.

**[method]** _85% confidence_
The sync_claude_md tool includes a save_as comment header in the response so Claude Code knows what filename to use without needing to infer it from context.
