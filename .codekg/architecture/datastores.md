# Data Stores — codeKG
_Generated 2026-06-08 13:57 UTC_

**6 data stores detected** by scanning source files.

| Store | Type | Runtime path | Modules |
|-------|------|--------------|---------|
| **Neo4j** | graph | `—` | `services/api`, `services/console`, `services/ingestion` |
| **agent_index.db** | sqlite | `/repos/agent_index.db` | `services/api`, `services/console` |
| **llm_audit.db** | sqlite | `/repos/llm_audit.db` | `services/api`, `services/console` |
| **mcp_audit.db** | sqlite | `/repos/mcp_audit.db` | `services/api`, `services/console` |
| **scan_log.db** | sqlite | `/repos/scan_log.db` | `services/api`, `services/console` |
| **telemetry.db** | sqlite | `/repos/telemetry.db` | `services/api` |

---

## Neo4j (graph)

**Used by:** `services/api`, `services/console`, `services/ingestion`

**Source files:**
- `scripts/repo_backup.py`
- `services/api/agent_index/generator.py`
- `services/api/impact/engine.py`
- `services/api/main.py`
- `services/api/nl_query.py`
- `services/api/renderers/template_renderer.py`
- `services/api/tests/test_api.py`
- `services/console/deps.py`
- `services/console/nl_query.py`
- `services/console/pattern_detector.py`
- `services/console/routes/system_health.py`
- `services/console/tests/test_config_routes.py`
- `services/console/tests/test_console.py`
- `services/ingestion/kg/call_chain.py`
- `services/ingestion/kg/enrichment.py`
- `services/ingestion/kg/hygiene.py`
- `services/ingestion/kg/object_model.py`
- `services/ingestion/kg/writer.py`
- `services/ingestion/pattern_detector.py`
- `services/ingestion/policy_scanner.py`
- `shared/pattern_detector.py`
- `tools/backfill_javadoc.py`
- `tools/summarise_classes.py`

**Schema:** see Neo4j section below for node labels, properties, and relationships.

## agent_index.db (sqlite)

**Runtime path:** `/repos/agent_index.db`
**Used by:** `services/api`, `services/console`

**Source files:**
- `scripts/repo_backup.py`
- `services/api/agent_index/generator.py`
- `services/api/agent_index/store.py`
- `services/api/tests/test_agent_index_generator.py`
- `services/api/tests/test_agent_index_store.py`
- `services/console/agent_index/store.py`
- `services/console/tests/test_config_routes.py`
- `shared/agent_index/store.py`
- `shared/config.py`

**Schema:**

#### `agent_index_files`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PK |
| `repo_id` | TEXT | NOT NULL |
| `file_key` | TEXT | NOT NULL |
| `directory` | TEXT | NOT NULL |
| `filename` | TEXT | NOT NULL |
| `description` | TEXT | — |
| `content` | TEXT | — |
| `manual_additions` | TEXT | — |
| `status` | TEXT | NOT NULL |
| `trigger` | TEXT | — |
| `generated_at` | TEXT | — |
| `published_at` | TEXT | — |
| `published_sha` | TEXT | — |
| `hidden` | INTEGER | NOT NULL |

#### `agent_index_module_files`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PK |
| `repo_id` | TEXT | NOT NULL |
| `file_key` | TEXT | NOT NULL |
| `directory` | TEXT | NOT NULL |
| `filename` | TEXT | NOT NULL |
| `description` | TEXT | — |
| `content` | TEXT | — |
| `manual_additions` | TEXT | — |
| `status` | TEXT | NOT NULL |
| `generated_at` | TEXT | — |
| `published_at` | TEXT | — |
| `hidden` | INTEGER | NOT NULL |
| `trigger` | TEXT | — |
| `published_sha` | TEXT | — |

## llm_audit.db (sqlite)

**Runtime path:** `/repos/llm_audit.db`
**Used by:** `services/api`, `services/console`

**Source files:**
- `scripts/healthcheck.py`
- `scripts/repo_backup.py`
- `services/api/agent_index/generator.py`
- `services/api/llm_audit.py`
- `services/api/nl_query.py`
- `services/console/llm_audit.py`
- `services/console/nl_query.py`
- `services/console/routes/audit_log.py`
- `services/console/routes/system_health.py`
- `shared/config.py`

