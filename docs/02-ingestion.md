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

---

## Common failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `wire_edges` times out | Repo > ~5k classes with dense import graph | Increase timeout in `kg/writer.py` or run in batches |
| Scan container exits immediately | Wrong `repo_path` (case mismatch on Linux) | Normalise last path component to lowercase |
| Classes missing from graph | File extension not in parser dispatch | Add to extension map in `ingestion_engine.py` |
| Blast radius all zeros | Import chain not resolved past first hop | Known limitation — transitive resolution not yet implemented |
| Duplicate nodes on re-scan | `delete_file_nodes` not called before incremental | Ensure `from_commit` differs from current HEAD |
