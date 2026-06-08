"""
Unit tests for services/api/agent_index/generator.py.

Coverage scope:
  - _shorten_fp() strips repo_path prefix, host-home prefix, and falls back to last-4-segments
  - generate_index() returns a string containing '## Available files'
  - generate_index() marks stale files with '⚠ stale'
  - _render_class() produces a markdown table with Method/Parameters/Returns columns
  - _render_class() handles None/empty object_model without crashing

run_query is mocked — no Neo4j required.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")
os.environ.setdefault("AGENT_INDEX_DB", ":memory:")

_SVC_ROOT = str(Path(__file__).parent.parent)
if _SVC_ROOT not in sys.path:
    sys.path.insert(0, _SVC_ROOT)

import agent_index.generator as gen


class TestShortenFp:
    """Exercises shorten file-path behavior in the agent index generator test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_strips_repo_path_prefix(self):
        """
        _shorten_fp() must strip the repo_path prefix from an absolute file path
        to produce a relative path. This makes file paths in index files portable
        across machines where /repos may be mounted at different locations.
        """
        fp = "/repos/my-project/src/main/java/Foo.java"
        result = gen._shorten_fp(fp, repo_path="/repos/my-project")
        assert result == "src/main/java/Foo.java"

    def test_falls_back_to_host_home_stripping(self):
        """
        When repo_path is not set but the path contains /host-home/, the function
        must strip the mount prefix and return a shortened path. This handles
        the case where the repo is mounted from the host home directory.
        """
        fp = "/host-home/Documents/projects/myrepo/src/Foo.java"
        result = gen._shorten_fp(fp, repo_path="")
        # Should return at most the last 4 segments
        parts = result.split("/")
        assert len(parts) <= 4
        assert "Foo.java" in result

    def test_falls_back_to_last_4_segments(self):
        """
        When neither repo_path nor /host-home/ helps, _shorten_fp() must return
        the last 4 path segments as a best-effort relative path.
        """
        fp = "/a/b/c/d/e/f/Foo.java"
        result = gen._shorten_fp(fp, repo_path="")
        parts = result.split("/")
        assert len(parts) <= 4
        assert "Foo.java" in result

    def test_empty_string_returns_empty(self):
        """
        An empty file path must be returned as-is without crashing.
        """
        assert gen._shorten_fp("", repo_path="") == ""


class TestGenerateIndex:
    """Exercises generate index behavior in the agent index generator test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_contains_available_files_heading(self):
        """
        generate_index() must return a string containing '## Available files'.
        This heading is how agents orient themselves to the index structure.
        """
        with patch.object(gen, "run_query", return_value=[]):
            result = gen.generate_index("my-repo", [
                {"file_key": "index", "directory": "", "filename": "INDEX.md",
                 "description": "Main index", "status": "current", "generated_at": None}
            ])
        assert "## Available files" in result

    def test_marks_stale_files(self):
        """
        A file with status='stale' must appear in the output with a '⚠ stale'
        annotation. Agents use this to know which files need re-reading.
        """
        with patch.object(gen, "run_query", return_value=[]):
            result = gen.generate_index("my-repo", [
                {"file_key": "modules/api", "directory": "modules", "filename": "api.md",
                 "description": "API module", "status": "stale", "generated_at": None}
            ])
        assert "stale" in result

    def test_current_files_not_marked_stale(self):
        """
        A file with status='current' must not have the stale marker.
        Only genuinely stale files should trigger a re-read by agents.
        """
        with patch.object(gen, "run_query", return_value=[]):
            result = gen.generate_index("my-repo", [
                {"file_key": "index", "directory": "", "filename": "INDEX.md",
                 "description": "desc", "status": "current", "generated_at": None}
            ])
        # stale marker should not appear on this entry
        lines_with_index = [ln for ln in result.splitlines() if "INDEX.md" in ln]
        assert any("stale" not in ln for ln in lines_with_index)


class TestRenderClass:
    """Exercises render class behavior in the agent index generator test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_produces_method_table(self):
        """
        _render_class() must output a markdown table with Method, Parameters, and
        Returns columns when the class has an object_model with methods.
        Agents rely on this table to understand the class interface without reading source.
        """
        cls = {
            "name": "PaymentService",
            "kind": "class",
            "fqn": "com.example.PaymentService",
            "file_path": "/repo/PaymentService.java",
            "grade": "A",
            "blast": 3,
            "loc": 120,
            "object_model": json.dumps({
                "methods": [
                    {"name": "processPayment", "return_type": "PaymentResult",
                     "parameters": ["String orderId", "BigDecimal amount"],
                     "modifiers": ["public"]},
                ]
            }),
        }
        lines = gen._render_class(cls)
        text = "\n".join(lines)
        assert "Method" in text or "method" in text.lower()
        assert "Parameters" in text or "Param" in text
        assert "processPayment" in text

    def test_handles_none_object_model(self):
        """
        _render_class() must not crash when object_model is None.
        Not all classes have a generated object model (e.g. if summarisation
        hasn't run yet). The function must return at least the class header.
        """
        cls = {
            "name": "EmptyClass",
            "kind": "class",
            "fqn": "com.example.EmptyClass",
            "file_path": "/repo/EmptyClass.java",
            "grade": "B",
            "blast": 0,
            "loc": 10,
            "object_model": None,
        }
        lines = gen._render_class(cls)
        assert any("EmptyClass" in ln for ln in lines)

    def test_handles_empty_dict_object_model(self):
        """
        _render_class() must not crash when object_model is an empty JSON object {}.
        An empty model means no methods were extracted (valid for some classes).
        """
        cls = {
            "name": "Minimal",
            "kind": "class",
            "fqn": "com.example.Minimal",
            "file_path": "/repo/Minimal.java",
            "grade": "C",
            "blast": 1,
            "loc": 5,
            "object_model": "{}",
        }
        lines = gen._render_class(cls)
        assert isinstance(lines, list)
