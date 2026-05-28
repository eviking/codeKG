"""
CodeKG MCP Server — exposes the knowledge graph as MCP tools so coding tools
(Claude Code, Cursor, Codex) can query pre-computed codebase context natively.

Tools exposed:
  - get_module_context      → full context for a logical module
  - get_class_context       → full context for a single class
  - get_feature_context     → aggregate context for a set of classes
  - search_class            → find classes by name pattern
  - list_arch_policies      → list active architectural policies
  - check_violations        → check for policy violations in given files
  - get_repo_summary        → high-level summary of a registered repository
"""
from __future__ import annotations

import os

import httpx
import mcp.server.stdio
from mcp.server import Server
from mcp.types import Tool, TextContent

API_URL = os.environ.get("API_URL", "http://api:8000")

server = Server("codekg")
http = httpx.Client(base_url=API_URL, timeout=30.0)


def _get(path: str, **params) -> dict | list:
    resp = http.get(path, params={k: v for k, v in params.items() if v is not None})
    resp.raise_for_status()
    return resp.json()


@server.list_tools()
async def list_tools() -> list[Tool]:
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
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    import json

    try:
        if name == "get_module_context":
            data = _get(f"/context/module/{arguments['module_id']}")

        elif name == "get_class_context":
            data = _get(f"/context/class/{arguments['fqn']}")

        elif name == "get_feature_context":
            data = _get("/context/feature", classes=arguments["classes"])

        elif name == "search_class":
            data = _get("/search/class", q=arguments["query"], repo_id=arguments.get("repo_id"))

        elif name == "list_arch_policies":
            data = _get("/policies")

        elif name == "check_violations":
            data = _get("/violations/pr", files=arguments["files"])

        elif name == "get_repo_summary":
            data = _get("/repos")

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    except httpx.HTTPStatusError as exc:
        return [TextContent(type="text", text=f"API error {exc.response.status_code}: {exc.response.text}")]
    except Exception as exc:
        return [TextContent(type="text", text=f"Error: {exc}")]


if __name__ == "__main__":
    import asyncio
    asyncio.run(mcp.server.stdio.run(server))
