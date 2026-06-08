#!/usr/bin/env python3
"""
CodeKG Health Inspector
=======================
Produces a structured health report for the entire CodeKG stack.
Designed to be run by IT-OPS and fed back to engineering for diagnosis.

Usage:
    python3 scripts/healthcheck.py              # pretty-printed to stdout
    python3 scripts/healthcheck.py --json       # machine-readable JSON
    python3 scripts/healthcheck.py --out report.txt   # write to file

Requirements: docker (CLI), curl, python3 ≥ 3.9
Optionally:   python3-requests (falls back to urllib if absent)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ENV_FILE     = PROJECT_ROOT / ".env"

SERVICES = {
    "neo4j":     {"container": "codekg-neo4j",     "port": 7474, "path": "/",            "protocol": "http"},
    "api":       {"container": "codekg-api",        "port": 8000, "path": "/health",      "protocol": "http"},
    "console":   {"container": "codekg-console",    "port": 8080, "path": "/health",      "protocol": "http"},
    "ingestion": {"container": "codekg-ingestion",  "port": None, "path": None,           "protocol": None},
    "watcher":   {"container": "codekg-watcher",    "port": None, "path": None,           "protocol": None},
    "mcp":       {"container": "codekg-mcp",        "port": None, "path": None,           "protocol": None},
}

# Thresholds that trigger warnings/errors in the report
THRESHOLDS = {
    "cpu_warn_pct":        50.0,   # container CPU %
    "cpu_crit_pct":        90.0,
    "mem_warn_pct":        70.0,   # container mem %
    "mem_crit_pct":        90.0,
    "neo4j_heap_warn_pct": 75.0,
    "neo4j_heap_crit_pct": 90.0,
    "tx_warn_secs":        30,     # long-running Neo4j transaction
    "tx_crit_secs":        120,
    "log_error_warn":      5,      # error lines in last 500 log lines
    "log_error_crit":      20,
    "restart_warn":        3,      # container restart count
    "restart_crit":        10,
    "watcher_loop_warn":   5,      # consecutive "triggering full scan" without completion
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except FileNotFoundError as e:
        return -2, "", str(e)


def _http_get(url: str, timeout: int = 5) -> tuple[int, str]:
    """Returns (status_code, body). status_code=-1 means connection error."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return -1, str(e)


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _neo4j_query(cypher: str, env: dict[str, str]) -> list[dict]:
    password = env.get("NEO4J_PASSWORD", "codekg_dev")
    url = "http://localhost:7474/db/neo4j/tx/commit"
    payload = json.dumps({"statements": [{"statement": cypher}]}).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Basic " + __import__("base64").b64encode(
                f"neo4j:{password}".encode()).decode()
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("errors"):
                return []
            rows = []
            results = data.get("results", [])
            if results and results[0].get("data"):
                cols = results[0]["columns"]
                for d in results[0]["data"]:
                    rows.append(dict(zip(cols, d["row"])))
            return rows
    except Exception:
        return []


def _parse_duration_secs(iso: str) -> float:
    """Convert Neo4j duration string like PT17.621S or PT2M3S to seconds."""
    if not iso:
        return 0.0
    iso = iso.upper().lstrip("PT")
    total = 0.0
    for part in re.findall(r"[\d.]+[SMHD]", iso + ("S" if iso[-1:].isdigit() else "")):
        val, unit = float(part[:-1]), part[-1]
        total += val * {"S": 1, "M": 60, "H": 3600, "D": 86400}.get(unit, 1)
    return total


# ── Collectors ────────────────────────────────────────────────────────────────

