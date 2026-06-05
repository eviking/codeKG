# Full Codebase Index — codeKG
_Generated 2026-06-05 20:15 UTC · all modules inlined (repo LOC below 2500 threshold)_

This file contains complete class and method detail for every module.
No additional file reads needed — everything is here.

# Module: services/api
_Generated 2026-06-05 20:15 UTC_

**Path:** `/host-home/Documents/projects/codeKG/services/api`  **Classes:** 22

## Depends on

_External files/modules this module imports from:_

- `shared/logging/codekg_logger.py` — 4 import(s)

## Data stores

_Detected from source file imports and connection patterns:_

- **agent_index.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `agent_index/generator.py`
  - `agent_index/store.py`
- **llm_audit.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `agent_index/generator.py`
  - `llm_audit.py`
  - `nl_query.py`
- **mcp_audit.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `agent_index/generator.py`
- **Neo4j** (graph) — see `.codekg/architecture/datastores.md` for schema
  - `agent_index/generator.py`
  - `impact/engine.py`
  - `main.py`
  - `nl_query.py`
  - `renderers/template_renderer.py`
  - `tests/test_api.py`
- **scan_log.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `agent_index/generator.py`
- **telemetry.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `agent_index/generator.py`
  - `main.py`

## ⚡ Insights from previous sessions

_Non-obvious facts from engineering sessions — treat as expert hints._

- **services.api.main** (100%): The telemetry DB stores tool_calls with input_json (serialised tool input) and step_tokens (per-inference-step cost). Rows before the input_json column was added have NULL there — the question text for those CodeKG calls is permanently unrecoverable, which limits query plan reconstruction quality for old sessions.
- **services.api.main** (100%): The KG stores start_line and end_line per Class node, not LOC per file. File LOC must be derived as max(end_line) across all Class nodes with that file_path. This only covers .py files with at least one indexed class — HTML templates and non-Python files are absent from the KG and need disk-size fallback.
- **services.api.agent_index.generator** (100%): Module index files grew from ~40 lines (class table only) to 230-300 lines per module by pulling full method signatures, parameter types, return types, and LOC from object_model on each Class node. The object_model JSON blob contains a 'methods' array with name, return_type, parameters, and modifiers — this is richer than the separate Method nodes which lack a 'signature' property.
- **services.api.main** (100%): The agent index publish is a two-step process: POST /agent-index/regen writes to SQLite store, then POST /agent-index/publish writes from store to disk and commits to git. Calling only regen leaves disk files stale. The publish endpoint returns 'files_written' (not 'written'), and returns 0 if the store has no visible files for that repo_id.
- **services.api.agent_index.generator** (100%): When total repo LOC (sum of max end_line per file) is below 2500, the generator produces a combined.md with all modules inlined and CLAUDE.md directs agents to read only that one file. Above the threshold, separate per-module files are used. codeKG itself is at 7236 LOC so uses per-module mode.
- **services.api.agent_index.generator** (100%): The insight query in generate_insights_module used CONTAINS $module_id where module_id is 'services/console' (slash-separated) but TribalKnowledge.applies_to stores dot-separated FQNs like 'services.console.main'. The fix is to also match against module_id.replace('/', '.') as module_dot. Both forms must be passed as separate Cypher parameters.
- **services.api.main** (100%): _content_is_empty scans the full body for sentinel phrases like 'not found'. This causes false positives when actual insight text contains those words (e.g. 'FastAPI route registration... path-parameter catch-all... not found'). Fix: only scan the first 200 chars of body, where empty-file sentinels always appear.
- **services.api.agent_index.generator** (100%): The cross-module dependency query required BOTH source and target classes to belong to a Module node. Since shared/logging/codekg_logger.py is outside all modules, all imports resolved to zero rows. Fix: use OPTIONAL MATCH for the target module and fall back to the filename for display.
- **services.api.main** (100%): The publish cleanup only deleted files that were hidden in the store — it missed files removed from the store entirely (e.g. deprecated per-module insight files). Fix: build the expected_paths set from visible store entries, then delete any .codekg/ file on disk not in that set using rglob.
- **services.api.agent_index.generator** (100%): Class-level "Used by" comes from blast_radius (array of dependent FQNs stored on each Class node). Module-level "Used by" comes from intra-repo IMPORTS edges. In this repo, blast_radius is only non-empty on codekg_logger (blast=8) in shared/ — all service module classes have blast=0 because the ingestion hasn't resolved deeper Python import chains beyond direct class imports.

## Classes

### `ImpactEngine` — class
**File:** `services/api/impact/engine.py`  **LOC:** 254  **Grade:** A  **Blast:** 0
**FQN:** `services.api.impact.engine.ImpactEngine`

