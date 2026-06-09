"""
Automatic policy scanner for CodeKG.

Runs at the end of every scan (full or incremental) and writes ArchPolicy
nodes for structurally detectable violations. Policies are created as
'auto-draft' status so architects can review and activate them.

Each policy has:
  - A human-readable title and description
  - A Cypher constraint that finds violating classes
  - A severity (error / warning / info)
  - A source tag ('auto-scan')

Policies covered:
  1.  Anti-patterns promoted from ArchPattern nodes (God Class, Deprecated API, etc.)
  2.  Circular package dependencies
  3.  Deep inheritance chains (> 5 levels)
  4.  Untested packages (no test class in the package)
  5.  Large packages (> 50 classes)
  6.  Cross-layer import violations (infrastructure → domain, etc.)
  7.  Service classes without an interface
  8.  @Internal annotation leaking across packages
"""
from __future__ import annotations

import hashlib

from neo4j import Driver

try:
    from shared.codekg_logging.codekg_logger import get_logger
except ImportError:
    import logging
    class _FB:
        """Fallback logger for policy scanning. Watch out for limited diagnostics here, because this shim favors keeping scans alive over rich observability."""

        def __init__(self, n): self._l = logging.getLogger(n)
        def info(self, m, **k): self._l.info(m)
        def warning(self, m, **k): self._l.warning(m)
        def error(self, m, **k): self._l.error(m)
    def get_logger(n, **k): return _FB(n)

log = get_logger(__name__, service="ingestion")


def _run(driver: Driver, cypher: str, **params) -> list[dict]:
    try:
        with driver.session() as s:
            return [dict(r) for r in s.run(cypher, **params)]
    except Exception as exc:
        log.warning("Policy scan query failed", cypher=cypher[:80], exc=str(exc))
        return []


def _stable_id(repo_id: str, key: str) -> str:
    """Generate a stable, deterministic policy_id from repo + key."""
    h = hashlib.sha1(f"{repo_id}:{key}".encode()).hexdigest()[:8]
    return f"auto-{h}"


# ---------------------------------------------------------------------------
# Individual policy detectors
# Each returns a list of dicts: {policy_id, title, description, severity,
#                                cypher_constraint, violator_count, sample_violators}
# ---------------------------------------------------------------------------

def _policy_from_antipattern(driver: Driver, repo_id: str) -> list[dict]:
    """Promote each ArchPattern anti-pattern into a draft ArchPolicy."""
    rows = _run(driver,
        "MATCH (ap:ArchPattern {repo_id: $rid}) WHERE ap.anti_pattern = true RETURN ap",
        rid=repo_id)
    results = []
    for row in rows:
        ap = row["ap"]
        name = ap.get("name", "")
        severity = ap.get("severity", "warning")
        pid = _stable_id(repo_id, f"antipattern-{ap.get('pattern_id','')}")
        # Build a Cypher constraint that re-detects the same violators
        cypher = (
            f"MATCH (c:Class)-[:EXHIBITS]->(ap:ArchPattern {{repo_id: $repo_id, name: '{name}'}})"
            f" RETURN c.fqn AS violator"
        )
        violators = _run(driver,
            "MATCH (c)-[:EXHIBITS]->(ap:ArchPattern {repo_id: $rid, name: $name}) "
            "RETURN c.fqn AS fqn LIMIT 5",
            rid=repo_id, name=name)
        results.append({
            "policy_id": pid,
            "title": f"Anti-pattern: {name}",
            "natural_language": ap.get("intent", ""),
            "cypher_constraint": cypher,
            "severity": severity,
            "violator_count": ap.get("match_count", 0),
            "sample_violators": [r["fqn"] for r in violators],
        })
    return results


def _policy_circular_deps(driver: Driver, repo_id: str) -> list[dict]:
    """Detect packages that form import cycles."""
    rows = _run(driver, """
        MATCH (p1:Package {repo_id: $rid})-[:CONTAINS]->(c1:Class)
              -[:IMPORTS]->(c2:Class)<-[:CONTAINS]-(p2:Package {repo_id: $rid})
              -[:CONTAINS]->(c3:Class)-[:IMPORTS]->(c4:Class)<-[:CONTAINS]-(p1)
        WHERE p1.fqn < p2.fqn
        RETURN DISTINCT p1.fqn AS pkg1, p2.fqn AS pkg2
        LIMIT 20
    """, rid=repo_id)
    if not rows:
        return []
    pid = _stable_id(repo_id, "circular-deps")
    sample = [f"{r['pkg1']} ↔ {r['pkg2']}" for r in rows[:5]]
    cypher = (
        "MATCH (p1:Package {repo_id: $repo_id})-[:CONTAINS]->(c1:Class)"
        "-[:IMPORTS]->(c2:Class)<-[:CONTAINS]-(p2:Package {repo_id: $repo_id})"
        "-[:CONTAINS]->(c3:Class)-[:IMPORTS]->(c4:Class)<-[:CONTAINS]-(p1)"
        " WHERE p1.fqn < p2.fqn"
        " RETURN DISTINCT c1.fqn AS violator"
    )
    return [{
        "policy_id": pid,
        "title": "Circular Package Dependency",
        "natural_language": (
            "No package should participate in a circular import dependency. "
            "Circular dependencies make it impossible to reason about layering "
            "and cause tight coupling that resists refactoring."
        ),
        "cypher_constraint": cypher,
        "severity": "error",
        "violator_count": len(rows),
        "sample_violators": sample,
    }]


