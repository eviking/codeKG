# Onboarding a Repository to CodeKG

This guide explains how to connect a new codebase to a running CodeKG instance so that Claude Code agents can query the knowledge graph instead of scraping source files.

---

## Prerequisites

- CodeKG is running and accessible (console at `http://localhost:8080`, API at `http://localhost:8001`, MCP at port 8002)
- The repository you want to index is on the same machine as CodeKG (or is accessible via a mounted path)
- Your `.env` contains `HOME_MOUNT=<your-home-directory>` so Docker can see your repos

---

## Step 1 — Register the repository

Open the CodeKG console at **http://localhost:8080/repos** and click **Register Repository**.

| Field | What to enter |
|---|---|
| **Repository ID** | A short unique name, e.g. `my-service` or `org/my-service`. This is the `repo_id` Claude will reference in tool calls. |
| **Local path** | Absolute path to the repo root on your machine, e.g. `/Users/you/code/my-service`. Must be inside `HOME_MOUNT`. |

Click **Register & Scan**. CodeKG will start a full ingestion run immediately. Watch the console for progress — large repos can take several minutes.

Alternatively, register via the API:

```bash
curl -X POST http://localhost:8080/repos \
  -d "repo_id=my-service&repo_path=/Users/you/code/my-service"
```

---

## Step 2 — Verify ingestion

Once the scan completes, the repository page at **http://localhost:8080/repos/my-service** should show class, method, and package counts. You can also check via the Modules page or run a natural-language query to confirm the graph has content.

---

## Step 3 — Add a `CLAUDE.md` and/or `AGENTS.md` to the repo

CodeKG generates the correct instruction file content for each agent type automatically. The easiest path is to let it write these files for you — skip to Step 4 and come back here only if you want to seed the files manually.

**Automatic generation (recommended):** After a successful scan, open `http://localhost:8080/agent-index` and click **Publish to repo**. CodeKG writes:
- `CLAUDE.md` — if a `CLAUDE.md` already exists at the repo root (updates the `<!-- codekg:start -->…<!-- codekg:end -->` section)
- `AGENTS.md` — if an `AGENTS.md` already exists at the repo root (same update strategy)
- Falls back to `.codekg/CLAUDE.md` / `.codekg/AGENTS.md` if neither root file exists yet

To use root-level files from the start, create empty placeholders:
```bash
touch CLAUDE.md AGENTS.md   # in your repo root
```
Then publish from the console — codeKG will insert its section into both files.

**Content differences between the two files:**
- **`CLAUDE.md`** references MCP tools: `capture_insight`, `get_change_impact`, `search_classes`
- **`AGENTS.md`** uses shell commands (`cat .codekg/INDEX.md`) since Codex has no MCP support

**Manual template (if you want to write it yourself):**

`CLAUDE.md` (for Claude Code):
```markdown
## CodeKG Agent Index
<!-- codekg:start -->
<!-- codekg:end -->
```
Leave the markers in place — the publish step inserts the full generated content between them.

`AGENTS.md` (for Codex / OpenAI agents): same marker pattern, different generated content (shell commands instead of MCP tool references).

---

## Step 4 — Connect the MCP server to Claude Code

The default transport is **stdio** (local Docker exec). Add it once to your Claude Code config:

```bash
claude mcp add codekg --transport stdio -- docker exec -i codekg-mcp python main.py
```

Or add it manually to `~/.claude/settings.json` (or the repo-local `.claude/settings.json`):

```json
{
  "mcpServers": {
    "codekg": {
      "command": "docker",
      "args": ["exec", "-i", "codekg-mcp", "python", "main.py"]
    }
  }
}
```

If you prefer SSE mode (for shared or remote access), set `MCP_TRANSPORT=sse` in `.env` and connect via HTTP instead:

```json
{
  "mcpServers": {
    "codekg": {
      "type": "http",
      "url": "http://localhost:8002/mcp"
    }
  }
}
```

Restart Claude Code after saving.

---

## Step 5 — Test it

Open a Claude Code session in the repository and ask something about the codebase:

```
What does the AuthService class do?
```

Claude should call `answer_question` (using the knowledge graph) rather than opening source files. The call will appear in the **MCP Audit** dashboard at `http://localhost:8080/mcp-audit`.

---

## Keeping the graph up to date

CodeKG ships a watcher service (`codekg-watcher`) that detects file changes and re-indexes incrementally. As long as `docker compose up` is running, changes are picked up automatically within a few seconds of saving a file.

To trigger a manual full re-scan at any time, click **Re-scan** on the repository page in the console.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| 0 modules / 0 classes after scan | Repo path not visible to Docker | Check `HOME_MOUNT` in `.env`; path must start with that prefix |
| `answer_question` returns nothing | Wrong `repo_id` in CLAUDE.md | Make sure `repo_id` matches exactly what you entered during registration (case-sensitive) |
| MCP tools not available in Claude | MCP server not configured | Run `claude mcp list` and verify `codekg` appears |
| Class detail page returns 500 | Stale build | Run `docker compose build console && docker compose up -d console` |
