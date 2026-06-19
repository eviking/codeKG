# codeKG Documentation

Complete reference documentation for all major areas of the system.

## Files

| # | Document | What it covers |
|---|----------|---------------|
| [01](./01-overview.md) | **System Overview** | Architecture, data flow, six services, design decisions, getting started |
| [02](./02-ingestion.md) | **Ingestion & Knowledge Graph** | Tree-sitter parsing, KGWriter, enrichment passes, blast radius, hygiene scoring |
| [03](./03-api.md) | **API Service** | All endpoints, impact analysis, agent index regen/publish, NL queries, telemetry recording |
| [04](./04-mcp.md) | **MCP Server & Tools** | All 15 MCP tools with examples, session identity, audit logging, adding new tools |
| [05](./05-agent-index.md) | **Agent Index System** | File structure, generation pipeline, status lifecycle, empty detection, ghost cleanup |
| [06](./06-console.md) | **Console UI** | All routes with context vars, design system, API proxying, summarisation jobs |
| [07](./07-watcher.md) | **Watcher Service** | Polling loop, scan container lifecycle, incremental vs full scan, post-scan flow |
| [08](./08-neo4j-schema.md) | **Neo4j Schema** | All node labels, properties, relationships, and common Cypher query patterns |
| [09](./09-policies.md) | **Architectural Policies** | Policy lifecycle, writing Cypher constraints, auto-generated policies, MCP integration |
| [10](./10-telemetry-insights.md) | **Telemetry & Insights** | Stop hook telemetry, session views, tribal knowledge capture, approval gate, staleness, quality guide |

## Quick orientation

**"How does a commit turn into an agent index file?"** → [01 Overview](./01-overview.md) → [02 Ingestion](./02-ingestion.md) → [05 Agent Index](./05-agent-index.md)

**"I want to add a new MCP tool"** → [04 MCP](./04-mcp.md)

**"I want to understand the Neo4j graph"** → [08 Neo4j Schema](./08-neo4j-schema.md)

**"How do policies work and how do I write one?"** → [09 Policies](./09-policies.md)

**"What is tribal knowledge and how do I use it?"** → [10 Telemetry & Insights](./10-telemetry-insights.md)

**"I want to add a new page to the console"** → [06 Console](./06-console.md)
