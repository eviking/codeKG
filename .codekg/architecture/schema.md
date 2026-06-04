# Knowledge Graph Schema — codeKG
_Generated 2026-06-04 16:25 UTC_

Use this file to write correct Cypher queries without probing the KG.
All nodes are scoped to a repo via `repo_id` — always include it in MATCH clauses.

## Node labels

### `Class`
| Property | Example value |
|---|---|
| `annotations` | `[]` |
| `blast_radius` | `[]` |
| `blast_size` | `0` |
| `coupling` | `0.04` |
| `end_line` | `0` |
| `file_path` | `/host-home/Documents/projects/codeKG/tools/backfill_javadoc.py` |
| `fqn` | `tools.backfill_javadoc` |
| `hygiene_grade` | `B` |
| `hygiene_score` | `75` |
| `hygiene_tier` | `small` |
| `kind` | `module` |
| `name` | `backfill_javadoc` |
| `object_model` | `{"fqn":"tools.backfill_javadoc","name":"backfill_javadoc","kind":"module","modul` |
| `package_fqn` | `tools` |
| `prov_commit_sha` | `ba59a23d43e4a2e47c419c7d6cbf73f4d9fbdaa3` |
| `prov_confidence` | `0.85` |
| `prov_freshness_ts` | `2026-06-03T21:47:39Z` |
| `prov_source_tool` | `tree-sitter-java` |
| `repo_id` | `codeKG` |
| `role` | `CLASS` |
| `start_line` | `1` |
| `summary` | `The `fetch_classes` method retrieves classes from a repository identified by `re` |
| `summary_model` | `qwen2.5-coder:7b` |
| `summary_ts` | `2026-06-01T19:36:41.095560+00:00` |

### `Method`
| Property | Example value |
|---|---|
| `annotations` | `[]` |
| `calls_unresolved` | `['run', 'session']` |
| `class_fqn` | `tools.backfill_javadoc` |
| `docstring` | `Write javadoc for a batch of {fqn, javadoc} dicts.` |
| `end_line` | `131` |
| `fqn` | `tools.backfill_javadoc#write_batch` |
| `modifiers` | `['public']` |
| `name` | `write_batch` |
| `parameters` | `['driver', 'list[dict] rows']` |
| `prov_commit_sha` | `ba59a23d43e4a2e47c419c7d6cbf73f4d9fbdaa3` |
| `prov_confidence` | `0.85` |
| `prov_freshness_ts` | `2026-06-03T21:47:39Z` |
| `prov_source_tool` | `tree-sitter-java` |
| `repo_id` | `codeKG` |
| `start_line` | `124` |

### `Module`
| Property | Example value |
|---|---|
| `auto` | `True` |
| `build_tool` | `python` |
| `module_id` | `services/api` |
| `name` | `services/api` |
| `path` | `/host-home/Documents/projects/codeKG/services/api` |
| `pkg_prefix` | `api` |
| `prov_commit_sha` | `ba59a23d43e4a2e47c419c7d6cbf73f4d9fbdaa3` |
| `prov_confidence` | `0.95` |
| `prov_freshness_ts` | `2026-06-03T21:47:39Z` |
| `prov_source_tool` | `build-extractor` |
| `repo_id` | `codeKG` |

### `Repository`
| Property | Example value |
|---|---|
| `build_tool` | `unknown` |
| `hygiene_computed_at` | `2026-06-03T21:49:03.591000000+00:00` |
| `hygiene_grade` | `B` |
| `hygiene_score` | `74.4` |
| `hygiene_stats` | `{"repo_score":74.4,"repo_grade":"B","total_classes":153,"scored_classes":116,"go` |
| `key_dependencies` | `[]` |
| `language` | `python` |
| `last_commit` | `51488d529bf8a7c5b5821b2d4a35257efda80a1f` |
| `name` | `codeKG` |
| `path` | `/host-home/Documents/projects/codeKG` |
| `prov_commit_sha` | `ba59a23d43e4a2e47c419c7d6cbf73f4d9fbdaa3` |
| `prov_confidence` | `0.75` |
| `prov_freshness_ts` | `2026-06-03T21:47:38Z` |
| `prov_source_tool` | `repo-structure` |
| `repo_id` | `codeKG` |
| `test_framework` | `junit5` |

