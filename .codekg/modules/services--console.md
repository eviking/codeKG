# Module: services/console
_Generated 2026-06-09 20:27 UTC · commit `unpublished`_

**Path:** `/host-home/Documents/projects/codeKG/services/console`  **Classes:** 34

## Data stores

_Detected from source file imports and connection patterns:_

- **agent_index.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `agent_index/store.py`
  - `tests/test_config_routes.py`
- **llm_audit.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `llm_audit.py`
  - `nl_query.py`
  - `routes/audit_log.py`
  - `routes/system_health.py`
- **mcp_audit.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `main.py`
  - `routes/mcp_audit.py`
- **Neo4j** (graph) — see `.codekg/architecture/datastores.md` for schema
  - `deps.py`
  - `nl_query.py`
  - `pattern_detector.py`
  - `routes/system_health.py`
  - `tests/test_config_routes.py`
  - `tests/test_console.py`
- **scan_log.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `routes/system_health.py`
  - `scan_launcher.py`
  - `tests/test_scan_launcher.py`

## Routes

_FastAPI route handlers in this module — what each renders, its template, and template context._

| Method | URL | Template | Parameters | Template context |
|--------|-----|----------|------------|-----------------|
| `GET` | `/` | `dashboard.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `repo_stats`, `gc`, `recent_events`, `token_savings`, `tk_total`, `tk_by_repo` |
| `GET` | `/agent-index` | `agent_index_overview.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `files`, `standard_grouped`, `module_files`, `modules`, `has_files` |
| `GET` | `/agent-index/file/{file_key:path}` | `agent_index_file.html` | `file_key: str` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `file`, `file_key`, `content_html` |
| `GET` | `/ask` | `ask.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `result` |
| `POST` | `/ask` | `ask.html` | `question: str` = `Form(...` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `question`, `repo_id`, `result` |
| `GET` | `/audit` | `audit.html` | `source: str` = `""`, `limit: int` = `200`, `hours: int` = `24` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `calls`, `stats`, `source_filter`, `limit`, `hours` |
| `GET` | `/auth/callback` | `—` | `code: str` = `""`, `state: str` = `""`, `error: str` = `""` | — |
| `GET` | `/classes` | `classes.html` | `q: str` = `""`, `role: str` = `""`, `repo_id: str` = `""`, `sort: str` = `"coupling"`, `has_summary: str` = `"false"`, `page: int` = `1` | `effective_repo (via _template_ctx)`, `current_path (via _template_ctx)`, `classes`, `total`, `page`, `pages`, `page_size`, `q`, `role`, `repo_id`, `sort`, `has_summary`, `summary_total`, `class_total`, `roles`, `repos` |
| `POST` | `/classes/summarise` | `—` | `repo_id: str` = `Form(...` | — |
| `GET` | `/classes/summarise/{job_id}` | `summarise_progress.html` | `job_id: str` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `job_id`, `status`, `done`, `total`, `log` |
| `GET` | `/classes/{fqn:path}` | `class_detail.html` | `fqn: str` | — |
| `GET` | `/config` | `config.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `sections`, `env_file_exists`, `env_file_path` |
| `GET` | `/getstarted` | `getstarted.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)` |
| `GET` | `/hygiene` | `hygiene_overview.html` | — | `effective_repo (via _template_ctx)`, `current_path (via _template_ctx)`, `repos` |
| `GET` | `/hygiene/{repo_id:path}` | `hygiene_detail.html` | `repo_id: str` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `repo_id`, `repo_score`, `classes`, `stats` |
| `GET` | `/hygiene/{repo_id}/refactor` | `hygiene_refactor.html` | `repo_id: str` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `repo_id`, `classes`, `module_index_path` |
| `GET` | `/insights` | `insights.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `sections`, `total`, `include_hidden`, `q`, `sort`, `pending_count` |
| `GET` | `/mcp-audit` | `mcp_audit.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)` |
| `GET` | `/modules` | `modules.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `modules`, `module_tree`, `edges` |
| `GET` | `/modules/{module_id:path}` | `module_detail.html` | `module_id: str` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `mod`, `module_id`, `stat` |
| `GET` | `/pattern-catalog` | `pattern_catalog.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `patterns`, `patterns_json` |
| `GET` | `/patterns` | `patterns.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `repo_id`, `results` |
| `POST` | `/patterns` | `patterns.html` | `repo_id: str` = `Form(""` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `repo_id`, `results` |
| `GET` | `/policies` | `policies.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `policies`, `modules` |
| `GET` | `/policies/{policy_id}` | `policy_detail.html` | `policy_id: str` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `policy`, `violations`, `violations_run`, `run_error`, `run_error_msg`, `recompiled`, `has_valid_cypher`, `saved` |
| `GET` | `/repos` | `repos.html` | — | `effective_repo (via _template_ctx)`, `current_path (via _template_ctx)`, `repos`, `repos_path` |
| `GET` | `/repos/{repo_id:path}` | `repo_detail.html` | `repo_id: str` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `repo_id`, `repo_path`, `git`, `kg`, `provenance`, `stats`, `in_registry`, `scanning`, `api_url` |
| `GET` | `/system-health` | `system_health.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)` |
| `GET` | `/telemetry` | `telemetry.html` | — | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `sessions` |
| `GET` | `/telemetry/{session_id}` | `telemetry_detail.html` | `session_id: str` | `effective_repo (via _template_ctx)`, `repos (via _template_ctx)`, `current_path (via _template_ctx)`, `detail` |

## ⚡ Insights from previous sessions

_Non-obvious facts from engineering sessions — treat as expert hints._

- **services.console.routes.classes** (100%): FastAPI route registration order is critical when a path-parameter catch-all exists. GET /classes/{fqn:path} greedily matches everything under /classes/. More-specific routes like /classes/summarise/{job_id} MUST be registered before the catch-all or they are swallowed. Symptom: 404 with body: Class summarise/<id> not found.
- **services.console.routes.classes.start_summarise** (100%): summarise_classes.py skips TEST and GENERATED role classes by default (_SKIP_ROLES). For large repos like ElasticSearch this is ~16k classes. If resume=True and all remaining unsummarised classes are TEST/GENERATED, the job exits with 0 written — looks like failure but is correct. The console shows a Nothing to summarise warning. Use include_skip_roles=True or force=True to override.
- **services.console.routes.classes** (100%): When summarise_classes.py is loaded via importlib from inside the console container, the self-bootstrap block must be stripped from the source string before exec()-ing it, since it would run against the read-only host-home mount and crash. All deps (neo4j, requests) must be pre-installed in the container image.
- **services.console.routes.classes** (100%): summarise_classes.py is NOT copied into any Docker container — it lives only in tools/ on the host. The console loads it at runtime via importlib from /host-home/Documents/projects/codeKG/tools/summarise_classes.py through the host-home mount. If that path is wrong or the mount is missing, the job errors immediately.
- **services.console.routes.classes.start_summarise** (100%): Ollama runs on the Mac host, not inside Docker. From any container the correct URL is http://host.docker.internal:11434 — never localhost:11434 which resolves to the container loopback. The console UI and summarise_classes.py default both use host.docker.internal.
- **services.console** (100%): requests is not installed in the console container by default (FastAPI uses httpx). summarise_classes.py imports requests to call Ollama — it must be listed in services/console/requirements.txt or the job fails immediately with: No module named requests.
- **services.console.routes.classes.classes_list** (100%): summary_total in classes_list() is correctly scoped to effective_repo using: MATCH (c:Class) WHERE c.repo_id = $repo_id AND NOT c.kind IN ["module"] AND c.summary IS NOT NULL. A separate class_total query provides the denominator (total non-module classes for the repo). The filtered `total` variable must never be used as the denominator — it reflects the current search filter, not the full repo size.
- **services.console.llm_audit.aggregate_stats** (100%): aggregate_stats correctly accepts a `days` parameter, computes a `cutoff` timestamp, and passes it to the SQL query via a bound parameter in the WHERE clause, ensuring stats are scoped to the requested timeframe rather than all-time.
- **services.console** (100%): The console container does not hot-reload. All files (templates, routes, requirements.txt) are baked at build time via COPY in the Dockerfile. Any change to services/console/ requires: docker compose up -d --build console
- **services.console** (100%): The console UI uses CSS custom properties defined in base.html :root (--bg, --surface, --primary, --success, --danger etc). All page templates must use these tokens — raw hex values in a template are a design bug. There is no external CSS file or build pipeline; all styles are inline in HTML templates.

## Classes

### `AuthMiddleware` — class
**File:** `services/console/main.py`  **LOC:** 21  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.main.AuthMiddleware`

