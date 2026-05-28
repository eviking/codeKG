"""
Change Impact Engine.

Given a set of changed files (from a PR diff or direct list), computes the
blast radius across the knowledge graph using purely deterministic Cypher
traversals — no LLM involved.

Blast radius components (matches the research report's component breakdown):
  1. directly_affected_classes  — classes defined in the changed files
  2. callers                    — methods/classes that call into affected classes (1-hop)
  3. transitive_dependents      — classes that transitively import/call affected classes (up to N hops)
  4. affected_modules           — logical modules containing any affected class
  5. exposed_endpoints          — API endpoints exposed by affected classes
  6. relevant_policies          — architectural policies that target affected modules
  7. policy_violations          — existing violations in affected classes
  8. suggested_tests            — test classes whose names or annotations suggest coverage of affected areas

Each result carries:
  - confidence: inherited from the provenance of the source nodes
  - hop_distance: how many graph hops from the directly changed file
  - reason: which edge type caused inclusion
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from neo4j import Driver


@dataclass
class ImpactedNode:
    fqn: str
    name: str
    kind: str                       # class | method | interface | enum
    file_path: Optional[str]
    module: Optional[str]
    hop_distance: int               # 0 = directly in changed file
    reason: str                     # "direct" | "caller" | "importer" | "transitive"
    confidence: float = 1.0


@dataclass
class ImpactedEndpoint:
    endpoint_id: str
    http_method: str
    path: str
    handler_class: str
    handler_method: str
    file_path: Optional[str]
    confidence: float = 1.0


@dataclass
class ImpactedPolicy:
    policy_id: str
    title: str
    natural_language: str
    severity: str
    is_violated: bool               # True if this module already has a violation


@dataclass
class SuggestedTest:
    fqn: str
    name: str
    file_path: Optional[str]
    reason: str                     # why this test is suggested


@dataclass
class ImpactReport:
    repo_id: str
    changed_files: list[str]
    commit_sha: Optional[str]

    directly_affected: list[ImpactedNode] = field(default_factory=list)
    callers: list[ImpactedNode] = field(default_factory=list)
    transitive_dependents: list[ImpactedNode] = field(default_factory=list)
    affected_modules: list[str] = field(default_factory=list)
    exposed_endpoints: list[ImpactedEndpoint] = field(default_factory=list)
    relevant_policies: list[ImpactedPolicy] = field(default_factory=list)
    suggested_tests: list[SuggestedTest] = field(default_factory=list)

    # Summary stats
    total_affected_classes: int = 0
    total_affected_modules: int = 0
    risk_score: float = 0.0         # 0.0–1.0, heuristic based on breadth of impact

    def to_dict(self) -> dict:
        return {
            "repo_id": self.repo_id,
            "changed_files": self.changed_files,
            "commit_sha": self.commit_sha,
            "summary": {
                "directly_affected_classes": len(self.directly_affected),
                "callers": len(self.callers),
                "transitive_dependents": len(self.transitive_dependents),
                "affected_modules": self.affected_modules,
                "exposed_endpoints": len(self.exposed_endpoints),
                "relevant_policies": len(self.relevant_policies),
                "suggested_tests": len(self.suggested_tests),
                "risk_score": round(self.risk_score, 2),
            },
            "directly_affected": [_node_dict(n) for n in self.directly_affected],
            "callers": [_node_dict(n) for n in self.callers],
            "transitive_dependents": [_node_dict(n) for n in self.transitive_dependents],
            "exposed_endpoints": [_ep_dict(e) for e in self.exposed_endpoints],
            "relevant_policies": [_policy_dict(p) for p in self.relevant_policies],
            "suggested_tests": [_test_dict(t) for t in self.suggested_tests],
        }


def _node_dict(n: ImpactedNode) -> dict:
    return {
        "fqn": n.fqn, "name": n.name, "kind": n.kind,
        "file_path": n.file_path, "module": n.module,
        "hop_distance": n.hop_distance, "reason": n.reason,
        "confidence": n.confidence,
    }

def _ep_dict(e: ImpactedEndpoint) -> dict:
    return {
        "endpoint_id": e.endpoint_id, "http_method": e.http_method,
        "path": e.path, "handler_class": e.handler_class,
        "handler_method": e.handler_method, "file_path": e.file_path,
        "confidence": e.confidence,
    }

def _policy_dict(p: ImpactedPolicy) -> dict:
    return {
        "policy_id": p.policy_id, "title": p.title,
        "natural_language": p.natural_language,
        "severity": p.severity, "is_violated": p.is_violated,
    }

def _test_dict(t: SuggestedTest) -> dict:
    return {"fqn": t.fqn, "name": t.name, "file_path": t.file_path, "reason": t.reason}


class ImpactEngine:
    """
    All graph traversals are done in Cypher — purely deterministic, no LLM.
    Max traversal depth is bounded to prevent runaway queries on large graphs.
    """

    MAX_TRANSITIVE_HOPS = 4
    MAX_RESULTS_PER_CATEGORY = 50

    def __init__(self, driver: Driver):
        self._driver = driver

    def compute(
        self,
        repo_id: str,
        changed_files: list[str],
        commit_sha: Optional[str] = None,
    ) -> ImpactReport:
        report = ImpactReport(
            repo_id=repo_id,
            changed_files=changed_files,
            commit_sha=commit_sha,
        )

        if not changed_files:
            return report

        # Step 1: directly affected classes
        report.directly_affected = self._directly_affected(repo_id, changed_files)
        if not report.directly_affected:
            return report

        direct_fqns = [n.fqn for n in report.directly_affected]

        # Steps 2–7 in parallel (each is an independent Cypher query)
        report.callers = self._callers(direct_fqns)
        report.transitive_dependents = self._transitive_dependents(direct_fqns)
        report.exposed_endpoints = self._exposed_endpoints(direct_fqns)

        all_affected_fqns = direct_fqns + [n.fqn for n in report.callers] + \
                            [n.fqn for n in report.transitive_dependents]
        report.affected_modules = self._affected_modules(all_affected_fqns)
        report.relevant_policies = self._relevant_policies(report.affected_modules)
        report.suggested_tests = self._suggested_tests(direct_fqns, report.affected_modules)

        # Summary
        report.total_affected_classes = len(set(all_affected_fqns))
        report.total_affected_modules = len(report.affected_modules)
        report.risk_score = self._risk_score(report)

        return report

    # ------------------------------------------------------------------
    # Cypher traversal queries
    # ------------------------------------------------------------------

    def _run(self, cypher: str, **params) -> list[dict]:
        with self._driver.session() as s:
            return [dict(r) for r in s.run(cypher, **params)]

    def _directly_affected(self, repo_id: str, files: list[str]) -> list[ImpactedNode]:
        rows = self._run(
            """
            MATCH (c)
            WHERE c.file_path IN $files AND c.repo_id = $repo_id
              AND (c:Class OR c:Interface OR c:Enum)
            RETURN c.fqn AS fqn, c.name AS name, c.kind AS kind,
                   c.file_path AS file_path, c.module AS module,
                   coalesce(c.prov_confidence, 0.85) AS confidence
            ORDER BY c.fqn
            LIMIT $limit
            """,
            files=files, repo_id=repo_id, limit=self.MAX_RESULTS_PER_CATEGORY,
        )
        return [ImpactedNode(
            fqn=r["fqn"], name=r["name"], kind=r["kind"] or "class",
            file_path=r["file_path"], module=r["module"],
            hop_distance=0, reason="direct", confidence=r["confidence"],
        ) for r in rows]

    def _callers(self, direct_fqns: list[str]) -> list[ImpactedNode]:
        """Classes whose methods call into any directly affected class."""
        rows = self._run(
            """
            MATCH (caller:Method)-[:CALLS]->(callee:Method)
            WHERE callee.class_fqn IN $fqns
            MATCH (callerClass)-[:CONTAINS]->(caller)
            WHERE NOT callerClass.fqn IN $fqns
            RETURN DISTINCT callerClass.fqn AS fqn, callerClass.name AS name,
                   coalesce(callerClass.kind, 'class') AS kind,
                   callerClass.file_path AS file_path,
                   callerClass.module AS module,
                   coalesce(callerClass.prov_confidence, 0.80) AS confidence
            LIMIT $limit
            """,
            fqns=direct_fqns, limit=self.MAX_RESULTS_PER_CATEGORY,
        )
        return [ImpactedNode(
            fqn=r["fqn"], name=r["name"], kind=r["kind"],
            file_path=r["file_path"], module=r["module"],
            hop_distance=1, reason="caller", confidence=r["confidence"],
        ) for r in rows]

    def _transitive_dependents(self, direct_fqns: list[str]) -> list[ImpactedNode]:
        """Classes that transitively import any directly affected class (up to MAX hops)."""
        rows = self._run(
            f"""
            MATCH path = (dependent)-[:IMPORTS*1..{self.MAX_TRANSITIVE_HOPS}]->(affected)
            WHERE affected.fqn IN $fqns
              AND NOT dependent.fqn IN $fqns
              AND (dependent:Class OR dependent:Interface)
            RETURN DISTINCT dependent.fqn AS fqn, dependent.name AS name,
                   coalesce(dependent.kind, 'class') AS kind,
                   dependent.file_path AS file_path,
                   dependent.module AS module,
                   length(path) AS hops,
                   coalesce(dependent.prov_confidence, 0.75) AS confidence
            ORDER BY hops, dependent.fqn
            LIMIT $limit
            """,
            fqns=direct_fqns, limit=self.MAX_RESULTS_PER_CATEGORY,
        )
        return [ImpactedNode(
            fqn=r["fqn"], name=r["name"], kind=r["kind"],
            file_path=r["file_path"], module=r["module"],
            hop_distance=r["hops"], reason="transitive-import",
            confidence=r["confidence"],
        ) for r in rows]

    def _exposed_endpoints(self, direct_fqns: list[str]) -> list[ImpactedEndpoint]:
        """API endpoints exposed by any affected class."""
        rows = self._run(
            """
            MATCH (c)-[:EXPOSES]->(e:ApiEndpoint)
            WHERE c.fqn IN $fqns
            RETURN e.endpoint_id AS endpoint_id, e.http_method AS http_method,
                   e.path AS path, e.handler_class AS handler_class,
                   e.handler_method AS handler_method, e.file_path AS file_path,
                   coalesce(e.prov_confidence, 0.90) AS confidence
            ORDER BY e.http_method, e.path
            LIMIT $limit
            """,
            fqns=direct_fqns, limit=self.MAX_RESULTS_PER_CATEGORY,
        )
        return [ImpactedEndpoint(
            endpoint_id=r["endpoint_id"], http_method=r["http_method"],
            path=r["path"], handler_class=r["handler_class"],
            handler_method=r["handler_method"], file_path=r["file_path"],
            confidence=r["confidence"],
        ) for r in rows]

    def _affected_modules(self, all_fqns: list[str]) -> list[str]:
        rows = self._run(
            """
            MATCH (c) WHERE c.fqn IN $fqns AND c.module IS NOT NULL
            RETURN DISTINCT c.module AS module ORDER BY module
            """,
            fqns=all_fqns,
        )
        return [r["module"] for r in rows]

    def _relevant_policies(self, modules: list[str]) -> list[ImpactedPolicy]:
        if not modules:
            return []
        rows = self._run(
            """
            MATCH (ap:ArchPolicy)-[:TARGETS]->(mod:Module)
            WHERE mod.module_id IN $modules AND ap.status = 'active'
            OPTIONAL MATCH (v)-[:VIOLATES]->(ap)
            RETURN ap.policy_id AS policy_id, ap.title AS title,
                   ap.natural_language AS natural_language,
                   ap.severity AS severity,
                   count(v) > 0 AS is_violated
            ORDER BY ap.severity DESC
            """,
            modules=modules,
        )
        return [ImpactedPolicy(
            policy_id=r["policy_id"], title=r["title"],
            natural_language=r["natural_language"],
            severity=r["severity"], is_violated=bool(r["is_violated"]),
        ) for r in rows]

    def _suggested_tests(self, direct_fqns: list[str], modules: list[str]) -> list[SuggestedTest]:
        """
        Suggest test classes by two heuristics:
        1. Test class name contains the name of an affected class
        2. Test class is in the same module as an affected class
        """
        affected_names = [fqn.split(".")[-1] for fqn in direct_fqns]

        # Heuristic 1: name-based match
        name_tests = self._run(
            """
            MATCH (c:Class)
            WHERE (c.name ENDS WITH 'Test' OR c.name ENDS WITH 'Tests' OR c.name ENDS WITH 'Spec')
              AND any(name IN $names WHERE c.name CONTAINS name)
            RETURN c.fqn AS fqn, c.name AS name, c.file_path AS file_path
            LIMIT 20
            """,
            names=affected_names,
        )

        # Heuristic 2: same-module test classes
        module_tests: list[dict] = []
        if modules:
            module_tests = self._run(
                """
                MATCH (c:Class)
                WHERE (c.name ENDS WITH 'Test' OR c.name ENDS WITH 'Tests' OR c.name ENDS WITH 'Spec')
                  AND c.module IN $modules
                RETURN c.fqn AS fqn, c.name AS name, c.file_path AS file_path
                LIMIT 20
                """,
                modules=modules,
            )

        seen: set[str] = set()
        result: list[SuggestedTest] = []
        for r in name_tests:
            if r["fqn"] not in seen:
                seen.add(r["fqn"])
                result.append(SuggestedTest(
                    fqn=r["fqn"], name=r["name"],
                    file_path=r["file_path"], reason="name-match",
                ))
        for r in module_tests:
            if r["fqn"] not in seen:
                seen.add(r["fqn"])
                result.append(SuggestedTest(
                    fqn=r["fqn"], name=r["name"],
                    file_path=r["file_path"], reason="same-module",
                ))
        return result

    # ------------------------------------------------------------------
    # Risk scoring — purely heuristic, no LLM
    # ------------------------------------------------------------------

    def _risk_score(self, report: ImpactReport) -> float:
        """
        0.0–1.0 heuristic score based on blast radius breadth.
        Factors: number of affected classes, modules, endpoints, error policies.
        """
        score = 0.0
        # Breadth of class impact (caps at 0.4)
        score += min(report.total_affected_classes / 50, 0.4)
        # Module spread (caps at 0.2)
        score += min(report.total_affected_modules / 5, 0.2)
        # Public API exposure (caps at 0.2)
        score += min(len(report.exposed_endpoints) / 10, 0.2)
        # Error-level policy violations (caps at 0.2)
        error_policies = sum(1 for p in report.relevant_policies if p.severity == "error")
        score += min(error_policies / 3, 0.2)
        return min(score, 1.0)
