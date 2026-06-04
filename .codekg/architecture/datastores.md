# Data Stores — codeKG
_Generated 2026-06-04 17:09 UTC_

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

_See `.codekg/architecture/schema.md` for the full Neo4j schema._

## agent_index.db (sqlite)

**Runtime path:** `/repos/agent_index.db`
**Used by:** `services/api`, `services/console`

**Source files:**
- `services/api/agent_index/generator.py`
- `services/api/agent_index/store.py`
- `services/console/agent_index/store.py`

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
- `services/api/agent_index/generator.py`
- `services/api/llm_audit.py`
- `services/api/nl_query.py`
- `services/console/llm_audit.py`
- `services/console/nl_query.py`
- `services/console/routes/audit_log.py`
- `services/console/routes/system_health.py`

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
- `services/api/agent_index/generator.py`
- `services/console/main.py`
- `services/console/routes/dashboard.py`
- `services/console/routes/mcp_audit.py`

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
- `services/api/agent_index/generator.py`
- `services/console/routes/system_health.py`
- `services/console/scan_launcher.py`

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
- `services/api/agent_index/generator.py`
- `services/api/main.py`

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
