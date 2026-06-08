"""
Agent Index Store — single source of truth.
SQLite-backed persistence for generated .codekg/ files.

Both services/api and services/console import from here.
Do not create per-service copies of this module.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from shared.config import cfg

AGENT_INDEX_DB = cfg.agent_index.db_path
_lock = threading.Lock()

_VALID_TABLES = frozenset({"agent_index_files", "agent_index_module_files"})


def _validate_table(table: str) -> None:
    if table not in _VALID_TABLES:
        raise ValueError(f"Invalid table name: {table!r}")


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path(), check_same_thread=False, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def _db_path() -> str:
    """Resolve the current SQLite path, allowing tests to override it via env."""
    return os.environ.get("AGENT_INDEX_DB", AGENT_INDEX_DB)


def init_db() -> None:
    Path(_db_path()).parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        con = _con()
        con.execute("""
            CREATE TABLE IF NOT EXISTS agent_index_files (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id          TEXT NOT NULL,
                file_key         TEXT NOT NULL,
                directory        TEXT NOT NULL DEFAULT '',
                filename         TEXT NOT NULL,
                description      TEXT,
                content          TEXT,
                manual_additions TEXT,
                status           TEXT NOT NULL DEFAULT 'current',
                trigger          TEXT,
                generated_at     TEXT,
                published_at     TEXT,
                published_sha    TEXT,
                hidden           INTEGER NOT NULL DEFAULT 0,
                UNIQUE(repo_id, file_key)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS agent_index_module_files (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id          TEXT NOT NULL,
                file_key         TEXT NOT NULL,
                directory        TEXT NOT NULL,
                filename         TEXT NOT NULL,
                description      TEXT,
                content          TEXT,
                manual_additions TEXT,
                status           TEXT NOT NULL DEFAULT 'current',
                trigger          TEXT,
                generated_at     TEXT,
                published_at     TEXT,
                published_sha    TEXT,
                hidden           INTEGER NOT NULL DEFAULT 0,
                UNIQUE(repo_id, file_key)
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_aif_repo ON agent_index_files(repo_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_aimf_repo ON agent_index_module_files(repo_id)")
        con.execute("PRAGMA journal_mode=WAL")
        # migrate existing DBs that predate added columns
        existing = {row[1] for row in con.execute("PRAGMA table_info(agent_index_module_files)")}
        if "trigger" not in existing:
            con.execute("ALTER TABLE agent_index_module_files ADD COLUMN trigger TEXT")
        if "published_sha" not in existing:
            con.execute("ALTER TABLE agent_index_module_files ADD COLUMN published_sha TEXT")
        con.commit()
        con.close()


def upsert_file(repo_id: str, file_key: str, directory: str, filename: str,
                description: str, content: str, trigger: str,
                table: str = "agent_index_files") -> None:
    _validate_table(table)
    ts = datetime.now(timezone.utc).isoformat()
    with _lock:
        con = _con()
        # Determine new status: if already published and content changed → stale
        existing = con.execute(
            f"SELECT content, published_at FROM {table} WHERE repo_id=? AND file_key=?",
            (repo_id, file_key)
        ).fetchone()
        if existing and existing["published_at"] and existing["content"] != content:
            new_status = "stale"
        else:
            new_status = "current"
        con.execute(f"""
            INSERT INTO {table}
              (repo_id, file_key, directory, filename, description, content,
               status, trigger, generated_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(repo_id, file_key) DO UPDATE SET
              content      = excluded.content,
              description  = excluded.description,
              status       = excluded.status,
              generated_at = excluded.generated_at
        """, (repo_id, file_key, directory, filename, description, content, new_status, trigger, ts))
        con.commit()
        con.close()


def get_file(repo_id: str, file_key: str, table: str = "agent_index_files") -> dict | None:
    _validate_table(table)
    con = _con()
    row = con.execute(
        f"SELECT * FROM {table} WHERE repo_id=? AND file_key=?",
        (repo_id, file_key)
    ).fetchone()
    con.close()
    return dict(row) if row else None


def list_files(repo_id: str) -> list[dict]:
    con = _con()
    rows = con.execute(
        "SELECT * FROM agent_index_files WHERE repo_id=? ORDER BY directory, filename",
        (repo_id,)
    ).fetchall()
    module_rows = con.execute(
        "SELECT * FROM agent_index_module_files WHERE repo_id=? ORDER BY directory, filename",
        (repo_id,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows] + [dict(r) for r in module_rows]


def update_manual_additions(repo_id: str, file_key: str, text: str,
                            table: str = "agent_index_files") -> bool:
    _validate_table(table)
    with _lock:
        con = _con()
        updated = con.execute(
            f"UPDATE {table} SET manual_additions=? WHERE repo_id=? AND file_key=?",
            (text, repo_id, file_key)
        ).rowcount
        con.commit()
        con.close()
    return updated > 0


def toggle_hidden(repo_id: str, file_key: str, hidden: bool,
                  table: str = "agent_index_files") -> bool:
    _validate_table(table)
    with _lock:
        con = _con()
        updated = con.execute(
            f"UPDATE {table} SET hidden=? WHERE repo_id=? AND file_key=?",
            (1 if hidden else 0, repo_id, file_key)
        ).rowcount
        con.commit()
        con.close()
    return updated > 0


def mark_published(repo_id: str, sha: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    with _lock:
        con = _con()
        con.execute(
            "UPDATE agent_index_files SET published_at=?, published_sha=?, status='current' WHERE repo_id=? AND hidden=0",
            (ts, sha, repo_id)
        )
        con.execute(
            "UPDATE agent_index_module_files SET published_at=?, published_sha=?, status='current' WHERE repo_id=? AND hidden=0",
            (ts, sha, repo_id)
        )
        con.commit()
        con.close()


def mark_stale(repo_id: str, trigger: str) -> None:
    """Mark files with matching trigger as stale when their trigger fires."""
    with _lock:
        con = _con()
        for tbl in ("agent_index_files", "agent_index_module_files"):
            con.execute(
                f"""UPDATE {tbl} SET status='stale'
                    WHERE repo_id=? AND (trigger=? OR trigger='any_change')
                    AND hidden=0""",
                (repo_id, trigger)
            )
        con.commit()
        con.close()
