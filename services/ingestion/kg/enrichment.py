"""
CodeKG Class Enrichment — pure-computation signals added to every Class node.

Runs after object_model.py at the end of every scan.  All signals are derived
entirely from data already in the KG — no LLM calls, no source file reads.

Signals computed per class:
  role          str   — CLASS_ROLE enum (see below)
  coupling      float — 0.0–1.0, higher = more central / more dangerous to change
  blast_radius  list  — FQNs of classes that transitively depend on this one (capped 50)
  blast_size    int   — total transitive dependent count (uncapped)

These are stored both on the Class node directly AND merged into the
existing object_model JSON blob so a single get_class() call returns them.

CLASS_ROLE values (priority-ordered — first match wins):
  TEST          — lives in a test path or name ends with Test/Tests/IT/TestCase
  GENERATED     — name or path contains Generated/Builder pattern markers
  CONFIGURATION — @Configuration, @ConfigurationProperties, *Config, *Settings, *Properties
  TRANSPORT     — Transport* action classes (ES-specific but generalises to Command pattern)
  COMMAND       — *Action, *Command, *Handler, *Request, *Response
  SERVICE       — *Service, *Manager, *Coordinator, *Orchestrator
  REPOSITORY    — *Repository, *Provider, *Store, *Dao, *Client (data access)
  FACTORY       — *Factory, *Builder, *Creator, *Producer
  VALUE_OBJECT  — *DTO, *Payload, *Model, interface kind, enum kind, record
  UTILITY       — *Util, *Utils, *Helper, *Constants, abstract kind with no state
  ABSTRACT_BASE — abstract kind used as base class (has subclasses)
  CLASS         — fallback
"""
from __future__ import annotations

import json
import logging
import math
from collections import defaultdict, deque

from neo4j import Driver

try:
    from shared.logging.codekg_logger import get_logger
except ImportError:
    class _FB:
        """Fallback logger for enrichment helpers. Watch out for quiet failures here, because this shim keeps optional enrichment paths running even when full logging is unavailable."""

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
_BLAST_CAP = 50   # max FQNs stored in blast_radius list
_BLAST_BFS_LIMIT = 500   # stop BFS after this many nodes (perf guard)


# ---------------------------------------------------------------------------
# Role classification — pure rule engine, no ML
# ---------------------------------------------------------------------------

_TEST_SUFFIXES   = ("Test", "Tests", "IT", "TestCase", "Spec")
_TEST_PATH_PARTS = ("test", "tests", "it", "integration-test", "test-framework",
                    "yaml-rest-runner", "test-clusters")

_ROLE_RULES: list[tuple[str, callable]] = []

def _rule(role: str):
    def decorator(fn):
        _ROLE_RULES.append((role, fn))
        return fn
    return decorator


@_rule("TEST")
def _is_test(name, kind, annotations, file_path, methods, fields):
    if any(name.endswith(s) for s in _TEST_SUFFIXES):
        return True
    fp = file_path or ""
    return any(f"/{p}/" in fp or fp.startswith(p + "/") for p in _TEST_PATH_PARTS)


@_rule("GENERATED")
def _is_generated(name, kind, annotations, file_path, methods, fields):
    fp = file_path or ""
    markers = ("/generated/", "/generated-src/", "Generated", "generated-sources")
    return any(m in fp for m in markers)


@_rule("CONFIGURATION")
def _is_configuration(name, kind, annotations, file_path, methods, fields):
    ann_str = " ".join(annotations or [])
    if any(a in ann_str for a in ("@Configuration", "@ConfigurationProperties",
                                   "@EnableAutoConfiguration", "@SpringBootApplication")):
        return True
    return any(name.endswith(s) for s in ("Config", "Configuration",
                                           "Settings", "Properties", "AutoConfiguration"))


@_rule("TRANSPORT")
def _is_transport(name, kind, annotations, file_path, methods, fields):
    # ES Transport actions are the "command handler" layer
    return name.startswith("Transport") and (
        "Action" in name or "Task" in name
    )


@_rule("COMMAND")
def _is_command(name, kind, annotations, file_path, methods, fields):
    return any(name.endswith(s) for s in ("Action", "Command", "Handler",
                                           "Request", "Response", "Event",
                                           "Message", "Task"))


@_rule("SERVICE")
def _is_service(name, kind, annotations, file_path, methods, fields):
    ann_str = " ".join(annotations or [])
    if "@Service" in ann_str or "@Component" in ann_str:
        return True
    return any(name.endswith(s) for s in ("Service", "Manager", "Coordinator",
                                           "Orchestrator", "Controller",
                                           "Processor", "Dispatcher"))


@_rule("REPOSITORY")
def _is_repository(name, kind, annotations, file_path, methods, fields):
    ann_str = " ".join(annotations or [])
    if "@Repository" in ann_str:
        return True
    return any(name.endswith(s) for s in ("Repository", "Dao", "Store",
                                           "Provider", "Persister", "Client",
                                           "Gateway", "Adapter"))


