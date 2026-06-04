# Insights — services/ingestion
_Generated 2026-06-04 16:25 UTC_

Non-obvious facts discovered from previous coding sessions.
Treat as strong hints from engineers who have worked in this code.

## System-level insights

**`services.ingestion`** (confidence 100%)
The codeKG protocol text exists in three separate places that must be kept in sync: (1) services/ingestion/claude_md_writer.py — written to repos at ingestion time, (2) services/api/renderers/template_renderer.py — served by GET /template/{repo_id} which powers both sync_claude_md and get_codebase_template, (3) .claude/CLAUDE.md — the live file for this repo. Changing the protocol in one place does not update the others.

## Method-level insights

**`services.ingestion.kg.writer.KGWriter`** (confidence 90%)
KGWriter wire_edges has a 90s timeout added to prevent large repos from pinning Neo4j indefinitely — do not remove without load testing.
