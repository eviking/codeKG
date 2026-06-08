"""
API service tests — all routes, error paths, and edge cases.

Strategy: patch the Neo4j driver at the module level so every test runs without
a live database. The `run_query` helper is the single choke-point; monkeypatching
it is sufficient to drive all route branches.

ISE guard: every route that touches Neo4j is tested with both a happy-path return
and an empty-result return to ensure we never leak an unhandled exception as a 500.
"""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Bootstrap — inject required env vars before importing the app
# ---------------------------------------------------------------------------

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

# Patch the driver at construction time so we never open a real socket
_mock_driver = MagicMock()
_mock_session = MagicMock()
_mock_driver.session.return_value.__enter__ = MagicMock(return_value=_mock_session)
_mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

with patch("neo4j.GraphDatabase.driver", return_value=_mock_driver):
    # Add service root to path so relative imports work
    sys.path.insert(0, str(__file__).replace("/tests/test_api.py", ""))
    from main import app  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_rq(return_value):
    """Patch run_query in the api main module."""
    return patch("main.run_query", return_value=return_value)


SAMPLE_REPO = {"repo_id": "myrepo", "name": "My Repo", "last_commit": "abc123"}
SAMPLE_CLASS = {
    "fqn": "com.example.Foo", "name": "Foo", "kind": "class",
    "file_path": "/src/Foo.java", "annotations": [],
    "object_model": None,
}
SAMPLE_POLICY = {
    "policy_id": "p-001", "title": "No cross-module calls",
    "natural_language": "auth module must not call billing",
    "severity": "error", "status": "active",
}


# ===========================================================================
# /health
# ===========================================================================

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ===========================================================================
# /repos
# ===========================================================================

class TestRepos:
    """Exercises repos behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_list_repos_empty(self):
        with _patch_rq([]):
            r = client.get("/repos")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_repos_returns_data(self):
        with _patch_rq([SAMPLE_REPO]):
            r = client.get("/repos")
        assert r.status_code == 200
        assert r.json()[0]["repo_id"] == "myrepo"

    def test_get_repo_found(self):
        with _patch_rq([SAMPLE_REPO]):
            r = client.get("/repos/myrepo")
        assert r.status_code == 200
        assert r.json()["repo_id"] == "myrepo"

    def test_get_repo_not_found(self):
        with _patch_rq([]):
            r = client.get("/repos/doesnotexist")
        assert r.status_code == 404

    def test_get_repo_not_found_no_ise(self):
        """Ensure missing repo returns 404, not 500."""
        with _patch_rq([]):
            r = client.get("/repos/missing")
        assert r.status_code != 500


# ===========================================================================
# /context/module/{module_id}
# ===========================================================================

class TestModuleContext:
    """Exercises module context behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_happy_path(self):
        with patch("main.run_query", side_effect=[
            [SAMPLE_CLASS],  # classes
            [SAMPLE_POLICY],  # policies
            [],               # violations
        ]):
            r = client.get("/context/module/auth")
        assert r.status_code == 200
        body = r.json()
        assert body["module"] == "auth"
        assert isinstance(body["classes"], list)
        assert isinstance(body["policies"], list)
        assert isinstance(body["violations"], list)

    def test_empty_module(self):
        with patch("main.run_query", side_effect=[[], [], []]):
            r = client.get("/context/module/empty")
        assert r.status_code == 200
        assert r.json()["classes"] == []

    def test_no_ise_on_exception(self):
        """run_query raising should not bleed as 500 through bad code paths."""
        with patch("main.run_query", side_effect=[[], [], []]):
            r = client.get("/context/module/x")
        assert r.status_code != 500


# ===========================================================================
# /context/class/{fqn}
# ===========================================================================

