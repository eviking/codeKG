"""Console routes for the dashboard landing page. Watch out for query fan-out here, because this page aggregates several metrics into one response."""

from __future__ import annotations

import json
import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from shared.config import cfg
from deps import run_query, _template_ctx, templates

router = APIRouter()


def _compute_token_savings() -> dict | None:
    import sqlite3 as _sq, json as _json
    db_path = cfg.paths.mcp_audit_db
    total_kg_cache = 0
    total_kg_input = 0
    total_input    = 0
    seen_sessions: set = set()
    try:
        con = _sq.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3)
        rows = con.execute(
            "SELECT input_tokens_est, output_tokens_est, telemetry "
            "FROM mcp_calls WHERE telemetry IS NOT NULL AND turn_id IS NOT NULL"
        ).fetchall()
        con.close()
        for tok_in, tok_out, raw_telem in rows:
            try:
                telem = _json.loads(raw_telem)
            except ValueError:
                continue
            sid = telem.get("session_id", "")
            if sid and sid in seen_sessions:
                continue
            if sid:
                seen_sessions.add(sid)
            turns        = telem.get("turns", [])
            tok_in_total = telem.get("total_input_tokens", tok_in or 0)
            kg_turns     = [t for t in turns if t.get("cat") == "codekg"
                            or str(t.get("tool_name", "")).startswith("mcp__codekg__")]
            kg_cache = sum(t.get("cache_read_tokens", 0) for t in kg_turns)
            kg_input = sum(t.get("input_tokens", 0) for t in kg_turns)
            total_kg_cache += kg_cache
            total_kg_input += kg_input
            total_input    += tok_in_total + kg_cache
    except Exception:  # DB or schema may vary — return None to skip this metric
        return None

    if total_input == 0:
        return None
    return {
        "cache_pct": round(total_kg_cache / total_input * 100, 1),
        "input_pct": round(total_kg_input / max(total_input, 1) * 100, 1),
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    repo_stats = run_query("""
        MATCH (r:Repository)
        CALL {
            WITH r
            MATCH (c:Class {repo_id: r.repo_id})
            RETURN count(c) AS total_classes,
                   sum(CASE WHEN c.fqn CONTAINS 'Test' OR c.name ENDS WITH 'Test'
                            OR c.name ENDS WITH 'Tests' THEN 1 ELSE 0 END) AS test_classes
        }
        CALL { WITH r MATCH (m:Method {repo_id: r.repo_id}) RETURN count(m) AS total_methods }
        CALL { WITH r MATCH (p:Package {repo_id: r.repo_id}) RETURN count(p) AS total_packages }
        CALL { WITH r MATCH (ap:ArchPattern {repo_id: r.repo_id}) RETURN count(ap) AS patterns }
        CALL {
            WITH r
            MATCH (pol:ArchPolicy {repo_id: r.repo_id, status: 'active'})
            RETURN count(pol) AS active_policies
        }
        RETURN r.repo_id AS repo_id, r.name AS name, r.language AS language,
               r.build_tool AS build_tool, r.java_version AS java_version,
               r.last_commit AS last_commit, r.description AS description,
               r.hygiene_score AS hygiene_score, r.hygiene_grade AS hygiene_grade,
               r.hygiene_stats AS hygiene_stats,
               total_classes, test_classes, total_methods, total_packages,
               patterns, active_policies
        ORDER BY total_classes DESC
    """)

    global_counts = run_query("""
        CALL {
            MATCH (r:Repository) RETURN 'repos' AS k, count(r) AS v
            UNION ALL MATCH (c:Class) RETURN 'classes' AS k, count(c) AS v
            UNION ALL MATCH (m:Method) RETURN 'methods' AS k, count(m) AS v
            UNION ALL MATCH (p:Package) RETURN 'packages' AS k, count(p) AS v
            UNION ALL MATCH (ap:ArchPolicy {status:'active'}) RETURN 'active_policies' AS k, count(ap) AS v
            UNION ALL MATCH (ap:ArchPolicy {status:'auto-draft'}) RETURN 'pending_policies' AS k, count(ap) AS v
            UNION ALL MATCH ()-[:VIOLATES]->() RETURN 'violations' AS k, count(*) AS v
        }
        RETURN k, v
    """)
    gc = {row["k"]: row["v"] for row in global_counts}

    # Enrich repo_stats with hygiene savings pct from the JSON blob
    for r in repo_stats:
        try:
            hs = json.loads(r.get("hygiene_stats") or "{}")
            r["hygiene_savings_pct"] = hs.get("realistic_savings_pct", 0)
        except ValueError:
            r["hygiene_savings_pct"] = 0

    recent_events = []
    for r in repo_stats:
        if r.get("last_commit"):
            recent_events.append({
                "type": "scan", "repo_id": r["repo_id"],
                "repo_name": r["name"] or r["repo_id"],
                "message": f"Indexed {'{:,}'.format(r['total_classes'])} classes · {'{:,}'.format(r['total_methods'])} methods",
                "detail": r["last_commit"][:12],
            })

    draft_policies = run_query("""
        MATCH (ap:ArchPolicy {status: 'auto-draft'})
        RETURN ap.policy_id AS policy_id, ap.title AS title,
               ap.severity AS severity, ap.repo_id AS repo_id,
               ap.violator_count AS violator_count
        ORDER BY ap.violator_count DESC LIMIT 10
    """)
    for p in draft_policies:
        recent_events.append({
            "type": "policy", "repo_id": p["repo_id"], "repo_name": p["repo_id"],
            "policy_id": p["policy_id"], "message": p["title"],
            "detail": f"{p['violator_count'] or 0} violators · needs review",
            "severity": p["severity"],
        })

    recent_violations = run_query("""
        MATCH (c)-[:VIOLATES]->(ap:ArchPolicy)
        RETURN c.fqn AS fqn, ap.title AS policy_title,
               ap.policy_id AS policy_id, ap.severity AS severity, ap.repo_id AS repo_id
        LIMIT 10
    """)
    for v in recent_violations:
        recent_events.append({
            "type": "violation", "repo_id": v["repo_id"], "repo_name": v["repo_id"],
            "policy_id": v["policy_id"],
            "message": f"Violation: {v['fqn'].split('.')[-1] if v['fqn'] else '?'}",
            "detail": v["policy_title"], "severity": v["severity"],
        })

    tk_rows = run_query("""
        MATCH (tk:TribalKnowledge)
        WHERE coalesce(tk.hidden, false) = false
        RETURN coalesce(tk.repo_id, '') AS repo_id, count(tk) AS n
        ORDER BY n DESC
    """)
    tk_total  = sum(r["n"] for r in tk_rows)
    tk_by_repo = {r["repo_id"]: r["n"] for r in tk_rows if r["repo_id"]}

    return templates.TemplateResponse("dashboard.html", {
        **_template_ctx(request),
        "repo_stats":    repo_stats,
        "gc":            gc,
        "recent_events": recent_events,
        "token_savings": _compute_token_savings(),
        "tk_total":      tk_total,
        "tk_by_repo":    tk_by_repo,
    })
