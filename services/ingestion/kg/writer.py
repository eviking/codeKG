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
        ]
        indexes = [
            "CREATE INDEX IF NOT EXISTS FOR (c:Class) ON (c.name)",
            "CREATE INDEX IF NOT EXISTS FOR (c:Class) ON (c.module)",
            "CREATE INDEX IF NOT EXISTS FOR (m:Method) ON (m.name)",
            "CREATE INDEX IF NOT EXISTS FOR (p:Package) ON (p.repo_id)",
        ]
        with self._driver.session() as s:
            for stmt in constraints + indexes:
                s.run(stmt)

    def upsert_repository(self, repo_id: str, name: str, path: str, language: str = "java"):
        with self._driver.session() as s:
            s.run(
                """
                MERGE (r:Repository {repo_id: $repo_id})
                SET r.name = $name, r.path = $path, r.language = $language
                """,
                repo_id=repo_id, name=name, path=path, language=language,
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
