# Neo4j Schema

> The knowledge graph stores a structural and semantic model of every registered repository. All queries must include `repo_id` — the same database instance serves multiple repos.

---

## Node labels

### `Class`

The primary node type. Represents a class, interface, enum, record, or module-level file.

| Property | Type | Example | Notes |
|----------|------|---------|-------|
| `repo_id` | String | `"codeKG"` | Always filter by this |
| `fqn` | String | `"services.api.impact.engine.ImpactEngine"` | Fully-qualified name — unique per repo |
| `name` | String | `"ImpactEngine"` | Short class name |
| `kind` | String | `"class"` | `class`, `interface`, `enum`, `record`, `module` |
| `role` | String | `"CLASS"` | `CLASS`, `INTERFACE`, `ENUM`, `TEST`, `GENERATED` |
| `file_path` | String | `/host-home/code/my-service/services/api/impact/engine.py` | Absolute path |
| `package_fqn` | String | `"services.api.impact.engine"` | Parent package |
| `start_line` | Integer | `1` | First line in source file |
| `end_line` | Integer | `254` | Last line — LOC = `end_line - start_line` |
| `hygiene_grade` | String | `"A"` | A, B, C, D, or F |
| `hygiene_score` | Float | `92.5` | 0–100 |
| `hygiene_tier` | String | `"small"` | `small`, `medium`, `large` |
| `blast_size` | Integer | `8` | Number of classes that depend on this one |
| `blast_radius` | List[String] | `["shared.logging.codekg_logger"]` | FQNs of dependent classes |
| `coupling` | Float | `0.04` | Import fan-out normalised by repo size |
| `object_model` | JSON String | `{"fqn": "...", "methods": [...]}` | Complete structural snapshot |
| `summary` | String | `"ImpactEngine computes..."` | LLM-generated one-sentence description |
| `javadoc` | String | `"..."` | Extracted docstring / javadoc |
| `annotations` | List[String] | `["RestController", "RequestMapping"]` | Class-level annotations |
| `modifiers` | List[String] | `["public", "abstract"]` | Access modifiers |
| `prov_source_tool` | String | `"tree-sitter-java"` | Which parser wrote this node |
| `prov_commit_sha` | String | `"5185bf1"` | Commit when last parsed |
| `prov_freshness_ts` | String | `"2026-06-05T20:34:00Z"` | When last updated |
| `prov_confidence` | Float | `0.85` | Parser confidence score |

```cypher
-- Find all classes in a module by file path prefix
MATCH (c:Class {repo_id: "codeKG"})
WHERE c.file_path STARTS WITH "/host-home/code/my-service/services/api"
  AND NOT c.kind IN ["module"]
RETURN c.name, c.fqn, c.hygiene_grade, c.blast_size
ORDER BY c.blast_size DESC
```

---

### `Method`

One node per method or function. Linked to its Class via `HAS_METHOD`.

| Property | Type | Example |
|----------|------|---------|
| `repo_id` | String | `"codeKG"` |
| `fqn` | String | `"services.api.impact.engine.ImpactEngine#compute"` |
| `name` | String | `"compute"` |
| `class_fqn` | String | `"services.api.impact.engine.ImpactEngine"` |
| `parameters` | List[String] | `["str repo_id", "list[str] changed_files", "Optional[str] commit_sha"]` |
| `return_type` | String | `"ImpactReport"` |
| `modifiers` | List[String] | `["public"]` |
| `annotations` | List[String] | `[]` |
| `docstring` | String | `"Compute blast radius for changed files."` |
| `start_line` | Integer | `45` |
| `end_line` | Integer | `89` |
| `calls_unresolved` | List[String] | `["_directly_affected", "_transitive_dependents"]` |

> **Note:** `object_model` on the `Class` node is richer than `Method` nodes. The `methods` array in `object_model` includes `summary` which Method nodes lack. Use `object_model` for agent index generation; use `Method` nodes for relationship traversal.

```cypher
-- All methods of a class
MATCH (c:Class {repo_id: "codeKG", fqn: $fqn})-[:HAS_METHOD]->(m:Method)
RETURN m.name, m.parameters, m.return_type, m.modifiers
ORDER BY m.name
```

---

### `Module`

Logical module — typically maps to a `services/xxx` directory with its own build config.

| Property | Type | Example |
|----------|------|---------|
| `repo_id` | String | `"codeKG"` |
| `module_id` | String | `"services/api"` |
| `name` | String | `"services/api"` |
| `path` | String | `/host-home/code/my-service/services/api` |
| `build_tool` | String | `"python"` |
| `pkg_prefix` | String | `"api"` |
| `auto` | Boolean | `true` |