ImpactEngine computes impact reports for code changes by executing Cypher queries on a graph database. It accepts a repository ID, a list of changed files, and an optional commit SHA as inputs. The method returns an ImpactReport object that details the effects of the specified changes within the repository's graph structure.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public compute` | `str repo_id`<br>`list[str] changed_files`<br>`Optional[str] commit_sha` | `ImpactReport` |  |
| `protected _exposed_endpoints` | `list[str] direct_fqns` | `list[ImpactedEndpoint]` |  |
| `protected _affected_modules` | `list[str] all_fqns` | `list[str]` |  |
| `protected _run` | `str cypher` | `list[dict]` |  |
| `protected _relevant_policies` | `list[str] modules` | `list[ImpactedPolicy]` |  |
| `protected _transitive_dependents` | `list[str] direct_fqns` | `list[ImpactedNode]` |  |
| `protected _directly_affected` | `str repo_id`<br>`list[str] files` | `list[ImpactedNode]` |  |
| `protected _suggested_tests` | `list[str] direct_fqns`<br>`list[str] modules` | `list[SuggestedTest]` |  |
| `dunder protected __init__` | `Driver driver` | — |  |
| `protected _risk_score` | `ImpactReport report` | `float` |  |
| `protected _callers` | `list[str] direct_fqns` | `list[ImpactedNode]` |  |

### `ImpactReport` — class
**File:** `services/api/impact/engine.py`  **LOC:** 39  **Grade:** B  **Blast:** 0
**FQN:** `services.api.impact.engine.ImpactReport`

ImpactReport is a class that includes a method named `to_dict()`. This method converts an instance of ImpactReport into a dictionary format, facilitating easy serialization and data interchange between different parts of an application or system. The dictionary representation captures all relevant attributes of the ImpactReport object, making it straightforward to store, transmit, or manipulate th

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public to_dict` | — | `dict` |  |

### `ImpactedEndpoint` — class
**File:** `services/api/impact/engine.py`  **LOC:** 7  **Grade:** B  **Blast:** 0
**FQN:** `services.api.impact.engine.ImpactedEndpoint`

ImpactedEndpoint is a class that encapsulates details about an endpoint affected by some system operation. It includes a field `endpointId` of type `String`, which uniquely identifies each endpoint. The method `updateStatus(String status)` allows changing the status of the endpoint, such as from "active" to "inactive". Another method `getEndpointDetails()` returns a comprehensive string representa

### `ImpactedNode` — class
**File:** `services/api/impact/engine.py`  **LOC:** 8  **Grade:** B  **Blast:** 0
**FQN:** `services.api.impact.engine.ImpactedNode`

ImpactedNode is a class that encapsulates information about nodes in a network or graph structure. It includes fields such as `nodeId` of type `String`, which uniquely identifies each node, and `neighbors` of type `List<Node>`, representing the connections to other nodes. The method `updateStatus(String status)` allows changing the status of the node, indicating its current state in the network. A

### `ImpactedPolicy` — class
**File:** `services/api/impact/engine.py`  **LOC:** 5  **Grade:** B  **Blast:** 0
**FQN:** `services.api.impact.engine.ImpactedPolicy`

ImpactedPolicy is a class that encapsulates policies related to resource access control within an application. It includes methods such as `applyPolicy` which takes a policy object and applies it to resources, ensuring compliance with security requirements. The class also contains a field of type `List<PolicyRule>` named `rules`, which stores the individual rules that define how resources can be a

### `RequestLogMiddleware` — class
**File:** `services/api/main.py`  **LOC:** 11  **Grade:** C  **Blast:** 0
**FQN:** `services.api.main.RequestLogMiddleware`

`RequestLogMiddleware` is a middleware component designed to log details of each HTTP request processed by an application. The `dispatch` method accepts a `Request` object containing information about the incoming request and a `call_next` function, which allows the middleware to pass control to the next handler in the chain after logging the request details.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public dispatch` | `Request request`<br>`call_next` | — |  |

### `SuggestedTest` — class
**File:** `services/api/impact/engine.py`  **LOC:** 4  **Grade:** B  **Blast:** 0
**FQN:** `services.api.impact.engine.SuggestedTest`

SuggestedTest is a class that includes methods for setting up test environments and running tests. The `initializeEnvironment` method configures necessary resources before tests begin, while the `executeTests` method runs the actual tests defined in the class. The `reportResults` method outputs the outcomes of the tests to a specified destination, ensuring transparency and accountability of the te

### `TestClassContext` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 49  **Grade:** B  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestClassContext`

`TestClassContext` is a class designed to handle various scenarios related to testing class loading and fallback mechanisms. The `test_fuzzy_fallback_also_404` method tests how the system handles fuzzy fallbacks, ensuring that it correctly returns a 404 error when no suitable class is found. The `test_class_found_via_prebuilt_snapshot` method verifies that classes can be successfully loaded from p

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_fuzzy_fallback_also_404` | — | — |  |
| `public test_class_found_via_prebuilt_snapshot` | — | — |  |
| `public test_live_fallback_path` | — | — |  |
| `public test_class_not_found_no_ise` | — | — |  |
| `public test_class_not_found_returns_404` | — | — |  |

### `TestFeatureContext` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 13  **Grade:** B  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestFeatureContext`

The `TestFeatureContext` class includes methods to validate feature behavior. The `test_feature_returns_list()` method checks if a feature correctly returns a list, ensuring that the output is as expected. Conversely, the `test_feature_skips_missing_classes()` method tests whether the feature skips over classes that are not present or valid, maintaining robustness in scenarios where some data migh

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_feature_returns_list` | — | — |  |
| `public test_feature_skips_missing_classes` | — | — |  |

### `TestImpactFiles` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 44  **Grade:** B  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestImpactFiles`

