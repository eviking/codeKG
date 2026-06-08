"""
Transcript Analyser — correlates Claude Code .jsonl transcripts with MCP audit sessions.

For each MCP session, finds the matching Claude Code conversation and extracts:
  - The user's original prompt
  - Full tool call sequence in order (MCP + bash + read + edit)
  - Whether CodeKG was called first vs files read first
  - File read count before/after first MCP call
  - Total tool calls, unique files touched

The ~/.claude/projects directory is accessible via the /host-home mount.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


# Path to ~/.claude/projects inside the container
# The host home dir is always mounted at /host-home inside the container.
# HOST_HOME tells us the host-side path (e.g. /home/user or /Users/yourname) but inside
# the container we always use the mount point /host-home.
_CLAUDE_PROJECTS = Path("/host-home") / ".claude" / "projects"


def _parse_ts(ts: str) -> datetime | None:
    """Parse ISO timestamp to UTC datetime."""
    if not ts:
        return None
    try:
        # Handle both Z and +00:00 suffixes
        ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _decode_project_path(folder_name: str) -> str:
    """Convert encoded project folder name back to an absolute path.
    e.g. -Users-yourname-Documents-GitHub-django → /Users/yourname/Documents/GitHub/django
    """
    return folder_name.replace("-", "/", 1).replace("-", "/")


def _classify_tool(name: str) -> str:
    """Classify a tool call into a category."""
    if "codekg" in name or name in (
        "mcp__codekg__answer_question", "mcp__codekg__get_class",
        "mcp__codekg__search_classes", "mcp__codekg__get_module_context",
        "mcp__codekg__get_class_context", "mcp__codekg__get_codebase_template",
        "mcp__codekg__get_change_impact", "mcp__codekg__get_arch_patterns",
        "mcp__codekg__check_violations", "mcp__codekg__get_repo_summary",
    ):
        return "codekg"
    if name in ("Read", "mcp__Read"):
        return "read"
    if name in ("Bash", "mcp__Bash"):
        return "bash"
    if name in ("Edit", "Write", "mcp__Edit", "mcp__Write"):
        return "edit"
    if name in ("Grep", "mcp__Grep", "Find"):
        return "search"
    if name == "ToolSearch":
        return "toolsearch"
    return "other"


def _extract_tool_sequence(transcript_path: Path) -> dict[str, Any]:
    """
    Parse a .jsonl transcript and extract the tool call sequence with metadata.
    Returns a dict suitable for storing as JSON.
    """
    turns = []
    # agent_loops tracks where each user prompt starts a new loop.
    # Each entry: {"prompt": str, "turn_start": int (index into turns when loop began)}
    agent_loops: list[dict] = []
    _pending_prompt: str = ""   # user prompt seen, waiting for next tool call
    user_prompt = ""
    ts_start = None
    ts_end = None
    tok_input = 0
    tok_output = 0
    tok_cache_read = 0
    tok_cache_create = 0

    try:
        with open(transcript_path) as f:
            lines = [json.loads(ln.strip()) for ln in f if ln.strip()]
    except (OSError, ValueError):
        return {}

    for obj in lines:
        # Accumulate real token counts from assistant message usage blocks
        usage = obj.get("message", {}).get("usage", {})
        if usage:
            tok_input        += usage.get("input_tokens", 0)
            tok_output       += usage.get("output_tokens", 0)
            tok_cache_read   += usage.get("cache_read_input_tokens", 0)
            tok_cache_create += usage.get("cache_creation_input_tokens", 0)
        ts_raw = obj.get("timestamp", "")
        ts = _parse_ts(ts_raw)
        if ts:
            if ts_start is None or ts < ts_start:
                ts_start = ts
            if ts_end is None or ts > ts_end:
                ts_end = ts

        msg = obj.get("message", {})
        role = msg.get("role", "")
        content = msg.get("content", "")

        # Support both "human"/"assistant" and "user"/"assistant" role names,
        # and both string and list content formats.
        if role in ("human", "user"):
            # Extract the text of this user message
            prompt_text = ""
            if isinstance(content, str):
                prompt_text = content.strip()
            elif isinstance(content, list):
                for block in content:
                    if block.get("type") == "text" and block.get("text", "").strip():
                        prompt_text = block["text"].strip()
                        break
            # Only treat it as a real user prompt if it has substance
            # (skip tool_result injections which are also role=user)
            is_real_prompt = len(prompt_text) > 10 and not any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in (content if isinstance(content, list) else [])
            )
            if is_real_prompt:
                if not user_prompt:
                    user_prompt = prompt_text[:500]
                _pending_prompt = prompt_text[:500]

        elif role == "assistant" and isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_use":
                    name = block.get("name", "")
                    inp  = block.get("input", {})
                    cat  = _classify_tool(name)

                    # When a new user prompt was seen before this tool call,
                    # record that a new agent loop started here.
                    if _pending_prompt:
                        agent_loops.append({
                            "prompt":     _pending_prompt,
                            "turn_start": len(turns),
                        })
                        _pending_prompt = ""

                    # Extract a meaningful summary of the input
                    summary = ""
                    if cat == "codekg":
                        summary = (inp.get("question") or inp.get("fqn") or
                                   inp.get("query") or inp.get("repo_id") or "")
                    elif cat == "read":
                        summary = inp.get("file_path", "")
                    elif cat in ("bash", "search"):
                        summary = (inp.get("command") or inp.get("query") or "")[:120]
                    elif cat == "edit":
                        summary = inp.get("file_path", "")

                    turns.append({
                        "ts":      ts_raw,
                        "tool":    name,
                        "cat":     cat,
                        "summary": summary[:200],
                    })

    if not turns:
        return {}

    # Compute efficiency signals
    first_codekg_idx = next(
        (i for i, t in enumerate(turns) if t["cat"] == "codekg"), None
    )
    reads_before_codekg = sum(
        1 for t in turns[:first_codekg_idx or 0]
        if t["cat"] in ("read", "bash", "search")
    )
    reads_after_codekg = sum(
        1 for t in (turns[first_codekg_idx + 1:] if first_codekg_idx is not None else [])
        if t["cat"] in ("read", "bash", "search")
    )
    total_codekg  = sum(1 for t in turns if t["cat"] == "codekg")
    total_reads   = sum(1 for t in turns if t["cat"] == "read")
    total_bash    = sum(1 for t in turns if t["cat"] == "bash")
    total_edits   = sum(1 for t in turns if t["cat"] == "edit")

    unique_files = list(dict.fromkeys(
        t["summary"] for t in turns
        if t["cat"] in ("read", "edit") and t["summary"]
    ))

    codekg_first = (
        first_codekg_idx is not None and reads_before_codekg == 0
    )

    # Slice out the agent loop that contains the first CodeKG call:
    # from the loop's turn_start up to (not including) the next loop's turn_start.
    codekg_loop_prompt: str = ""
    codekg_loop_turns: list = []
    if first_codekg_idx is not None and agent_loops:
        # Find which loop contains first_codekg_idx
        containing_loop = None
        for i, loop in enumerate(agent_loops):
            next_start = agent_loops[i + 1]["turn_start"] if i + 1 < len(agent_loops) else len(turns)
            if loop["turn_start"] <= first_codekg_idx < next_start:
                containing_loop = loop
                loop_end = next_start
                break
        if containing_loop:
            codekg_loop_prompt = containing_loop["prompt"]
            codekg_loop_turns  = turns[containing_loop["turn_start"]:loop_end]
        else:
            # Fallback: no loop boundary found, use all turns
            codekg_loop_turns = turns

    # ── Token saving estimation ──────────────────────────────────────────────
    # Without CodeKG, Claude would need to blind-search through files to answer
    # the same question. We estimate avoided work based on the actual loop data.
    #
    # Model:
    #   avoided_tool_calls = BASELINE_BLIND_SEARCHES - reads_after_codekg
    #     BASELINE: empirical average for a "find where X is in a large codebase"
    #     question without KG assistance (~10 tool calls: grep, read, bash).
    #   saved_input_tok  = avoided_tool_calls × avg_context_growth_per_turn
    #     (each read/bash adds ~1500 tokens to context that Claude must re-read)
    #   saved_output_tok = avoided_tool_calls × avg_output_per_tool_call (~150 tok)
    #
    # These are clearly labelled estimates, not actuals.
    saved_input_tok  = 0
    saved_output_tok = 0
    saved_tool_calls = 0

    if first_codekg_idx is not None and tok_cache_read > 0 and codekg_loop_turns:
        BASELINE_BLIND_SEARCHES = 10   # typical blind search tool calls for a nav question
        AVG_OUTPUT_PER_TOOL    = 150   # tokens Claude outputs per tool invocation

        # Count *navigation* tool calls in the loop after the KG call and before
        # the first edit — these are the "still searching" calls that KG should
        # have eliminated. Reads/bash after the first edit are legitimate
        # implementation work and don't count as waste.
        kg_idx_in_loop = next(
            (i for i, t in enumerate(codekg_loop_turns) if t["cat"] == "codekg"), None
        )
        post_kg = codekg_loop_turns[kg_idx_in_loop + 1:] if kg_idx_in_loop is not None else []
        first_edit_in_post = next((i for i, t in enumerate(post_kg) if t["cat"] == "edit"), len(post_kg))
        nav_reads_after_kg = sum(
            1 for t in post_kg[:first_edit_in_post]
            if t["cat"] in ("read", "bash", "search")
        )

        loop_tool_count = len(codekg_loop_turns)
        loop_cache_read = tok_cache_read

        # Average context tokens added per tool call in this session
        avg_context_per_call = loop_cache_read / max(loop_tool_count, 1)

        # Avoided = baseline blind nav searches minus the nav still needed after KG
        avoided = max(0, BASELINE_BLIND_SEARCHES - nav_reads_after_kg)
        saved_tool_calls = avoided
        saved_input_tok  = round(avoided * avg_context_per_call)
        saved_output_tok = round(avoided * AVG_OUTPUT_PER_TOOL)

    return {
        "user_prompt":          user_prompt,
        "ts_start":             ts_start.isoformat() if ts_start else None,
        "ts_end":               ts_end.isoformat()   if ts_end   else None,
        "turns":                turns,
        "total_turns":          len(turns),
        "total_codekg":         total_codekg,
        "total_reads":          total_reads,
        "total_bash":           total_bash,
        "total_edits":          total_edits,
        "first_codekg_idx":     first_codekg_idx,
        "reads_before_codekg":  reads_before_codekg,
        "reads_after_codekg":   reads_after_codekg,
        "unique_files":         unique_files[:20],
        "codekg_first":         codekg_first,
        "codekg_loop_prompt":   codekg_loop_prompt,
        "codekg_loop_turns":    codekg_loop_turns,
        # Estimated tokens saved by using CodeKG instead of blind file search
        "saved_tool_calls":     saved_tool_calls,
        "saved_input_tok":      saved_input_tok,
        "saved_output_tok":     saved_output_tok,
        "transcript_file":      transcript_path.name,
        "project":              transcript_path.parent.name,
        # Real token counts from the API (not estimated)
        "tok_input":            tok_input,
        "tok_output":           tok_output,
        "tok_cache_read":       tok_cache_read,
        "tok_cache_create":     tok_cache_create,
        # Total billed tokens: input + output + cache_create (cache reads are ~10% cost)
        "tok_total_billed":     tok_input + tok_output + tok_cache_create,
    }


def _repo_path_to_project_dir(repo_path: str) -> Path | None:
    """
    Convert a repo host path like /host-home/Documents/GitHub/django
    to the matching Claude project directory name under _CLAUDE_PROJECTS.
    Claude encodes the path by replacing / with - (leading slash becomes leading -).
    e.g. /Users/yourname/Documents/GitHub/django
      -> -Users-yourname-Documents-GitHub-django
    We strip the /host-home prefix first to get the real host path.
    """
    # Strip /host-home mount prefix to get the path as it appears on the host
    p = repo_path
    if p.startswith("/host-home"):
        # e.g. /host-home/Documents/GitHub/django -> /home/user/Documents/GitHub/django
        # We don't know the host username exactly, so search by suffix match instead
        suffix = p[len("/host-home"):]  # e.g. /Documents/GitHub/django
        # Find which project dir ends with this suffix (encoded as -Documents-GitHub-django)
        encoded_suffix = suffix.replace("/", "-")  # -Documents-GitHub-django
        if not _CLAUDE_PROJECTS.exists():
            return None
        for d in _CLAUDE_PROJECTS.iterdir():
            if d.is_dir() and d.name.endswith(encoded_suffix):
                return d
        return None
    # Already a host path like /home/user/... or /Users/yourname/...
    encoded = p.replace("/", "-")  # e.g. -home-user-...
    candidate = _CLAUDE_PROJECTS / encoded
    if candidate.exists():
        return candidate
    return None


def find_transcript_for_session(
    session_ts: str,          # ISO timestamp of first MCP call in session
    session_ts_last: str,     # ISO timestamp of last MCP call
    window_seconds: int = 120,
    project_dir: Path | None = None,  # if known, only search this directory
    call_anchors: list[tuple[datetime, float]] | None = None,
    # Each anchor is (audit_ts, elapsed_ms): the audit DB records the ts *after*
    # the tool returns, so audit_ts - elapsed_ms ≈ when Claude started the tool call.
    # We match transcript turns within ANCHOR_TOLERANCE_S of that start time.
    anchor_tolerance_s: float = 5.0,
) -> dict[str, Any] | None:
    """
    Walk ~/.claude/projects (or a specific project_dir) looking for a transcript
    whose tool call timestamps align with the MCP session's calls.

    Primary matching: for each (audit_ts, elapsed_ms) anchor, compute the expected
    turn start = audit_ts - elapsed_ms, then find transcript turns within
    anchor_tolerance_s of that time. A transcript with any direct hit wins
    immediately over any transcript matched only by time-window overlap.
    """
    ts_first = _parse_ts(session_ts)
    ts_last  = _parse_ts(session_ts_last)
    if not ts_first:
        return None

    window = timedelta(seconds=window_seconds)
    best: dict | None = None
    best_score: float = float("inf")  # lower = better

    if not _CLAUDE_PROJECTS.exists():
        return None

    # Pre-compute expected turn start times from MCP audit anchors
    # anchor_score = 0 means a direct timestamp hit (beats any fallback)
    expected_starts: list[datetime] = []
    if call_anchors:
        for audit_ts, elapsed_ms in call_anchors:
            expected_starts.append(
                audit_ts - timedelta(milliseconds=max(elapsed_ms, 0))
            )

    # If we know the project directory, only search there; otherwise search all
    search_dirs = [project_dir] if project_dir and project_dir.is_dir() \
                  else [d for d in _CLAUDE_PROJECTS.iterdir() if d.is_dir()]

    for search_dir in search_dirs:
        if not search_dir.is_dir():
            continue
        for jsonl in search_dir.glob("*.jsonl"):
            try:
                # Quick pre-filter: mtime must be within 2h of the session
                mtime = datetime.fromtimestamp(jsonl.stat().st_mtime, tz=timezone.utc)
                if abs(mtime - ts_first) > timedelta(hours=2):
                    continue

                analysis = _extract_tool_sequence(jsonl)
                if not analysis or not analysis.get("ts_start"):
                    continue

                t_start = _parse_ts(analysis["ts_start"])
                t_end   = _parse_ts(analysis["ts_end"])
                if not t_start:
                    continue

                # Broad overlap check — must overlap the session window at all
                session_start = ts_first - window
                session_end   = (ts_last or ts_first) + window
                overlap_start = max(t_start, session_start)
                overlap_end   = min(t_end or t_start + timedelta(minutes=10), session_end)
                if overlap_end - overlap_start <= timedelta(0):
                    continue

                # --- Primary scoring: anchor-based ---
                # For each expected turn start, find the closest turn in this transcript.
                # Score = minimum seconds distance across all anchors.
                # Transcripts with a turn within anchor_tolerance_s get a "direct hit"
                # bonus (score < tolerance), beating any fallback match.
                turn_times = [
                    _parse_ts(t["ts"]) for t in analysis.get("turns", [])
                    if t.get("ts")
                ]
                turn_times = [tt for tt in turn_times if tt is not None]

                if expected_starts and turn_times:
                    score = min(
                        abs((tt - exp).total_seconds())
                        for exp in expected_starts
                        for tt in turn_times
                    )
                elif turn_times:
                    # Fallback: closest turn to ts_first
                    score = min(abs((tt - ts_first).total_seconds()) for tt in turn_times)
                else:
                    score = abs((t_start - ts_first).total_seconds())

                if score < best_score:
                    best_score = score
                    best = analysis

            except (ValueError, TypeError, AttributeError):
                continue

    return best


def _load_repos(repos_path: str | None = None) -> dict[str, str]:
    """Load repo_id -> host_path mapping from repos.json."""
    from shared.config import cfg as _cfg_tr
    path = repos_path or _cfg_tr.paths.repos_registry
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def analyse_all_sessions(db_path: str) -> list[dict]:
    """
    For all sessions in the MCP audit DB, find and attach transcript analysis.
    Matches each session to the Claude project directory for the repo it worked on.
    Returns list of enriched session dicts.
    """
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        con.row_factory = sqlite3.Row

        sessions = [dict(r) for r in con.execute("""
            SELECT s.session_id, s.started_at, s.client, s.last_seen,
                   s.call_count, s.error_count,
                   s.total_input_tok, s.total_output_tok,
                   MIN(c.ts) as first_call_ts,
                   MAX(c.ts) as last_call_ts
            FROM mcp_sessions s
            LEFT JOIN mcp_calls c USING (session_id)
            GROUP BY s.session_id
            ORDER BY s.last_seen DESC
            LIMIT 20
        """).fetchall()]

        # For each session, collect repo_id and precise (ts, elapsed_ms) anchors
        session_repos: dict[str, str] = {}
        session_anchors: dict[str, list[tuple[datetime, float]]] = {}
        for row in con.execute("""
            SELECT session_id, ts, elapsed_ms, arguments FROM mcp_calls
            WHERE ts IS NOT NULL
            ORDER BY ts
        """).fetchall():
            sid = row["session_id"]
            # Collect repo_id from first call that has one
            if sid not in session_repos:
                try:
                    args = json.loads(row["arguments"] or "{}")
                    repo_id = args.get("repo_id")
                    if repo_id:
                        session_repos[sid] = repo_id
                except (ValueError, KeyError):
                    pass
            # Collect anchors: (audit_ts, elapsed_ms)
            audit_ts = _parse_ts(row["ts"])
            if audit_ts:
                session_anchors.setdefault(sid, []).append(
                    (audit_ts, float(row["elapsed_ms"] or 0))
                )

        con.close()
    except Exception:  # DB may not exist on first run — return empty list
        return []

    repos = _load_repos()

    for s in sessions:
        # Resolve which Claude project directory to search
        repo_id = session_repos.get(s["session_id"])
        s["repo_id"] = repo_id
        project_dir: Path | None = None
        if repo_id and repo_id in repos:
            project_dir = _repo_path_to_project_dir(repos[repo_id])
            s["repo_path"] = repos[repo_id]

        analysis = find_transcript_for_session(
            s.get("first_call_ts") or s["started_at"],
            s.get("last_call_ts")  or s["started_at"],
            call_anchors=session_anchors.get(s["session_id"]),
            project_dir=project_dir,
        )
        s["transcript"] = analysis

    return sessions
