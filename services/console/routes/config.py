"""
Configuration management page.

Reads the current live configuration from shared.config.cfg and exposes
a read-only view of every setting with its source (env var name), current
value, and the compiled default.

Write support: saves changes to /repos/codekg.env.  On startup the console
reads this file (via python-dotenv) so the values survive container rebuilds
without touching docker-compose.yml.  Secrets (passwords, API keys, tokens)
are redacted in the UI display but are preserved on save.

The config file is /repos/codekg.env — mounted from the host via the
existing /repos volume, so it outlives any container rebuild or re-pull.
"""
from __future__ import annotations

import os
import re
from dataclasses import fields as dc_fields
from pathlib import Path
from typing import Any

import httpx as _httpx

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from shared.config import cfg
from deps import _template_ctx, templates, _api_headers

router = APIRouter()

# Path to the persistent env file that survives container rebuilds.
# Mounted from the host via the /repos volume.
_ENV_FILE = Path(os.environ.get("REPOS_PATH", "/repos")) / "codekg.env"

# Env vars whose values are never shown in full — replaced with *** in display
_SECRET_KEYS = frozenset({
    "NEO4J_PASSWORD",
    "ANTHROPIC_API_KEY",
    "API_TOKEN",
    "GITHUB_CLIENT_SECRET",
    "SESSION_SECRET",
})

# ── Schema: every tunable setting ────────────────────────────────────────────
# Each entry: (env_var, section, label, type, description, current_value_fn)

