"""
Unit tests for services/api/llm_audit.py.

Coverage scope:
  - cost calculation for known and unknown models
  - direct row insertion via log_call_simple()
  - context-manager logging for successful and failing calls
  - aggregate_stats() excludes errored calls from totals

All tests use a temporary SQLite file and reset the module-level connection.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

_SVC_ROOT = str(Path(__file__).parent.parent)
_PROJECT_ROOT = str(Path(__file__).parent.parent.parent.parent)
for _path in (_PROJECT_ROOT, _SVC_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import llm_audit
from shared.llm import LLMResponse, LLMUsage


@pytest.fixture(autouse=True)
def fresh_audit_db(tmp_path):
    """Point llm_audit at a fresh file-backed SQLite database for each test."""
    db_path = tmp_path / "llm_audit.db"
    llm_audit._DB_PATH = db_path
    if llm_audit._conn is not None:
        llm_audit._conn.close()
    llm_audit._conn = None
    yield db_path
    if llm_audit._conn is not None:
        llm_audit._conn.close()
    llm_audit._conn = None


class TestComputeCost:
    """Exercises compute cost behavior in the llm audit test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_known_model_uses_pricing_table(self):
        cost = llm_audit.compute_cost(
            "claude-haiku-4-5",
            input_tokens=1_000_000,
            output_tokens=500_000,
            cache_read_tokens=500_000,
        )
        assert cost == 2.84

    def test_unknown_model_uses_default_pricing(self):
        cost = llm_audit.compute_cost("mystery-model", 1_000_000, 1_000_000, 1_000_000)
        assert cost == 18.3


class TestLogCallSimple:
    """Exercises log call simple behavior in the llm audit test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_inserts_row_and_truncates_large_text(self):
        row_id = llm_audit.log_call_simple(
            source="nl_query/answer",
            model="claude-sonnet-4-5",
            input_text="x" * 25_000,
            output_text="y" * 25_000,
            input_tokens=10,
            output_tokens=20,
            meta={"route": "/answer"},
        )
        rows = llm_audit.recent_calls(hours=0)
        assert row_id > 0
        assert len(rows) == 1
        assert rows[0]["source"] == "nl_query/answer"
        assert len(rows[0]["input_text"]) == 20_000
        assert len(rows[0]["output_text"]) == 20_000


class TestLogCallContext:
    """Exercises log call context behavior in the llm audit test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_success_path_records_unified_response(self):
        response = LLMResponse(
            text="hello",
            model="claude-sonnet-4-5",
            usage=LLMUsage(input_tokens=11, output_tokens=7, cache_read_tokens=3),
        )
        with llm_audit.log_call("answer", "claude-sonnet-4-5", "prompt") as entry:
            entry.record(response)

        row = llm_audit.recent_calls(hours=0)[0]
        assert row["source"] == "answer"
        assert row["output_text"] == "hello"
        assert row["input_tokens"] == 11
        assert row["output_tokens"] == 7
        assert row["cache_read_tokens"] == 3

    def test_exception_path_records_error_and_reraises(self):
        with pytest.raises(RuntimeError, match="boom"):
            with llm_audit.log_call("answer", "claude-sonnet-4-5", "prompt"):
                raise RuntimeError("boom")

        row = llm_audit.recent_calls(hours=0)[0]
        assert row["error"] == "boom"
        assert row["output_text"] is None

    def test_legacy_response_shape_is_supported(self):
        response = SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=5,
                output_tokens=2,
                cache_read_input_tokens=1,
                cache_creation_input_tokens=4,
            ),
            content=[SimpleNamespace(text="legacy payload")],
        )
        with llm_audit.log_call("legacy", "claude-haiku-4-5", "prompt") as entry:
            entry.record(response)

        row = llm_audit.recent_calls(hours=0)[0]
        assert row["output_text"] == "legacy payload"
        assert row["cache_read_tokens"] == 1
        assert row["cache_write_tokens"] == 4


class TestAggregateStats:
    """Exercises aggregate stats behavior in the llm audit test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_excludes_errors_from_totals(self):
        llm_audit.log_call_simple(
            source="ok",
            model="claude-haiku-4-5",
            input_tokens=10,
            output_tokens=20,
            elapsed_ms=30,
        )
        llm_audit.log_call_simple(
            source="err",
            model="claude-haiku-4-5",
            input_tokens=99,
            output_tokens=99,
            error="bad request",
        )

        stats = llm_audit.aggregate_stats(hours=0)
        assert stats["totals"]["calls"] == 1
        assert stats["totals"]["input_tokens"] == 10
        assert stats["totals"]["output_tokens"] == 20
        assert stats["by_model"][0]["calls"] == 1
