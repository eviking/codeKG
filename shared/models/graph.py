"""
Shared data models for nodes and edges in the CodeKG knowledge graph.
These are used by both the ingestion service and the API/MCP layer.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class NodeLabel(str, Enum):
    """Enumerates the Neo4j node labels used by CodeKG. Watch out for renames here, because stored Cypher queries depend on these exact label values."""

    REPOSITORY = "Repository"
    PACKAGE = "Package"
    CLASS = "Class"
    INTERFACE = "Interface"
    ENUM = "Enum"
    METHOD = "Method"
    FIELD = "Field"
    MODULE = "Module"
    ARCH_POLICY = "ArchPolicy"


class EdgeType(str, Enum):
    """Enumerates the relationship types used in the knowledge graph. Watch out for value changes here, because ingestion writes and query code both treat them as wire-format constants."""

    # structural
    CONTAINS = "CONTAINS"           # Package→Class, Class→Method/Field
    BELONGS_TO = "BELONGS_TO"       # Class→Package
    # code relationships
    CALLS = "CALLS"                 # Method→Method
    EXTENDS = "EXTENDS"             # Class→Class/Interface
    IMPLEMENTS = "IMPLEMENTS"       # Class→Interface
    IMPORTS = "IMPORTS"             # Class→Class (import dependency)
    INSTANTIATES = "INSTANTIATES"   # Method→Class (new Foo())
    # architectural
    OWNS = "OWNS"                   # Module→Package
    TARGETS = "TARGETS"             # ArchPolicy→Module
    VIOLATES = "VIOLATES"           # Class/Method→ArchPolicy
    COMPLIES = "COMPLIES"           # Class/Method→ArchPolicy
    EXPOSES = "EXPOSES"             # Class→ApiEndpoint


class ConfidenceTier(str, Enum):
    """
    Confidence tiers tied to the source of a fact.
    HIGH  — from a compiler/language-server (JDT LS, clangd, tsc)
    MEDIUM — from Tree-sitter AST pattern matching
    LOW   — inferred heuristically (name patterns, directory structure)
    """
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SourceTool(str, Enum):
    """Enumerates the tools that can produce graph facts. Watch out for expansion here, because provenance-based confidence logic assumes this set stays interpretable."""

    TREE_SITTER_JAVA = "tree-sitter-java"
    JDT_LS = "jdt-ls"
    MAVEN = "maven"
    GRADLE = "gradle"
    REPO_STRUCTURE = "repo-structure"
    BUILD_EXTRACTOR = "build-extractor"
    API_EXTRACTOR = "api-extractor"
    CONCURRENCY_EXTRACTOR = "concurrency-extractor"
    HUMAN = "human"


@dataclass
class Provenance:
    """
    Attached to every KG node so staleness and confidence are always queryable.
    commit_sha  — the repo commit at which this fact was extracted
    freshness_ts — ISO-8601 UTC timestamp of last extraction
    confidence  — 0.0–1.0 numeric score; maps to ConfidenceTier thresholds
    source_tool — which extractor produced this fact
    """
    commit_sha: str
    freshness_ts: str           # ISO-8601 UTC, e.g. "2026-05-28T14:32:00Z"
    confidence: float = 1.0     # 0.0–1.0
    source_tool: str = SourceTool.TREE_SITTER_JAVA

    def tier(self) -> ConfidenceTier:
        if self.confidence >= 0.9:
            return ConfidenceTier.HIGH
        if self.confidence >= 0.7:
            return ConfidenceTier.MEDIUM
        return ConfidenceTier.LOW

    def to_dict(self) -> dict:
        return {
            "commit_sha": self.commit_sha,
            "freshness_ts": self.freshness_ts,
            "confidence": self.confidence,
            "source_tool": self.source_tool,
        }


@dataclass
class RepositoryNode:
    """Represents a repository node in the knowledge graph. Watch out for `repo_id` stability here, because many APIs use it as their primary lookup key."""

    repo_id: str        # slug, e.g. "org/my-service"
    name: str
    path: str           # local filesystem path
    language: str = "java"
    last_commit: Optional[str] = None


@dataclass
class PackageNode:
    """Represents a package or namespace in the graph. Watch out for module attribution here, because some languages map package structure to service boundaries only heuristically."""

    fqn: str            # fully-qualified name, e.g. "com.example.payment"
    name: str
    repo_id: str
    module: Optional[str] = None


@dataclass
class ClassNode:
    """Represents a class-like type discovered during ingestion. Watch out for line-range and annotation fields here, because UI drill-down pages expose them directly."""

    fqn: str            # e.g. "com.example.payment.PaymentService"
    name: str
    package_fqn: str
    repo_id: str
    kind: str = "class"         # class | interface | enum | abstract
    module: Optional[str] = None
    file_path: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    annotations: list[str] = field(default_factory=list)


@dataclass
class MethodNode:
    """Represents a method discovered during ingestion. Watch out for parameter normalization here, because call-chain and summary features compare these signatures textually."""

    fqn: str            # e.g. "com.example.payment.PaymentService#processPayment"
    name: str
    class_fqn: str
    return_type: Optional[str] = None
    parameters: list[str] = field(default_factory=list)
    modifiers: list[str] = field(default_factory=list)
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    annotations: list[str] = field(default_factory=list)


@dataclass
class FieldNode:
    """Represents a field attached to a class in the graph. Watch out for naming collisions here, because fields share the same enclosing namespace as methods in some views."""

    fqn: str            # e.g. "com.example.payment.PaymentService#amount"
    name: str
    class_fqn: str
    type_name: Optional[str] = None
    modifiers: list[str] = field(default_factory=list)


@dataclass
class ModuleNode:
    """Represents a logical module or bounded context in the graph. Watch out for how modules are inferred here, because not every repo has an explicit module system."""

    module_id: str      # logical name, e.g. "payment", "user", "notification"
    description: Optional[str] = None


@dataclass
class ArchPolicyNode:
    """Represents an architectural policy stored in the graph. Watch out for policy identifiers here, because edits and violations are joined through them."""

    policy_id: str
    title: str
    natural_language: str       # original NL statement from architect
    cypher_constraint: str      # compiled Cypher query that returns violations
    severity: str = "warning"   # warning | error | info
    status: str = "active"      # active | draft | deprecated
    module_targets: list[str] = field(default_factory=list)


@dataclass
class Edge:
    """Represents a relationship between two graph nodes. Watch out for `properties`, because callers often assume they can attach provenance or explanation metadata there."""

    source_fqn: str
    target_fqn: str
    edge_type: EdgeType
    properties: dict = field(default_factory=dict)
