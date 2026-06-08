"""Console routes for MCP audit history and maintenance. Watch out for schema migrations here, because startup and UI flows both touch the same audit database."""

from __future__ import annotations

import asyncio
import json as _json
import os
import sqlite3 as _sq

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from shared.config import cfg
from deps import _template_ctx, templates, log

router = APIRouter()

MCP_AUDIT_DB = cfg.paths.mcp_audit_db

_CODEKG_TOOLS = {
    "answer_question", "get_class", "search_classes", "get_module_context",
    "get_class_context", "get_feature_context", "get_change_impact",
    "get_repo_summary", "get_codebase_template", "get_arch_patterns",
    "check_violations", "list_arch_policies",
}


def migrate(db_path: str) -> None:
    try:
        con = _sq.connect(db_path)
        existing = {r[1] for r in con.execute("PRAGMA table_info(mcp_calls)")}
        for col, defn in [
            ("request_id",         "TEXT"),
            ("input_tokens_est",   "INTEGER DEFAULT 0"),
            ("output_tokens_est",  "INTEGER DEFAULT 0"),
            ("telemetry",          "TEXT"),
            ("learnings",          "TEXT"),
            ("nodes_consulted",    "INTEGER DEFAULT 0"),
            ("raw_source_chars",   "INTEGER DEFAULT 0"),
            ("raw_source_tokens",  "INTEGER DEFAULT 0"),
            ("response_tokens",    "INTEGER DEFAULT 0"),
            ("net_savings_tokens", "INTEGER DEFAULT 0"),
            ("compression_ratio",  "REAL DEFAULT 0"),
        ]:
            if col not in existing:
                con.execute(f"ALTER TABLE mcp_calls ADD COLUMN {col} {defn}")
        existing_s = {r[1] for r in con.execute("PRAGMA table_info(mcp_sessions)")}
        for col, defn in [
            ("total_input_tok",           "INTEGER DEFAULT 0"),
            ("total_output_tok",          "INTEGER DEFAULT 0"),
            ("total_raw_source_tokens",   "INTEGER DEFAULT 0"),
            ("total_response_tokens",     "INTEGER DEFAULT 0"),
            ("total_net_savings_tokens",  "INTEGER DEFAULT 0"),
        ]:
            if col not in existing_s:
                con.execute(f"ALTER TABLE mcp_sessions ADD COLUMN {col} {defn}")
        con.commit()
        con.close()
    except Exception as e:
        log.warning("Failed to init mcp_audit DB", exc=e)


def _cat(tool_name: str) -> str:
    tn = tool_name.lower().replace("mcp__codekg__", "")
    if tn in {t.lower() for t in _CODEKG_TOOLS}: return "codekg"
    if "read"  in tn: return "read"
    if "write" in tn or "edit" in tn: return "edit"
    if "bash"  in tn or "run"  in tn: return "bash"
    if "search" in tn or "grep" in tn: return "search"
    return "other"