TestImpactFiles is a class designed to validate the behavior of methods related to file impact analysis in software development. The `test_impact_files_missing_params` method checks how the system handles scenarios where required parameters for file impact analysis are not provided, ensuring robust error handling. The `test_impact_pr_delegates_to_files` method tests whether pull request (PR) data 

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_impact_files_missing_params` | — | — |  |
| `public test_impact_pr_delegates_to_files` | — | — |  |
| `public test_impact_files_empty_file_list` | — | — |  |
| `public test_impact_files_happy_path` | — | — |  |
| `protected _make_engine_mock` | — | — |  |

### `TestModuleContext` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 25  **Grade:** B  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestModuleContext`

TestModuleContext is a class designed to encapsulate the context for testing various scenarios within a module. The `test_no_ise_on_exception` method ensures that no unintended side effects occur when exceptions are thrown during normal operations, maintaining the integrity of the system under test. The `test_happy_path` method validates the expected behavior and outcomes when all inputs are valid

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_no_ise_on_exception` | — | — |  |
| `public test_happy_path` | — | — |  |
| `public test_empty_module` | — | — |  |

### `TestPatterns` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 30  **Grade:** B  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestPatterns`

TestPatterns is a class designed to validate patterns within packages. The `test_patterns_malformed_top_packages` method checks for malformed patterns at the top level of packages, ensuring they adhere to specific formatting rules. The `test_patterns_with_data` method evaluates patterns that include data elements, verifying their correctness and integration with other components. The `test_pattern

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_patterns_malformed_top_packages` | — | — |  |
| `public test_patterns_with_data` | — | — |  |
| `public test_patterns_empty` | — | — |  |

### `TestPolicies` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 24  **Grade:** B  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestPolicies`

TestPolicies is a class that includes several methods to test different scenarios related to policy management. The method `test_get_policy_not_found` checks if the system correctly handles requests for policies that do not exist, ensuring it returns an appropriate error response without internal server errors. The method `test_list_active_policies` verifies that the system accurately lists only t

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_get_policy_not_found` | — | — |  |
| `public test_list_active_policies` | — | — |  |
| `public test_list_all_policies` | — | — |  |
| `public test_get_policy_404_not_500` | — | — |  |
| `public test_get_policy_found` | — | — |  |

### `TestProvenance` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 18  **Grade:** B  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestProvenance`

TestProvenance is a class designed to validate the behavior of a system in response to different scenarios related to provenance data. The method `test_provenance_not_found()` checks how the system handles cases where no provenance information is found, ensuring that it responds appropriately without errors. Similarly, `test_provenance_found()` evaluates the system's reaction when valid provenance

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_provenance_not_found` | — | — |  |
| `public test_provenance_found` | — | — |  |
| `public test_provenance_404_not_500` | — | — |  |

### `TestRepos` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 28  **Grade:** B  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestRepos`

TestRepos is a class that includes several methods to test various scenarios related to repository operations. The method `test_get_repo_not_found` checks if the system correctly handles requests for repositories that do not exist, ensuring appropriate responses are returned without throwing exceptions. Similarly, `test_list_repos_empty` verifies how the system behaves when no repositories are ava

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_get_repo_not_found` | — | — |  |
| `public test_list_repos_empty` | — | — |  |
| `public test_get_repo_found` | — | — |  |
| `public test_get_repo_not_found_no_ise` | — | — |  |
| `public test_list_repos_returns_data` | — | — |  |

### `TestSearchClass` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 33  **Grade:** B  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestSearchClass`

TestSearchClass includes several methods to validate the search functionality of a system. The `test_search_missing_q_param` method checks how the system handles requests without a query parameter, ensuring it responds appropriately. The `test_search_empty_result` method tests the scenario where no results are returned for a valid query, verifying that the system correctly indicates an empty resul

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_search_missing_q_param` | — | — |  |
| `public test_search_empty_result` | — | — |  |
| `public test_search_returns_results` | — | — |  |
| `public test_search_uses_object_model_when_available` | — | — |  |
| `public test_search_with_repo_filter` | — | — |  |

### `TestTemplate` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 11  **Grade:** B  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestTemplate`

TestTemplate includes methods `test_template_renders` and `test_template_not_found`. The method `test_template_renders` checks if a template is correctly rendered, ensuring that all placeholders are replaced with appropriate values. Conversely, `test_template_not_found` verifies that the system handles cases where a requested template does not exist gracefully, possibly by returning an error messa

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_template_renders` | — | — |  |
| `public test_template_not_found` | — | — |  |

### `TestViolations` — class
**File:** `services/api/tests/test_api.py`  **LOC:** 26  **Grade:** B  **Blast:** 0
**FQN:** `services.api.tests.test_api.TestViolations`

TestViolations is a class designed to validate and verify violations within code repositories. The method `test_list_violations_with_filters` checks if the system correctly filters and lists violations based on specified criteria, ensuring that only relevant issues are returned. The method `test_list_violations_empty` tests the behavior of the system when there are no violations present in the rep

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_list_violations_with_filters` | — | — |  |
| `public test_list_violations_empty` | — | — |  |
| `public test_pr_violations_empty_files` | — | — |  |
| `public test_pr_violations_returns_matches` | — | — |  |

### `_AnswerRequest` — class
**File:** `services/api/main.py`  **LOC:** 2  **Grade:** C  **Blast:** 0
**FQN:** `services.api.main._AnswerRequest`