Gate all console pages behind GitHub OAuth when AUTH_ENABLED. Bypassed for the auth routes themselves and /health. When auth is disabled (GITHUB_CLIENT_ID not set) every request passes through.

### `RequestLogMiddleware` — class
**File:** `services/console/main.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.main.RequestLogMiddleware`

Logs console requests along with response timing. Watch out for static-asset noise here, because the middleware intentionally skips those paths.

### `TestAnnotationRequired` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 15  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestAnnotationRequired`

TestAnnotationRequired is a class that includes methods for testing various aspects of annotation processing. The `test_without_at_prefix` method checks if annotations can be processed correctly when they do not start with the '@' symbol, ensuring flexibility in how annotations are applied. The `test_basic_match` method evaluates whether the system accurately identifies and matches annotations bas

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_without_at_prefix` | — | — |  |
| `public test_basic_match` | — | — |  |
| `public test_case_insensitive` | — | — |  |

### `TestAsk` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 28  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestAsk`

Exercises ask behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestCancelScan` — class
**File:** `services/console/tests/test_scan_launcher.py`  **LOC:** 29  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_scan_launcher.TestCancelScan`

Exercises cancel scan behavior in the scan launcher test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestCheckAccess` — class
**File:** `services/console/tests/test_auth.py`  **LOC:** 97  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_auth.TestCheckAccess`

