"""
Architectural pattern detector for CodeKG.

Scans the knowledge graph for a given repo and matches classes against
the pattern catalog (GoF + EIP + Custom + Anti-patterns).

For each matched pattern it generates:
  - A summary of the classes that exhibit it
  - A proposed ArchPolicy node (to be reviewed and activated by the team)
  - A Cypher constraint query that enforces the pattern boundary

Results are written back to Neo4j as ArchPattern nodes (distinct from
ArchPolicy — patterns are descriptive, policies are normative).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from neo4j import Driver

from shared.logging.codekg_logger import get_logger

_CATALOG_PATH = Path(__file__).parent / "pattern_catalog.json"
log = get_logger(__name__, service="console")


def _load_catalog() -> list[dict]:
    return json.loads(_CATALOG_PATH.read_text())["patterns"]


def _run(driver: Driver, cypher: str, **params) -> list[dict]:
    try:
        with driver.session() as s:
            return [dict(r) for r in s.run(cypher, **params)]
    except Exception as e:
        log.warning("KG query failed in pattern detector", exc=e)
        return []


# ---------------------------------------------------------------------------
# Signal matchers — each returns matching classes from the KG
# ---------------------------------------------------------------------------

def _match_name_suffix(driver: Driver, suffixes: list[str], repo_id: str | None) -> list[dict]:
    if not suffixes:
        return []
    scope = "AND c.repo_id = $repo_id" if repo_id else ""
    conditions = " OR ".join(f"c.name ENDS WITH '{s}'" for s in suffixes)
    return _run(driver, f"""
        MATCH (c:Class)
        WHERE ({conditions}) {scope}
          AND NOT c.fqn CONTAINS '$'
        RETURN c.fqn AS fqn, c.name AS name, c.file_path AS file_path,
               c.kind AS kind, c.annotations AS annotations
        ORDER BY c.fqn LIMIT 500
    """, repo_id=repo_id)


def _match_name_prefix(driver: Driver, prefixes: list[str], repo_id: str | None) -> list[dict]:
    if not prefixes:
        return []
    scope = "AND c.repo_id = $repo_id" if repo_id else ""
    conditions = " OR ".join(f"c.name STARTS WITH '{p}'" for p in prefixes)
    return _run(driver, f"""
        MATCH (c:Class)
        WHERE ({conditions}) {scope}
          AND NOT c.fqn CONTAINS '$'
        RETURN c.fqn AS fqn, c.name AS name, c.file_path AS file_path,
               c.kind AS kind, c.annotations AS annotations
        ORDER BY c.fqn LIMIT 500
    """, repo_id=repo_id)


def _match_base_class(driver: Driver, base_contains: list[str], repo_id: str | None) -> list[dict]:
    if not base_contains:
        return []
    scope = "AND c.repo_id = $repo_id" if repo_id else ""
    conditions = " OR ".join(f"parent.name CONTAINS '{b}'" for b in base_contains)
    return _run(driver, f"""
        MATCH (c:Class)-[:EXTENDS|IMPLEMENTS]->(parent:Class)
        WHERE ({conditions}) {scope}
          AND NOT c.fqn CONTAINS '$'
        RETURN c.fqn AS fqn, c.name AS name, c.file_path AS file_path,
               c.kind AS kind, parent.name AS base_class
        ORDER BY c.fqn LIMIT 500
    """, repo_id=repo_id)


def _match_annotation(driver: Driver, annotations: list[str], repo_id: str | None) -> list[dict]:
    if not annotations:
        return []
    scope = "AND c.repo_id = $repo_id" if repo_id else ""
    conditions = " OR ".join(f"ANY(a IN c.annotations WHERE a CONTAINS '{ann.lstrip('@')}')" for ann in annotations)
    return _run(driver, f"""
        MATCH (c:Class)
        WHERE ({conditions}) {scope}
        RETURN c.fqn AS fqn, c.name AS name, c.file_path AS file_path,
               c.annotations AS annotations
        ORDER BY c.fqn LIMIT 500
    """, repo_id=repo_id)


def _match_generated(driver: Driver, repo_id: str | None) -> list[dict]:
    scope = "AND c.repo_id = $repo_id" if repo_id else ""
    return _run(driver, f"""
        MATCH (c:Class)
        WHERE c.file_path CONTAINS '/generated/' {scope}
          AND NOT c.fqn CONTAINS '$'
        RETURN c.fqn AS fqn, c.name AS name, c.file_path AS file_path
        ORDER BY c.fqn LIMIT 500
    """, repo_id=repo_id)


def _match_god_class(driver: Driver, method_gt: int, field_gt: int, repo_id: str | None) -> list[dict]:
    scope = "AND c.repo_id = $repo_id" if repo_id else ""
    return _run(driver, f"""
        MATCH (c:Class)
        WHERE NOT c.fqn CONTAINS 'Test' {scope}
        OPTIONAL MATCH (c)-[:HAS_METHOD]->(m:Method)
        OPTIONAL MATCH (c)-[:HAS_FIELD]->(f:Field)
        WITH c, count(DISTINCT m) AS method_count, count(DISTINCT f) AS field_count
        WHERE method_count > $method_gt AND field_count > $field_gt
        RETURN c.fqn AS fqn, c.name AS name, c.file_path AS file_path,
               method_count, field_count
        ORDER BY method_count DESC LIMIT 50
    """, repo_id=repo_id, method_gt=method_gt, field_gt=field_gt)


def _match_missing_evaluator_variant(driver: Driver, repo_id: str | None) -> list[dict]:
    """
    Find evaluator families where DocValuesAndDocValues variant is absent
    but DocValuesAndSource exists — this is the pattern that caused the
    ClassCastException bug in Elasticsearch.
    """
    scope = "AND c.repo_id = $repo_id" if repo_id else ""
    rows = _run(driver, f"""
        MATCH (c:Class)
        WHERE c.name ENDS WITH 'Evaluator'
          AND (c.name CONTAINS 'DocValuesAndSource' OR c.name CONTAINS 'DocValuesAndConstant') {scope}
        RETURN c.fqn AS fqn, c.name AS name, c.file_path AS file_path
        ORDER BY c.fqn LIMIT 200
    """, repo_id=repo_id)

    # For each, check whether the DocValuesAndDocValues sibling exists
    missing = []
    for row in rows:
        name = row["name"]
        base = name.replace("DocValuesAndSource", "").replace("DocValuesAndConstant", "")
        dv_dv_name = base + "DocValuesAndDocValues"
        exists = _run(driver, f"""
            MATCH (c:Class) WHERE c.name = $name RETURN c.fqn LIMIT 1
        """, name=dv_dv_name)
        if not exists:
            row["missing_variant"] = dv_dv_name
            missing.append(row)

    return missing


def _match_method_name(driver: Driver, method_names: list[str], repo_id: str | None) -> list[dict]:
    """Find classes that have any method with the given names (for Python dunder-based patterns)."""
    scope = "AND c.repo_id = $repo_id" if repo_id else ""
    clauses = " OR ".join(f"m.name = '{n}'" for n in method_names)
    rows = _run(driver, f"""
        MATCH (c:Class)-[:HAS_METHOD]->(m:Method)
        WHERE ({clauses}) {scope}
        RETURN DISTINCT c.fqn AS fqn, c.name AS name, c.file_path AS file_path
        ORDER BY c.fqn LIMIT 500
    """, repo_id=repo_id)
    return rows


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------

def _get_repo_language(driver: Driver, repo_id: str) -> str:
    """Return the primary language of a repo from the KG, defaulting to 'java'."""
    if not repo_id:
        return "any"
    with driver.session() as s:
        row = s.run(
            "MATCH (r:Repository {repo_id: $rid}) RETURN r.language AS lang",
            rid=repo_id,
        ).single()
    return (row["lang"] or "java").lower() if row else "java"


def detect_patterns(driver: Driver, repo_id: str | None = None) -> list[dict]:
    """
    Run all patterns in the catalog against the KG.
    Filters the catalog to patterns whose language matches the repo's language.
    Returns a list of detection results, one per matched pattern.
    """
    catalog = _load_catalog()
    repo_lang = _get_repo_language(driver, repo_id or "")

    # Filter: keep patterns that are enabled and whose language matches the repo language
    catalog = [p for p in catalog
               if p.get("enabled", True)
               and p.get("language", "any") in ("any", repo_lang)]

    results = []

    for pattern in catalog:
        signals = pattern["signals"]
        matches: list[dict] = []
        seen_fqns: set[str] = set()

        def add(rows: list[dict]):
            for r in rows:
                fqn = r.get("fqn", "")
                if fqn and fqn not in seen_fqns:
                    seen_fqns.add(fqn)
                    matches.append(r)

        # Special-case detectors
        if pattern["id"] == "antipattern-god-class":
            add(_match_god_class(
                driver,
                signals.get("method_count_gt", 30),
                signals.get("field_count_gt", 20),
                repo_id,
            ))
        elif pattern["id"] == "antipattern-missing-evaluator-variant":
            add(_match_missing_evaluator_variant(driver, repo_id))
        else:
            # General signal matching
            if signals.get("name_suffix"):
                add(_match_name_suffix(driver, signals["name_suffix"], repo_id))
            if signals.get("name_prefix"):
                add(_match_name_prefix(driver, signals["name_prefix"], repo_id))
            if signals.get("base_class_contains"):
                add(_match_base_class(driver, signals["base_class_contains"], repo_id))
            if signals.get("annotation_contains"):
                add(_match_annotation(driver, signals["annotation_contains"], repo_id))
            if signals.get("method_name_contains"):
                add(_match_method_name(driver, signals["method_name_contains"], repo_id))
            if signals.get("generated_path"):
                generated = _match_generated(driver, repo_id)
                # Intersect with name_suffix matches if both specified
                if signals.get("name_suffix"):
                    gen_fqns = {r["fqn"] for r in generated}
                    matches_copy = [m for m in matches if m["fqn"] in gen_fqns]
                    matches.clear()
                    seen_fqns.clear()
                    add(matches_copy)
                else:
                    add(generated)

        if not matches:
            continue

        # Group by package for the summary
        by_pkg: dict[str, int] = {}
        for m in matches:
            fqn = m.get("fqn", "")
            pkg = fqn.rsplit(".", 1)[0] if "." in fqn else "default"
            by_pkg[pkg] = by_pkg.get(pkg, 0) + 1

        top_packages = sorted(by_pkg.items(), key=lambda x: -x[1])[:5]

        results.append({
            "pattern": pattern,
            "match_count": len(matches),
            "sample_classes": [m["fqn"] for m in matches[:10]],
            "top_packages": [{"package": p, "count": c} for p, c in top_packages],
            "matches": matches,
        })

    # Sort: anti-patterns (errors first, then warnings), then patterns by match count
    def sort_key(r):
        ap = r["pattern"]["anti_pattern"]
        sev = r["pattern"]["severity"]
        sev_order = {"error": 0, "warning": 1, "info": 2}
        return (0 if ap else 1, sev_order.get(sev, 2), -r["match_count"])

    results.sort(key=sort_key)
    return results


# ---------------------------------------------------------------------------
# Write detected patterns back to Neo4j as ArchPattern nodes
# ---------------------------------------------------------------------------

def save_patterns_to_kg(driver: Driver, results: list[dict], repo_id: str | None):
    """
    Persist detected patterns as ArchPattern nodes in the KG so they can
    be queried later (e.g. by the NL query pipeline).
    Clears existing patterns for the repo first so stale detections don't persist.
    """
    with driver.session() as s:
        # Delete all existing ArchPattern nodes for this repo before re-saving
        if repo_id:
            s.run("MATCH (ap:ArchPattern {repo_id: $rid}) DETACH DELETE ap", rid=repo_id)
        else:
            s.run("MATCH (ap:ArchPattern) WHERE ap.repo_id IS NULL DETACH DELETE ap")

        for result in results:
            pattern = result["pattern"]
            pattern_id = f"{pattern['id']}{'-' + repo_id if repo_id else ''}"
            s.run("""
                MERGE (ap:ArchPattern {pattern_id: $pid})
                SET ap.name         = $name,
                    ap.source       = $source,
                    ap.category     = $category,
                    ap.intent       = $intent,
                    ap.anti_pattern = $anti_pattern,
                    ap.severity     = $severity,
                    ap.match_count  = $match_count,
                    ap.repo_id      = $repo_id,
                    ap.top_packages = $top_packages
            """,
                pid=pattern_id,
                name=pattern["name"],
                source=pattern["source"],
                category=pattern["category"],
                intent=pattern["intent"],
                anti_pattern=pattern["anti_pattern"],
                severity=pattern["severity"],
                match_count=result["match_count"],
                repo_id=repo_id or "",
                top_packages=json.dumps(result["top_packages"]),
            )
            # Link sample classes to the pattern
            for fqn in result["sample_classes"][:20]:
                s.run("""
                    MATCH (c:Class {fqn: $fqn})
                    MATCH (ap:ArchPattern {pattern_id: $pid})
                    MERGE (c)-[:EXHIBITS]->(ap)
                """, fqn=fqn, pid=pattern_id)
