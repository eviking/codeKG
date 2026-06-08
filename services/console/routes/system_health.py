"""Console routes for system health checks. Watch out for partial-failure handling here, because the page is most useful when one dependency is degraded rather than completely down."""

from __future__ import annotations

import re
import sqlite3 as _sq

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from shared.config import cfg
from deps import _template_ctx, templates, log

router = APIRouter()

# Pipeline stages matched against actual ingestion log msg fragments.
# Each entry: (stage_id, label, started_by, done_by)
# started_by  = fragment that appears when the stage begins
# done_by     = fragment that appears when the stage completes
# When "Full scan complete" is in logs every stage up through hygiene is implicitly done.
_PIPELINE_STAGES = [
    ("parse",         "Parse files",        "Full scan started",       "Parse phase complete"),
    ("write",         "Write to Neo4j",     "Parse phase complete",    "Object models built"),
    ("wire_edges",    "Wire edges",         "Parse phase complete",    "Object models built"),
    ("patterns",      "Detect patterns",    "Pattern detection",       "Pattern detection complete"),
    ("policies",      "Scan policies",      "Policy scan",             "Policy scan complete"),
    ("object_models", "Object models",      "Building object models",  "Object models written"),
    ("enrichment",    "Enrich classes",     "Enriching classes",       "Enrichment complete"),
    ("call_chains",   "Call chains",        "Building call chains",    "Call chains built"),
    ("hygiene",       "Hygiene scoring",    "Computing hygiene",       "Hygiene scoring complete"),
]


def _parse_pipeline_progress(logs: str) -> dict:
    """Parse structured log output from the ingestion container."""
    finished = "Full scan complete" in logs

    stages = []
    for sid, label, start_frag, done_frag in _PIPELINE_STAGES:
        started = start_frag in logs
        error   = False

        if not started:
            done = False
        elif start_frag == done_frag:
            done = logs.count(start_frag) >= 2
        else:
            idx_start = logs.index(start_frag)
            idx_done  = logs.find(done_frag, idx_start + len(start_frag))
            done = idx_done != -1

        # Everything up through hygiene is done when "Full scan complete" is logged.
        if finished:
            started = True
            done = True

        stages.append({"id": sid, "label": label, "started": started, "done": done,
                        "error": error, "error_detail": ""})

    # Determine running stage: last started-but-not-done stage
    running_idx = None
    for i, s in enumerate(stages):
        if s["started"] and not s["done"]:
            running_idx = i

    for i, s in enumerate(stages):
        if not s["started"]:
            s["status"] = "pending"
        elif s["done"]:
            s["status"] = "done"
        elif i == running_idx:
            s["status"] = "running"
        else:
            # started and a later stage is running → this one is effectively done
            s["status"] = "done"

    # File parse progress
    parse_done = parse_total = parse_errors = 0
    for m in re.finditer(r'"progress":\s*"(\d+)/(\d+)', logs):
        parse_done  = int(m.group(1))
        parse_total = int(m.group(2))
    m_complete = re.search(r'"parsed":\s*(\d+).*?"errors":\s*(\d+)', logs)
    if m_complete:
        parse_done   = int(m_complete.group(1))
        parse_errors = int(m_complete.group(2))

    # Elapsed from "Full scan complete"
    elapsed_ms = None
    m_done = re.search(r'"elapsed_ms":\s*(\d+).*?Full scan complete|Full scan complete.*?"elapsed_ms":\s*(\d+)', logs)
    if not m_done:
        # Try last elapsed_ms occurrence near the end
        for m in re.finditer(r'"elapsed_ms":\s*(\d+)', logs):
            elapsed_ms = int(m.group(1))
    else:
        elapsed_ms = int(m_done.group(1) or m_done.group(2))

    return {
        "stages":        stages,
        "parse_done":    parse_done,
        "parse_total":   parse_total,
        "parse_errors":  parse_errors,
        "elapsed_ms":    elapsed_ms,
        "finished":      finished,
    }


@router.get("/system-health", response_class=HTMLResponse)
async def system_health_page(request: Request):
    return templates.TemplateResponse("system_health.html", {**_template_ctx(request)})


