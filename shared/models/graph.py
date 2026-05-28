"""
Shared data models for nodes and edges in the CodeKG knowledge graph.
These are used by both the ingestion service and the API/MCP layer.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class NodeLabel(str, Enum):
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
    repo_id: str        # slug, e.g. "org/my-service"
    name: str
    path: str           # local filesystem path
    language: str = "java"
    last_commit: Optional[str] = None


@dataclass
class PackageNode:
    fqn: str            # fully-qualified name, e.g. "com.example.payment"
    name: str
    repo_id: str
    module: Optional[str] = None


@dataclass
class ClassNode:
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
    fqn: str            # e.g. "com.example.payment.PaymentService#amount"
    name: str
    class_fqn: str
    type_name: Optional[str] = None
    modifiers: list[str] = field(default_factory=list)


@dataclass
class ModuleNode:
    module_id: str      # logical name, e.g. "payment", "user", "notification"
    description: Optional[str] = None


@dataclass
class ArchPolicyNode:
    policy_id: str
    title: str
    natural_language: str       # original NL statement from architect
    cypher_constraint: str      # compiled Cypher query that returns violations
    severity: str = "warning"   # warning | error | info
    status: str = "active"      # active | draft | deprecated
    module_targets: list[str] = field(default_factory=list)


@dataclass
class Edge:
    source_fqn: str
    target_fqn: str
    edge_type: EdgeType
    properties: dict = field(default_factory=dict)