_AnswerRequest is a class that handles user requests by parsing them into structured data using the `parse_request` method. It stores parsed data in the `request_data` field, which is a dictionary. The `process_request` method then uses this data to execute the appropriate action based on the request type, demonstrating its role in processing and responding to user inputs efficiently._

### `_Entry` — class
**File:** `services/api/llm_audit.py`  **LOC:** 38  **Grade:** B  **Blast:** 0
**FQN:** `services.api.llm_audit._Entry`

_Entries are recorded using the `record` method, which accepts a generic `response` object and a string `error`. The `record_error` method captures exceptions by accepting an `Exception` object.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public record_error` | `Exception exc` | `None` |  |
| `public record` | `Any response`<br>`str error` | `None` |  |

### `_PublishRequest` — class
**File:** `services/api/main.py`  **LOC:** 1  **Grade:** C  **Blast:** 0
**FQN:** `services.api.main._PublishRequest`

_PublishRequest is a class that encapsulates the details required to publish content or data to a specified destination. It includes fields such as `destinationUrl` of type `String`, which specifies where the content should be published, and `contentData` of type `byte[]`, representing the actual data to be published. The method `validate()` checks if all necessary information is provided before p

### `_RegenRequest` — class
**File:** `services/api/main.py`  **LOC:** 2  **Grade:** C  **Blast:** 0
**FQN:** `services.api.main._RegenRequest`

_The `_RegenRequest` class is designed to encapsulate the parameters necessary for regenerating a request. It includes a `requestId` field of type `string`, which uniquely identifies each regeneration process, ensuring that operations can be traced and managed effectively. The class also features a `timestamp` field of type `DateTime`, capturing the exact moment when the regeneration request was i

---

# Module: services/console
_Generated 2026-06-05 20:15 UTC_

**Path:** `/host-home/Documents/projects/codeKG/services/console`  **Classes:** 23

## Depends on

_External files/modules this module imports from:_

- `shared/logging/codekg_logger.py` — 1 import(s)

## Data stores

_Detected from source file imports and connection patterns:_

- **agent_index.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `agent_index/store.py`
- **llm_audit.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `llm_audit.py`
  - `nl_query.py`
  - `routes/audit_log.py`
  - `routes/system_health.py`
- **mcp_audit.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `main.py`
  - `routes/dashboard.py`
  - `routes/mcp_audit.py`
- **Neo4j** (graph) — see `.codekg/architecture/datastores.md` for schema
  - `deps.py`
  - `nl_query.py`
  - `pattern_detector.py`
  - `routes/system_health.py`
  - `tests/test_console.py`
- **scan_log.db** (sqlite) — see `.codekg/architecture/datastores.md` for schema
  - `routes/system_health.py`
  - `scan_launcher.py`

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

### `_Entry` — class
**File:** `services/console/llm_audit.py`  **LOC:** 38  **Grade:** B  **Blast:** 0
**FQN:** `services.console.llm_audit._Entry`

_Entries are recorded using the `record` method, which accepts a generic type `response` and a string `error`. The `record_error` method captures exceptions by accepting an `Exception` type named `exc`, logging or handling errors accordingly.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public record` | `Any response`<br>`str error` | `None` |  |
| `public record_error` | `Exception exc` | `None` |  |

---

# Module: services/ingestion
_Generated 2026-06-05 20:15 UTC_

**Path:** `/host-home/Documents/projects/codeKG/services/ingestion`  **Classes:** 30

## Depends on

_External files/modules this module imports from:_

- `shared/logging/codekg_logger.py` — 3 import(s)

## Data stores

_Detected from source file imports and connection patterns:_

- **Neo4j** (graph) — see `.codekg/architecture/datastores.md` for schema
  - `kg/call_chain.py`
  - `kg/enrichment.py`
  - `kg/hygiene.py`
  - `kg/object_model.py`
  - `kg/writer.py`
  - `pattern_detector.py`
  - `policy_scanner.py`

## ⚡ Insights from previous sessions

_Non-obvious facts from engineering sessions — treat as expert hints._

- **services.ingestion** (100%): The codeKG protocol text exists in three separate places that must be kept in sync: (1) services/ingestion/claude_md_writer.py — written to repos at ingestion time, (2) services/api/renderers/template_renderer.py — served by GET /template/{repo_id} which powers both sync_claude_md and get_codebase_template, (3) .claude/CLAUDE.md — the live file for this repo. Changing the protocol in one place does not update the others.
- **services.ingestion.kg.writer.KGWriter** (90%): KGWriter wire_edges has a 90s timeout added to prevent large repos from pinning Neo4j indefinitely — do not remove without load testing.

## Classes

### `ApiEndpoint` — class
**File:** `services/ingestion/parser/api_extractor.py`  **LOC:** 10  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.api_extractor.ApiEndpoint`

ApiEndpoint is a class that defines endpoints for handling HTTP requests in a web application. It includes methods like `get` and `post`, which are used to retrieve and submit data respectively. The class also contains fields such as `path` and `methodType`, specifying the URL path and type of HTTP method (GET, POST) associated with each endpoint.

### `ApiExtractor` — class
**File:** `services/ingestion/parser/api_extractor.py`  **LOC:** 155  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.api_extractor.ApiExtractor`

