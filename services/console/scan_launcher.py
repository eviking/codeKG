"""
scan_launcher.py — launches ephemeral ingestion scan containers via Docker SDK.

Each scan runs in its own container — parallel scans across repos are fine,
no locking needed, stuck jobs are killed with cancel_scan().

After each container exits a background thread captures the logs and exit code
and writes them to scan_log.db so failures are never lost.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import docker as _docker_sdk

from shared.config import cfg
from shared.codekg_logging.codekg_logger import get_logger

log = get_logger(__name__, service="console")

INGESTION_IMAGE = cfg.ingestion.ingestion_image
NEO4J_URI       = cfg.neo4j.uri
NEO4J_USER      = cfg.neo4j.user
NEO4J_PASSWORD  = cfg.neo4j.password
HOST_REPOS_PATH = cfg.paths.host_repos_path
REPOS_PATH      = cfg.paths.repos_path
HOME_MOUNT      = cfg.paths.home_mount
DOCKER_NETWORK  = cfg.services.docker_network

_SCAN_LOG_DB = Path(cfg.paths.repos_path) / "scan_log.db"
_db_lock = threading.Lock()


def _init_db():
    with _db_lock:
        con = sqlite3.connect(str(_SCAN_LOG_DB))
        con.execute("""
            CREATE TABLE IF NOT EXISTS scan_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id      TEXT NOT NULL,
                scan_type    TEXT NOT NULL,
                started_at   TEXT NOT NULL,
                finished_at  TEXT,
                exit_code    INTEGER,
                status       TEXT NOT NULL DEFAULT 'running',
                logs         TEXT
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_sl_repo ON scan_log(repo_id)")
        con.commit()
        con.close()


def _log_start(repo_id: str, scan_type: str) -> int:
    with _db_lock:
        con = sqlite3.connect(str(_SCAN_LOG_DB))
        cur = con.execute(
            "INSERT INTO scan_log (repo_id, scan_type, started_at, status) VALUES (?,?,?,?)",
            (repo_id, scan_type, datetime.now(timezone.utc).isoformat(), "running"),
        )
        row_id = cur.lastrowid
        con.commit()
        con.close()
    return row_id


def _log_finish(row_id: int, exit_code: int, logs: str):
    status = "ok" if exit_code == 0 else "error"
    with _db_lock:
        con = sqlite3.connect(str(_SCAN_LOG_DB))
        con.execute(
            "UPDATE scan_log SET finished_at=?, exit_code=?, status=?, logs=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), exit_code, status, logs, row_id),
        )
        con.commit()
        con.close()


def _watch_container(container, repo_id: str, row_id: int):
    """Background thread: wait for container to exit, capture logs, update DB."""
    try:
        exit_code = container.wait()["StatusCode"]
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
        _log_finish(row_id, exit_code, logs)
        if exit_code != 0:
            log.error("Scan container failed", repo_id=repo_id, exit_code=exit_code,
                      tail=logs[-500:] if logs else "")
        else:
            log.info("Scan container finished", repo_id=repo_id, exit_code=exit_code)
    except Exception as exc:
        log.error("Error watching scan container", repo_id=repo_id, error=str(exc))
        _log_finish(row_id, -1, str(exc))
    finally:
        try:
            container.remove(force=True)
        except Exception:  # Docker SDK can raise APIError, NotFound, etc. — ignore cleanup failures
            pass


