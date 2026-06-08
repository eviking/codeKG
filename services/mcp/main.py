"""
CodeKG MCP Server — exposes the knowledge graph as MCP tools so coding tools
(Claude Code, Cursor, Codex) can query pre-computed codebase context natively.

Tools exposed:
  - answer_question        → natural-language question answered from KG
  - get_module_context     → full context for a logical module
  - get_class_context      → full context for a single class
  - get_class              → object model snapshot for a class
  - get_feature_context    → aggregate context for a set of classes
  - search_class           → find classes by name pattern
  - search_classes         → find classes by name with full snapshots
  - list_arch_policies     → list active architectural policies
  - check_violations       → check for policy violations in given files
  - get_repo_summary       → high-level summary of all registered repositories
  - get_change_impact      → blast radius analysis for changed files
  - get_arch_patterns      → architectural patterns and anti-patterns
  - get_codebase_template  → full pre-computed codebase intelligence document
  - sync_claude_md         → fetch latest CLAUDE.md content from codeKG
  - capture_insight        → record a non-obvious code insight into the knowledge graph
"""
from __future__ import annotations

import contextvars
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone

import httpx
import mcp.server.stdio
from mcp.server import Server
from mcp.types import Tool, TextContent

from shared.config import cfg
from shared.codekg_logging.codekg_logger import get_logger

log = get_logger(__name__, service="mcp")

_auth_headers = {"Authorization": f"Bearer {cfg.services.api_token}"} if cfg.services.api_token else {}
http = httpx.Client(base_url=cfg.services.api_url, timeout=30.0, headers=_auth_headers)


def _make_server() -> Server:
    s = Server("codekg")
    s.list_tools()(_list_tools)
    s.call_tool()(_call_tool)
    return s


# ── Session identity ──────────────────────────────────────────────────────────
# In stdio mode: one process = one session, globals are fine.
# In SSE mode: one process serves many connections concurrently — use contextvars.

_cv_session_id    = contextvars.ContextVar("session_id",    default=None)
_cv_session_start = contextvars.ContextVar("session_start", default=None)
_cv_client        = contextvars.ContextVar("session_client", default="unknown")

SESSION_ID    = str(uuid.uuid4())[:8]
SESSION_START = datetime.now(timezone.utc).isoformat()
SESSION_CLIENT = "unknown"
_session_lock  = threading.Lock()


def _get_session_id() -> str:
    return _cv_session_id.get() or SESSION_ID


def _get_session_client() -> str:
    return _cv_client.get() or SESSION_CLIENT


def _set_client(name: str):
    global SESSION_CLIENT
    with _session_lock:
        SESSION_CLIENT = name
    log.info("MCP session started", session_id=SESSION_ID, client=name)


# ── Format helpers ────────────────────────────────────────────────────────────

