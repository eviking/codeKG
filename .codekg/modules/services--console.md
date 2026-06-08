# Module: services/console
_Generated 2026-06-08 14:12 UTC · commit `47004d4`_

**Path:** `/host-home/Documents/projects/codeKG/services/console`  **Classes:** 24

## Depends on

_External files/modules this module imports from:_

- `shared/logging/codekg_logger.py` — 1 import(s)

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

### `RequestLogMiddleware` — class
**File:** `services/console/main.py`  **LOC:** 11  **Grade:** C  **Blast:** 0
**FQN:** `services.console.main.RequestLogMiddleware`

The `RequestLogMiddleware` class includes a method named `dispatch`, which accepts two parameters: a `Request` object and a `call_next` function. This method is designed to log details about each request processed by the middleware before passing control to the next handler in the chain, thereby enabling detailed tracking of requests through the application's layers.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public dispatch` | `Request request`<br>`call_next` | — |  |

### `TestAnnotationRequired` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 13  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestAnnotationRequired`

TestAnnotationRequired is a class that includes methods for testing various aspects of annotation processing. The `test_without_at_prefix` method checks if annotations can be processed correctly when they do not start with the '@' symbol, ensuring flexibility in how annotations are applied. The `test_basic_match` method evaluates whether the system accurately identifies and matches annotations bas

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_without_at_prefix` | — | — |  |
| `public test_basic_match` | — | — |  |
| `public test_case_insensitive` | — | — |  |

### `TestAsk` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 26  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestAsk`