**Schema:**

#### `llm_calls`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PK |
| `ts` | TEXT | NOT NULL |
| `source` | TEXT | NOT NULL |
| `model` | TEXT | NOT NULL |
| `input_tokens` | INTEGER | NOT NULL |
| `output_tokens` | INTEGER | NOT NULL |
| `cache_read_tokens` | INTEGER | NOT NULL |
| `cache_write_tokens` | INTEGER | NOT NULL |
| `cost_usd` | REAL | NOT NULL |
| `elapsed_ms` | INTEGER | — |
| `input_text` | TEXT | — |
| `output_text` | TEXT | — |
| `error` | TEXT | — |
| `meta` | TEXT | — |

## mcp_audit.db (sqlite)

**Runtime path:** `/repos/mcp_audit.db`
**Used by:** `services/api`, `services/console`

**Source files:**
- `scripts/healthcheck.py`
- `scripts/repo_backup.py`
- `services/api/agent_index/generator.py`
- `services/console/main.py`
- `services/console/routes/mcp_audit.py`
- `shared/config.py`

**Schema:**

#### `mcp_calls`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PK |
| `ts` | TEXT | NOT NULL |
| `session_id` | TEXT | NOT NULL |
| `session_client` | TEXT | — |
| `tool` | TEXT | NOT NULL |
| `arguments` | TEXT | — |
| `response_size` | INTEGER | — |
| `elapsed_ms` | REAL | — |
| `status` | TEXT | NOT NULL |
| `error` | TEXT | — |
| `response_preview` | TEXT | — |
| `request_id` | TEXT | — |
| `input_tokens_est` | INTEGER | — |
| `output_tokens_est` | INTEGER | — |
| `telemetry` | TEXT | — |
| `turn_id` | TEXT | — |
| `learnings` | TEXT | — |
| `nodes_consulted` | INTEGER | — |
| `raw_source_chars` | INTEGER | — |
| `raw_source_tokens` | INTEGER | — |
| `response_tokens` | INTEGER | — |
| `net_savings_tokens` | INTEGER | — |
| `compression_ratio` | REAL | — |

#### `mcp_sessions`

| Column | Type | Constraints |
|--------|------|-------------|
| `session_id` | TEXT | PK |
| `started_at` | TEXT | NOT NULL |
| `client` | TEXT | — |
| `last_seen` | TEXT | — |
| `call_count` | INTEGER | — |
| `error_count` | INTEGER | — |
| `total_input_tok` | INTEGER | — |
| `total_output_tok` | INTEGER | — |
| `total_raw_source_tokens` | INTEGER | — |
| `total_response_tokens` | INTEGER | — |
| `total_net_savings_tokens` | INTEGER | — |
| `total_cache_read_tok` | INTEGER | — |
| `total_cache_creation_tok` | INTEGER | — |
| `hook_submitted_at` | TEXT | — |
| `hook_source` | TEXT | — |

## scan_log.db (sqlite)

**Runtime path:** `/repos/scan_log.db`
**Used by:** `services/api`, `services/console`

**Source files:**
- `scripts/repo_backup.py`
- `services/api/agent_index/generator.py`
- `services/console/routes/system_health.py`
- `services/console/scan_launcher.py`
- `services/console/tests/test_scan_launcher.py`
- `shared/config.py`

**Schema:**

#### `scan_log`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PK |
| `repo_id` | TEXT | NOT NULL |
| `scan_type` | TEXT | NOT NULL |
| `started_at` | TEXT | NOT NULL |
| `finished_at` | TEXT | — |
| `exit_code` | INTEGER | — |
| `status` | TEXT | NOT NULL |
| `logs` | TEXT | — |

## telemetry.db (sqlite)

**Runtime path:** `/repos/telemetry.db`
**Used by:** `services/api`

**Source files:**
- `scripts/repo_backup.py`
- `services/api/agent_index/generator.py`
- `services/api/main.py`
- `shared/config.py`

**Schema:**

#### `sessions`

| Column | Type | Constraints |
|--------|------|-------------|
| `session_id` | TEXT | PK |
| `started_at` | TEXT | NOT NULL |
| `last_seen` | TEXT | NOT NULL |
| `client` | TEXT | — |
| `cwd` | TEXT | — |