def _schema() -> list[dict]:
    """Build the full settings schema with live values from cfg."""
    def _val(v: Any) -> str:
        return str(v) if v is not None else ""

    return [
        # ── Neo4j ─────────────────────────────────────────────────────────
        {
            "section": "Neo4j",
            "section_icon": "db",
            "key": "NEO4J_URI",
            "label": "Connection URI",
            "type": "text",
            "value": cfg.neo4j.uri,
            "default": "bolt://neo4j:7687",
            "description": "Bolt URI for the Neo4j instance.",
            "restart_required": True,
        },
        {
            "section": "Neo4j",
            "key": "NEO4J_USER",
            "label": "Username",
            "type": "text",
            "value": cfg.neo4j.user,
            "default": "neo4j",
            "description": "Neo4j authentication username.",
            "restart_required": True,
        },
        {
            "section": "Neo4j",
            "key": "NEO4J_PASSWORD",
            "label": "Password",
            "type": "password",
            "value": cfg.neo4j.password,
            "default": "",
            "description": "Neo4j authentication password.",
            "restart_required": True,
        },
        {
            "section": "Neo4j",
            "key": "NEO4J_HEAP_INITIAL",
            "label": "Heap (initial)",
            "type": "text",
            "value": cfg.neo4j.heap_initial,
            "default": "2g",
            "description": "Initial JVM heap for the Neo4j container. Requires Neo4j restart.",
            "restart_required": True,
        },
        {
            "section": "Neo4j",
            "key": "NEO4J_HEAP_MAX",
            "label": "Heap (max)",
            "type": "text",
            "value": cfg.neo4j.heap_max,
            "default": "4g",
            "description": "Maximum JVM heap for Neo4j. heap_initial + pagecache should be ≤ available RAM.",
            "restart_required": True,
        },
        {
            "section": "Neo4j",
            "key": "NEO4J_PAGECACHE",
            "label": "Page cache",
            "type": "text",
            "value": cfg.neo4j.pagecache,
            "default": "2g",
            "description": "Neo4j page cache size. Larger = faster graph traversal on big repos.",
            "restart_required": True,
        },

        # ── LLM / AI ──────────────────────────────────────────────────────
        # API keys — one per provider
        {
            "section": "AI Models",
            "section_icon": "brain",
            "key": "ANTHROPIC_API_KEY",
            "label": "Anthropic API key",
            "type": "password",
            "value": cfg.llm.anthropic_api_key,
            "default": "",
            "description": "Enables Claude models (claude-haiku-*, claude-sonnet-*, claude-opus-*).",
            "restart_required": True,
        },
        {
            "section": "AI Models",
            "key": "OPENAI_API_KEY",
            "label": "OpenAI API key",
            "type": "password",
            "value": cfg.llm.openai_api_key,
            "default": "",
            "description": "Enables OpenAI models (gpt-4o, gpt-4o-mini, o1-*, o3-*). Leave blank if not using OpenAI.",
            "restart_required": True,
        },
        {
            "section": "AI Models",
            "key": "OLLAMA_URL",
            "label": "Ollama URL",
            "type": "text",
            "value": cfg.llm.ollama_url,
            "default": "http://host.docker.internal:11434",
            "description": "Ollama server URL — enables local models (prefix with 'ollama/'). macOS: host.docker.internal:11434.",
            "restart_required": True,
        },
        # Model assignments — type "model" renders a live dropdown
        {
            "section": "AI Models",
            "key": "NL_QUERY_MODEL",
            "label": "NL → Cypher model",
            "type": "model",
            "value": cfg.llm.nl_query_model,
            "default": "claude-haiku-4-5",
            "description": "Translates natural-language questions into Cypher. Use a fast, cheap model.",
            "restart_required": True,
        },
        {
            "section": "AI Models",
            "key": "NL_ANSWER_MODEL",
            "label": "NL answer model",
            "type": "model",
            "value": cfg.llm.nl_answer_model,
            "default": "claude-sonnet-4-5",
            "description": "Generates free-text answers for complex questions. More capable = better results.",
            "restart_required": True,
        },
        {
            "section": "AI Models",
            "key": "POLICY_MODEL",
            "label": "Policy compiler model",
            "type": "model",
            "value": cfg.llm.policy_model,
            "default": "claude-haiku-4-5-20251001",
            "description": "Compiles natural-language architectural rules into Cypher constraints.",
            "restart_required": True,
        },
        {
            "section": "AI Models",
            "key": "SUMMARY_MODEL",
            "label": "Class summarisation model",
            "type": "model",
            "value": cfg.llm.summary_model,
            "default": "ollama/qwen2.5-coder:7b",
            "description": "Generates one-sentence class summaries. Prefix with 'ollama/' for local models.",
            "restart_required": True,
        },
        {
            "section": "AI Models",
            "key": "NL_CYPHER_MAX_TOKENS",
            "label": "Cypher generation max tokens",
            "type": "number",
            "value": str(cfg.llm.nl_cypher_max_tokens),
            "default": "600",
            "description": "Token cap for the Cypher-generation LLM call.",
            "restart_required": True,
        },
        {
            "section": "AI Models",
            "key": "NL_ANSWER_MAX_TOKENS",
            "label": "Answer max tokens (complex)",
            "type": "number",
            "value": str(cfg.llm.nl_answer_max_tokens),
            "default": "800",
            "description": "Token cap for complex NL answers (code reasoning, multi-class queries).",
            "restart_required": True,
        },
        {
            "section": "AI Models",
            "key": "NL_ANSWER_MAX_TOKENS_FAST",
            "label": "Answer max tokens (simple)",
            "type": "number",
            "value": str(cfg.llm.nl_answer_max_tokens_fast),
            "default": "500",
            "description": "Token cap for simple factual answers (count/find/list queries).",
            "restart_required": True,
        },

        # ── Ingestion ─────────────────────────────────────────────────────
        {
            "section": "Ingestion",
            "section_icon": "scan",
            "key": "POLL_INTERVAL",
            "label": "Poll interval (s)",
            "type": "number",
            "value": str(cfg.watcher.poll_interval),
            "default": "30",
            "description": "Seconds between git-commit checks per registered repo.",
            "restart_required": True,
        },
        {
            "section": "Ingestion",
            "key": "WORKER_COUNT",
            "label": "Parse workers",
            "type": "number",
            "value": str(cfg.ingestion.worker_count),
            "default": "0",
            "description": "Parallel file parser threads. 0 = use all available CPU cores.",
            "restart_required": True,
        },
        {
            "section": "Ingestion",
            "key": "PARSE_BATCH_SIZE",
            "label": "Parse batch size",
            "type": "number",
            "value": str(cfg.ingestion.parse_batch_size),
            "default": "200",
            "description": "Files processed per batch before flushing to Neo4j.",
            "restart_required": True,
        },
        {
            "section": "Ingestion",
            "key": "WIRE_EDGES_TIMEOUT",
            "label": "Wire-edges timeout (s)",
            "type": "number",
            "value": str(cfg.ingestion.wire_edges_timeout),
            "default": "90",
            "description": "Per-query timeout for edge resolution. Do not lower below 30s without Neo4j load testing.",
            "restart_required": True,
        },
        {
            "section": "Ingestion",
            "key": "INGESTION_IMAGE",
            "label": "Ingestion Docker image",
            "type": "text",
            "value": cfg.ingestion.ingestion_image,
            "default": "codekg-ingestion",
            "description": "Docker image name for ephemeral scan containers.",
            "restart_required": True,
        },

        # ── Agent Index ───────────────────────────────────────────────────
        {
            "section": "Agent Index",
            "section_icon": "index",
            "key": "AGENT_INDEX_COMBINED_LOC_THRESHOLD",
            "label": "Combined-file LOC threshold",
            "type": "number",
            "value": str(cfg.agent_index.combined_loc_threshold),
            "default": "2500",
            "description": "Repos with total LOC below this get a single combined.md instead of per-module files.",
            "restart_required": True,
        },
        {
            "section": "Agent Index",
            "key": "AGENT_INDEX_LARGE_REPO_THRESHOLD",
            "label": "Large-repo module threshold",
            "type": "number",
            "value": str(cfg.agent_index.large_repo_threshold),
            "default": "100",
            "description": "Module count above which the modules overview switches to compact index mode.",
            "restart_required": True,
        },

        # ── Neo4j memory (separate section for clarity) ───────────────────

        # ── Authentication ────────────────────────────────────────────────
        {
            "section": "Authentication",
            "section_icon": "auth",
            "key": "API_TOKEN",
            "label": "API bearer token",
            "type": "password",
            "value": cfg.services.api_token,
            "default": "",
            "description": "When set, all API requests require Authorization: Bearer <token>. Leave empty for open/single-user mode.",
            "restart_required": True,
        },
        {
            "section": "Authentication",
            "key": "GITHUB_CLIENT_ID",
            "label": "GitHub Client ID",
            "type": "text",
            "value": cfg.auth.github_client_id,
            "default": "",
            "description": "OAuth App Client ID from github.com/settings/developers. Leave empty to disable GitHub auth.",
            "restart_required": True,
        },
        {
            "section": "Authentication",
            "key": "GITHUB_CLIENT_SECRET",
            "label": "GitHub Client Secret",
            "type": "password",
            "value": cfg.auth.github_client_secret,
            "default": "",
            "description": "OAuth App Client Secret. Never shown after saving.",
            "restart_required": True,
        },
        {
            "section": "Authentication",
            "key": "SESSION_SECRET",
            "label": "Session signing secret",
            "type": "password",
            "value": cfg.auth.session_secret,
            "default": "dev-secret-change-me",
            "description": "Random string used to sign session cookies. Changing this invalidates all active sessions.",
            "restart_required": True,
        },
        {
            "section": "Authentication",
            "key": "GITHUB_ORG",
            "label": "GitHub org (access control)",
            "type": "text",
            "value": cfg.auth.github_org,
            "default": "",
            "description": "Restrict access to members of this GitHub organisation. Leave empty to allow any GitHub user.",
            "restart_required": True,
        },
        {
            "section": "Authentication",
            "key": "GITHUB_TEAM",
            "label": "GitHub team slug",
            "type": "text",
            "value": cfg.auth.github_team,
            "default": "",
            "description": "Restrict to a specific team within the org (team slug, not display name).",
            "restart_required": True,
        },
        {
            "section": "Authentication",
            "key": "ALLOWED_GITHUB_USERS",
            "label": "Allowed GitHub usernames",
            "type": "text",
            "value": cfg.auth.allowed_users_raw,
            "default": "",
            "description": "Comma-separated GitHub usernames. Alternative to org/team access control.",
            "restart_required": True,
        },
        {
            "section": "Authentication",
            "key": "SESSION_MAX_AGE",
            "label": "Session lifetime (s)",
            "type": "number",
            "value": str(cfg.auth.session_max_age),
            "default": "2592000",
            "description": "Session cookie lifetime in seconds. Default: 30 days (2592000).",
            "restart_required": True,
        },

        # ── MCP ───────────────────────────────────────────────────────────
        {
            "section": "MCP Server",
            "section_icon": "mcp",
            "key": "MCP_TRANSPORT",
            "label": "Transport",
            "type": "select",
            "options": ["stdio", "sse"],
            "value": cfg.mcp.transport,
            "default": "stdio",
            "description": "'stdio' for local Claude Code integration. 'sse' for shared/network access.",
            "restart_required": True,
        },
        {
            "section": "MCP Server",
            "key": "MCP_PORT",
            "label": "SSE port",
            "type": "number",
            "value": str(cfg.mcp.port),
            "default": "8002",
            "description": "Port the MCP SSE server listens on (only used when transport=sse).",
            "restart_required": True,
        },
    ]