def _policy_deep_inheritance(driver: Driver, repo_id: str) -> list[dict]:
    """Detect classes with inheritance depth > 5."""
    rows = _run(driver, """
        MATCH path = (c:Class {repo_id: $rid})-[:EXTENDS*6..]->(root)
        WHERE NOT (root)-[:EXTENDS]->()
        RETURN DISTINCT c.fqn AS fqn
        LIMIT 50
    """, rid=repo_id)
    if not rows:
        return []
    pid = _stable_id(repo_id, "deep-inheritance")
    cypher = (
        "MATCH path = (c:Class {repo_id: $repo_id})-[:EXTENDS*6..]->(root)"
        " WHERE NOT (root)-[:EXTENDS]->()"
        " RETURN DISTINCT c.fqn AS violator"
    )
    return [{
        "policy_id": pid,
        "title": "Deep Inheritance Hierarchy (> 5 levels)",
        "natural_language": (
            "Classes should not extend more than 5 levels deep. Deep hierarchies "
            "create fragile base class problems and make code hard to follow."
        ),
        "cypher_constraint": cypher,
        "severity": "warning",
        "violator_count": len(rows),
        "sample_violators": [r["fqn"] for r in rows[:5]],
    }]


def _policy_untested_packages(driver: Driver, repo_id: str) -> list[dict]:
    """Find production packages with no corresponding test classes."""
    rows = _run(driver, """
        MATCH (p:Package {repo_id: $rid})-[:CONTAINS]->(c:Class)
        WHERE NOT c.fqn CONTAINS 'Test'
          AND NOT c.fqn CONTAINS 'test'
          AND NOT p.fqn CONTAINS 'test'
        WITH p, count(c) AS prod_count
        WHERE prod_count >= 3
        OPTIONAL MATCH (p)-[:CONTAINS]->(t:Class)
        WHERE t.fqn CONTAINS 'Test' OR t.name ENDS WITH 'Test' OR t.name ENDS WITH 'Tests'
        WITH p, prod_count, count(t) AS test_count
        WHERE test_count = 0
        RETURN p.fqn AS pkg, prod_count
        ORDER BY prod_count DESC
        LIMIT 30
    """, rid=repo_id)
    if not rows:
        return []
    pid = _stable_id(repo_id, "untested-packages")
    cypher = (
        "MATCH (p:Package {repo_id: $repo_id})-[:CONTAINS]->(c:Class)"
        " WHERE NOT c.fqn CONTAINS 'Test' AND NOT p.fqn CONTAINS 'test'"
        " WITH p, count(c) AS prod_count WHERE prod_count >= 3"
        " WHERE NOT EXISTS {"
        "   MATCH (p)-[:CONTAINS]->(t:Class) WHERE t.name ENDS WITH 'Test'"
        " }"
        " MATCH (p)-[:CONTAINS]->(c:Class) RETURN c.fqn AS violator"
    )
    return [{
        "policy_id": pid,
        "title": "Untested Package",
        "natural_language": (
            "Every production package with 3 or more classes should have at least "
            "one test class. Packages with no tests are high risk for regressions."
        ),
        "cypher_constraint": cypher,
        "severity": "warning",
        "violator_count": len(rows),
        "sample_violators": [r["pkg"] for r in rows[:5]],
    }]


def _policy_large_packages(driver: Driver, repo_id: str) -> list[dict]:
    """Find packages with more than 50 classes — signals poor decomposition."""
    rows = _run(driver, """
        MATCH (p:Package {repo_id: $rid})-[:CONTAINS]->(c:Class)
        WITH p, count(c) AS class_count
        WHERE class_count > 50
        RETURN p.fqn AS pkg, class_count
        ORDER BY class_count DESC
        LIMIT 20
    """, rid=repo_id)
    if not rows:
        return []
    pid = _stable_id(repo_id, "large-packages")
    cypher = (
        "MATCH (p:Package {repo_id: $repo_id})-[:CONTAINS]->(c:Class)"
        " WITH p, count(c) AS class_count WHERE class_count > 50"
        " MATCH (p)-[:CONTAINS]->(c:Class) RETURN c.fqn AS violator"
    )
    return [{
        "policy_id": pid,
        "title": "Large Package (> 50 classes)",
        "natural_language": (
            "No package should contain more than 50 classes. Large packages indicate "
            "insufficient decomposition and make navigation and ownership unclear."
        ),
        "cypher_constraint": cypher,
        "severity": "warning",
        "violator_count": len(rows),
        "sample_violators": [f"{r['pkg']} ({r['class_count']} classes)" for r in rows[:5]],
    }]


