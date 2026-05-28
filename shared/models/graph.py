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
