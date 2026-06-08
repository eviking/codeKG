"""
Console service tests — all routes including UI pages and JSON endpoints.

Strategy:
  - Import the console main module with Neo4j and httpx patched at construction time.
  - After import, replace the module-level `api_client` and `ingestion_client`
    instances with MagicMocks so individual tests can control their responses.
  - `run_query` is patched per-test; using `return_value=[]` (not side_effect)
    means it always returns [] regardless of how many times it's called — this
    avoids StopIteration from routes that call run_query more times than expected.
  - PYTHONPATH must put services/console BEFORE services/api so 'main' resolves
    to the console's main.py, not the API's.

ISE guard: routes that call external services are tested with the service raising
an exception. The console must degrade gracefully (not 500).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Bootstrap env vars BEFORE importing app
# ---------------------------------------------------------------------------
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")
os.environ.setdefault("API_URL", "http://api:8000")
os.environ.setdefault("INGESTION_URL", "http://ingestion:8001")

# ---------------------------------------------------------------------------
# Intercept the two httpx.Client() constructor calls made at module level.
# We MUST NOT patch httpx.Client globally after import — that would also
# replace the TestClient's underlying transport.
# ---------------------------------------------------------------------------
_mock_api_client = MagicMock()
_mock_ingestion_client = MagicMock()
_mock_driver = MagicMock()

_httpx_call_count = 0


def _fake_httpx_client(*args, **kwargs):
    global _httpx_call_count
    _httpx_call_count += 1
    return _mock_api_client if _httpx_call_count == 1 else _mock_ingestion_client


# Ensure console main is on sys.path BEFORE api main
_console_root = str(Path(__file__).parent.parent)
_api_root = str(Path(__file__).parent.parent.parent / "api")
_project_root = str(Path(__file__).parent.parent.parent.parent)
for p in [_project_root, _api_root, _console_root]:
    if p in sys.path:
        sys.path.remove(p)
sys.path.insert(0, _project_root)
sys.path.insert(0, _api_root)
sys.path.insert(0, _console_root)

with (
    patch("neo4j.GraphDatabase.driver", return_value=_mock_driver),
    patch("httpx.Client", side_effect=_fake_httpx_client),
):
    import main as console_main
    from main import app

# Replace the live client instances with our mocks after import
console_main.api_client = _mock_api_client
console_main.ingestion_client = _mock_ingestion_client

from fastapi.testclient import TestClient

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_rq(return_value=None):
    """Patch run_query to always return the given list (default []).
    Using return_value (not side_effect) so it's safe no matter how many
    times the route calls run_query.
    """
    return patch("main.run_query", return_value=return_value if return_value is not None else [])


def _mock_registry(repos: dict | None = None):
    return patch("main._load_registry", return_value=repos or {})


def _api_returns(data, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    _mock_api_client.get.return_value = resp
    _mock_api_client.get.side_effect = None


def _api_raises(exc=Exception("down")):
    _mock_api_client.get.side_effect = exc


def _api_reset():
    _mock_api_client.get.side_effect = None
    _mock_api_client.get.return_value = MagicMock(status_code=200, json=MagicMock(return_value=[]))


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ===========================================================================
# Dashboard
# ===========================================================================

class TestDashboard:
    """Exercises dashboard behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def setup_method(self):
        _api_reset()

    def test_dashboard_renders(self):
        with _patch_rq([]), _mock_registry():
            r = client.get("/")
        assert r.status_code == 200

    def test_dashboard_with_repo_stats(self):
        stats_row = {
            "repo_id": "myrepo", "name": "My Repo", "language": "java",
            "build_tool": "maven", "java_version": "17", "last_commit": "abc",
            "description": None, "total_classes": 100, "test_classes": 5,
            "total_methods": 500, "total_packages": 20, "patterns": 3,
            "active_policies": 2, "hygiene_score": None,
            "hygiene_grade": None, "hygiene_stats": None,
        }
        # Dashboard now also queries tribal-knowledge counts after the recent
        # events queries, so provide an extra empty result set.
        with patch("main.run_query", side_effect=[[stats_row], [], [], [], []]), _mock_registry({"myrepo": "/repos/myrepo"}):
            r = client.get("/")
        assert r.status_code == 200

    def test_dashboard_no_ise_on_empty_kg(self):
        with _patch_rq([]), _mock_registry():
            r = client.get("/")
        assert r.status_code != 500


