# Module: services/console
_Generated 2026-06-03 20:10 UTC_

**Path:** `/host-home/Documents/projects/codeKG/services/console`  
**Classes:** 23

## All classes

_Full list sorted by blast radius (impact if changed). Grade A=clean, F=needs attention._

| Class | Kind | Grade | Blast | Methods | Description |
|---|---|---|---|---|---|
| `RequestLogMiddleware` | class | C | 0 | 1 | The `RequestLogMiddleware` class includes a method named `dispatch`, which accepts two parameters: a `Request` object an |
| `TestAnnotationRequired` | class | B | 0 | 3 | TestAnnotationRequired is a class that includes methods for testing various aspects of annotation processing. The `test_ |
| `TestAsk` | class | B | 0 | 6 | TestAsk is a class that includes several methods to test various scenarios related to an API endpoint designed for askin |
| `TestAuditLog` | class | B | 0 | 1 | TestAuditLog is a class that includes a method named `test_audit_page_renders`. This method is designed to verify that a |
| `TestClassesPage` | class | B | 0 | 9 | TestClassesPage includes methods for testing various aspects of a classes page, such as sorting classes by name or blast |
| `TestControllerRepoRestriction` | class | B | 0 | 2 | The `TestControllerRepoRestriction` class includes methods for testing API endpoints without direct access and for stand |
| `TestDashboard` | class | B | 0 | 4 | TestDashboard includes methods to validate the rendering of a dashboard, its behavior when no data is present in the kno |
| `TestLayerMustNotDependOn` | class | B | 0 | 3 | TestLayerMustNotDependOn is a class that includes methods for testing various aspects of FQN (Fully Qualified Name) hand |
| `TestMcpAudit` | class | B | 0 | 4 | TestMcpAudit is a class that includes several methods to validate the behavior of an audit API for a system named MCP (l |
| `TestModuleMustNotCall` | class | B | 0 | 4 | TestModuleMustNotCall ensures that no service tests are called directly, promoting isolation. It validates FQN (Fully Qu |
| `TestModulesPage` | class | B | 0 | 5 | TestModulesPage is a class designed to perform various tests related to module management within an application. The `te |
| `TestOutputSafety` | class | B | 0 | 1 | TestOutputSafety ensures that curly braces within input data do not lead to a key error by implementing a robust validat |
| `TestPatternCatalog` | class | B | 0 | 8 | TestPatternCatalog is a class designed to perform various tests on a catalog system. The `test_catalog_toggle_off` metho |
| `TestPatternsPage` | class | B | 0 | 2 | The `TestPatternsPage` class includes methods for detecting patterns through a POST request (`test_patterns_detect_post` |
| `TestPoliciesPage` | class | B | 0 | 9 | The `TestPoliciesPage` class includes several methods to validate various aspects of a policies page in an application.  |
| `TestPublicMethodAnnotation` | class | B | 0 | 4 | TestPublicMethodAnnotation is a class that includes several methods to validate the behavior of public method annotation |
| `TestReposPage` | class | B | 0 | 16 | TestReposPage is a class that includes several methods for testing various functionalities related to repository managem |
| `TestServiceMustNotExtend` | class | B | 0 | 1 | TestServiceMustNotExtend is a class that includes a method named `test_basic_match`. This method does not take any param |
| `TestSystemHealth` | class | B | 0 | 2 | TestSystemHealth includes methods to verify that the system health API returns JSON data and that the system health page |
| `TestToContainerPath` | class | B | 0 | 3 | The `TestToContainerPath` class contains methods to verify different scenarios for converting host paths to container pa |
| `TestUnknownPolicy` | class | B | 0 | 4 | TestUnknownPolicy is a class that includes several methods to validate the behavior of placeholder text in various scena |
| `TestValidateRepoPath` | class | B | 0 | 4 | TestValidateRepoPath is a class designed to validate Git repository paths. The method `test_nonexistent_path` checks if  |
| `_Entry` | class | B | 0 | 2 | _Entries are recorded using the `record` method, which accepts a generic type `response` and a string `error`. The `reco |

## Dependency map

**This module imports from:**
- `shared/logging/codekg_logger.py` (1 imports)