Exercises check access behavior in the auth test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestClassesPage` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 54  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestClassesPage`

Exercises classes page behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestConfigRoutes` — class
**File:** `services/console/tests/test_config_routes.py`  **LOC:** 35  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_config_routes.TestConfigRoutes`

Exercises config routes behavior in the config routes test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_save_valid_key` | `console_client` | — |  |
| `public test_save_unknown_key_returns_400` | `console_client` | — |  |
| `public test_current_returns_redacted_secrets` | `console_client` | — |  |

### `TestControllerRepoRestriction` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 11  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestControllerRepoRestriction`

The `TestControllerRepoRestriction` class includes methods for testing API endpoints without direct access and for standard phrasing in tests. The `test_without_directly()` method ensures that certain API calls can be made even when not authenticated directly, verifying the system's ability to handle such scenarios gracefully. Meanwhile, the `test_standard_phrasing()` method checks that all respon

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_without_directly` | — | — |  |
| `public test_standard_phrasing` | — | — |  |

### `TestCurrentUser` — class
**File:** `services/console/tests/test_auth.py`  **LOC:** 19  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_auth.TestCurrentUser`

Exercises current user behavior in the auth test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestDashboard` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 29  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestDashboard`

Exercises dashboard behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestLaunchScan` — class
**File:** `services/console/tests/test_scan_launcher.py`  **LOC:** 80  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_scan_launcher.TestLaunchScan`

Exercises launch scan behavior in the scan launcher test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestLayerMustNotDependOn` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 14  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestLayerMustNotDependOn`

TestLayerMustNotDependOn is a class that includes methods for testing various aspects of FQN (Fully Qualified Name) handling. The `test_returns_fqn` method checks if the class correctly returns the FQN, ensuring that it adheres to naming conventions. The `test_quoted_names` method evaluates how the class handles names that require quoting, verifying that special characters are managed appropriatel

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_returns_fqn` | — | — |  |
| `public test_quoted_names` | — | — |  |
| `public test_basic_match` | — | — |  |

### `TestLoadEnvFile` — class
**File:** `services/console/tests/test_config_routes.py`  **LOC:** 54  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_config_routes.TestLoadEnvFile`

Exercises load env file behavior in the config routes test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_skips_comment_lines` | `config_routes` | — |  |
| `public test_strips_quotes_from_values` | `config_routes` | — |  |
| `public test_skips_blank_lines` | `config_routes` | — |  |
| `public test_parses_key_value_pairs` | `config_routes` | — |  |
| `public test_returns_empty_when_file_missing` | `config_routes` | — |  |

### `TestMcpAudit` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 26  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestMcpAudit`

Exercises mcp audit behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestModuleMustNotCall` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 20  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestModuleMustNotCall`

TestModuleMustNotCall ensures that no service tests are called directly, promoting isolation. It validates FQN (Fully Qualified Name) column handling through test_returns_fqn_column. test_basic_match checks for basic matching functionality, while test_directly_variant assesses variant handling without direct calls.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_services_in_prefix` | — | — |  |
| `public test_returns_fqn_column` | — | — |  |
| `public test_basic_match` | — | — |  |
| `public test_directly_variant` | — | — |  |

### `TestModulesPage` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 41  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestModulesPage`