@router.get("/api/system-health")
async def system_health_api():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    # ── Docker stats via unix socket ──────────────────────────────────────
    containers = {}
    try:
        _docker = httpx.Client(
            transport=httpx.HTTPTransport(uds="/var/run/docker.sock"),
            base_url="http://docker",
            timeout=8,
        )

        def _docker_get(path):
            return _docker.get(path).json()

        for ctr in _docker_get("/containers/json?all=true"):
            name   = (ctr.get("Names") or [""])[0].lstrip("/")
            short  = name.replace("codekg-", "")
            status = "running" if ctr.get("State") == "running" else "stopped"
            containers[short] = {
                "name": name, "status": status,
                "status_text": ctr.get("Status", ""),
                "cpu_pct": 0, "mem_pct": 0,
                "mem_usage": "—", "mem_limit": "—",
                "net_io": "—", "blk_io": "—", "pids": 0,
            }
            if status == "running":
                try:
                    cid = ctr["Id"]
                    st  = _docker_get(f"/containers/{cid}/stats?stream=false")

                    cpu_delta = (st["cpu_stats"]["cpu_usage"]["total_usage"]
                                 - st["precpu_stats"]["cpu_usage"]["total_usage"])
                    sys_delta = (st["cpu_stats"]["system_cpu_usage"]
                                 - st["precpu_stats"]["system_cpu_usage"])
                    ncpu      = st["cpu_stats"].get("online_cpus") or len(
                        st["cpu_stats"]["cpu_usage"].get("percpu_usage") or [1])
                    cpu_pct   = (cpu_delta / sys_delta * ncpu * 100) if sys_delta > 0 else 0

                    mem       = st["memory_stats"]
                    mem_used  = mem.get("usage", 0) - mem.get("stats", {}).get("cache", 0)
                    mem_lim   = mem.get("limit", 1)
                    mem_pct   = mem_used / mem_lim * 100 if mem_lim else 0

                    def _fmt(b):
                        if b >= 1073741824: return f"{b/1073741824:.1f}GiB"
                        if b >= 1048576:    return f"{b/1048576:.1f}MiB"
                        return f"{b/1024:.0f}KiB"

                    nets  = st.get("networks", {})
                    rx    = sum(v.get("rx_bytes", 0) for v in nets.values())
                    tx    = sum(v.get("tx_bytes", 0) for v in nets.values())
                    bio   = st.get("blkio_stats", {}).get("io_service_bytes_recursive") or []
                    bread = sum(x["value"] for x in bio if x.get("op", "").lower() == "read")
                    bwrite= sum(x["value"] for x in bio if x.get("op", "").lower() == "write")

                    containers[short].update({
                        "cpu_pct":   round(cpu_pct, 2),
                        "mem_usage": _fmt(mem_used), "mem_limit": _fmt(mem_lim),
                        "mem_pct":   round(mem_pct, 2),
                        "net_io":    f"{_fmt(rx)} / {_fmt(tx)}",
                        "blk_io":    f"{_fmt(bread)} / {_fmt(bwrite)}",
                        "pids":      st.get("pids_stats", {}).get("current", 0),
                    })
                except (KeyError, TypeError, ZeroDivisionError):
                    pass
        _docker.close()
    except Exception as e:
        containers["_error"] = str(e)

    # ── Neo4j detailed metrics ─────────────────────────────────────────────
    neo4j = {}
    try:
        from neo4j import GraphDatabase as _GD
        _drv = _GD.driver(
            cfg.neo4j.uri,
            auth=(cfg.neo4j.user, cfg.neo4j.password),
        )
        with _drv.session() as s:
            heap_row = list(s.run(
                "CALL dbms.queryJmx('java.lang:type=Memory') YIELD attributes "
                "RETURN attributes.HeapMemoryUsage AS h, attributes.NonHeapMemoryUsage AS nh"
            ))[0]
            h  = heap_row["h"]["value"]["properties"]
            nh = heap_row["nh"]["value"]["properties"]
            neo4j.update({
                "heap_used_mb":      round(h["used"] / 1024 / 1024),
                "heap_committed_mb": round(h["committed"] / 1024 / 1024),
                "heap_max_mb":       round(h["max"] / 1024 / 1024),
                "heap_pct":          round(h["used"] / h["max"] * 100, 1),
                "nonheap_used_mb":   round(nh["used"] / 1024 / 1024),
            })

            os_row = list(s.run(
                "CALL dbms.queryJmx('java.lang:type=OperatingSystem') YIELD attributes RETURN attributes"
            ))[0]["attributes"]
            def _v(attrs, key): return attrs.get(key, {}).get("value", 0)
            neo4j.update({
                "process_cpu_load": round(_v(os_row, "ProcessCpuLoad") * 100, 1),
                "system_cpu_load":  round(_v(os_row, "SystemCpuLoad") * 100, 1),
                "free_phys_mb":     round(_v(os_row, "FreePhysicalMemorySize") / 1024 / 1024),
                "total_phys_mb":    round(_v(os_row, "TotalPhysicalMemorySize") / 1024 / 1024),
                "open_fds":         _v(os_row, "OpenFileDescriptorCount"),
                "max_fds":          _v(os_row, "MaxFileDescriptorCount"),
                "load_avg":         round(_v(os_row, "SystemLoadAverage"), 2),
            })

            node_rows = list(s.run(
                "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY cnt DESC LIMIT 15"
            ))
            neo4j["node_counts"] = [{"label": r["label"], "count": r["cnt"]} for r in node_rows]
            neo4j["total_nodes"] = sum(r["cnt"] for r in node_rows)

            rel_rows = list(s.run(
                "MATCH ()-[r]->() RETURN type(r) AS rel, count(r) AS cnt ORDER BY cnt DESC LIMIT 10"
            ))
            neo4j["rel_counts"] = [{"type": r["rel"], "count": r["cnt"]} for r in rel_rows]
            neo4j["total_rels"]  = sum(r["cnt"] for r in rel_rows)

            repo_rows = list(s.run(
                "MATCH (r:Repository) RETURN r.repo_id AS id, r.language AS lang, "
                "r.last_commit AS sha ORDER BY r.repo_id"
            ))
            neo4j["repos"] = [{"id": r["id"], "lang": r["lang"],
                                "sha": (r["sha"] or "")[:8]} for r in repo_rows]
        _drv.close()
        neo4j["status"] = "ok"
    except Exception as e:
        neo4j.update({"status": "error", "error": str(e)})

    # ── Active scan containers + recent log ───────────────────────────────
    ingestion = {"status": "ok", "active_scans": [], "recent_scans": []}
    try:
        from scan_launcher import list_active_scans, recent_scan_logs
        active = list_active_scans()
        ingestion["active_scans"] = active
        ingestion["scanning"] = bool(active)
        ingestion["recent_scans"] = recent_scan_logs(limit=10)
    except Exception as e:
        ingestion.update({"status": "error", "error": str(e)})

    # ── API service health ─────────────────────────────────────────────────
    api_svc = {"status": "unknown"}
    try:
        resp = httpx.get("http://api:8000/health", timeout=3)
        api_svc["status"] = "ok" if resp.status_code == 200 else "error"
    except Exception as e:
        api_svc.update({"status": "unreachable", "error": str(e)})

    # ── LLM audit stats (last 24h) ─────────────────────────────────────────
    llm_stats = []
    llm_total = {"calls": 0, "cost_usd": 0}
    try:
        audit_path = cfg.paths.llm_audit_db
        con = _sq.connect(audit_path)
        for row in con.execute("""
            SELECT source, COUNT(*) as calls, ROUND(AVG(elapsed_ms)) as avg_ms,
                   ROUND(SUM(cost_usd), 4) as cost_usd,
                   SUM(CASE WHEN error IS NOT NULL AND error != '' THEN 1 ELSE 0 END) as errors
            FROM llm_calls WHERE ts > datetime('now', '-24 hours')
            GROUP BY source ORDER BY calls DESC
        """).fetchall():
            llm_stats.append({"source": row[0], "calls": row[1],
                               "avg_ms": row[2], "cost_usd": row[3], "errors": row[4]})
        total = con.execute(
            "SELECT COUNT(*), ROUND(SUM(cost_usd),4) FROM llm_calls "
            "WHERE ts > datetime('now', '-24 hours')"
        ).fetchone()
        con.close()
        llm_total = {"calls": total[0], "cost_usd": total[1]}
    except Exception as e:
        log.warning("Failed to read LLM cost totals from DB", exc=e)

    return {
        "ts": now, "containers": containers, "neo4j": neo4j,
        "ingestion": ingestion, "api": api_svc,
        "llm_stats": llm_stats, "llm_total": llm_total,
    }