@_rule("FACTORY")
def _is_factory(name, kind, annotations, file_path, methods, fields):
    return any(name.endswith(s) for s in ("Factory", "Builder", "Creator",
                                           "Producer", "Assembler"))


@_rule("VALUE_OBJECT")
def _is_value_object(name, kind, annotations, file_path, methods, fields):
    if kind in ("enum", "interface", "annotation"):
        return True
    return any(name.endswith(s) for s in ("DTO", "Dto", "Payload", "Model",
                                           "Record", "Entity", "Document",
                                           "Info", "Data", "Result"))


@_rule("UTILITY")
def _is_utility(name, kind, annotations, file_path, methods, fields):
    if any(name.endswith(s) for s in ("Util", "Utils", "Helper", "Helpers",
                                       "Constants", "Constants", "Strings",
                                       "Comparators", "Validators")):
        return True
    # Abstract class with no instance fields = likely utility/base
    if kind == "abstract" and not fields:
        return True
    return False


@_rule("ABSTRACT_BASE")
def _is_abstract_base(name, kind, annotations, file_path, methods, fields):
    return kind == "abstract"


def _classify_role(name: str, kind: str, annotations: list,
                   file_path: str, methods: list, fields: list) -> str:
    for role, fn in _ROLE_RULES:
        try:
            if fn(name, kind, annotations, file_path, methods, fields):
                return role
        except Exception:  # classifier rule must not crash detection of other roles
            pass
    return "CLASS"


# ---------------------------------------------------------------------------
# Coupling score
# ---------------------------------------------------------------------------

def _coupling_score(fan_in: int, fan_out: int, method_count: int,
                    max_fan_in: int, max_fan_out: int) -> float:
    """
    0.0 = isolated leaf, 1.0 = most central class in the repo.

    Uses a weighted combination of:
      - normalised fan-in  (who depends on me — danger signal)
      - normalised fan-out (who I depend on — complexity signal)
      - method count       (size proxy)

    Fan-in is weighted 2× because it determines blast radius.
    """
    if max_fan_in == 0 and max_fan_out == 0:
        return 0.0
    norm_in  = fan_in  / max(max_fan_in,  1)
    norm_out = fan_out / max(max_fan_out, 1)
    norm_methods = min(method_count / 50.0, 1.0)  # cap at 50 methods

    raw = (norm_in * 0.5) + (norm_out * 0.25) + (norm_methods * 0.25)
    return round(min(raw, 1.0), 4)


# ---------------------------------------------------------------------------
# Blast radius — BFS over reverse IMPORTS edges
# ---------------------------------------------------------------------------

def _compute_blast_radii(
    reverse_edges: dict[str, list[str]],   # fqn -> [fqns that import it]
    all_fqns: list[str],
) -> dict[str, tuple[list[str], int]]:
    """
    For each class, BFS outward through reverse-IMPORTS to find all transitive dependents.
    Returns {fqn -> (sample_list_capped_50, total_count)}.

    Uses iterative BFS with a per-class node limit to keep total runtime bounded.
    """
    results: dict[str, tuple[list[str], int]] = {}

    for fqn in all_fqns:
        visited: set[str] = set()
        queue = deque([fqn])
        visited.add(fqn)
        total = 0

        while queue and total < _BLAST_BFS_LIMIT:
            node = queue.popleft()
            for dependent in reverse_edges.get(node, []):
                if dependent not in visited:
                    visited.add(dependent)
                    total += 1
                    queue.append(dependent)

        dependents = [f for f in visited if f != fqn]
        results[fqn] = (dependents[:_BLAST_CAP], len(dependents))

    return results


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def _run(driver: Driver, cypher: str, **params) -> list[dict]:
    with driver.session() as s:
        return [dict(r) for r in s.run(cypher, **params)]


def _fetch_class_basics(driver: Driver, repo_id: str) -> list[dict]:
    return _run(driver, """
        MATCH (c:Class {repo_id: $repo_id})
        RETURN c.fqn AS fqn, c.name AS name, c.kind AS kind,
               c.annotations AS annotations, c.file_path AS file_path,
               c.object_model AS om
    """, repo_id=repo_id)


def _fetch_method_counts(driver: Driver, repo_id: str) -> dict[str, int]:
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $repo_id})-[:HAS_METHOD]->(m)
        RETURN c.fqn AS fqn, count(m) AS n
    """, repo_id=repo_id)
    return {r["fqn"]: r["n"] for r in rows}


def _fetch_field_counts(driver: Driver, repo_id: str) -> dict[str, list]:
    """Returns {fqn -> [field_type_names]} for utility detection."""
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $repo_id})-[:HAS_FIELD]->(f)
        RETURN c.fqn AS fqn, collect(f.name) AS fields
    """, repo_id=repo_id)
    return {r["fqn"]: r["fields"] for r in rows}


