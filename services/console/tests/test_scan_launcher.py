"""
Unit tests for services/console/scan_launcher.py.

Coverage scope:
  - launch_scan() passes SCAN_REPO_ID and SCAN_REPO_PATH to container env
  - launch_scan() uses INGESTION_IMAGE from config
  - launch_scan() passes HOME_MOUNT as a volume bind when set
  - launch_scan() labels the container with codekg.repo_id for overlap detection
  - cancel_scan() calls container.stop() on the matching container
  - cancel_scan() is a no-op when no matching container is running

All Docker SDK calls are mocked — no Docker daemon required.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import threading

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

_CONSOLE_ROOT = str(Path(__file__).parent.parent)
if _CONSOLE_ROOT not in sys.path:
    sys.path.insert(0, _CONSOLE_ROOT)

_SHARED_ROOT = str(Path(__file__).parent.parent.parent.parent)
if _SHARED_ROOT not in sys.path:
    sys.path.insert(0, _SHARED_ROOT)

import pytest


@pytest.fixture()
def launcher(tmp_path):
    """Import scan_launcher with a temp scan_log.db to avoid filesystem pollution."""
    with patch("docker.from_env", return_value=MagicMock()):
        import scan_launcher
    scan_launcher._SCAN_LOG_DB = tmp_path / "scan_log.db"
    return scan_launcher


def _make_docker_client():
    """Create a mock docker client whose containers.run returns a container mock."""
    client = MagicMock()
    container = MagicMock()
    container.id = "abc123def456"
    container.short_id = "abc123"
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b"ok"
    client.containers.run.return_value = container
    return client, container


class TestLaunchScan:
    """Exercises launch scan behavior in the scan launcher test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_passes_scan_repo_id_and_path(self, launcher, tmp_path):
        """
        launch_scan() must include SCAN_REPO_ID and SCAN_REPO_PATH in the container
        environment. These are the primary inputs that tell the ingestion container
        which repo to process and where it lives on disk.
        """
        client, container = _make_docker_client()
        with patch("docker.from_env", return_value=client), \
             patch.object(launcher, "_SCAN_LOG_DB", tmp_path / "scan_log.db"), \
             patch("threading.Thread"):
            launcher.launch_scan("my-repo", "/repos/my-repo")

        call_kwargs = client.containers.run.call_args[1]
        env = call_kwargs.get("environment", {})
        assert env.get("SCAN_REPO_ID") == "my-repo"
        assert env.get("SCAN_REPO_PATH") == "/repos/my-repo"

    def test_uses_ingestion_image_from_config(self, launcher, tmp_path):
        """
        launch_scan() must use the INGESTION_IMAGE configured in cfg.ingestion.
        This image name is set by operators and must be forwarded exactly.
        """
        client, _ = _make_docker_client()
        with patch("docker.from_env", return_value=client), \
             patch.object(launcher, "INGESTION_IMAGE", "my-custom-image:v2"), \
             patch("threading.Thread"):
            launcher.launch_scan("my-repo", "/repos/my-repo")

        positional_args = client.containers.run.call_args[0]
        image_arg = positional_args[0] if positional_args else client.containers.run.call_args[1].get("image")
        assert image_arg == "my-custom-image:v2"

    def test_home_mount_added_as_volume(self, launcher, tmp_path):
        """
        When HOME_MOUNT is set, launch_scan() must include it in the volumes dict
        bound to /host-home. This gives ingestion access to user-level tooling
        such as ~/.m2 Maven cache or ~/.gradle.
        """
        client, _ = _make_docker_client()
        with patch("docker.from_env", return_value=client), \
             patch.object(launcher, "HOME_MOUNT", "/home/testuser"), \
             patch("threading.Thread"):
            launcher.launch_scan("my-repo", "/repos/my-repo")

        call_kwargs = client.containers.run.call_args[1]
        volumes = call_kwargs.get("volumes", {})
        assert "/home/testuser" in volumes
        assert volumes["/home/testuser"]["bind"] == "/host-home"

    def test_container_labelled_with_repo_id(self, launcher, tmp_path):
        """
        The launched container must have a 'codekg.repo_id' label matching the
        repo_id argument. This label enables _is_scan_running() and cancel_scan()
        to find the container without storing its ID externally.
        """
        client, _ = _make_docker_client()
        with patch("docker.from_env", return_value=client), \
             patch("threading.Thread"):
            launcher.launch_scan("my-repo", "/repos/my-repo")

        call_kwargs = client.containers.run.call_args[1]
        labels = call_kwargs.get("labels", {})
        assert labels.get("codekg.repo_id") == "my-repo"

    def test_incremental_scan_type_passed(self, launcher, tmp_path):
        """
        An incremental scan must set SCAN_TYPE=incremental in the environment
        so the ingestion container knows to perform a diff-based update.
        """
        client, _ = _make_docker_client()
        with patch("docker.from_env", return_value=client), \
             patch("threading.Thread"):
            launcher.launch_scan("my-repo", "/repos/my-repo", scan_type="incremental",
                                 from_commit="abc", to_commit="def")

        call_kwargs = client.containers.run.call_args[1]
        env = call_kwargs.get("environment", {})
        assert env.get("SCAN_TYPE") == "incremental"


class TestCancelScan:
    """Exercises cancel scan behavior in the scan launcher test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_stops_matching_container(self, launcher):
        """
        cancel_scan() must call container.stop() on every container matching the
        codekg.repo_id label. This is the primary mechanism for aborting a stuck scan.
        """
        container = MagicMock()
        client = MagicMock()
        client.containers.list.return_value = [container]

        with patch("docker.from_env", return_value=client):
            result = launcher.cancel_scan("my-repo")

        container.stop.assert_called_once()
        assert result is True

    def test_noop_when_no_container_running(self, launcher):
        """
        cancel_scan() must return False and call no stop() when no container with
        the codekg.repo_id label is running. This is not an error condition.
        """
        client = MagicMock()
        client.containers.list.return_value = []

        with patch("docker.from_env", return_value=client):
            result = launcher.cancel_scan("my-repo")

        assert result is False
