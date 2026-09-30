"""Tests for one-pass source discovery.

These exist because of a specific incident: a scan of a bind-mounted macOS home
directory collected 724,304 paths in order to keep 115,274, produced no progress log for
twelve hours, and ended as a container Docker could not kill. The cause was discovery
that walked the whole tree ~30 times and applied its exclusions only afterwards.

So the properties worth guarding are not "does it find files" but "does it avoid ever
looking at the directories it is about to discard", and "does it prefer git's answer".
"""
from __future__ import annotations

import os
import subprocess

import pytest

from shared import source_discovery
from shared.source_discovery import discover_source_files

PY = {".py"}


def _git(tmp_path, *args):
    subprocess.run(["git", "-C", str(tmp_path), *args],
                   check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """A real git repository — git's own behaviour is the thing under test."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    (tmp_path / "app.py").write_text("x = 1\n")
    vendor = tmp_path / "node_modules" / "pkg"
    vendor.mkdir(parents=True)
    (vendor / "index.py").write_text("vendored = True\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def test_a_gitignored_vendor_tree_is_not_indexed(repo):
    found = {p.name for p in discover_source_files(repo, PY)}
    assert found == {"app.py"}


def test_an_uncommitted_source_file_is_still_found(repo):
    """A fresh checkout whose work is not committed must not index as empty.

    `git ls-files --cached` alone would return nothing here and the scan would look
    perfectly healthy while indexing none of the code.
    """
    (repo / "new_feature.py").write_text("y = 2\n")
    found = {p.name for p in discover_source_files(repo, PY)}
    assert found == {"app.py", "new_feature.py"}


def test_a_tracked_file_deleted_from_disk_is_dropped(repo):
    """git still lists it; parsing it would raise."""
    (repo / "app.py").unlink()
    assert discover_source_files(repo, PY) == []


def test_a_vendored_tree_git_happens_to_track_is_still_skipped(repo):
    """`.gitignore` is not the only line of defence — a repo can commit node_modules."""
    tracked_vendor = repo / "node_modules" / "tracked.py"
    tracked_vendor.write_text("z = 3\n")
    _git(repo, "add", "-f", str(tracked_vendor))
    found = {p.name for p in discover_source_files(repo, PY)}
    assert found == {"app.py"}


def test_salesforce_metadata_matches_on_the_whole_name(tmp_path):
    """`Path.suffix` of `foo.js-meta.xml` is `.xml`, which would match nothing useful."""
    (tmp_path / "foo.js-meta.xml").write_text("<x/>")
    (tmp_path / "unrelated.xml").write_text("<y/>")
    found = {p.name for p in discover_source_files(tmp_path, {".js-meta.xml"})}
    assert found == {"foo.js-meta.xml"}


def test_matching_is_case_insensitive(tmp_path):
    """The old rglob ran on a case-insensitive filesystem and matched either way."""
    (tmp_path / "Loud.PY").write_text("x = 1\n")
    (tmp_path / "Perms.permissionset-meta.xml").write_text("<x/>")
    found = {p.name for p in discover_source_files(
        tmp_path, {".py", ".permissionSet-meta.xml"})}
    assert found == {"Loud.PY", "Perms.permissionset-meta.xml"}


def test_claude_worktrees_are_skipped_outside_git_too(tmp_path):
    """The 93% case, on the walk path.

    In the tree that hung, `.claude` held 1,048,822 of 1,125,799 files — Claude Code
    worktrees, each a full checkout with its own node_modules. Nothing in there is the
    repository being scanned.
    """
    (tmp_path / "real.py").write_text("x = 1\n")
    nested = tmp_path / ".claude" / "worktrees" / "copy" / "app"
    nested.mkdir(parents=True)
    (nested / "real.py").write_text("x = 1\n")

    found = discover_source_files(tmp_path, PY)

    assert [p.name for p in found] == ["real.py"]
    assert not any(".claude" in p.parts for p in found)


def test_the_walk_prunes_instead_of_filtering_afterwards(tmp_path, monkeypatch):
    """The actual fix, stated as a property.

    Collecting everything and filtering later gives the same file list — and still
    traverses the tree that must not be traversed. Only pruning during descent avoids
    the I/O, so assert on where the walk *went*, not on what it returned.
    """
    (tmp_path / "keep.py").write_text("x = 1\n")
    buried = tmp_path / "node_modules" / "a" / "b" / "c"
    buried.mkdir(parents=True)
    (buried / "deep.py").write_text("x = 1\n")

    visited: list[str] = []
    real_walk = os.walk

    def spy(top, **kwargs):
        # os.walk honours in-place mutation of `dirnames`, so yielding the very same
        # list keeps pruning working while recording every directory actually opened.
        for dirpath, dirnames, filenames in real_walk(top, **kwargs):
            visited.append(dirpath)
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(source_discovery.os, "walk", spy)

    found = discover_source_files(tmp_path, PY)

    assert [p.name for p in found] == ["keep.py"]
    assert not any("node_modules" in v for v in visited), (
        f"the walk descended into a skipped tree: {visited}"
    )


def test_a_broken_git_repo_falls_back_to_the_walk(tmp_path):
    """A `.git` that git refuses to read must not mean "this repo has no source"."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "app.py").write_text("x = 1\n")

    found = discover_source_files(tmp_path, PY)

    assert [p.name for p in found] == ["app.py"]


def test_git_is_preferred_over_the_walk(repo, monkeypatch):
    """Guards the ordering: the walk is the fallback, not the default."""
    def _no_walk(*a, **k):
        raise AssertionError("discovery walked a git repository instead of asking git")

    monkeypatch.setattr(source_discovery.os, "walk", _no_walk)
    assert {p.name for p in discover_source_files(repo, PY)} == {"app.py"}


def test_extra_skip_dirs_are_honoured(tmp_path):
    (tmp_path / "keep.py").write_text("x = 1\n")
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "sample.py").write_text("x = 1\n")

    found = discover_source_files(tmp_path, PY, extra_skip_dirs={"fixtures"})

    assert [p.name for p in found] == ["keep.py"]


