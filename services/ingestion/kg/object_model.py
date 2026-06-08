"""
Repo Object Model builder for CodeKG.

Runs after wire_edges + pattern detection at the end of every scan.
For each Class node in the repo, assembles a pre-resolved JSON snapshot
containing everything an LLM coding tool needs to understand a class —
superclass, interfaces, methods, fields, dependencies, dependents,
module membership, test coverage, and architectural patterns.

The snapshot is stored as `c.object_model` (JSON string) on the Class node
and can be retrieved in a single Cypher query.  No source file reading.

JSON shape (per class, ~500–2000 bytes):
{
  "fqn":           "org.elasticsearch.xpack.ml.job.persistence.JobConfigProvider",
  "name":          "JobConfigProvider",
  "kind":          "class",           // class | interface | enum | abstract | annotation
  "module_id":     "x-pack/plugin/ml",
  "module_name":   "ml",
  "package":       "org.elasticsearch.xpack.ml.job.persistence",
  "file_path":     "x-pack/plugin/ml/src/main/java/.../JobConfigProvider.java",
  "lines":         [99, 823],
  "line_count":    724,
  "annotations":   ["@Component"],
  "superclass":    "AbstractJobManager",   // simple name or null
  "interfaces":    ["ClusterStateListener"],
  "methods": [
    {"name": "putJob", "return_type": "void",
     "parameters": ["PutJobAction.Request"], "modifiers": ["public"], "annotations": []}
  ],
  "fields": [
    {"name": "client", "type": "Client", "modifiers": ["private", "final"]}
  ],
  "method_count":    37,
  "public_methods":  12,
  "imports":         ["org.elasticsearch.client.Client"],   // same-repo, top 20 FQNs
  "dependencies":    ["Client", "AnomalyDetectionAuditor"], // simple names, top 20
  "dependents":      ["TransportPutJobAction"],              // simple names of importers, top 10
  "is_module_api":   true,   // imported by classes in OTHER modules
  "test_classes":    ["JobConfigProviderTests"],
  "patterns":        [{"name": "God Class", "anti": true}],
  "warnings":        ["God Class (37 methods)"]
}
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any

from neo4j import Driver

try:
    from shared.codekg_logging.codekg_logger import get_logger
except ImportError:
    class _FB:
        """Fallback logger for object-model extraction helpers. Watch out for debugging depth here, because this shim intentionally keeps logging lightweight."""

        def __init__(self, n): self._l = logging.getLogger(n)
        def info(self, m, **k): self._l.info(m)
        def warning(self, m, **k): self._l.warning(m)
        def error(self, m, **k): self._l.error(m)
        def timed(self, op, **k):
            import contextlib
            return contextlib.nullcontext()
    def get_logger(n, **k): return _FB(n)

log = get_logger(__name__, service="ingestion")

_BATCH = 500
_MAX_METHODS   = 60   # per snapshot
_MAX_IMPORTS   = 20
_MAX_DEPS      = 20
_MAX_DEPENDENTS = 10
_SIZE_BUDGET   = 3000  # bytes — trim if over


# ---------------------------------------------------------------------------
# Bulk data fetchers — each returns a dict keyed by class FQN
# ---------------------------------------------------------------------------

def _run(driver: Driver, cypher: str, **params) -> list[dict]:
    with driver.session() as s:
        return [dict(r) for r in s.run(cypher, **params)]


def _fetch_all_classes(driver: Driver, repo_id: str) -> list[dict]:
    return _run(driver, """
        MATCH (c:Class {repo_id: $repo_id})
        RETURN c.fqn AS fqn, c.name AS name, c.kind AS kind,
               c.package_fqn AS package_fqn, c.file_path AS file_path,
               c.start_line AS start_line, c.end_line AS end_line,
               c.source_chars AS source_chars,
               c.annotations AS annotations, c.javadoc AS javadoc
        ORDER BY c.fqn
    """, repo_id=repo_id)


def _fetch_module_map(driver: Driver, repo_id: str) -> dict[str, tuple[str, str]]:
    """Returns {fqn -> (module_id, module_name)} — longest (most-specific) match."""
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $repo_id}), (m:Module {repo_id: $repo_id})
        WHERE c.file_path STARTS WITH m.path
        RETURN c.fqn AS fqn, m.module_id AS module_id,
               m.name AS module_name, size(m.path) AS path_len
        ORDER BY c.fqn, path_len DESC
    """, repo_id=repo_id)
    result: dict[str, tuple[str, str]] = {}
    for r in rows:
        if r["fqn"] not in result:  # first = longest match (ordered DESC)
            result[r["fqn"]] = (r["module_id"], r["module_name"])
    return result