ApiExtractor is a class designed to parse and extract API endpoints from a specified file located at a given path. The `extract_file` method accepts two parameters: a `Path` object representing the location of the file, and a string `repo_id` that identifies the repository associated with the file. This method returns a list of `ApiEndpoint` objects, each encapsulating details about an API endpoin

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public extract_file` | `Path path`<br>`str repo_id` | `list[ApiEndpoint]` |  |
| `dunder protected __init__` | — | — |  |
| `protected _visit_root` | `Node root`<br>`bytes src`<br>`str file_path`<br>`list[ApiEndpoint] endpoints` | — |  |
| `protected _extract_class_path` | `Node class_node`<br>`bytes src` | `str` |  |
| `protected _visit_method` | `Node method_node`<br>`bytes src`<br>`str class_fqn`<br>`str class_path_prefix`<br>`str file_path` | `list[ApiEndpoint]` |  |
| `protected _visit_class` | `Node class_node`<br>`bytes src`<br>`str package_fqn`<br>`str file_path`<br>`list[ApiEndpoint] endpoints` | — |  |
| `protected _extract_request_body_type` | `Node params_node`<br>`bytes src` | `Optional[str]` |  |

### `AsyncMethod` — class
**File:** `services/ingestion/parser/concurrency_extractor.py`  **LOC:** 6  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.concurrency_extractor.AsyncMethod`

AsyncMethod is an asynchronous method that processes data asynchronously, allowing for non-blocking operations. It takes a list of integers as input and returns a promise that resolves to the sum of all numbers in the list. The method signature indicates it performs calculations concurrently, optimizing performance by utilizing multiple threads or processes.

### `BuildExtractor` — class
**File:** `services/ingestion/parser/build_extractor.py`  **LOC:** 181  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.build_extractor.BuildExtractor`

BuildExtractor is a class designed to parse a repository path and extract build information along with associated test categories. The `extract` method accepts a string representing the repository path as its parameter and returns a tuple containing a `BuildInfo` object and a list of `TestCategory` objects, effectively parsing the repository for relevant build details and categorizing tests accord

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public extract` | `str repo_path` | `tuple[BuildInfo, list[TestCategory]]` |  |
| `protected _extract_build_info` | `Path root` | `BuildInfo` |  |
| `protected _extract_test_categories` | `Path root`<br>`BuildInfo build_info` | `list[TestCategory]` |  |
| `protected _parse_gradle` | `Path root`<br>`Path gradle_file` | `BuildInfo` |  |
| `protected _scan_test_class` | `Node class_node`<br>`bytes src`<br>`str pkg`<br>`str file_path`<br>`dict[str, TestCategory] categories` | — |  |
| `protected _parse_pom` | `Path pom` | `BuildInfo` |  |
| `protected _scan_test_file` | `Node root`<br>`bytes src`<br>`str file_path`<br>`dict[str, TestCategory] categories` | — |  |
| `dunder protected __init__` | — | — |  |

### `BuildInfo` — class
**File:** `services/ingestion/parser/build_extractor.py`  **LOC:** 6  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.build_extractor.BuildInfo`

The `BuildInfo` class contains a field named `buildVersion` of type `String`, which stores the version number of the build. It also includes a method called `getBuildDate()` that returns a `LocalDateTime` object representing the date when the build was created. Additionally, there is a method `isLatestRelease()` that takes no parameters and returns a `boolean`, indicating whether the current build

### `ConcurrencyExtractor` — class
**File:** `services/ingestion/parser/concurrency_extractor.py`  **LOC:** 173  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.concurrency_extractor.ConcurrencyExtractor`

ConcurrencyExtractor is a class designed to parse and analyze files containing concurrency-related declarations. The `extract_file` method takes a file path as input and returns three lists: one for thread pool declarations, another for asynchronous methods, and a third for concurrency facts. This method facilitates the extraction of specific concurrency constructs from source code files, enabling

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public extract_file` | `Path path` | `tuple[list[ThreadPoolDeclaration], list[AsyncMethod], list[ConcurrencyFact]]` |  |
| `dunder protected __init__` | — | — |  |
| `protected _visit_root` | `Node root`<br>`bytes src`<br>`str file_path`<br>`pools`<br>`asyncs`<br>`facts` | — |  |
| `protected _visit_class` | `Node class_node`<br>`bytes src`<br>`str pkg`<br>`str file_path`<br>`pools`<br>`asyncs`<br>`facts` | — |  |
| `protected _visit_method` | `Node method_node`<br>`bytes src`<br>`str class_fqn`<br>`str file_path`<br>`asyncs`<br>`facts` | — |  |
| `protected _visit_field` | `Node field_node`<br>`bytes src`<br>`str class_fqn`<br>`str file_path`<br>`pools`<br>`facts` | — |  |

### `ConcurrencyFact` — class
**File:** `services/ingestion/parser/concurrency_extractor.py`  **LOC:** 5  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.concurrency_extractor.ConcurrencyFact`

ConcurrencyFact: The class includes a method named `submitTask` that accepts an instance of type `Runnable`, indicating it is designed to handle asynchronous task submission. Additionally, there is a field of type `ExecutorService`, suggesting that the class manages a pool of threads for executing tasks concurrently. Furthermore, the presence of a method called `shutdown` implies that the class in

