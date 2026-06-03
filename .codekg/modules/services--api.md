# Module: services/api
_Generated 2026-06-03 20:01 UTC_

**Path:** `/host-home/Documents/projects/codeKG/services/api`  
**Classes:** 22

## All classes

_Full list sorted by blast radius (impact if changed). Grade A=clean, F=needs attention._

| Class | Kind | Grade | Blast | Methods | Description |
|---|---|---|---|---|---|
| `ImpactEngine` | class | A | 0 | 11 | ImpactEngine computes impact reports for code changes by executing Cypher queries on a graph database. It accepts a repo |
| `ImpactReport` | class | B | 0 | 1 | ImpactReport is a class that includes a method named `to_dict()`. This method converts an instance of ImpactReport into  |
| `ImpactedEndpoint` | class | B | 0 | 0 | ImpactedEndpoint is a class that encapsulates details about an endpoint affected by some system operation. It includes a |
| `ImpactedNode` | class | B | 0 | 0 | ImpactedNode is a class that encapsulates information about nodes in a network or graph structure. It includes fields su |
| `ImpactedPolicy` | class | B | 0 | 0 | ImpactedPolicy is a class that encapsulates policies related to resource access control within an application. It includ |
| `RequestLogMiddleware` | class | C | 0 | 1 | `RequestLogMiddleware` is a middleware component designed to log details of each HTTP request processed by an applicatio |
| `SuggestedTest` | class | B | 0 | 0 | SuggestedTest is a class that includes methods for setting up test environments and running tests. The `initializeEnviro |
| `TestClassContext` | class | B | 0 | 5 | `TestClassContext` is a class designed to handle various scenarios related to testing class loading and fallback mechani |
| `TestFeatureContext` | class | B | 0 | 2 | The `TestFeatureContext` class includes methods to validate feature behavior. The `test_feature_returns_list()` method c |
| `TestImpactFiles` | class | B | 0 | 5 | TestImpactFiles is a class designed to validate the behavior of methods related to file impact analysis in software deve |
| `TestModuleContext` | class | B | 0 | 3 | TestModuleContext is a class designed to encapsulate the context for testing various scenarios within a module. The `tes |
| `TestPatterns` | class | B | 0 | 3 | TestPatterns is a class designed to validate patterns within packages. The `test_patterns_malformed_top_packages` method |
| `TestPolicies` | class | B | 0 | 5 | TestPolicies is a class that includes several methods to test different scenarios related to policy management. The meth |
| `TestProvenance` | class | B | 0 | 3 | TestProvenance is a class designed to validate the behavior of a system in response to different scenarios related to pr |
| `TestRepos` | class | B | 0 | 5 | TestRepos is a class that includes several methods to test various scenarios related to repository operations. The metho |
| `TestSearchClass` | class | B | 0 | 5 | TestSearchClass includes several methods to validate the search functionality of a system. The `test_search_missing_q_pa |
| `TestTemplate` | class | B | 0 | 2 | TestTemplate includes methods `test_template_renders` and `test_template_not_found`. The method `test_template_renders`  |
| `TestViolations` | class | B | 0 | 4 | TestViolations is a class designed to validate and verify violations within code repositories. The method `test_list_vio |
| `_AnswerRequest` | class | C | 0 | 0 | _AnswerRequest is a class that handles user requests by parsing them into structured data using the `parse_request` meth |
| `_Entry` | class | B | 0 | 2 | _Entries are recorded using the `record` method, which accepts a generic `response` object and a string `error`. The `re |
| `_PublishRequest` | class | C | 0 | 0 | _PublishRequest is a class that encapsulates the details required to publish content or data to a specified destination. |
| `_RegenRequest` | class | C | 0 | 0 | _The `_RegenRequest` class is designed to encapsulate the parameters necessary for regenerating a request. It includes a |

## Dependency map

**This module imports from:**
- `shared/logging/codekg_logger.py` (4 imports)
