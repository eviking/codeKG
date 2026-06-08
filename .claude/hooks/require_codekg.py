#!/usr/bin/env python3
"""
PreToolUse hook — blocks Read/Edit/Write/Bash unless codeKG was consulted
this turn. If blocked, the agent MUST:
  1. Say out loud why it is skipping codeKG (or that it forgot)
  2. Call answer_question / get_class_context / get_module_context first
  3. Then retry the original tool call
"""
import json
import os
import sys
from pathlib import Path

# Tools that require a prior codeKG call this turn
GATED_TOOLS = {"Read", "Edit", "Write", "MultiEdit"}

# For Bash, only gate write/destructive operations
BASH_WRITE_SIGNALS = [">", "mkdir", "touch", "mv ", "cp ", "rm ", "docker",
                      "sed ", "awk ", "tee ", "chmod", "chown"]

CODEKG_OPENERS = {
    "mcp__codekg__answer_question",
    "mcp__codekg__get_class_context",
    "mcp__codekg__get_module_context",
    "mcp__codekg__get_change_impact",
    "mcp__codekg__get_codebase_template",
    "mcp__codekg__search_classes",
    "mcp__codekg__get_class",
    "mcp__codekg__get_feature_context",
    "mcp__codekg__get_repo_summary",
    "mcp__codekg__capture_insight",
}

BLOCK_MESSAGE = (
    "⛔ codeKG not consulted this turn.\n"
    "\n"
    "Before reading or modifying files you MUST:\n"
    "  1. Say out loud that you are about to consult codeKG (or explain why you cannot)\n"
    "  2. Call mcp__codekg__answer_question with your intent as a natural-language question\n"
    "  3. Then proceed with the file operation\n"
    "\n"
    "This rule applies to every task regardless of apparent size.\n"
    "The only exceptions are: trivial one-line edits where file+line are already known\n"
    "from a prior codeKG call in this turn, or pure documentation changes."
)


def main():
    raw = sys.stdin.read()
    try:
        hook_input = json.loads(raw)
    except Exception:
        sys.exit(0)

    tool_name  = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    gated = False
    if tool_name in GATED_TOOLS:
        gated = True
    elif tool_name == "Bash":
        cmd = str(tool_input.get("command", ""))
        if any(s in cmd for s in BASH_WRITE_SIGNALS):
            gated = True

    if not gated:
        sys.exit(0)

    session_id = hook_input.get("session_id", "")
    if not session_id:
        sys.exit(0)

    claude_dir = Path.home() / ".claude"
    jsonl_files = list(claude_dir.rglob(f"{session_id}.jsonl"))
    if not jsonl_files:
        sys.exit(0)

    lines = jsonl_files[0].read_text(errors="replace").splitlines()

    found_codekg = False
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except Exception:
            continue

        etype = entry.get("type")

        if etype == "user":
            content = entry.get("message", {}).get("content", "")
            if isinstance(content, list):
                if all(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in content
                ):
                    continue
            break

        if etype == "assistant":
            for block in entry.get("message", {}).get("content", []):
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("name") in CODEKG_OPENERS
                ):
                    found_codekg = True
                    break

        if found_codekg:
            break

    if not found_codekg:
        print(json.dumps({
            "decision": "block",
            "reason": BLOCK_MESSAGE,
        }))
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