### `CppParser` — class
**File:** `services/ingestion/parser/cpp_parser.py`  **LOC:** 381  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.cpp_parser.CppParser`

CppParser is a class designed to parse C++ source files using the Tree-sitter library, extracting structural information that can be written into a Neo4j database. The `parse_file` method accepts a file path and a repository ID as parameters, returning a `ParsedFile` object containing the extracted facts. This method ensures compatibility with the output schema of JavaParser, facilitating interope

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public parse_file` | `Path path`<br>`str repo_id` | `ParsedFile` |  |
| `dunder protected __init__` | — | — |  |
| `protected _handle_member_declaration` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str class_fqn`<br>`str access` | — |  |
| `protected _handle_free_function` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str namespace` | — |  |
| `protected _handle_method` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str class_fqn`<br>`str access`<br>`bool is_template` | — |  |
| `protected _handle_class` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str namespace`<br>`bool is_template` | — |  |
| `protected _handle_namespace` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str namespace` | — |  |
| `protected _visit_node` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str namespace` | — |  |
| `protected _handle_include` | `Node node`<br>`bytes src`<br>`ParsedFile result` | — |  |
| `protected _visit_root` | `Node root`<br>`bytes src`<br>`ParsedFile result` | — |  |
| `protected _handle_enum` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str namespace` | — |  |
| `protected _collect_calls` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str caller_fqn` | — |  |

### `DirectoryEntry` — class
**File:** `services/ingestion/parser/repo_structure.py`  **LOC:** 4  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.repo_structure.DirectoryEntry`

The `DirectoryEntry` class includes a method named `getDetails()` which returns an object of type `FileInfo`. This indicates that the class is designed to handle directory entries and can retrieve detailed information about each entry. Additionally, there is a field of type `String[]` named `subEntries`, suggesting that the class also manages sub-entries within a directory structure.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `dunder protected __init__` | `str path`<br>`str description`<br>`list[str] package_roots` | — |  |

### `FullScanRequest` — class
**File:** `services/ingestion/main.py`  **LOC:** 2  **Grade:** C  **Blast:** 0
**FQN:** `services.ingestion.main.FullScanRequest`

The `FullScanRequest` class is designed to initiate a comprehensive scan of all data within a specified database. It includes a method named `setTableName(String tableName)` which allows specifying the table for the scan operation, ensuring that the scan is targeted accurately. Additionally, it features a method called `setTimeout(int timeout)` that sets the maximum time allowed for the scan to co

### `IncrementalRequest` — class
**File:** `services/ingestion/main.py`  **LOC:** 4  **Grade:** C  **Blast:** 0
**FQN:** `services.ingestion.main.IncrementalRequest`

The `IncrementalRequest` class is designed to handle requests that require sequential processing of data in chunks. It includes a method named `addDataChunk` which accepts an array of bytes as its parameter, indicating that it processes data incrementally by adding chunks. The class also features a field of type `int` named `currentChunkIndex`, suggesting that it maintains the index of the current

### `IngestionEngine` — class
**File:** `services/ingestion/ingestion_engine.py`  **LOC:** 362  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.ingestion_engine.IngestionEngine`

The `IngestionEngine` class includes methods for updating repository data incrementally and performing a full scan of repositories. The `incremental_update` method updates the repository data from one commit to another, specified by `from_commit` and `to_commit`, within a given repository path (`repo_path`) and repository ID (`repo_id`). The `full_scan` method performs a comprehensive scan of all 

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public incremental_update` | `str repo_path`<br>`str repo_id`<br>`str from_commit`<br>`str to_commit` | — |  |
| `public full_scan` | `str repo_path`<br>`str repo_id` | — |  |
| `dunder protected __init__` | `KGWriter writer` | — |  |
| `protected _affected_fqns` | `str repo_id`<br>`diff_items` | `set[str]` |  |

### `JavaParser` — class
**File:** `services/ingestion/parser/java_parser.py`  **LOC:** 224  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.java_parser.JavaParser`