def _format_answer(result: dict) -> str:
    lines = []
    lines.append("> **IMPORTANT:** Always use the exact FQNs shown below when calling")
    lines.append("> `get_class_context`, `get_class`, or `get_change_impact`.")
    lines.append("> Never construct or guess a FQN — copy it verbatim from the results.")
    lines.append("")

    summary = result.get("summary", "")
    if summary:
        lines.append("## Answer\n")
        lines.append(summary)
        lines.append("")

    enriched = result.get("enriched_classes") or result.get("classes") or []
    if enriched:
        lines.append("## Exact FQNs (use these verbatim in follow-up tool calls)\n")
        for cls in enriched[:15]:
            fqn  = cls.get("fqn", "")
            name = cls.get("name", fqn.split(".")[-1] if fqn else "")
            lines.append(f"- `{fqn}`  → {name}")
        lines.append("")

    if enriched:
        lines.append("## Relevant Classes\n")
        for cls in enriched[:15]:
            fqn         = cls.get("fqn", "")
            name        = cls.get("name", fqn.split(".")[-1] if fqn else "")
            role        = cls.get("role", "")
            coupling    = cls.get("coupling") or 0
            blast       = cls.get("blast") or cls.get("blast_size") or 0
            summary_txt = cls.get("summary", "")
            javadoc     = cls.get("javadoc", "")
            chains      = cls.get("call_chains") or []

            lines.append(f"### `{name}` ({role})")
            lines.append(f"**FQN:** `{fqn}`  ")
            if coupling or blast:
                lines.append(f"**Coupling:** {coupling:.2f}  **Blast radius:** {blast} classes")
            if javadoc:
                lines.append(f"**Docstring:** {javadoc[:200]}")
            if summary_txt:
                lines.append(f"**Summary:** {summary_txt[:300]}")
            if chains:
                lines.append("**Call chains:**")
                for ch in chains[:2]:
                    lines.append(f"  - {ch}")
            lines.append("")

    # Fetch insights for all matched FQNs and append if any exist
    fqns = [cls.get("fqn", "") for cls in enriched if cls.get("fqn")]
    if fqns:
        try:
            tk_resp = http.get("/insights/for-classes",
                               params={"fqns": ",".join(fqns)})
            if tk_resp.status_code == 200:
                tk_entries = tk_resp.json()
                if tk_entries:
                    lines.append("## Insights\n")
                    lines.append("> Captured from previous sessions — treat as strong hints, not ground truth.\n")
                    for tk in tk_entries:
                        scope      = tk.get("scope", "")
                        applies_to = tk.get("applies_to", "")
                        confidence = tk.get("confidence", 0)
                        staleness  = tk.get("staleness", 0)
                        insight    = tk.get("insight", "")
                        stale_warn = " ⚠ possibly stale" if staleness > 0.3 else ""
                        lines.append(
                            f"- **[{scope}]** `{applies_to}` "
                            f"(confidence {round(confidence*100)}%{stale_warn}): {insight}"
                        )
                    lines.append("")
        except Exception:  # network error or unexpected shape — fall back to raw JSON
            pass

    output = "\n".join(lines) if lines else json.dumps(result, indent=2)

    MAX_CHARS = 60_000
    if len(output) > MAX_CHARS:
        output = output[:MAX_CHARS] + "\n\n> ⚠ Response truncated to stay within context limits."

    return output


def _get(path: str, **params) -> dict | list:
    resp = http.get(path, params={k: v for k, v in params.items() if v is not None})
    resp.raise_for_status()
    return resp.json()


# ── Tool registry ─────────────────────────────────────────────────────────────

