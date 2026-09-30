"""One-pass source-file discovery for repository scans.

Discovery used to be ~30 separate ``Path.rglob()`` passes whose results were
concatenated and only then filtered. Every pass walked the *whole* tree, including the
vendored and generated directories the filter was about to discard, so those were
traversed thirty times over.

On a Docker bind mount of a macOS home directory that is fatal rather than merely slow.
A scan of one 1.1M-inode checkout collected 724,304 paths in order to keep 115,274, and
never reached its first progress log: the container ran for twelve hours and then could
not be killed at all, because a process blocked in FUSE I/O does not take a signal. It
took the Docker daemon down with it.

So discovery is one pass now, and in a git repository the index *is* the answer.
``git ls-files`` returns exactly what the repository tracks, honours ``.gitignore`` for
free, and on the tree above answers in 0.02 s with 1,271 source files. The filesystem
walk remains for directories that are not repositories, and prunes as it descends
instead of filtering afterwards.
"""
from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable, Iterator
from pathlib import Path

try:  # the logger lives in the service images; tests may run without it
    from shared.codekg_logging.codekg_logger import get_logger
    log = get_logger(__name__, service="ingestion")
except Exception:  # pragma: no cover - logging is not what this module is for
    import logging

    class _Fallback:
        def __init__(self): self._l = logging.getLogger(__name__)
        def info(self, m, **k): self._l.info("%s %s", m, k)
        def warning(self, m, **k): self._l.warning("%s %s", m, k)
        def debug(self, m, **k): self._l.debug("%s %s", m, k)

    log = _Fallback()


#: Directories never worth descending into. Pruned during the walk, and also applied to
#: git's answer, because a repository can track a vendored tree.
#:
#: ``.claude`` earns its place the hard way: Claude Code keeps its worktrees there, each
#: a full checkout with its own ``node_modules`` and ``.venv``. In the scan that hung,
#: ``.claude`` held 1,048,822 of the tree's 1,125,799 files — 93% of everything walked.
SKIP_DIRS = frozenset({
    ".venv", "venv", "env", ".env",
    "node_modules", "__pycache__", ".git",
    "build", "dist", ".eggs", ".tox",
    "site-packages",
    ".gradle", ".mvn", "target",
    "out", "generated", "gen",
    ".claude", ".codekg",
    # git worktrees checked out inside the repo: full copies of the same code, so
    # indexing them duplicates every class under a path nobody edits.
    "worktrees", ".worktrees",
    ".idea", ".vscode",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".next", ".nuxt", ".parcel-cache", ".turbo",
    "coverage", "htmlcov",
})

def _configured_skip_dirs() -> frozenset[str]:
    """Extra directory names from `CODEKG_SKIP_DIRS`, comma-separated.

    So excluding a directory does not require editing this file.
    """
    raw = os.environ.get("CODEKG_SKIP_DIRS", "")
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


#: Beyond which `git ls-files` is assumed wedged and the walk takes over. Discovery that
#: cannot be interrupted is the failure this module exists to prevent, so it gets a clock.
GIT_TIMEOUT_SECONDS = 120


def _is_skipped(rel_parts: tuple[str, ...], skip: frozenset[str]) -> bool:
    return any(part in skip for part in rel_parts)


def _matches(name: str, suffixes: tuple[str, ...]) -> bool:
    """Suffix match on the whole name, case-insensitively.

    Not ``Path.suffix``: Salesforce metadata files are named ``*.js-meta.xml`` and
    friends, whose suffix is plain ``.xml``. Case folding reproduces what the old
    ``rglob`` did on a case-insensitive filesystem.
    """
    return name.lower().endswith(suffixes)


def _git_tracked_files(root: Path) -> list[str] | None:
    """Paths git knows about — tracked plus untracked-but-not-ignored — or None.

    ``--others --exclude-standard`` matters for a repository whose source has not been
    committed yet; without it a fresh checkout would index nothing and look healthy.
    """
    if not (root / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z",
             "--cached", "--others", "--exclude-standard"],
            capture_output=True, timeout=GIT_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("git ls-files unavailable — falling back to walk",
                    path=str(root), error=str(exc))
        return None
    if proc.returncode != 0:
        log.warning("git ls-files failed — falling back to walk",
                    path=str(root), returncode=proc.returncode)
        return None
    return [p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p]


def _walk_files(root: Path, skip: frozenset[str]) -> Iterable[tuple[str, ...]]:
    """Every file under `root`, as path parts relative to it, pruning as it descends."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in skip]
        rel = Path(dirpath).relative_to(root)
        prefix = rel.parts if str(rel) != "." else ()
        for name in filenames:
            yield prefix + (name,)


def iter_files(
    root: str | Path,
    *,
    suffixes: Iterable[str] = (),
    names: Iterable[str] = (),
    extra_skip_dirs: Iterable[str] = (),
) -> Iterator[Path]:
    """Files under `root` matching `suffixes` or `names`, yielded from a single pass.

    Match on either the end of the filename (`suffixes`) or the whole filename
    (`names`, for build files such as `build.gradle` or `CMakeLists.txt`). Callers own
    both, so the parsers stay the single source of truth for what they can read.

    A generator, so that "is there any file like this" costs one match rather than a
    full traversal — `any(d.rglob("*.py"))` looks cheap and is not.
    """
    root = Path(root)
    skip = SKIP_DIRS | _configured_skip_dirs() | frozenset(extra_skip_dirs)
    wanted_suffixes = tuple(sorted({s.lower() for s in suffixes}))
    wanted_names = frozenset(n.lower() for n in names)

    def _wanted(name: str) -> bool:
        lowered = name.lower()
        return (bool(wanted_suffixes) and lowered.endswith(wanted_suffixes)) \
            or lowered in wanted_names

    tracked = _git_tracked_files(root)
    if tracked is not None:
        for rel in tracked:
            parts = tuple(rel.split("/"))
            if _wanted(parts[-1]) and not _is_skipped(parts, skip):
                candidate = root / rel
                # git lists paths, not files: a tracked path can be deleted-but-unstaged.
                # Parsing that raises, so drop it here rather than downstream.
                if candidate.is_file():
                    yield candidate
    else:
        for parts in _walk_files(root, skip):
            if _wanted(parts[-1]):
                yield root.joinpath(*parts)


def has_any_file(root: str | Path, *, suffixes: Iterable[str] = (),
                 names: Iterable[str] = ()) -> bool:
    """Whether `root` contains any matching file, stopping at the first one."""
    return next(iter_files(root, suffixes=suffixes, names=names), None) is not None


def discover_source_files(
    root: str | Path,
    suffixes: Iterable[str],
    *,
    extra_skip_dirs: Iterable[str] = (),
) -> list[Path]:
    """Source files under `root` matching `suffixes`, in one pass."""
    root = Path(root)
    via = "git" if (root / ".git").exists() else "walk"
    files = list(iter_files(root, suffixes=suffixes, extra_skip_dirs=extra_skip_dirs))
    log.info("Source discovery complete", path=str(root), via=via, files=len(files))
    return files
