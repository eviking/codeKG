#!/usr/bin/env python3
"""
Single-shot ingestion entrypoint.

Reads env vars, runs one scan (full or incremental), then exits.
Designed to be launched as an ephemeral Docker container per scan job.

Required env vars:
  NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
  SCAN_REPO_ID    — registry key, e.g. "codeKG"
  SCAN_REPO_PATH  — path inside the container, e.g. "/host-home/Documents/projects/codeKG"

Optional env vars:
  SCAN_TYPE        — "full" (default) or "incremental"
  SCAN_FROM_COMMIT — required when SCAN_TYPE=incremental
  SCAN_TO_COMMIT   — required when SCAN_TYPE=incremental
"""
import os
import sys

from shared.config import cfg
from shared.codekg_logging.codekg_logger import get_logger
from kg.writer import KGWriter
from ingestion_engine import IngestionEngine

log = get_logger(__name__, service="ingestion")


def main():
    # NEO4J_* sourced from cfg; SCAN_* are per-job vars injected by the watcher
    repo_id   = os.environ["SCAN_REPO_ID"]
    repo_path = os.environ["SCAN_REPO_PATH"]
    scan_type = os.environ.get("SCAN_TYPE", "full")

    log.info("Scan job starting", repo_id=repo_id, path=repo_path, type=scan_type)

    writer = KGWriter(cfg.neo4j.uri, cfg.neo4j.user, cfg.neo4j.password)
    writer.ensure_schema()
    engine = IngestionEngine(writer)

    try:
        if scan_type == "incremental":
            from_commit = os.environ["SCAN_FROM_COMMIT"]
            to_commit   = os.environ["SCAN_TO_COMMIT"]
            log.info("Incremental scan", from_commit=from_commit[:8], to_commit=to_commit[:8])
            engine.incremental_update(repo_path, repo_id, from_commit, to_commit)
        else:
            engine.full_scan(repo_path, repo_id)

        log.info("Scan job complete", repo_id=repo_id, type=scan_type)
        sys.exit(0)
    except Exception as exc:
        log.error("Scan job failed", repo_id=repo_id, error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