def _load_env_file() -> dict[str, str]:
    """Read the persistent env file into a dict."""
    result: dict[str, str] = {}
    if not _ENV_FILE.exists():
        return result
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def _save_env_file(updates: dict[str, str]):
    """
    Merge `updates` into the persistent env file.
    Existing keys not in `updates` are preserved.
    Empty-string values remove the key from the file.
    """
    existing = _load_env_file()
    merged = {**existing, **updates}
    # Remove keys explicitly set to ""
    merged = {k: v for k, v in merged.items() if v != ""}

    lines = ["# codeKG persistent configuration", "# Managed by the console — do not edit manually", ""]
    for k, v in sorted(merged.items()):
        # Quote values that contain spaces or special chars
        if " " in v or "#" in v or not v:
            v = f'"{v}"'
        lines.append(f"{k}={v}")
    lines.append("")  # trailing newline
    _ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ENV_FILE.write_text("\n".join(lines))


def _redact(key: str, value: str) -> str:
    """Redact secrets for display — show only whether a value is set."""
    if key in _SECRET_KEYS and value:
        return "••••••••"
    return value


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    schema = _schema()
    env_file_values = _load_env_file()

    # Group by section
    sections: dict[str, list[dict]] = {}
    for item in schema:
        s = item["section"]
        if s not in sections:
            sections[s] = []
        # Mark whether value comes from env file vs process env vs default
        env_file_val = env_file_values.get(item["key"])
        proc_env_val = os.environ.get(item["key"])
        if env_file_val is not None:
            item["source"] = "file"
        elif proc_env_val is not None:
            item["source"] = "env"
        else:
            item["source"] = "default"
        item["display_value"] = _redact(item["key"], item["value"])
        item["is_set"] = bool(item["value"])
        sections[s].append(item)

    env_file_exists = _ENV_FILE.exists()
    env_file_path   = str(_ENV_FILE)

    return templates.TemplateResponse("config.html", {
        **_template_ctx(request),
        "sections": sections,
        "env_file_exists": env_file_exists,
        "env_file_path": env_file_path,
    })