### `ArchPolicy`
| Property | Example value |
|---|---|
| `cypher_constraint` | `MATCH (p:Package {repo_id: 'codeKG'})-[:CONTAINS]->(c:Class) WHERE NOT c.fqn CON` |
| `natural_language` | `Every production package with 3 or more classes should have at least one test cl` |
| `policy_id` | `auto-403ee21d` |
| `repo_id` | `codeKG` |
| `sample_violators` | `['services.console.routes', 'shared.models.graph', 'services.ingestion.parser', ` |
| `severity` | `warning` |
| `source` | `auto-scan` |
| `status` | `auto-draft` |
| `title` | `Untested Package` |
| `violator_count` | `8` |

### `ArchPattern`
| Property | Example value |
|---|---|
| `anti_pattern` | `False` |
| `category` | `Testing` |
| `intent` | `Classes inheriting from unittest.TestCase or Django's TestCase providing isolate` |
| `match_count` | `34` |
| `name` | `Test Case` |
| `pattern_id` | `python-test-case-codeKG` |
| `repo_id` | `codeKG` |
| `severity` | `info` |
| `source` | `Python` |
| `top_packages` | `[{"package": "services.console.tests.test_console", "count": 13}, {"package": "s` |

### `TribalKnowledge`
| Property | Example value |
|---|---|
| `applies_to` | `services.console.main` |
| `confidence` | `0.8` |
| `insight` | `The base.html CSS already uses green (#16a34a) as --primary. The blue appearance` |
| `last_touched_commit` | `unknown` |
| `repo_id` | `codeKG` |
| `saved_at` | `2026-06-03T13:43:50.687680+00:00` |
| `scope` | `system` |
| `session_id` | `8e5d8a1e` |
| `staleness` | `0.0` |
| `tk_id` | `tk_f9fd11a79a1d` |

## Relationships

| From | Relationship | To |
|---|---|---|
| `Class` | `:BELONGS_TO` | `Package` |
| `Class` | `:EXHIBITS` | `ArchPattern` |
| `Class` | `:HAS_METHOD` | `Method` |
| `Class` | `:IMPORTS` | `Class` |
| `Enum` | `:BELONGS_TO` | `Package` |
| `Enum` | `:IMPORTS` | `Class` |
| `Method` | `:CALLS` | `Method` |
| `Package` | `:CONTAINS` | `Class` |
| `Package` | `:CONTAINS` | `Enum` |
| `Package` | `:HAS_METHOD` | `Method` |
| `Repository` | `:HAS_MODULE` | `Module` |
| `TribalKnowledge` | `:APPLIES_TO` | `Class` |
| `TribalKnowledge` | `:APPLIES_TO` | `Package` |

## Common query patterns

```cypher
// All classes in a module
MATCH (c:Class {repo_id: $repo_id}) WHERE c.file_path STARTS WITH $module_path RETURN c

// Methods of a class
MATCH (c:Class {repo_id: $repo_id, fqn: $fqn})-[:HAS_METHOD]->(m:Method) RETURN m

// Classes that depend on a given class (blast radius)
MATCH (caller:Class {repo_id: $repo_id})-[:IMPORTS]->(c:Class {repo_id: $repo_id, fqn: $fqn}) RETURN caller

// Active policy violations
MATCH (c:Class {repo_id: $repo_id})-[:VIOLATES]->(ap:ArchPolicy) RETURN c.fqn, ap.name, ap.severity

// Insights for a class or module
MATCH (tk:TribalKnowledge {repo_id: $repo_id}) WHERE tk.applies_to CONTAINS $name RETURN tk ORDER BY tk.confidence DESC
```

**Always filter by `repo_id`** — the KG stores multiple repos in the same database.