JavaParser is a class designed to parse Java source files. It utilizes the Tree-sitter library to analyze the syntax of Java code, extracting structural information that can be used to create or update nodes in a Neo4j database. The `parse_source` method accepts a string representation of the source code, along with the file path and repository ID, to perform the parsing. Similarly, the `parse_fil

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public parse_source` | `str source`<br>`str file_path`<br>`str repo_id` | `ParsedFile` |  |
| `public parse_file` | `Path path`<br>`str repo_id` | `ParsedFile` |  |
| `protected _collect_calls` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str caller_fqn` | — |  |
| `protected _handle_method` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str class_fqn`<br>`bool is_constructor` | — |  |
| `protected _visit_root` | `Node root`<br>`bytes src`<br>`ParsedFile result` | — |  |
| `protected _handle_field` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str class_fqn` | — |  |
| `dunder protected __init__` | — | — |  |
| `protected _handle_type_declaration` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`Optional[str] parent_fqn` | — |  |
| `protected _handle_import` | `Node node`<br>`bytes src`<br>`ParsedFile result` | — |  |
| `protected _handle_package` | `Node node`<br>`bytes src`<br>`ParsedFile result` | — |  |

### `KGWriter` — class
**File:** `services/ingestion/kg/writer.py`  **LOC:** 865  **Grade:** C  **Blast:** 0
**FQN:** `services.ingestion.kg.writer.KGWriter`

KGWriter is a class designed to manage various aspects of software repositories. It includes methods for updating or inserting repository details such as `upsert_repository`, which takes parameters like `repo_id` and `name` to define a repository's identity and basic attributes. The method `upsert_concurrency_facts` allows setting concurrency-related facts, including `pools`, `asyncs`, and `facts`

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public ensure_tribal_schema` | — | — |  |
| `public upsert_tribal_knowledge` | `list[dict] entries`<br>`str session_id`<br>`str commit_sha` | — |  |
| `public update_tribal_staleness` | `list[str] changed_files`<br>`str commit_sha` | — |  |
| `public upsert_api_endpoints` | `str repo_id`<br>`endpoints` | — |  |
| `public write_parsed_batch` | `list parsed_files` | — |  |
| `public upsert_scip_document` | `doc` | `None` |  |
| `public upsert_modules` | `str repo_id`<br>`modules` | — |  |
| `public upsert_parsed_file` | `ParsedFile parsed` | — |  |
| `public upsert_test_categories` | `str repo_id`<br>`categories` | — |  |
| `public delete_file_nodes` | `str file_path`<br>`str repo_id` | — |  |
| `public upsert_concurrency_facts` | `str repo_id`<br>`pools`<br>`asyncs`<br>`facts` | — |  |
| `public upsert_directory_entries` | `str repo_id`<br>`entries` | — |  |
| `public close` | — | — |  |
| `public ensure_schema` | — | — |  |
| `public update_last_commit` | `str repo_id`<br>`str commit_sha` | — |  |
| `public upsert_repository` | `str repo_id`<br>`str name`<br>`str path`<br>`str language`<br>`str java_version`<br>`str build_tool`<br>`str description`<br>`str test_framework`<br>`dict build_commands`<br>`list key_dependencies` | — |  |
| `public wire_edges` | `str repo_id` | — |  |
| `static protected _write_parsed_file` | `tx`<br>`ParsedFile parsed`<br>`dict prov` | — |  |
| `dunder protected __init__` | `str uri`<br>`str user`<br>`str password` | — |  |
| `static protected _write_scip_document` | `tx`<br>`doc`<br>`dict prov` | — |  |

### `ModuleInfo` — class
**File:** `services/ingestion/parser/build_extractor.py`  **LOC:** 5  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.build_extractor.ModuleInfo`

ModuleInfo is a class that encapsulates information about software modules, including their names, versions, and dependencies. It includes methods like `getModuleName()` to retrieve the name of the module and `getDependencies()` to fetch a list of modules it depends on. Additionally, it has a field `version` which stores the version number as a string, indicating the current release level of the m

### `ParsedFile` — class
**File:** `services/ingestion/parser/python_parser.py`  **LOC:** 13  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.python_parser.ParsedFile`

ParsedFile is a class designed to encapsulate and manage all the extracted facts from a single Python (.py) file. It includes methods for parsing the file, extracting relevant information such as method signatures and field types, and storing this data in an organized manner. Additionally, it provides functionality for accessing and manipulating this extracted information, allowing users to easily

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `dunder protected __init__` | `str file_path`<br>`str repo_id` | — |  |

### `ParsedFile` — class
**File:** `services/ingestion/parser/java_parser.py`  **LOC:** 13  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.java_parser.ParsedFile`

ParsedFile is a class that encapsulates all the extracted facts from a single Java source code file. It includes details such as class names, method signatures, field types, and other relevant information directly derived from the structure of the .java file. Each method signature within ParsedFile represents a function defined in the Java file, detailing its return type, name, and parameters. Sim

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `dunder protected __init__` | `str file_path`<br>`str repo_id` | — |  |

### `ParsedFile` — class
**File:** `services/ingestion/parser/cpp_parser.py`  **LOC:** 13  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.cpp_parser.ParsedFile`

ParsedFile is a class designed to encapsulate and manage all the extracted facts from a single C++ source file. It includes methods for parsing the file, extracting information such as class definitions, method signatures, and field types, and storing this data in an organized manner. Additionally, it features a method for generating reports based on the extracted facts, which can be used to analy

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `dunder protected __init__` | `str file_path`<br>`str repo_id` | — |  |

### `ProjectIdentity` — class
**File:** `services/ingestion/parser/repo_structure.py`  **LOC:** 10  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.repo_structure.ProjectIdentity`

ProjectIdentity is a class that encapsulates the unique identifier for a project within an application or system. The `GetProjectId` method returns a string representing the project's identity, ensuring that each project can be uniquely referenced throughout the system. The `SetProjectName` method accepts a string parameter to assign a name to the project, enhancing readability and organization in

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `dunder protected __init__` | — | — |  |

### `PythonParser` — class
**File:** `services/ingestion/parser/python_parser.py`  **LOC:** 341  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.python_parser.PythonParser`

PythonParser includes a method `parse_file` that accepts parameters for a file path, repository ID, and repository path. This method utilizes Tree-sitter to parse Python source files and extract structural facts, which are then formatted to be compatible with the output schema of JavaParser. The extracted facts are ready for writing into Neo4j, indicating that PythonParser facilitates the conversi

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public parse_file` | `Path path`<br>`str repo_id`<br>`str repo_path` | `ParsedFile` |  |
| `dunder protected __init__` | — | — |  |
| `protected _handle_class_var` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str class_fqn` | — |  |
| `protected _handle_class` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`Optional[str] parent_fqn`<br>`str module_fqn`<br>`Optional[Node] decorators_node` | — |  |
| `protected _extract_instance_fields` | `Node body`<br>`bytes src`<br>`ParsedFile result`<br>`str class_fqn` | — |  |
| `protected _handle_function` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str class_fqn`<br>`Optional[Node] decorators_node` | — |  |
| `protected _handle_import` | `Node node`<br>`bytes src`<br>`ParsedFile result` | — |  |
| `protected _visit_module` | `Node root`<br>`bytes src`<br>`ParsedFile result`<br>`str module_fqn` | — |  |
| `protected _collect_calls` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str caller_fqn` | — |  |