TestAsk is a class that includes several methods to test various scenarios related to an API endpoint designed for asking questions. The method `test_ask_post_happy()` evaluates how the system handles a successful POST request with all necessary parameters, ensuring it processes the question correctly. `test_ask_api_endpoint_missing_question()` checks the response when a required parameter (the qu

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_ask_post_happy` | — | — |  |
| `public test_ask_api_endpoint_missing_question` | — | — |  |
| `public test_ask_api_endpoint_happy` | — | — |  |
| `public test_ask_get_renders` | — | — |  |
| `public test_ask_post_no_summary` | — | — |  |
| `public test_ask_api_endpoint_empty_question` | — | — |  |

### `TestAuditLog` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 7  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestAuditLog`

TestAuditLog is a class that includes a method named `test_audit_page_renders`. This method is designed to verify that an audit page renders correctly, ensuring that all necessary elements are displayed as expected.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_audit_page_renders` | — | — |  |

### `TestClassesPage` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 52  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestClassesPage`

TestClassesPage includes methods for testing various aspects of a classes page, such as sorting classes by name or blast, handling a 404 error when accessing a non-existent class detail, rendering the list of classes correctly, and ensuring that a not-found message is displayed when attempting to access a class that does not exist. Additionally, it tests the functionality of displaying a list of c

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_classes_list_sort_by_name` | — | — |  |
| `public test_classes_list_sort_by_blast` | — | — |  |
| `public test_class_detail_404_not_500` | — | — |  |
| `public test_classes_list_renders` | — | — |  |
| `public test_class_detail_not_found` | — | — |  |
| `public test_classes_list_with_sort` | — | — |  |
| `public test_classes_list_has_summary_filter` | — | — |  |
| `public test_class_detail_renders` | — | — |  |
| `public test_classes_list_with_query` | — | — |  |

### `TestControllerRepoRestriction` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 9  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestControllerRepoRestriction`

The `TestControllerRepoRestriction` class includes methods for testing API endpoints without direct access and for standard phrasing in tests. The `test_without_directly()` method ensures that certain API calls can be made even when not authenticated directly, verifying the system's ability to handle such scenarios gracefully. Meanwhile, the `test_standard_phrasing()` method checks that all respon

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_without_directly` | — | — |  |
| `public test_standard_phrasing` | — | — |  |

### `TestDashboard` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 26  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestDashboard`

TestDashboard includes methods to validate the rendering of a dashboard, its behavior when no data is present in the knowledge graph, and its interaction with repository statistics.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public setup_method` | — | — |  |
| `public test_dashboard_renders` | — | — |  |
| `public test_dashboard_no_ise_on_empty_kg` | — | — |  |
| `public test_dashboard_with_repo_stats` | — | — |  |

### `TestLayerMustNotDependOn` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 12  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestLayerMustNotDependOn`

TestLayerMustNotDependOn is a class that includes methods for testing various aspects of FQN (Fully Qualified Name) handling. The `test_returns_fqn` method checks if the class correctly returns the FQN, ensuring that it adheres to naming conventions. The `test_quoted_names` method evaluates how the class handles names that require quoting, verifying that special characters are managed appropriatel

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_returns_fqn` | — | — |  |
| `public test_quoted_names` | — | — |  |
| `public test_basic_match` | — | — |  |

### `TestMcpAudit` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 24  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestMcpAudit`

TestMcpAudit is a class that includes several methods to validate the behavior of an audit API for a system named MCP (likely Management Control Panel). The method `test_mcp_audit_api_returns_shape()` checks if the API returns data in the expected format or shape. Another method, `test_mcp_audit_page_renders()`, ensures that the audit page is rendered correctly without errors. The method `test_mcp

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_mcp_audit_api_returns_shape` | — | — |  |
| `public test_mcp_audit_page_renders` | — | — |  |
| `public test_mcp_audit_call_detail_not_found` | — | — |  |
| `public test_mcp_audit_api_no_db` | — | — |  |

### `TestModuleMustNotCall` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 18  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestModuleMustNotCall`

TestModuleMustNotCall ensures that no service tests are called directly, promoting isolation. It validates FQN (Fully Qualified Name) column handling through test_returns_fqn_column. test_basic_match checks for basic matching functionality, while test_directly_variant assesses variant handling without direct calls.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_services_in_prefix` | — | — |  |
| `public test_returns_fqn_column` | — | — |  |
| `public test_basic_match` | — | — |  |
| `public test_directly_variant` | — | — |  |

### `TestModulesPage` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 39  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestModulesPage`

TestModulesPage is a class designed to perform various tests related to module management within an application. The `test_modules_list_with_data` method checks if the list of modules renders correctly when data is available, ensuring that the UI displays the modules as expected. The `test_modules_list_renders` method verifies that the module list page renders without errors, regardless of whether

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_modules_list_with_data` | — | — |  |
| `public test_modules_list_renders` | — | — |  |
| `public test_create_module` | — | — |  |
| `public test_module_detail_renders` | — | — |  |
| `public test_module_detail_not_found` | — | — |  |

### `TestOutputSafety` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 7  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestOutputSafety`

TestOutputSafety ensures that curly braces within input data do not lead to a key error by implementing a robust validation mechanism. The method `test_curly_braces_in_input_do_not_cause_key_error` specifically checks how the system handles unexpected characters in input, thereby enhancing the safety and reliability of output generation.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_curly_braces_in_input_do_not_cause_key_error` | — | — |  |

### `TestPatternCatalog` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 48  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestPatternCatalog`

TestPatternCatalog is a class designed to perform various tests on a catalog system. The `test_catalog_toggle_off` method checks the functionality of toggling items in the catalog off, ensuring that the system correctly handles this operation without errors. The `test_catalog_page_renders` method verifies that the catalog pages are rendered properly, checking for any layout or display issues. The 

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_catalog_toggle_off` | — | — |  |
| `public test_catalog_page_renders` | — | — |  |
| `public test_catalog_update_invalid_json` | — | — |  |
| `public test_catalog_toggle_not_found` | — | — |  |
| `public test_catalog_toggle_on` | — | — |  |
| `public test_catalog_update_happy` | — | — |  |
| `public test_catalog_update_not_found` | — | — |  |
| `protected _catalog` | — | — |  |

### `TestPatternsPage` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 17  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestPatternsPage`

The `TestPatternsPage` class includes methods for detecting patterns through a POST request (`test_patterns_detect_post`) and retrieving rendered patterns via a GET request (`test_patterns_get_renders`).

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_patterns_detect_post` | — | — |  |
| `public test_patterns_get_renders` | — | — |  |

### `TestPoliciesPage` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 77  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestPoliciesPage`

The `TestPoliciesPage` class includes several methods to validate various aspects of a policies page in an application. The `test_policies_list_no_ise_when_api_fails()` method checks that the policies list does not display any issues when the API call fails, ensuring robust error handling. The `test_activate_policy()` method tests the functionality of activating a policy, verifying that the system

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public setup_method` | — | — |  |
| `public test_policies_list_no_ise_when_api_fails` | — | — |  |
| `public test_activate_policy` | — | — |  |
| `public test_create_policy_redirects` | — | — |  |
| `public test_policy_detail_renders` | — | — |  |
| `public test_run_policy_not_found` | — | — |  |
| `public test_policies_list_renders` | — | — |  |
| `public test_policy_detail_not_found` | — | — |  |
| `public test_run_policy_executes_cypher` | — | — |  |

### `TestPublicMethodAnnotation` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 21  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestPublicMethodAnnotation`

TestPublicMethodAnnotation is a class that includes several methods to validate the behavior of public method annotations in Java. The `test_must_annotated_variant` method checks if a method must be annotated with a specific annotation, ensuring compliance with coding standards. The `test_module_keyword_in_phrase_is_not_matched` method tests whether the module keyword within phrases is correctly i

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_must_annotated_variant` | — | — |  |
| `public test_module_keyword_in_phrase_is_not_matched` | — | — |  |
| `public test_basic_match` | — | — |  |
| `public test_without_at_prefix` | — | — |  |

### `TestReposPage` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 90  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestReposPage`

TestReposPage is a class that includes several methods for testing various functionalities related to repository management. The `test_repo_detail_unknown` method likely tests how the system handles requests for details of repositories when the requested information is not available or unknown. The `test_scan_status_api` method probably checks the functionality of an API endpoint that returns the 

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_repo_detail_unknown` | — | — |  |
| `public setup_method` | — | — |  |
| `public test_scan_status_api` | — | — |  |
| `public test_clone_repo_valid_url_starts_job` | — | — |  |
| `public test_repos_list_no_ise_when_api_unreachable` | — | — |  |
| `public test_repos_list_empty` | — | — |  |
| `public test_register_repo_path_not_git` | — | — |  |
| `public test_remove_repo` | — | — |  |
| `public test_register_repo_invalid_path` | — | — |  |
| `public test_clone_repo_bad_url` | — | — |  |
| `public test_repos_list_with_repo` | — | — |  |
| `public test_register_repo_happy_path` | — | — |  |
| `public test_scan_triggers_ingestion` | — | — |  |
| `public test_scan_unknown_repo_404` | — | — |  |
| `public test_clone_status_not_found` | — | — |  |
| `public test_repo_detail_not_in_registry` | — | — |  |

### `TestServiceMustNotExtend` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 4  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestServiceMustNotExtend`

TestServiceMustNotExtend is a class that includes a method named `test_basic_match`. This method does not take any parameters and does not return any value, indicated by its signature `void test_basic_match()`. The purpose of this method is to perform basic matching tests within the TestServiceMustNotExtend class.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_basic_match` | — | — |  |

### `TestSystemHealth` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 14  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestSystemHealth`

TestSystemHealth includes methods to verify that the system health API returns JSON data and that the system health page renders correctly. The `test_system_health_api_returns_json` method checks if the API endpoint responds with a valid JSON format, ensuring data integrity for automated monitoring systems. Meanwhile, the `test_system_health_page_renders` method assesses whether the web page displ

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_system_health_api_returns_json` | — | — |  |
| `public test_system_health_page_renders` | — | — |  |

### `TestToContainerPath` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 20  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestToContainerPath`

The `TestToContainerPath` class contains methods to verify different scenarios for converting host paths to container paths. The `test_passthrough_when_no_match` method checks that if there is no matching pattern, the original path is returned unchanged. The `test_passthrough_when_host_home_empty` method ensures that if the host home directory is empty, the conversion still returns the original pa

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_passthrough_when_no_match` | — | — |  |
| `public test_passthrough_when_host_home_empty` | — | — |  |
| `public test_rewrites_host_home` | — | — |  |

### `TestUnknownPolicy` — class
**File:** `services/console/tests/test_policy_compiler.py`  **LOC:** 16  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_policy_compiler.TestUnknownPolicy`

TestUnknownPolicy is a class that includes several methods to validate the behavior of placeholder text in various scenarios. The method `test_placeholder_has_fqn_comment()` checks if the placeholder contains a fully qualified name (FQN) comment, ensuring it adheres to naming conventions. The method `test_empty_string_returns_placeholder()` verifies that an empty string input results in a default 

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_placeholder_has_fqn_comment` | — | — |  |
| `public test_empty_string_returns_placeholder` | — | — |  |
| `public test_gibberish_returns_placeholder` | — | — |  |
| `public test_placeholder_contains_original_text` | — | — |  |

### `TestValidateRepoPath` — class
**File:** `services/console/tests/test_console.py`  **LOC:** 22  **Grade:** B  **Blast:** 0
**FQN:** `services.console.tests.test_console.TestValidateRepoPath`

TestValidateRepoPath is a class designed to validate Git repository paths. The method `test_nonexistent_path` checks if the system correctly identifies and handles non-existent paths, ensuring robust error handling for missing directories. The method `test_not_a_directory` verifies that the validation logic distinguishes between valid Git repositories and non-directory entities, preventing incorre

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_nonexistent_path` | — | — |  |
| `public test_not_a_directory` | — | — |  |
| `public test_valid_git_repo` | — | — |  |
| `public test_directory_without_git` | — | — |  |

### `_DefaultZero` — class
**File:** `services/console/agent_index/generator.py`  **LOC:** 1  **Grade:** B  **Blast:** 0
**FQN:** `services.console.agent_index.generator._DefaultZero`

_DefaultZero is a class that initializes default values for its fields to zero when an instance is created. The constructor sets all integer fields to 0, ensuring that no uninitialized data exists in the object. Additionally, it resets string fields to empty strings, preventing any null references or undefined states. Furthermore, _DefaultZero includes a method named `resetAllFields` which iterate

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `dunder protected __missing__` | `key` | — |  |

### `_Entry` — class
**File:** `services/console/llm_audit.py`  **LOC:** 38  **Grade:** B  **Blast:** 0
**FQN:** `services.console.llm_audit._Entry`

_Entries are recorded using the `record` method, which accepts a generic type `response` and a string `error`. The `record_error` method captures exceptions by accepting an `Exception` type named `exc`, logging or handling errors accordingly.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public record` | `Any response`<br>`str error` | `None` |  |
| `public record_error` | `Exception exc` | `None` |  |
