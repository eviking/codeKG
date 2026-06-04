# Insights — services/mcp
_Generated 2026-06-04 16:25 UTC_

Non-obvious facts discovered from previous coding sessions.
Treat as strong hints from engineers who have worked in this code.

## System-level insights

**`services.mcp`** (confidence 100%)
codekg_request_id in the MCP response footer was previously the JSON-RPC request_id — a different value for every single tool call. This is why using the 'first call's request_id' was so fragile: any mistake in tracking which call was first gave a wrong value. Fixed by making codekg_request_id equal to turn_id in the footer, so both values are always the same stable string and there is no ambiguity about which to use.

**`services.mcp.main`** (confidence 95%)
sync_claude_md must return content to Claude Code rather than writing server-side — server-side writes break remote usage where the codeKG server and the engineer's filesystem are on different machines. The correct pattern is: tool returns content, Claude Code calls Write.

## Method-level insights

**`services.mcp.main`** (confidence 85%)
The sync_claude_md tool includes a save_as comment header in the response so Claude Code knows what filename to use without needing to infer it from context.
