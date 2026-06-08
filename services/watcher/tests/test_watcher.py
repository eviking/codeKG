"""
Unit tests for the watcher service (services/watcher/main.py).

Coverage scope:
  - load_repos() from repos.json, from filesystem discovery, and empty fallback
  - _is_scan_running() based on Docker container label presence
  - _launch_scan() environment variables and volume binds
  - HOME_MOUNT volume binding when env var is set
  - Container labels for codekg.repo_id

All Docker SDK calls and httpx calls are mocked — no Docker daemon required.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# Set required env vars before importing the watcher module
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

_SVC_ROOT = str(Path(__file__).parent.parent)
if _SVC_ROOT not in sys.path:
    sys.path.insert(0, _SVC_ROOT)

import pytest

# ---------------------------------------------------------------------------
# We need to import main but patch docker.from_env at import time because
# the module-level constants reference cfg values, not docker directly.
# ---------------------------------------------------------------------------

with patch("docker.from_env", return_value=MagicMock()):
    import main as watcher_main


# ---------------------------------------------------------------------------
# load_repos() tests
# ---------------------------------------------------------------------------

class TestLoadRepos:
    """Exercises load repos behavior in the watcher test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_reads_from_repos_json(self, tmp_path):
        """
        When repos.json exists at REPOS_REGISTRY path, load_repos() should parse
        it and return the dict. This is the primary registry mechanism.
        """
        registry = tmp_path / "repos.json"
        registry.write_text(json.dumps({
            "my-repo": "/repos/my-repo",
            "other-repo": "/repos/other-repo",
        }))
        with patch.object(watcher_main, "REPOS_REGISTRY", str(registry)), \
             patch.object(watcher_main, "REPOS_PATH", str(tmp_path)):
            repos = watcher_main.load_repos()
        assert repos == {"my-repo": "/repos/my-repo", "other-repo": "/repos/other-repo"}

    def test_falls_back_to_filesystem_discovery(self, tmp_path):
        """
        When no repos.json exists, load_repos() should discover git repos by
        looking for directories containing a .git subdirectory under REPOS_PATH.
        """
        repo_dir = tmp_path / "discovered-repo"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()

        registry = tmp_path / "repos.json"  # does not exist
        with patch.object(watcher_main, "REPOS_REGISTRY", str(registry)), \
             patch.object(watcher_main, "REPOS_PATH", str(tmp_path)):
            repos = watcher_main.load_repos()
        assert "discovered-repo" in repos
        assert repos["discovered-repo"] == str(repo_dir)

    def test_returns_empty_when_neither_exists(self, tmp_path):
        """
        When neither repos.json exists nor any git repos are present, load_repos()
        must return an empty dict rather than crashing. The watcher should log a
        warning and wait for the next poll cycle.
        """
        registry = tmp_path / "repos.json"  # does not exist
        empty_repos = tmp_path / "repos"
        empty_repos.mkdir()
        with patch.object(watcher_main, "REPOS_REGISTRY", str(registry)), \
             patch.object(watcher_main, "REPOS_PATH", str(empty_repos)):
            repos = watcher_main.load_repos()
        assert repos == {}


# ---------------------------------------------------------------------------
# _is_scan_running() tests
# ---------------------------------------------------------------------------

class TestIsScanRunning:
    """Exercises is scan running behavior in the watcher test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_returns_false_when_no_matching_container(self):
        """
        _is_scan_running() should return False when Docker reports no containers
        with the codekg.repo_id label matching the given repo_id.
        This prevents launching duplicate scans only when one is actually running.
        """
        mock_client = MagicMock()
        mock_client.containers.list.return_value = []
        with patch("docker.from_env", return_value=mock_client):
            result = watcher_main._is_scan_running("my-repo")
        assert result is False
        mock_client.containers.list.assert_called_once_with(
            filters={"label": "codekg.repo_id=my-repo"}
        )

    def test_returns_true_when_matching_container_exists(self):
        """
        _is_scan_running() should return True when Docker lists at least one
        container with the matching codekg.repo_id label.
        """
        mock_client = MagicMock()
        mock_client.containers.list.return_value = [MagicMock()]
        with patch("docker.from_env", return_value=mock_client):
            result = watcher_main._is_scan_running("my-repo")
        assert result is True


# ---------------------------------------------------------------------------
# _launch_scan() tests
# ---------------------------------------------------------------------------

class TestLaunchScan:
    """Exercises launch scan behavior in the watcher test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def _make_client(self):
        client = MagicMock()
        client.containers.run.return_value = MagicMock()
        return client

    def test_passes_scan_env_vars(self):
        """
        _launch_scan() must pass SCAN_REPO_ID, SCAN_REPO_PATH, and SCAN_TYPE in
        the container environment dict. These are the primary inputs the ingestion
        container uses to know what to scan.
        """
        client = self._make_client()
        with patch("docker.from_env", return_value=client):
            watcher_main._launch_scan("my-repo", "/repos/my-repo", scan_type="full")

        _, kwargs = client.containers.run.call_args
        env = kwargs.get("environment") or client.containers.run.call_args[1].get("environment") or {}
        # Also check positional args
        if not env:
            args = client.containers.run.call_args[0]
            if len(args) > 1:
                env = args[1]

        call_kwargs = client.containers.run.call_args[1]
        env = call_kwargs.get("environment", {})
        assert env.get("SCAN_REPO_ID") == "my-repo"
        assert env.get("SCAN_REPO_PATH") == "/repos/my-repo"
        assert env.get("SCAN_TYPE") == "full"

    def test_home_mount_volume_added_when_set(self):
        """
        When HOME_MOUNT is configured, _launch_scan() must include it in the
        volumes dict bound to /host-home. This lets ingestion access user-level
        config files (e.g. ~/.m2, ~/.gradle) for dependency resolution.
        """
        client = self._make_client()
        with patch("docker.from_env", return_value=client), \
             patch.object(watcher_main, "HOME_MOUNT", "/home/testuser"):
            watcher_main._launch_scan("my-repo", "/repos/my-repo")

        call_kwargs = client.containers.run.call_args[1]
        volumes = call_kwargs.get("volumes", {})
        assert "/home/testuser" in volumes
        assert volumes["/home/testuser"]["bind"] == "/host-home"

    def test_container_labelled_with_repo_id(self):
        """
        The launched container must have a codekg.repo_id label set to the
        repo_id argument. This label is how _is_scan_running() detects overlap.
        """
        client = self._make_client()
        with patch("docker.from_env", return_value=client):
            watcher_main._launch_scan("my-repo", "/repos/my-repo")

        call_kwargs = client.containers.run.call_args[1]
        labels = call_kwargs.get("labels", {})
        assert labels.get("codekg.repo_id") == "my-repo"

    def test_incremental_scan_passes_commits(self):
        """
        For an incremental scan, _launch_scan() must pass SCAN_FROM_COMMIT and
        SCAN_TO_COMMIT in the environment so the ingestion container knows the
        range of commits to process.
        """
        client = self._make_client()
        with patch("docker.from_env", return_value=client):
            watcher_main._launch_scan(
                "my-repo", "/repos/my-repo",
                scan_type="incremental",
                from_commit="abc123",
                to_commit="def456",
            )

        call_kwargs = client.containers.run.call_args[1]
        env = call_kwargs.get("environment", {})
        assert env.get("SCAN_FROM_COMMIT") == "abc123"
        assert env.get("SCAN_TO_COMMIT") == "def456"
