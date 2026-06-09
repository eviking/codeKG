# Module: services/ingestion
_Generated 2026-06-09 20:27 UTC · commit `unpublished`_

**Path:** `/host-home/Documents/projects/codeKG/services/ingestion`  **Classes:** 39

## Depends on

_External files/modules this module imports from:_

- `codeKG/shared/config.py` — 1 import(s)

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
- **services.ingestion.policy_scanner** (95%): Policy detectors in policy_scanner.py only fire against the *running* container's code — seeding new detectors requires either a container rebuild or manually calling `_save_policy()` via cypher. The 6 new open-source-checklist policies (undocumented-module, undocumented-high-blast, public-method-no-doc, console-imports-ingestion, mcp-imports-neo4j, duplicate-class-names) were seeded directly into Neo4j as `status='active'` with `source='manual'` so they are visible in the console and agent index immediately. On the next `docker compose up --build ingestion`, the auto-scan will MERGE over them (policy_id stable via sha1 hash), so the manual seed is safe to leave.

```python
# policy_scanner.py _stable_id()
def _stable_id(repo_id: str, key: str) -> str:
    h = hashlib.sha1(f"{repo_id}:{key}".encode()).hexdigest()[:8]
    return f"auto-{h}"
# BUT manually seeded policies use "policy-<name>" ids, not "auto-<hash>"
# so they will NOT be overwritten by auto-scan — they persist as separate nodes
```

When a manually seeded policy and an auto-scan policy cover the same concern, the KG will have two nodes. Use the same `_stable_id()` key when seeding manually, or accept the duplicate and delete the manual one after first auto-scan.
- **services.ingestion.kg.writer.KGWriter** (90%): KGWriter wire_edges has a 90s timeout added to prevent large repos from pinning Neo4j indefinitely — do not remove without load testing.

## Classes

### `ApiEndpoint` — class
**File:** `services/ingestion/parser/api_extractor.py`  **LOC:** 12  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.api_extractor.ApiEndpoint`

Describes an HTTP endpoint inferred from source annotations or route declarations. Watch out for the handler fields here, because later graph edges rely on them to join endpoints back to code.

### `ApiExtractor` — class
**File:** `services/ingestion/parser/api_extractor.py`  **LOC:** 157  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.api_extractor.ApiExtractor`

Extracts API surface area from supported source trees. Watch out for framework-specific heuristics here, because false positives here become durable endpoint nodes in the graph.

### `AsyncMethod` — class
**File:** `services/ingestion/parser/concurrency_extractor.py`  **LOC:** 8  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.concurrency_extractor.AsyncMethod`

Captures a method that appears to run asynchronously. Watch out for heuristic detection here, because async behavior is often inferred from framework annotations rather than explicit syntax alone.

### `BuildExtractor` — class
**File:** `services/ingestion/parser/build_extractor.py`  **LOC:** 287  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.build_extractor.BuildExtractor`

Inspects repository build files and test layouts to infer tooling. Watch out for mixed-language repos here, because this extractor is optimized for Java conventions and falls back heuristically elsewhere.

### `BuildInfo` — class
**File:** `services/ingestion/parser/build_extractor.py`  **LOC:** 8  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.build_extractor.BuildInfo`

Summarizes the build and test stack discovered for a repository. Watch out for default values here, because downstream prompts assume these fields are always populated sensibly.

### `ConcurrencyExtractor` — class
**File:** `services/ingestion/parser/concurrency_extractor.py`  **LOC:** 175  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.concurrency_extractor.ConcurrencyExtractor`

Scans source trees for concurrency patterns and hazards. Watch out for framework bias here, because different languages expose async behavior through very different idioms.

### `ConcurrencyFact` — class
**File:** `services/ingestion/parser/concurrency_extractor.py`  **LOC:** 7  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.concurrency_extractor.ConcurrencyFact`

Normalizes one concurrency-related signal before it is written to the graph. Watch out for confidence and source details here, because many of these facts are best-effort inferences.

### `CppParser` — class
**File:** `services/ingestion/parser/cpp_parser.py`  **LOC:** 397  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.cpp_parser.CppParser`

Parses C++ source files using Tree-sitter and extracts structural facts ready for writing into Neo4j. Output schema is compatible with JavaParser.

