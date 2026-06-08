#!/usr/bin/env python3
"""
CodeKG log pretty-printer.

Reads JSON log lines from stdin (piped from `docker compose logs -f`)
and renders them with color, alignment, and human-friendly formatting.

Usage:
    docker compose logs -f --no-log-prefix 2>&1 | python3 scripts/log_pretty.py
    docker compose logs -f 2>&1 | python3 scripts/log_pretty.py

Or via the ops script:
    ./codekg logs [service]
    ./codekg logs ingestion
"""
import json
import re
import sys
from datetime import datetime

# ANSI color codes
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"

BLACK   = "\033[30m"
RED     = "\033[31m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
BLUE    = "\033[34m"
MAGENTA = "\033[35m"
CYAN    = "\033[36m"
WHITE   = "\033[37m"

BRIGHT_RED     = "\033[91m"
BRIGHT_GREEN   = "\033[92m"
BRIGHT_YELLOW  = "\033[93m"
BRIGHT_BLUE    = "\033[94m"
BRIGHT_MAGENTA = "\033[95m"
BRIGHT_CYAN    = "\033[96m"
BRIGHT_WHITE   = "\033[97m"

BG_RED    = "\033[41m"
BG_YELLOW = "\033[43m"
BG_BLUE   = "\033[44m"

# Per-service colors (applied to service name badge)
SERVICE_COLORS = {
    "ingestion": BRIGHT_CYAN,
    "watcher":   BRIGHT_MAGENTA,
    "api":       BRIGHT_BLUE,
    "mcp":       BRIGHT_GREEN,
    "console":   BRIGHT_YELLOW,
    "neo4j":     "\033[38;5;208m",   # orange
    "unknown":   WHITE,
}

# Per-level formatting
LEVEL_STYLES = {
    "DEBUG":    (DIM + WHITE,        "·DBG"),
    "TIMING":   (CYAN,               "⏱ TMG"),
    "INFO":     (BRIGHT_GREEN,       " INF"),
    "WARNING":  (BRIGHT_YELLOW,      "⚠ WRN"),
    "ERROR":    (BRIGHT_RED,         "✖ ERR"),
    "CRITICAL": (BG_RED + BOLD,      "!! CRT"),
}

# Fields to suppress from the "extras" line (already shown in the header)
HEADER_FIELDS = {"ts", "level", "service", "logger", "msg"}


def _svc_color(service: str) -> str:
    return SERVICE_COLORS.get(service.lower(), WHITE)


def _format_ts(ts: str) -> str:
    try:
        # "2026-05-28T14:32:00.123Z"
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")
        return dt.strftime("%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"
    except Exception:
        return ts[-12:] if len(ts) > 12 else ts


def _format_extras(data: dict) -> str:
    extras = {k: v for k, v in data.items() if k not in HEADER_FIELDS and v is not None}
    if not extras:
        return ""
    parts = []
    # Special handling for well-known fields
    if "repo_id" in extras:
        parts.append(f"{BRIGHT_CYAN}repo={extras.pop('repo_id')}{RESET}")
    if "elapsed_ms" in extras:
        ms = extras.pop("elapsed_ms")
        color = BRIGHT_GREEN if ms < 100 else BRIGHT_YELLOW if ms < 1000 else BRIGHT_RED
        parts.append(f"{color}{ms}ms{RESET}")
    if "files" in extras:
        parts.append(f"{CYAN}files={extras.pop('files')}{RESET}")
    if "file" in extras:
        fname = str(extras.pop("file")).split("/")[-1]
        parts.append(f"{DIM}{fname}{RESET}")
    if "exc" in extras:
        exc_text = str(extras.pop("exc"))
        parts.append(f"\n  {BRIGHT_RED}{exc_text}{RESET}")
    # Remaining fields
    for k, v in extras.items():
        if k == "exc_text":
            continue
        parts.append(f"{DIM}{k}{RESET}={BRIGHT_WHITE}{v}{RESET}")
    return "  " + "  ".join(parts) if parts else ""


def render_json_line(data: dict) -> str:
    level    = data.get("level", "INFO").upper()
    service  = data.get("service", "unknown")
    logger   = data.get("logger", "")
    msg      = data.get("msg", "")
    ts       = data.get("ts", "")

    level_color, level_badge = LEVEL_STYLES.get(level, (WHITE, level[:3].upper()))
    svc_color = _svc_color(service)

    ts_str  = f"{DIM}{_format_ts(ts)}{RESET}"
    svc_str = f"{svc_color}{BOLD}{service:<10}{RESET}"
    lvl_str = f"{level_color}{level_badge}{RESET}"

    # Shorten logger name: ingestion_engine → engine, parser.java_parser → java_parser
    short_logger = logger.split(".")[-1] if "." in logger else logger
    log_str = f"{DIM}{short_logger:<20}{RESET}"

    extras = _format_extras(data)

    return f"{ts_str}  {svc_str}  {lvl_str}  {log_str}  {BRIGHT_WHITE}{msg}{RESET}{extras}"


def render_plain_line(line: str) -> str:
    """Fallback for non-JSON lines (e.g. Neo4j startup messages, Python tracebacks)."""
    line = line.rstrip()
    if not line:
        return ""
    # Docker prefix like "ingestion-1  | "
    m = re.match(r"^(\S+)-\d+\s+\|\s+(.*)", line)
    if m:
        service = m.group(1)
        rest = m.group(2)
        svc_color = _svc_color(service)
        return f"{DIM}{'':>14}{RESET}  {svc_color}{BOLD}{service:<10}{RESET}  {DIM}{'SYS':<7}{RESET}  {DIM}{rest}{RESET}"
    return f"{DIM}{line}{RESET}"


def main():
    # Print a header banner
    print(f"\n{BOLD}{BRIGHT_CYAN}━━━  CodeKG Log Stream  ━━━{RESET}  {DIM}(Ctrl-C to stop){RESET}\n")
    print(f"{DIM}{'TIME':>14}  {'SERVICE':<10}  {'LVL':>7}  {'LOGGER':<20}  MESSAGE{RESET}\n")

    try:
        for raw_line in sys.stdin:
            line = raw_line.rstrip("\n")
            if not line:
                continue

            # Strip docker compose prefix "service-1  | " if present
            m = re.match(r"^\S+-\d+\s+\|\s+(.*)", line)
            json_candidate = m.group(1) if m else line

            try:
                data = json.loads(json_candidate)
                if isinstance(data, dict) and "level" in data:
                    print(render_json_line(data))
                else:
                    print(render_plain_line(line))
            except (json.JSONDecodeError, ValueError):
                print(render_plain_line(line))

    except KeyboardInterrupt:
        print(f"\n{DIM}Log stream ended.{RESET}\n")


if __name__ == "__main__":
    main()
