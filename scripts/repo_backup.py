#!/usr/bin/env python3
"""
codeKG per-repo backup and restore.

Bundles everything that belongs to a single repo_id into one compressed
archive (.tar.gz) that can be moved to another machine and restored intact.

What is included
----------------
  Neo4j        — all nodes and relationships where repo_id = <id>
                 exported as Cypher MERGE statements
  agent_index  — agent_index_files + agent_index_module_files rows
                 exported as SQLite INSERT statements
  scan_log     — scan_log rows for the repo
  repos.json   — the registry entry for this repo_id

What is NOT included
--------------------
  telemetry.db, mcp_audit.db, llm_audit.db
  (those are observability data, not repo content)

Bundle layout
-------------
  codekg-backup-<repo_id>-<timestamp>/
  ├── manifest.json          metadata: version, repo_id, created_at, neo4j_version
  ├── neo4j.cypher           MERGE statements — idempotent, safe to re-run
  ├── agent_index.sql        INSERT OR REPLACE statements
  ├── scan_log.sql           INSERT OR REPLACE statements
  └── registry.json          {"repo_id": "path"} entry

Usage
-----
  python3 scripts/repo_backup.py backup  --repo codeKG  [--out ./backups] [--tag label]
  python3 scripts/repo_backup.py restore --file path/to/bundle.tar.gz [--yes]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
REPOS_DIR    = PROJECT_ROOT / "repos"
BACKUPS_DIR  = PROJECT_ROOT / "backups"

BUNDLE_VERSION = "1"

NEO4J_CONTAINER  = os.environ.get("NEO4J_CONTAINER", "codekg-neo4j")
NEO4J_USER       = os.environ.get("NEO4J_USER",      "neo4j")
NEO4J_PASSWORD   = os.environ.get("NEO4J_PASSWORD",  "codekg_dev")
REPOS_REGISTRY   = os.environ.get("REPOS_REGISTRY",  str(REPOS_DIR / "repos.json"))
AGENT_INDEX_DB   = os.environ.get("AGENT_INDEX_DB",  str(REPOS_DIR / "agent_index.db"))
SCAN_LOG_DB      = os.environ.get("SCAN_LOG_DB",     str(REPOS_DIR / "scan_log.db"))


# ── helpers ───────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _load_registry() -> dict[str, str]:
    p = Path(REPOS_REGISTRY)
    return json.loads(p.read_text()) if p.exists() else {}


API_CONTAINER = os.environ.get("API_CONTAINER", "codekg-api")


def _run_in_api(python_code: str) -> str:
    """Run a Python snippet inside the API container and return stdout."""
    result = subprocess.run(
        ["docker", "exec", API_CONTAINER, "python3", "-c", python_code],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def _neo4j_version() -> str:
    try:
        return _run_in_api(
            "from shared.config import cfg; from neo4j import GraphDatabase; "
            "d=GraphDatabase.driver(cfg.neo4j.uri,auth=(cfg.neo4j.user,cfg.neo4j.password)); "
            "[print(r['versions'][0]) for r in d.session().run('CALL dbms.components() YIELD versions')]; "
            "d.close()"
        ).strip()
    except Exception:
        return "unknown"


def _try_json(s: str):
    try:
        return json.loads(s)
    except Exception:
        return None


def _query_neo4j(cypher: str, repo_id: str) -> list[dict]:
    """Run a Cypher query via the API container's neo4j driver. Returns list of row dicts."""
    escaped_cypher = cypher.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
    code = (
        "import json, sys\n"
        "from shared.config import cfg\n"
        "from neo4j import GraphDatabase\n"
        "from neo4j.time import DateTime, Date, Duration\n"
        "def _ser(v):\n"
        "    if isinstance(v, (DateTime, Date)): return str(v)\n"
        "    if isinstance(v, Duration): return str(v)\n"
        "    if isinstance(v, dict): return {k2: _ser(v2) for k2,v2 in v.items()}\n"
        "    if isinstance(v, list): return [_ser(i) for i in v]\n"
        "    return v\n"
        "d = GraphDatabase.driver(cfg.neo4j.uri, auth=(cfg.neo4j.user, cfg.neo4j.password))\n"
        "rows = []\n"
        "with d.session() as s:\n"
        f"    for r in s.run('{escaped_cypher}', repo_id='{repo_id}'):\n"
        "        rows.append({k: _ser(v) for k,v in dict(r).items()})\n"
        "d.close()\n"
        "print(json.dumps(rows))\n"
    )
    raw = _run_in_api(code)
    return json.loads(raw) if raw else []