def launch_scan(
    repo_id: str,
    repo_path: str,
    scan_type: Literal["full", "incremental"] = "full",
    from_commit: str = "",
    to_commit: str = "",
) -> str:
    """Launch an ephemeral ingestion container. Returns the container ID."""
    _init_db()
    client = _docker_sdk.from_env()

    env = {
        "NEO4J_URI":      NEO4J_URI,
        "NEO4J_USER":     NEO4J_USER,
        "NEO4J_PASSWORD": NEO4J_PASSWORD,
        "REPOS_PATH":     "/repos",
        "SCAN_REPO_ID":   repo_id,
        "SCAN_REPO_PATH": repo_path,
        "SCAN_TYPE":      scan_type,
    }
    if scan_type == "incremental":
        env["SCAN_FROM_COMMIT"] = from_commit
        env["SCAN_TO_COMMIT"]   = to_commit

    host_repos = HOST_REPOS_PATH or REPOS_PATH
    volumes = {host_repos: {"bind": "/repos", "mode": "rw"}}
    if HOME_MOUNT:
        volumes[HOME_MOUNT] = {"bind": "/host-home", "mode": "ro"}

    # Remove any leftover container with the same name (stopped/exited from a previous run).
    # This happens when the console restarted mid-scan or the watcher thread crashed.
    container_name = f"codekg-scan-{repo_id.lower().replace(' ', '-')}"
    try:
        stale = client.containers.get(container_name)
        if stale.status != "running":
            stale.remove(force=True)
            log.info("Removed stale scan container", name=container_name, status=stale.status)
        else:
            raise RuntimeError(
                f"Scan for {repo_id!r} is already running (container {container_name})"
            )
    except _docker_sdk.errors.NotFound:
        pass  # no leftover container — proceed normally

    row_id = _log_start(repo_id, scan_type)

    container = client.containers.run(
        INGESTION_IMAGE,
        command=["python", "run_scan.py"],
        detach=True,
        remove=False,     # we remove it ourselves after capturing logs
        environment=env,
        volumes=volumes,
        network=DOCKER_NETWORK,
        name=container_name,
        labels={
            "codekg.scan":      "true",
            "codekg.repo_id":   repo_id,
            "codekg.scan_type": scan_type,
        },
    )
    log.info("Scan container launched", repo_id=repo_id,
             container_id=container.short_id, type=scan_type)

    threading.Thread(
        target=_watch_container, args=(container, repo_id, row_id), daemon=True
    ).start()

    return container.id


def list_active_scans() -> list[dict]:
    """Return currently running scan containers."""
    try:
        client = _docker_sdk.from_env()
        containers = client.containers.list(filters={"label": "codekg.scan=true"})
        return [
            {
                "container_id": c.short_id,
                "repo_id":      c.labels.get("codekg.repo_id", "unknown"),
                "scan_type":    c.labels.get("codekg.scan_type", "unknown"),
                "status":       c.status,
                "name":         c.name,
            }
            for c in containers
        ]
    except Exception as e:
        log.warning("Failed to list active scan containers", exc=e)
        return []


def recent_scan_logs(limit: int = 20) -> list[dict]:
    """Return recent scan log entries from the DB."""
    try:
        _init_db()
        con = sqlite3.connect(str(_SCAN_LOG_DB))
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, repo_id, scan_type, started_at, finished_at, exit_code, status, logs "
            "FROM scan_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        con.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.warning("Failed to read recent scan logs from DB", exc=e)
        return []


def get_scan_logs(repo_id: str) -> str | None:
    """Return live stdout+stderr of the running scan container, or None if not running."""
    try:
        client = _docker_sdk.from_env()
        containers = client.containers.list(filters={"label": f"codekg.repo_id={repo_id}"})
        if not containers:
            return None
        c = containers[0]
        return c.logs(stdout=True, stderr=True, tail=2000).decode("utf-8", errors="replace")
    except Exception as exc:
        log.warning("Failed to fetch scan logs", repo_id=repo_id, error=str(exc))
        return None


def cancel_scan(repo_id: str) -> bool:
    """Stop the scan container for the given repo_id."""
    try:
        client = _docker_sdk.from_env()
        containers = client.containers.list(filters={"label": f"codekg.repo_id={repo_id}"})
        for c in containers:
            c.stop(timeout=5)
            log.info("Scan container stopped", repo_id=repo_id, container_id=c.short_id)
        return bool(containers)
    except Exception as exc:
        log.error("Failed to stop scan container", repo_id=repo_id, error=str(exc))
        return False
