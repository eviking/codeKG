"""
Salesforce Apex source file parser using Tree-sitter (tree-sitter-sfapex).

Parses .cls, .trigger, and .apex files. Extracts:
  - Classes, interfaces, enums (with base classes, implemented interfaces, sharing model)
  - Triggers (object, events — before/after insert/update/delete/undelete)
  - Methods (return types, parameters, modifiers, annotations)
  - Fields (type, access modifier, static/final)
  - @AuraEnabled, @InvocableMethod, @RemoteAction and other Apex annotations
  - SOQL queries (detected as string literals containing SELECT ... FROM)
  - CALLS edges from method bodies
  - Doxygen / ApexDoc block comments (/** ... */)

Output schema matches ParsedFile from java_parser.py — KGWriter works unchanged.

Apex specifics handled:
  - Triggers: emitted as a synthetic class with kind='trigger'; events stored in annotations
  - Sharing model: 'with sharing' / 'without sharing' / 'inherited sharing' stored in modifiers
  - Virtual/abstract/global/public/private access modifiers
  - Inner classes and interfaces
  - Properties (get/set) treated as methods
  - Test classes: @IsTest annotation → kind becomes 'test_class'
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import ctypes
from tree_sitter import Language, Parser, Node

# tree-sitter-sfapex has no PyPI package — grammar is compiled from source in the
# Dockerfile and installed to /usr/local/lib/tree_sitter_apex.so
def _load_apex_language() -> Language:
    import os
    so_path = os.environ.get("TREE_SITTER_APEX_SO", "/usr/local/lib/tree_sitter_apex.so")
    if not os.path.exists(so_path):
        raise ImportError(
            f"Apex grammar .so not found at {so_path}. "
            "Rebuild the ingestion Docker image — the Dockerfile compiles it from "
            "aheber/tree-sitter-sfapex."
        )
    lib = ctypes.CDLL(so_path)
    lib.tree_sitter_apex.restype = ctypes.c_void_p
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return Language(lib.tree_sitter_apex())

APEX_LANGUAGE = _load_apex_language()

# File extensions this parser handles
APEX_EXTENSIONS = {".cls", ".trigger", ".apex"}


def _text(node: Node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _extract_apexdoc(node: Node, src: bytes) -> Optional[str]:
    """Find a /** ... */ ApexDoc comment immediately preceding this node."""
    parent = node.parent
    if parent is None:
        return None
    siblings = list(parent.children)
    idx = next((i for i, c in enumerate(siblings) if c == node), None)
    if idx is None or idx == 0:
        return None
    prev = siblings[idx - 1]
    # Skip whitespace nodes
    if prev.type in ("line_comment", "block_comment"):
        raw = _text(prev, src)
        if raw.startswith("/**"):
            lines = [ln.strip().lstrip("*").strip() for ln in raw[3:-2].splitlines()]
            return " ".join(ln for ln in lines if ln).strip() or None
    return None


class ParsedFile:
    """All extracted facts from a single Apex source file."""

    def __init__(self, file_path: str, repo_id: str):
        self.file_path = file_path
        self.repo_id = repo_id
        self.package_fqn: Optional[str] = None   # namespace (if declared)
        self.imports: list[str] = []              # not meaningful in Apex — left empty
        self.classes: list[dict] = []
        self.interfaces: list[dict] = []
        self.enums: list[dict] = []
        self.methods: list[dict] = []
        self.fields: list[dict] = []
        self.edges: list[dict] = []


class ApexParser:
    """
    Parses Salesforce Apex source files (.cls, .trigger, .apex) via Tree-sitter.
    Output schema is compatible with JavaParser so KGWriter works unchanged.
    """

    def __init__(self):
        self._parser = Parser(APEX_LANGUAGE)

    def parse_file(self, path: Path, repo_id: str) -> ParsedFile:
        src = path.read_bytes()
        tree = self._parser.parse(src)
        result = ParsedFile(str(path), repo_id)
        self._visit_root(tree.root_node, src, result)
        return result

    # ------------------------------------------------------------------
    # Root visitor
    # ------------------------------------------------------------------

    def _visit_root(self, root: Node, src: bytes, result: ParsedFile):
        for node in root.children:
            self._visit_top(node, src, result, namespace="")

    def _visit_top(self, node: Node, src: bytes, result: ParsedFile, namespace: str):
        if node.type == "class_declaration":
            self._handle_class(node, src, result, namespace=namespace)
        elif node.type == "interface_declaration":
            self._handle_interface(node, src, result, namespace=namespace)
        elif node.type == "enum_declaration":
            self._handle_enum(node, src, result, namespace=namespace)
        elif node.type == "trigger_declaration":
            self._handle_trigger(node, src, result)

    # ------------------------------------------------------------------
    # Class
    # ------------------------------------------------------------------

    def _handle_class(self, node: Node, src: bytes, result: ParsedFile,
                      namespace: str, parent_fqn: Optional[str] = None):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        fqn = f"{parent_fqn}.{name}" if parent_fqn else (
            f"{namespace}.{name}" if namespace else name
        )

        # Modifiers (access + sharing model)
        modifiers, annotations = self._extract_modifiers(node, src)

        # Superclass — superclass node contains `extends <type_identifier>`, grab the identifier
        superclass_node = node.child_by_field_name("superclass")
        if superclass_node:
            type_id = next((c for c in superclass_node.children
                            if c.type in ("type_identifier", "generic_type")), None)
            base = _text(type_id or superclass_node, src).strip()
            if base and base.lower() != "extends":
                result.edges.append({"source": fqn, "target": base,
                                      "type": "EXTENDS", "unresolved": True})

        # Interfaces
        ifaces_node = node.child_by_field_name("interfaces")
        if ifaces_node:
            for child in ifaces_node.children:
                if child.is_named and child.type != "type_list":
                    iface = _text(child, src).strip()
                    if iface:
                        result.edges.append({"source": fqn, "target": iface,
                                              "type": "IMPLEMENTS", "unresolved": True})
                elif child.type == "type_list":
                    for tc in child.children:
                        if tc.is_named:
                            result.edges.append({"source": fqn, "target": _text(tc, src).strip(),
                                                  "type": "IMPLEMENTS", "unresolved": True})

        apexdoc = _extract_apexdoc(node, src)

        # Determine kind
        kind = "class"
        if "@IsTest" in annotations or "testmethod" in [m.lower() for m in modifiers]:
            kind = "test_class"
        elif "abstract" in modifiers:
            kind = "abstract_class"
        elif "interface" == node.type:
            kind = "interface"

        result.classes.append({
            "fqn": fqn,
            "name": name,
            "package_fqn": namespace or (parent_fqn or ""),
            "repo_id": result.repo_id,
            "kind": kind,
            "file_path": result.file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "annotations": annotations,
            "modifiers": modifiers,
            "javadoc": apexdoc,
        })

        # Walk body
        body = node.child_by_field_name("body")
        if body:
            self._visit_class_body(body, src, result, class_fqn=fqn,
                                   namespace=namespace)

    def _visit_class_body(self, body: Node, src: bytes, result: ParsedFile,
                          class_fqn: str, namespace: str):
        for member in body.children:
            if member.type == "class_declaration":
                self._handle_class(member, src, result, namespace=namespace,
                                   parent_fqn=class_fqn)
            elif member.type == "interface_declaration":
                self._handle_interface(member, src, result, namespace=namespace,
                                       parent_fqn=class_fqn)
            elif member.type == "enum_declaration":
                self._handle_enum(member, src, result, namespace=namespace,
                                  parent_fqn=class_fqn)
            elif member.type == "method_declaration":
                self._handle_method(member, src, result, class_fqn=class_fqn)
            elif member.type == "constructor_declaration":
                self._handle_constructor(member, src, result, class_fqn=class_fqn)
            elif member.type == "field_declaration":
                self._handle_field(member, src, result, class_fqn=class_fqn)
            elif member.type == "property_declaration":
                self._handle_property(member, src, result, class_fqn=class_fqn)

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------

    def _handle_interface(self, node: Node, src: bytes, result: ParsedFile,
                          namespace: str, parent_fqn: Optional[str] = None):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        fqn = f"{parent_fqn}.{name}" if parent_fqn else (
            f"{namespace}.{name}" if namespace else name
        )
        modifiers, annotations = self._extract_modifiers(node, src)
        apexdoc = _extract_apexdoc(node, src)
        result.classes.append({
            "fqn": fqn,
            "name": name,
            "package_fqn": namespace or "",
            "repo_id": result.repo_id,
            "kind": "interface",
            "file_path": result.file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "annotations": annotations,
            "modifiers": modifiers,
            "javadoc": apexdoc,
        })
        body = node.child_by_field_name("body")
        if body:
            for member in body.children:
                if member.type == "method_declaration":
                    self._handle_method(member, src, result, class_fqn=fqn)

    # ------------------------------------------------------------------
    # Enum
    # ------------------------------------------------------------------

    def _handle_enum(self, node: Node, src: bytes, result: ParsedFile,
                     namespace: str, parent_fqn: Optional[str] = None):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        fqn = f"{parent_fqn}.{name}" if parent_fqn else (
            f"{namespace}.{name}" if namespace else name
        )
        apexdoc = _extract_apexdoc(node, src)
        result.classes.append({
            "fqn": fqn,
            "name": name,
            "package_fqn": namespace or "",
            "repo_id": result.repo_id,
            "kind": "enum",
            "file_path": result.file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "annotations": [],
            "modifiers": [],
            "javadoc": apexdoc,
        })

    # ------------------------------------------------------------------
    # Trigger
    # ------------------------------------------------------------------

    def _handle_trigger(self, node: Node, src: bytes, result: ParsedFile):
        name_node = node.child_by_field_name("name")
        object_node = node.child_by_field_name("object")
        events_node = node.child_by_field_name("events")

        name = _text(name_node, src) if name_node else "UnknownTrigger"
        sobject = _text(object_node, src) if object_node else "Unknown"
        events = _text(events_node, src) if events_node else ""

        fqn = name
        apexdoc = _extract_apexdoc(node, src)

        # Events stored as annotations so they're queryable
        event_list = [e.strip() for e in events.split(",") if e.strip()]
        annotations = [f"@Trigger({sobject}:{e})" for e in event_list] or [f"@Trigger({sobject})"]

        result.classes.append({
            "fqn": fqn,
            "name": name,
            "package_fqn": "",
            "repo_id": result.repo_id,
            "kind": "trigger",
            "file_path": result.file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "annotations": annotations,
            "modifiers": [],
            "javadoc": apexdoc or f"Trigger on {sobject} ({events})",
        })

        # Trigger body — extract methods/calls
        body = node.child_by_field_name("body")
        if body:
            self._visit_class_body(body, src, result, class_fqn=fqn, namespace="")

    # ------------------------------------------------------------------
    # Method
    # ------------------------------------------------------------------

    def _handle_method(self, node: Node, src: bytes, result: ParsedFile,
                       class_fqn: str):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        fqn = f"{class_fqn}#{name}"

        type_node = node.child_by_field_name("type")
        return_type = _text(type_node, src) if type_node else "void"

        params = self._extract_params(node, src)
        modifiers, annotations = self._extract_modifiers(node, src)
        apexdoc = _extract_apexdoc(node, src)

        result.methods.append({
            "fqn": fqn,
            "name": name,
            "class_fqn": class_fqn,
            "repo_id": result.repo_id,
            "return_type": return_type,
            "parameters": params,
            "modifiers": modifiers,
            "annotations": annotations,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "docstring": apexdoc,
        })

        body = node.child_by_field_name("body")
        if body:
            self._collect_calls(body, src, result, fqn)
            self._collect_soql(body, src, result, fqn)

    def _handle_constructor(self, node: Node, src: bytes, result: ParsedFile,
                            class_fqn: str):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        fqn = f"{class_fqn}#<init>"
        params = self._extract_params(node, src)
        modifiers, annotations = self._extract_modifiers(node, src)
        apexdoc = _extract_apexdoc(node, src)

        result.methods.append({
            "fqn": fqn,
            "name": f"<init>",
            "class_fqn": class_fqn,
            "repo_id": result.repo_id,
            "return_type": None,
            "parameters": params,
            "modifiers": modifiers + ["constructor"],
            "annotations": annotations,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "docstring": apexdoc,
        })

        body = node.child_by_field_name("body")
        if body:
            self._collect_calls(body, src, result, fqn)

    def _handle_property(self, node: Node, src: bytes, result: ParsedFile,
                         class_fqn: str):
        """Apex property (get/set accessors) — emit as a synthetic method."""
        type_node = node.child_by_field_name("type")
        prop_type = _text(type_node, src) if type_node else "Object"
        modifiers, annotations = self._extract_modifiers(node, src)

        # Find declarator name
        for child in node.children:
            if child.type == "property_declarator":
                name_node = child.child_by_field_name("name")
                if name_node:
                    name = _text(name_node, src)
                    fqn = f"{class_fqn}#{name}"
                    result.methods.append({
                        "fqn": fqn,
                        "name": name,
                        "class_fqn": class_fqn,
                        "repo_id": result.repo_id,
                        "return_type": prop_type,
                        "parameters": [],
                        "modifiers": modifiers + ["property"],
                        "annotations": annotations,
                        "start_line": node.start_point[0] + 1,
                        "end_line": node.end_point[0] + 1,
                        "docstring": None,
                    })

    # ------------------------------------------------------------------
    # Field
    # ------------------------------------------------------------------

    def _handle_field(self, node: Node, src: bytes, result: ParsedFile,
                      class_fqn: str):
        type_node = node.child_by_field_name("type")
        ftype = _text(type_node, src) if type_node else "Object"
        modifiers, _ = self._extract_modifiers(node, src)

        declarator = node.child_by_field_name("declarator")
        if declarator:
            name_node = declarator.child_by_field_name("name")
            if name_node:
                fname = _text(name_node, src).strip()
                if fname and re.match(r"^[a-zA-Z_]\w*$", fname):
                    result.fields.append({
                        "name": fname,
                        "class_fqn": class_fqn,
                        "type": ftype,
                        "modifiers": modifiers,
                    })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_modifiers(self, node: Node, src: bytes) -> tuple[list[str], list[str]]:
        """Return (modifier_strings, annotation_strings) from a node's modifiers child."""
        modifiers: list[str] = []
        annotations: list[str] = []
        for child in node.children:
            if child.type == "modifiers":
                for mod in child.children:
                    if mod.type == "modifier":
                        modifiers.append(_text(mod, src).lower())
                    elif mod.type == "annotation":
                        ann_text = _text(mod, src)
                        annotations.append(ann_text)
        return modifiers, annotations

    def _extract_params(self, node: Node, src: bytes) -> list[str]:
        """Extract formal_parameter list from a method/constructor node."""
        params: list[str] = []
        params_node = node.child_by_field_name("parameters")
        if params_node is None:
            return params
        for p in params_node.children:
            if p.type == "formal_parameter":
                type_node = p.child_by_field_name("type")
                name_node = p.child_by_field_name("name")
                ptype = _text(type_node, src) if type_node else ""
                pname = _text(name_node, src) if name_node else ""
                params.append(f"{ptype} {pname}".strip() if ptype else pname)
        return params

    def _collect_calls(self, node: Node, src: bytes, result: ParsedFile,
                       caller_fqn: str):
        """Walk a method body emitting CALLS edges for method_invocations."""
        queue = list(node.children)
        while queue:
            n = queue.pop(0)
            if n.type == "method_invocation":
                name_node = n.child_by_field_name("name")
                if name_node:
                    callee = _text(name_node, src).split(".")[-1].strip()
                    if callee and re.match(r"^[a-zA-Z_]\w*$", callee):
                        result.edges.append({
                            "source": caller_fqn,
                            "target": callee,
                            "type": "CALLS",
                            "unresolved": True,
                        })
            queue.extend(n.children)

    def _collect_soql(self, node: Node, src: bytes, result: ParsedFile,
                      caller_fqn: str):
        """Detect inline SOQL queries and emit QUERIES edges."""
        queue = list(node.children)
        while queue:
            n = queue.pop(0)
            # tree-sitter-sfapex models SOQL as soql_query nodes
            if n.type in ("soql_query", "soql_query_body"):
                raw = _text(n, src)
                # Extract sObject from FROM clause
                m = re.search(r'\bFROM\s+(\w+)', raw, re.IGNORECASE)
                if m:
                    sobject = m.group(1)
                    result.edges.append({
                        "source": caller_fqn,
                        "target": sobject,
                        "type": "QUERIES",
                        "unresolved": True,
                    })
            queue.extend(n.children)