async def _list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_module_context",
            description=(
                "Get pre-computed knowledge graph context for a logical module "
                "(e.g. 'payment', 'user', 'notification'). Returns classes, active "
                "architectural policies, and known violations. Use this at the start "
                "of a session when working on a feature area."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "module_id": {"type": "string", "description": "Logical module name, e.g. 'payment'"},
                },
                "required": ["module_id"],
            },
        ),
        Tool(
            name="get_class_context",
            description=(
                "Get detailed context for a specific Java class by fully-qualified name. "
                "Returns methods, fields, inheritance, interfaces implemented, and callers."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "fqn": {"type": "string", "description": "Fully-qualified class name, e.g. 'com.example.payment.PaymentService'"},
                },
                "required": ["fqn"],
            },
        ),
        Tool(
            name="get_feature_context",
            description=(
                "Get aggregated context for multiple classes involved in a feature. "
                "Pass a comma-separated list of fully-qualified class names."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "classes": {"type": "string", "description": "Comma-separated FQNs"},
                },
                "required": ["classes"],
            },
        ),
        Tool(
            name="search_class",
            description="Search for classes by name pattern. Returns matching class names and their modules.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Name fragment to search for"},
                    "repo_id": {"type": "string", "description": "Optional: limit to a specific repository"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="list_arch_policies",
            description=(
                "List active architectural policies defined by the architecture team. "
                "Use this to understand the intended architectural direction before making changes."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="check_violations",
            description=(
                "Check whether specific files contain architectural policy violations. "
                "Pass a comma-separated list of file paths (as they appear in the repo). "
                "Use this before submitting a PR or during code review."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "files": {"type": "string", "description": "Comma-separated file paths"},
                },
                "required": ["files"],
            },
        ),
        Tool(
            name="get_repo_summary",
            description="Get a high-level summary of all registered repositories and their last-indexed commit.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="get_change_impact",
            description=(
                "Compute the blast radius of a set of changed files. "
                "Returns: directly affected classes, classes that call into them, "
                "transitive import dependents, affected logical modules, exposed API endpoints, "
                "relevant architectural policies, suggested test classes, and a risk score (0–1). "
                "Call this when reviewing a PR or before committing changes to understand what else might break."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_id": {"type": "string", "description": "Repository ID, e.g. 'org/my-service'"},
                    "files": {"type": "string", "description": "Comma-separated file paths that changed"},
                    "commit_sha": {"type": "string", "description": "Optional: commit SHA for provenance"},
                },
                "required": ["repo_id", "files"],
            },
        ),
        Tool(
            name="get_class",
            description=(
                "Get the full object model snapshot for a Java class by FQN. "
                "Returns everything pre-resolved in one call: superclass, interfaces, "
                "all methods with signatures, fields, same-repo dependencies, classes "
                "that depend on this class, test coverage, module membership, and "
                "architectural pattern warnings. Use this instead of reading source "
                "files — it's ~30x more token-efficient and includes relationship context "
                "the source file alone cannot provide."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "fqn": {
                        "type": "string",
                        "description": "Fully qualified class name, e.g. 'org.elasticsearch.xpack.ml.job.persistence.JobConfigProvider'",
                    },
                },
                "required": ["fqn"],
            },
        ),
        Tool(
            name="search_classes",
            description=(
                "Search for Java classes by simple name (case-insensitive substring). "
                "Returns object model snapshots for matching classes. Use this to find "
                "a class when you don't know the full FQN — e.g. search 'JobManager' "
                "to find all classes with that name across all packages. Each result "
                "includes methods, dependencies, module membership, and warnings."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Simple class name or substring to search for",
                    },
                    "repo_id": {
                        "type": "string",
                        "description": "Optional repository ID to scope the search",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 20)",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_arch_patterns",
            description=(
                "Get all auto-detected architectural patterns and anti-patterns for a repository. "
                "Returns GoF/EIP patterns found (Factory, Observer, Strategy etc.) and anti-patterns "
                "(God Class, Deprecated API, Missing Evaluator Variant etc.) with match counts and "
                "top affected packages. Use this to understand the architecture before making changes "
                "or to identify code quality risks."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_id": {"type": "string", "description": "Repository ID, e.g. 'ElasticSearch'"},
                },
                "required": ["repo_id"],
            },
        ),
        Tool(
            name="get_codebase_template",
            description=(
                "Get the full Codebase Intelligence Template for a repository as Markdown. "
                "This is the primary tool to call at the start of a session — it returns a "
                "pre-computed document covering repo structure, data models, API surface, "
                "concurrency model, build commands, architectural policies, and known violations. "
                "Eliminates the need for the LLM to analyze the codebase from scratch."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_id": {"type": "string", "description": "Repository ID, e.g. 'org/my-service'"},
                },
                "required": ["repo_id"],
            },
        ),
        Tool(
            name="sync_claude_md",
            description=(
                "Fetch the latest generated CLAUDE.md (or AGENTS.md) content from codeKG for a "
                "repository. Returns the full file content — you must write it to the repo root "
                "yourself using the Write tool.\n\n"
                "Call this at the start of a session to ensure the local file is current — "
                "it includes the latest architectural policies, insights, and structural changes. "
                "Works remotely: codeKG serves the content, Claude Code writes the file.\n\n"
                "After calling this tool, write the returned content to CLAUDE.md (or AGENTS.md) "
                "in the repo root using: Write(file_path='<repo_root>/CLAUDE.md', content=<content>)"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_id": {
                        "type": "string",
                        "description": "Repository ID as registered in codeKG, e.g. 'ElasticSearch'",
                    },
                    "filename": {
                        "type": "string",
                        "description": "Filename to write: 'CLAUDE.md' (default) or 'AGENTS.md'",
                        "enum": ["CLAUDE.md", "AGENTS.md"],
                    },
                },
                "required": ["repo_id"],
            },
        ),
        Tool(
            name="answer_question",
            description=(
                "Ask a natural-language question about the codebase and get a structured answer "
                "backed by the knowledge graph. USE THIS INSTEAD OF READING SOURCE FILES when you "
                "need to understand: which classes are relevant to a feature, where to hook in, "
                "what the blast radius of a change is, or what a class does.\n\n"
                "Returns:\n"
                "  - answer: prose explanation with specific class names and file paths\n"
                "  - matched_classes: ranked list of relevant classes with role, coupling, blast_radius, "
                "    javadoc, NL summary, and call chains\n"
                "  - cypher: the graph query that was run (for transparency)\n\n"
                "Examples of good questions:\n"
                "  - 'Where should I add query cost tracking as a function of CPU and IO?'\n"
                "  - 'Which classes are involved in ML job persistence?'\n"
                "  - 'What is the safest place to add request rate limiting?'\n"
                "  - 'How does a search request flow from the REST layer to the shard?'\n"
                "  - 'What calls TransportSearchAction and what does it call?'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Natural-language question about the codebase",
                    },
                    "repo_id": {
                        "type": "string",
                        "description": "Optional: scope to a specific repository ID, e.g. 'ElasticSearch'",
                    },
                },
                "required": ["question"],
            },
        ),
        Tool(
            name="capture_insight",
            description=(
                "Record a non-obvious insight about the codebase into the CodeKG knowledge graph. "
                "Call this whenever you discover something a future engineer should know — a hidden "
                "constraint, surprising behaviour, gotcha, historical design decision, or implicit "
                "coupling that is not obvious from reading the code.\n\n"
                "Ask yourself: 'What would I warn a new engineer about before they touch this code?'\n\n"
                "Every insight MUST include:\n"
                "  1. The fact — state plainly what is true, what happens, or what breaks\n"
                "  2. A code snippet (≤8 lines) showing the exact lines where the behaviour lives, "
                "or a file:line reference if a snippet is impractical\n"
                "  3. So what — one sentence on what a future engineer should do differently\n\n"
                "Good example insight text:\n"
                "  'store_insights() sets approved=coalesce(tk.approved,false) so re-capturing an "
                "already-approved insight silently resets it to false:\n"
                "  ```python\n"
                "  tk.approved = coalesce(tk.approved, false)\n"
                "  ```\n"
                "  Always approve insights through the console, not by re-submitting them.'\n\n"
                "Do NOT capture obvious facts ('KGWriter writes to Neo4j'). "
                "Only capture things that would surprise an experienced engineer."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "insight": {
                        "type": "string",
                        "description": (
                            "The non-obvious fact. Structure as: (1) the fact, "
                            "(2) a short code snippet (≤8 lines, fenced with ```) showing where it lives, "
                            "(3) one sentence on what a future engineer should do differently. "
                            "Plain prose without a snippet is not accepted for important insights."
                        ),
                    },
                    "technical_debt": {
                        "type": "string",
                        "description": (
                            "Optional. Technical debt observed in the same code as this insight — "
                            "shortcuts, missing error handling, hardcoded values, or structural weaknesses "
                            "that were noticed but not fixed this turn. "
                            "Format as a markdown bulleted list; each bullet: "
                            "file + function, what the debt is (one sentence), "
                            "and the risk if left unaddressed (one sentence). "
                            "Only include debt actually observed in files touched this turn. "
                            "Omit this field if no debt was observed."
                        ),
                    },
                    "applies_to": {
                        "type": "string",
                        "description": "Fully-qualified name of the class, method, or module this applies to",
                    },
                    "repo_id": {
                        "type": "string",
                        "description": "Repository ID this insight belongs to, e.g. 'ElasticSearch'",
                    },
                    "scope": {
                        "type": "string",
                        "description": (
                            "Required. The tightest scope that correctly describes where this insight applies:\n"
                            "  'method'  — applies to one specific function/method\n"
                            "  'class'   — applies to an entire class\n"
                            "  'module'  — applies to a whole service or package\n"
                            "  'system'  — applies across services or to infrastructure\n"
                            "Pick the tightest scope — prefer 'method' over 'class' when accurate."
                        ),
                        "enum": ["method", "class", "module", "system"],
                    },
                    "confidence": {
                        "type": "number",
                        "description": "How certain you are: 0.0 (speculation) to 1.0 (verified fact)",
                    },
                    "importance": {
                        "type": "integer",
                        "description": (
                            "How important this insight is for future engineers: 1–100. "
                            "Only insights scoring >75 are published to the agent index. "
                            "Score it honestly:\n"
                            "  90–100: Will almost certainly prevent a serious bug or wasted day if missed\n"
                            "  76–89:  Meaningfully changes how you'd approach work in this area\n"
                            "  51–75:  Good to know but not critical — captured but not published\n"
                            "  1–50:   Minor, obvious after reading the code — avoid capturing these"
                        ),
                    },
                },
                "required": ["insight", "applies_to", "repo_id"],
            },
        ),
    ]