@router.get("/api/system-health/scan-progress/{repo_id:path}")
async def scan_progress(repo_id: str):
    """Live pipeline progress for a running scan — parses container logs."""
    from scan_launcher import get_scan_logs, list_active_scans, recent_scan_logs
    active = {s["repo_id"] for s in list_active_scans()}
    if repo_id not in active:
        # Not running — check if we have finished logs in the DB
        recent = recent_scan_logs(limit=20)
        for row in recent:
            if row["repo_id"] == repo_id and row["status"] != "running":
                progress = _parse_pipeline_progress(row.get("logs") or "")
                progress["running"] = False
                progress["repo_id"] = repo_id
                return JSONResponse(progress)
        return JSONResponse({"running": False, "repo_id": repo_id, "stages": []})

    logs = get_scan_logs(repo_id) or ""
    progress = _parse_pipeline_progress(logs)
    progress["running"] = True
    progress["repo_id"] = repo_id
    return JSONResponse(progress)


@router.post("/api/system-health/cancel-scan")
async def cancel_scan(repo_id: str = ""):
    from scan_launcher import cancel_scan as _cancel, list_active_scans
    if repo_id:
        ok = _cancel(repo_id)
        return JSONResponse({"cancelled": ok, "repo_id": repo_id})
    # Cancel all running scans
    active = list_active_scans()
    results = [{"repo_id": s["repo_id"], "cancelled": _cancel(s["repo_id"])} for s in active]
    return JSONResponse({"results": results})
