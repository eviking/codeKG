# Getting started with codeKG

The fastest path is the **Get Started wizard** at `http://localhost:8080/getstarted`. It walks you through every step in the browser, detects what's already done, and lets you re-run any step at any time.

---

## 1 — Start the stack

```bash
git clone https://github.com/eviking/codeKG.git
cd codeKG
docker compose up -d
open http://localhost:8080/getstarted
```

If no repos are registered yet, a banner on the dashboard also links directly to the wizard.

---

## 2 — Configure (Step 1 of the wizard)

Enter your credentials. The wizard saves them to `/repos/codekg.env` — a file on the host-mounted volume that persists across container rebuilds.

| Field | Purpose |
|---|---|
| **Anthropic API key** | Required for NL queries, policy compilation, and tribal knowledge analysis |
| **Home mount path** | Your home directory (`/Users/you`). Mounted into containers at `/host-home` so Docker can read your repos |
| **Repos path** | Directory where scan logs and SQLite databases are stored (default: `/repos`) |
| **Neo4j password** | Graph database auth (change from the default for any non-local deployment) |

> **Alternatively:** copy `.env.example` to `.env`, fill in the values, and restart: `docker compose up -d`. The wizard will detect existing config and mark Step 1 complete.

---

## 3 — Register & scan a repo (Step 2)

Enter a short unique **repo ID** (e.g. `my-service`) and the **absolute path** on your machine (e.g. `/Users/you/code/my-service`). The path must be under your home mount.

Click **Register & Scan**. codeKG launches an ingestion container immediately. A status badge polls every 8 seconds and turns green when the scan completes. Large repos (>100k LOC) can take a few minutes.

What ingestion does:
- Parses every Java, Python, C++, JavaScript, TypeScript, and Salesforce Apex source file via tree-sitter
- Writes Class, Method, Module, Package, and Field nodes to Neo4j
- Resolves IMPORTS, CALLS, HAS_METHOD, and EXTENDS edges
- Scores blast radius and hygiene grades for every class
- Detects GoF/EIP/C++ patterns and policy violations

---

## 4 — NL summaries (Step 3, optional)

Class-level natural language summaries make the agent index richer and power the `answer_question` MCP tool.

**If Ollama is running locally** the wizard detects it automatically, lists available models, and lets you pick one. Summaries are generated locally at no cost.

**If Ollama is not available** the wizard falls back to Claude (Anthropic API). A cost estimate is shown before you proceed.

To run Ollama locally:
```bash
brew install ollama
ollama pull llama3.2          # or any model you prefer
ollama serve                  # starts on localhost:11434
```
Then click **↺ recheck** in the wizard to detect it.

---

## 5 — Publish agent index (Step 4)

Click **Publish**. codeKG commits the following into your repo:

```
.codekg/
├── INDEX.md                    # master navigation — agents read this first
├── architecture/
│   ├── modules.md
│   ├── dependencies.md
│   ├── hotspots.md
│   ├── patterns.md
│   └── violations.md
├── modules/
│   └── <name>.md               # full class + method detail per module
└── policies/
    └── active.md
CLAUDE.md                       # instructs Claude Code to read the index
AGENTS.md                       # same for Codex / OpenAI agents
```

`CLAUDE.md` and `AGENTS.md` are written into your repo root (or updated if they already exist, within `<!-- codekg:start -->…<!-- codekg:end -->` markers). They include a session-close block that prompts Claude Code to call `capture_insight` at the end of each session.

---

## 6 — Connect the MCP server (Step 5)

codeKG's MCP server runs on SSE transport by default. Add it to Claude Code once:

```bash
claude mcp add codekg --transport sse http://localhost:8002/sse
```

Or add it to `.mcp.json` in any repo that should use codeKG:

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

Restart Claude Code after saving. Verify with `claude mcp list` — `codekg` should appear.

---

## 7 — Memory & insights (Step 6)

This step wires codeKG into Claude Code's persistent memory so insights captured during sessions surface in future ones.

**A — Install the session hook**

Download the stop hook and save it to your Claude Code project-scoped hooks directory:

```bash
curl -o ~/.claude/projects/<your-project-slug>/hooks/require_telemetry.py \
  https://raw.githubusercontent.com/eviking/codeKG/main/.claude/hooks/require_telemetry.py
```

The hook fires at the end of every Claude Code session and submits token usage, tool calls, and captured insights to codeKG. It never blocks — exits 0 on any error.

**B — Add the Insights memory rule**

Open `~/.claude/projects/<your-project-slug>/memory/MEMORY.md` and add:

```markdown
- [Insights section required](feedback_insights_section.md) — Every response must end with **Insights:** written as a sr engineer explaining a gotcha to a jr engineer (fact → why → what it means for future work)
```

**C — Session-close prompt (already in CLAUDE.md)**

The `CLAUDE.md` published in Step 4 already contains a session-close block that prompts Claude Code to call `capture_insight` before ending a session. Nothing more to do here.

---

## Keeping the graph current

The watcher service (`codekg-watcher`) polls your registered repos for new commits and triggers incremental re-ingestion automatically. As long as `docker compose up` is running, changes appear in the graph within seconds of a commit.

To trigger a full re-scan manually: open the repo page in the console and click **Re-scan**.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| 0 classes after scan | Repo path not visible to Docker | Check `HOME_MOUNT` in the wizard or `.env`; path must start with your home directory |
| `answer_question` returns nothing | Wrong `repo_id` | Must match exactly what you entered during registration (case-sensitive) |
| MCP tools not available in Claude | MCP not configured | Run `claude mcp list`; if codekg is missing, re-run Step 5 |
| Ollama not detected | Ollama not running or wrong URL | Run `ollama serve`, then click **↺ recheck** in the wizard |
| Wizard step stuck on scanning | Ingestion container failed | Check `docker logs codekg-ingestion` for parse errors |
| Console returns 500 | Stale container | `docker compose up -d --build console` |
