# Ingestion & Knowledge Graph

> The ingestion service parses source files using tree-sitter, extracts structural information, and writes a semantic graph of classes, methods, modules, dependencies, and architectural patterns into Neo4j.

---

## How ingestion works

Ingestion runs as an ephemeral Docker container — one container per repo per scan. The watcher launches it, it runs to completion, then exits. There is no persistent ingestion process.

There are two scan modes:

**Full scan** — used for new repos or forced rescans. Walks the entire file tree, parses every supported source file, writes all nodes and edges.

**Incremental update** — used for commits on watched repos. Compares `from_commit` to `to_commit` using git diff, identifies changed files, re-parses only those files, deletes stale nodes for modified files before re-inserting.

```python
# Entry point: services/ingestion/ingestion_engine.py

class IngestionEngine:
    def full_scan(self, repo_path: str, repo_id: str) -> None: ...
    def incremental_update(
        self,
        repo_path: str,
        repo_id: str,
        from_commit: str,
        to_commit: str,
    ) -> None: ...
```

---

## Parsing pipeline

Each source file goes through three stages:

```
source file (.py / .java)
       │
       ▼
  Language parser (tree-sitter)
       │  extracts: classes, methods, fields, imports, packages
       │  produces: ParsedFile dataclass
       ▼
  KGWriter.upsert_parsed_file()
       │  writes: Class, Method, Package, Enum nodes
       │  sets: properties (fqn, kind, modifiers, start_line, end_line, annotations)
       ▼
  KGWriter.wire_edges()
       │  resolves: IMPORTS, HAS_METHOD, BELONGS_TO edges
       │  timeout: 90 seconds (prevents Neo4j lock on large repos)
       ▼
  Post-processors
       │  hygiene scoring
       │  object_model JSON assembly
       │  blast radius computation
       │  pattern detection
       │  policy scanning
```

---

## Language support

### Python parser (`parser/python_parser.py`)

Uses tree-sitter-python. Extracts:
- Classes with base classes, decorators, docstrings
- Methods with parameters (including type annotations), return types, modifiers
- Module-level functions treated as standalone classes
- Import statements for IMPORTS edge resolution

```python
# Example: parsing a Python class
source = '''
class ImpactEngine:
    def compute(self, repo_id: str, changed_files: list[str]) -> ImpactReport:
        ...
'''
parser = PythonParser()
result = parser.parse_source(source, "services/api/impact/engine.py", "codeKG")
# result.classes[0].fqn == "services.api.impact.engine.ImpactEngine"
# result.classes[0].methods[0].parameters == ["str repo_id", "list[str] changed_files"]
# result.classes[0].methods[0].return_type == "ImpactReport"
```

### C++ parser (`parser/cpp_parser.py`)

Uses tree-sitter-cpp. Extracts:
- Classes, structs, templates, enums
- Inheritance (`EXTENDS` edges) for single and multiple bases
- Methods with return types, parameters, and modifiers (`virtual`, `static`, `const`, access specifiers)
- Constructors and destructors
- Member fields
- Free functions (collected under a synthetic module class)
- `#include` directives for `IMPORTS` edges
- `CALLS` edges from method bodies
- Doxygen `/** */` and `///` doc comments

### JavaScript / TypeScript parser (`parser/js_parser.py`)

Uses tree-sitter-javascript and tree-sitter-typescript. Extracts:
- ES6 classes, TypeScript interfaces, enums, and type aliases
- Inheritance (`EXTENDS`) and interface implementation (`IMPLEMENTS`) edges
- Methods with modifiers (`async`, `static`, `get`, `set`) and TS return types
- TypeScript decorators on classes and methods
- Class fields (including TS access modifiers)
- Module-level function declarations and arrow/function-expression `const` assignments
- `export` and `module.exports` patterns
- ES module `import` statements for `IMPORTS` edges
- `CALLS` edges from method bodies
- JSDoc `/** */` comments

> **Dependency note:** tree-sitter-javascript and tree-sitter-typescript are installed via PyPI (`pip install tree-sitter-javascript tree-sitter-typescript`). They are compiled wheels — no system tooling required.

### Salesforce Apex parser (`parser/apex_parser.py`)