def _fetch_superclasses(driver: Driver, repo_id: str) -> dict[str, str]:
    """Returns {fqn -> superclass_simple_name}."""
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $repo_id})-[:EXTENDS]->(s)
        RETURN c.fqn AS fqn, s.name AS superclass
    """, repo_id=repo_id)
    return {r["fqn"]: r["superclass"] for r in rows}


def _fetch_interfaces(driver: Driver, repo_id: str) -> dict[str, list[str]]:
    """Returns {fqn -> [interface_simple_name, ...]}."""
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $repo_id})-[:IMPLEMENTS]->(i)
        RETURN c.fqn AS fqn, i.name AS iface
    """, repo_id=repo_id)
    result: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        result[r["fqn"]].append(r["iface"])
    return dict(result)


def _fetch_dependents(driver: Driver, repo_id: str) -> dict[str, list[dict]]:
    """
    Returns {imported_fqn -> [{name, file_path}, ...]} — classes that import this one.
    Also used for is_module_api computation (file_path carried through).
    """
    rows = _run(driver, """
        MATCH (importer:Class {repo_id: $repo_id})-[:IMPORTS]->(imported:Class {repo_id: $repo_id})
        RETURN imported.fqn AS fqn,
               importer.name AS importer_name,
               importer.file_path AS importer_path
    """, repo_id=repo_id)
    result: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        result[r["fqn"]].append({
            "name": r["importer_name"],
            "file_path": r["importer_path"],
        })
    return dict(result)


def _fetch_imports(driver: Driver, repo_id: str) -> dict[str, list[str]]:
    """Returns {fqn -> [imported_fqn, ...]} — same-repo imports only."""
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $repo_id})-[:IMPORTS]->(imp:Class {repo_id: $repo_id})
        RETURN c.fqn AS fqn, imp.fqn AS import_fqn
    """, repo_id=repo_id)
    result: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        result[r["fqn"]].append(r["import_fqn"])
    return dict(result)


def _fetch_patterns(driver: Driver, repo_id: str) -> dict[str, list[dict]]:
    """Returns {fqn -> [{name, anti}, ...]}."""
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $repo_id})-[:EXHIBITS]->(ap:ArchPattern)
        RETURN c.fqn AS fqn, ap.name AS name,
               coalesce(ap.anti_pattern, false) AS anti
    """, repo_id=repo_id)
    result: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        result[r["fqn"]].append({"name": r["name"], "anti": r["anti"]})
    return dict(result)


def _fetch_methods_batch(
    driver: Driver, repo_id: str, skip: int, limit: int
) -> dict[str, list[dict]]:
    """Returns {class_fqn -> [method_dict, ...]} for one page of classes."""
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $repo_id})
        WITH c ORDER BY c.fqn SKIP $skip LIMIT $limit
        MATCH (c)-[:HAS_METHOD]->(m:Method)
        RETURN c.fqn AS class_fqn,
               m.name AS name,
               m.return_type AS return_type,
               m.parameters AS parameters,
               m.modifiers AS modifiers,
               m.annotations AS annotations
    """, repo_id=repo_id, skip=skip, limit=limit)
    result: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        result[r["class_fqn"]].append({
            "name": r["name"],
            "return_type": r["return_type"],
            "parameters": r["parameters"] or [],
            "modifiers": r["modifiers"] or [],
            "annotations": r["annotations"] or [],
        })
    return dict(result)


def _fetch_fields_batch(
    driver: Driver, repo_id: str, skip: int, limit: int
) -> dict[str, list[dict]]:
    """Returns {class_fqn -> [field_dict, ...]} for one page of classes."""
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $repo_id})
        WITH c ORDER BY c.fqn SKIP $skip LIMIT $limit
        MATCH (c)-[:HAS_FIELD]->(f:Field)
        RETURN c.fqn AS class_fqn,
               f.name AS name,
               f.type_name AS type_name,
               f.modifiers AS modifiers
    """, repo_id=repo_id, skip=skip, limit=limit)
    result: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        result[r["class_fqn"]].append({
            "name": r["name"],
            "type": r["type_name"],
            "modifiers": r["modifiers"] or [],
        })
    return dict(result)


# ---------------------------------------------------------------------------
# Test class heuristic — pure Python, no extra query
# ---------------------------------------------------------------------------

