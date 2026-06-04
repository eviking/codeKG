# Insights — services/api
_Generated 2026-06-04 16:25 UTC_

Non-obvious facts discovered from previous coding sessions.
Treat as strong hints from engineers who have worked in this code.

## System-level insights

**`services.api.main`** (confidence 100%)
The KG stores start_line and end_line per Class node, not LOC per file. File LOC must be derived as max(end_line) across all Class nodes with that file_path. This only covers .py files with at least one indexed class — HTML templates and non-Python files are absent from the KG and need disk-size fallback.

**`services.api.main`** (confidence 90%)
TribalKnowledge nodes use applies_to as a plain string FQN (not a required relationship) — the APPLIES_TO edge to the target node is optional and may not exist if the FQN wasn't found in the KG at write time. Always query by tk.applies_to string, not by traversing the edge.

## Module-level insights

**`services.api.main`** (confidence 100%)
The telemetry DB stores tool_calls with input_json (serialised tool input) and step_tokens (per-inference-step cost). Rows before the input_json column was added have NULL there — the question text for those CodeKG calls is permanently unrecoverable, which limits query plan reconstruction quality for old sessions.

**`services.api.agent_index.generator`** (confidence 100%)
Module index files grew from ~40 lines (class table only) to 230-300 lines per module by pulling full method signatures, parameter types, return types, and LOC from object_model on each Class node. The object_model JSON blob contains a 'methods' array with name, return_type, parameters, and modifiers — this is richer than the separate Method nodes which lack a 'signature' property.

**`services.api.main`** (confidence 100%)
The agent index publish is a two-step process: POST /agent-index/regen writes to SQLite store, then POST /agent-index/publish writes from store to disk and commits to git. Calling only regen leaves disk files stale. The publish endpoint returns 'files_written' (not 'written'), and returns 0 if the store has no visible files for that repo_id.

**`services.api.agent_index.generator`** (confidence 100%)
When total repo LOC (sum of max end_line per file) is below 2500, the generator produces a combined.md with all modules inlined and CLAUDE.md directs agents to read only that one file. Above the threshold, separate per-module files are used. codeKG itself is at 7236 LOC so uses per-module mode.