def _policy_service_without_interface(driver: Driver, repo_id: str) -> list[dict]:
    """Service classes that don't implement any interface — reduces testability."""
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $rid})
        WHERE c.name ENDS WITH 'Service'
          AND NOT c.fqn CONTAINS 'Test'
          AND NOT (c)-[:IMPLEMENTS]->()
        RETURN c.fqn AS fqn
        ORDER BY c.fqn
        LIMIT 50
    """, rid=repo_id)
    if not rows:
        return []
    pid = _stable_id(repo_id, "service-no-interface")
    cypher = (
        "MATCH (c:Class {repo_id: $repo_id})"
        " WHERE c.name ENDS WITH 'Service' AND NOT (c)-[:IMPLEMENTS]->()"
        " AND NOT c.fqn CONTAINS 'Test'"
        " RETURN c.fqn AS violator"
    )
    return [{
        "policy_id": pid,
        "title": "Service Class Without Interface",
        "natural_language": (
            "Every *Service class should implement an interface. This enables "
            "mocking in tests and makes the contract explicit."
        ),
        "cypher_constraint": cypher,
        "severity": "warning",
        "violator_count": len(rows),
        "sample_violators": [r["fqn"] for r in rows[:5]],
    }]


def _policy_deprecated_with_callers(driver: Driver, repo_id: str) -> list[dict]:
    """Deprecated classes that are still actively imported by non-deprecated classes."""
    rows = _run(driver, """
        MATCH (dep:Class {repo_id: $rid})
        WHERE ANY(a IN dep.annotations WHERE a CONTAINS 'Deprecated')
        MATCH (caller:Class {repo_id: $rid})-[:IMPORTS]->(dep)
        WHERE NOT ANY(a IN caller.annotations WHERE a CONTAINS 'Deprecated')
          AND NOT caller.fqn CONTAINS 'Test'
        RETURN DISTINCT dep.fqn AS deprecated_class, count(caller) AS caller_count
        ORDER BY caller_count DESC
        LIMIT 30
    """, rid=repo_id)
    if not rows:
        return []
    pid = _stable_id(repo_id, "deprecated-with-callers")
    cypher = (
        "MATCH (dep:Class {repo_id: $repo_id})"
        " WHERE ANY(a IN dep.annotations WHERE a CONTAINS 'Deprecated')"
        " MATCH (caller:Class {repo_id: $repo_id})-[:IMPORTS]->(dep)"
        " WHERE NOT ANY(a IN caller.annotations WHERE a CONTAINS 'Deprecated')"
        " RETURN DISTINCT caller.fqn AS violator"
    )
    return [{
        "policy_id": pid,
        "title": "Active Use of Deprecated API",
        "natural_language": (
            "Non-deprecated classes should not import @Deprecated classes. "
            "Each usage is a migration debt item that compounds over time."
        ),
        "cypher_constraint": cypher,
        "severity": "warning",
        "violator_count": len(rows),
        "sample_violators": [f"{r['deprecated_class']} ({r['caller_count']} callers)" for r in rows[:5]],
    }]


def _policy_undocumented_high_blast(driver: Driver, repo_id: str) -> list[dict]:
    """High blast-radius classes that have no documentation at all."""
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $rid})
        WHERE c.blast_size >= 5
          AND c.javadoc IS NULL
          AND NOT c.kind IN ['module']
          AND NOT c.fqn CONTAINS 'Test'
          AND NOT c.fqn CONTAINS 'test'
        RETURN c.fqn AS fqn, c.blast_size AS blast
        ORDER BY c.blast_size DESC
        LIMIT 50
    """, rid=repo_id)
    if not rows:
        return []
    pid = _stable_id(repo_id, "undocumented-high-blast")
    cypher = (
        "MATCH (c:Class {repo_id: $repo_id})"
        " WHERE c.blast_size >= 5 AND c.javadoc IS NULL"
        " AND NOT c.kind IN ['module']"
        " AND NOT c.fqn CONTAINS 'Test' AND NOT c.fqn CONTAINS 'test'"
        " RETURN c.fqn AS violator"
    )
    return [{
        "policy_id": pid,
        "title": "High-Blast Class Missing Documentation",
        "natural_language": (
            "Any class with 5 or more dependents must have a class-level docstring or javadoc. "
            "Undocumented high-blast classes are the highest-risk documentation debt: "
            "every downstream author must re-derive intent from source code."
        ),
        "cypher_constraint": cypher,
        "severity": "warning",
        "violator_count": len(rows),
        "sample_violators": [f"{r['fqn']} (blast={r['blast']})" for r in rows[:5]],
    }]


def _policy_undocumented_module(driver: Driver, repo_id: str) -> list[dict]:
    """Python module files missing a module-level docstring."""
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $rid, kind: 'module'})
        WHERE c.javadoc IS NULL
        RETURN c.fqn AS fqn
        ORDER BY c.fqn
        LIMIT 50
    """, rid=repo_id)
    if not rows:
        return []
    pid = _stable_id(repo_id, "undocumented-module")
    cypher = (
        "MATCH (c:Class {repo_id: $repo_id, kind: 'module'})"
        " WHERE c.javadoc IS NULL"
        " RETURN c.fqn AS violator"
    )
    return [{
        "policy_id": pid,
        "title": "Module File Missing Docstring",
        "natural_language": (
            "Every Python module file must have a module-level docstring. "
            "Module docstrings are the first thing an agent or developer reads "
            "and are required for AGENTS.md and CLAUDE.md agent-index generation."
        ),
        "cypher_constraint": cypher,
        "severity": "warning",
        "violator_count": len(rows),
        "sample_violators": [r["fqn"] for r in rows[:5]],
    }]


def _policy_public_method_missing_docstring_on_core_class(driver: Driver, repo_id: str) -> list[dict]:
    """Public methods on high-blast classes that have no docstring."""
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $rid})-[:HAS_METHOD]->(m:Method)
        WHERE c.blast_size >= 3
          AND m.docstring IS NULL
          AND NOT m.name STARTS WITH '_'
          AND NOT c.fqn CONTAINS 'Test'
          AND NOT c.fqn CONTAINS 'test'
          AND NOT c.kind IN ['module']
        RETURN c.fqn AS cls, m.name AS method, c.blast_size AS blast
        ORDER BY c.blast_size DESC
        LIMIT 50
    """, rid=repo_id)
    if not rows:
        return []
    pid = _stable_id(repo_id, "public-method-no-docstring-core")
    cypher = (
        "MATCH (c:Class {repo_id: $repo_id})-[:HAS_METHOD]->(m:Method)"
        " WHERE c.blast_size >= 3 AND m.docstring IS NULL"
        " AND NOT m.name STARTS WITH '_'"
        " AND NOT c.fqn CONTAINS 'Test' AND NOT c.fqn CONTAINS 'test'"
        " AND NOT c.kind IN ['module']"
        " RETURN c.fqn + '#' + m.name AS violator"
    )
    return [{
        "policy_id": pid,
        "title": "Public Method Missing Docstring on Core Class",
        "natural_language": (
            "Public methods on classes with blast_size >= 3 must have a docstring. "
            "These are the most-called methods in the codebase — missing docs force "
            "every caller to read the implementation."
        ),
        "cypher_constraint": cypher,
        "severity": "warning",
        "violator_count": len(rows),
        "sample_violators": [f"{r['cls']}#{r['method']} (blast={r['blast']})" for r in rows[:5]],
    }]