def _build_test_map(all_classes: list[dict]) -> dict[str, list[str]]:
    """
    For each class, find test classes whose name contains the class name
    and ends with Test / Tests / IT.  Done entirely in Python.
    Returns {fqn -> [test_class_name, ...]}.
    """
    test_suffixes = ("Test", "Tests", "IT", "TestCase")
    test_entries = [
        c for c in all_classes
        if any(c["name"].endswith(s) for s in test_suffixes)
    ]
    result: dict[str, list[str]] = defaultdict(list)
    for cls in all_classes:
        if any(cls["name"].endswith(s) for s in test_suffixes):
            continue  # skip test classes themselves
        for t in test_entries:
            if cls["name"] in t["name"] and t["fqn"] != cls["fqn"]:
                result[cls["fqn"]].append(t["name"])
    return dict(result)


# ---------------------------------------------------------------------------
# Snapshot assembly
# ---------------------------------------------------------------------------

def _rel_file_path(file_path: str | None) -> str:
    """Strip common repo root prefix for readability."""
    if not file_path:
        return ""
    # strip everything up to /src/ or keep last 4 segments
    idx = file_path.find("/src/")
    if idx >= 0:
        return file_path[idx + 1:]
    parts = file_path.split("/")
    return "/".join(parts[-5:]) if len(parts) > 5 else file_path


def _assemble_snapshot(
    cls: dict,
    module_map: dict,
    superclasses: dict,
    interfaces: dict,
    dependents_map: dict,
    imports_map: dict,
    patterns_map: dict,
    methods_map: dict,
    fields_map: dict,
    test_map: dict,
) -> dict:
    fqn = cls["fqn"]
    mod = module_map.get(fqn)
    module_id   = mod[0] if mod else None
    module_name = mod[1] if mod else None

    methods   = methods_map.get(fqn, [])
    fields    = fields_map.get(fqn, [])
    imports   = imports_map.get(fqn, [])
    dependents = dependents_map.get(fqn, [])
    patterns  = patterns_map.get(fqn, [])

    # Sort methods: public first, constructors last
    def method_sort_key(m):
        mods = m.get("modifiers", [])
        if "public" in mods:    return 0
        if "protected" in mods: return 1
        return 2
    methods_sorted = sorted(methods, key=method_sort_key)

    public_methods = [m for m in methods if "public" in m.get("modifiers", [])]

    # is_module_api: any importer is in a different module
    is_api = False
    if module_id and dependents:
        for dep in dependents:
            dep_path = dep.get("file_path", "")
            # check if any module's path is a prefix of the importer path
            # we use module_map which only covers exact module members —
            # approximate: if importer_path doesn't start with our module's path prefix
            # We carry the module_id separately so we only need to check if dep is outside ours
            # Simple heuristic: dep file_path not under module_id path component
            mod_path_component = "/" + module_id.split("/")[0] + "/"
            if mod_path_component not in dep_path:
                is_api = True
                break

    # Warnings
    warnings = []
    for p in patterns:
        if p["anti"]:
            warnings.append(p["name"])
    if len(methods) > 30:
        warnings.append(f"Large class ({len(methods)} methods)")
    if not any(m for m in methods if "public" in m.get("modifiers", [])):
        if len(methods) > 0:
            warnings.append("No public methods")

    start = cls.get("start_line") or 0
    end   = cls.get("end_line") or 0
    # source_chars: exact byte count from Tree-sitter parser (end_byte - start_byte).
    # Used by the MCP layer to calculate how many tokens Claude would have consumed
    # reading raw source instead of the KG response. Stored at parse time.
    source_chars = cls.get("source_chars") or max(0, end - start) * 50  # 50 chars/line fallback

    snap: dict[str, Any] = {
        "fqn":          fqn,
        "name":         cls["name"],
        "kind":         cls.get("kind") or "class",
        "module_id":    module_id,
        "module_name":  module_name,
        "package":      cls.get("package_fqn"),
        "file_path":    _rel_file_path(cls.get("file_path")),
        "lines":        [start, end],
        "line_count":   max(0, end - start),
        "source_chars": source_chars,
        "annotations":  cls.get("annotations") or [],
        "javadoc":      cls.get("javadoc"),
        "superclass":   superclasses.get(fqn),
        "interfaces":   interfaces.get(fqn, []),
        "method_count": len(methods),
        "public_methods": len(public_methods),
        "methods":      methods_sorted[:_MAX_METHODS],
        "fields":       fields,
        "imports":      imports[:_MAX_IMPORTS],
        "dependencies": [i.split(".")[-1] for i in imports[:_MAX_DEPS]],
        "dependents":   [d["name"] for d in dependents[:_MAX_DEPENDENTS]],
        "is_module_api": is_api,
        "test_classes": test_map.get(fqn, [])[:5],
        "patterns":     patterns,
        "warnings":     warnings,
    }
    return snap