#### `tool_calls`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PK |
| `turn_id` | TEXT | NOT NULL |
| `session_id` | TEXT | NOT NULL |
| `ts` | TEXT | NOT NULL |
| `tool_name` | TEXT | NOT NULL |
| `result_preview` | TEXT | — |
| `input_json` | TEXT | — |
| `step_tokens` | INTEGER | — |

#### `turns`

| Column | Type | Constraints |
|--------|------|-------------|
| `turn_id` | TEXT | PK |
| `session_id` | TEXT | NOT NULL |
| `ts` | TEXT | NOT NULL |
| `user_prompt` | TEXT | — |
| `insights_raw` | TEXT | — |
| `input_tokens` | INTEGER | — |
| `output_tokens` | INTEGER | — |
| `cache_read_tokens` | INTEGER | — |
| `cache_creation_tokens` | INTEGER | — |
| `cache_creation_1h_tokens` | INTEGER | — |
| `cache_creation_5m_tokens` | INTEGER | — |
| `tool_call_count` | INTEGER | — |

---

## Neo4j graph schema

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
| `prov_commit_sha` | `5e7c40281587e7e79043ffa67e073dfe794bca10` |
| `prov_confidence` | `0.85` |
| `prov_freshness_ts` | `2026-06-05T20:43:14Z` |
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
| `calls_unresolved` | `['session', 'run']` |
| `class_fqn` | `tools.backfill_javadoc` |
| `docstring` | `Write javadoc for a batch of {fqn, javadoc} dicts.` |
| `end_line` | `131` |
| `fqn` | `tools.backfill_javadoc#write_batch` |
| `modifiers` | `['public']` |
| `name` | `write_batch` |
| `parameters` | `['driver', 'list[dict] rows']` |
| `prov_commit_sha` | `5e7c40281587e7e79043ffa67e073dfe794bca10` |
| `prov_confidence` | `0.85` |
| `prov_freshness_ts` | `2026-06-05T20:43:14Z` |
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
| `prov_commit_sha` | `5e7c40281587e7e79043ffa67e073dfe794bca10` |
| `prov_confidence` | `0.95` |
| `prov_freshness_ts` | `2026-06-05T20:43:13Z` |
| `prov_source_tool` | `build-extractor` |
| `repo_id` | `codeKG` |

### `Repository`
| Property | Example value |
|---|---|
| `build_tool` | `unknown` |
| `hygiene_computed_at` | `2026-06-05T20:44:48.842000000+00:00` |
| `hygiene_grade` | `B` |
| `hygiene_score` | `74.1` |
| `hygiene_stats` | `{"repo_score":74.1,"repo_grade":"B","total_classes":159,"scored_classes":122,"go` |
| `key_dependencies` | `[]` |
| `language` | `python` |
| `last_commit` | `47004d461a8f0cb1dc00100ebe748436df4deceb` |
| `name` | `codeKG` |
| `path` | `/host-home/Documents/projects/codeKG` |
| `prov_commit_sha` | `5e7c40281587e7e79043ffa67e073dfe794bca10` |
| `prov_confidence` | `0.75` |
| `prov_freshness_ts` | `2026-06-05T20:43:13Z` |
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
| `applies_to` | `open-source-release-checklist` |
| `approved` | `False` |
| `confidence` | `0.97` |
| `importance` | `88` |
| `insight` | `Open-source release checklist audit (2026-06-08): 8 of 22 items are done, 3 are ` |
| `last_touched_commit` | `unknown` |
| `repo_id` | `codeKG` |
| `saved_at` | `2026-06-08T13:15:51.176555+00:00` |
| `scope` | `system` |
| `session_id` | `6ca36900` |
| `staleness` | `0.0` |
| `technical_debt` | `- `services/api/agent_index/store.py` + `services/console/agent_index/store.py`:` |
| `tk_id` | `tk_97b502e4e3d1` |

## Relationships

| From | Relationship | To |
|---|---|---|
| `ArchPolicy` | `:TARGETS` | `Module` |
| `Class` | `:BELONGS_TO` | `Package` |
| `Class` | `:EXHIBITS` | `ArchPattern` |
| `Class` | `:HAS_METHOD` | `Method` |
| `Class` | `:IMPORTS` | `Class` |
| `Class` | `:VIOLATES` | `ArchPolicy` |
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