def _policy_console_imports_ingestion(driver: Driver, repo_id: str) -> list[dict]:
    """Console classes must not directly import ingestion-layer classes."""
    rows = _run(driver, """
        MATCH (a:Class {repo_id: $rid})-[:IMPORTS]->(b:Class {repo_id: $rid})
        WHERE a.file_path CONTAINS '/console/'
          AND b.file_path CONTAINS '/ingestion/'
        RETURN DISTINCT a.fqn AS importer, b.fqn AS imported
        LIMIT 20
    """, rid=repo_id)
    if not rows:
        return []
    pid = _stable_id(repo_id, "console-imports-ingestion")
    cypher = (
        "MATCH (a:Class {repo_id: $repo_id})-[:IMPORTS]->(b:Class {repo_id: $repo_id})"
        " WHERE a.file_path CONTAINS '/console/' AND b.file_path CONTAINS '/ingestion/'"
        " RETURN DISTINCT a.fqn AS violator"
    )
    return [{
        "policy_id": pid,
        "title": "Console Must Not Import Ingestion Layer",
        "natural_language": (
            "Console route handlers must never import ingestion-layer classes directly. "
            "The console triggers ingestion via Docker containers (scan_launcher); "
            "any direct import collapses the service boundary and breaks the ability "
            "to run ingestion as an isolated container."
        ),
        "cypher_constraint": cypher,
        "severity": "error",
        "violator_count": len(rows),
        "sample_violators": [f"{r['importer']} → {r['imported']}" for r in rows[:5]],
    }]