def collect_docker_overview() -> dict[str, Any]:
    """docker ps + stats for all codekg containers."""
    rc, out, _ = _run(["docker", "ps", "--filter", "name=codekg-",
                        "--format", "{{.Names}}\t{{.Status}}\t{{.RunningFor}}"])
    containers: dict[str, dict] = {}
    if rc == 0:
        for line in out.splitlines():
            parts = line.split("\t")
            name = parts[0] if parts else "?"
            containers[name] = {
                "status_text": parts[1] if len(parts) > 1 else "unknown",
                "running_for": parts[2] if len(parts) > 2 else "unknown",
                "running": "Up" in (parts[1] if len(parts) > 1 else ""),
            }

    # Restart counts
    rc2, out2, _ = _run(["docker", "inspect",
                          "--format", "{{.Name}}\t{{.RestartCount}}",
                          *[s["container"] for s in SERVICES.values()]])
    if rc2 == 0:
        for line in out2.splitlines():
            parts = line.split("\t")
            name = parts[0].lstrip("/")
            if name in containers and len(parts) > 1:
                containers[name]["restarts"] = int(parts[1])

    # CPU + memory stats (one-shot)
    rc3, out3, _ = _run(["docker", "stats", "--no-stream", "--no-trunc",
                          "--format",
                          "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"])
    if rc3 == 0:
        for line in out3.splitlines():
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            name = parts[0]
            if name not in containers:
                containers[name] = {}
            containers[name]["cpu_pct"]  = float(parts[1].rstrip("%") or 0)
            containers[name]["mem_usage"] = parts[2]
            containers[name]["mem_pct"]  = float(parts[3].rstrip("%") or 0)

    return containers


def collect_neo4j_health(env: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}

    # HTTP reachable?
    status, body = _http_get("http://localhost:7474/", timeout=5)
    result["http_status"] = status
    result["http_ok"] = status == 200

    # JVM heap from Neo4j metrics (community edition)
    jvm_rows = _neo4j_query(
        "CALL dbms.queryJmx('java.lang:type=Memory') YIELD name, attributes "
        "RETURN name, attributes", env)
    if jvm_rows:
        try:
            attrs = jvm_rows[0].get("attributes", {})
            heap = attrs.get("HeapMemoryUsage", {}).get("value", {})
            result["heap_used_mb"]  = round(heap.get("used", 0) / 1048576)
            result["heap_max_mb"]   = round(heap.get("max",  0) / 1048576)
            result["heap_used_pct"] = round(
                heap.get("used", 0) / max(heap.get("max", 1), 1) * 100, 1)
        except Exception:
            pass

    # Active transactions
    txn_rows = _neo4j_query(
        "SHOW TRANSACTIONS YIELD transactionId, currentQuery, elapsedTime, status "
        "RETURN transactionId, left(currentQuery,200) AS query, elapsedTime, status", env)
    transactions = []
    for row in txn_rows:
        elapsed_str = str(row.get("elapsedTime", "PT0S"))
        elapsed_s = _parse_duration_secs(elapsed_str)
        transactions.append({
            "id":      row.get("transactionId"),
            "elapsed_s": elapsed_s,
            "elapsed_str": elapsed_str,
            "status":  row.get("status"),
            "query":   (row.get("query") or "")[:120],
        })
    result["transactions"] = sorted(transactions, key=lambda t: -t["elapsed_s"])

    # KG node counts
    count_rows = _neo4j_query("""
        CALL {
            MATCH (c:Class)    RETURN 'Class'    AS label, count(c) AS n
            UNION ALL
            MATCH (m:Method)   RETURN 'Method'   AS label, count(m) AS n
            UNION ALL
            MATCH (p:Package)  RETURN 'Package'  AS label, count(p) AS n
            UNION ALL
            MATCH (r:Repository) RETURN 'Repository' AS label, count(r) AS n
        } RETURN label, n ORDER BY label
    """, env)
    result["node_counts"] = {r["label"]: r["n"] for r in count_rows}

    # Repos and their last_commit status
    repo_rows = _neo4j_query(
        "MATCH (r:Repository) RETURN r.repo_id AS repo_id, r.last_commit AS last_commit", env)
    result["repos"] = repo_rows

    # Indexes
    idx_rows = _neo4j_query(
        "SHOW INDEXES YIELD name, labelsOrTypes, properties, state "
        "RETURN name, labelsOrTypes, properties, state", env)
    result["indexes"] = idx_rows
    result["indexes_not_online"] = [i for i in idx_rows if i.get("state") != "ONLINE"]

    return result


