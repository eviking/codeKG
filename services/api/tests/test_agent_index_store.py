"""
Unit tests for services/api/agent_index/store.py.

Coverage scope:
  - init_db() creates both tables
  - upsert_file() creates new rows and updates on conflict
  - Status transitions: 'current' on first write, 'stale' when content changes post-publish
  - get_file() returns None for missing and dict for existing rows
  - list_files() returns rows from both tables
  - toggle_hidden() sets hidden flag correctly
  - update_manual_additions() returns True on success, False for unknown row
  - mark_published() sets published_at/sha on visible files only
  - mark_published() skips hidden files

All tests use an in-memory SQLite database via AGENT_INDEX_DB env var.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Point to a temp db before importing the module
os.environ["AGENT_INDEX_DB"] = ":memory:"
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

_SVC_ROOT = str(Path(__file__).parent.parent)
if _SVC_ROOT not in sys.path:
    sys.path.insert(0, _SVC_ROOT)

import pytest


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """
    Each test gets a fresh on-disk SQLite database so state does not leak
    between tests. Uses tmp_path to ensure cleanup.
    """
    db_path = str(tmp_path / "agent_index.db")
    os.environ["AGENT_INDEX_DB"] = db_path

    # Re-patch the module-level constant
    import agent_index.store as store
    store.AGENT_INDEX_DB = db_path

    store.init_db()
    yield store

    # Restore to avoid polluting other test modules
    os.environ["AGENT_INDEX_DB"] = ":memory:"


class TestInitDb:
    """Exercises init database behavior in the agent index store test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_creates_both_tables(self, fresh_db):
        """
        init_db() must create both agent_index_files and agent_index_module_files tables.
        Both tables are required for the full agent index functionality.
        """
        import sqlite3
        con = sqlite3.connect(fresh_db.AGENT_INDEX_DB)
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
        assert "agent_index_files" in tables
        assert "agent_index_module_files" in tables


class TestUpsertFile:
    """Exercises upsert file behavior in the agent index store test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_creates_new_row(self, fresh_db):
        """
        upsert_file() must insert a new row when the (repo_id, file_key) pair
        does not exist. get_file() should then return the row.
        """
        fresh_db.upsert_file(
            "repo1", "index", "", "INDEX.md", "Main index", "# Index", "any_change"
        )
        row = fresh_db.get_file("repo1", "index")
        assert row is not None
        assert row["filename"] == "INDEX.md"
        assert row["content"] == "# Index"

    def test_updates_on_conflict(self, fresh_db):
        """
        A second upsert_file() call with the same (repo_id, file_key) must update
        the content rather than inserting a duplicate. ON CONFLICT DO UPDATE is the
        mechanism for keeping index files current.
        """
        fresh_db.upsert_file("repo1", "index", "", "INDEX.md", "desc", "v1", "any_change")
        fresh_db.upsert_file("repo1", "index", "", "INDEX.md", "desc", "v2", "any_change")
        row = fresh_db.get_file("repo1", "index")
        assert row["content"] == "v2"

    def test_status_current_on_first_write(self, fresh_db):
        """
        The first upsert_file() for a file must set status='current' because no
        prior published state exists. Files are not stale until they've been
        published and then regenerated with different content.
        """
        fresh_db.upsert_file("repo1", "k", "", "f.md", "d", "content", "any")
        row = fresh_db.get_file("repo1", "k")
        assert row["status"] == "current"

    def test_status_stale_when_content_changes_after_publish(self, fresh_db):
        """
        If a file has been published and then regenerated with different content,
        status must be set to 'stale'. This signals to the console that the file
        needs re-publishing.
        """
        fresh_db.upsert_file("repo1", "k", "", "f.md", "d", "v1", "any")
        fresh_db.mark_published("repo1", sha="sha1")
        fresh_db.upsert_file("repo1", "k", "", "f.md", "d", "v2", "any")
        row = fresh_db.get_file("repo1", "k")
        assert row["status"] == "stale"

    def test_status_stays_current_when_content_unchanged(self, fresh_db):
        """
        Re-upserting a file with identical content after publish must NOT set it
        to stale — only content changes should trigger the stale transition.
        """
        fresh_db.upsert_file("repo1", "k", "", "f.md", "d", "same", "any")
        fresh_db.mark_published("repo1", sha="sha1")
        fresh_db.upsert_file("repo1", "k", "", "f.md", "d", "same", "any")
        row = fresh_db.get_file("repo1", "k")
        assert row["status"] == "current"


class TestGetFile:
    """Exercises get file behavior in the agent index store test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_returns_none_for_missing(self, fresh_db):
        """
        get_file() must return None when no row matches the given (repo_id, file_key).
        Callers use None to decide whether to insert vs update.
        """
        result = fresh_db.get_file("no-such-repo", "no-such-key")
        assert result is None

    def test_returns_dict_for_existing(self, fresh_db):
        """
        get_file() must return a dict (not a sqlite3.Row) for an existing file so
        callers can use standard dict operations without special handling.
        """
        fresh_db.upsert_file("repo1", "k", "dir", "f.md", "d", "c", "any")
        row = fresh_db.get_file("repo1", "k")
        assert isinstance(row, dict)
        assert row["directory"] == "dir"