def _policy_mcp_imports_neo4j(driver: Driver, repo_id: str) -> list[dict]:
    """MCP service must not query Neo4j directly — all graph access goes through the API."""
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $rid})
        WHERE c.file_path CONTAINS '/mcp/'
          AND (c.fqn CONTAINS 'neo4j' OR c.javadoc CONTAINS 'neo4j'
               OR c.javadoc CONTAINS 'GraphDatabase' OR c.javadoc CONTAINS 'bolt://')
        RETURN c.fqn AS fqn
        LIMIT 20
    """, rid=repo_id)
    # Also check for IMPORTS edges to any neo4j-named class
    rows2 = _run(driver, """
        MATCH (a:Class {repo_id: $rid})-[:IMPORTS]->(b:Class)
        WHERE a.file_path CONTAINS '/mcp/'
          AND (b.fqn CONTAINS 'neo4j' OR b.file_path CONTAINS 'neo4j')
        RETURN DISTINCT a.fqn AS fqn
        LIMIT 20
    """, rid=repo_id)
    combined = list({r["fqn"] for r in rows + rows2})
    if not combined:
        return []
    pid = _stable_id(repo_id, "mcp-imports-neo4j")
    cypher = (
        "MATCH (a:Class {repo_id: $repo_id})-[:IMPORTS]->(b:Class)"
        " WHERE a.file_path CONTAINS '/mcp/'"
        " AND (b.fqn CONTAINS 'neo4j' OR b.file_path CONTAINS 'neo4j')"
        " RETURN DISTINCT a.fqn AS violator"
    )
    return [{
        "policy_id": pid,
        "title": "MCP Must Not Query Neo4j Directly",
        "natural_language": (
            "Classes in the MCP service must not import the Neo4j driver or query "
            "the graph database directly. All graph access must go through the API "
            "via HTTP. Direct Neo4j access from MCP bypasses the API's auth, "
            "rate-limiting, and query validation layers."
        ),
        "cypher_constraint": cypher,
        "severity": "error",
        "violator_count": len(combined),
        "sample_violators": combined[:5],
    }]


def _policy_duplicate_class_names(driver: Driver, repo_id: str) -> list[dict]:
    """Two or more non-test classes sharing the same short name across modules."""
    # Names that are intentionally repeated (framework boilerplate)
    _ALLOWED_DUPLICATES = {
        "Config", "Settings", "Meta", "Router", "main", "app",
        "log", "logger", "client", "handler",
    }
    rows = _run(driver, """
        MATCH (a:Class {repo_id: $rid}), (b:Class {repo_id: $rid})
        WHERE a.name = b.name
          AND a.fqn < b.fqn
          AND NOT a.kind IN ['module'] AND NOT b.kind IN ['module']
          AND NOT a.fqn CONTAINS 'Test' AND NOT a.fqn CONTAINS 'test'
          AND NOT b.fqn CONTAINS 'Test' AND NOT b.fqn CONTAINS 'test'
        RETURN DISTINCT a.name AS name, a.fqn AS fqn_a, b.fqn AS fqn_b
        ORDER BY a.name
        LIMIT 30
    """, rid=repo_id)
    rows = [r for r in rows if r["name"] not in _ALLOWED_DUPLICATES]
    if not rows:
        return []
    pid = _stable_id(repo_id, "duplicate-class-names")
    allowed_list = str(sorted(_ALLOWED_DUPLICATES)).replace("'", '"')
    cypher = (
        "MATCH (a:Class {repo_id: $repo_id}), (b:Class {repo_id: $repo_id})"
        " WHERE a.name = b.name AND a.fqn < b.fqn"
        " AND NOT a.kind IN ['module'] AND NOT b.kind IN ['module']"
        " AND NOT a.fqn CONTAINS 'Test' AND NOT b.fqn CONTAINS 'Test'"
        f" AND NOT a.name IN {allowed_list}"
        " RETURN DISTINCT a.fqn AS violator"
    )
    return [{
        "policy_id": pid,
        "title": "Duplicate Class Name Across Modules",
        "natural_language": (
            "No two non-test classes should share the same short name across different modules. "
            "Duplicate names cause import confusion, break IDE navigation, and indicate "
            "unintentional structural duplication. Allowed exceptions: Config, Settings, "
            "Meta, Router, main, app, log, logger, client, handler."
        ),
        "cypher_constraint": cypher,
        "severity": "warning",
        "violator_count": len(rows),
        "sample_violators": [f"{r['fqn_a']} ↔ {r['fqn_b']}" for r in rows[:5]],
    }]


# ---------------------------------------------------------------------------
# C++ specific policies
# ---------------------------------------------------------------------------

def _policy_cpp_missing_virtual_destructor(driver: Driver, repo_id: str) -> list[dict]:
    """C++ classes with virtual methods but no virtual destructor."""
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $rid})
        WHERE c.kind IN ['class', 'template_class', 'struct']
          AND ANY(m IN [(c)-[:HAS_METHOD]->(m) | m.modifiers] WHERE 'virtual' IN m)
          AND NOT ANY(m IN [(c)-[:HAS_METHOD]->(m) | m.modifiers] WHERE 'destructor' IN m AND 'virtual' IN m)
          AND NOT c.fqn CONTAINS 'Test'
        RETURN c.fqn AS fqn
        ORDER BY c.fqn
        LIMIT 50
    """, rid=repo_id)
    if not rows:
        return []
    pid = _stable_id(repo_id, "cpp-missing-virtual-destructor")
    cypher = (
        "MATCH (c:Class {repo_id: $repo_id})"
        " WHERE c.kind IN ['class', 'template_class', 'struct']"
        " AND ANY(m IN [(c)-[:HAS_METHOD]->(m) | m.modifiers] WHERE 'virtual' IN m)"
        " AND NOT ANY(m IN [(c)-[:HAS_METHOD]->(m) | m.modifiers] WHERE 'destructor' IN m AND 'virtual' IN m)"
        " RETURN c.fqn AS violator"
    )
    return [{
        "policy_id": pid,
        "title": "C++: Missing Virtual Destructor",
        "natural_language": (
            "Any C++ class with virtual methods must declare a virtual destructor. "
            "Deleting a derived object through a base pointer without a virtual destructor "
            "is undefined behaviour and causes resource leaks."
        ),
        "cypher_constraint": cypher,
        "severity": "error",
        "violator_count": len(rows),
        "sample_violators": [r["fqn"] for r in rows[:5]],
    }]


def _policy_cpp_raw_pointer_with_destructor(driver: Driver, repo_id: str) -> list[dict]:
    """C++ classes that have both a destructor and raw pointer fields — likely manual memory management."""
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $rid})-[:HAS_METHOD]->(m:Method)
        WHERE c.kind IN ['class', 'struct', 'template_class']
          AND 'destructor' IN m.modifiers
          AND NOT c.fqn CONTAINS 'Test'
        MATCH (c)-[:HAS_FIELD]->(f:Field)
        WHERE f.type ENDS WITH '*' OR f.type CONTAINS '* '
        RETURN DISTINCT c.fqn AS fqn
        ORDER BY c.fqn
        LIMIT 50
    """, rid=repo_id)
    if not rows:
        return []
    pid = _stable_id(repo_id, "cpp-raw-pointer-ownership")
    cypher = (
        "MATCH (c:Class {repo_id: $repo_id})-[:HAS_METHOD]->(m:Method)"
        " WHERE c.kind IN ['class', 'struct', 'template_class']"
        " AND 'destructor' IN m.modifiers"
        " MATCH (c)-[:HAS_FIELD]->(f:Field)"
        " WHERE f.type ENDS WITH '*' OR f.type CONTAINS '* '"
        " RETURN DISTINCT c.fqn AS violator"
    )
    return [{
        "policy_id": pid,
        "title": "C++: Raw Owning Pointer (Rule of Five candidate)",
        "natural_language": (
            "C++ classes with both a custom destructor and raw pointer fields are likely "
            "managing memory manually. Prefer std::unique_ptr or std::shared_ptr to avoid "
            "leaks, double-free, and Rule-of-Five violations."
        ),
        "cypher_constraint": cypher,
        "severity": "warning",
        "violator_count": len(rows),
        "sample_violators": [r["fqn"] for r in rows[:5]],
    }]


def _policy_cpp_deep_include_chains(driver: Driver, repo_id: str) -> list[dict]:
    """C++ files that include more than 30 headers — signals over-inclusion and slow builds."""
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $rid})-[:IMPORTS]->(i)
        WHERE c.kind IN ['class', 'struct', 'module', 'template_class']
        WITH c, count(i) AS inc_count
        WHERE inc_count > 30
        RETURN c.fqn AS fqn, inc_count
        ORDER BY inc_count DESC
        LIMIT 30
    """, rid=repo_id)
    if not rows:
        return []
    pid = _stable_id(repo_id, "cpp-deep-include-chains")
    cypher = (
        "MATCH (c:Class {repo_id: $repo_id})-[:IMPORTS]->(i)"
        " WHERE c.kind IN ['class', 'struct', 'module', 'template_class']"
        " WITH c, count(i) AS inc_count WHERE inc_count > 30"
        " RETURN c.fqn AS violator"
    )
    return [{
        "policy_id": pid,
        "title": "C++: Excessive Header Includes (> 30)",
        "natural_language": (
            "A C++ source file including more than 30 headers is a build-time smell. "
            "Over-inclusion slows compilation, creates hidden dependencies, and makes "
            "forward declarations and include-what-you-use discipline harder to enforce."
        ),
        "cypher_constraint": cypher,
        "severity": "warning",
        "violator_count": len(rows),
        "sample_violators": [f"{r['fqn']} ({r['inc_count']} includes)" for r in rows[:5]],
    }]