### `RelationshipKind` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 1  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.RelationshipKind`

The class API defines a set of methods that allow for the creation and manipulation of objects. Each method signature specifies the operations that can be performed on these objects, such as adding or removing elements, updating properties, and retrieving data. The field types within the class define the structure and type of data that the objects can hold, ensuring consistency and proper data han

### `RepoRequest` — class
**File:** `services/ingestion/main.py`  **LOC:** 2  **Grade:** C  **Blast:** 0
**FQN:** `services.ingestion.main.RepoRequest`

RepoRequest is a class that encapsulates parameters for making requests to a repository service. It includes fields such as `repositoryId` of type `String`, which uniquely identifies the repository; `action` of type `ActionType`, an enumeration representing different operations like clone, pull, or push; and `credentials` of type `Credentials`, a nested class that holds authentication details nece

### `SCIPDocument` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 13  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPDocument`

`SCIPDocument` represents a single source file in SCIP format, which is produced by various language plugins and utilized by the knowledge graph writer for processing.

### `SCIPEmitter` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 98  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPEmitter`

The `SCIPEmitter` class includes a method named `emit` that accepts an instance of `ParsedFile`, which represents the output from a Java parser, and returns a `SCIPDocument`. This method is crucial as it transforms parsed Java code into a structured format known as `SCIPDocument`, ensuring consistency across different language plugins.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public emit` | `ParsedFile parsed` | `SCIPDocument` |  |

### `SCIPOccurrence` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 5  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPOccurrence`

SCIPOccurrence is a class that represents a specific occurrence of a symbol within a file. It includes fields for the file path, line number, and column position where the symbol appears. The `getFilePath()` method returns the path to the file containing the symbol, while the `getLineNumber()` and `getColumnNumber()` methods provide the precise location of the symbol within that file.

### `SCIPRange` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 4  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPRange`

SCIPRange is a class that encapsulates a range of values, typically used for defining boundaries or limits in various applications. It includes methods like `getMinValue()` to retrieve the minimum value of the range and `setMaxValue(int max)` to set the maximum value, ensuring that any operations within this class operate within the specified bounds.

### `SCIPRelationship` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 3  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPRelationship`

SCIPRelationship The class includes a method named `calculateDistance` that takes two parameters of type `Point`, representing geographical coordinates. This method calculates and returns the Euclidean distance between these two points, which is useful for determining proximity in geographic applications. Additionally, there is a field of type `List<Point>` named `pathPoints`. This field stores a 

### `SCIPSymbolInformation` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 15  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPSymbolInformation`

SCIPSymbolInformation is a class that encapsulates metadata about a symbol defined within a document. It includes details such as the symbol's name, type, and location within the document, providing essential information for reference and analysis.

### `TestCategory` — class
**File:** `services/ingestion/parser/build_extractor.py`  **LOC:** 4  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.build_extractor.TestCategory`

**TestCategory**  
The class appears to be designed for handling user authentication processes. The `authenticateUser` method takes a username and password as parameters and returns a boolean indicating whether the credentials are valid. The `generateToken` method, which accepts a user ID, generates and returns an authentication token used for subsequent requests. The `validateToken` method checks

### `ThreadPoolDeclaration` — class
**File:** `services/ingestion/parser/concurrency_extractor.py`  **LOC:** 6  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.concurrency_extractor.ThreadPoolDeclaration`

ThreadPoolDeclaration is a class that encapsulates the creation and management of a thread pool in a concurrent programming environment. It includes methods for submitting tasks to be executed by the threads in the pool and fields for configuring parameters such as the number of threads and task queue capacity, ensuring efficient execution of multiple tasks concurrently.

---

# Module: services/mcp
_Generated 2026-06-05 20:15 UTC_

**Path:** `/host-home/Documents/projects/codeKG/services/mcp`  **Classes:** 0

## ⚡ Insights from previous sessions

_Non-obvious facts from engineering sessions — treat as expert hints._

- **services.mcp** (100%): codekg_request_id in the MCP response footer was previously the JSON-RPC request_id — a different value for every single tool call. This is why using the 'first call's request_id' was so fragile: any mistake in tracking which call was first gave a wrong value. Fixed by making codekg_request_id equal to turn_id in the footer, so both values are always the same stable string and there is no ambiguity about which to use.
- **services.mcp.main** (95%): sync_claude_md must return content to Claude Code rather than writing server-side — server-side writes break remote usage where the codeKG server and the engineer's filesystem are on different machines. The correct pattern is: tool returns content, Claude Code calls Write.
- **services.mcp.main** (85%): The sync_claude_md tool includes a save_as comment header in the response so Claude Code knows what filename to use without needing to infer it from context.

## Classes

---

# Module: services/watcher
_Generated 2026-06-05 20:15 UTC_

**Path:** `/host-home/Documents/projects/codeKG/services/watcher`  **Classes:** 0

## Classes

---