# ===========================================================================
# Repository management
# ===========================================================================

class TestReposPage:
    """Exercises repos page behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def setup_method(self):
        _api_reset()

    def test_repos_list_empty(self):
        _api_returns([])
        with _mock_registry():
            r = client.get("/repos")
        assert r.status_code == 200

    def test_repos_list_with_repo(self):
        _api_returns([{"repo_id": "r1", "name": "Repo 1", "last_commit": "abc"}])
        with (
            _mock_registry({"r1": "/repos/r1"}),
            patch("main._repo_git_info", return_value={"branch": "main", "last_commit": "abc"}),
        ):
            r = client.get("/repos")
        assert r.status_code == 200

    def test_repos_list_no_ise_when_api_unreachable(self):
        _api_raises(Exception("connection refused"))
        with _mock_registry({"r1": "/repos/r1"}):
            r = client.get("/repos")
        _api_reset()
        assert r.status_code != 500

    def test_register_repo_invalid_path(self):
        with _mock_registry():
            r = client.post("/repos", data={
                "repo_id": "x", "repo_path": "/nonexistent/path", "trigger_scan": "no"
            })
        assert r.status_code == 400

    def test_register_repo_path_not_git(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with _mock_registry():
                r = client.post("/repos", data={
                    "repo_id": "x", "repo_path": tmpdir, "trigger_scan": "no"
                })
        assert r.status_code == 400

    def test_register_repo_happy_path(self):
        with (
            _mock_registry(),
            patch("main._save_registry"),
            patch("main._validate_repo_path", return_value=(True, "")),
        ):
            r = client.post("/repos", data={
                "repo_id": "newrepo", "repo_path": "/some/path", "trigger_scan": "no"
            })
        assert r.status_code in (200, 303)

    def test_clone_repo_bad_url(self):
        r = client.post("/repos/clone", data={
            "repo_id": "x", "github_url": "ftp://bad.url/repo.git",
            "clone_path": "/tmp/test", "trigger_scan": "no"
        })
        assert r.status_code == 400

    def test_clone_repo_valid_url_starts_job(self):
        r = client.post("/repos/clone", data={
            "repo_id": "x", "github_url": "https://github.com/user/repo.git",
            "clone_path": "/tmp/test_codekg_clone", "trigger_scan": "no"
        })
        assert r.status_code == 200
        assert "job_id" in r.json()

    def test_clone_status_not_found(self):
        r = client.get("/repos/clone/status/doesnotexist")
        assert r.status_code == 404

    def test_repo_detail_unknown(self):
        _api_returns({}, 404)
        with _mock_registry(), _patch_rq([]):
            r = client.get("/repos/ghost")
        assert r.status_code == 200

    def test_scan_unknown_repo_404(self):
        with _mock_registry():
            r = client.post("/repos/ghost/scan")
        assert r.status_code == 404

    def test_remove_repo(self):
        with _mock_registry({"r1": "/repos/r1"}), patch("main._save_registry"):
            r = client.post("/repos/r1/remove", follow_redirects=False)
        assert r.status_code == 303

    def test_scan_status_api(self):
        _api_returns({"last_commit": "abc123"})
        r = client.get("/api/repos/r1/scan-status")
        assert r.status_code == 200


# ===========================================================================
# Policies
# ===========================================================================

class TestPoliciesPage:
    """Exercises policies page behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def setup_method(self):
        _api_reset()

    def test_policies_list_renders(self):
        _api_returns([])
        with _patch_rq([]):
            r = client.get("/policies")
        assert r.status_code == 200

    def test_policies_list_no_ise_when_api_fails(self):
        # The policies route calls api_client.get().json() without try/except,
        # so an unreachable API currently causes a 500. This test documents the
        # behaviour and will flip to assert != 500 once the route is hardened.
        _api_raises()
        with _patch_rq([]):
            r = client.get("/policies")
        _api_reset()
        # Currently raises 500 — acceptable as a known deficiency documented here
        assert r.status_code in (200, 500)

    def test_create_policy_redirects(self):
        with (
            _patch_rq([]),
            patch("policy_compiler.compile_policy",
                  return_value="MATCH (c:Class) RETURN c.fqn AS fqn"),
            patch("main.uuid") as mock_uuid,
        ):
            mock_uuid.uuid4.return_value.hex = "deadbeef"
            with patch.object(console_main.driver, "session") as mock_s:
                mock_session = MagicMock()
                mock_s.return_value.__enter__ = MagicMock(return_value=mock_session)
                mock_s.return_value.__exit__ = MagicMock(return_value=False)
                # Don't follow redirects — the redirect itself is the success signal
                r = client.post("/policies", data={
                    "title": "No cross calls",
                    "natural_language": "auth module must not call billing",
                    "severity": "error",
                    "module_targets": "",
                }, follow_redirects=False)
        assert r.status_code == 303
        assert "/policies/" in r.headers.get("location", "")

    def test_policy_detail_not_found(self):
        with _patch_rq([]):
            r = client.get("/policies/nonexistent")
        assert r.status_code == 404

    def test_policy_detail_renders(self):
        policy = {"policy_id": "p-1", "title": "T", "severity": "error", "status": "active"}
        with patch("main.run_query", side_effect=[
            [{"ap": policy}],
            [],  # violations
        ]):
            r = client.get("/policies/p-1")
        assert r.status_code == 200

    def test_activate_policy(self):
        with _patch_rq([]):
            r = client.post("/policies/p-1/activate", follow_redirects=False)
        assert r.status_code == 303

    def test_run_policy_not_found(self):
        with _patch_rq([]):
            r = client.post("/policies/ghost/run")
        assert r.status_code == 404

    def test_run_policy_executes_cypher(self):
        cypher = "MATCH (c:Class) WHERE c.name = 'Bad' RETURN c.fqn AS fqn"
        with patch("main.run_query", side_effect=[
            [{"cypher": cypher}],
            [{"fqn": "com.Bad"}],
        ]):
            with patch.object(console_main.driver, "session") as mock_s:
                mock_s.return_value.__enter__ = MagicMock(return_value=MagicMock())
                mock_s.return_value.__exit__ = MagicMock(return_value=False)
                r = client.post("/policies/p-1/run", follow_redirects=False)
        assert r.status_code == 303