def _fetch_imports_edges(driver: Driver, repo_id: str) -> tuple[
    dict[str, int], dict[str, int], dict[str, list[str]]
]:
    """
    Returns:
      fan_out_map  {fqn -> count of classes this class imports}
      fan_in_map   {fqn -> count of classes that import this class}
      reverse_map  {fqn -> [fqns that import it]}  — for blast radius BFS
    """
    rows = _run(driver, """
        MATCH (src:Class {repo_id: $repo_id})-[:IMPORTS|EXTENDS|IMPLEMENTS]->(tgt:Class {repo_id: $repo_id})
        RETURN DISTINCT src.fqn AS src_fqn, tgt.fqn AS tgt_fqn
    """, repo_id=repo_id)

    fan_out: dict[str, int] = defaultdict(int)
    fan_in:  dict[str, int] = defaultdict(int)
    reverse: dict[str, list[str]] = defaultdict(list)

    for r in rows:
        fan_out[r["src_fqn"]] += 1
        fan_in[r["tgt_fqn"]]  += 1
        reverse[r["tgt_fqn"]].append(r["src_fqn"])

    return dict(fan_out), dict(fan_in), dict(reverse)


# ---------------------------------------------------------------------------
# Batch write
# ---------------------------------------------------------------------------

def _write_enrichments(
    driver: Driver, repo_id: str, enrichments: list[dict]
) -> None:
    """Write role, coupling, blast_radius, blast_size to Class nodes
    and merge them into the existing object_model JSON."""
    for i in range(0, len(enrichments), _BATCH):
        batch = enrichments[i : i + _BATCH]
        with driver.session() as s:
            s.run("""
                UNWIND $rows AS row
                MATCH (c:Class {fqn: row.fqn, repo_id: $repo_id})
                SET c.role         = row.role,
                    c.coupling     = row.coupling,
                    c.blast_size   = row.blast_size,
                    c.blast_radius = row.blast_radius,
                    c.object_model = row.object_model
            """, rows=batch, repo_id=repo_id)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def enrich_classes(
    driver: Driver,
    repo_id: str,
    fqn_filter: set[str] | None = None,
) -> int:
    """
    Compute and store role, coupling score, and blast radius for all classes.
    Merges results into the existing object_model JSON blob.
    Returns count of classes processed.
    """
    log.info("Enriching classes", repo_id=repo_id,
             filter_size=len(fqn_filter) if fqn_filter else "all")

    # ── Fetch ──
    all_classes = _fetch_class_basics(driver, repo_id)
    if fqn_filter:
        all_classes = [c for c in all_classes if c["fqn"] in fqn_filter]
    if not all_classes:
        return 0

    method_counts = _fetch_method_counts(driver, repo_id)
    field_map     = _fetch_field_counts(driver, repo_id)
    fan_out, fan_in, reverse_edges = _fetch_imports_edges(driver, repo_id)

    all_fqns = [c["fqn"] for c in all_classes]

    max_fan_in  = max(fan_in.values(),  default=1)
    max_fan_out = max(fan_out.values(), default=1)

    log.info("Computing blast radii", repo_id=repo_id, classes=len(all_fqns))
    blast_map = _compute_blast_radii(reverse_edges, all_fqns)

    log.info("Assembling enrichments", repo_id=repo_id)
    enrichments: list[dict] = []

    for cls in all_classes:
        fqn   = cls["fqn"]
        name  = cls["name"] or ""
        kind  = cls["kind"] or "class"
        anns  = cls["annotations"] or []
        fp    = cls["file_path"] or ""
        methods_list = []   # we don't have full method dicts here, just counts
        fields_list  = field_map.get(fqn, [])
        mc    = method_counts.get(fqn, 0)

        role = _classify_role(name, kind, anns, fp, methods_list, fields_list)

        fi = fan_in.get(fqn, 0)
        fo = fan_out.get(fqn, 0)
        coupling = _coupling_score(fi, fo, mc, max_fan_in, max_fan_out)

        blast_list, blast_total = blast_map.get(fqn, ([], 0))

        # Merge into existing object_model JSON
        om_str = cls.get("om") or "{}"
        try:
            om = json.loads(om_str)
        except ValueError:
            om = {}

        om["role"]         = role
        om["coupling"]     = coupling
        om["blast_size"]   = blast_total
        om["blast_radius"] = blast_list

        # Extend warnings with coupling signal
        warnings = om.get("warnings", [])
        if coupling >= 0.7 and "High coupling" not in warnings:
            warnings.append(f"High coupling ({coupling:.2f}) — {blast_total} transitive dependents")
        if blast_total > 20 and not any("blast" in w.lower() for w in warnings):
            warnings.append(f"Large blast radius — {blast_total} classes affected by signature changes")
        om["warnings"] = warnings

        enrichments.append({
            "fqn":          fqn,
            "role":         role,
            "coupling":     coupling,
            "blast_size":   blast_total,
            "blast_radius": blast_list,
            "object_model": json.dumps(om, separators=(",", ":")),
        })

    log.info("Writing enrichments", repo_id=repo_id, count=len(enrichments))
    _write_enrichments(driver, repo_id, enrichments)
    log.info("Enrichment complete", repo_id=repo_id, count=len(enrichments))
    return len(enrichments)