def collect_service_health() -> dict[str, Any]:
    results: dict[str, Any] = {}
    for svc, cfg in SERVICES.items():
        port = cfg.get("port")
        path = cfg.get("path")
        entry: dict[str, Any] = {"endpoint_checked": port is not None}
        if port and path:
            url = f"http://localhost:{port}{path}"
            status, body = _http_get(url)
            entry["http_status"] = status
            entry["http_ok"] = status in (200, 404)  # 404 ok for neo4j browser
            try:
                entry["response_json"] = json.loads(body)
            except Exception:
                entry["response_body"] = body[:200] if body else ""
        results[svc] = entry
    return results


def collect_ingestion_status() -> dict[str, Any]:
    # Ingestion runs on port 8001 inside Docker (not exposed to host).
    # Query it via docker exec using curl inside the container.
    result: dict[str, Any] = {}
    rc, out, _ = _run(["docker", "exec", "codekg-ingestion",
                        "python3", "-c",
                        "import urllib.request, json; "
                        "r=urllib.request.urlopen('http://localhost:8001/scan/status',timeout=5); "
                        "print(r.read().decode())"],
                       timeout=10)
    if rc == 0 and out:
        try:
            data = json.loads(out)
            result["scanning"]    = data.get("scanning", False)
            result["active_scan"] = data
            result["reachable"]   = True
        except Exception:
            result["scanning"]  = False
            result["reachable"] = False
    else:
        result["scanning"]  = False
        result["reachable"] = (rc != -2)  # -2 = docker not found
    return result


def collect_log_analysis() -> dict[str, Any]:
    results: dict[str, Any] = {}
    error_patterns  = re.compile(r'"level":\s*"(ERROR|CRITICAL)"', re.IGNORECASE)
    warning_pattern = re.compile(r'"level":\s*"WARNING"', re.IGNORECASE)
    watcher_loop    = re.compile(r"No indexed commit found")
    scan_complete   = re.compile(r"Full scan complete")
    exception_pat   = re.compile(r"Traceback|Exception in ASGI|NoSuchPathError|ClientError")

    for svc_name, cfg in SERVICES.items():
        container = cfg["container"]
        rc, out, _ = _run(["docker", "logs", container, "--tail", "500",
                            "--timestamps"], timeout=20)
        if rc != 0:
            results[svc_name] = {"error": "could not read logs"}
            continue

        lines = out.splitlines()
        errors   = [l for l in lines if error_patterns.search(l)]
        warnings = [l for l in lines if warning_pattern.search(l)]
        excepts  = [l for l in lines if exception_pat.search(l)]

        entry: dict[str, Any] = {
            "total_lines_sampled": len(lines),
            "error_count":    len(errors),
            "warning_count":  len(warnings),
            "exception_count": len(excepts),
            "recent_errors":  [l[-200:] for l in errors[-5:]],
            "recent_exceptions": [l[-200:] for l in excepts[-3:]],
        }

        # Watcher-specific: detect loop storm
        if svc_name == "watcher":
            loop_lines = [l for l in lines if watcher_loop.search(l)]
            complete_lines = [l for l in lines if scan_complete.search(l)]
            entry["watcher_loop_trigger_count"] = len(loop_lines)
            entry["scan_complete_count"] = len(complete_lines)
            entry["watcher_loop_storm"] = (
                len(loop_lines) >= THRESHOLDS["watcher_loop_warn"]
                and len(complete_lines) == 0
            )

        results[svc_name] = entry

    return results


def collect_disk_and_volumes() -> dict[str, Any]:
    results: dict[str, Any] = {}

    # Host disk
    rc, out, _ = _run(["df", "-h", str(PROJECT_ROOT)])
    if rc == 0 and out:
        lines = out.splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            results["host_disk"] = {
                "filesystem": parts[0] if parts else "?",
                "size":  parts[1] if len(parts) > 1 else "?",
                "used":  parts[2] if len(parts) > 2 else "?",
                "avail": parts[3] if len(parts) > 3 else "?",
                "use_pct": parts[4] if len(parts) > 4 else "?",
            }

    # Docker volume sizes
    for vol in ["neo4j_data", "neo4j_logs"]:
        rc2, out2, _ = _run(["docker", "run", "--rm", "-v",
                              f"codekg_{vol}:/vol", "alpine",
                              "sh", "-c", "du -sh /vol 2>/dev/null | cut -f1"],
                             timeout=15)
        if rc2 == 0:
            results[f"volume_{vol}"] = out2.strip()

    # repos/ directory
    repos_path = PROJECT_ROOT / "repos"
    if repos_path.exists():
        rc3, out3, _ = _run(["du", "-sh", str(repos_path)])
        if rc3 == 0:
            results["repos_dir"] = out3.split()[0]

    # MCP audit DB size
    mcp_db = repos_path / "mcp_audit.db"
    if mcp_db.exists():
        results["mcp_audit_db_mb"] = round(mcp_db.stat().st_size / 1048576, 2)
    llm_db = repos_path / "llm_audit.db"
    if llm_db.exists():
        results["llm_audit_db_mb"] = round(llm_db.stat().st_size / 1048576, 2)

    return results