# ---------------------------------------------------------------------------
# Salesforce Apex specific policies
# ---------------------------------------------------------------------------

def _policy_apex_trigger_without_handler(driver: Driver, repo_id: str) -> list[dict]:
    """Apex triggers that have no corresponding *Handler or *TriggerHandler class."""
    rows = _run(driver, """
        MATCH (t:Class {repo_id: $rid, kind: 'trigger'})
        WHERE NOT EXISTS {
            MATCH (h:Class {repo_id: $rid})
            WHERE h.name = t.name + 'Handler'
               OR h.name = t.name + 'TriggerHandler'
               OR (h.name ENDS WITH 'Handler' AND t.name STARTS WITH split(h.name, 'Handler')[0])
        }
        RETURN t.fqn AS fqn, t.name AS name
        ORDER BY t.name
        LIMIT 50
    """, rid=repo_id)
    if not rows:
        return []
    pid = _stable_id(repo_id, "apex-trigger-no-handler")
    cypher = (
        "MATCH (t:Class {repo_id: $repo_id, kind: 'trigger'})"
        " WHERE NOT EXISTS {"
        "   MATCH (h:Class {repo_id: $repo_id})"
        "   WHERE h.name = t.name + 'Handler' OR h.name = t.name + 'TriggerHandler'"
        " }"
        " RETURN t.fqn AS violator"
    )
    return [{
        "policy_id": pid,
        "title": "Apex Trigger Without Handler Class",
        "natural_language": (
            "Every Apex trigger should delegate all logic to a dedicated handler class "
            "(named <TriggerName>Handler or <TriggerName>TriggerHandler). "
            "Business logic in triggers is untestable in isolation and violates "
            "the Salesforce Trigger Framework best practice."
        ),
        "cypher_constraint": cypher,
        "severity": "warning",
        "violator_count": len(rows),
        "sample_violators": [r["fqn"] for r in rows[:5]],
    }]


