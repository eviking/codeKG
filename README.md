# codeKG — Codebase Knowledge Graph

![CI](https://github.com/your-org/codekg/actions/workflows/ci.yml/badge.svg)

A self-hosted knowledge graph for large codebases. Indexes Java, Python, and C++ repositories into Neo4j, exposes pre-computed architectural context via MCP, and provides a web console for exploration, policy enforcement, and AI session auditing.

## What it does

- **Ingests** repositories (Java/Python/C++) and builds a Neo4j graph of classes, methods, packages, modules, dependencies, and call chains
- **Serves context** to AI coding tools (Claude Code, Cursor) via an MCP server — `answer_question`, `get_class_context`, `get_change_impact`, and more
- **Enforces hooks** that ensure AI agents always consult the KG before modifying files and always submit telemetry when done
- **Audits** every MCP call, session, token usage, and tribal knowledge entry in a web console

---

## Quick start

```bash
cp .env.example .env
# Edit .env — set NEO4J_PASSWORD, REPOS_PATH, HOME_MOUNT, ANTHROPIC_API_KEY

docker compose up -d
open http://localhost:8080   # Architecture console
```

Register a repo in the console → Repositories → Add, then trigger a full scan.

---

## Services

| Service | Port | Purpose |
|---------|------|---------|
| `console` | 8080 | Web UI — repos, classes, patterns, policies, audit, tribal knowledge |
| `api` | 8000 | REST API — KG queries, policies, tribal knowledge storage |
| `mcp` | 8002 | MCP server — SSE transport for Claude Code / Cursor |
| `ingestion` | 8001 | Repo parser and KG writer |
| `watcher` | — | Monitors repos for git changes, triggers re-ingestion |
| `neo4j` | 7474/7687 | Graph database |

---

## MCP tools

The MCP server exposes these tools to AI coding agents:

| Tool | Purpose |
|------|---------|
| `answer_question` | Natural-language question → ranked classes + blast radius + tribal knowledge |
| `get_class_context` | Full context for a class by FQN |
| `get_module_context` | All classes and policies for a logical module |
| `get_change_impact` | Blast radius for a set of changed files |
| `search_classes` | Find classes by name fragment |
| `get_codebase_template` | Full pre-computed CLAUDE.md for a repo |
| `sync_claude_md` | Fetch latest generated CLAUDE.md content |
| `check_violations` | Check files against active architectural policies |
| `list_arch_policies` | List active policies |
| `get_arch_patterns` | Detected GoF/EIP patterns and anti-patterns |
| `submit_session_telemetry` | Record session token usage and tribal knowledge |

---

## Agent protocol hooks

Two Claude Code hooks enforce the codeKG protocol for every registered repo. They live in `.claude/hooks/` inside each repo.

### `require_codekg.py` — PreToolUse

Blocks `Read`, `Edit`, `Write`, and write-bearing `Bash` commands if no codeKG tool has been called since the last user message. Forces the agent to consult the KG before touching any file.

**Blocked with message:**
> ⛔ codeKG not consulted this turn. Call `answer_question` before reading or modifying files.

### `require_telemetry.py` — Stop

Fires when the agent finishes a response turn. Checks whether `submit_session_telemetry` was called after any codeKG tool use. If not, blocks turn completion and injects a reminder into model context.

**Blocked with message:**
> ⚠️ submit_session_telemetry not called. Call it now with codekg_request_id, turn_id, user_prompt, turns, and learnings.

### Installing hooks in a new repo

1. Copy the hooks into the repo's `.claude/hooks/` directory:
   ```bash
   mkdir -p <repo>/.claude/hooks
   cp .claude/hooks/require_codekg.py <repo>/.claude/hooks/
   cp .claude/hooks/require_telemetry.py <repo>/.claude/hooks/
   ```

2. Add to `<repo>/.claude/settings.local.json`:
   ```json
   {
     "enabledMcpjsonServers": ["codekg"],
     "enableAllProjectMcpServers": true,
     "hooks": {
       "PreToolUse": [
         {
           "matcher": ".*",
           "hooks": [{ "type": "command", "command": "python3 .claude/hooks/require_codekg.py" }]
         }
       ],
       "Stop": [
         {
           "hooks": [{ "type": "command", "command": "python3 .claude/hooks/require_telemetry.py" }]
         }
       ]
     }
   }
   ```

3. Register the repo in the codeKG console and trigger a full scan.

---

## MCP configuration

Add to `.mcp.json` in any repo (or to `~/.claude/.mcp.json` for all projects):

```json
{
  "mcpServers": {
    "codekg": {
      "type": "sse",
      "url": "http://localhost:8002/sse"
    }
  }
}
```

---

## .env variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `NEO4J_PASSWORD` | `codekg_dev` | Neo4j auth password |
| `REPOS_PATH` | `./repos` | Host directory mounted at `/repos` in containers |
| `HOME_MOUNT` | — | Your home dir mounted at `/host-home` (read-only) for reaching repos |
| `ANTHROPIC_API_KEY` | — | Required for NL summary generation and tribal knowledge analysis |

---

## Registered repos

Currently indexed:

| Repo ID | Path |
|---------|------|
| `codeKG` | This repository |
| `ElasticSearch` | `/host-home/Documents/GitHub/elasticsearch-main` |
| `Django` | `/host-home/Documents/GitHub/django` |

---

## NL Summaries

Generate natural-language summaries for classes using a local Ollama model:

1. Install and run [Ollama](https://ollama.com) on your Mac
2. Pull a model: `ollama pull qwen2.5-coder:7b`
3. Open the console → Classes → **Run NL summaries**

The summariser runs inside the console container and calls Ollama at `http://host.docker.internal:11434`.

---

## Tribal Knowledge

The console's **Tribal Knowledge** page shows insights captured by AI agents across sessions. Use the **✦ Analyse quality** button to run an AI review that detects:

- **Conflicts** — entries that contradict each other
- **Redundant** — entries saying the same thing
- **Uplift** — insights stated at class level that apply at module/system level
- **Rewrite** — stale entries using past-tense or outdated phrasing

Findings can be applied with one click to update, merge, or hide entries.
