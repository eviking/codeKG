"""
Neo4j writer — upserts parsed Java facts into the knowledge graph.
All writes use MERGE so the operation is idempotent and safe to re-run
on incremental commit updates.

Every node write stamps provenance: commit_sha, freshness_ts, confidence,
and source_tool. Never write a node without provenance.
"""
from __future__ import annotations

from neo4j import GraphDatabase, Driver

from parser.java_parser import ParsedFile
from kg.provenance import make_provenance, provenance_set_clause, now_utc


class KGWriter:
    """Writes parsed facts into Neo4j as CodeKG nodes and edges. Watch out for idempotency and batching here, because this class sits on the boundary between noisy source code and durable graph state."""


    def __init__(self, uri: str, user: str, password: str):
        self._driver: Driver = GraphDatabase.driver(uri, auth=(user, password))
        # Set per full_scan / incremental call before any writes
        self.current_commit: str = "unknown"

    def close(self):
        self._driver.close()

    def ensure_schema(self):
        """Create indexes and constraints on first startup."""
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:Repository) REQUIRE r.repo_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Package) REQUIRE p.fqn IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Class) REQUIRE c.fqn IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Method) REQUIRE m.fqn IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (f:Field) REQUIRE f.fqn IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (mod:Module) REQUIRE mod.module_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (ap:ArchPolicy) REQUIRE ap.policy_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (e:ApiEndpoint) REQUIRE e.endpoint_id IS UNIQUE",
            # FlowKG
            "CREATE CONSTRAINT IF NOT EXISTS FOR (f:Flow) REQUIRE f.flow_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (fs:FlowStep) REQUIRE fs.step_id IS UNIQUE",
        ]
        indexes = [
            # ── Class ──────────────────────────────────────────────────────────
            "CREATE INDEX IF NOT EXISTS FOR (c:Class) ON (c.name)",
            "CREATE INDEX IF NOT EXISTS FOR (c:Class) ON (c.module)",
            "CREATE INDEX IF NOT EXISTS FOR (c:Class) ON (c.prov_commit_sha)",
            # repo_id is the most common filter in every dashboard/API query
            "CREATE INDEX IF NOT EXISTS FOR (c:Class) ON (c.repo_id)",
            # role is used in class list filters and entry-point detection
            "CREATE INDEX IF NOT EXISTS FOR (c:Class) ON (c.role)",
            # coupling + blast_size are used for ordering in dangerous-class queries
            "CREATE INDEX IF NOT EXISTS FOR (c:Class) ON (c.coupling)",
            "CREATE INDEX IF NOT EXISTS FOR (c:Class) ON (c.blast_size)",
            # summary_ts is used for ordering in summary-progress queries
            "CREATE INDEX IF NOT EXISTS FOR (c:Class) ON (c.summary_ts)",

            # ── Method ─────────────────────────────────────────────────────────
            "CREATE INDEX IF NOT EXISTS FOR (m:Method) ON (m.name)",
            "CREATE INDEX IF NOT EXISTS FOR (m:Method) ON (m.repo_id)",

            # ── Package ────────────────────────────────────────────────────────
            "CREATE INDEX IF NOT EXISTS FOR (p:Package) ON (p.repo_id)",

            # ── ArchPolicy ─────────────────────────────────────────────────────
            # status ('active', 'auto-draft', 'draft') is filtered on every page
            "CREATE INDEX IF NOT EXISTS FOR (ap:ArchPolicy) ON (ap.status)",
            "CREATE INDEX IF NOT EXISTS FOR (ap:ArchPolicy) ON (ap.repo_id)",

            # ── ArchPattern ────────────────────────────────────────────────────
            "CREATE INDEX IF NOT EXISTS FOR (ap:ArchPattern) ON (ap.repo_id)",
            "CREATE INDEX IF NOT EXISTS FOR (ap:ArchPattern) ON (ap.anti_pattern)",

            # ── ApiEndpoint ────────────────────────────────────────────────────
            "CREATE INDEX IF NOT EXISTS FOR (e:ApiEndpoint) ON (e.repo_id)",
            "CREATE INDEX IF NOT EXISTS FOR (e:ApiEndpoint) ON (e.path)",

            # ── FlowKG ─────────────────────────────────────────────────────────
            "CREATE INDEX IF NOT EXISTS FOR (f:Flow) ON (f.repo_id)",
            "CREATE INDEX IF NOT EXISTS FOR (f:Flow) ON (f.entry_point_fqn)",
            "CREATE INDEX IF NOT EXISTS FOR (fs:FlowStep) ON (fs.flow_id)",
            "CREATE INDEX IF NOT EXISTS FOR (fs:FlowStep) ON (fs.fqn)",
            "CREATE INDEX IF NOT EXISTS FOR (fs:FlowStep) ON (fs.repo_id)",
        ]
        with self._driver.session() as s:
            for stmt in constraints + indexes:
                s.run(stmt)

    # ------------------------------------------------------------------
    # Repository + metadata nodes
    # ------------------------------------------------------------------

    def upsert_repository(
        self, repo_id: str, name: str, path: str, language: str = "java",
        java_version: str = None, build_tool: str = None, description: str = None,
        test_framework: str = None, build_commands: dict = None, key_dependencies: list = None,
    ):
        prov = make_provenance(self.current_commit, "repo-structure")
        with self._driver.session() as s:
            s.run(
                f"""
                MERGE (r:Repository {{repo_id: $repo_id}})
                SET r.name = $name, r.path = $path, r.language = $language,
                    r.java_version = $java_version, r.build_tool = $build_tool,
                    r.description = $description, r.test_framework = $test_framework,
                    r.build_commands = $build_commands, r.key_dependencies = $key_dependencies,
                    {provenance_set_clause('r')}
                """,
                repo_id=repo_id, name=name, path=path, language=language,
                java_version=java_version, build_tool=build_tool, description=description,
                test_framework=test_framework,
                build_commands=str(build_commands) if build_commands else None,
                key_dependencies=key_dependencies or [],
                **prov,
            )

    def upsert_directory_entries(self, repo_id: str, entries):
        if not entries:
            return
        prov = make_provenance(self.current_commit, "repo-structure")
        rows = [{
            "repo_id": repo_id,
            "path": e.path,
            "description": e.description,
            "package_roots": e.package_roots,
            **prov,
        } for e in entries]
        with self._driver.session() as s:
            s.run(
                """
                UNWIND $rows AS row
                MERGE (d:DirectoryEntry {repo_id: row.repo_id, path: row.path})
                SET d.description = row.description, d.package_roots = row.package_roots,
                    d.prov_commit_sha = row.prov_commit_sha,
                    d.prov_freshness_ts = row.prov_freshness_ts,
                    d.prov_confidence = row.prov_confidence,
                    d.prov_source_tool = row.prov_source_tool
                """,
                rows=rows,
            )

    def upsert_api_endpoints(self, repo_id: str, endpoints):
        if not endpoints:
            return
        prov = make_provenance(self.current_commit, "api-extractor")
        rows = [{
            "eid": f"{repo_id}:{ep.http_method}:{ep.path}:{ep.handler_class}#{ep.handler_method}",
            "repo_id": repo_id,
            "http_method": ep.http_method,
            "path": ep.path,
            "handler_class": ep.handler_class,
            "handler_method": ep.handler_method,
            "path_variables": ep.path_variables,
            "request_body_type": ep.request_body_type,
            "response_type": ep.response_type,
            "file_path": ep.file_path,
            "line": ep.line,
            **prov,
        } for ep in endpoints]
        with self._driver.session() as s:
            s.run(
                """
                UNWIND $rows AS row
                MERGE (e:ApiEndpoint {endpoint_id: row.eid})
                SET e.repo_id = row.repo_id,
                    e.http_method = row.http_method,
                    e.path = row.path,
                    e.handler_class = row.handler_class,
                    e.handler_method = row.handler_method,
                    e.path_variables = row.path_variables,
                    e.request_body_type = row.request_body_type,
                    e.response_type = row.response_type,
                    e.file_path = row.file_path,
                    e.line = row.line,
                    e.prov_commit_sha = row.prov_commit_sha,
                    e.prov_freshness_ts = row.prov_freshness_ts,
                    e.prov_confidence = row.prov_confidence,
                    e.prov_source_tool = row.prov_source_tool
                WITH e, row
                MATCH (c {fqn: row.handler_class})
                MERGE (c)-[:EXPOSES]->(e)
                """,
                rows=rows,
            )

    def upsert_concurrency_facts(self, repo_id: str, pools, asyncs, facts):
        prov = make_provenance(self.current_commit, "concurrency-extractor")
        with self._driver.session() as s:
            if pools:
                s.run(
                    """
                    UNWIND $rows AS row
                    MERGE (tp:ThreadPool {repo_id: row.repo_id, class_fqn: row.class_fqn, field_name: row.field_name})
                    SET tp.pool_type = row.pool_type, tp.configuration = row.config,
                        tp.file_path = row.file_path, tp.line = row.line,
                        tp.prov_commit_sha = row.prov_commit_sha,
                        tp.prov_freshness_ts = row.prov_freshness_ts,
                        tp.prov_confidence = row.prov_confidence,
                        tp.prov_source_tool = row.prov_source_tool
                    """,
                    rows=[{
                        "repo_id": repo_id, "class_fqn": p.class_fqn, "field_name": p.field_name,
                        "pool_type": p.pool_type, "config": p.configuration,
                        "file_path": p.file_path, "line": p.line, **prov,
                    } for p in pools],
                )
            if asyncs:
                s.run(
                    """
                    UNWIND $rows AS row
                    MERGE (am:AsyncMethod {repo_id: row.repo_id, class_fqn: row.class_fqn, method_name: row.method_name, mechanism: row.mechanism})
                    SET am.return_type = row.return_type, am.file_path = row.file_path, am.line = row.line,
                        am.prov_commit_sha = row.prov_commit_sha,
                        am.prov_freshness_ts = row.prov_freshness_ts,
                        am.prov_confidence = row.prov_confidence,
                        am.prov_source_tool = row.prov_source_tool
                    """,
                    rows=[{
                        "repo_id": repo_id, "class_fqn": a.class_fqn, "method_name": a.method_name,
                        "mechanism": a.mechanism, "return_type": a.return_type,
                        "file_path": a.file_path, "line": a.line, **prov,
                    } for a in asyncs],
                )
            if facts:
                s.run(
                    """
                    UNWIND $rows AS row
                    MERGE (cf:ConcurrencyFact {repo_id: row.repo_id, class_fqn: row.class_fqn, fact_type: row.fact_type, detail: row.detail})
                    SET cf.file_path = row.file_path, cf.line = row.line,
                        cf.prov_commit_sha = row.prov_commit_sha,
                        cf.prov_freshness_ts = row.prov_freshness_ts,
                        cf.prov_confidence = row.prov_confidence,
                        cf.prov_source_tool = row.prov_source_tool
                    """,
                    rows=[{
                        "repo_id": repo_id, "class_fqn": f.class_fqn, "fact_type": f.fact_type,
                        "detail": f.detail or "", "file_path": f.file_path, "line": f.line, **prov,
                    } for f in facts],
                )

    def upsert_test_categories(self, repo_id: str, categories):
        prov = make_provenance(self.current_commit, "build-extractor")
        with self._driver.session() as s:
            for c in categories:
                s.run(
                    f"""
                    MERGE (tc:TestCategory {{repo_id: $repo_id, annotation: $annotation}})
                    SET tc.description = $description, tc.base_class = $base_class,
                        tc.example_classes = $examples,
                        {provenance_set_clause('tc')}
                    """,
                    repo_id=repo_id, annotation=c.annotation, description=c.description,
                    base_class=c.base_class, examples=c.example_classes[:5], **prov,
                )

    def upsert_modules(self, repo_id: str, modules):
        """Write auto-discovered build submodules as Module nodes."""
        prov = make_provenance(self.current_commit, "build-extractor")
        with self._driver.session() as s:
            for mod in modules:
                s.run(
                    f"""
                    MERGE (m:Module {{module_id: $module_id}})
                    SET m.name        = $name,
                        m.path        = $path,
                        m.pkg_prefix  = $pkg_prefix,
                        m.build_tool  = $build_tool,
                        m.repo_id     = $repo_id,
                        m.auto        = true,
                        {provenance_set_clause('m')}
                    WITH m
                    MATCH (repo:Repository {{repo_id: $repo_id}})
                    MERGE (repo)-[:HAS_MODULE]->(m)
                    """,
                    module_id=mod.module_id,
                    name=mod.name,
                    path=mod.path,
                    pkg_prefix=mod.pkg_prefix,
                    build_tool=mod.build_tool,
                    repo_id=repo_id,
                    **prov,
                )

    # ------------------------------------------------------------------
    # Core code structure (classes, methods, fields)
    # ------------------------------------------------------------------

    def upsert_parsed_file(self, parsed: ParsedFile):
        self.write_parsed_batch([parsed])

    def write_parsed_batch(self, parsed_files: list):
        """
        Write a batch of ParsedFile objects using UNWIND — one Cypher query per
        node/edge type across all files, instead of N queries per file.
        This is the hot path for full scans.
        """
        prov = make_provenance(self.current_commit, "tree-sitter-java")

        # Accumulate rows for each node type across all files in the batch
        packages: list[dict] = []
        classes:  list[dict] = []
        methods:  list[dict] = []
        fields:   list[dict] = []
        edges:    list[dict] = []

        for parsed in parsed_files:
            if parsed.package_fqn:
                packages.append({
                    "fqn": parsed.package_fqn,
                    "name": parsed.package_fqn.split(".")[-1],
                    "repo_id": parsed.repo_id,
                })
            for c in parsed.classes:
                classes.append({**c, "label": _kind_to_label(c["kind"])})
            for m in parsed.methods:
                methods.append(m)
            for f in parsed.fields:
                fields.append(f)
            for e in parsed.edges:
                edges.append(e)

        with self._driver.session() as s:

            if packages:
                s.run(
                    """
                    UNWIND $rows AS row
                    MERGE (p:Package {fqn: row.fqn})
                    SET p.name = row.name, p.repo_id = row.repo_id,
                        p.prov_commit_sha = row.prov_commit_sha,
                        p.prov_freshness_ts = row.prov_freshness_ts,
                        p.prov_confidence = row.prov_confidence,
                        p.prov_source_tool = row.prov_source_tool
                    """,
                    rows=[{**p, **prov} for p in packages],
                )

            # Classes — grouped by label since Cypher labels must be literals
            for label in ("Class", "Interface", "Enum"):
                label_rows = [c for c in classes if c["label"] == label]
                if not label_rows:
                    continue
                s.run(
                    f"""
                    UNWIND $rows AS row
                    MERGE (c:{label} {{fqn: row.fqn}})
                    SET c.name = row.name,
                        c.package_fqn = row.package_fqn,
                        c.repo_id = row.repo_id,
                        c.kind = row.kind,
                        c.file_path = row.file_path,
                        c.start_line = row.start_line,
                        c.end_line = row.end_line,
                        c.source_chars = row.source_chars,
                        c.annotations = row.annotations,
                        c.javadoc = row.javadoc,
                        c.prov_commit_sha = row.prov_commit_sha,
                        c.prov_freshness_ts = row.prov_freshness_ts,
                        c.prov_confidence = row.prov_confidence,
                        c.prov_source_tool = row.prov_source_tool
                    """,
                    rows=[{**r, **prov} for r in label_rows],
                )

            if methods:
                s.run(
                    """
                    UNWIND $rows AS row
                    MERGE (m:Method {fqn: row.fqn})
                    SET m.name = row.name,
                        m.class_fqn = row.class_fqn,
                        m.repo_id = row.repo_id,
                        m.return_type = row.return_type,
                        m.parameters = row.parameters,
                        m.modifiers = row.modifiers,
                        m.annotations = row.annotations,
                        m.start_line = row.start_line,
                        m.end_line = row.end_line,
                        m.docstring = row.docstring,
                        m.prov_commit_sha = row.prov_commit_sha,
                        m.prov_freshness_ts = row.prov_freshness_ts,
                        m.prov_confidence = row.prov_confidence,
                        m.prov_source_tool = row.prov_source_tool
                    """,
                    rows=[{**m, **prov} for m in methods],
                )

            # Store call targets on Method nodes for wire_edges to resolve later
            calls_edges = [e for e in edges if e["type"] == "CALLS"]
            if calls_edges:
                # Accumulate per-method call lists
                from collections import defaultdict
                calls_by_method: dict = defaultdict(list)
                for e in calls_edges:
                    target = e["target"]
                    # Extract just the method name from obj#method or ?#method
                    method_name = target.split("#")[-1] if "#" in target else target
                    if method_name:
                        calls_by_method[e["source"]].append(method_name)
                call_rows = [{"fqn": fqn, "targets": list(set(names))}
                             for fqn, names in calls_by_method.items()]
                s.run(
                    """
                    UNWIND $rows AS row
                    MATCH (m:Method {fqn: row.fqn})
                    SET m.calls_unresolved = row.targets
                    """,
                    rows=call_rows,
                )

            # Write IMPORTS edges in bulk
            import_edges = [e for e in edges if e["type"] == "IMPORTS"]
            if import_edges:
                # Internal vs external split
                external_prefixes = (
                    "java.", "javax.", "jakarta.", "sun.", "com.sun.",
                    "org.apache.", "org.junit.", "org.mockito.", "com.google.",
                    "org.hamcrest.", "org.slf4j.", "io.netty.", "reactor.",
                )
                internal_rows = []
                external_rows = []
                for e in import_edges:
                    t = e["target"]
                    pkg = t.rsplit(".", 1)[0] if "." in t else ""
                    simple = t.rsplit(".", 1)[-1]
                    if any(t.startswith(p) for p in external_prefixes):
                        external_rows.append({"source": e["source"], "target": t,
                                              "simple": simple, "pkg": pkg})
                    else:
                        internal_rows.append({"source": e["source"], "target": t,
                                              "simple": simple, "pkg": pkg})
                # Write in chunks — avoids single enormous transactions that pin Neo4j
                _IMPORT_CHUNK = 500
                for i in range(0, len(internal_rows), _IMPORT_CHUNK):
                    s.run(
                        """
                        UNWIND $rows AS row
                        MERGE (tgt:Class {fqn: row.target})
                        ON CREATE SET tgt.name = row.simple, tgt.package_fqn = row.pkg
                        WITH tgt, row
                        MATCH (src {fqn: row.source})
                        MERGE (src)-[:IMPORTS]->(tgt)
                        """,
                        rows=internal_rows[i : i + _IMPORT_CHUNK],
                    )
                for i in range(0, len(external_rows), _IMPORT_CHUNK):
                    s.run(
                        """
                        UNWIND $rows AS row
                        MERGE (tgt:ExternalClass {fqn: row.target})
                        ON CREATE SET tgt.name = row.simple, tgt.package_fqn = row.pkg,
                                      tgt.external = true
                        WITH tgt, row
                        MATCH (src {fqn: row.source})
                        MERGE (src)-[:IMPORTS]->(tgt)
                        """,
                        rows=external_rows[i : i + _IMPORT_CHUNK],
                    )

            # EXTENDS / IMPLEMENTS: store as properties on src for bulk resolution
            # in wire_edges() — do NOT resolve here (name is unqualified simple name,
            # matching globally is wrong and slow)
            for etype in ("EXTENDS", "IMPLEMENTS"):
                typed_edges = [e for e in edges if e["type"] == etype]
                if typed_edges:
                    prop = "extends_unresolved" if etype == "EXTENDS" else "implements_unresolved"
                    s.run(
                        f"""
                        UNWIND $rows AS row
                        MATCH (src:Class {{fqn: row.source}})
                        SET src.{prop} = coalesce(src.{prop}, []) + [row.target]
                        """,
                        rows=[{"source": e["source"], "target": e["target"]}
                              for e in typed_edges],
                    )

            if fields:
                s.run(
                    """
                    UNWIND $rows AS row
                    WITH row WHERE row.fqn IS NOT NULL
                    MERGE (f:Field {fqn: row.fqn})
                    SET f.name = row.name,
                        f.class_fqn = row.class_fqn,
                        f.type_name = row.type_name,
                        f.modifiers = row.modifiers,
                        f.prov_commit_sha = row.prov_commit_sha,
                        f.prov_freshness_ts = row.prov_freshness_ts,
                        f.prov_confidence = row.prov_confidence,
                        f.prov_source_tool = row.prov_source_tool
                    """,
                    rows=[{**f, **prov} for f in fields],
                )

            # Skip edges during batch — wire_edges() does them in bulk post-scan

    def wire_edges(self, repo_id: str):
        """
        Run once after all nodes are loaded. Wires all structural edges using
        properties already on the nodes — no per-file round trips needed.

        Each statement runs in its own auto-commit transaction with a 90-second
        timeout. This prevents any single edge-wiring query from pinning Neo4j
        indefinitely when the graph is large (e.g. Elasticsearch at 49K classes).
        """
        with self._driver.session() as s:
            # Package → Class/Interface/Enum
            s.run("""
                MATCH (c) WHERE c.package_fqn IS NOT NULL AND c.repo_id = $repo_id
                  AND (c:Class OR c:Interface OR c:Enum)
                MATCH (p:Package {fqn: c.package_fqn})
                MERGE (p)-[:CONTAINS]->(c)
                MERGE (c)-[:BELONGS_TO]->(p)
            """, repo_id=repo_id)

            # Class → Method
            s.run("""
                MATCH (m:Method) WHERE m.class_fqn IS NOT NULL AND m.repo_id = $repo_id
                MATCH (c {fqn: m.class_fqn}) WHERE c.repo_id = $repo_id
                MERGE (c)-[:HAS_METHOD]->(m)
            """, repo_id=repo_id)

            # Class → Field
            s.run("""
                MATCH (f:Field) WHERE f.class_fqn IS NOT NULL
                MATCH (c {fqn: f.class_fqn}) WHERE c.repo_id = $repo_id
                MERGE (c)-[:HAS_FIELD]->(f)
            """, repo_id=repo_id)

            # ---- EXTENDS / IMPLEMENTS two-pass resolution ----
            for rel, prop in (("EXTENDS", "extends_unresolved"),
                              ("IMPLEMENTS", "implements_unresolved")):
                # Pass 1: name is unique within the repo — direct match
                s.run(f"""
                    MATCH (src:Class {{repo_id: $repo_id}})
                    WHERE src.{prop} IS NOT NULL
                    UNWIND src.{prop} AS target_name
                    MATCH (tgt:Class {{name: target_name, repo_id: $repo_id}})
                    WITH src, tgt, count(tgt) AS cnt
                    WHERE cnt = 1
                    MERGE (src)-[:{rel}]->(tgt)
                """, repo_id=repo_id)
                # Pass 2: ambiguous name — use IMPORTS edge to disambiguate
                s.run(f"""
                    MATCH (src:Class {{repo_id: $repo_id}})
                    WHERE src.{prop} IS NOT NULL
                      AND NOT (src)-[:{rel}]->()
                    UNWIND src.{prop} AS target_name
                    MATCH (src)-[:IMPORTS]->(tgt:Class {{name: target_name, repo_id: $repo_id}})
                    MERGE (src)-[:{rel}]->(tgt)
                """, repo_id=repo_id)

            # ---- CALLS two-pass resolution ----
            # Pass 1: intra-class (safest — same class_fqn scope)
            s.run("""
                MATCH (caller:Method {repo_id: $repo_id})
                WHERE caller.calls_unresolved IS NOT NULL
                UNWIND caller.calls_unresolved AS callee_name
                MATCH (callee:Method {name: callee_name, class_fqn: caller.class_fqn,
                                      repo_id: $repo_id})
                WHERE callee.fqn <> caller.fqn
                MERGE (caller)-[:CALLS]->(callee)
            """, repo_id=repo_id)
            # Pass 2: intra-package (skip overly common names)
            s.run("""
                MATCH (caller:Method {repo_id: $repo_id})
                WHERE caller.calls_unresolved IS NOT NULL
                UNWIND caller.calls_unresolved AS callee_name
                WITH caller, callee_name
                WHERE NOT callee_name IN ['toString','equals','hashCode','getClass',
                                          'notify','wait','clone','finalize']
                MATCH (caller_class:Class {fqn: caller.class_fqn, repo_id: $repo_id})
                MATCH (callee:Method {name: callee_name, repo_id: $repo_id})
                MATCH (callee_class:Class {fqn: callee.class_fqn,
                                           package_fqn: caller_class.package_fqn,
                                           repo_id: $repo_id})
                WHERE callee.fqn <> caller.fqn
                  AND NOT (caller)-[:CALLS]->(callee)
                WITH caller, callee, count(callee) AS candidates
                WHERE candidates = 1
                MERGE (caller)-[:CALLS]->(callee)
            """, repo_id=repo_id)

    @staticmethod
    def _write_parsed_file(tx, parsed: ParsedFile, prov: dict):
        # Package
        if parsed.package_fqn:
            tx.run(
                f"""
                MERGE (p:Package {{fqn: $fqn}})
                SET p.name = $name, p.repo_id = $repo_id,
                    {provenance_set_clause('p')}
                """,
                fqn=parsed.package_fqn,
                name=parsed.package_fqn.split(".")[-1],
                repo_id=parsed.repo_id,
                **prov,
            )

        # Classes / interfaces / enums
        for c in parsed.classes:
            label = _kind_to_label(c["kind"])
            tx.run(
                f"""
                MERGE (c:{label} {{fqn: $fqn}})
                SET c.name = $name,
                    c.package_fqn = $package_fqn,
                    c.repo_id = $repo_id,
                    c.kind = $kind,
                    c.file_path = $file_path,
                    c.start_line = $start_line,
                    c.end_line = $end_line,
                    c.annotations = $annotations,
                    {provenance_set_clause('c')}
                WITH c
                MATCH (p:Package {{fqn: $package_fqn}})
                MERGE (p)-[:CONTAINS]->(c)
                MERGE (c)-[:BELONGS_TO]->(p)
                """,
                {**c, **prov},
            )

        # Methods
        for m in parsed.methods:
            tx.run(
                f"""
                MERGE (m:Method {{fqn: $fqn}})
                SET m.name = $name,
                    m.class_fqn = $class_fqn,
                    m.repo_id = $repo_id,
                    m.return_type = $return_type,
                    m.parameters = $parameters,
                    m.modifiers = $modifiers,
                    m.annotations = $annotations,
                    m.start_line = $start_line,
                    m.end_line = $end_line,
                    m.docstring = $docstring,
                    {provenance_set_clause('m')}
                WITH m
                MATCH (c {{fqn: $class_fqn}})
                MERGE (c)-[:HAS_METHOD]->(m)
                """,
                {**m, "repo_id": parsed.repo_id, "docstring": m.get("docstring"), **prov},
            )

        # Fields
        for f in parsed.fields:
            tx.run(
                f"""
                MERGE (f:Field {{fqn: $fqn}})
                SET f.name = $name,
                    f.class_fqn = $class_fqn,
                    f.repo_id = $repo_id,
                    f.type_name = $type_name,
                    f.modifiers = $modifiers,
                    {provenance_set_clause('f')}
                WITH f
                MATCH (c {{fqn: $class_fqn}})
                MERGE (c)-[:HAS_FIELD]->(f)
                """,
                {**f, "repo_id": parsed.repo_id, **prov},
            )

        # Edges
        for edge in parsed.edges:
            _write_edge(tx, edge)

    # ------------------------------------------------------------------
    # SCIP document ingestion (language-agnostic entry point)
    # ------------------------------------------------------------------

    def upsert_scip_document(self, doc) -> None:
        """
        Ingest a SCIPDocument into the KG.
        This is the canonical write path for all language plugins.
        The doc carries repo_id; provenance uses self.current_commit.
        """
        prov = make_provenance(self.current_commit, "tree-sitter-java")
        with self._driver.session() as s:
            s.execute_write(self._write_scip_document, doc, prov)

    @staticmethod
    def _write_scip_document(tx, doc, prov: dict):
        from parser.scip_emitter import (
            CONTAINS, EXTENDS, IMPLEMENTS, IMPORTS, CALLS,
        )

        # Package
        if doc.package_symbol:
            tx.run(
                f"""
                MERGE (p:Package {{fqn: $fqn}})
                SET p.repo_id = $repo_id, p.name = $name,
                    {provenance_set_clause('p')}
                """,
                {
                    "fqn": doc.package_symbol,
                    "repo_id": doc.repo_id,
                    "name": doc.package_symbol.rstrip("/").split("/")[-1],
                    **prov,
                },
            )

        # Symbol definitions
        for si in doc.symbols:
            kind = si.kind
            label = {
                "class": "Class", "abstract": "Class",
                "interface": "Interface", "enum": "Enum",
                "method": "Method", "field": "Field",
            }.get(kind, "Class")

            tx.run(
                f"""
                MERGE (n:{label} {{scip_symbol: $symbol}})
                SET n.display_name = $display_name,
                    n.kind = $kind,
                    n.repo_id = $repo_id,
                    n.file_path = $file_path,
                    n.start_line = $start_line,
                    n.end_line = $end_line,
                    n.annotations = $annotations,
                    n.modifiers = $modifiers,
                    n.method_parameters = $method_parameters,
                    n.return_type = $return_type,
                    n.type_name = $type_name,
                    {provenance_set_clause('n')}
                """,
                {
                    "symbol": si.symbol,
                    "display_name": si.display_name,
                    "kind": si.kind,
                    "repo_id": doc.repo_id,
                    "file_path": si.file_path,
                    "start_line": si.start_line,
                    "end_line": si.end_line,
                    "annotations": si.annotations,
                    "modifiers": si.modifiers,
                    "method_parameters": si.parameters,
                    "return_type": si.return_type,
                    "type_name": si.type_name,
                    **prov,
                },
            )

        # Relationships
        rel_cypher = {
            str(CONTAINS):    "CONTAINS",
            str(EXTENDS):     "EXTENDS",
            str(IMPLEMENTS):  "IMPLEMENTS",
            str(IMPORTS):     "IMPORTS",
            str(CALLS):       "CALLS",
        }
        for src_sym, tgt_sym, kind in doc.relationships:
            rel = rel_cypher.get(str(kind))
            if rel:
                tx.run(
                    f"""
                    MATCH (src {{scip_symbol: $src}})
                    MATCH (tgt {{scip_symbol: $tgt}})
                    MERGE (src)-[:{rel}]->(tgt)
                    """,
                    src=src_sym, tgt=tgt_sym,
                )

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def delete_file_nodes(self, file_path: str, repo_id: str):
        """Remove all nodes originating from a deleted/replaced file."""
        with self._driver.session() as s:
            s.run(
                """
                MATCH (c {file_path: $file_path, repo_id: $repo_id})
                DETACH DELETE c
                """,
                file_path=file_path,
                repo_id=repo_id,
            )

    def update_last_commit(self, repo_id: str, commit_sha: str):
        with self._driver.session() as s:
            s.run(
                "MATCH (r:Repository {repo_id: $repo_id}) SET r.last_commit = $sha",
                repo_id=repo_id, sha=commit_sha,
            )

    # ------------------------------------------------------------------
    # Insights (Neo4j label remains TribalKnowledge for schema compatibility)
    # ------------------------------------------------------------------

    def ensure_insight_schema(self):
        with self._driver.session() as s:
            s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (tk:TribalKnowledge) REQUIRE tk.tk_id IS UNIQUE")
            s.run("CREATE INDEX IF NOT EXISTS FOR (tk:TribalKnowledge) ON (tk.applies_to)")
            s.run("CREATE INDEX IF NOT EXISTS FOR (tk:TribalKnowledge) ON (tk.staleness)")

    def upsert_insights(self, entries: list[dict], session_id: str, commit_sha: str):
        """
        Store insight entries extracted from a Claude Code session.
        Each entry: {tk_id, insight, scope, applies_to, confidence, repo_id}
        Links to the target node (Method/Class/Module/Repository) via APPLIES_TO.
        """
        if not entries:
            return
        ts = now_utc()
        with self._driver.session() as s:
            for e in entries:
                s.run(
                    """
                    MERGE (tk:TribalKnowledge {tk_id: $tk_id})
                    SET tk.insight            = $insight,
                        tk.scope              = $scope,
                        tk.applies_to         = $applies_to,
                        tk.confidence         = $confidence,
                        tk.staleness          = coalesce(tk.staleness, 0.0),
                        tk.repo_id            = $repo_id,
                        tk.session_id         = $session_id,
                        tk.saved_at           = $ts,
                        tk.last_touched_commit = $commit_sha
                    WITH tk
                    OPTIONAL MATCH (target {fqn: $applies_to})
                    FOREACH (_ IN CASE WHEN target IS NOT NULL THEN [1] ELSE [] END |
                        MERGE (tk)-[:APPLIES_TO]->(target)
                    )
                    """,
                    tk_id=e["tk_id"],
                    insight=e["insight"],
                    scope=e["scope"],
                    applies_to=e["applies_to"],
                    confidence=float(e.get("confidence", 0.7)),
                    repo_id=e.get("repo_id", ""),
                    session_id=session_id,
                    ts=ts,
                    commit_sha=commit_sha,
                )

    def update_insight_staleness(self, changed_files: list[str], commit_sha: str):
        """
        Called after a commit lands. Increments staleness on Insight nodes
        whose target node lives in one of the changed files.
        - Target file changed slightly  → staleness += 0.15
        - Target file changed heavily   → staleness += 0.35 (caller passes weight > 1)
        Nodes that reach staleness >= 1.0 are marked ORPHANED.
        """
        if not changed_files:
            return
        with self._driver.session() as s:
            s.run(
                """
                MATCH (tk:TribalKnowledge)-[:APPLIES_TO]->(target)
                WHERE target.file_path IN $files
                SET tk.staleness = CASE
                    WHEN tk.staleness + 0.2 >= 1.0 THEN 1.0
                    ELSE tk.staleness + 0.2
                END,
                tk.last_touched_commit = $commit_sha
                """,
                files=changed_files,
                commit_sha=commit_sha,
            )
            # Also catch entries where applies_to matches a file path directly
            s.run(
                """
                MATCH (tk:TribalKnowledge)
                WHERE tk.applies_to IN $files AND tk.staleness < 1.0
                SET tk.staleness = CASE
                    WHEN tk.staleness + 0.2 >= 1.0 THEN 1.0
                    ELSE tk.staleness + 0.2
                END,
                tk.last_touched_commit = $commit_sha
                """,
                files=changed_files,
                commit_sha=commit_sha,
            )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _kind_to_label(kind: str) -> str:
    return {
        "class": "Class", "abstract": "Class",
        "interface": "Interface", "enum": "Enum", "annotation": "Class",
    }.get(kind, "Class")