```cypher
-- All modules for a repo
MATCH (m:Module {repo_id: "codeKG"})
RETURN m.module_id, m.name, m.path
ORDER BY m.module_id
```

---

### `Package`

Python package or Java package node. Classes belong to packages.

| Property | Type | Example |
|----------|------|---------|
| `repo_id` | String | `"codeKG"` |
| `fqn` | String | `"services.api.impact"` |
| `name` | String | `"impact"` |

---

### `Repository`

One node per registered repo. Carries repo-level hygiene and metadata.

| Property | Type | Example |
|----------|------|---------|
| `repo_id` | String | `"codeKG"` |
| `name` | String | `"codeKG"` |
| `path` | String | `/host-home/code/my-service` |
| `language` | String | `"python"` |
| `build_tool` | String | `"python"` |
| `hygiene_grade` | String | `"B"` |
| `hygiene_score` | Float | `74.4` |
| `last_commit` | String | `"5185bf1"` |
| `test_framework` | String | `"pytest"` |

---

### `ArchPolicy`

An architectural constraint — either manually defined or auto-generated by policy scanning.

| Property | Type | Example |
|----------|------|---------|
| `repo_id` | String | `"codeKG"` |
| `policy_id` | String | `"auto-403ee21d"` |
| `title` | String | `"Untested Package"` |
| `natural_language` | String | `"Every production package with 3+ classes should have at least one test class"` |
| `cypher_constraint` | String | `"MATCH (p:Package {repo_id: 'codeKG'})-[:CONTAINS]->(c:Class) WHERE NOT..."` |
| `severity` | String | `"warning"` | `info`, `warning`, `error` |
| `source` | String | `"auto-scan"` | `auto-scan`, `manual` |
| `status` | String | `"auto-draft"` | `active`, `auto-draft`, `disabled` |
| `violator_count` | Integer | `8` |
| `sample_violators` | List[String] | `["services.console.routes", "shared.models.graph"]` |

```cypher
-- All active policies
MATCH (ap:ArchPolicy {repo_id: "codeKG"})
WHERE ap.status = "active"
RETURN ap.policy_id, ap.title, ap.severity, ap.violator_count
ORDER BY ap.severity DESC, ap.violator_count DESC
```

---

### `ArchPattern`

A detected architectural pattern or anti-pattern (Repository, Factory, Singleton, Test Case, etc.).

| Property | Type | Example |
|----------|------|---------|
| `repo_id` | String | `"codeKG"` |
| `pattern_id` | String | `"python-test-case-codeKG"` |
| `name` | String | `"Test Case"` |
| `category` | String | `"Testing"` |
| `intent` | String | `"Classes inheriting from unittest.TestCase..."` |
| `anti_pattern` | Boolean | `false` |
| `source` | String | `"Python"` |
| `match_count` | Integer | `34` |
| `severity` | String | `"info"` |
| `top_packages` | JSON String | `[{"package": "services.console.tests", "count": 13}]` |

---

### `TribalKnowledge`

Non-obvious facts captured by agents during coding sessions. The institutional memory layer.

| Property | Type | Example |
|----------|------|---------|
| `repo_id` | String | `"codeKG"` |
| `tk_id` | String | `"tk_a3b9f1c2d4e5"` |
| `insight` | String | `"The wire_edges method has a 90-second timeout..."` |
| `applies_to` | String | `"services.ingestion.kg.writer.KGWriter"` | Dot-separated FQN |
| `scope` | String | `"method"` | `system`, `module`, `class`, `method` |
| `confidence` | Float | `0.9` |
| `session_id` | String | `"a3f9c1b2"` |
| `saved_at` | String | `"2026-06-05T20:34:11Z"` |
| `staleness` | Float | `0.0` | Increases when related files change |
| `last_touched_commit` | String | `"5185bf1"` |

```cypher
-- All insights for a module (handles both path formats)
MATCH (tk:TribalKnowledge {repo_id: "codeKG"})
WHERE tk.applies_to CONTAINS "services.api"
   OR tk.applies_to CONTAINS "services/api"
RETURN tk.applies_to, tk.insight, tk.confidence
ORDER BY tk.confidence DESC
```

> **Path format:** `applies_to` stores dot-separated FQNs (`services.api.main`) but the module registry uses slash-separated IDs (`services/api`). Always match against both forms when querying by module.

---

## Relationships

