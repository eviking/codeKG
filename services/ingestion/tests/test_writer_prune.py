"""Tests for pruning nodes that a full scan no longer sees.

Every writer method MERGEs, so the graph never forgets. A file deleted, renamed, or
newly excluded from the scan keeps its classes indefinitely — carrying the commit SHA of
whichever scan last saw them — and they go on being served as part of the codebase. This
was first noticed on a directory entry that survived three scans after being excluded.

The dangerous half is the guard: the same query, handed an empty or partial keep set,
deletes the repository.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from kg.writer import KGWriter


def _writer_with_result(removed: int):
    """A KGWriter wired to a driver that records queries instead of running them."""
    session = MagicMock()
    session.run.return_value.single.return_value = {"removed": removed}
    driver = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    w = KGWriter.__new__(KGWriter)   # bypass __init__ — it opens a connection
    w._driver = driver
    return w, session


class TestPruneFiles:
    def test_it_keeps_the_files_the_scan_saw(self):
        w, session = _writer_with_result(4)

        removed = w.prune_files_not_in("r", ["/repo/a.py", "/repo/b.py"])

        assert removed == 4
        _, kwargs = session.run.call_args
        assert kwargs["keep"] == ["/repo/a.py", "/repo/b.py"]
        assert kwargs["repo_id"] == "r"

    def test_an_empty_keep_set_deletes_nothing(self):
        """A scan that found no files is a broken scan, not an empty repository.

        Without this the first failed discovery would empty the graph — and the next
        query against it would look like the repository had vanished.
        """
        w, session = _writer_with_result(999)

        assert w.prune_files_not_in("r", []) == 0
        session.run.assert_not_called()

    def test_a_generator_keep_set_is_materialised_before_the_emptiness_check(self):
        """`if not keep` on a generator is always False — it would defeat the guard."""
        w, session = _writer_with_result(0)

        assert w.prune_files_not_in("r", (p for p in [])) == 0
        session.run.assert_not_called()

    def test_methods_hanging_off_a_removed_class_go_with_it(self):
        """Method nodes carry no file_path, so deleting only the class orphans them."""
        w, session = _writer_with_result(1)

        w.prune_files_not_in("r", ["/repo/a.py"])

        cypher = session.run.call_args[0][0]
        assert "HAS_METHOD" in cypher
        assert "DETACH DELETE n, m" in cypher


class TestPruneModules:
    def test_it_removes_modules_the_scan_no_longer_discovers(self):
        w, session = _writer_with_result(2)

        assert w.prune_modules_not_in("r", ["app", "app/api"]) == 2
        assert session.run.call_args[1]["keep"] == ["app", "app/api"]

    def test_an_empty_keep_set_deletes_nothing(self):
        w, session = _writer_with_result(999)

        assert w.prune_modules_not_in("r", []) == 0
        session.run.assert_not_called()