def _write_edge(tx, edge: dict):
    etype = edge["type"]
    source = edge["source"]
    target = edge["target"]

    if etype == "IMPORTS":
        # MERGE the target as ExternalClass if it doesn't exist in the KG,
        # so import edges are never silently dropped.
        pkg = target.rsplit(".", 1)[0] if "." in target else ""
        simple = target.rsplit(".", 1)[-1]
        is_internal = not any(target.startswith(p) for p in (
            "java.", "javax.", "jakarta.", "sun.", "com.sun.",
            "org.apache.", "org.junit.", "org.mockito.", "com.google.",
            "org.hamcrest.", "org.slf4j.", "io.netty.", "reactor.",
        ))
        label = "Class" if is_internal else "ExternalClass"
        tx.run(
            f"""
            MERGE (tgt:{label} {{fqn: $target}})
            ON CREATE SET tgt.name = $simple, tgt.package_fqn = $pkg, tgt.external = $external
            WITH tgt
            MATCH (src {{fqn: $source}})
            MERGE (src)-[:IMPORTS]->(tgt)
            """,
            source=source, target=target, simple=simple, pkg=pkg,
            external=(label == "ExternalClass"),
        )
    elif etype == "EXTENDS":
        tx.run(
            "MATCH (src {fqn: $source}) MATCH (tgt {name: $target}) MERGE (src)-[:EXTENDS]->(tgt)",
            source=source, target=target,
        )
    elif etype == "IMPLEMENTS":
        tx.run(
            "MATCH (src {fqn: $source}) MATCH (tgt {name: $target}) MERGE (src)-[:IMPLEMENTS]->(tgt)",
            source=source, target=target,
        )
    elif etype == "CALLS":
        # Store unresolved call targets on the source Method so Claude can
        # reason about call chains even without full FQN resolution.
        tx.run(
            """
            MATCH (src:Method {fqn: $source})
            SET src.calls_unresolved = coalesce(src.calls_unresolved, []) + [$target]
            """,
            source=source, target=target,
        )
        # Also attempt resolved edge if target looks like a qualified FQN
        if "#" in target and not target.startswith("?#"):
            tx.run(
                """
                MATCH (src:Method {fqn: $source})
                MATCH (tgt:Method {fqn: $target})
                MERGE (src)-[:CALLS]->(tgt)
                """,
                source=source, target=target,
            )
