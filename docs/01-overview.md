# codeKG — System Overview

> A source code intelligence layer that turns a git repository into a queryable knowledge graph — and publishes pre-computed agent indexes so AI coding tools never have to explore the codebase blind.

---

## What it is

codeKG is a self-contained infrastructure system that runs alongside a software repository. It continuously scans commits, builds a semantic knowledge graph of the codebase in Neo4j, enforces architectural policies, records non-obvious engineering insights, and publishes a pre-computed `.codekg/` directory into the repo so that AI coding agents (Claude Code, Cursor, Codex) can read structured intelligence instead of exploring raw source files.

The central idea: **code exploration is expensive and incomplete. Pre-computed intelligence is cheap and total.** An agent that reads `.codekg/INDEX.md` and the relevant module file knows more about the codebase in 3 seconds than it would discover in 30 tool calls of `find` and `Read`.

---

## The six services

All services run as Docker containers, orchestrated by a single `docker-compose.yml`.

```
┌─────────────────────────────────────────────────────────┐
│                    docker network: codekg               │
│                                                         │
│  watcher ──────► api ◄──────────────── mcp             │
│      │            │                      │              │
│      │            ▼                      │              │
│      └──► ingestion ──► Neo4j ◄── console              │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

| Service | Container | Role |
|---------|-----------|------|
| **watcher** | `codekg-watcher` | Polls git repos for new commits, launches ephemeral ingestion containers |
| **ingestion** | `codekg-ingestion` | Parses source files, writes Class/Method/Module nodes to Neo4j |
| **api** | `codekg-api` | FastAPI service — impact analysis, agent index generation, policy evaluation |
| **mcp** | `codekg-mcp` | MCP server — exposes 15 KG tools to Claude Code and other AI agents |
| **console** | `codekg-console` | Web UI — browse KG, manage agent index, view telemetry |
| **neo4j** | `codekg-neo4j` | Graph database — stores all nodes, relationships, and properties |

---

## Data flow for a git commit

```
git commit pushed
       │
       ▼
  watcher polls repo (every 30s)
       │  detects new HEAD
       ▼
  docker run codekg-ingestion
       │  full_scan or incremental_update
       │  parses Python/Java files via tree-sitter
       │  writes Class, Method, Module, Package nodes
       │  resolves IMPORTS, CALLS, HAS_METHOD edges
       │  computes blast_radius and hygiene grades
       ▼
  Neo4j graph updated
       │
       ├──► api /agent-index/regen
       │       generates .codekg/ markdown files from KG
       │       stores in agent_index.db SQLite
       │
       └──► watcher notifies api of scan completion
                api /agent-index/publish
                writes .codekg/ to disk
                creates git commit
```

---

## Data flow for an agent query

```
Claude Code / Cursor
       │  calls MCP tool e.g. get_change_impact
       ▼
  codekg-mcp (SSE — http://localhost:8002/sse)
       │  proxies to api via HTTP
       ▼
  codekg-api
       │  runs Cypher query against Neo4j
       │  logs call to mcp_audit.db and telemetry.db
       ▼
  structured JSON response
       │
       ▼
  Agent uses response without touching source files
```

---

## Shared state: the SQLite databases

Five SQLite databases live in the `/repos/` volume, shared across services:

| Database | Path | Written by | Read by |
|----------|------|-----------|---------|
| `agent_index.db` | `/repos/agent_index.db` | api | api, console |
| `llm_audit.db` | `/repos/llm_audit.db` | api, console | api, console |
| `mcp_audit.db` | `/repos/mcp_audit.db` | mcp | api, console |
| `scan_log.db` | `/repos/scan_log.db` | ingestion/api | console |
| `telemetry.db` | `/repos/telemetry.db` | api | api, console |

---

## Repository registry

Repos are registered in `/repos/repos.json`:

```json
{
  "my-service":    "/host-home/code/my-service",
  "another-repo":  "/host-home/code/another-repo"
}
```

The `selected_repo` cookie in the console UI determines which repo's data is shown. All Neo4j queries are scoped by `repo_id` — the KG holds multiple repos in the same graph database.

Repo paths use the `HOME_MOUNT` prefix — set `HOME_MOUNT` to your local home directory in `.env` and use `/host-home/...` as the path prefix in `repos.json`:

```json
{
  "my-service": "/host-home/code/my-service"
}
```

---

## Key design decisions

**1. Pre-computation over live exploration**
Agent index files are generated offline and committed to git. Agents read static markdown — they never need to call the KG for structural information.

**2. Ephemeral ingestion containers**
Each scan runs in a fresh Docker container. The watcher launches them, the container runs to completion, then exits. No persistent ingestion process that can accumulate state or block.

**3. API as single source of truth for write operations**
The console is read-only except for UI interactions it proxies to the API. Regen and publish both go through `/api`, never through the console directly. This ensures a single writer for `agent_index.db`.

**4. All KG queries scoped by repo_id**
The same Neo4j instance serves all registered repos. Every `MATCH` clause must include `{repo_id: $repo_id}` — this is an architectural invariant enforced by policy.

**5. Stale-aware status**
When an agent index file is regenerated after a publish, its status changes to `stale`. The console shows a visual warning and the INDEX.md flags the file with `⚠ stale`. Agents can trust the freshness of what they read.

---

## Getting started

```bash
# Copy env template
cp .env.example .env
# Edit NEO4J_PASSWORD, HOME_MOUNT, REPOS_PATH, ANTHROPIC_API_KEY

# Start all services
docker compose up -d

# Open console
open http://localhost:8080

# Add a repo via the UI at http://localhost:8080/repos
# Or directly (HOME_MOUNT must point to a directory that contains your repo):
echo '{"myrepo": "/host-home/path/to/myrepo"}' > repos/repos.json
```

The watcher will detect the new repo on its next poll (default: 30 seconds) and launch a full scan.

---

## Further reading

- [Ingestion & Knowledge Graph](./02-ingestion.md)
- [API Service](./03-api.md)
- [MCP Server & Tools](./04-mcp.md)
- [Agent Index System](./05-agent-index.md)
- [Console UI](./06-console.md)
- [Watcher Service](./07-watcher.md)
- [Neo4j Schema](./08-neo4j-schema.md)
- [Architectural Policies](./09-policies.md)
- [Telemetry & Insights](./10-telemetry-insights.md)