# ── Tool dispatch ─────────────────────────────────────────────────────────────

async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
    start = time.perf_counter()

    try:
        if name == "get_module_context":
            data = _get(f"/context/module/{arguments['module_id']}")
            response_text = json.dumps(data, indent=2)

        elif name == "get_class_context":
            data = _get(f"/context/class/{arguments['fqn']}")
            response_text = json.dumps(data, indent=2)

        elif name == "get_class":
            data = _get(f"/context/class/{arguments['fqn']}")
            response_text = json.dumps(data, indent=2)

        elif name == "get_feature_context":
            data = _get("/context/feature", classes=arguments["classes"])
            response_text = json.dumps(data, indent=2)

        elif name == "search_class":
            data = _get("/search/class", q=arguments["query"], repo_id=arguments.get("repo_id"))
            response_text = json.dumps(data, indent=2)

        elif name == "search_classes":
            params = {"q": arguments["query"], "limit": arguments.get("limit", 20)}
            if arguments.get("repo_id"):
                params["repo_id"] = arguments["repo_id"]
            data = _get("/search/class", **params)
            response_text = json.dumps(data, indent=2)

        elif name == "list_arch_policies":
            data = _get("/policies")
            response_text = json.dumps(data, indent=2)

        elif name == "check_violations":
            data = _get("/violations/pr", files=arguments["files"])
            response_text = json.dumps(data, indent=2)

        elif name == "get_repo_summary":
            data = _get("/repos")
            response_text = json.dumps(data, indent=2)

        elif name == "get_change_impact":
            data = _get(
                "/impact/files",
                files=arguments["files"],
                repo_id=arguments["repo_id"],
                commit_sha=arguments.get("commit_sha"),
            )
            response_text = json.dumps(data, indent=2)

        elif name == "get_arch_patterns":
            data = _get("/patterns", repo_id=arguments["repo_id"])
            response_text = json.dumps(data, indent=2)

        elif name == "get_codebase_template":
            data = _get(f"/template/{arguments['repo_id']}")
            response_text = json.dumps(data, indent=2) if isinstance(data, dict) else str(data)

        elif name == "sync_claude_md":
            repo_id  = arguments["repo_id"]
            filename = arguments.get("filename", "CLAUDE.md")
            resp = http.get(f"/template/{repo_id}")
            resp.raise_for_status()
            content = resp.text
            response_text = (
                f"Write this content to `{filename}` in the repo root using the Write tool.\n\n"
                f"```markdown\n{content}\n```"
            )

        elif name == "answer_question":
            resp = http.post("/answer", json={
                "question": arguments["question"],
                "repo_id":  arguments.get("repo_id"),
            })
            data = resp.json() if resp.status_code == 200 else {"error": f"HTTP {resp.status_code}"}
            response_text = _format_answer(data)

        elif name == "capture_insight":
            insight    = (arguments.get("insight") or "").strip()
            applies_to = (arguments.get("applies_to") or "").strip()
            repo_id    = (arguments.get("repo_id") or "").strip()
            if not insight or not applies_to or not repo_id:
                response_text = json.dumps({"ok": False, "error": "insight, applies_to, and repo_id are required"})
            else:
                importance = arguments.get("importance")
                if importance is not None:
                    importance = max(1, min(100, int(importance)))
                tech_debt = (arguments.get("technical_debt") or "").strip() or None
                entry = {
                    "tk_id":          f"tk_{uuid.uuid4().hex[:12]}",
                    "insight":        insight,
                    "scope":          arguments.get("scope", "class"),
                    "applies_to":     applies_to,
                    "confidence":     float(arguments.get("confidence", 0.7)),
                    "importance":     importance,
                    "repo_id":        repo_id,
                    "technical_debt": tech_debt,
                }
                resp = http.post("/insights", json={
                    "entries":    [entry],
                    "session_id": _get_session_id(),
                    "commit_sha": "unknown",
                })
                resp.raise_for_status()
                stored = resp.json().get("stored", 0)
                response_text = json.dumps({
                    "ok": stored > 0,
                    "stored": stored,
                    "applies_to": applies_to,
                    "repo_id": repo_id,
                    "importance": importance,
                    "will_publish": importance is not None and importance > 75,
                })

        else:
            response_text = json.dumps({"error": f"Unknown tool: {name}"})

    except httpx.HTTPStatusError as exc:
        response_text = json.dumps({"error": f"API error {exc.response.status_code}: {exc.response.text[:200]}"})
        log.error("Tool call API error", tool=name, status=exc.response.status_code)

    except Exception as exc:
        response_text = json.dumps({"error": str(exc)})
        log.error("Tool call failed", tool=name, error=str(exc))

    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
    log.info("Tool call complete", tool=name, elapsed_ms=elapsed_ms, session_id=_get_session_id())

    return [TextContent(type="text", text=response_text)]


