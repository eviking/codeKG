#!/usr/bin/env python3
"""
Backfill commit impact analyses for every commit in the codeKG repo.

Reads the git log, diffs each commit against its parent, runs lightweight
Cypher impact queries against the running Neo4j, and writes results to
commit_impact.db on the /repos volume.

Usage (from repo root):
    python3 tools/backfill_commit_impact.py

Requires:
    pip install neo4j gitpython
"""
from __future__ import annotations

import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
REPO_PATH   = str(Path(__file__).parent.parent.resolve())
REPO_ID     = "codeKG"
DB_PATH     = Path(REPO_PATH) / "repos" / "commit_impact.db"

# The KG was first scanned when the repo was named codeKG (capital K+G).
# All stored file_path values use that capitalisation — override it here.
KG_REPO_NAME = "codeKG"   # name as it appears in KG file paths
NEO4J_URI   = os.environ.get("NEO4J_URI",  "bolt://localhost:7687")
NEO4J_USER  = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASS  = os.environ.get("NEO4J_PASSWORD", "codekg_pass")
MAX_NODES   = 50

# The KG stores file paths using the container mount prefix /host-home/...
# Map host path → container path so Cypher file_path lookups match.
HOST_HOME        = str(Path.home())     # e.g. /Users/jensschutt
CONTAINER_PREFIX = "/host-home"         # how the host home appears inside the container

# Path translation is needed for Cypher lookups but NOT for git diff
# (git diff runs against the actual host repo path).

def _to_kg_path(host_path: str) -> str:
    """Convert a host absolute path to the path stored in the KG.
    Also fixes the repo folder name case (codekg → codeKG on macOS case-insensitive FS).
    """
    p = host_path
    if p.startswith(HOST_HOME):
        p = CONTAINER_PREFIX + p[len(HOST_HOME):]
    # Fix case: replace the lowercase repo folder name with the KG version
    repo_lower = Path(REPO_PATH).name          # e.g. "codekg"
    if repo_lower != KG_REPO_NAME:
        p = p.replace("/" + repo_lower + "/", "/" + KG_REPO_NAME + "/", 1)
        if p.endswith("/" + repo_lower):
            p = p[:-len(repo_lower)] + KG_REPO_NAME
    return p

# Add shared/ and repo root to path
sys.path.insert(0, str(Path(REPO_PATH) / "shared"))
sys.path.insert(0, str(Path(REPO_PATH)))


