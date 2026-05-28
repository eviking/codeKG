"""
SCIP (Sourcegraph Code Intelligence Protocol) emitter.

Converts a ParsedFile (from java_parser.py) into a SCIP-compatible Document
representation. This is the interchange contract between language plugins and
the KG writer — every language plugin (Java, TypeScript, Python, C++) must
produce SCIPDocument objects. The KG writer reads only SCIPDocument, never
raw language-specific AST dicts.

SCIP concepts used here:
  - Document:   one source file
  - Symbol:     a globally unique identifier for a definition
                format: "{scheme} {manager} {package} {descriptor}"
                e.g.  "scip-java maven com.example/payment 1.0 com/example/payment/PaymentService#"
  - Occurrence: a reference to a symbol at a specific range in the document
  - Relationship: typed edge between two symbols

We use a simplified flat representation (not the full proto binary) because
we are writing to Neo4j not a SCIP index file. The output is a plain Python
dataclass tree that the KG writer ingests uniformly for all languages.

References:
  https://github.com/sourcegraph/scip
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

from parser.java_parser import ParsedFile


# ------------------------------------------------------------------
# SCIP-compatible data model (simplified for KG ingestion)
# ------------------------------------------------------------------

class SymbolRole(IntEnum):
    UNSPECIFIED = 0
    DEFINITION = 1
    IMPORT = 8
    WRITE_ACCESS = 16
    READ_ACCESS = 32
    GENERATED = 64


class RelationshipKind(str):
    pass

IMPLEMENTS  = RelationshipKind("IMPLEMENTS")
EXTENDS     = RelationshipKind("EXTENDS")
CALLS       = RelationshipKind("CALLS")
IMPORTS     = RelationshipKind("IMPORTS")
INSTANTIATES = RelationshipKind("INSTANTIATES")
CONTAINS    = RelationshipKind("CONTAINS")


@dataclass
class SCIPRange:
    start_line: int     # 0-based
    start_char: int
    end_line: int
    end_char: int


@dataclass
class SCIPOccurrence:
    """A use of a symbol at a specific location in the file."""
    symbol: str             # globally unique symbol string
    range: SCIPRange
    role: SymbolRole = SymbolRole.UNSPECIFIED
    override_documentation: list[str] = field(default_factory=list)


@dataclass
class SCIPRelationship:
    symbol: str                 # the related symbol
    kind: RelationshipKind
    is_implementation: bool = False


@dataclass
class SCIPSymbolInformation:
    """Metadata about a symbol defined in this document."""
    symbol: str                 # globally unique symbol string
    display_name: str
    kind: str                   # class | interface | enum | method | field | package
    documentation: list[str] = field(default_factory=list)
    relationships: list[SCIPRelationship] = field(default_factory=list)
    # Extra KG-specific fields (not in SCIP spec but carried through pipeline)
    file_path: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    annotations: list[str] = field(default_factory=list)
    modifiers: list[str] = field(default_factory=list)
    parameters: list[str] = field(default_factory=list)
    return_type: Optional[str] = None
    type_name: Optional[str] = None


@dataclass
class SCIPDocument:
    """
    SCIP representation of one source file.
    Produced by language plugins; consumed by the KG writer.
    """
    relative_path: str              # path relative to repo root
    language: str                   # "java" | "typescript" | "python" | "cpp"
    repo_id: str
    occurrences: list[SCIPOccurrence] = field(default_factory=list)
    symbols: list[SCIPSymbolInformation] = field(default_factory=list)
    # Flat edge list for relationships between symbols
    relationships: list[tuple[str, str, RelationshipKind]] = field(default_factory=list)
    # Package FQN for this file
    package_symbol: Optional[str] = None


# ------------------------------------------------------------------
# Symbol naming convention
# ------------------------------------------------------------------
# Format: "scip-java {package_fqn}/{ClassName}#{methodName}({params})"
# Kept simple — not full SCIP proto format — but globally unique within a repo.

def _class_symbol(package_fqn: str, class_name: str) -> str:
    pkg = package_fqn.replace(".", "/") if package_fqn else ""
    return f"scip-java {pkg}/{class_name}#"


def _method_symbol(package_fqn: str, class_name: str, method_name: str) -> str:
    pkg = package_fqn.replace(".", "/") if package_fqn else ""
    return f"scip-java {pkg}/{class_name}#{method_name}()."


def _field_symbol(package_fqn: str, class_name: str, field_name: str) -> str:
    pkg = package_fqn.replace(".", "/") if package_fqn else ""
    return f"scip-java {pkg}/{class_name}#{field_name}."


def _package_symbol(package_fqn: str) -> str:
    return f"scip-java {package_fqn.replace('.', '/')}/"


# ------------------------------------------------------------------
# Emitter: ParsedFile → SCIPDocument
# ------------------------------------------------------------------

class SCIPEmitter:
    """
    Converts a ParsedFile (Java parser output) to a SCIPDocument.
    All language plugins must produce SCIPDocument — this is the contract.
    """

    def emit(self, parsed: ParsedFile) -> SCIPDocument:
        doc = SCIPDocument(
            relative_path=parsed.file_path,
            language="java",
            repo_id=parsed.repo_id,
            package_symbol=_package_symbol(parsed.package_fqn) if parsed.package_fqn else None,
        )

        pkg = parsed.package_fqn or ""

        # -- Classes --
        for c in parsed.classes:
            sym = _class_symbol(pkg, c["name"])
            si = SCIPSymbolInformation(
                symbol=sym,
                display_name=c["name"],
                kind=c.get("kind", "class"),
                file_path=c.get("file_path"),
                start_line=c.get("start_line"),
                end_line=c.get("end_line"),
                annotations=c.get("annotations", []),
                modifiers=c.get("modifiers", []),
            )
            doc.symbols.append(si)
            doc.occurrences.append(SCIPOccurrence(
                symbol=sym,
                range=SCIPRange(
                    start_line=(c.get("start_line") or 1) - 1,
                    start_char=0,
                    end_line=(c.get("end_line") or 1) - 1,
                    end_char=0,
                ),
                role=SymbolRole.DEFINITION,
            ))

        # -- Methods --
        for m in parsed.methods:
            # derive class name from class_fqn
            class_name = m["class_fqn"].split(".")[-1]
            sym = _method_symbol(pkg, class_name, m["name"])
            si = SCIPSymbolInformation(
                symbol=sym,
                display_name=m["name"],
                kind="method",
                file_path=parsed.file_path,
                start_line=m.get("start_line"),
                end_line=m.get("end_line"),
                annotations=m.get("annotations", []),
                modifiers=m.get("modifiers", []),
                parameters=m.get("parameters", []),
                return_type=m.get("return_type"),
            )
            doc.symbols.append(si)
            # CONTAINS relationship: class → method
            class_sym = _class_symbol(pkg, class_name)
            doc.relationships.append((class_sym, sym, CONTAINS))

        # -- Fields --
        for f in parsed.fields:
            class_name = f["class_fqn"].split(".")[-1]
            sym = _field_symbol(pkg, class_name, f["name"])
            si = SCIPSymbolInformation(
                symbol=sym,
                display_name=f["name"],
                kind="field",
                file_path=parsed.file_path,
                type_name=f.get("type_name"),
                modifiers=f.get("modifiers", []),
            )
            doc.symbols.append(si)
            class_sym = _class_symbol(pkg, class_name)
            doc.relationships.append((class_sym, sym, CONTAINS))

        # -- Structural relationships from edges --
        for edge in parsed.edges:
            src = edge["source"]
            tgt = edge["target"]
            etype = edge["type"]

            # Convert FQN-style source to SCIP symbol
            src_sym = _fqn_to_symbol(src, pkg)
            tgt_sym = _fqn_to_symbol(tgt, pkg)

            kind_map = {
                "EXTENDS": EXTENDS,
                "IMPLEMENTS": IMPLEMENTS,
                "IMPORTS": IMPORTS,
                "CALLS": CALLS,
            }
            if etype in kind_map:
                doc.relationships.append((src_sym, tgt_sym, kind_map[etype]))

        return doc


def _fqn_to_symbol(fqn: str, default_pkg: str) -> str:
    """
    Best-effort conversion of a Java FQN or method reference to a SCIP symbol.
    e.g.  "com.example.payment.PaymentService"      → "scip-java com/example/payment/PaymentService#"
          "com.example.payment.PaymentService#process" → "scip-java com/example/payment/PaymentService#process()."
    """
    if "#" in fqn:
        parts = fqn.split("#", 1)
        class_fqn = parts[0]
        method = parts[1]
        path = class_fqn.replace(".", "/")
        class_name = class_fqn.split(".")[-1]
        pkg_path = "/".join(class_fqn.split(".")[:-1])
        return f"scip-java {pkg_path}/{class_name}#{method}()."
    elif "." in fqn:
        path = fqn.replace(".", "/")
        class_name = fqn.split(".")[-1]
        pkg_path = "/".join(fqn.split(".")[:-1])
        return f"scip-java {pkg_path}/{class_name}#"
    else:
        # Unqualified name — best effort with default package
        pkg_path = default_pkg.replace(".", "/")
        return f"scip-java {pkg_path}/{fqn}#"
