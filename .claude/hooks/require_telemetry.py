#!/usr/bin/env python3
"""
Stop hook — submits telemetry (tokens, tool calls, user prompt) to the API.

Insights are Claude's responsibility via the capture_insight MCP tool.
This hook never blocks — it always submits whatever it can parse and exits 0.
"""
import json
import sys
import urllib.request
from pathlib import Path

API_TELEMETRY_URL = "http://localhost:8000/telemetry/session"


def _load_transcript(hook_input: dict) -> list[dict]:
    transcript_path = hook_input.get("transcript_path")
    if transcript_path:
        p = Path(transcript_path)
    else:
        session_id = hook_input.get("session_id", "")
        if not session_id:
            return []
        matches = list(Path.home().joinpath(".claude").rglob(f"{session_id}.jsonl"))
        if not matches:
            return []
        p = matches[0]

    if not p.exists():
        return []

    entries = []
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _last_turn_entries(entries: list[dict]) -> list[dict]:
    """Return entries from the last real user message to the end."""
    turn = []
    for entry in reversed(entries):
        etype = entry.get("type")
        if etype == "user":
            content = entry.get("message", {}).get("content", [])
            is_tool_results_only = (
                isinstance(content, list) and len(content) > 0 and
                all(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
            )
            turn.append(entry)
            if not is_tool_results_only:
                break
        else:
            turn.append(entry)
    turn.reverse()
    return turn


def _parse_transcript(entries: list[dict], turn_entries: list[dict]) -> dict:
    """Extract exact token usage, tool calls, user prompt, and session_id."""
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_creation_1h_tokens": 0,
        "cache_creation_5m_tokens": 0,
    }
    tool_calls = []
    user_prompt = ""
    session_id = ""

    # Build tool_result lookup: tool_use_id → result text
    tool_results: dict[str, str] = {}
    for entry in entries:
        if entry.get("type") == "user":
            content = entry.get("message", {}).get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tid = block.get("tool_use_id", "")
                        rc = block.get("content", "")
                        if isinstance(rc, list):
                            rc = " ".join(c.get("text", "") for c in rc if isinstance(c, dict))
                        tool_results[tid] = str(rc)

    # Track cumulative cache totals so we can compute per-step deltas
    prev_cache_read     = 0
    prev_cache_creation = 0

    for entry in turn_entries:
        etype = entry.get("type")
        session_id = session_id or entry.get("sessionId", "")

        if etype == "user":
            content = entry.get("message", {}).get("content", [])
            if isinstance(content, str) and not user_prompt:
                user_prompt = content[:300]
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text" and not user_prompt:
                        user_prompt = block.get("text", "")[:300]

        elif etype == "assistant":
            msg = entry.get("message", {})
            u = msg.get("usage", {}) or {}

            cur_cache_read     = u.get("cache_read_input_tokens", 0) or 0
            cur_cache_creation = u.get("cache_creation_input_tokens", 0) or 0
            cur_output         = u.get("output_tokens", 0) or 0
            cur_input          = u.get("input_tokens", 0) or 0

            # Per-step context delta: new cache tokens processed + output generated this step
            step_input_delta = (cur_cache_read - prev_cache_read) + (cur_cache_creation - prev_cache_creation) + cur_input
            step_tokens = step_input_delta + cur_output

            prev_cache_read     = cur_cache_read
            prev_cache_creation = cur_cache_creation

            # input_tokens is incremental uncached-only — sum across the turn
            usage["input_tokens"]          += cur_input
            usage["output_tokens"]         += cur_output
            # cache fields are cumulative high-water marks — take max
            usage["cache_read_tokens"]     = max(usage["cache_read_tokens"],     cur_cache_read)
            usage["cache_creation_tokens"] = max(usage["cache_creation_tokens"], cur_cache_creation)
            cc = u.get("cache_creation", {}) or {}
            usage["cache_creation_1h_tokens"] = max(usage["cache_creation_1h_tokens"], cc.get("ephemeral_1h_input_tokens", 0) or 0)
            usage["cache_creation_5m_tokens"] = max(usage["cache_creation_5m_tokens"], cc.get("ephemeral_5m_input_tokens", 0) or 0)

            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_calls.append({
                        "tool_name": block.get("name", ""),
                        "tool_use_id": block.get("id", ""),
                        "input": block.get("input", {}),
                        "result_preview": tool_results.get(block.get("id", ""), "")[:200],
                        "step_tokens": step_tokens,
                    })

    return {
        "usage": usage,
        "tool_calls": tool_calls,
        "user_prompt": user_prompt,
        "session_id": session_id,
    }


def _post(url: str, payload: dict) -> bool:
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


def main():
    try:
        hook_input = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    entries = _load_transcript(hook_input)
    if not entries:
        sys.exit(0)

    turn_entries = _last_turn_entries(entries)
    parsed = _parse_transcript(entries, turn_entries)

    payload = {
        "session_id":  parsed["session_id"] or hook_input.get("session_id", ""),
        "user_prompt": parsed["user_prompt"],
        "usage":       parsed["usage"],
        "tool_calls":  parsed["tool_calls"],
        "cwd":         hook_input.get("cwd", ""),
    }

    _post(API_TELEMETRY_URL, payload)
    sys.exit(0)


if __name__ == "__main__":
    main()