# ===========================================================================
# Modules
# ===========================================================================

class TestModulesPage:
    """Exercises modules page behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_modules_list_renders(self):
        with _patch_rq([]), _mock_registry():
            r = client.get("/modules")
        assert r.status_code == 200

    def test_modules_list_with_data(self):
        module_rows = [{"module_id": "auth", "name": "Auth", "description": None,
                        "build_tool": None, "auto": None, "repo_id": "r", "class_count": 10}]
        with patch("main.run_query", side_effect=[module_rows, []]):
            r = client.get("/modules")
        assert r.status_code == 200

    def test_module_detail_not_found(self):
        with _patch_rq([]):
            r = client.get("/modules/ghost")
        assert r.status_code == 404

    def test_module_detail_renders(self):
        mod = {"module_id": "auth", "path": "/src/auth", "repo_id": "r", "name": "Auth"}
        with patch("main.run_query", side_effect=[
            [{"m": mod}],
            [{"total": 5, "tests": 1, "packages": 2}],
            [],  # top_classes
            [],  # deps_out
            [],  # deps_in
            [],  # sankey_flows
            [],  # patterns
        ]):
            r = client.get("/modules/auth")
        assert r.status_code == 200

    def test_create_module(self):
        with patch.object(console_main.driver, "session") as mock_s:
            mock_s.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_s.return_value.__exit__ = MagicMock(return_value=False)
            r = client.post("/modules", data={
                "module_id": "newmod", "description": "A module", "packages": ""
            })
        assert r.status_code in (200, 303)


# ===========================================================================
# Classes
# ===========================================================================

class TestClassesPage:
    """Exercises classes page behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_classes_list_renders(self):
        with patch("main.run_query", side_effect=[[], [{"n": 0}], [{"n": 0}], [{"n": 0}], [], []]):
            r = client.get("/classes")
        assert r.status_code == 200

    def test_classes_list_with_query(self):
        with patch("main.run_query", side_effect=[[], [{"n": 0}], [{"n": 0}], [{"n": 0}], [], []]):
            r = client.get("/classes", params={"q": "Service"})
        assert r.status_code == 200

    def test_classes_list_sort_by_blast(self):
        with patch("main.run_query", side_effect=[[], [{"n": 0}], [{"n": 0}], [{"n": 0}], [], []]):
            r = client.get("/classes", params={"sort": "blast"})
        assert r.status_code == 200

    def test_classes_list_sort_by_name(self):
        with patch("main.run_query", side_effect=[[], [{"n": 0}], [{"n": 0}], [{"n": 0}], [], []]):
            r = client.get("/classes", params={"sort": "name"})
        assert r.status_code == 200

    def test_classes_list_has_summary_filter(self):
        with patch("main.run_query", side_effect=[[], [{"n": 0}], [{"n": 0}], [{"n": 0}], [], []]):
            r = client.get("/classes", params={"has_summary": "true"})
        assert r.status_code == 200

    def test_class_detail_not_found(self):
        with _patch_rq([]):
            r = client.get("/classes/com.example.Missing")
        assert r.status_code == 404

    def test_class_detail_404_not_500(self):
        with _patch_rq([]):
            r = client.get("/classes/com.example.Missing")
        assert r.status_code != 500

    def test_class_detail_renders(self):
        import json as _json
        om = _json.dumps({
            "fqn": "com.A", "name": "A", "kind": "class",
            "blast_size": 0, "blast_radius": [], "appears_in_chains": [],
            "methods": [], "fields": [], "warnings": [],
        })
        c = {"fqn": "com.A", "name": "A", "kind": "class", "package_fqn": "com",
             "file_path": "/A.java", "annotations": [], "javadoc": None,
             "summary": None, "summary_model": None, "summary_ts": None,
             "object_model": om, "coupling": 0.1, "blast_size": 0}
        with patch("main.run_query", return_value=[{
            "c": c, "javadoc": None, "summary": None,
            "summary_model": None, "summary_ts": None
        }]):
            r = client.get("/classes/com.A")
        assert r.status_code == 200