def _query(db_path: str, limit: int, session_id: str, tool: str, status: str, since: str = "") -> dict:
    result: dict = {"calls": [], "sessions": [], "stats": {}, "tool_breakdown": []}
    try:
        con = _sq.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False, timeout=5)
        con.row_factory = _sq.Row
        where = ["1=1"]; params: list = []
        if session_id: where.append("session_id = ?"); params.append(session_id)
        if tool:       where.append("tool = ?");       params.append(tool)
        if status:     where.append("status = ?");     params.append(status)
        if since:
            where.append("REPLACE(ts, '+00:00', '') > ?"); params.append(since)

        result["calls"] = [dict(r) for r in con.execute(f"""
            SELECT id, ts, session_id, session_client, request_id, turn_id, tool,
                   arguments, response_size, elapsed_ms, status, error, response_preview,
                   input_tokens_est, output_tokens_est,
                   CASE WHEN telemetry IS NOT NULL THEN 1 ELSE 0 END as has_telemetry
            FROM mcp_calls WHERE {' AND '.join(where)}
            ORDER BY ts DESC LIMIT ?
        """, params + [limit]).fetchall()]

        result["sessions"] = [dict(r) for r in con.execute("""
            SELECT session_id, started_at, client, last_seen, call_count, error_count,
                   total_input_tok, total_output_tok,
                   total_raw_source_tokens, total_response_tokens, total_net_savings_tokens
            FROM mcp_sessions ORDER BY last_seen DESC LIMIT 50
        """).fetchall()]

        row = con.execute("""
            SELECT COUNT(*) as total_calls, COUNT(DISTINCT session_id) as total_sessions,
                   SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as total_errors,
                   ROUND(AVG(elapsed_ms)) as avg_ms, MAX(elapsed_ms) as max_ms,
                   SUM(input_tokens_est) as total_input_tok,
                   SUM(output_tokens_est) as total_output_tok,
                   SUM(raw_source_tokens) as total_raw_source_tokens,
                   SUM(net_savings_tokens) as total_net_savings_tokens
            FROM mcp_calls WHERE REPLACE(ts, '+00:00', '') > datetime('now', '-24 hours')
        """).fetchone()
        result["stats"] = dict(row) if row else {}

        result["tool_breakdown"] = [dict(r) for r in con.execute("""
            SELECT tool, COUNT(*) as n, ROUND(AVG(elapsed_ms)) as avg_ms,
                   SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as errors,
                   SUM(input_tokens_est) as input_tok, SUM(output_tokens_est) as output_tok,
                   SUM(raw_source_tokens) as raw_source_tokens,
                   SUM(net_savings_tokens) as net_savings_tokens
            FROM mcp_calls WHERE REPLACE(ts, '+00:00', '') > datetime('now', '-24 hours')
            GROUP BY tool ORDER BY n DESC
        """).fetchall()]
        con.close()
    except Exception as e:
        result["error"] = str(e)
    return result