| From | Relationship | To | Notes |
|------|--------------|----|-------|
| `Class` | `:HAS_METHOD` | `Method` | One per method in the class |
| `Class` | `:BELONGS_TO` | `Package` | Class → its package |
| `Class` | `:IMPORTS` | `Class` | Resolved import dependency |
| `Class` | `:EXHIBITS` | `ArchPattern` | Class matches a pattern |
| `Class` | `:VIOLATES` | `ArchPolicy` | Class violates a policy |
| `Package` | `:CONTAINS` | `Class` | Package → its classes |
| `Package` | `:CONTAINS` | `Enum` | Package → its enums |
| `Repository` | `:HAS_MODULE` | `Module` | Repo → logical modules |
| `Method` | `:CALLS` | `Method` | Resolved method call |
| `TribalKnowledge` | `:APPLIES_TO` | `Class` | Insight attached to class |
| `TribalKnowledge` | `:APPLIES_TO` | `Package` | Insight attached to package |

---

## Common query patterns

```cypher
-- Classes that import a given class (direct dependents)
MATCH (caller:Class {repo_id: $repo_id})-[:IMPORTS]->(c:Class {repo_id: $repo_id, fqn: $fqn})
RETURN caller.fqn, caller.hygiene_grade, caller.blast_size
ORDER BY caller.blast_size DESC

-- All classes in a specific file
MATCH (c:Class {repo_id: $repo_id, file_path: $file_path})
RETURN c.fqn, c.kind, c.start_line, c.end_line

-- Classes with failing hygiene (grade C or worse)
MATCH (c:Class {repo_id: $repo_id})
WHERE c.hygiene_grade IN ["C", "D", "F"]
  AND NOT c.kind IN ["module"]
RETURN c.name, c.fqn, c.hygiene_grade, c.hygiene_score
ORDER BY c.hygiene_score ASC

-- Policy violations with class details
MATCH (c:Class {repo_id: $repo_id})-[:VIOLATES]->(ap:ArchPolicy {repo_id: $repo_id})
WHERE ap.status = "active"
RETURN c.fqn, ap.title, ap.severity
ORDER BY ap.severity DESC

-- Insights for a class, ordered by confidence
MATCH (tk:TribalKnowledge {repo_id: $repo_id})
WHERE tk.applies_to = $fqn
   OR tk.applies_to CONTAINS $class_name
RETURN tk.insight, tk.confidence, tk.scope, tk.saved_at
ORDER BY tk.confidence DESC

-- Module-level dependency graph
MATCH (a:Class {repo_id: $repo_id})-[:IMPORTS]->(b:Class {repo_id: $repo_id})
WITH a.file_path AS from_path, b.file_path AS to_path, count(*) AS edge_count
RETURN from_path, to_path, edge_count
ORDER BY edge_count DESC LIMIT 20

-- Top 10 blast radius classes
MATCH (c:Class {repo_id: $repo_id})
WHERE c.blast_size > 0 AND NOT c.kind IN ["module"]
RETURN c.name, c.fqn, c.blast_size, c.hygiene_grade
ORDER BY c.blast_size DESC LIMIT 10
```

---

## Index and constraints

Created by `KGWriter.ensure_schema()` on first run:

```cypher
CREATE CONSTRAINT class_fqn_unique IF NOT EXISTS
  FOR (c:Class) REQUIRE (c.repo_id, c.fqn) IS UNIQUE;

CREATE CONSTRAINT method_fqn_unique IF NOT EXISTS
  FOR (m:Method) REQUIRE (m.repo_id, m.fqn) IS UNIQUE;

CREATE INDEX class_repo IF NOT EXISTS FOR (c:Class) ON (c.repo_id);
CREATE INDEX class_file_path IF NOT EXISTS FOR (c:Class) ON (c.file_path);
CREATE INDEX method_class_fqn IF NOT EXISTS FOR (m:Method) ON (m.class_fqn);
```

---

## Multi-repo isolation

Every node carries `repo_id`. There is no cross-repo relationship. Querying without `repo_id` returns data from all repos — always include it:

```cypher
-- WRONG: returns classes from all repos
MATCH (c:Class) WHERE c.name = "UserService" RETURN c

-- CORRECT: scoped to one repo
MATCH (c:Class {repo_id: "myPT"}) WHERE c.name = "UserService" RETURN c
```

The console UI enforces this via the `selected_repo` cookie. The API enforces it by requiring `repo_id` on all endpoints. The MCP tools enforce it by making `repo_id` a required parameter.

---

## File LOC calculation

```cypher
-- LOC per file (max end_line across all Class nodes with that file_path)
-- Only covers .py/.java files with at least one indexed class
MATCH (c:Class {repo_id: $repo_id})
WHERE c.end_line IS NOT NULL AND c.end_line > 0
WITH c.file_path AS fp, max(c.end_line) AS loc
RETURN fp, loc
ORDER BY loc DESC
```

HTML templates and non-Python/Java files have no Class nodes and therefore no LOC data in the KG. Use disk file sizes as fallback for those.
