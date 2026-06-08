"""
llm_audit.py — lightweight SQLite audit log for every LLM API call.

Usage:
    from llm_audit import log_call, CallContext

    with log_call(ctx) as entry:
        response = client.messages.create(...)
        entry.record(response)

Or for fire-and-forget:
    log_call_simple(
        source="nl_query/cypher",
        model="claude-haiku-4-5",
        input_text=prompt,
        output_text=response_text,
        input_tokens=n,
        output_tokens=m,
        cache_read_tokens=k,
    )
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from shared.config import cfg
from typing import Any, Optional

# ── Pricing ($ per million tokens, as of 2026-05) ────────────────────────────
_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5":   {"input": 0.80,  "output": 4.00,  "cache_read": 0.08},
    "claude-haiku-3-5":   {"input": 0.80,  "output": 4.00,  "cache_read": 0.08},
    "claude-sonnet-4-5":  {"input": 3.00,  "output": 15.00, "cache_read": 0.30},
    "claude-sonnet-4":    {"input": 3.00,  "output": 15.00, "cache_read": 0.30},
    "claude-opus-4":      {"input": 15.00, "output": 75.00, "cache_read": 1.50},
    "claude-opus-4-5":    {"input": 15.00, "output": 75.00, "cache_read": 1.50},
}
_DEFAULT_PRICE = {"input": 3.00, "output": 15.00, "cache_read": 0.30}


def compute_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Return cost in USD."""
    p = _PRICING.get(model, _DEFAULT_PRICE)
    cost = (
        (input_tokens       / 1_000_000) * p["input"]  +
        (output_tokens      / 1_000_000) * p["output"] +
        (cache_read_tokens  / 1_000_000) * p.get("cache_read", 0)
    )
    return round(cost, 8)


# ── DB setup ─────────────────────────────────────────────────────────────────

