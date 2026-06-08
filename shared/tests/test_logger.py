"""
Unit tests for shared/logging/codekg_logger.py.

Coverage scope:
  - get_logger() returns a CodeKGLogger instance
  - log.info() emits a JSON line to stdout with ts, level, msg keys
  - log.error() includes exc info when an exception is passed
  - log.timing() emits a record with level='TIMING'
  - Multiple calls produce separate JSON lines (not merged)
  - Each emitted line is parseable with json.loads

All tests run in pure Python — no external services, no Docker.
"""
from __future__ import annotations

import io
import json
import logging
import sys
from pathlib import Path

_SHARED_ROOT = str(Path(__file__).parent.parent.parent)
if _SHARED_ROOT not in sys.path:
    sys.path.insert(0, _SHARED_ROOT)



def _capture_log(fn, *, service: str = "test") -> list[dict]:
    """
    Run fn(log) with a fresh CodeKGLogger that writes to a StringIO buffer.
    Bypasses the root-logger handler setup so pytest capture doesn't interfere.
    """
    import shared.codekg_logging.codekg_logger as ckg

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(ckg.JSONFormatter(service))
    handler.setLevel(logging.DEBUG)

    # Create a dedicated logger name so we don't interfere with root
    logger_name = f"_test_{id(fn)}"
    raw_logger = logging.getLogger(logger_name)
    raw_logger.handlers = [handler]
    raw_logger.setLevel(logging.DEBUG)
    raw_logger.propagate = False

    # Patch CodeKGLogger to use this isolated logger
    log = ckg.CodeKGLogger(logger_name, service)
    fn(log)

    lines = [ln.strip() for ln in buf.getvalue().splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


class TestGetLogger:
    """Exercises get logger behavior in the logger test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_returns_logger_instance(self):
        """
        get_logger() must return a CodeKGLogger instance (not a raw logging.Logger).
        Callers rely on the structured .info(), .warning(), etc. interface.
        """
        import shared.codekg_logging.codekg_logger as ckg
        ckg._bootstrapped = False
        log = ckg.get_logger("test", service="test")
        assert isinstance(log, ckg.CodeKGLogger)
        ckg._bootstrapped = False


class TestInfoEmission:
    """Exercises info emission behavior in the logger test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_info_emits_valid_json_with_required_keys(self):
        """
        log.info() must emit exactly one JSON line containing ts, level, and msg keys.
        These are the contract for downstream log parsers and the `codekg logs` command.
        """
        records = _capture_log(lambda log: log.info("hello world"))
        assert len(records) == 1
        rec = records[0]
        assert "ts" in rec
        assert rec["level"] == "INFO"
        assert rec["msg"] == "hello world"

    def test_extra_kwargs_appear_as_fields(self):
        """
        Extra keyword arguments passed to log.info() must appear as top-level
        JSON fields (not nested). This is how repo_id, file, etc. are attached.
        """
        records = _capture_log(lambda log: log.info("scan started", repo_id="my-repo", files=42))
        assert len(records) == 1
        assert records[0].get("repo_id") == "my-repo"
        assert records[0].get("files") == 42


class TestErrorEmission:
    """Exercises error emission behavior in the logger test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_error_includes_exc_text(self):
        """
        log.error() called with exc=<exception> must include 'exc' or 'exc_text' in
        the JSON output so stack traces are captured in structured form.
        """
        def _emit(log):
            try:
                raise ValueError("boom")
            except ValueError as e:
                log.error("something failed", exc=e)

        records = _capture_log(_emit)
        assert len(records) == 1
        rec = records[0]
        assert rec["level"] == "ERROR"
        # Either exc or exc_text should be present
        assert "exc" in rec or "exc_text" in rec


class TestTimingEmission:
    """Exercises timing emission behavior in the logger test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_timing_emits_timing_level(self):
        """
        log.timing() must emit a record with level='TIMING'. This custom level
        sits between DEBUG and INFO and lets ops filter timing data separately.
        """
        records = _capture_log(lambda log: log.timing("parse_file", elapsed_ms=12.4))
        assert len(records) == 1
        assert records[0]["level"] == "TIMING"
        assert records[0]["msg"] == "parse_file"


class TestMultipleLines:
    """Exercises multiple lines behavior in the logger test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_multiple_calls_produce_separate_lines(self):
        """
        Three separate log calls must produce three separate JSON lines, not one
        merged blob. Log consumers rely on line-delimited JSON for streaming.
        """
        def _emit(log):
            log.info("line 1")
            log.info("line 2")
            log.info("line 3")

        records = _capture_log(_emit)
        assert len(records) == 3
        messages = [r["msg"] for r in records]
        assert messages == ["line 1", "line 2", "line 3"]


class TestJsonValidity:
    """Exercises json validity behavior in the logger test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_each_line_is_valid_json(self):
        """
        Each emitted log line must be independently parseable by json.loads.
        Malformed JSON would break log aggregation and the ops dashboard.
        """
        def _emit(log):
            log.info("alpha", key="value with spaces")
            log.warning("beta", count=99)
            log.timing("gamma", elapsed_ms=0.1)

        records = _capture_log(_emit)
        assert len(records) == 3
        # All parsed successfully (json.loads would have raised if invalid)
        for rec in records:
            assert isinstance(rec, dict)