def collect_repos_registry() -> dict[str, Any]:
    registry_path = PROJECT_ROOT / "repos" / "repos.json"
    if not registry_path.exists():
        return {"error": "repos.json not found"}
    try:
        registry = json.loads(registry_path.read_text())
        result = {"count": len(registry), "repos": []}
        for repo_id, path in registry.items():
            # Check path exists from host perspective
            host_home = _load_env().get("HOME_MOUNT", "")
            local_path = path
            if path.startswith("/host-home") and host_home:
                local_path = host_home + path[len("/host-home"):]
            exists = Path(local_path).exists()
            result["repos"].append({
                "repo_id": repo_id,
                "container_path": path,
                "host_path": local_path,
                "host_path_exists": exists,
            })
        return result
    except Exception as e:
        return {"error": str(e)}


# ── Scoring / findings ────────────────────────────────────────────────────────

def _severity(level: str) -> str:
    return {"ok": "✅", "warn": "⚠️ ", "error": "🔴", "info": "ℹ️ "}.get(level, "  ")


def generate_findings(
    containers: dict,
    neo4j: dict,
    services: dict,
    ingestion: dict,
    logs: dict,
    disk: dict,
    repos: dict,
) -> list[dict]:
    findings: list[dict] = []

    def add(level: str, component: str, title: str, detail: str = ""):
        findings.append({"level": level, "component": component,
                         "title": title, "detail": detail})

    # ── Container health ──────────────────────────────────────────────────────
    for name, info in containers.items():
        if not info.get("running"):
            add("error", name, "Container is DOWN",
                f"Status: {info.get('status_text', 'unknown')}")
            continue

        restarts = info.get("restarts", 0)
        if restarts >= THRESHOLDS["restart_crit"]:
            add("error", name, f"High restart count: {restarts}",
                "Container is crash-looping")
        elif restarts >= THRESHOLDS["restart_warn"]:
            add("warn", name, f"Elevated restarts: {restarts}")

        cpu = info.get("cpu_pct", 0.0)
        if cpu >= THRESHOLDS["cpu_crit_pct"]:
            add("error", name, f"CPU critical: {cpu:.1f}%",
                "May indicate a runaway query or infinite loop")
        elif cpu >= THRESHOLDS["cpu_warn_pct"]:
            add("warn", name, f"CPU elevated: {cpu:.1f}%")

        mem = info.get("mem_pct", 0.0)
        if mem >= THRESHOLDS["mem_crit_pct"]:
            add("error", name, f"Memory critical: {mem:.1f}%  ({info.get('mem_usage','')})")
        elif mem >= THRESHOLDS["mem_warn_pct"]:
            add("warn", name, f"Memory elevated: {mem:.1f}%  ({info.get('mem_usage','')})")

    # ── Service HTTP health ───────────────────────────────────────────────────
    for svc, info in services.items():
        if not info.get("endpoint_checked"):
            continue
        if not info.get("http_ok"):
            add("error", svc, f"HTTP health check failed (status {info.get('http_status',-1)})")

    # ── Neo4j internals ───────────────────────────────────────────────────────
    heap_pct = neo4j.get("heap_used_pct")
    if heap_pct is not None:
        if heap_pct >= THRESHOLDS["neo4j_heap_crit_pct"]:
            add("error", "neo4j", f"JVM heap critical: {heap_pct}%",
                f"{neo4j.get('heap_used_mb')}MB / {neo4j.get('heap_max_mb')}MB used")
        elif heap_pct >= THRESHOLDS["neo4j_heap_warn_pct"]:
            add("warn", "neo4j", f"JVM heap elevated: {heap_pct}%",
                f"{neo4j.get('heap_used_mb')}MB / {neo4j.get('heap_max_mb')}MB used")

    for tx in neo4j.get("transactions", []):
        # Skip the healthcheck query itself
        if "SHOW TRANSACTIONS" in (tx.get("query") or ""):
            continue
        elapsed = tx.get("elapsed_s", 0)
        if elapsed >= THRESHOLDS["tx_crit_secs"]:
            add("error", "neo4j",
                f"Long-running transaction: {elapsed:.0f}s ({tx['id']})",
                f"Query: {tx.get('query','?')[:100]}")
        elif elapsed >= THRESHOLDS["tx_warn_secs"]:
            add("warn", "neo4j",
                f"Slow transaction: {elapsed:.0f}s ({tx['id']})",
                f"Query: {tx.get('query','?')[:100]}")

    if neo4j.get("indexes_not_online"):
        for idx in neo4j["indexes_not_online"]:
            add("warn", "neo4j",
                f"Index not ONLINE: {idx.get('name')} state={idx.get('state')}")

    for repo in neo4j.get("repos", []):
        if not repo.get("last_commit"):
            add("warn", "neo4j",
                f"Repo '{repo.get('repo_id')}' has no last_commit",
                "Full scans will retrigger every poll interval until this is set")

    # ── Watcher loop storm ────────────────────────────────────────────────────
    wlog = logs.get("watcher", {})
    if wlog.get("watcher_loop_storm"):
        add("error", "watcher",
            f"Scan-trigger loop storm detected",
            f"{wlog['watcher_loop_trigger_count']} triggers, "
            f"{wlog['scan_complete_count']} completions in last 500 log lines. "
            "A scan is repeatedly failing before writing last_commit.")

    # ── Ingestion ─────────────────────────────────────────────────────────────
    if ingestion.get("reachable") is False:
        add("error", "ingestion", "Ingestion service not reachable inside Docker")
    elif ingestion.get("scanning"):
        add("info", "ingestion", "Scan currently in progress",
            str(ingestion.get("active_scan", {})))

    # ── Log errors ───────────────────────────────────────────────────────────
    for svc, info in logs.items():
        errs = info.get("error_count", 0)
        excpts = info.get("exception_count", 0)
        if errs >= THRESHOLDS["log_error_crit"] or excpts >= 3:
            add("error", svc,
                f"High error rate in logs: {errs} errors, {excpts} exceptions",
                "Recent: " + "; ".join(info.get("recent_errors", [])[-2:]))
        elif errs >= THRESHOLDS["log_error_warn"] or excpts >= 1:
            add("warn", svc,
                f"Errors in logs: {errs} errors, {excpts} exceptions",
                "Recent: " + "; ".join(info.get("recent_errors", [])[-1:]))

    # ── Repos registry ────────────────────────────────────────────────────────
    for repo in repos.get("repos", []):
        if not repo.get("host_path_exists"):
            add("warn", "repos",
                f"Repo path not found on host: {repo['repo_id']}",
                f"Expected at: {repo['host_path']}")

    return findings