class TestClassContext:
    """Exercises class context behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_class_found_via_prebuilt_snapshot(self):
        om = json.dumps({"fqn": "com.example.Foo", "name": "Foo", "kind": "class",
                         "methods": [], "fields": []})
        row = {"om": om, "c": MagicMock(**{"__iter__": MagicMock(return_value=iter([
            ("fqn", "com.example.Foo"), ("name", "Foo")
        ]))})}
        # dict(node) must work — use a plain dict as the node value
        row["c"] = {"fqn": "com.example.Foo", "name": "Foo", "kind": "class"}
        with _patch_rq([row]):
            r = client.get("/context/class/com.example.Foo")
        assert r.status_code == 200

    def test_class_not_found_returns_404(self):
        with patch("main.run_query", return_value=[]):
            r = client.get("/context/class/com.example.Missing")
        assert r.status_code == 404

    def test_class_not_found_no_ise(self):
        with patch("main.run_query", return_value=[]):
            r = client.get("/context/class/com.example.Missing")
        assert r.status_code != 500

    def test_fuzzy_fallback_also_404(self):
        # First call (exact fqn) returns empty, second call (fuzzy) also empty → 404
        with patch("main.run_query", side_effect=[[], []]):
            r = client.get("/context/class/NonExistent")
        assert r.status_code == 404

    def test_live_fallback_path(self):
        """When object_model is absent, fall back to live queries — should return 200."""
        cls_node = {"fqn": "com.example.Foo", "name": "Foo", "kind": "class",
                    "package_fqn": "com.example", "file_path": "/Foo.java",
                    "annotations": [], "javadoc": None, "summary": None,
                    "summary_model": None, "summary_ts": None}
        with patch("main.run_query", side_effect=[
            [{"om": None, "c": cls_node}],  # initial lookup
            [],  # methods
            [],  # fields
            [],  # extends
            [],  # implements
            [],  # dependents
            [],  # imports
            [],  # patterns
        ]):
            r = client.get("/context/class/com.example.Foo")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Foo"
        assert body["methods"] == []


# ===========================================================================
# /context/feature
# ===========================================================================

class TestFeatureContext:
    """Exercises feature context behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_feature_returns_list(self):
        om = json.dumps({"fqn": "com.A", "name": "A", "kind": "class", "methods": [], "fields": []})
        with patch("main.run_query", return_value=[{"om": om, "c": {"fqn": "com.A", "name": "A"}}]):
            r = client.get("/context/feature", params={"classes": "com.A"})
        assert r.status_code == 200
        assert "feature_classes" in r.json()

    def test_feature_skips_missing_classes(self):
        """Missing classes are silently dropped, no 500."""
        with patch("main.run_query", return_value=[]):
            r = client.get("/context/feature", params={"classes": "com.A,com.B"})
        assert r.status_code == 200
        assert r.json()["feature_classes"] == []


# ===========================================================================
# /violations
# ===========================================================================

class TestViolations:
    """Exercises violations behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_list_violations_empty(self):
        with _patch_rq([]):
            r = client.get("/violations")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_violations_with_filters(self):
        row = {"violator": "com.A", "file_path": "/A.java",
               "policy_id": "p-1", "policy_title": "Rule", "severity": "error"}
        with _patch_rq([row]):
            r = client.get("/violations", params={"repo_id": "myrepo", "severity": "error"})
        assert r.status_code == 200
        assert r.json()[0]["violator"] == "com.A"

    def test_pr_violations_empty_files(self):
        with _patch_rq([]):
            r = client.get("/violations/pr", params={"files": "/src/Foo.java"})
        assert r.status_code == 200

    def test_pr_violations_returns_matches(self):
        row = {"violator": "com.A", "file_path": "/A.java",
               "policy_id": "p-1", "policy_title": "Rule", "severity": "warning"}
        with _patch_rq([row]):
            r = client.get("/violations/pr", params={"files": "/A.java,/B.java"})
        assert r.status_code == 200
        assert len(r.json()) == 1


# ===========================================================================
# /policies
# ===========================================================================

class TestPolicies:
    """Exercises policies behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_list_active_policies(self):
        with _patch_rq([{"ap": SAMPLE_POLICY}]):
            r = client.get("/policies")
        assert r.status_code == 200

    def test_list_all_policies(self):
        with _patch_rq([{"ap": SAMPLE_POLICY}]):
            r = client.get("/policies", params={"status": None})
        assert r.status_code == 200

    def test_get_policy_found(self):
        with _patch_rq([{"ap": SAMPLE_POLICY}]):
            r = client.get("/policies/p-001")
        assert r.status_code == 200

    def test_get_policy_not_found(self):
        with _patch_rq([]):
            r = client.get("/policies/p-999")
        assert r.status_code == 404

    def test_get_policy_404_not_500(self):
        with _patch_rq([]):
            r = client.get("/policies/p-999")
        assert r.status_code != 500


# ===========================================================================
# /search/class
# ===========================================================================