def test_worktrees_checked_out_inside_the_repo_are_not_indexed(tmp_path):
    """A git worktree is a second copy of the same code, under a path nobody edits.

    Indexing it duplicates every class. In the checkout that hung, `worktrees/` and
    `.claude/worktrees/` together held over a million files.
    """
    (tmp_path / "real.py").write_text("x = 1\n")
    for holder in ("worktrees", ".claude/worktrees"):
        copy = tmp_path / holder / "branch-a" / "app"
        copy.mkdir(parents=True)
        (copy / "real.py").write_text("x = 1\n")

    found = discover_source_files(tmp_path, PY)

    assert [p.name for p in found] == ["real.py"]
    assert not any("worktrees" in p.parts for p in found)


def test_a_directory_can_be_excluded_without_editing_the_code(tmp_path, monkeypatch):
    """`CODEKG_SKIP_DIRS` — the answer to "can we leave this folder out of scope"."""
    (tmp_path / "keep.py").write_text("x = 1\n")
    (tmp_path / "scratch").mkdir()
    (tmp_path / "scratch" / "throwaway.py").write_text("x = 1\n")

    assert len(discover_source_files(tmp_path, PY)) == 2

    monkeypatch.setenv("CODEKG_SKIP_DIRS", " scratch , ")
    found = discover_source_files(tmp_path, PY)

    assert [p.name for p in found] == ["keep.py"]


def test_an_empty_skip_setting_excludes_nothing(tmp_path, monkeypatch):
    """A blank or comma-only value must not turn into a skip entry matching every dir."""
    (tmp_path / "keep.py").write_text("x = 1\n")
    monkeypatch.setenv("CODEKG_SKIP_DIRS", " , , ")

    assert [p.name for p in discover_source_files(tmp_path, PY)] == ["keep.py"]