### `DirectoryEntry` — class
**File:** `services/ingestion/parser/repo_structure.py`  **LOC:** 6  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.repo_structure.DirectoryEntry`

Represents one directory discovered while classifying repository structure. Watch out for recursive expansion here, because callers use these entries to decide what parts of a repo deserve deeper parsing.

### `IngestionEngine` — class
**File:** `services/ingestion/ingestion_engine.py`  **LOC:** 361  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.ingestion_engine.IngestionEngine`

Coordinates repository scans from parsing through graph writes. Watch out for batch sizing and timeout behavior here, because this class is where large-repo performance problems tend to surface first.

### `JavaParser` — class
**File:** `services/ingestion/parser/java_parser.py`  **LOC:** 224  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.java_parser.JavaParser`

Parses Java source files using Tree-sitter and extracts structural facts ready for writing into Neo4j.

### `KGWriter` — class
**File:** `services/ingestion/kg/writer.py`  **LOC:** 860  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.kg.writer.KGWriter`

Writes parsed facts into Neo4j as CodeKG nodes and edges. Watch out for idempotency and batching here, because this class sits on the boundary between noisy source code and durable graph state.

### `ModuleInfo` — class
**File:** `services/ingestion/parser/build_extractor.py`  **LOC:** 7  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.build_extractor.ModuleInfo`

Represents one discovered module or service directory. Watch out for name and path normalization here, because later index generation uses this object to build stable file names.

### `ParsedFile` — class
**File:** `services/ingestion/parser/java_parser.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.java_parser.ParsedFile`

Holds all extracted facts from a single .java file.

### `ParsedFile` — class
**File:** `services/ingestion/parser/python_parser.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.python_parser.ParsedFile`

Holds all extracted facts from a single .py file.

### `ParsedFile` — class
**File:** `services/ingestion/parser/cpp_parser.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.cpp_parser.ParsedFile`

Holds all extracted facts from a single C++ file.

### `ProjectIdentity` — class
**File:** `services/ingestion/parser/repo_structure.py`  **LOC:** 12  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.repo_structure.ProjectIdentity`

Describes the high-level identity of a scanned project. Watch out for naming stability here, because several downstream artifacts use this object to label generated summaries.

### `PythonParser` — class
**File:** `services/ingestion/parser/python_parser.py`  **LOC:** 343  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.python_parser.PythonParser`

Parses Python source files using Tree-sitter and extracts structural facts ready for writing into Neo4j. Output schema is compatible with JavaParser.

### `RelationshipKind` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 3  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.RelationshipKind`

Names supported relationship kinds in emitted SCIP symbol information. Watch out for spelling changes here, because consumers treat these strings as wire-format values.

### `RepoRequest` — class
**File:** `services/ingestion/main.py`  **LOC:** 4  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.main.RepoRequest`

Validates ingestion requests for a repository path and identifier. Watch out for trust boundaries here, because these values come from external callers and drive filesystem access.

### `SCIPDocument` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPDocument`

SCIP representation of one source file. Produced by language plugins; consumed by the KG writer.

### `SCIPEmitter` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 98  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPEmitter`

Converts a ParsedFile (Java parser output) to a SCIPDocument. All language plugins must produce SCIPDocument — this is the contract.

### `SCIPOccurrence` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 5  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPOccurrence`

A use of a symbol at a specific location in the file.

### `SCIPRange` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 6  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPRange`

Represents a source range in SCIP coordinates. Watch out for line and character indexing here, because off-by-one errors make downstream navigation frustrating fast.

### `SCIPRelationship` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 5  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPRelationship`

Represents a relationship attached to symbol information. Watch out for directionality here, because consumers use these links to reconstruct hierarchy and inheritance.

### `SCIPSymbolInformation` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 15  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPSymbolInformation`

Metadata about a symbol defined in this document.

### `TestBlastScoring` — class
**File:** `services/ingestion/tests/test_hygiene.py`  **LOC:** 23  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.tests.test_hygiene.TestBlastScoring`

Exercises blast scoring behavior in the hygiene test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_no_dependents_full_score` | — | — |  |
| `public test_high_blast_zero_score` | — | — |  |
| `public test_moderate_blast_partial_score` | — | — |  |