# ── Report rendering ──────────────────────────────────────────────────────────

def render_text(
    ts: str,
    containers: dict,
    neo4j: dict,
    services: dict,
    ingestion: dict,
    logs: dict,
    disk: dict,
    repos: dict,
    findings: list[dict],
) -> str:
    lines: list[str] = []
    sep = "─" * 72

    def h1(t: str):
        lines.append(f"\n{'═' * 72}")
        lines.append(f"  {t}")
        lines.append(f"{'═' * 72}")

    def h2(t: str):
        lines.append(f"\n{sep}")
        lines.append(f"  {t}")
        lines.append(sep)

    def row(label: str, value: str, width: int = 30):
        lines.append(f"  {label:<{width}} {value}")

    # ── Header ──
    h1(f"CodeKG Health Report  ·  {ts}")
    lines.append(f"  Generated: {ts}")
    lines.append(f"  Project:   {PROJECT_ROOT}")

    # ── Findings summary ──
    h2("FINDINGS SUMMARY")
    errors   = [f for f in findings if f["level"] == "error"]
    warnings = [f for f in findings if f["level"] == "warn"]
    infos    = [f for f in findings if f["level"] == "info"]

    if not findings:
        lines.append("  ✅  No issues detected — all systems nominal.")
    else:
        lines.append(f"  🔴  Errors:   {len(errors)}")
        lines.append(f"  ⚠️   Warnings: {len(warnings)}")
        lines.append(f"  ℹ️   Info:     {len(infos)}")
        lines.append("")
        for f in findings:
            icon = _severity(f["level"])
            lines.append(f"  {icon}  [{f['component']}]  {f['title']}")
            if f.get("detail"):
                lines.append(f"       ↳ {f['detail'][:140]}")

    # ── Container status ──
    h2("CONTAINER STATUS")
    lines.append(f"  {'Container':<28} {'State':<10} {'CPU%':>6} {'Mem%':>6} {'Mem Usage':<22} {'Restarts':>8}")
    lines.append(f"  {'-'*28} {'-'*10} {'-'*6} {'-'*6} {'-'*22} {'-'*8}")
    for name, info in sorted(containers.items()):
        state  = "UP" if info.get("running") else "DOWN"
        cpu    = f"{info.get('cpu_pct', 0):.1f}" if "cpu_pct" in info else "—"
        mem    = f"{info.get('mem_pct', 0):.1f}" if "mem_pct" in info else "—"
        mem_u  = info.get("mem_usage", "—")
        restarts = str(info.get("restarts", "—"))
        lines.append(f"  {name:<28} {state:<10} {cpu:>6} {mem:>6} {mem_u:<22} {restarts:>8}")

    # ── Neo4j ──
    h2("NEO4J DATABASE")
    row("HTTP reachable:", "Yes" if neo4j.get("http_ok") else "NO ← CHECK THIS")
    if "heap_used_mb" in neo4j:
        row("JVM heap:",
            f"{neo4j['heap_used_mb']}MB / {neo4j['heap_max_mb']}MB "
            f"({neo4j.get('heap_used_pct', '?')}%)")
    counts = neo4j.get("node_counts", {})
    for label, n in sorted(counts.items()):
        row(f"  {label} nodes:", f"{n:,}")
    lines.append("")
    lines.append("  Active transactions:")
    txns = [t for t in neo4j.get("transactions", [])
            if "SHOW TRANSACTIONS" not in (t.get("query") or "")]
    if not txns:
        lines.append("    (none beyond this query)")
    for t in txns:
        lines.append(f"    [{t['id']}] {t['elapsed_s']:.1f}s  {t['status']}")
        lines.append(f"      {t.get('query','')[:100]}")
    lines.append("")
    lines.append("  Repos in KG:")
    for r in neo4j.get("repos", []):
        commit = (r.get("last_commit") or "NULL — WILL LOOP!")[:16]
        lines.append(f"    {r.get('repo_id','?'):<24} last_commit: {commit}")
    if neo4j.get("indexes_not_online"):
        lines.append("")
        lines.append("  ⚠️  Non-ONLINE indexes:")
        for idx in neo4j["indexes_not_online"]:
            lines.append(f"    {idx.get('name')} state={idx.get('state')}")

    # ── Service endpoints ──
    h2("SERVICE ENDPOINTS")
    for svc, info in sorted(services.items()):
        if not info.get("endpoint_checked"):
            lines.append(f"  {svc:<16} (no HTTP endpoint — process-only)")
            continue
        ok = "OK" if info.get("http_ok") else f"FAIL ({info.get('http_status',-1)})"
        lines.append(f"  {svc:<16} HTTP: {ok}")

    # ── Ingestion ──
    h2("INGESTION STATUS")
    row("Scan in progress:", str(ingestion.get("scanning", False)))
    if ingestion.get("scanning"):
        row("Active scan:", str(ingestion.get("active_scan", {})))

    # ── Log analysis ──
    h2("LOG ANALYSIS  (last 500 lines per service)")
    lines.append(f"  {'Service':<16} {'Errors':>7} {'Warnings':>9} {'Exceptions':>11}")
    lines.append(f"  {'-'*16} {'-'*7} {'-'*9} {'-'*11}")
    for svc, info in sorted(logs.items()):
        if "error" in info:
            lines.append(f"  {svc:<16} (log unavailable)")
            continue
        errs  = info.get("error_count", 0)
        warns = info.get("warning_count", 0)
        excps = info.get("exception_count", 0)
        lines.append(f"  {svc:<16} {errs:>7} {warns:>9} {excps:>11}")
    lines.append("")
    for svc, info in sorted(logs.items()):
        if info.get("recent_errors") or info.get("recent_exceptions"):
            lines.append(f"  Recent errors/exceptions in [{svc}]:")
            for e in (info.get("recent_errors", []) + info.get("recent_exceptions", []))[-3:]:
                lines.append(f"    {e[-180:]}")
            lines.append("")

    # Watcher detail
    wlog = logs.get("watcher", {})
    if "watcher_loop_trigger_count" in wlog:
        lines.append(f"  Watcher scan triggers (last 500 lines): {wlog['watcher_loop_trigger_count']}")
        lines.append(f"  Watcher scan completions:               {wlog['scan_complete_count']}")
        if wlog.get("watcher_loop_storm"):
            lines.append("  🔴 LOOP STORM DETECTED — see Findings section")

    # ── Disk ──
    h2("DISK & STORAGE")
    hd = disk.get("host_disk", {})
    if hd:
        row("Host disk (project root):",
            f"{hd.get('used','?')} / {hd.get('size','?')} ({hd.get('use_pct','?')} used)")
    for key in ["volume_neo4j_data", "volume_neo4j_logs", "repos_dir"]:
        if key in disk:
            label = key.replace("_", " ") + ":"
            row(label, str(disk[key]))
    for key in ["mcp_audit_db_mb", "llm_audit_db_mb"]:
        if key in disk:
            row(f"{key}:", f"{disk[key]} MB")

    # ── Repos registry ──
    h2("REPOS REGISTRY")
    row("Registered repos:", str(repos.get("count", "?")))
    for r in repos.get("repos", []):
        ok = "✅" if r.get("host_path_exists") else "🔴 PATH NOT FOUND"
        lines.append(f"  {ok}  {r['repo_id']:<24} {r['host_path']}")

    # ── Footer ──
    lines.append(f"\n{'═' * 72}")
    lines.append(f"  End of report  ·  {ts}")
    lines.append(f"{'═' * 72}\n")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CodeKG Health Inspector")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--out", metavar="FILE", help="Write report to file")
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"CodeKG Health Inspector  ·  collecting data...", file=sys.stderr)

    env = _load_env()

    print("  [1/7] Docker container status...",  file=sys.stderr)
    containers = collect_docker_overview()

    print("  [2/7] Neo4j internals...",          file=sys.stderr)
    neo4j = collect_neo4j_health(env)

    print("  [3/7] Service HTTP endpoints...",   file=sys.stderr)
    services = collect_service_health()

    print("  [4/7] Ingestion status...",         file=sys.stderr)
    ingestion = collect_ingestion_status()

    print("  [5/7] Log analysis...",             file=sys.stderr)
    logs = collect_log_analysis()

    print("  [6/7] Disk & volumes...",           file=sys.stderr)
    disk = collect_disk_and_volumes()

    print("  [7/7] Repos registry...",           file=sys.stderr)
    repos = collect_repos_registry()

    findings = generate_findings(containers, neo4j, services, ingestion, logs, disk, repos)

    if args.json:
        payload = {
            "generated_at": ts,
            "findings":     findings,
            "containers":   containers,
            "neo4j":        neo4j,
            "services":     services,
            "ingestion":    ingestion,
            "logs":         logs,
            "disk":         disk,
            "repos":        repos,
        }
        output = json.dumps(payload, indent=2, default=str)
    else:
        output = render_text(ts, containers, neo4j, services, ingestion, logs, disk, repos, findings)

    if args.out:
        Path(args.out).write_text(output)
        print(f"\nReport written to: {args.out}", file=sys.stderr)
    else:
        print(output)

    # Exit non-zero if any errors found
    errors = [f for f in findings if f["level"] == "error"]
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