def _init_db(db_path: Path) -> None:
    with sqlite3.connect(str(db_path)) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS commit_analyses (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id       TEXT    NOT NULL,
                commit_sha    TEXT    NOT NULL,
                parent_sha    TEXT,
                committed_at  TEXT,
                author        TEXT,
                message       TEXT,
                changed_files TEXT,
                impact_json   TEXT    NOT NULL,
                risk_score    REAL    NOT NULL DEFAULT 0.0,
                total_affected INTEGER NOT NULL DEFAULT 0,
                security_score REAL   NOT NULL DEFAULT 0.0,
                availability_score REAL NOT NULL DEFAULT 0.0,
                performance_score  REAL NOT NULL DEFAULT 0.0,
                observability_score REAL NOT NULL DEFAULT 0.0,
                ops_score      REAL   NOT NULL DEFAULT 0.0,
                deps_score     REAL   NOT NULL DEFAULT 0.0,
                created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        c.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_commit
            ON commit_analyses(repo_id, commit_sha)
        """)


def _upsert(db_path: Path, row: dict) -> None:
    with sqlite3.connect(str(db_path)) as c:
        c.execute("""
            INSERT INTO commit_analyses
              (repo_id, commit_sha, parent_sha, committed_at, author, message,
               changed_files, impact_json, risk_score, total_affected,
               security_score, availability_score, performance_score,
               observability_score, ops_score, deps_score)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(repo_id, commit_sha) DO UPDATE SET
              impact_json        = excluded.impact_json,
              risk_score         = excluded.risk_score,
              total_affected     = excluded.total_affected,
              security_score     = excluded.security_score,
              availability_score = excluded.availability_score,
              performance_score  = excluded.performance_score,
              observability_score = excluded.observability_score,
              ops_score          = excluded.ops_score,
              deps_score         = excluded.deps_score,
              created_at         = excluded.created_at
        """, (
            row["repo_id"], row["commit_sha"], row["parent_sha"],
            row["committed_at"], row["author"], row["message"],
            json.dumps(row["changed_files"]), json.dumps(row["impact"]),
            row["risk_score"], row["total_affected"],
            row["security_score"], row["availability_score"],
            row["performance_score"], row["observability_score"],
            row["ops_score"], row["deps_score"],
        ))


def _analyse(driver, repo_id: str, commit_sha: str, parent_sha: str | None,
             kg_files: list[str], repo_path: str) -> tuple[dict, dict]:
    """Run graph traversals + diff signals. Returns (impact dict, scores dict)."""
    import subprocess
    from impact_config import load_config as _load_impact_config
    from impact_scorer import score_all_vectors as _score_all_vectors

    def run(cypher: str, **params) -> list[dict]:
        with driver.session() as s:
            return [dict(r) for r in s.run(cypher, **params)]

    # ── Graph traversals ──────────────────────────────────────────────────────
    direct = run(
        """
        MATCH (c) WHERE c.file_path IN $files AND c.repo_id = $repo_id
          AND (c:Class OR c:Interface OR c:Enum)
        RETURN c.fqn AS fqn, c.name AS name,
               coalesce(c.kind,'class') AS kind,
               c.file_path AS file_path, c.module AS module
        ORDER BY c.fqn LIMIT $lim
        """,
        files=kg_files, repo_id=repo_id, lim=MAX_NODES,
    )
    direct_fqns = [r["fqn"] for r in direct]

    callers = run(
        """
        MATCH (caller:Method)-[:CALLS]->(callee:Method)
        WHERE callee.class_fqn IN $fqns
        MATCH (callerClass)-[:CONTAINS]->(caller)
        WHERE NOT callerClass.fqn IN $fqns
        RETURN DISTINCT callerClass.fqn AS fqn, callerClass.name AS name,
               coalesce(callerClass.kind,'class') AS kind,
               callerClass.file_path AS file_path, callerClass.module AS module
        LIMIT $lim
        """,
        fqns=direct_fqns, lim=MAX_NODES,
    ) if direct_fqns else []

    transitive = run(
        """
        MATCH path = (dep)-[:IMPORTS*1..2]->(affected)
        WHERE affected.fqn IN $fqns AND NOT dep.fqn IN $fqns
          AND (dep:Class OR dep:Interface)
        RETURN DISTINCT dep.fqn AS fqn, dep.name AS name,
               coalesce(dep.kind,'class') AS kind,
               dep.file_path AS file_path, dep.module AS module,
               length(path) AS hops
        ORDER BY hops, dep.fqn LIMIT $lim
        """,
        fqns=direct_fqns, lim=MAX_NODES,
    ) if direct_fqns else []

    endpoints = run(
        """
        MATCH (ep:ApiEndpoint)-[:HANDLED_BY]->(c:Class)
        WHERE c.fqn IN $fqns
        RETURN ep.endpoint_id AS endpoint_id,
               ep.http_method AS http_method, ep.path AS path,
               c.fqn AS handler_class
        LIMIT $lim
        """,
        fqns=direct_fqns, lim=MAX_NODES,
    ) if direct_fqns else []

    all_modules = list({
        r["module"] for r in direct + callers + transitive if r.get("module")
    })
    policies = run(
        """
        MATCH (ap:ArchPolicy)-[:TARGETS]->(mod:Module)
        WHERE mod.module_id IN $modules AND ap.status = 'active'
        RETURN ap.policy_id AS policy_id, ap.title AS title,
               ap.natural_language AS natural_language, ap.severity AS severity
        LIMIT 20
        """,
        modules=all_modules,
    ) if all_modules else []

    names = [r["name"] for r in direct if r.get("name")]
    tests = run(
        """
        MATCH (c:Class {repo_id: $repo_id})
        WHERE c.role = 'TEST' AND any(n IN $names WHERE c.name CONTAINS n)
        RETURN c.fqn AS fqn, c.name AS name, c.file_path AS file_path
        LIMIT 20
        """,
        repo_id=repo_id, names=names,
    ) if names else []

    graph = {
        "direct":     direct,
        "callers":    callers,
        "transitive": transitive,
        "endpoints":  endpoints,
        "policies":   policies,
        "tests":      tests,
    }

    # ── Git diff lines (against actual host path, not KG path) ───────────────
    diff_lines: list[str] = []
    try:
        if parent_sha:
            result = subprocess.run(
                ["git", "-C", repo_path, "diff", "--unified=3", parent_sha, commit_sha],
                capture_output=True, text=True, timeout=60,
            )
        else:
            result = subprocess.run(
                ["git", "-C", repo_path, "show", "--unified=3", "--format=", commit_sha],
                capture_output=True, text=True, timeout=60,
            )
        if result.returncode in (0, 1):
            diff_lines = result.stdout.splitlines()
    except Exception as e:
        print(f"  [warn] diff failed: {e}")

    # ── Score using config + signals ──────────────────────────────────────────
    impact_cfg = _load_impact_config(repo_path)
    scores_dict = _score_all_vectors(diff_lines, graph, impact_cfg)

    impact = {
        "repo_id":      repo_id,
        "changed_files": kg_files,
        "commit_sha":   commit_sha,
        "summary": {
            "directly_affected_classes": len(direct),
            "callers":                   len(callers),
            "transitive_dependents":     len(transitive),
            "affected_modules":          all_modules,
            "exposed_endpoints":         len(endpoints),
            "relevant_policies":         len(policies),
            "suggested_tests":           len(tests),
            "risk_score":                scores_dict["risk_score"],
        },
        "directly_affected":     direct,
        "callers":               callers,
        "transitive_dependents": [
            {**r, "hop_distance": r.get("hops", 1), "reason": "transitive-import"}
            for r in transitive
        ],
        "exposed_endpoints":  endpoints,
        "relevant_policies":  policies,
        "suggested_tests":    [{**r, "reason": "name match with changed class"} for r in tests],
        "signals":            scores_dict.get("signals", {}),
    }

    return impact, scores_dict


def main():
    try:
        import git
        from neo4j import GraphDatabase
    except ImportError:
        print("ERROR: pip install neo4j gitpython")
        sys.exit(1)

    print(f"Connecting to Neo4j at {NEO4J_URI} …")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        driver.verify_connectivity()
    except Exception as e:
        print(f"ERROR: Cannot connect to Neo4j: {e}")
        sys.exit(1)

    print(f"Opening repo at {REPO_PATH} …")
    repo = git.Repo(REPO_PATH)

    # Collect all commits oldest → newest
    commits = list(reversed(list(repo.iter_commits("HEAD"))))
    print(f"Found {len(commits)} commits to backfill\n")

    _init_db(DB_PATH)

    ok = skipped = errors = 0

    for i, commit in enumerate(commits, 1):
        sha      = commit.hexsha
        short    = sha[:8]
        parent   = commit.parents[0].hexsha if commit.parents else None
        author   = f"{commit.author.name} <{commit.author.email}>"
        message  = commit.message.splitlines()[0]
        ts       = datetime.datetime.fromtimestamp(
            commit.committed_date, tz=datetime.timezone.utc
        ).isoformat()

        # Build changed file list using KG-compatible paths (/host-home/...)
        if parent:
            diff = repo.commit(parent).diff(commit)
            changed = [
                _to_kg_path(str(Path(REPO_PATH) / (d.b_path or d.a_path)))
                for d in diff if d.b_path or d.a_path
            ]
        else:
            # Initial commit — list all files tracked at that point
            changed = [
                _to_kg_path(str(Path(REPO_PATH) / item.path))
                for item in commit.tree.traverse()
                if item.type == "blob"
            ]

        print(f"[{i:3}/{len(commits)}] {short}  {message[:60]:<60}  {len(changed)} files", end="  ")

        try:
            impact, scores = _analyse(driver, REPO_ID, sha, parent, changed, REPO_PATH)
            _upsert(DB_PATH, {
                "repo_id":      REPO_ID,
                "commit_sha":   sha,
                "parent_sha":   parent,
                "committed_at": ts,
                "author":       author,
                "message":      message,
                "changed_files": changed,
                "impact":       impact,
                "risk_score":           scores["risk_score"],
                "total_affected":       scores["total_affected"],
                "security_score":       scores["security_score"],
                "availability_score":   scores["availability_score"],
                "performance_score":    scores["performance_score"],
                "observability_score":  scores["observability_score"],
                "ops_score":            scores["ops_score"],
                "deps_score":           scores["deps_score"],
            })
            print(f"risk={scores['risk_score']:.2f}  affected={scores['total_affected']}")
            ok += 1
        except Exception as exc:
            print(f"ERROR: {exc}")
            errors += 1

    driver.close()
    print(f"\nDone — {ok} stored, {skipped} skipped, {errors} errors")
    print(f"DB: {DB_PATH}")


if __name__ == "__main__":
    main()