_DB_PATH = Path(cfg.paths.llm_audit_db)
_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_calls (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ts              TEXT NOT NULL,
                source          TEXT NOT NULL,
                model           TEXT NOT NULL,
                input_tokens    INTEGER NOT NULL DEFAULT 0,
                output_tokens   INTEGER NOT NULL DEFAULT 0,
                cache_read_tokens  INTEGER NOT NULL DEFAULT 0,
                cache_write_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd        REAL NOT NULL DEFAULT 0,
                elapsed_ms      INTEGER,
                input_text      TEXT,
                output_text     TEXT,
                error           TEXT,
                meta            TEXT
            )
        """)
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON llm_calls(ts)")
        _conn.commit()
    return _conn


def _insert(row: dict) -> int:
    with _lock:
        conn = _get_conn()
        cur = conn.execute("""
            INSERT INTO llm_calls
                (ts, source, model, input_tokens, output_tokens,
                 cache_read_tokens, cache_write_tokens,
                 cost_usd, elapsed_ms, input_text, output_text, error, meta)
            VALUES
                (:ts, :source, :model, :input_tokens, :output_tokens,
                 :cache_read_tokens, :cache_write_tokens,
                 :cost_usd, :elapsed_ms, :input_text, :output_text, :error, :meta)
        """, row)
        conn.commit()
        return cur.lastrowid


# ── Public API ────────────────────────────────────────────────────────────────

def log_call_simple(
    source: str,
    model: str,
    input_text: str = "",
    output_text: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    elapsed_ms: Optional[int] = None,
    error: Optional[str] = None,
    meta: Optional[dict] = None,
) -> int:
    """Log a completed API call. Returns the row id."""
    cost = compute_cost(model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)
    return _insert({
        "ts":                  datetime.now(timezone.utc).isoformat(),
        "source":              source,
        "model":               model,
        "input_tokens":        input_tokens,
        "output_tokens":       output_tokens,
        "cache_read_tokens":   cache_read_tokens,
        "cache_write_tokens":  cache_write_tokens,
        "cost_usd":            cost,
        "elapsed_ms":          elapsed_ms,
        "input_text":          input_text[:20_000] if input_text else None,
        "output_text":         output_text[:20_000] if output_text else None,
        "error":               error,
        "meta":                json.dumps(meta) if meta else None,
    })


@dataclass
class _Entry:
    """Represents one stored LLM audit event. Watch out for field naming here, because audit pages and API responses read these entries back verbatim."""

    source: str
    model: str
    input_text: str
    _start: float = field(default_factory=time.perf_counter)
    _row_id: Optional[int] = None

    def record(self, response: Any, error: str = "") -> None:
        elapsed_ms = round((time.perf_counter() - self._start) * 1000)
        # Accept either a normalised LLMResponse (from shared.llm) or a raw
        # Anthropic SDK response (legacy call sites not yet migrated).
        try:
            from shared.llm import LLMResponse as _LR
            is_unified = isinstance(response, _LR)
        except ImportError:
            is_unified = False

        if is_unified:
            u = response.usage
            input_tokens       = u.input_tokens
            output_tokens      = u.output_tokens
            cache_read_tokens  = u.cache_read_tokens
            cache_write_tokens = 0
            output_text        = response.text
        else:
            usage = getattr(response, "usage", None)
            input_tokens       = getattr(usage, "input_tokens",                   0) if usage else 0
            output_tokens      = getattr(usage, "output_tokens",                  0) if usage else 0
            cache_read_tokens  = getattr(usage, "cache_read_input_tokens",        0) if usage else 0
            cache_write_tokens = getattr(usage, "cache_creation_input_tokens",    0) if usage else 0
            output_text = ""
            if response and hasattr(response, "content") and response.content:
                output_text = getattr(response.content[0], "text", "") or ""
        self._row_id = log_call_simple(
            source=self.source,
            model=self.model,
            input_text=self.input_text,
            output_text=output_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            elapsed_ms=elapsed_ms,
            error=error or None,
        )

    def record_error(self, exc: Exception) -> None:
        elapsed_ms = round((time.perf_counter() - self._start) * 1000)
        log_call_simple(
            source=self.source,
            model=self.model,
            input_text=self.input_text,
            elapsed_ms=elapsed_ms,
            error=str(exc),
        )


@contextmanager
def log_call(source: str, model: str, input_text: str = ""):
    """
    Context manager that yields an _Entry. Call entry.record(response) inside.

    with log_call("nl_query/answer", "claude-sonnet-4-5", prompt) as entry:
        resp = client.messages.create(...)
        entry.record(resp)
    """
    entry = _Entry(source=source, model=model, input_text=input_text)
    try:
        yield entry
    except Exception as exc:
        entry.record_error(exc)
        raise


# ── Query helpers for the UI ──────────────────────────────────────────────────

def _hours_cutoff(hours: int) -> str | None:
    if hours <= 0:
        return None
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def recent_calls(limit: int = 200, source_filter: str = "", hours: int = 24) -> list[dict]:
    conn = _get_conn()
    conditions, params = [], []
    cutoff = _hours_cutoff(hours)
    if cutoff:
        conditions.append("ts >= ?")
        params.append(cutoff)
    if source_filter:
        conditions.append("source LIKE ?")
        params.append(f"%{source_filter}%")
    q = "SELECT * FROM llm_calls"
    if conditions:
        q += " WHERE " + " AND ".join(conditions)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def aggregate_stats(hours: int = 24) -> dict:
    conn = _get_conn()
    cutoff = _hours_cutoff(hours)
    time_clause = "AND ts >= ?" if cutoff else ""
    time_params = [cutoff] if cutoff else []
    rows = conn.execute(f"""
        SELECT
            model,
            count(*)            AS calls,
            sum(input_tokens)   AS input_tokens,
            sum(output_tokens)  AS output_tokens,
            sum(cache_read_tokens) AS cache_read_tokens,
            sum(cost_usd)       AS cost_usd,
            avg(elapsed_ms)     AS avg_ms
        FROM llm_calls
        WHERE error IS NULL {time_clause}
        GROUP BY model
        ORDER BY cost_usd DESC
    """, time_params).fetchall()
    totals = conn.execute(f"""
        SELECT count(*) AS calls, sum(cost_usd) AS cost_usd,
               sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens
        FROM llm_calls WHERE error IS NULL {time_clause}
    """, time_params).fetchone()
    return {
        "by_model": [dict(r) for r in rows],
        "totals":   dict(totals) if totals else {},
    }