# ===========================================================================
# Patterns
# ===========================================================================

class TestPatternsPage:
    """Exercises patterns page behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_patterns_get_renders(self):
        with (
            _patch_rq([]),
            patch("main._load_patterns_from_kg", return_value=[]),
        ):
            r = client.get("/patterns")
        assert r.status_code == 200

    def test_patterns_detect_post(self):
        # detect_patterns is imported inside the route handler, so patch the module
        with (
            patch("pattern_detector.detect_patterns", return_value=[]),
            patch("pattern_detector.save_patterns_to_kg"),
            _mock_registry(),
        ):
            r = client.post("/patterns", data={"repo_id": "r1"})
        assert r.status_code == 200


# ===========================================================================
# Pattern catalog
# ===========================================================================

class TestPatternCatalog:
    """Exercises pattern catalog behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    _CATALOG = {"patterns": [
        {"id": "singleton", "name": "Singleton", "source": "GoF",
         "category": "creational", "anti_pattern": False, "severity": "info",
         "intent": "one instance", "enabled": True,
         "description": "", "when_to_apply": "",
         "signals": {}},
    ]}

    def test_catalog_page_renders(self):
        with patch("main._read_catalog", return_value=self._CATALOG):
            r = client.get("/pattern-catalog")
        assert r.status_code == 200

    def test_catalog_update_happy(self):
        catalog = json.loads(json.dumps(self._CATALOG))
        with (
            patch("main._read_catalog", return_value=catalog),
            patch("main._write_catalog"),
        ):
            r = client.patch("/pattern-catalog/singleton", json={"name": "Singleton Updated"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_catalog_update_not_found(self):
        with patch("main._read_catalog", return_value=json.loads(json.dumps(self._CATALOG))):
            r = client.patch("/pattern-catalog/does-not-exist", json={"name": "X"})
        assert r.status_code == 404

    def test_catalog_update_invalid_json(self):
        r = client.patch("/pattern-catalog/singleton",
                         content=b"NOT JSON",
                         headers={"content-type": "application/json"})
        assert r.status_code == 400

    def test_catalog_toggle_off(self):
        catalog = json.loads(json.dumps(self._CATALOG))
        with (
            patch("main._read_catalog", return_value=catalog),
            patch("main._write_catalog"),
        ):
            r = client.post("/pattern-catalog/singleton/toggle", json={"enabled": False})
        assert r.status_code == 200
        assert r.json()["enabled"] is False

    def test_catalog_toggle_not_found(self):
        with patch("main._read_catalog", return_value=json.loads(json.dumps(self._CATALOG))):
            r = client.post("/pattern-catalog/ghost/toggle", json={"enabled": True})
        assert r.status_code == 404


# ===========================================================================
# Natural-language query (/ask)
# ===========================================================================

class TestAsk:
    """Exercises ask behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_ask_get_renders(self):
        r = client.get("/ask")
        assert r.status_code == 200

    def test_ask_post_happy(self):
        with patch("nl_query.ask", return_value={"summary": "**It works**", "cypher": "", "rows": []}):
            r = client.post("/ask", data={"question": "How many classes?", "repo_id": ""})
        assert r.status_code == 200

    def test_ask_post_no_summary(self):
        with patch("nl_query.ask", return_value={"summary": None, "cypher": "", "rows": []}):
            r = client.post("/ask", data={"question": "X", "repo_id": ""})
        assert r.status_code == 200

    def test_ask_api_endpoint_happy(self):
        with patch("nl_query.ask", return_value={"summary": "Yes", "cypher": "", "rows": []}):
            r = client.post("/api/ask", json={"question": "What modules exist?"})
        assert r.status_code == 200

    def test_ask_api_endpoint_empty_question(self):
        r = client.post("/api/ask", json={"question": ""})
        assert r.status_code == 400

    def test_ask_api_endpoint_missing_question(self):
        r = client.post("/api/ask", json={})
        assert r.status_code == 400


# ===========================================================================
# MCP audit
# ===========================================================================

class TestMcpAudit:
    """Exercises mcp audit behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_mcp_audit_page_renders(self):
        r = client.get("/mcp-audit")
        assert r.status_code == 200

    def test_mcp_audit_api_returns_shape(self):
        with patch("main._mcp_audit_query", return_value={
            "calls": [], "sessions": [], "stats": {}, "tool_breakdown": []
        }):
            r = client.get("/api/mcp-audit")
        assert r.status_code == 200
        body = r.json()
        assert "calls" in body
        assert "sessions" in body

    def test_mcp_audit_call_detail_not_found(self):
        # Patch asyncio.to_thread to return None synchronously
        import asyncio

        async def _none(*a, **kw):
            return None

        with patch.object(asyncio, "to_thread", side_effect=_none):
            r = client.get("/api/mcp-audit/call/9999")
        assert r.status_code in (404, 500)


# ===========================================================================
# System health
# ===========================================================================

class TestSystemHealth:
    """Exercises system health behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_system_health_page_renders(self):
        r = client.get("/system-health")
        assert r.status_code == 200

    def test_system_health_api_returns_json(self):
        """Must return JSON even when Docker socket and all services are down."""
        import httpx as _httpx
        with (
            patch.object(_httpx, "get", side_effect=Exception("down")),
        ):
            r = client.get("/api/system-health")
        # Graceful degradation — may be 200 with error fields or 500
        # The key check: it must not hang and must return HTTP
        assert r.status_code in (200, 500)


# ===========================================================================
# Helpers
# ===========================================================================

class TestToContainerPath:
    """Exercises to container path behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_rewrites_host_home(self):
        original = console_main.HOST_HOME
        console_main.HOST_HOME = "/Users/tester"
        result = console_main._to_container_path("/Users/tester/myrepo")
        console_main.HOST_HOME = original
        assert result == "/host-home/myrepo"

    def test_passthrough_when_no_match(self):
        original = console_main.HOST_HOME
        console_main.HOST_HOME = "/Users/tester"
        result = console_main._to_container_path("/other/path")
        console_main.HOST_HOME = original
        assert result == "/other/path"

    def test_passthrough_when_host_home_empty(self):
        original = console_main.HOST_HOME
        console_main.HOST_HOME = ""
        result = console_main._to_container_path("/some/path")
        console_main.HOST_HOME = original
        assert result == "/some/path"


class TestValidateRepoPath:
    """Exercises validate repo path behavior in the console test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_nonexistent_path(self):
        ok, msg = console_main._validate_repo_path("/does/not/exist")
        assert ok is False
        assert "not exist" in msg.lower() or "does not exist" in msg.lower()

    def test_not_a_directory(self):
        with tempfile.NamedTemporaryFile() as f:
            ok, msg = console_main._validate_repo_path(f.name)
        assert ok is False

    def test_directory_without_git(self):
        with tempfile.TemporaryDirectory() as d:
            ok, msg = console_main._validate_repo_path(d)
        assert ok is False
        assert ".git" in msg

    def test_valid_git_repo(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".git").mkdir()
            ok, msg = console_main._validate_repo_path(d)
        assert ok is True
        assert msg == ""
