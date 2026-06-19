"""Persistent store for per-commit impact analyses."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from shared.config import cfg

_DB_PATH = Path(cfg.paths.repos_path) / "commit_impact.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS commit_analyses (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id       TEXT    NOT NULL,
                commit_sha    TEXT    NOT NULL,
                parent_sha    TEXT,
                committed_at  TEXT,
                author        TEXT,
                message       TEXT,
                changed_files TEXT,
                impact_json   TEXT    NOT NULL,
                risk_score    REAL    NOT NULL DEFAULT 0.0,
                total_affected INTEGER NOT NULL DEFAULT 0,
                security_score REAL   NOT NULL DEFAULT 0.0,
                availability_score REAL NOT NULL DEFAULT 0.0,
                performance_score  REAL NOT NULL DEFAULT 0.0,
                observability_score REAL NOT NULL DEFAULT 0.0,
                ops_score      REAL   NOT NULL DEFAULT 0.0,
                deps_score     REAL   NOT NULL DEFAULT 0.0,
                created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        c.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_commit
            ON commit_analyses(repo_id, commit_sha)
        """)


def upsert(
    repo_id: str,
    commit_sha: str,
    parent_sha: str | None,
    committed_at: str | None,
    author: str | None,
    message: str | None,
    changed_files: list[str],
    impact: dict,
    scores: dict,
) -> None:
    with _conn() as c:
        c.execute("""
            INSERT INTO commit_analyses
              (repo_id, commit_sha, parent_sha, committed_at, author, message,
               changed_files, impact_json, risk_score, total_affected,
               security_score, availability_score, performance_score,
               observability_score, ops_score, deps_score)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(repo_id, commit_sha) DO UPDATE SET
              impact_json        = excluded.impact_json,
              risk_score         = excluded.risk_score,
              total_affected     = excluded.total_affected,
              security_score     = excluded.security_score,
              availability_score = excluded.availability_score,
              performance_score  = excluded.performance_score,
              observability_score = excluded.observability_score,
              ops_score          = excluded.ops_score,
              deps_score         = excluded.deps_score,
              created_at         = excluded.created_at
        """, (
            repo_id, commit_sha, parent_sha, committed_at, author, message,
            json.dumps(changed_files), json.dumps(impact),
            scores.get("risk_score", 0.0),
            scores.get("total_affected", 0),
            scores.get("security_score", 0.0),
            scores.get("availability_score", 0.0),
            scores.get("performance_score", 0.0),
            scores.get("observability_score", 0.0),
            scores.get("ops_score", 0.0),
            scores.get("deps_score", 0.0),
        ))


def list_analyses(repo_id: str | None = None, limit: int = 50) -> list[dict]:
    with _conn() as c:
        if repo_id:
            rows = c.execute("""
                SELECT id, repo_id, commit_sha, parent_sha, committed_at, author,
                       message, changed_files, risk_score, total_affected,
                       security_score, availability_score, performance_score,
                       observability_score, ops_score, deps_score, created_at
                FROM commit_analyses
                WHERE repo_id = ?
                ORDER BY created_at DESC LIMIT ?
            """, (repo_id, limit)).fetchall()
        else:
            rows = c.execute("""
                SELECT id, repo_id, commit_sha, parent_sha, committed_at, author,
                       message, changed_files, risk_score, total_affected,
                       security_score, availability_score, performance_score,
                       observability_score, ops_score, deps_score, created_at
                FROM commit_analyses
                ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_analysis(repo_id: str, commit_sha: str) -> dict | None:
    with _conn() as c:
        row = c.execute("""
            SELECT * FROM commit_analyses
            WHERE repo_id = ? AND commit_sha = ?
        """, (repo_id, commit_sha)).fetchone()
    if not row:
        return None
    d = _row_to_dict(row)
    d["impact"] = json.loads(row["impact_json"])
    d["changed_files"] = json.loads(row["changed_files"] or "[]")
    return d


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if "changed_files" in d and isinstance(d["changed_files"], str):
        try:
            d["changed_files"] = json.loads(d["changed_files"])
        except Exception:
            d["changed_files"] = []
    d.pop("impact_json", None)
    return d