Uses tree-sitter-sfapex (compiled from source — no PyPI package). Extracts:
- Classes, interfaces, enums, triggers
- Sharing model (`with sharing` / `without sharing` / `inherited sharing`) in modifiers
- Abstract and `@IsTest` classes (`kind = abstract_class` / `test_class`)
- Methods with return types, parameters, and Apex annotations (`@AuraEnabled`, `@InvocableMethod`, etc.)
- Constructors
- Inner classes
- `SOQL` queries detected in method bodies → `QUERIES` edges
- `CALLS` edges from method bodies
- Triggers: emitted as synthetic classes (`kind = trigger`); sObject and events stored as annotations

> **Dependency note:** tree-sitter-sfapex has no PyPI package. The grammar `.so` is compiled from [aheber/tree-sitter-sfapex](https://github.com/aheber/tree-sitter-sfapex) using `gcc`. For local development, the compiled `tree_sitter_apex.so` lives in `services/ingestion/parser/` alongside the parser source (it is `.gitignore`d — each developer must compile it once). In Docker / CI, the Dockerfile and CI workflow compile it automatically.
>
> **Local setup (one-time):**
> ```bash
> git clone --depth=1 https://github.com/aheber/tree-sitter-sfapex.git /tmp/tree-sitter-sfapex
> gcc -shared -fPIC -o services/ingestion/parser/tree_sitter_apex.so \
>   /tmp/tree-sitter-sfapex/apex/src/parser.c
> ```

### Java parser (`parser/java_parser.py`)

Uses tree-sitter-java. Extracts:
- Classes, interfaces, enums, records
- Methods with full parameter types and return types
- Annotations (@Override, @SpringBootTest, custom)
- Package declarations and import statements
- Constructor detection

```java
// Example: what gets extracted from Java
@RestController
@RequestMapping("/api/users")
public class UserController {
    @GetMapping("/{id}")
    public ResponseEntity<User> getUser(@PathVariable Long id) { ... }
}

// Produces:
// Class node: fqn="com.example.UserController", kind="class", annotations=["RestController"]
// Method node: name="getUser", parameters=["Long id"], return_type="ResponseEntity", annotations=["GetMapping"]
// ApiEndpoint node: path="/api/users/{id}", method="GET", handler_fqn="...getUser"
```

---

## The KGWriter

`services/ingestion/kg/writer.py` — 865 LOC, grade C (complex but tested)

The KGWriter is the sole writer to Neo4j during ingestion. All mutations go through it. It uses Cypher `MERGE ... ON CREATE SET ... ON MATCH SET ...` for idempotent upserts — running ingestion twice on the same repo produces identical graph state.

Key methods:

| Method | Purpose |
|--------|---------|
| `ensure_schema()` | Creates indexes and constraints on first run |
| `upsert_parsed_file(parsed)` | Writes one file's worth of nodes in a transaction |
| `write_parsed_batch(files)` | Bulk write with parallel transactions |
| `wire_edges(repo_id)` | Resolves all IMPORTS, HAS_METHOD, BELONGS_TO edges |
| `upsert_modules(repo_id, modules)` | Writes Module nodes from build extractor output |
| `upsert_tribal_knowledge(entries, session_id, commit_sha)` | Writes insights captured by agents |
| `delete_file_nodes(file_path, repo_id)` | Removes stale nodes before incremental re-parse |

> **⚠ `wire_edges` has a 90-second timeout.** Do not remove it — it prevents large repos from pinning Neo4j indefinitely.

---

## Enrichment passes

After parsing, several enrichment passes run in order:

### Hygiene scoring (`kg/hygiene.py`)

Computes a letter grade (A–F) and numeric score (0–100) for each class based on:
- Lines of code (penalizes large classes)
- Method count
- Docstring / javadoc presence
- Test coverage presence
- Coupling (import fan-out)

```cypher
// Hygiene grade stored on Class node
MATCH (c:Class {repo_id: $repo_id, fqn: $fqn})
RETURN c.hygiene_grade, c.hygiene_score, c.hygiene_tier
// → "B", 74, "medium"
```

### Object model assembly (`kg/object_model.py`)

Builds a JSON blob stored on each Class node containing the complete structural snapshot:

```json
{
  "fqn": "services.api.impact.engine.ImpactEngine",
  "name": "ImpactEngine",
  "kind": "class",
  "methods": [
    {
      "name": "compute",
      "return_type": "ImpactReport",
      "parameters": ["str repo_id", "list[str] changed_files", "Optional[str] commit_sha"],
      "modifiers": ["public"],
      "annotations": [],
      "summary": null
    }
  ]
}
```

This is richer than the separate Method nodes — it is the primary source for agent index method tables.

### Blast radius (`kg/enrichment.py`)

For each class, computes how many other classes transitively depend on it via IMPORTS edges. Stored as `blast_size` (integer) and `blast_radius` (array of dependent FQNs) on the Class node.

```python
# Classes with blast_size > 10 are flagged as hotspots
# codekg_logger has blast_size=8 — the highest in this repo
# All service classes have blast_size=0 because Python import chain
# resolution doesn't yet follow transitive imports across modules
```

### Pattern detection (`pattern_detector.py`)

Scans the graph for known architectural patterns (Test Case, Repository, Factory, Singleton, etc.) and writes `ArchPattern` nodes with match counts and top packages. Both patterns and anti-patterns are detected.

```cypher
MATCH (ap:ArchPattern {repo_id: $repo_id})
RETURN ap.name, ap.category, ap.match_count, ap.anti_pattern
ORDER BY ap.match_count DESC
// → "Test Case", "Testing", 34, false
// → "Repository", "Data Access", 12, false
```

### Policy scanning (`policy_scanner.py`)

Evaluates each `ArchPolicy` node's `cypher_constraint` against the graph and writes `VIOLATES` edges between violating classes and their policies.

---

## Build extractor

`parser/build_extractor.py` — detects build tooling and extracts module boundaries.

For Python repos: looks for `pyproject.toml`, `setup.py`, `requirements.txt` per directory.
For Java repos: looks for `pom.xml` (Maven) or `build.gradle` (Gradle).

Produces `Module` nodes with:
- `module_id` (e.g. `services/api`)
- `path` (absolute path on disk)
- `build_tool` (python, maven, gradle)
- `pkg_prefix` (Python package root for import resolution)

```python
extractor = BuildExtractor()
build_info, test_categories = extractor.extract("/path/to/repo")
# build_info.build_tool == "python"
# build_info.modules == [ModuleInfo(id="services/api", path="..."), ...]
```

---

## Concurrency model

The ingestion container is single-process. No threading. Operations are sequential:

1. `full_scan` or `incremental_update`
2. Enrichment passes (hygiene → object_model → blast_radius)
3. Pattern detection
4. Policy scanning
5. Container exits

The watcher checks for a running container with `codekg.repo_id` Docker label before launching a new one — prevents overlapping scans on the same repo.

---

## Adding a new language

1. Create `parser/my_language_parser.py` implementing:
   ```python
   class MyParser:
       def parse_file(self, path: Path, repo_id: str) -> ParsedFile: ...
       def parse_source(self, source: str, file_path: str, repo_id: str) -> ParsedFile: ...
   ```
2. Register it in `ingestion_engine.py` extension dispatch
3. Add tree-sitter grammar to `requirements.txt`
4. KGWriter handles the rest — it is language-agnostic

**If the grammar has no PyPI package** (like Apex), use the lazy-load + native `.so` pattern:
- Wrap grammar initialisation in a `_load_<lang>_language()` function; do **not** call it at import time
- Support an env var override for the `.so` path, with the parser directory as the local default
- Add the compiled `.so` to `.gitignore`
- Add `gcc` + compile steps to both the Dockerfile and `.github/workflows/ci.yml`
- In tests, probe by calling the loader function inside a `try/except` block — a bare `import` will succeed even when the `.so` is absent

---

## Common failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `wire_edges` times out | Repo > ~5k classes with dense import graph | Increase timeout in `kg/writer.py` or run in batches |
| Scan container exits immediately | Wrong `repo_path` (case mismatch on Linux) | Normalise last path component to lowercase |
| Classes missing from graph | File extension not in parser dispatch | Add to extension map in `ingestion_engine.py` |
| Blast radius all zeros | Import chain not resolved past first hop | Known limitation — transitive resolution not yet implemented |
| Duplicate nodes on re-scan | `delete_file_nodes` not called before incremental | Ensure `from_commit` differs from current HEAD |