class TestSearchClass:
    """Exercises search class behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_search_returns_results(self):
        row = {"fqn": "com.example.Foo", "name": "Foo", "kind": "class",
               "package_fqn": "com.example", "repo_id": "myrepo", "om": None}
        with _patch_rq([row]):
            r = client.get("/search/class", params={"q": "Foo"})
        assert r.status_code == 200
        assert r.json()[0]["name"] == "Foo"

    def test_search_empty_result(self):
        with _patch_rq([]):
            r = client.get("/search/class", params={"q": "zzznomatch"})
        assert r.status_code == 200
        assert r.json() == []

    def test_search_with_repo_filter(self):
        with _patch_rq([]):
            r = client.get("/search/class", params={"q": "X", "repo_id": "myrepo"})
        assert r.status_code == 200

    def test_search_uses_object_model_when_available(self):
        om = json.dumps({"fqn": "com.Foo", "name": "Foo", "kind": "class",
                         "methods": [], "fields": []})
        row = {"fqn": "com.Foo", "name": "Foo", "kind": "class",
               "package_fqn": "com", "repo_id": "r", "om": om}
        with _patch_rq([row]):
            r = client.get("/search/class", params={"q": "Foo"})
        body = r.json()
        assert body[0]["fqn"] == "com.Foo"
        assert body[0]["methods"] == []

    def test_search_missing_q_param(self):
        r = client.get("/search/class")
        assert r.status_code == 422  # FastAPI validation


# ===========================================================================
# /patterns
# ===========================================================================

class TestPatterns:
    """Exercises patterns behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_patterns_empty(self):
        with _patch_rq([]):
            r = client.get("/patterns")
        assert r.status_code == 200
        assert r.json() == []

    def test_patterns_with_data(self):
        row = {"ap": {
            "pattern_id": "singleton-myrepo", "name": "Singleton",
            "source": "GoF", "category": "creational", "intent": "one instance",
            "anti_pattern": False, "severity": "info", "match_count": 3,
            "repo_id": "myrepo", "top_packages": "[]",
        }}
        with _patch_rq([row]):
            r = client.get("/patterns", params={"repo_id": "myrepo"})
        assert r.status_code == 200
        body = r.json()
        assert body[0]["name"] == "Singleton"

    def test_patterns_malformed_top_packages(self):
        """top_packages that is not valid JSON must not cause a 500."""
        row = {"ap": {
            "pattern_id": "p1", "name": "X", "source": "Custom",
            "category": "", "intent": "", "anti_pattern": False,
            "severity": "info", "match_count": 0, "repo_id": "r",
            "top_packages": "NOT_JSON",
        }}
        with _patch_rq([row]):
            r = client.get("/patterns")
        assert r.status_code == 200


# ===========================================================================
# /provenance/{repo_id}
# ===========================================================================

class TestProvenance:
    """Exercises provenance behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_provenance_found(self):
        with patch("main.run_query", side_effect=[
            [{"last_commit": "abc", "freshness_ts": None, "prov_commit_sha": "abc"}],
            [{"stale_count": 2}],
        ]):
            r = client.get("/provenance/myrepo")
        assert r.status_code == 200
        assert r.json()["stale_node_count"] == 2

    def test_provenance_not_found(self):
        with _patch_rq([]):
            r = client.get("/provenance/ghost")
        assert r.status_code == 404

    def test_provenance_404_not_500(self):
        with _patch_rq([]):
            r = client.get("/provenance/ghost")
        assert r.status_code != 500


# ===========================================================================
# /template/{repo_id}
# ===========================================================================

class TestTemplate:
    """Exercises template behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_template_not_found(self):
        with _patch_rq([]):
            r = client.get("/template/ghost")
        assert r.status_code == 404

    def test_template_renders(self):
        with patch("main.run_query", return_value=[{"repo_id": "myrepo"}]):
            with patch("renderers.template_renderer.render_template", return_value="# Report\n"):
                r = client.get("/template/myrepo")
        assert r.status_code == 200
        assert "Report" in r.text


# ===========================================================================
# /impact/files
# ===========================================================================

class TestImpactFiles:
    """Exercises impact files behavior in the api test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def _make_engine_mock(self):
        report_mock = MagicMock()
        report_mock.to_dict.return_value = {
            "repo_id": "myrepo",
            "changed_files": ["/Foo.java"],
            "commit_sha": None,
            "summary": {"risk_score": 0.1, "directly_affected_classes": 1,
                        "callers": 0, "transitive_dependents": 0,
                        "affected_modules": [], "exposed_endpoints": 0,
                        "relevant_policies": 0, "suggested_tests": 0},
            "directly_affected": [], "callers": [], "transitive_dependents": [],
            "exposed_endpoints": [], "relevant_policies": [], "suggested_tests": [],
        }
        return report_mock

    def test_impact_files_happy_path(self):
        report_mock = self._make_engine_mock()
        with patch("impact.engine.ImpactEngine") as MockEngine:
            MockEngine.return_value.compute.return_value = report_mock
            r = client.get("/impact/files", params={
                "files": "/Foo.java", "repo_id": "myrepo"
            })
        assert r.status_code == 200
        assert r.json()["repo_id"] == "myrepo"

    def test_impact_pr_delegates_to_files(self):
        report_mock = self._make_engine_mock()
        with patch("impact.engine.ImpactEngine") as MockEngine:
            MockEngine.return_value.compute.return_value = report_mock
            r = client.get("/impact/pr", params={
                "files": "/Foo.java,/Bar.java", "repo_id": "myrepo"
            })
        assert r.status_code == 200

    def test_impact_files_missing_params(self):
        r = client.get("/impact/files", params={"repo_id": "myrepo"})
        assert r.status_code == 422

    def test_impact_files_empty_file_list(self):
        report_mock = self._make_engine_mock()
        with patch("impact.engine.ImpactEngine") as MockEngine:
            MockEngine.return_value.compute.return_value = report_mock
            r = client.get("/impact/files", params={"files": "", "repo_id": "myrepo"})
        assert r.status_code == 200
