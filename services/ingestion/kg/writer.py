"""
Neo4j writer — upserts parsed Java facts into the knowledge graph.
All writes use MERGE so the operation is idempotent and safe to re-run
on incremental commit updates.
"""
from __future__ import annotations

from neo4j import GraphDatabase, Driver

from parser.java_parser import ParsedFile


class KGWriter:

    def __init__(self, uri: str, user: str, password: str):
        self._driver: Driver = GraphDatabase.driver(uri, auth=(user, password))

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
        ]
        indexes = [
            "CREATE INDEX IF NOT EXISTS FOR (c:Class) ON (c.name)",
            "CREATE INDEX IF NOT EXISTS FOR (c:Class) ON (c.module)",
            "CREATE INDEX IF NOT EXISTS FOR (m:Method) ON (m.name)",
            "CREATE INDEX IF NOT EXISTS FOR (p:Package) ON (p.repo_id)",
            "CREATE INDEX IF NOT EXISTS FOR (e:ApiEndpoint) ON (e.repo_id)",
            "CREATE INDEX IF NOT EXISTS FOR (e:ApiEndpoint) ON (e.path)",
        ]
        with self._driver.session() as s:
            for stmt in constraints + indexes:
                s.run(stmt)

    def upsert_repository(
        self, repo_id: str, name: str, path: str, language: str = "java",
        java_version: str = None, build_tool: str = None, description: str = None,
        test_framework: str = None, build_commands: dict = None, key_dependencies: list = None,
    ):
        with self._driver.session() as s:
            s.run(
                """
                MERGE (r:Repository {repo_id: $repo_id})
                SET r.name = $name, r.path = $path, r.language = $language,
                    r.java_version = $java_version, r.build_tool = $build_tool,
                    r.description = $description, r.test_framework = $test_framework,
                    r.build_commands = $build_commands, r.key_dependencies = $key_dependencies
                """,
                repo_id=repo_id, name=name, path=path, language=language,
                java_version=java_version, build_tool=build_tool, description=description,
                test_framework=test_framework,
                build_commands=str(build_commands) if build_commands else None,
                key_dependencies=key_dependencies or [],
            )

    def upsert_directory_entries(self, repo_id: str, entries):
        with self._driver.session() as s:
            for e in entries:
                s.run(
                    """
                    MERGE (d:DirectoryEntry {repo_id: $repo_id, path: $path})
                    SET d.description = $description, d.package_roots = $package_roots
                    """,
                    repo_id=repo_id, path=e.path,
                    description=e.description, package_roots=e.package_roots,
                )

    def upsert_api_endpoints(self, repo_id: str, endpoints):
        with self._driver.session() as s:
            for ep in endpoints:
                endpoint_id = f"{repo_id}:{ep.http_method}:{ep.path}:{ep.handler_class}#{ep.handler_method}"
                s.run(
                    """
                    MERGE (e:ApiEndpoint {endpoint_id: $eid})
                    SET e.repo_id = $repo_id,
                        e.http_method = $http_method,
                        e.path = $path,
                        e.handler_class = $handler_class,
                        e.handler_method = $handler_method,
                        e.path_variables = $path_variables,
                        e.request_body_type = $request_body_type,
                        e.response_type = $response_type,
                        e.file_path = $file_path,
                        e.line = $line
                    WITH e
                    MATCH (c {fqn: $handler_class})
                    MERGE (c)-[:EXPOSES]->(e)
                    """,
                    eid=endpoint_id,
                    repo_id=repo_id,
                    http_method=ep.http_method,
                    path=ep.path,
                    handler_class=ep.handler_class,
                    handler_method=ep.handler_method,
                    path_variables=ep.path_variables,
                    request_body_type=ep.request_body_type,
                    response_type=ep.response_type,
                    file_path=ep.file_path,
                    line=ep.line,
                )

    def upsert_concurrency_facts(self, repo_id: str, pools, asyncs, facts):
        with self._driver.session() as s:
            for p in pools:
                s.run(
                    """
                    MERGE (tp:ThreadPool {repo_id: $repo_id, class_fqn: $class_fqn, field_name: $field_name})
                    SET tp.pool_type = $pool_type, tp.configuration = $config,
                        tp.file_path = $file_path, tp.line = $line
                    """,
                    repo_id=repo_id, class_fqn=p.class_fqn, field_name=p.field_name,
                    pool_type=p.pool_type, config=p.configuration,
                    file_path=p.file_path, line=p.line,
                )
            for a in asyncs:
                s.run(
                    """
                    MERGE (am:AsyncMethod {repo_id: $repo_id, class_fqn: $class_fqn, method_name: $method_name, mechanism: $mechanism})
                    SET am.return_type = $return_type, am.file_path = $file_path, am.line = $line
                    """,
                    repo_id=repo_id, class_fqn=a.class_fqn, method_name=a.method_name,
                    mechanism=a.mechanism, return_type=a.return_type,
                    file_path=a.file_path, line=a.line,
                )
            for f in facts:
                s.run(
                    """
                    MERGE (cf:ConcurrencyFact {repo_id: $repo_id, class_fqn: $class_fqn, fact_type: $fact_type, detail: $detail})
                    SET cf.file_path = $file_path, cf.line = $line
                    """,
                    repo_id=repo_id, class_fqn=f.class_fqn, fact_type=f.fact_type,
                    detail=f.detail or "", file_path=f.file_path, line=f.line,
                )

    def upsert_test_categories(self, repo_id: str, categories):
        with self._driver.session() as s:
            for c in categories:
                s.run(
                    """
                    MERGE (tc:TestCategory {repo_id: $repo_id, annotation: $annotation})
                    SET tc.description = $description, tc.base_class = $base_class,
                        tc.example_classes = $examples
                    """,
                    repo_id=repo_id, annotation=c.annotation, description=c.description,
                    base_class=c.base_class, examples=c.example_classes[:5],
                )

    def upsert_parsed_file(self, parsed: ParsedFile):
        with self._driver.session() as s:
            s.execute_write(self._write_parsed_file, parsed)

    @staticmethod
    def _write_parsed_file(tx, parsed: ParsedFile):
        # Package
        if parsed.package_fqn:
            tx.run(
                """
                MERGE (p:Package {fqn: $fqn})
                SET p.name = $name, p.repo_id = $repo_id
                """,
                fqn=parsed.package_fqn,
                name=parsed.package_fqn.split(".")[-1],
                repo_id=parsed.repo_id,
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
                    c.annotations = $annotations
                WITH c
                MATCH (p:Package {{fqn: $package_fqn}})
                MERGE (p)-[:CONTAINS]->(c)
                MERGE (c)-[:BELONGS_TO]->(p)
                """,
                **c,
            )

        # Methods
        for m in parsed.methods:
            tx.run(
                """
                MERGE (m:Method {fqn: $fqn})
                SET m.name = $name,
                    m.class_fqn = $class_fqn,
                    m.return_type = $return_type,
                    m.parameters = $parameters,
                    m.modifiers = $modifiers,
                    m.annotations = $annotations,
                    m.start_line = $start_line,
                    m.end_line = $end_line
                WITH m
                MATCH (c {fqn: $class_fqn})
                MERGE (c)-[:CONTAINS]->(m)
                """,
                **m,
            )

        # Fields
        for f in parsed.fields:
            tx.run(
                """
                MERGE (f:Field {fqn: $fqn})
                SET f.name = $name,
                    f.class_fqn = $class_fqn,
                    f.type_name = $type_name,
                    f.modifiers = $modifiers
                WITH f
                MATCH (c {fqn: $class_fqn})
                MERGE (c)-[:CONTAINS]->(f)
                """,
                **f,
            )

        # Edges
        for edge in parsed.edges:
            _write_edge(tx, edge)

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


def _kind_to_label(kind: str) -> str:
    mapping = {
        "class": "Class",
        "abstract": "Class",
        "interface": "Interface",
        "enum": "Enum",
        "annotation": "Class",
    }
    return mapping.get(kind, "Class")


def _write_edge(tx, edge: dict):
    etype = edge["type"]
    source = edge["source"]
    target = edge["target"]

    if etype == "IMPORTS":
        tx.run(
            """
            MATCH (src {fqn: $source})
            MATCH (tgt {fqn: $target})
            MERGE (src)-[:IMPORTS]->(tgt)
            """,
            source=source, target=target,
        )
    elif etype == "EXTENDS":
        tx.run(
            """
            MATCH (src {fqn: $source})
            MATCH (tgt {name: $target})
            MERGE (src)-[:EXTENDS]->(tgt)
            """,
            source=source, target=target,
        )
    elif etype == "IMPLEMENTS":
        tx.run(
            """
            MATCH (src {fqn: $source})
            MATCH (tgt {name: $target})
            MERGE (src)-[:IMPLEMENTS]->(tgt)
            """,
            source=source, target=target,
        )
    elif etype == "CALLS":
        # best-effort: match by method name fragment; skipped if no match
        tx.run(
            """
            MATCH (src:Method {fqn: $source})
            MATCH (tgt:Method {fqn: $target})
            MERGE (src)-[:CALLS]->(tgt)
            """,
            source=source, target=target,
        )