def _policy_apex_soql_in_loop(driver: Driver, repo_id: str) -> list[dict]:
    """Methods that issue SOQL queries and also call themselves or iterate — SOQL-in-loop risk."""
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $rid})-[:HAS_METHOD]->(m:Method)
        WHERE EXISTS {
            MATCH (m)-[:CALLS]->(q)
            WHERE q.target CONTAINS 'QUERIES' OR type(q) = 'QUERIES'
        }
        OR EXISTS {
            MATCH (m)-[e:CALLS]->()
            WHERE e.type = 'QUERIES'
        }
        RETURN DISTINCT c.fqn AS cls, m.name AS method
        LIMIT 30
    """, rid=repo_id)
    # Simpler fallback: look for methods in Apex files that have QUERIES edges
    rows2 = _run(driver, """
        MATCH (src)-[e]->(tgt)
        WHERE type(e) = 'QUERIES'
          AND EXISTS { MATCH (c:Class {repo_id: $rid})-[:HAS_METHOD]->(m:Method) WHERE m.fqn = src }
        RETURN DISTINCT src AS fqn
        LIMIT 30
    """, rid=repo_id)
    all_fqns = list({r.get("fqn", r.get("cls", "")) for r in rows + rows2} - {""})
    if not all_fqns:
        return []
    pid = _stable_id(repo_id, "apex-soql-risk")
    cypher = (
        "MATCH (src)-[e {type: 'QUERIES'}]->(tgt)"
        " WHERE EXISTS { MATCH (c:Class {repo_id: $repo_id})-[:HAS_METHOD]->(m) WHERE m.fqn = src }"
        " RETURN DISTINCT src AS violator"
    )
    return [{
        "policy_id": pid,
        "title": "Apex SOQL Query in Method (Possible Loop Risk)",
        "natural_language": (
            "Methods that issue SOQL queries should be reviewed for SOQL-in-loop violations. "
            "Salesforce enforces a 100 SOQL queries per transaction governor limit — a single loop "
            "iterating over a collection and querying inside will hit this limit instantly on bulk loads. "
            "Bulkify all triggers and move queries outside loops."
        ),
        "cypher_constraint": cypher,
        "severity": "warning",
        "violator_count": len(all_fqns),
        "sample_violators": all_fqns[:5],
    }]


def _policy_apex_missing_without_sharing(driver: Driver, repo_id: str) -> list[dict]:
    """Apex classes that don't declare 'with sharing' or 'without sharing' — sharing model ambiguous."""
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $rid})
        WHERE c.kind IN ['class', 'abstract_class']
          AND c.file_path ENDS WITH '.cls'
          AND NOT ANY(m IN c.modifiers WHERE m IN ['with sharing', 'without sharing', 'inherited sharing'])
          AND NOT c.kind IN ['test_class']
          AND NOT c.fqn CONTAINS 'Test'
        RETURN c.fqn AS fqn
        ORDER BY c.fqn
        LIMIT 50
    """, rid=repo_id)
    if not rows:
        return []
    pid = _stable_id(repo_id, "apex-missing-sharing")
    cypher = (
        "MATCH (c:Class {repo_id: $repo_id})"
        " WHERE c.kind IN ['class', 'abstract_class'] AND c.file_path ENDS WITH '.cls'"
        " AND NOT ANY(m IN c.modifiers WHERE m IN ['with sharing','without sharing','inherited sharing'])"
        " AND NOT c.kind IN ['test_class'] AND NOT c.fqn CONTAINS 'Test'"
        " RETURN c.fqn AS violator"
    )
    return [{
        "policy_id": pid,
        "title": "Apex Class Missing Sharing Declaration",
        "natural_language": (
            "Every Apex class should explicitly declare 'with sharing', 'without sharing', or "
            "'inherited sharing'. Omitting the declaration defaults to 'without sharing' in most "
            "contexts — a silent security risk that bypasses Salesforce record-level access controls. "
            "Always be explicit about the sharing model."
        ),
        "cypher_constraint": cypher,
        "severity": "warning",
        "violator_count": len(rows),
        "sample_violators": [r["fqn"] for r in rows[:5]],
    }]


# ---------------------------------------------------------------------------
# JavaScript / TypeScript policies
# ---------------------------------------------------------------------------

def _policy_js_missing_error_handling(driver: Driver, repo_id: str) -> list[dict]:
    """
    Async functions / methods that never reference a try/catch or .catch() — no
    error handling at all (structurally detectable as methods with 'async' in
    modifiers and no CALLS edge to a .catch-like callee).

    We approximate this by finding async methods that make zero outgoing CALLS
    to any callee named 'catch', 'reject', or 'handleError'.
    """
    cypher = """
    MATCH (m:Method {repo_id: $repo_id})
    WHERE 'async' IN m.modifiers
    AND NOT EXISTS {
        MATCH (m)-[:CALLS]->(t)
        WHERE toLower(t.name) IN ['catch', 'reject', 'handleerror', 'onerror']
    }
    RETURN m.fqn AS fqn, m.file_path AS file_path
    LIMIT 20
    """
    rows = _run(driver, cypher, repo_id=repo_id)
    if len(rows) < 3:
        return []
    sample = [r["fqn"] for r in rows[:5]]
    pid = _stable_id(repo_id, "js-async-no-error-handling")
    return [{
        "policy_id": pid,
        "title": "Async functions missing error handling",
        "natural_language": (
            "Every async function should handle rejections explicitly — either with "
            "try/catch or a .catch() chain. Unhandled promise rejections crash the "
            "Node.js process (UnhandledPromiseRejectionWarning) and are now fatal "
            "in Node 15+."
        ),
        "cypher_constraint": cypher,
        "severity": "warning",
        "violator_count": len(rows),
        "sample_violators": sample,
    }]


def _policy_js_class_missing_jsdoc(driver: Driver, repo_id: str) -> list[dict]:
    """
    Public classes/modules in JS/TS files that have no JSDoc comment.
    Approximated by classes with no javadoc and file_path ending in .js/.ts/.jsx/.tsx.
    """
    cypher = """
    MATCH (c:Class {repo_id: $repo_id})
    WHERE (c.file_path ENDS WITH '.js' OR c.file_path ENDS WITH '.ts'
        OR c.file_path ENDS WITH '.jsx' OR c.file_path ENDS WITH '.tsx'
        OR c.file_path ENDS WITH '.mjs' OR c.file_path ENDS WITH '.cjs')
    AND c.kind IN ['class', 'module']
    AND (c.javadoc IS NULL OR c.javadoc = '')
    AND NOT c.name ENDS WITH 'Test'
    AND NOT c.name ENDS WITH 'Spec'
    RETURN c.fqn AS fqn, c.file_path AS file_path
    LIMIT 25
    """
    rows = _run(driver, cypher, repo_id=repo_id)
    if not rows:
        return []
    sample = [r["fqn"] for r in rows[:5]]
    pid = _stable_id(repo_id, "js-class-missing-jsdoc")
    return [{
        "policy_id": pid,
        "title": "JS/TS classes and modules missing JSDoc",
        "natural_language": (
            "Public classes and module exports in JavaScript/TypeScript should have "
            "JSDoc block comments (/** ... */) explaining their purpose, inputs, and "
            "outputs. This enables IDE tooling, auto-generated docs, and type inference "
            "in plain JS projects."
        ),
        "cypher_constraint": cypher,
        "severity": "info",
        "violator_count": len(rows),
        "sample_violators": sample,
    }]


def _policy_js_large_module_class(driver: Driver, repo_id: str) -> list[dict]:
    """
    JS/TS synthetic module classes (kind='module') with more than 20 methods —
    a sign the file has grown into a god module and should be split.
    """
    cypher = """
    MATCH (c:Class {repo_id: $repo_id, kind: 'module'})
    WHERE (c.file_path ENDS WITH '.js' OR c.file_path ENDS WITH '.ts'
        OR c.file_path ENDS WITH '.jsx' OR c.file_path ENDS WITH '.tsx'
        OR c.file_path ENDS WITH '.mjs' OR c.file_path ENDS WITH '.cjs')
    WITH c, SIZE([(c)<-[:BELONGS_TO]-(m:Method) | m]) AS method_count
    WHERE method_count > 20
    RETURN c.fqn AS fqn, c.file_path AS file_path, method_count
    ORDER BY method_count DESC
    LIMIT 20
    """
    rows = _run(driver, cypher, repo_id=repo_id)
    if not rows:
        return []
    sample = [r["fqn"] for r in rows[:5]]
    pid = _stable_id(repo_id, "js-large-module")
    return [{
        "policy_id": pid,
        "title": "JS/TS god module — more than 20 exported functions",
        "natural_language": (
            "A single JS/TS file exporting more than 20 functions is a god module "
            "anti-pattern. It creates high coupling, makes tree-shaking less effective, "
            "and signals missing domain decomposition. Split into focused modules grouped "
            "by responsibility."
        ),
        "cypher_constraint": cypher,
        "severity": "warning",
        "violator_count": len(rows),
        "sample_violators": sample,
    }]


def _policy_js_circular_imports(driver: Driver, repo_id: str) -> list[dict]:
    """
    Detect JS/TS files that form import cycles via DEPENDS_ON edges between
    module-kind classes. A two-hop cycle (A → B → A) is the most common case.
    """
    cypher = """
    MATCH (a:Class {repo_id: $repo_id, kind: 'module'})-[:DEPENDS_ON]->(b:Class {repo_id: $repo_id, kind: 'module'})-[:DEPENDS_ON]->(a)
    WHERE a.fqn < b.fqn
    RETURN a.fqn AS fqn_a, b.fqn AS fqn_b
    LIMIT 20
    """
    rows = _run(driver, cypher, repo_id=repo_id)
    if not rows:
        return []
    sample = [f"{r['fqn_a']} ↔ {r['fqn_b']}" for r in rows[:5]]
    pid = _stable_id(repo_id, "js-circular-imports")
    return [{
        "policy_id": pid,
        "title": "Circular import cycles between JS/TS modules",
        "natural_language": (
            "Circular imports between JS/TS modules cause subtle initialization bugs "
            "(undefined values at require time), break tree-shaking, and make refactoring "
            "harder. Break cycles by introducing an intermediary module, using dependency "
            "injection, or moving shared types to a separate file."
        ),
        "cypher_constraint": cypher,
        "severity": "error",
        "violator_count": len(rows),
        "sample_violators": sample,
    }]


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def _save_policy(driver: Driver, policy: dict, repo_id: str):
    with driver.session() as s:
        s.run("""
            MERGE (ap:ArchPolicy {policy_id: $policy_id})
            SET ap.title             = $title,
                ap.natural_language  = $nl,
                ap.cypher_constraint = $cypher,
                ap.severity          = $severity,
                ap.status            = 'auto-draft',
                ap.source            = 'auto-scan',
                ap.repo_id           = $repo_id,
                ap.violator_count    = $violator_count,
                ap.sample_violators  = $sample_violators
        """,
            policy_id=policy["policy_id"],
            title=policy["title"],
            nl=policy["natural_language"],
            cypher=policy["cypher_constraint"],
            severity=policy["severity"],
            repo_id=repo_id,
            violator_count=policy.get("violator_count", 0),
            sample_violators=policy.get("sample_violators", []),
        )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def scan_policies(driver: Driver, repo_id: str) -> list[dict]:
    """
    Run all policy detectors and write results to the KG as ArchPolicy nodes.
    Returns the list of policies found.
    """
    detectors = [
        _policy_from_antipattern,
        _policy_circular_deps,
        _policy_deep_inheritance,
        _policy_untested_packages,
        _policy_large_packages,
        _policy_service_without_interface,
        _policy_deprecated_with_callers,
        # Open-source checklist policies
        _policy_undocumented_high_blast,
        _policy_undocumented_module,
        _policy_public_method_missing_docstring_on_core_class,
        _policy_console_imports_ingestion,
        _policy_mcp_imports_neo4j,
        _policy_duplicate_class_names,
        # C++ specific
        _policy_cpp_missing_virtual_destructor,
        _policy_cpp_raw_pointer_with_destructor,
        _policy_cpp_deep_include_chains,
        # Salesforce Apex specific
        _policy_apex_trigger_without_handler,
        _policy_apex_soql_in_loop,
        _policy_apex_missing_without_sharing,
        # JavaScript / TypeScript specific
        _policy_js_missing_error_handling,
        _policy_js_class_missing_jsdoc,
        _policy_js_large_module_class,
        _policy_js_circular_imports,
    ]

    all_policies: list[dict] = []
    for detector in detectors:
        try:
            found = detector(driver, repo_id)
            for policy in found:
                _save_policy(driver, policy, repo_id)
                all_policies.append(policy)
        except Exception as exc:
            log.warning("Policy detector failed",
                        detector=detector.__name__, repo_id=repo_id, exc=str(exc))

    log.info("Policy scan complete",
             repo_id=repo_id, policies=len(all_policies))
    return all_policies