def _trim_to_budget(snap: dict, budget: int = _SIZE_BUDGET) -> dict:
    """Trim the snapshot if it exceeds the byte budget."""
    encoded = json.dumps(snap, separators=(",", ":"))
    if len(encoded) <= budget:
        return snap
    # Trim in order of descending cost: methods → fields → imports
    snap = dict(snap)
    snap["methods"] = snap["methods"][:20]
    encoded = json.dumps(snap, separators=(",", ":"))
    if len(encoded) <= budget:
        return snap
    snap["fields"] = snap["fields"][:10]
    snap["imports"] = snap["imports"][:10]
    snap["dependencies"] = snap["dependencies"][:10]
    return snap


# ---------------------------------------------------------------------------
# Batch write
# ---------------------------------------------------------------------------

def _write_snapshots(
    driver: Driver, repo_id: str, snapshots: list[tuple[str, str]]
) -> None:
    """Write (fqn, json_str) pairs to Class nodes in batches."""
    for i in range(0, len(snapshots), _BATCH):
        batch = snapshots[i : i + _BATCH]
        with driver.session() as s:
            s.run("""
                UNWIND $rows AS row
                MATCH (c:Class {fqn: row.fqn, repo_id: $repo_id})
                SET c.object_model = row.json
            """, rows=[{"fqn": fqn, "json": js} for fqn, js in batch],
                  repo_id=repo_id)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_object_models(
    driver: Driver,
    repo_id: str,
    fqn_filter: set[str] | None = None,
) -> int:
    """
    Build and store object_model JSON snapshots for all (or filtered) classes
    in the repo.  Returns the count of classes processed.

    fqn_filter: if provided, only rebuild snapshots for these FQNs.
    """
    log.info("Building object models", repo_id=repo_id,
             filter_size=len(fqn_filter) if fqn_filter else "all")

    # ── 1. Fetch all scalar class data ──
    all_classes = _fetch_all_classes(driver, repo_id)
    if fqn_filter:
        all_classes = [c for c in all_classes if c["fqn"] in fqn_filter]
    if not all_classes:
        log.warning("No classes found for object model build", repo_id=repo_id)
        return 0

    total = len(all_classes)
    log.info("Classes to process", repo_id=repo_id, count=total)

    # ── 2. Fetch all relationship maps in bulk ──
    module_map   = _fetch_module_map(driver, repo_id)
    superclasses = _fetch_superclasses(driver, repo_id)
    interfaces   = _fetch_interfaces(driver, repo_id)
    dependents   = _fetch_dependents(driver, repo_id)
    imports      = _fetch_imports(driver, repo_id)
    patterns     = _fetch_patterns(driver, repo_id)
    test_map     = _build_test_map(all_classes)

    log.info("Relationship maps loaded",
             repo_id=repo_id,
             modules=len(module_map),
             superclasses=len(superclasses),
             dependents=len(dependents),
             imports=len(imports))

    # ── 3. Fetch methods + fields in batches ──
    methods_map: dict[str, list[dict]] = {}
    fields_map:  dict[str, list[dict]] = {}

    for skip in range(0, total, _BATCH):
        batch_methods = _fetch_methods_batch(driver, repo_id, skip, _BATCH)
        batch_fields  = _fetch_fields_batch(driver, repo_id, skip, _BATCH)
        methods_map.update(batch_methods)
        fields_map.update(batch_fields)
        if skip % (10 * _BATCH) == 0 and skip > 0:
            log.info("Method/field fetch progress",
                     repo_id=repo_id, processed=skip, total=total)

    # ── 4. Assemble and write snapshots ──
    snapshots: list[tuple[str, str]] = []
    for cls in all_classes:
        snap = _assemble_snapshot(
            cls, module_map, superclasses, interfaces,
            dependents, imports, patterns,
            methods_map, fields_map, test_map,
        )
        snap = _trim_to_budget(snap)
        snapshots.append((cls["fqn"], json.dumps(snap, separators=(",", ":"))))

    _write_snapshots(driver, repo_id, snapshots)

    log.info("Object models written",
             repo_id=repo_id, count=len(snapshots))
    return len(snapshots)