def _value_to_cypher(v) -> str:
    """Render a Python value as a Cypher literal."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_value_to_cypher(i) for i in v) + "]"
    # string — escape backslash then single-quote
    s = str(v).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{s}'"


def _props_to_cypher(props: dict) -> str:
    """Render a property dict as {key: value, ...}."""
    parts = [f"`{k}`: {_value_to_cypher(v)}" for k, v in props.items()]
    return "{" + ", ".join(parts) + "}"


# ── Neo4j export ──────────────────────────────────────────────────────────────

# Node labels that carry repo_id and their unique key properties
_NODE_SPECS: list[tuple[str, list[str]]] = [
    ("Repository",     ["repo_id"]),
    ("Module",         ["repo_id", "module_id"]),
    ("Package",        ["repo_id", "fqn"]),
    ("Class",          ["repo_id", "fqn"]),
    ("Method",         ["repo_id", "fqn"]),
    ("Enum",           ["repo_id", "fqn"]),
    ("ArchPolicy",     ["repo_id", "policy_id"]),
    ("ArchPattern",    ["repo_id", "pattern_id"]),
    ("TribalKnowledge",["repo_id", "tk_id"]),
]

# Relationship types to export (source and target both in repo scope)
_REL_TYPES = [
    "HAS_METHOD", "BELONGS_TO", "CONTAINS", "IMPORTS",
    "CALLS", "EXHIBITS", "VIOLATES", "APPLIES_TO",
    "HAS_MODULE",
]


def _export_nodes(repo_id: str) -> list[str]:
    lines: list[str] = [
        f"// Neo4j node export — repo_id: {repo_id}",
        f"// Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
    ]

    for label, key_props in _NODE_SPECS:
        print(f"    exporting {label} nodes…", end=" ", flush=True)
        try:
            rows = _query_neo4j(
                f"MATCH (n:{label}) WHERE n.repo_id = $repo_id RETURN properties(n) AS props",
                repo_id,
            )
            count = 0
            for row in rows:
                props = row.get("props") or {}
                if not props:
                    continue
                match_props = {k: props[k] for k in key_props if k in props}
                merge_clause = f"MERGE (n:{label} {_props_to_cypher(match_props)})"
                set_parts = [
                    f"n.`{k}` = {_value_to_cypher(v)}"
                    for k, v in props.items()
                    if k not in key_props
                ]
                if set_parts:
                    lines.append(merge_clause)
                    lines.append(f"  ON CREATE SET {', '.join(set_parts)}")
                    lines.append(f"  ON MATCH  SET {', '.join(set_parts)};")
                else:
                    lines.append(f"{merge_clause};")
                count += 1
            print(f"{count} nodes")
        except Exception as exc:
            print(f"SKIP ({exc})")
            lines.append(f"// SKIPPED {label}: {exc}")

        lines.append("")

    return lines


def _export_relationships(repo_id: str) -> list[str]:
    lines: list[str] = [
        "",
        f"// Relationships — repo_id: {repo_id}",
        "",
    ]

    for rel_type in _REL_TYPES:
        print(f"    exporting :{rel_type} edges…", end=" ", flush=True)
        try:
            rows = _query_neo4j(
                f"MATCH (a)-[r:{rel_type}]->(b) "
                f"WHERE a.repo_id = $repo_id AND b.repo_id = $repo_id "
                f"RETURN labels(a)[0] AS al, a.fqn AS af, "
                f"labels(b)[0] AS bl, b.fqn AS bf, "
                f"properties(r) AS rp",
                repo_id,
            )
            count = 0
            for row in rows:
                al, af = row.get("al", ""), row.get("af", "")
                bl, bf = row.get("bl", ""), row.get("bf", "")
                rp = row.get("rp") or {}
                if not al or not af or not bl or not bf:
                    continue
                match_a = f"MATCH (a:{al} {{repo_id: {_value_to_cypher(repo_id)}, fqn: {_value_to_cypher(af)}}})"
                match_b = f"MATCH (b:{bl} {{repo_id: {_value_to_cypher(repo_id)}, fqn: {_value_to_cypher(bf)}}})"
                merge   = f"MERGE (a)-[:{rel_type}{' ' + _props_to_cypher(rp) if rp else ''}]->(b);"
                lines.append(match_a)
                lines.append(match_b)
                lines.append(merge)
                count += 1
            print(f"{count} edges")
        except Exception as exc:
            print(f"SKIP ({exc})")
            lines.append(f"// SKIPPED :{rel_type}: {exc}")

        lines.append("")

    return lines


# ── SQLite export ─────────────────────────────────────────────────────────────

def _export_sqlite_table(db_path: str, table: str, repo_id: str) -> list[str]:
    """Export rows for repo_id from one SQLite table as INSERT OR REPLACE statements."""
    if not Path(db_path).exists():
        return [f"-- {db_path} not found\n"]

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        cols_info = con.execute(f"PRAGMA table_info({table})").fetchall()
        if not cols_info:
            return [f"-- table {table} not found\n"]
        col_names = [c["name"] for c in cols_info]
        if "repo_id" not in col_names:
            return [f"-- {table} has no repo_id column — skipped\n"]

        rows = con.execute(
            f"SELECT * FROM {table} WHERE repo_id = ?", (repo_id,)
        ).fetchall()
        if not rows:
            return [f"-- {table}: no rows for {repo_id}\n"]

        lines = [f"-- {table}: {len(rows)} rows for {repo_id}"]
        cols_str = ", ".join(f'"{c}"' for c in col_names)
        for row in rows:
            vals = []
            for v in row:
                if v is None:
                    vals.append("NULL")
                elif isinstance(v, (int, float)):
                    vals.append(str(v))
                else:
                    escaped = str(v).replace("'", "''")
                    vals.append(f"'{escaped}'")
            vals_str = ", ".join(vals)
            lines.append(
                f"INSERT OR REPLACE INTO {table} ({cols_str}) VALUES ({vals_str});"
            )
        lines.append("")
        return lines
    finally:
        con.close()


def _export_agent_index(repo_id: str) -> list[str]:
    print(f"    exporting agent_index_files…", end=" ", flush=True)
    lines = [
        f"-- agent_index export — repo_id: {repo_id}",
        f"-- Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
    ]
    for table in ("agent_index_files", "agent_index_module_files"):
        rows = _export_sqlite_table(AGENT_INDEX_DB, table, repo_id)
        count = sum(1 for r in rows if r.startswith("INSERT"))
        lines.extend(rows)
        print(f"{count} rows ({table})", end=" ", flush=True)
    print()
    return lines


def _export_scan_log(repo_id: str) -> list[str]:
    print(f"    exporting scan_log…", end=" ", flush=True)
    lines = [
        f"-- scan_log export — repo_id: {repo_id}",
        f"-- Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
    ]
    rows = _export_sqlite_table(SCAN_LOG_DB, "scan_log", repo_id)
    count = sum(1 for r in rows if r.startswith("INSERT"))
    lines.extend(rows)
    print(f"{count} rows")
    return lines


# ── backup ────────────────────────────────────────────────────────────────────

def cmd_backup(repo_id: str, out_dir: Path, tag: str = "") -> Path:
    registry = _load_registry()
    if repo_id not in registry:
        print(f"ERROR: '{repo_id}' not found in registry. Registered repos:")
        for k in registry:
            print(f"  {k}")
        sys.exit(1)

    ts      = _ts()
    label   = f"-{tag}" if tag else ""
    name    = f"codekg-backup-{repo_id}-{ts}{label}"
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle  = out_dir / f"{name}.tar.gz"

    print(f"\ncodeKG repo backup — {repo_id}")
    print(f"  bundle → {bundle}\n")

    with tempfile.TemporaryDirectory(prefix="codekg-backup-") as tmp:
        staging = Path(tmp) / name
        staging.mkdir()

        # 1. Manifest
        print("  [1/5] Writing manifest…")
        neo4j_ver = _neo4j_version()
        manifest = {
            "version":      BUNDLE_VERSION,
            "repo_id":      repo_id,
            "created_at":   datetime.now(timezone.utc).isoformat(),
            "neo4j_version": neo4j_ver,
            "includes": ["neo4j.cypher", "agent_index.sql", "scan_log.sql", "registry.json"],
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2))

        # 2. Registry entry
        print("  [2/5] Exporting registry entry…")
        (staging / "registry.json").write_text(
            json.dumps({repo_id: registry[repo_id]}, indent=2)
        )

        # 3. Neo4j
        print("  [3/5] Exporting Neo4j graph…")
        node_lines = _export_nodes(repo_id)
        rel_lines  = _export_relationships(repo_id)
        cypher_content = "\n".join(node_lines + rel_lines)
        (staging / "neo4j.cypher").write_text(cypher_content)
        stmt_count = cypher_content.count(";")
        print(f"    → {stmt_count} Cypher statements")

        # 4. Agent index
        print("  [4/5] Exporting agent index…")
        (staging / "agent_index.sql").write_text("\n".join(_export_agent_index(repo_id)))

        # 5. Scan log
        print("  [5/5] Exporting scan log…")
        (staging / "scan_log.sql").write_text("\n".join(_export_scan_log(repo_id)))

        # Pack
        print(f"\n  Packing bundle…")
        with tarfile.open(bundle, "w:gz") as tar:
            tar.add(staging, arcname=name)

    size_mb = bundle.stat().st_size / 1_048_576
    print(f"\n✓ Backup complete: {bundle}  ({size_mb:.1f} MB)")
    return bundle


# ── restore ───────────────────────────────────────────────────────────────────

def cmd_restore(bundle_path: Path, yes: bool = False) -> None:
    if not bundle_path.exists():
        print(f"ERROR: file not found: {bundle_path}")
        sys.exit(1)

    # Read manifest from archive without full extraction
    with tarfile.open(bundle_path, "r:gz") as tar:
        members = tar.getnames()
        manifest_name = next((m for m in members if m.endswith("manifest.json")), None)
        if not manifest_name:
            print("ERROR: bundle has no manifest.json — not a valid codeKG backup")
            sys.exit(1)
        manifest = json.loads(tar.extractfile(manifest_name).read())

    repo_id = manifest["repo_id"]
    created = manifest.get("created_at", "unknown")
    includes = manifest.get("includes", [])

    print(f"\ncodeKG repo restore")
    print(f"  repo_id  : {repo_id}")
    print(f"  backed up: {created}")
    print(f"  bundle   : {bundle_path}")
    print(f"  includes : {', '.join(includes)}")
    print()
    print("  This will MERGE data into Neo4j and REPLACE rows in SQLite.")
    print("  Existing data for this repo_id is overwritten, not deleted.")
    print()

    if not yes:
        answer = input("  Proceed? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    with tempfile.TemporaryDirectory(prefix="codekg-restore-") as tmp:
        print("\n  Extracting bundle…")
        with tarfile.open(bundle_path, "r:gz") as tar:
            tar.extractall(tmp)

        # Find the staging dir (first subdir in tmp)
        staging = next(Path(tmp).iterdir())

        # 1. Registry
        reg_file = staging / "registry.json"
        if reg_file.exists():
            print("  [1/4] Restoring registry entry…")
            current = _load_registry()
            entry   = json.loads(reg_file.read_text())
            current.update(entry)
            Path(REPOS_REGISTRY).parent.mkdir(parents=True, exist_ok=True)
            Path(REPOS_REGISTRY).write_text(json.dumps(current, indent=2))
            for k, v in entry.items():
                print(f"    {k} → {v}")

        # 2. Neo4j
        cypher_file = staging / "neo4j.cypher"
        if cypher_file.exists():
            print("  [2/4] Restoring Neo4j graph…")
            cypher_text = cypher_file.read_text()
            # Extract individual statements (skip comments and blank lines)
            stmts = [
                s.strip() for s in cypher_text.split(";")
                if s.strip() and not s.strip().startswith("//")
            ]
            print(f"    running {len(stmts)} Cypher statements via API container…")
            errors = 0
            for i, stmt in enumerate(stmts, 1):
                try:
                    escaped = stmt.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
                    _run_in_api(
                        "from shared.config import cfg\n"
                        "from neo4j import GraphDatabase\n"
                        "d = GraphDatabase.driver(cfg.neo4j.uri, auth=(cfg.neo4j.user, cfg.neo4j.password))\n"
                        "with d.session() as s:\n"
                        f"    s.run('{escaped}')\n"
                        "d.close()\n"
                    )
                except Exception as exc:
                    errors += 1
                    if errors <= 5:
                        print(f"    WARNING stmt {i}: {str(exc)[:120]}")
            if errors:
                print(f"    Completed with {errors} warnings (often harmless — missing optional nodes)")
            else:
                print(f"    OK")

        # 3. Agent index
        ai_file = staging / "agent_index.sql"
        if ai_file.exists():
            print("  [3/4] Restoring agent index…")
            _run_sql_file(AGENT_INDEX_DB, ai_file)

        # 4. Scan log
        sl_file = staging / "scan_log.sql"
        if sl_file.exists():
            print("  [4/4] Restoring scan log…")
            _run_sql_file(SCAN_LOG_DB, sl_file)

    print(f"\n✓ Restore complete for repo_id '{repo_id}'")


def _run_sql_file(db_path: str, sql_file: Path) -> None:
    sql = sql_file.read_text()
    stmts = [s.strip() for s in sql.split(";") if s.strip() and not s.strip().startswith("--")]
    if not stmts:
        print(f"    no statements to execute")
        return
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        for stmt in stmts:
            try:
                con.execute(stmt)
            except sqlite3.OperationalError as e:
                print(f"    WARNING: {e}")
        con.commit()
        print(f"    {len(stmts)} statements executed → {Path(db_path).name}")
    finally:
        con.close()


# ── list ──────────────────────────────────────────────────────────────────────

def cmd_list(out_dir: Path) -> None:
    bundles = sorted(out_dir.glob("codekg-backup-*.tar.gz"), reverse=True)
    if not bundles:
        print(f"No repo backups found in {out_dir}")
        return
    print(f"\n{'Bundle':<60}  {'Repo':<20}  {'Created':<25}  {'Size':>8}")
    print("-" * 115)
    for b in bundles:
        size = f"{b.stat().st_size / 1_048_576:.1f} MB"
        try:
            with tarfile.open(b, "r:gz") as tar:
                mf = next((m for m in tar.getnames() if m.endswith("manifest.json")), None)
                if mf:
                    manifest = json.loads(tar.extractfile(mf).read())
                    repo   = manifest.get("repo_id", "?")
                    ts     = manifest.get("created_at", "?")[:19].replace("T", " ")
                else:
                    repo, ts = "?", "?"
        except Exception:
            repo, ts = "?", "?"
        print(f"  {b.name:<58}  {repo:<20}  {ts:<25}  {size:>8}")
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="codeKG per-repo backup and restore",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # backup
    p_bk = sub.add_parser("backup", help="Create a repo backup bundle")
    p_bk.add_argument("--repo", required=True, help="Repo ID (e.g. codeKG)")
    p_bk.add_argument("--out",  default=str(BACKUPS_DIR), help="Output directory")
    p_bk.add_argument("--tag",  default="", help="Extra label appended to filename")

    # restore
    p_rs = sub.add_parser("restore", help="Restore from a backup bundle")
    p_rs.add_argument("--file", required=True, help="Path to .tar.gz bundle")
    p_rs.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")

    # list
    p_ls = sub.add_parser("list", help="List available repo backup bundles")
    p_ls.add_argument("--dir", default=str(BACKUPS_DIR), help="Directory to scan")

    args = parser.parse_args()

    if args.cmd == "backup":
        cmd_backup(args.repo, Path(args.out), args.tag)
    elif args.cmd == "restore":
        cmd_restore(Path(args.file), args.yes)
    elif args.cmd == "list":
        cmd_list(Path(args.dir))


if __name__ == "__main__":
    main()
