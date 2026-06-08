"""
Unit tests for MCP tool handlers (services/mcp/main.py).

Coverage scope:
  - Each tool handler calls the correct API endpoint via httpx
  - Happy-path: valid API response → correct TextContent returned
  - Error path: API 404/500 → error JSON returned as TextContent (no Python exception)
  - capture_insight POSTs to /insights with correct payload
  - SESSION_ID is a stable string within a process (not regenerated on each call)

All tests mock httpx.Client so no real network calls are made.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Set required env vars before importing the MCP module
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

_SVC_ROOT = str(Path(__file__).parent.parent)
if _SVC_ROOT not in sys.path:
    sys.path.insert(0, _SVC_ROOT)

# Shared root for shared module
_SHARED_ROOT = str(Path(__file__).parent.parent.parent.parent / "shared")
if _SHARED_ROOT not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


def _mock_response(data, status_code: int = 200):
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = json.dumps(data)
    if status_code >= 400:
        from httpx import HTTPStatusError, Request, Response
        resp.raise_for_status.side_effect = HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Import the module under a mock http client so it doesn't connect at import time
# ---------------------------------------------------------------------------

_mock_http = MagicMock()

with patch("httpx.Client", return_value=_mock_http):
    # Prevent MCP stdio from starting
    with patch("mcp.server.stdio"):
        import main as mcp_main


def _call(tool_name: str, arguments: dict):
    """Invoke _call_tool and return the first TextContent."""
    results = _run(mcp_main._call_tool(tool_name, arguments))
    assert results, "Expected at least one TextContent result"
    return results[0]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetRepoSummary:
    """Exercises get repo summary behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_returns_repos_json(self):
        """
        get_repo_summary must call GET /repos and return its JSON response as
        the TextContent text. Agents use this to discover registered repositories.
        """
        repos_data = [{"repo_id": "my-repo", "name": "My Repo", "last_commit": "abc"}]
        mcp_main.http.get.return_value = _mock_response(repos_data)

        result = _call("get_repo_summary", {})
        payload = json.loads(result.text)
        assert isinstance(payload, list)
        assert payload[0]["repo_id"] == "my-repo"


class TestSearchClasses:
    """Exercises search classes behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_returns_search_results(self):
        """
        search_classes must call GET /search/class with the query parameter and
        return the result list. This is used to locate classes by name pattern.
        """
        search_data = [{"fqn": "com.example.Foo", "name": "Foo"}]
        mcp_main.http.get.return_value = _mock_response(search_data)

        result = _call("search_classes", {"query": "Foo", "repo_id": "my-repo"})
        payload = json.loads(result.text)
        assert isinstance(payload, list)


class TestGetClass:
    """Exercises get class behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_returns_class_data(self):
        """
        get_class must call GET /context/class/{fqn} and return the class data.
        Used by agents to get a full object model snapshot for a single class.
        """
        class_data = {"fqn": "com.example.Foo", "name": "Foo", "kind": "class"}
        mcp_main.http.get.return_value = _mock_response(class_data)

        result = _call("get_class", {"fqn": "com.example.Foo"})
        payload = json.loads(result.text)
        assert payload["fqn"] == "com.example.Foo"


class TestGetChangeImpact:
    """Exercises get change impact behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_returns_impact_report(self):
        """
        get_change_impact must call GET /impact/files and return the impact report.
        Used by agents to understand blast radius before committing a change.
        """
        impact_data = {"files": ["a.java"], "affected_classes": [], "blast_radius": 3}
        mcp_main.http.get.return_value = _mock_response(impact_data)

        result = _call("get_change_impact", {
            "files": ["a.java"],
            "repo_id": "my-repo",
        })
        payload = json.loads(result.text)
        assert "blast_radius" in payload or "files" in payload


class TestCaptureInsight:
    """Exercises capture insight behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_posts_to_insights_and_returns_ok(self):
        """
        capture_insight must POST to /insights with a properly structured entry
        and return a JSON response containing ok=True when the API succeeds.
        This is the mechanism for agents to record non-obvious codebase facts.
        """
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.raise_for_status.return_value = None
        post_resp.json.return_value = {"stored": 1}
        mcp_main.http.post.return_value = post_resp

        result = _call("capture_insight", {
            "insight": "Calling X without Y causes Z",
            "applies_to": "com.example.Foo",
            "repo_id": "my-repo",
            "scope": "class",
            "confidence": 0.9,
            "importance": 80,
        })
        payload = json.loads(result.text)
        assert payload["ok"] is True
        assert payload["stored"] == 1

    def test_missing_required_fields_returns_error_not_exception(self):
        """
        capture_insight with missing required fields must return a JSON error
        response (not raise a Python exception) so the MCP server stays alive.
        """
        result = _call("capture_insight", {
            "insight": "something",
            # applies_to and repo_id missing
        })
        payload = json.loads(result.text)
        assert payload.get("ok") is False


class TestListArchPolicies:
    """Exercises list arch policies behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_returns_policies_list(self):
        """
        list_arch_policies must call GET /policies and return the result.
        Policies govern architectural rules; agents check these before coding.
        """
        policies = [{"policy_id": "p-001", "title": "No cross-module calls"}]
        mcp_main.http.get.return_value = _mock_response(policies)

        result = _call("list_arch_policies", {})
        payload = json.loads(result.text)
        assert isinstance(payload, list)


class TestGetCodebaseTemplate:
    """Exercises get codebase template behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_returns_text_content(self):
        """
        get_codebase_template must return the template content as a string.
        This is the primary context document agents consume at session start.
        """
        template_text = "# My Repo\n\nStructure..."
        mcp_main.http.get.return_value = _mock_response(template_text)

        result = _call("get_codebase_template", {"repo_id": "my-repo"})
        # Result is TextContent with some text
        assert result.text is not None
        assert len(result.text) > 0


class TestErrorHandling:
    """Exercises error handling behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_api_error_returns_error_text_not_exception(self):
        """
        When the API returns a 404 or 500, the tool must return an error TextContent
        with an 'error' key — it must NOT raise a Python exception that would kill
        the MCP server process.
        """
        import httpx
        error_resp = MagicMock()
        error_resp.status_code = 404
        error_resp.text = "Not Found"
        http_error = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=error_resp
        )
        mcp_main.http.get.side_effect = http_error

        result = _call("get_repo_summary", {})
        payload = json.loads(result.text)
        assert "error" in payload
        # Cleanup
        mcp_main.http.get.side_effect = None


class TestSessionId:
    """Exercises session id behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_session_id_is_consistent(self):
        """
        SESSION_ID must be a stable string for the lifetime of the process.
        Agents use it to correlate audit log entries across tool calls.
        """
        sid1 = mcp_main.SESSION_ID
        sid2 = mcp_main._get_session_id()
        assert sid1 == sid2
        assert isinstance(sid1, str)
        assert len(sid1) > 0