Exercises modules page behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestOutputSafety` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 9  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestOutputSafety`

TestOutputSafety ensures that curly braces within input data do not lead to a key error by implementing a robust validation mechanism. The method `test_curly_braces_in_input_do_not_cause_key_error` specifically checks how the system handles unexpected characters in input, thereby enhancing the safety and reliability of output generation.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_curly_braces_in_input_do_not_cause_key_error` | — | — |  |

### `TestPatternCatalog` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 50  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestPatternCatalog`

Exercises pattern catalog behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestPatternsPage` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 19  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestPatternsPage`

Exercises patterns page behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestPoliciesPage` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 79  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestPoliciesPage`

Exercises policies page behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestPublicMethodAnnotation` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 23  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestPublicMethodAnnotation`

TestPublicMethodAnnotation is a class that includes several methods to validate the behavior of public method annotations in Java. The `test_must_annotated_variant` method checks if a method must be annotated with a specific annotation, ensuring compliance with coding standards. The `test_module_keyword_in_phrase_is_not_matched` method tests whether the module keyword within phrases is correctly i

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_must_annotated_variant` | — | — |  |
| `public test_module_keyword_in_phrase_is_not_matched` | — | — |  |
| `public test_basic_match` | — | — |  |
| `public test_without_at_prefix` | — | — |  |

### `TestRedact` — class
**File:** `services/console/tests/test_config_routes.py`  **LOC:** 29  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_config_routes.TestRedact`

Exercises redact behavior in the config routes test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_leaves_non_secret_unchanged` | `config_routes` | — |  |
| `public test_replaces_secret_with_dots` | `config_routes` | — |  |
| `public test_returns_empty_for_unset_secret` | `config_routes` | — |  |

### `TestReposPage` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 92  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestReposPage`

Exercises repos page behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestSaveEnvFile` — class
**File:** `services/console/tests/test_config_routes.py`  **LOC:** 35  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_config_routes.TestSaveEnvFile`

Exercises save env file behavior in the config routes test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_merges_with_existing_values` | `config_routes` | — |  |
| `public test_creates_file_with_correct_content` | `config_routes` | — |  |
| `public test_removes_keys_with_empty_values` | `config_routes` | — |  |

### `TestServiceMustNotExtend` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 6  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestServiceMustNotExtend`

TestServiceMustNotExtend is a class that includes a method named `test_basic_match`. This method does not take any parameters and does not return any value, indicated by its signature `void test_basic_match()`. The purpose of this method is to perform basic matching tests within the TestServiceMustNotExtend class.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_basic_match` | — | — |  |

### `TestSessionCookie` — class
**File:** `services/console/tests/test_auth.py`  **LOC:** 51  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_auth.TestSessionCookie`

Exercises session cookie behavior in the auth test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestSystemHealth` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 16  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestSystemHealth`

Exercises system health behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestToContainerPath` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 22  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestToContainerPath`

Exercises to container path behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestUnknownPolicy` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 18  **Grade:** A  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestUnknownPolicy`

TestUnknownPolicy is a class that includes several methods to validate the behavior of placeholder text in various scenarios. The method `test_placeholder_has_fqn_comment()` checks if the placeholder contains a fully qualified name (FQN) comment, ensuring it adheres to naming conventions. The method `test_empty_string_returns_placeholder()` verifies that an empty string input results in a default 

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_placeholder_has_fqn_comment` | — | — |  |
| `public test_empty_string_returns_placeholder` | — | — |  |
| `public test_gibberish_returns_placeholder` | — | — |  |
| `public test_placeholder_contains_original_text` | — | — |  |

### `TestValidateRepoPath` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 24  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestValidateRepoPath`

Exercises validate repo path behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `_AttrProxy` — class
**File:** `services/console/main.py`  **LOC:** 5  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.main._AttrProxy`

### `_DefaultZero` — class
**File:** `services/console/agent_index/generator.py`  **LOC:** 3  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.agent_index.generator._DefaultZero`

Dictionary that treats missing counters as zero during console summaries. Watch out for accidental writes here, because absent keys become real buckets once touched.

### `_Entry` — class
**File:** `services/console/llm_audit.py`  **LOC:** 51  **Grade:** ?  **Blast:** 0
**FQN:** `services.console.llm_audit._Entry`

Represents one LLM audit row as rendered by the console. Watch out for schema alignment here, because UI filters and exports assume stable field names.