# Module-level server for stdio mode
server = _make_server()


# ── Startup ───────────────────────────────────────────────────────────────────

async def _main():
    client_hints = [
        os.environ.get("TERM_PROGRAM", ""),
        os.environ.get("CLAUDE_CODE_VERSION", ""),
        os.environ.get("MCP_CLIENT", ""),
    ]
    client_name = next((h for h in client_hints if h), "claude-code")
    _set_client(client_name)

    transport = cfg.mcp.transport.lower()
    log.info("MCP server starting", session_id=SESSION_ID, client=SESSION_CLIENT, transport=transport)

    if transport == "sse":
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Route, Mount
        import uvicorn

        sse_transport = SseServerTransport("/messages/")

        async def handle_sse(request):
            conn_session_id = str(uuid.uuid4())[:8]
            conn_start      = datetime.now(timezone.utc).isoformat()
            conn_client     = request.headers.get("x-client-name", "claude-code")
            _cv_session_id.set(conn_session_id)
            _cv_session_start.set(conn_start)
            _cv_client.set(conn_client)
            log.info("SSE connection — new session", session_id=conn_session_id)

            async with sse_transport.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await server.run(
                    streams[0], streams[1],
                    server.create_initialization_options(),
                    stateless=True,
                )

        starlette_app = Starlette(routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse_transport.handle_post_message),
        ])

        port = cfg.mcp.port
        log.info("SSE transport listening", port=port)
        config = uvicorn.Config(starlette_app, host="0.0.0.0", port=port, log_level="warning")
        await uvicorn.Server(config).serve()
    else:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )


if __name__ == "__main__":
    import asyncio
    asyncio.run(_main())
