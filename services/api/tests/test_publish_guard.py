"""Tests for the guard on what a publish is allowed to delete.

Publishing mirrors the store onto disk: anything not in the bundle is removed. That is
correct when the store is populated, and destructive when it is not. On 2026-09-28 a
store holding three entries — because a regen had never run to completion — deleted
sixteen of a repository's nineteen index files and committed the deletion to the branch
that happened to be checked out.
"""
from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

# Same bootstrap as test_api.py: env before import, and no real socket. REPOS_PATH is
# redirected because importing the app creates it.
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")
_TMP = tempfile.mkdtemp(prefix="codekg-test-repos-")
os.environ.setdefault("REPOS_PATH", _TMP)
os.environ.setdefault("AGENT_INDEX_DB", os.path.join(_TMP, "agent_index.db"))
os.environ.setdefault("TELEMETRY_DB", os.path.join(_TMP, "telemetry.db"))
os.environ.setdefault("AUDIT_DB_PATH", os.path.join(_TMP, "llm_audit.db"))

with patch("neo4j.GraphDatabase.driver", return_value=MagicMock()):
    sys.path.insert(0, str(__file__).replace("/tests/test_publish_guard.py", ""))
    from main import _expected_publish_paths, _publish_deletion_is_suspicious  # noqa: E402


class TestDeletionGuard:
    def test_deleting_nothing_is_never_suspicious(self):
        assert _publish_deletion_is_suspicious(0, 19) is False

    def test_a_half_populated_store_is_refused(self):
        """The incident: 3 files in the bundle, 19 on disk, 16 deletions."""
        assert _publish_deletion_is_suspicious(16, 19) is True

    def test_routine_removals_are_allowed(self):
        """A module disappears, an insights file empties — this must keep working."""
        assert _publish_deletion_is_suspicious(1, 19) is False
        assert _publish_deletion_is_suspicious(3, 19) is False

    def test_a_small_index_is_judged_by_the_floor_not_the_ratio(self):
        """With four files on disk, "half" is two — too tight to be a useful signal."""
        assert _publish_deletion_is_suspicious(2, 4) is False
        assert _publish_deletion_is_suspicious(4, 4) is True

    def test_an_empty_directory_does_not_divide_by_anything(self):
        """First publish into a repo with no .codekg/ at all."""
        assert _publish_deletion_is_suspicious(0, 0) is False


class TestExpectedPaths:
    def test_a_file_in_a_subdirectory_keeps_its_directory(self, tmp_path):
        visible = [{"file_key": "architecture/modules", "directory": "architecture",
                    "filename": "modules.md"}]
        assert _expected_publish_paths(visible, tmp_path) == {
            tmp_path / "architecture" / "modules.md"
        }

    def test_a_root_level_file_has_no_directory(self, tmp_path):
        visible = [{"file_key": "index", "directory": "", "filename": "INDEX.md"}]
        assert _expected_publish_paths(visible, tmp_path) == {tmp_path / "INDEX.md"}

    def test_claude_md_is_protected_from_the_sweep(self, tmp_path):
        """It is written to the repository root, but its `.codekg/` path must still be
        claimed — otherwise the sweep deletes the copy it just wrote."""
        visible = [{"file_key": "claude_md", "directory": "", "filename": "claude_md.md"},
                   {"file_key": "agents_md", "directory": "", "filename": "agents_md.md"}]
        assert _expected_publish_paths(visible, tmp_path) == {
            tmp_path / "CLAUDE.md", tmp_path / "AGENTS.md",
        }
