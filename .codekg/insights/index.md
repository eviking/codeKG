# All Insights — codeKG
_Generated 2026-06-04 16:34 UTC_

Non-obvious facts captured from previous coding sessions.
These are also inlined at the top of each module file.
**Total:** 40 insights

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

## `services.api.main`

**[module]** _100% confidence_
The telemetry DB stores tool_calls with input_json (serialised tool input) and step_tokens (per-inference-step cost). Rows before the input_json column was added have NULL there — the question text for those CodeKG calls is permanently unrecoverable, which limits query plan reconstruction quality for old sessions.

**[system]** _100% confidence_
The KG stores start_line and end_line per Class node, not LOC per file. File LOC must be derived as max(end_line) across all Class nodes with that file_path. This only covers .py files with at least one indexed class — HTML templates and non-Python files are absent from the KG and need disk-size fallback.

**[module]** _100% confidence_
The agent index publish is a two-step process: POST /agent-index/regen writes to SQLite store, then POST /agent-index/publish writes from store to disk and commits to git. Calling only regen leaves disk files stale. The publish endpoint returns 'files_written' (not 'written'), and returns 0 if the store has no visible files for that repo_id.

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
aggregate_stats accepted a `days` parameter and computed a `cutoff` timestamp but never passed it to the SQL query — stats were always all-time regardless of the argument. Fixed by passing cutoff as a bound parameter in the WHERE clause.

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
summarise_classes.py has a self-bootstrap block that creates a .venv and re-execs itself. When loaded via importlib from inside the console container it runs against the read-only host-home mount and crashes with exit status 1. Fix: strip the bootstrap block from the source string before exec()-ing it. All deps (neo4j, requests) must be pre-installed in the container image.

**[module]** _100% confidence_
FastAPI route registration order is critical when a path-parameter catch-all exists. GET /classes/{fqn:path} greedily matches everything under /classes/. More-specific routes like /classes/summarise/{job_id} MUST be registered before the catch-all or they are swallowed. Symptom: 404 with body: Class summarise/<id> not found.

**[module]** _90% confidence_
summarise_classes.py is a standalone CLI script in tools/ that is NOT copied into the console container (Dockerfile only copies services/console/ and shared/). To invoke it from the console it must be imported dynamically by path from the host-home mount (/host-home/Documents/projects/codeKG/tools/). It is self-bootstrapping and safe to re-exec via importlib.

## `services.console.routes.classes.classes_list`

**[method]** _100% confidence_
summary_total in classes_list() is now correctly scoped to effective_repo (fixed 2026-06-02). It uses: MATCH (c:Class) WHERE c.repo_id = $repo_id AND NOT c.kind IN ["module"] AND c.summary IS NOT NULL. A separate class_total query provides the denominator (total non-module classes for the repo). Previously it counted across ALL repos with no filter, inflating the progress bar. The filtered `total` variable must never be used as the denominator — it reflects the current search filter, not the full repo size.

## `services.console.routes.classes.start_summarise`

**[system]** _100% confidence_
Ollama runs on the Mac host, not inside Docker. From any container the correct URL is http://host.docker.internal:11434 — never localhost:11434 which resolves to the container loo

> ⚠ truncated to stay within file size limit
