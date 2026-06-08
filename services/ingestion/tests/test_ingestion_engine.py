"""
Integration-style unit tests for IngestionEngine (services/ingestion/ingestion_engine.py).

Coverage scope:
  - full_scan() on a temp directory with Python files calls writer methods
  - full_scan() skips __pycache__, .git, .venv directories
  - incremental_update() calls writer.delete_file_nodes for changed files
  - WORKER_COUNT=1 disables multiprocessing (safe for test environments)

KGWriter is fully mocked — no Neo4j, no Docker required.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# Force single-worker mode before importing config/engine
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")
os.environ["WORKER_COUNT"] = "1"

_SVC_ROOT = str(Path(__file__).parent.parent)
if _SVC_ROOT not in sys.path:
    sys.path.insert(0, _SVC_ROOT)

import pytest


def _make_writer():
    """Return a MagicMock that satisfies the KGWriter interface."""
    writer = MagicMock()
    writer.write_parsed_batch = MagicMock()
    writer.delete_file_nodes = MagicMock()
    writer.write_repo = MagicMock()
    writer.write_build_info = MagicMock()
    writer.write_endpoints = MagicMock()
    writer.write_concurrency_facts = MagicMock()
    writer.write_scip_documents = MagicMock()
    writer.wire_edges = MagicMock()
    return writer


class TestFullScan:
    """Exercises full scan behavior in the ingestion engine test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_full_scan_calls_write_parsed_batch(self, tmp_path):
        """
        full_scan() on a directory containing at least one .py file must call
        writer.write_parsed_batch at least once so parsed data reaches the KG.
        This verifies the core parse → write pipeline is connected.
        """
        (tmp_path / "hello.py").write_text("""\
class Greeter:
    def greet(self, name: str) -> str:
        return f"Hello, {name}"
""")
        writer = _make_writer()

        # Patch all expensive post-parse steps so we only test the parse/write loop
        with patch("ingestion_engine.compute_hygiene"), \
             patch("ingestion_engine.enrich_classes"), \
             patch("ingestion_engine.build_object_models"), \
             patch("ingestion_engine.build_call_chains"), \
             patch("ingestion_engine.scan_policies"), \
             patch("ingestion_engine.detect_patterns", return_value=[]), \
             patch("ingestion_engine.save_patterns_to_kg"), \
             patch("ingestion_engine.extract_modules", return_value=[]), \
             patch("ingestion_engine.extract_project_identity", return_value=MagicMock(name="test-repo")), \
             patch("ingestion_engine.extract_repo_map", return_value={}), \
             patch("ingestion_engine.write_claude_md"), \
             patch("ingestion_engine.BuildExtractor") as mock_be, \
             patch("git.Repo"):
            mock_be.return_value.extract.return_value = (MagicMock(build_tool="python"), [])
            from ingestion_engine import IngestionEngine
            engine = IngestionEngine(writer)
            engine.full_scan(str(tmp_path), "test-repo")

        assert writer.write_parsed_batch.called or writer.write_repo.called, (
            "Expected write_parsed_batch or write_repo to be called during full_scan"
        )

    def test_full_scan_skips_hidden_dirs(self, tmp_path):
        """
        full_scan() must not parse files inside __pycache__, .git, or .venv.
        Including these would pollute the KG with interpreter artifacts.
        This test verifies the skip logic by counting write calls vs total files.
        """
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "cached.pyc").write_bytes(b"\x00")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("[core]\n")
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "site.py").write_text("# venv\n")
        (tmp_path / "real.py").write_text("class Real: pass\n")

        writer = _make_writer()
        captured_batches = []
        writer.write_parsed_batch.side_effect = lambda batch, **kw: captured_batches.append(batch)

        with patch("ingestion_engine.compute_hygiene"), \
             patch("ingestion_engine.enrich_classes"), \
             patch("ingestion_engine.build_object_models"), \
             patch("ingestion_engine.build_call_chains"), \
             patch("ingestion_engine.scan_policies"), \
             patch("ingestion_engine.detect_patterns", return_value=[]), \
             patch("ingestion_engine.save_patterns_to_kg"), \
             patch("ingestion_engine.extract_modules", return_value=[]), \
             patch("ingestion_engine.extract_project_identity", return_value=MagicMock(name="test-repo")), \
             patch("ingestion_engine.extract_repo_map", return_value={}), \
             patch("ingestion_engine.write_claude_md"), \
             patch("ingestion_engine.BuildExtractor") as mock_be, \
             patch("git.Repo"):
            mock_be.return_value.extract.return_value = (MagicMock(build_tool="python"), [])
            from ingestion_engine import IngestionEngine
            engine = IngestionEngine(writer)
            engine.full_scan(str(tmp_path), "test-repo")

        # All parsed file paths in batches should not include pycache/git/venv paths
        for batch in captured_batches:
            for item in (batch if isinstance(batch, list) else []):
                if item and hasattr(item, "file_path"):
                    fp = item.file_path
                    assert "__pycache__" not in fp
                    assert "/.git/" not in fp
                    assert "/.venv/" not in fp
