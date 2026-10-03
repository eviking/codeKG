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


def _writer_scripted(present, removed: int = 0):
    """A KGWriter whose driver answers the two prune queries from a script.

    First call is the DISTINCT read of what the graph holds; second, if it happens, is
    the delete. Recording both is how a test can assert that the delete is not issued
    when there is nothing to delete.
    """
    calls: list[tuple] = []

    def _run(cypher, **kwargs):
        calls.append((cypher, kwargs))
        result = MagicMock()
        if "RETURN DISTINCT" in cypher:
            result.__iter__ = lambda _self: iter([{"p": p} for p in present])
        else:
            result.single.return_value = {"removed": removed}
        return result

    session = MagicMock()
    session.run.side_effect = _run
    driver = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    w = KGWriter.__new__(KGWriter)   # bypass __init__ — it opens a connection
    w._driver = driver
    return w, calls


class TestPruneFiles:
    def test_it_deletes_only_the_paths_the_scan_did_not_see(self):
        w, calls = _writer_scripted(["/repo/a.py", "/repo/gone.py"], removed=1)

        removed = w.prune_files_not_in("r", ["/repo/a.py"])

        assert removed == 1
        delete = [c for c in calls if "DETACH DELETE" in c[0]]
        assert len(delete) == 1
        assert delete[0][1]["stale"] == ["/repo/gone.py"]

    def test_nothing_stale_issues_no_delete_at_all(self):
        """The common case. A scan where nothing moved must not write to the graph."""
        w, calls = _writer_scripted(["/repo/a.py", "/repo/b.py"])

        assert w.prune_files_not_in("r", ["/repo/a.py", "/repo/b.py"]) == 0
        assert not any("DETACH DELETE" in c[0] for c in calls)

    def test_the_keep_list_is_never_sent_to_the_database(self):
        """The old query shipped the whole keep set and tested it per node — a nested
        loop over 28,431 nodes and 1,783 paths. The difference belongs in Python."""
        w, calls = _writer_scripted(["/repo/a.py"])

        w.prune_files_not_in("r", ["/repo/a.py"])

        assert not any("keep" in kwargs for _cypher, kwargs in calls)

    def test_an_empty_keep_set_deletes_nothing(self):
        """A scan that found no files is a broken scan, not an empty repository.

        Without this the first failed discovery would empty the graph — and the next
        query against it would look like the repository had vanished.
        """
        w, calls = _writer_scripted(["/repo/a.py"], removed=999)

        assert w.prune_files_not_in("r", []) == 0
        assert calls == []

    def test_a_generator_keep_set_is_materialised_before_the_emptiness_check(self):
        """`if not keep` on a generator is always False — it would defeat the guard."""
        w, calls = _writer_scripted(["/repo/a.py"])

        assert w.prune_files_not_in("r", (p for p in [])) == 0
        assert calls == []

    def test_methods_hanging_off_a_removed_class_go_with_it(self):
        """Method nodes carry no file_path, so deleting only the class orphans them."""
        w, calls = _writer_scripted(["/repo/gone.py"], removed=1)

        w.prune_files_not_in("r", ["/repo/a.py"])

        cypher = next(c[0] for c in calls if "DETACH DELETE" in c[0])
        assert "HAS_METHOD" in cypher
        assert "DETACH DELETE n, m" in cypher


def _writer_single_query(removed: int):
    """For `prune_modules_not_in`, which is still one query — unchanged by this work."""
    session = MagicMock()
    session.run.return_value.single.return_value = {"removed": removed}
    driver = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    w = KGWriter.__new__(KGWriter)
    w._driver = driver
    return w, session


class TestPruneModules:
    def test_it_removes_modules_the_scan_no_longer_discovers(self):
        w, session = _writer_single_query(2)

        assert w.prune_modules_not_in("r", ["app", "app/api"]) == 2
        assert session.run.call_args[1]["keep"] == ["app", "app/api"]

    def test_an_empty_keep_set_deletes_nothing(self):
        w, session = _writer_single_query(999)

        assert w.prune_modules_not_in("r", []) == 0
        session.run.assert_not_called()