class TestListFiles:
    """Exercises list files behavior in the agent index store test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_returns_rows_from_both_tables(self, fresh_db):
        """
        list_files() must return rows from both agent_index_files and
        agent_index_module_files. Both tables contribute to the full file listing
        shown in the console and consumed by agents.
        """
        fresh_db.upsert_file("repo1", "k1", "", "index.md", "d", "c", "any",
                              table="agent_index_files")
        fresh_db.upsert_file("repo1", "k2", "modules", "api.md", "d", "c", "any",
                              table="agent_index_module_files")
        files = fresh_db.list_files("repo1")
        keys = [f["file_key"] for f in files]
        assert "k1" in keys
        assert "k2" in keys


class TestToggleHidden:
    """Exercises toggle hidden behavior in the agent index store test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_sets_hidden_true(self, fresh_db):
        """
        toggle_hidden(..., hidden=True) must set the hidden column to 1.
        Hidden files are excluded from publishing and the agent listing.
        """
        fresh_db.upsert_file("repo1", "k", "", "f.md", "d", "c", "any")
        fresh_db.toggle_hidden("repo1", "k", hidden=True)
        row = fresh_db.get_file("repo1", "k")
        assert row["hidden"] == 1

    def test_sets_hidden_false(self, fresh_db):
        """
        toggle_hidden(..., hidden=False) must set hidden back to 0 so a previously
        hidden file can be re-exposed to agents.
        """
        fresh_db.upsert_file("repo1", "k", "", "f.md", "d", "c", "any")
        fresh_db.toggle_hidden("repo1", "k", hidden=True)
        fresh_db.toggle_hidden("repo1", "k", hidden=False)
        row = fresh_db.get_file("repo1", "k")
        assert row["hidden"] == 0


class TestUpdateManualAdditions:
    """Exercises update manual additions behavior in the agent index store test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_returns_true_on_success(self, fresh_db):
        """
        update_manual_additions() must return True when the row exists and the
        update succeeds. Returns value is used by the console to confirm the save.
        """
        fresh_db.upsert_file("repo1", "k", "", "f.md", "d", "c", "any")
        result = fresh_db.update_manual_additions("repo1", "k", "## Extra\n- note")
        assert result is True

    def test_returns_false_for_nonexistent_row(self, fresh_db):
        """
        update_manual_additions() must return False when no row matches the given
        (repo_id, file_key). The console uses this to show an error to the user.
        """
        result = fresh_db.update_manual_additions("no-repo", "no-key", "text")
        assert result is False


class TestMarkPublished:
    """Exercises mark published behavior in the agent index store test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_sets_published_at_and_sha(self, fresh_db):
        """
        mark_published() must set published_at and published_sha on visible files.
        These fields track which version of the file is currently live in the repo.
        """
        fresh_db.upsert_file("repo1", "k", "", "f.md", "d", "c", "any")
        fresh_db.mark_published("repo1", sha="abc123")
        row = fresh_db.get_file("repo1", "k")
        assert row["published_sha"] == "abc123"
        assert row["published_at"] is not None

    def test_does_not_update_hidden_files(self, fresh_db):
        """
        mark_published() must skip files with hidden=1. Hidden files are excluded
        from the published bundle and should not receive a published_at timestamp.
        """
        fresh_db.upsert_file("repo1", "hidden-key", "", "h.md", "d", "c", "any")
        fresh_db.toggle_hidden("repo1", "hidden-key", hidden=True)
        fresh_db.mark_published("repo1", sha="sha1")
        row = fresh_db.get_file("repo1", "hidden-key")
        assert row["published_at"] is None


class TestValidateTable:
    """Exercises validate table behavior in the agent index store test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_valid_tables_are_accepted(self, fresh_db):
        fresh_db._validate_table("agent_index_files")
        fresh_db._validate_table("agent_index_module_files")

    def test_invalid_table_raises_value_error(self, fresh_db):
        with pytest.raises(ValueError, match="Invalid table name"):
            fresh_db._validate_table("users")

    def test_sql_injection_attempt_raises(self, fresh_db):
        with pytest.raises(ValueError, match="Invalid table name"):
            fresh_db._validate_table("agent_index_files; DROP TABLE agent_index_files--")

    def test_upsert_rejects_invalid_table(self, fresh_db):
        with pytest.raises(ValueError):
            fresh_db.upsert_file("r", "k", "", "f.md", "d", "c", "any", table="evil")

    def test_get_file_rejects_invalid_table(self, fresh_db):
        with pytest.raises(ValueError):
            fresh_db.get_file("r", "k", table="evil")

    def test_toggle_hidden_rejects_invalid_table(self, fresh_db):
        with pytest.raises(ValueError):
            fresh_db.toggle_hidden("r", "k", hidden=True, table="evil")

    def test_update_manual_additions_rejects_invalid_table(self, fresh_db):
        with pytest.raises(ValueError):
            fresh_db.update_manual_additions("r", "k", "text", table="evil")
