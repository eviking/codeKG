#!/usr/bin/env python3
"""
backfill_javadoc.py — Backfill c.javadoc for existing Class nodes in Neo4j.

Reads source files for Class nodes that have a file_path but no javadoc yet,
extracts the Javadoc comment (/** ... */) preceding the class/interface/enum
declaration, and writes it back to Neo4j.

This is a one-shot backfill; the ingestion pipeline now stores javadoc
automatically at parse time via java_parser._extract_javadoc().

Usage:
    python3 tools/backfill_javadoc.py --repo elasticsearch \
        --repo-root /path/to/elasticsearch
    python3 tools/backfill_javadoc.py --repo elasticsearch \
        --repo-root /path/to/elasticsearch --force   # re-extract even if set
    python3 tools/backfill_javadoc.py --stats
"""
from __future__ import annotations

# ── Bootstrap: ensure neo4j driver is available ──────────────────────────────
import sys, os

def _missing(*names):
    import importlib.util
    return [n for n in names if importlib.util.find_spec(n) is None]

if _missing("neo4j"):
    import subprocess, venv
    venv_dir = os.path.join(os.path.dirname(__file__), ".venv")
    if not os.path.isdir(venv_dir):
        venv.create(venv_dir, with_pip=True)
    pip = os.path.join(venv_dir, "bin", "pip")
    subprocess.check_call([pip, "install", "-q", "neo4j"])
    python = os.path.join(venv_dir, "bin", "python3")
    os.execv(python, [python] + sys.argv)

# ── Real imports ──────────────────────────────────────────────────────────────
import argparse
import logging
import re
import time
from pathlib import Path

from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# Neo4j defaults
# ---------------------------------------------------------------------------
NEO4J_URI  = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "codekg_dev")
BATCH_SIZE = 200

# ---------------------------------------------------------------------------
# Javadoc extractor (pure-regex, no Tree-sitter dependency)
# ---------------------------------------------------------------------------
# Matches /** ... */ block comment immediately before a type declaration line
# (with optional annotations and modifiers in between).
_JAVADOC_RE = re.compile(
    r"/\*\*(.*?)\*/\s*"          # /** ... */  (DOTALL)
    r"(?:@\w[\w.]*(?:\(.*?\))?\s*)*"  # optional annotations
    r"(?:public|protected|private|abstract|final|static|sealed|non-sealed|\s)*"
    r"(?:class|interface|enum|@interface)\s+(\w+)",
    re.DOTALL,
)

_STAR_STRIP_RE = re.compile(r"^\s*\*\s?", re.MULTILINE)


def _clean_javadoc(raw: str) -> str:
    """Strip /** */ delimiters and leading * from each line."""
    inner = raw.strip()
    if inner.startswith("/**"):
        inner = inner[3:]
    if inner.endswith("*/"):
        inner = inner[:-2]
    inner = _STAR_STRIP_RE.sub("", inner)
    lines = [l.strip() for l in inner.splitlines() if l.strip()]
    return " ".join(lines)


def extract_javadoc(source: str, class_name: str) -> str | None:
    """
    Extract the Javadoc for a specific class_name from Java source text.
    Returns the cleaned text or None.
    """
    for m in _JAVADOC_RE.finditer(source):
        if m.group(2) == class_name:
            return _clean_javadoc(m.group(1)) or None
    return None


# ---------------------------------------------------------------------------
# Neo4j helpers
# ---------------------------------------------------------------------------
def _run(session, cypher: str, **params):
    return [dict(r) for r in session.run(cypher, **params)]


def fetch_classes(driver, repo_id: str, force: bool, limit: int | None):
    where = ["c.file_path IS NOT NULL"]
    if repo_id:
        # case-insensitive match in case stored repo_id capitalisation differs
        where.append("toLower(c.repo_id) = toLower($repo_id)")
    # Note: we always fetch all and filter in Python to avoid Neo4j property-existence
    # warnings on c.javadoc when no node has that property yet.
    cypher = f"""
        MATCH (c:Class)
        WHERE {' AND '.join(where)}
        RETURN c.fqn AS fqn, c.name AS name, c.file_path AS file_path,
               c.repo_id AS repo_id,
               CASE WHEN c.javadoc IS NOT NULL THEN c.javadoc ELSE null END AS javadoc
        ORDER BY c.fqn
        {"LIMIT " + str(limit) if limit else ""}
    """
    with driver.session() as s:
        rows = _run(s, cypher, repo_id=repo_id)
    if not force:
        rows = [r for r in rows if not r.get("javadoc")]
    return rows