### `TestBuildExtractorDetection` — class
**File:** `services/ingestion/tests/test_build_extractor.py`  **LOC:** 67  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.tests.test_build_extractor.TestBuildExtractorDetection`

Exercises build extractor detection behavior in the build extractor test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestCategory` — class
**File:** `services/ingestion/parser/build_extractor.py`  **LOC:** 6  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.build_extractor.TestCategory`

Groups tests by annotation or base-class signal. Watch out for the description text here, because it is surfaced directly in generated onboarding material.

### `TestClassExtraction` — class
**File:** `services/ingestion/tests/test_python_parser.py`  **LOC:** 194  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.tests.test_python_parser.TestClassExtraction`

Exercises class extraction behavior in the python parser test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestClassScore` — class
**File:** `services/ingestion/tests/test_hygiene.py`  **LOC:** 28  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.tests.test_hygiene.TestClassScore`

Exercises class score behavior in the hygiene test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_score_clamped_to_valid_range` | — | — |  |
| `public test_god_class_scores_low` | — | — |  |
| `public test_perfect_class_scores_100` | — | — |  |

### `TestCouplingScoring` — class
**File:** `services/ingestion/tests/test_hygiene.py`  **LOC:** 17  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.tests.test_hygiene.TestCouplingScoring`

Exercises coupling scoring behavior in the hygiene test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_high_coupling_zero_score` | — | — |  |
| `public test_low_coupling_full_score` | — | — |  |

### `TestDocsScoring` — class
**File:** `services/ingestion/tests/test_hygiene.py`  **LOC:** 15  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.tests.test_hygiene.TestDocsScoring`

Exercises docs scoring behavior in the hygiene test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_with_docstring_scores_25` | — | — |  |
| `public test_without_docstring_scores_0` | — | — |  |

### `TestExtractModules` — class
**File:** `services/ingestion/tests/test_build_extractor.py`  **LOC:** 48  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.tests.test_build_extractor.TestExtractModules`

Exercises extract modules behavior in the build extractor test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestFullScan` — class
**File:** `services/ingestion/tests/test_ingestion_engine.py`  **LOC:** 82  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.tests.test_ingestion_engine.TestFullScan`

Exercises full scan behavior in the ingestion engine test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestJavaClassExtraction` — class
**File:** `services/ingestion/tests/test_java_parser.py`  **LOC:** 167  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.tests.test_java_parser.TestJavaClassExtraction`

Exercises java class extraction behavior in the java parser test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_interface_kind` | — | — |  |
| `public test_simple_class_methods` | — | — |  |
| `public test_javadoc_extracted` | — | — |  |
| `public test_enum_kind` | — | — |  |
| `public test_empty_source_no_crash` | — | — |  |
| `public test_package_and_imports` | — | — |  |
| `public test_constructor_in_methods` | — | — |  |
| `public test_annotated_class` | — | — |  |

### `TestLetterGrade` — class
**File:** `services/ingestion/tests/test_hygiene.py`  **LOC:** 27  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.tests.test_hygiene.TestLetterGrade`

Exercises letter grade behavior in the hygiene test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_grade_f_boundary` | — | — |  |
| `public test_grade_d_boundary` | — | — |  |
| `public test_grade_c_boundary` | — | — |  |
| `public test_grade_a_boundary` | — | — |  |
| `public test_grade_b_boundary` | — | — |  |

### `TestSizeScoring` — class
**File:** `services/ingestion/tests/test_hygiene.py`  **LOC:** 33  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.tests.test_hygiene.TestSizeScoring`

Exercises size scoring behavior in the hygiene test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_small_class_full_score` | — | — |  |
| `public test_medium_class_partial_score` | — | — |  |
| `public test_large_class_low_score` | — | — |  |
| `public test_god_class_zero_score` | — | — |  |

### `ThreadPoolDeclaration` — class
**File:** `services/ingestion/parser/concurrency_extractor.py`  **LOC:** 8  **Grade:** ?  **Blast:** 0
**FQN:** `services.ingestion.parser.concurrency_extractor.ThreadPoolDeclaration`

Captures a discovered thread-pool declaration. Watch out for sizing fields here, because downstream analysis uses them to flag hidden concurrency hotspots.