def _analysed_from_db(db_path: str) -> list[dict]:
    try:
        con = _sq.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        con.row_factory = _sq.Row
        rows = con.execute("""
            SELECT id, ts, session_id, request_id, tool, arguments,
                   elapsed_ms, input_tokens_est, output_tokens_est, telemetry, learnings
            FROM mcp_calls WHERE telemetry IS NOT NULL
            ORDER BY ts DESC LIMIT 200
        """).fetchall()
        con.close()
    except Exception as e:
        log.warning("Failed to read mcp_audit sessions from DB", exc=e)
        return []

    results = []
    for r in rows:
        row = dict(r)
        try:
            telem = _json.loads(row["telemetry"])
        except ValueError:
            telem = {}

        raw_turns = telem.get("turns", [])
        tok_in    = telem.get("total_input_tokens",      row.get("input_tokens_est",  0))
        tok_out   = telem.get("total_output_tokens",     row.get("output_tokens_est", 0))
        tok_cache = telem.get("total_cache_read_tokens", 0)

        normalised_turns = []
        for t in raw_turns:
            tn = t.get("tool_name", t.get("tool", ""))
            normalised_turns.append({
                "tool":               tn,
                "cat":                _cat(tn),
                "ts":                 None,
                "summary":            t.get("summary", ""),
                "input_tokens":       t.get("input_tokens", 0),
                "output_tokens":      t.get("output_tokens", 0),
                "cache_read_tokens":  t.get("cache_read_tokens", 0),
                "raw_source_tokens":  t.get("raw_source_tokens", 0),
                "response_tokens":    t.get("response_tokens", 0),
                "net_savings_tokens": t.get("net_savings_tokens", 0),
                "nodes_consulted":    t.get("nodes_consulted", 0),
            })

        nav_turns    = [t for t in normalised_turns if t["cat"] not in ("codekg", "edit", "other")]
        codekg_turns = [t for t in normalised_turns if t["cat"] == "codekg"]

        # Real savings from telemetry (read from codekg_meta comments by Claude)
        total_raw_src   = telem.get("total_raw_source_tokens", 0) or sum(t.get("raw_source_tokens", 0) for t in codekg_turns)
        total_codekg_r  = telem.get("total_codekg_response_tokens", 0) or sum(t.get("response_tokens", 0) for t in codekg_turns)
        total_savings   = telem.get("total_net_savings_tokens", 0) or max(0, total_raw_src - total_codekg_r)
        savings_pct     = telem.get("savings_pct", 0) or (round(total_savings / tok_in * 100, 1) if tok_in > 0 else 0)
        compression     = telem.get("compression_ratio", 0) or (round(total_raw_src / total_codekg_r, 1) if total_codekg_r > 0 else 0)

        # Has real measurements (source_chars was populated during ingestion)
        has_real_savings = total_raw_src > 0

        transcript = {
            "tok_input":              tok_in,
            "tok_output":             tok_out,
            "tok_cache_read":         tok_cache,
            "tok_cache_create":       0,
            "tok_total_billed":       tok_in + tok_out,
            "user_prompt":            telem.get("user_prompt", ""),
            "codekg_loop_prompt":     telem.get("user_prompt", ""),
            "codekg_loop_turns":      normalised_turns,
            "turns":                  normalised_turns,
            "total_turns":            len(normalised_turns),
            "total_codekg":           len(codekg_turns),
            "codekg_first":           bool(normalised_turns and normalised_turns[0]["cat"] == "codekg"),
            "reads_before_codekg":    0,
            "reads_after_codekg":     len(nav_turns),
            # Real savings metrics
            "raw_source_tokens":      total_raw_src,
            "codekg_response_tokens": total_codekg_r,
            "net_savings_tokens":     total_savings,
            "savings_pct":            savings_pct,
            "compression_ratio":      compression,
            "has_real_savings":       has_real_savings,
            # Legacy fields kept for template compatibility
            "saved_tool_calls":       len(codekg_turns),
            "saved_input_tok":        total_savings,
            "saved_output_tok":       0,
            "kg_input_tokens":        total_codekg_r,
            "kg_output_tokens":       0,
            "kg_cache_tokens":        tok_cache,
            "transcript_file":        f"telemetry · session {row['session_id']}",
            "source":                 "telemetry",
        }

        learnings = []
        try:
            raw_learnings = row.get("learnings")
            if raw_learnings:
                learnings = _json.loads(raw_learnings)
        except ValueError:
            pass
        if not learnings:
            learnings = telem.get("learnings", [])

        results.append({
            "call_id":    row["id"],
            "ts":         row["ts"],
            "session_id": row["session_id"],
            "request_id": row["request_id"],
            "turn_id":    row.get("turn_id") or "",
            "tool":       row["tool"],
            "elapsed_ms": row["elapsed_ms"],
            "transcript": transcript,
            "learnings":  learnings,
            "source":     "telemetry",
        })
    return results


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@router.get("/mcp-audit", response_class=HTMLResponse)
async def mcp_audit_page(request: Request):
    return templates.TemplateResponse("mcp_audit.html", {**_template_ctx(request)})


@router.get("/api/mcp-audit")
async def mcp_audit_api(limit: int = 200, session_id: str = "", tool: str = "", status: str = "", since: str = ""):
    return await asyncio.to_thread(_query, MCP_AUDIT_DB, limit, session_id, tool, status, since)


@router.get("/api/mcp-audit/call/{call_id}")
async def mcp_audit_call_detail(call_id: int):
    def _fetch():
        con = _sq.connect(f"file:{MCP_AUDIT_DB}?mode=ro", uri=True, timeout=5)
        con.row_factory = _sq.Row
        row = con.execute("SELECT * FROM mcp_calls WHERE id = ?", (call_id,)).fetchone()
        con.close()
        return dict(row) if row else None

    try:
        row = await asyncio.to_thread(_fetch)
        if not row:
            raise HTTPException(status_code=404, detail="Call not found")
        return row
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/mcp-audit/sessions/analysed")
async def mcp_sessions_analysed():
    return await asyncio.to_thread(_analysed_from_db, MCP_AUDIT_DB)