def write_batch(driver, rows: list[dict]):
    """Write javadoc for a batch of {fqn, javadoc} dicts."""
    with driver.session() as s:
        s.run("""
            UNWIND $rows AS row
            MATCH (c:Class {fqn: row.fqn})
            SET c.javadoc = row.javadoc
        """, rows=rows)


def print_stats(driver):
    with driver.session() as s:
        total = s.run("MATCH (c:Class) RETURN count(c) AS n").single()["n"]
        with_jd = s.run("MATCH (c:Class) WHERE c.javadoc IS NOT NULL RETURN count(c) AS n").single()["n"]
        with_fp = s.run("MATCH (c:Class) WHERE c.file_path IS NOT NULL RETURN count(c) AS n").single()["n"]
    print(f"Total classes : {total}")
    print(f"With file_path: {with_fp}")
    print(f"With javadoc  : {with_jd}  ({with_jd*100//total if total else 0}%)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Backfill c.javadoc on Class nodes")
    ap.add_argument("--repo",      default="", help="Repo ID filter (empty = all)")
    ap.add_argument("--repo-root", help="Root directory of the Java source tree")
    ap.add_argument("--strip-prefix", default="",
                    help="Remove this prefix from stored file_path before resolving "
                         "(e.g. /host-home to remap Docker paths)")
    ap.add_argument("--add-prefix", default=str(Path.home()),
                    help="Replace stripped prefix with this (default: $HOME)")
    ap.add_argument("--force",     action="store_true", help="Re-extract even if javadoc already set")
    ap.add_argument("--limit",     type=int, help="Max classes to process")
    ap.add_argument("--stats",     action="store_true", help="Print stats and exit")
    ap.add_argument("--dry-run",   action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--neo4j-uri",  default=NEO4J_URI)
    ap.add_argument("--neo4j-user", default=NEO4J_USER)
    ap.add_argument("--neo4j-pass", default=NEO4J_PASS,
                    help="Neo4j password (default: NEO4J_PASSWORD env or 'codekg_dev')")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("backfill_javadoc")

    import warnings as _warnings
    import neo4j.warnings as _neo4j_warnings
    _warnings.filterwarnings("ignore", category=_neo4j_warnings.Neo4jWarning)

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_pass))

    if args.stats:
        print_stats(driver)
        driver.close()
        return

    if not args.repo_root:
        log.error("--repo-root is required (path to Java source tree)")
        driver.close()
        sys.exit(1)

    repo_root = Path(args.repo_root)
    if not repo_root.is_dir():
        log.error("--repo-root %s does not exist", repo_root)
        driver.close()
        sys.exit(1)

    log.info("Fetching classes from Neo4j (repo=%r, force=%s)…", args.repo or "all", args.force)
    classes = fetch_classes(driver, args.repo, args.force, args.limit)
    log.info("  %d classes to process", len(classes))

    done = skipped = missing = 0
    batch: list[dict] = []
    start = time.time()

    strip_prefix = args.strip_prefix
    add_prefix   = args.add_prefix

    for i, cls in enumerate(classes, 1):
        fqn       = cls["fqn"]
        name      = cls["name"]
        file_path = cls["file_path"]  # stored as relative or absolute

        # Remap Docker-internal paths (e.g. /host-home/ → /home/user/ or /Users/yourname/)
        if strip_prefix and file_path.startswith(strip_prefix):
            file_path = add_prefix + file_path[len(strip_prefix):]

        # Resolve file path
        candidate = Path(file_path)
        if not candidate.is_absolute():
            candidate = repo_root / file_path

        if not candidate.exists():
            log.debug("File not found: %s", candidate)
            missing += 1
            continue

        try:
            src = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            log.warning("Cannot read %s: %s", candidate, e)
            missing += 1
            continue

        javadoc = extract_javadoc(src, name)

        if args.verbose:
            preview = (javadoc or "")[:80]
            log.debug("[%d] %s → %s", i, name, preview or "(none)")

        if javadoc and not args.dry_run:
            batch.append({"fqn": fqn, "javadoc": javadoc})
            done += 1
        elif not javadoc:
            skipped += 1

        if len(batch) >= BATCH_SIZE:
            write_batch(driver, batch)
            log.info("  Written %d javadocs so far…", done)
            batch.clear()

        if i % 500 == 0:
            elapsed = time.time() - start
            log.info("Progress: %d/%d  done=%d  skipped=%d  missing=%d  (%.0fs)",
                     i, len(classes), done, skipped, missing, elapsed)

    if batch and not args.dry_run:
        write_batch(driver, batch)

    elapsed = time.time() - start
    log.info("Done in %.1fs — written=%d  no_javadoc=%d  file_missing=%d",
             elapsed, done, skipped, missing)
    driver.close()


if __name__ == "__main__":
    main()
