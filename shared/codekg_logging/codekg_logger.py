"""
CodeKG centralized structured logging.

Usage in any service:
    from shared.codekg_logging.codekg_logger import get_logger
    log = get_logger(__name__, service="ingestion")

    log.info("Scan started", repo_id="org/my-svc", files=1200)
    log.timing("parse_file", elapsed_ms=12.4, file="Foo.java")
    log.error("Parse failed", file="Bar.java", exc=e)

Output: one JSON line per event to stdout (captured by Docker).
The `codekg logs` ops command pretty-prints these in color.

JSON schema:
{
  "ts":      "2026-05-28T14:32:00.123Z",   # ISO-8601 UTC with ms
  "level":   "INFO",                         # DEBUG / INFO / WARNING / ERROR / CRITICAL / TIMING
  "service": "ingestion",                    # docker service name
  "logger":  "ingestion_engine",             # python logger name (module)
  "msg":     "Scan started",                 # human message
  "repo_id": "org/my-svc",                   # optional context
  ...                                        # any extra kwargs passed to the log call
}
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Optional


# ------------------------------------------------------------------
# Custom TIMING level (between DEBUG and INFO)
# ------------------------------------------------------------------
TIMING = 15
logging.addLevelName(TIMING, "TIMING")


# ------------------------------------------------------------------
# JSON formatter — one line per record, machine-readable
# ------------------------------------------------------------------

class JSONFormatter(logging.Formatter):
    """Formats log records as structured JSON. Watch out for field naming and serialization here, because external log consumers may parse these records automatically."""


    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.") + f"{int(record.msecs):03d}Z"

        payload: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Extra fields attached by CodeKGLogger.info(..., repo_id=...) etc.
        for key, val in record.__dict__.items():
            if key.startswith("_ckg_"):
                payload[key[5:]] = val

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.exc_text:
            payload["exc_text"] = record.exc_text

        return json.dumps(payload, default=str)


# ------------------------------------------------------------------
# CodeKGLogger — wraps standard Logger with structured keyword args
# ------------------------------------------------------------------

class CodeKGLogger:
    """
    Thin wrapper around logging.Logger that accepts extra keyword
    arguments on every call and serializes them as JSON fields.

        log.info("Scan started", repo_id="org/svc", files=1200)
        log.timing("parse_file", elapsed_ms=12.4, file="Foo.java")
        log.error("Write failed", repo_id="org/svc", exc=e)
    """

    def __init__(self, name: str, service: str):
        self._log = logging.getLogger(name)
        self._service = service

    def _emit(self, level: int, msg: str, **kwargs):
        if not self._log.isEnabledFor(level):
            return
        record = self._log.makeRecord(
            self._log.name, level, "(unknown)", 0, msg, (), None,
        )
        for k, v in kwargs.items():
            if isinstance(v, Exception):
                record.exc_info = (type(v), v, v.__traceback__)
                v = str(v)
            setattr(record, f"_ckg_{k}", v)
        self._log.handle(record)

    def debug(self, msg: str, **kwargs):    self._emit(logging.DEBUG, msg, **kwargs)
    def info(self, msg: str, **kwargs):     self._emit(logging.INFO, msg, **kwargs)
    def warning(self, msg: str, **kwargs):  self._emit(logging.WARNING, msg, **kwargs)
    def error(self, msg: str, **kwargs):    self._emit(logging.ERROR, msg, **kwargs)
    def critical(self, msg: str, **kwargs): self._emit(logging.CRITICAL, msg, **kwargs)
    def timing(self, msg: str, **kwargs):   self._emit(TIMING, msg, **kwargs)

    @contextmanager
    def timed(self, operation: str, **ctx):
        """Context manager that emits a TIMING record with elapsed_ms."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            self.timing(operation, elapsed_ms=elapsed_ms, **ctx)


# ------------------------------------------------------------------
# Factory + bootstrap
# ------------------------------------------------------------------

_SERVICE = os.environ.get("CODEKG_SERVICE", "unknown")
_bootstrapped = False


def _bootstrap(service: str) -> None:
    global _bootstrapped, _SERVICE
    if _bootstrapped:
        return
    _SERVICE = service

    log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter(service))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Quieten noisy third-party loggers
    for noisy in ("neo4j", "httpx", "httpcore", "uvicorn.access", "git"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # neo4j.notifications fires WARNING for every missing property during scans — suppress
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

    _bootstrapped = True


def get_logger(name: str, service: Optional[str] = None) -> CodeKGLogger:
    """
    Returns a CodeKGLogger bound to the given logger name.
    Call once per module at module level:
        log = get_logger(__name__, service="ingestion")
    """
    svc = service or _SERVICE or os.environ.get("CODEKG_SERVICE", "unknown")
    _bootstrap(svc)
    return CodeKGLogger(name, svc)
