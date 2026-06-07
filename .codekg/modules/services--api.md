# Module: services/api
_Generated 2026-06-07 16:52 UTC · commit `unpublished`_

**Path:** `/host-home/Documents/projects/codeKG/services/api`  **Classes:** 23

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

### `_DefaultZero` — class
**File:** `services/api/agent_index/generator.py`  **LOC:** 1  **Grade:** B  **Blast:** 0
**FQN:** `services.api.agent_index.generator._DefaultZero`

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `dunder protected __missing__` | `key` | — |  |

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
