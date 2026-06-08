# codeKG — Codebase Knowledge Graph

[![CI](https://github.com/eviking/codeKG/actions/workflows/ci.yml/badge.svg)](https://github.com/eviking/codeKG/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

**codeKG gives AI coding agents a complete, always-current map of your codebase — so they stop exploring blindly and start working with real architectural understanding.**

---

## The problem

AI coding agents (Claude Code, Cursor, Codex) explore your codebase the same way a new engineer would on day one: opening files, grepping for symbols, reading method signatures. For a large codebase this means 20–40 tool calls just to understand the context for a single change — most of which produce incomplete or stale information.

Every agent session starts from scratch. Nothing is retained between sessions. The agent that fixed a subtle bug last Tuesday has no memory of it today.

---

## What codeKG does

codeKG is a self-hosted service that runs alongside your repositories. It:

1. **Parses** your codebase (Java, Python, C++) and builds a Neo4j knowledge graph of every class, method, module, dependency, call chain, and architectural pattern
2. **Publishes** a `.codekg/` directory into your repo — pre-computed markdown files containing complete structural intelligence, committed on every push and always current
3. **Serves** that intelligence to AI agents via an MCP server with tools like `get_change_impact`, `answer_question`, and `check_violations`
4. **Enforces** architectural policies automatically — Cypher queries that run after every scan and flag violations
5. **Accumulates** tribal knowledge — non-obvious insights captured across agent sessions and surfaced in future ones

The result: an agent that reads `.codekg/INDEX.md` and the relevant module file has complete knowledge of your codebase architecture in under 5 seconds, without opening a single source file.

---

## Quick start

**Requirements:** Docker, Docker Compose, an Anthropic API key

```bash
git clone https://github.com/eviking/codeKG.git
cd codeKG

cp .env.example .env
# Edit .env: set NEO4J_PASSWORD, ANTHROPIC_API_KEY, HOME_MOUNT, REPOS_PATH

docker compose up -d

open http://localhost:8080
```

Then go to **Repositories → Add**, point it at a local repo, and trigger a full scan. The watcher will keep it current on every subsequent commit.

Full setup guide: [docs/onboarding.md](docs/onboarding.md)

---

## How it works

```
git commit
    │
    ▼
watcher detects new HEAD
    │
    ▼
ephemeral ingestion container
    │  parses Java / Python / C++ via tree-sitter
    │  writes Class, Method, Module, Package nodes to Neo4j
    │  resolves IMPORTS, CALLS, HAS_METHOD edges
    │  scores blast radius and hygiene grades
    │  detects architectural patterns and policy violations
    ▼
Neo4j graph updated
    │
    ├──► agent index regenerated → .codekg/ committed to your repo
    └──► MCP tools reflect updated graph immediately
```

When an AI agent is invoked, it reads `.codekg/INDEX.md` first (per the CLAUDE.md/AGENTS.md instructions codeKG writes into your repo), then the relevant module file. No source file exploration needed.

---

## Services

| Service | Port | Purpose |
|---------|------|---------|
| `console` | 8080 | Web UI — repos, classes, patterns, policies, hygiene, audit, tribal knowledge |
| `api` | 8000 | REST API — KG queries, impact analysis, agent index generation |
| `mcp` | 8002 | MCP server — tools for Claude Code, Cursor, Codex |
| `ingestion` | — | Ephemeral scan containers (launched per-repo, per-commit) |
| `watcher` | — | Polls repos for new commits, launches ingestion |
| `neo4j` | 7474/7687 | Graph database |

---

## MCP tools

Connect any MCP-capable AI agent to `http://localhost:8002/sse`:

| Tool | What it does |
|------|-------------|
| `answer_question` | Natural-language question → ranked classes + blast radius + tribal knowledge |
| `get_class_context` | Full context for a class: methods, dependencies, callers, insights |
| `get_module_context` | All classes and active policies for a logical module |
| `get_change_impact` | Blast radius for a set of changed files — which classes are at risk |
| `search_classes` | Find classes by name fragment across all indexed repos |
| `get_codebase_template` | Full pre-computed CLAUDE.md / AGENTS.md for a repo |
| `check_violations` | Run active architectural policies against specific files |
| `list_arch_policies` | List all active policies and their current violation counts |
| `get_arch_patterns` | Detected GoF/EIP patterns and anti-patterns |
| `capture_insight` | Record a non-obvious finding for future agent sessions |
| `submit_session_telemetry` | Log token usage, tool calls, and learnings from a session |

Add to `.mcp.json` in any repo:

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

## Agent index

After every scan, codeKG commits a `.codekg/` directory into your repo:

```
.codekg/
├── INDEX.md                    # master navigation — agents read this first
├── architecture/
│   ├── modules.md              # module map with class counts
│   ├── dependencies.md         # cross-module import graph
│   ├── hotspots.md             # highest blast-radius classes
│   ├── patterns.md             # detected architectural patterns
│   └── violations.md          # current policy violations
├── modules/
│   ├── services--api.md        # full class+method detail per module
│   └── ...
└── policies/
    └── active.md               # active architectural policies
```

It also writes `CLAUDE.md` (for Claude Code) and `AGENTS.md` (for Codex/OpenAI agents) into your repo root, instructing agents to read the index before touching any file.

---

## Architectural policies

Policies are Cypher queries stored as `ArchPolicy` nodes. After every scan, codeKG evaluates all active policies and records violations. Define a policy once, enforce it forever:

```cypher
-- Example: console must never import from ingestion layer
MATCH (a:Class {repo_id: $repo_id})-[:IMPORTS]->(b:Class {repo_id: $repo_id})
WHERE a.file_path CONTAINS '/console/'
  AND b.file_path CONTAINS '/ingestion/'
RETURN DISTINCT a.fqn AS violator
```

Policies can be written manually, compiled from natural language via the console's AI compiler, or auto-detected by the pattern scanner.

---

## Tribal knowledge

Every non-obvious finding an agent discovers can be captured as a tribal knowledge entry — a permanent, repo-scoped insight that surfaces in future sessions:

```
"store_insights() uses coalesce(tk.approved, false) — re-capturing an already-approved
insight silently resets it to false. Always approve through the console."
```

The console's **Analyse quality** button runs an AI review to detect conflicts, redundancies, and stale entries across the full knowledge base.

---

## Language support

| Language | Classes | Methods | Imports | Call chains | Patterns |
|----------|---------|---------|---------|-------------|---------|
| Java | ✅ | ✅ | ✅ | ✅ | ✅ |
| Python | ✅ | ✅ | ✅ | ✅ | ✅ |
| C++ | ✅ | ✅ | ✅ | — | — |

---

## Configuration

Key `.env` variables — see [.env.example](.env.example) for the full list:

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Required — used for NL queries, policy compilation, tribal knowledge analysis |
| `NEO4J_PASSWORD` | Neo4j auth (default: `codekg_dev` — change for any non-local deployment) |
| `HOME_MOUNT` | Your home directory, mounted read-only into containers at `/host-home` |
| `REPOS_PATH` | Directory where scan logs and SQLite databases are stored |
| `GITHUB_CLIENT_ID` | Optional — enables GitHub OAuth for multi-user console access |

---

## Documentation

| Doc | Contents |
|-----|---------|
| [Onboarding](docs/onboarding.md) | Step-by-step setup from zero |
| [Overview](docs/01-overview.md) | Architecture, data flow, design decisions |
| [Ingestion](docs/02-ingestion.md) | Parser, KG writer, hygiene scoring |
| [API](docs/03-api.md) | REST endpoints, impact analysis, agent index API |
| [MCP](docs/04-mcp.md) | MCP tools reference, transport modes |
| [Agent Index](docs/05-agent-index.md) | How `.codekg/` is generated and published |
| [Console](docs/06-console.md) | Web UI features and routes |
| [Policies](docs/09-policies.md) | Writing and enforcing architectural policies |
| [Telemetry & Insights](docs/10-telemetry-insights.md) | Session auditing and tribal knowledge |

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