@router.post("/api/config/save")
async def api_config_save(request: Request):
    """Save one or more settings to the persistent env file."""
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"ok": False, "detail": "Invalid JSON"}, status_code=400)

    updates: dict[str, str] = {}
    schema_keys = {item["key"] for item in _schema()}

    for key, value in body.items():
        if key not in schema_keys:
            return JSONResponse({"ok": False, "detail": f"Unknown key: {key}"}, status_code=400)
        updates[key] = str(value).strip()

    _save_env_file(updates)
    return JSONResponse({"ok": True, "saved": len(updates)})


@router.get("/api/config/current")
async def api_config_current():
    """Return all current live values (secrets redacted)."""
    schema = _schema()
    return JSONResponse({
        item["key"]: _redact(item["key"], item["value"])
        for item in schema
    })


@router.post("/api/config/reset")
async def api_config_reset(request: Request):
    """Remove a key from the env file (restores env-var or default)."""
    body = await request.json()
    key  = body.get("key", "")
    if not key:
        return JSONResponse({"ok": False, "detail": "key required"}, status_code=400)
    existing = _load_env_file()
    existing.pop(key, None)
    _save_env_file({})   # rewrite without the key by passing empty dict and merging
    # Rewrite directly
    merged = {k: v for k, v in existing.items() if k != key}
    lines = ["# codeKG persistent configuration", "# Managed by the console — do not edit manually", ""]
    for k, v in sorted(merged.items()):
        if " " in v or "#" in v or not v:
            v = f'"{v}"'
        lines.append(f"{k}={v}")
    lines.append("")
    _ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ENV_FILE.write_text("\n".join(lines))
    return JSONResponse({"ok": True})


@router.get("/api/llm/models/{provider}")
async def proxy_llm_models(provider: str):
    """
    Proxy to the API service's live model list endpoint.
    Returns {provider, models, error?}.
    """
    try:
        with _httpx.Client(base_url=cfg.services.api_url, timeout=10.0, headers=_api_headers()) as c:
            r = c.get(f"/llm/models/{provider}")
            return JSONResponse(r.json())
    except Exception as exc:
        return JSONResponse({"provider": provider, "models": [], "error": str(exc)})
