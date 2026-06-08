"""
Java source file parser using Tree-sitter.
Extracts structural information (packages, classes, interfaces, methods, fields,
annotations, inheritance, and import dependencies) without invoking any LLM.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import tree_sitter_java as tsjava
from tree_sitter import Language, Parser, Node

JAVA_LANGUAGE = Language(tsjava.language())


def _text(node: Node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _extract_javadoc(node: Node, src: bytes) -> Optional[str]:
    """
    Find the /** ... */ block comment immediately preceding this type declaration
    in its parent's children list. Returns cleaned text or None.
    """
    parent = node.parent
    if parent is None:
        return None
    siblings = list(parent.children)
    try:
        idx = siblings.index(node)
    except ValueError:
        return None
    # scan backwards skipping whitespace nodes and modifiers
    for i in range(idx - 1, -1, -1):
        sib = siblings[i]
        if sib.type == "block_comment":
            text = _text(sib, src)
            if text.startswith("/**"):
                # strip /** and */ then clean leading * on each line
                inner = text[3:]
                if inner.endswith("*/"):
                    inner = inner[:-2]
                lines = inner.splitlines()
                cleaned = []
                for line in lines:
                    line = line.strip().lstrip("*").strip()
                    if line:
                        cleaned.append(line)
                return " ".join(cleaned) if cleaned else None
        elif sib.type in ("modifiers", "line_comment"):
            continue  # keep looking past modifiers / single-line comments
        elif sib.is_named and sib.type not in ("block_comment", "line_comment"):
            break  # hit a real node — no Javadoc found
    return None


def _child_text(node: Node, field: str, src: bytes) -> Optional[str]:
    child = node.child_by_field_name(field)
    return _text(child, src) if child else None


def _collect_modifiers(node: Node, src: bytes) -> list[str]:
    mods = []
    for child in node.children:
        if child.type == "modifiers":
            for m in child.children:
                if m.type not in ("@", "\n"):
                    mods.append(_text(m, src))
    return mods


def _collect_annotations(node: Node, src: bytes) -> list[str]:
    annotations = []
    for child in node.children:
        if child.type == "modifiers":
            for m in child.children:
                if m.type in ("annotation", "marker_annotation"):
                    annotations.append(_text(m, src))
    return annotations


class ParsedFile:
    """Holds all extracted facts from a single .java file."""

    def __init__(self, file_path: str, repo_id: str):
        self.file_path = file_path
        self.repo_id = repo_id
        self.package_fqn: Optional[str] = None
        self.imports: list[str] = []
        self.classes: list[dict] = []        # ClassNode dicts
        self.interfaces: list[dict] = []
        self.enums: list[dict] = []
        self.methods: list[dict] = []        # MethodNode dicts
        self.fields: list[dict] = []         # FieldNode dicts
        self.edges: list[dict] = []          # {source, target, type}


class JavaParser:
    """
    Parses Java source files using Tree-sitter and extracts structural facts
    ready for writing into Neo4j.
    """

    def __init__(self):
        self._parser = Parser(JAVA_LANGUAGE)

    def parse_file(self, path: Path, repo_id: str) -> ParsedFile:
        src = path.read_bytes()
        tree = self._parser.parse(src)
        result = ParsedFile(str(path), repo_id)
        self._visit_root(tree.root_node, src, result)
        return result

    def parse_source(self, source: str, file_path: str, repo_id: str) -> ParsedFile:
        src = source.encode("utf-8")
        tree = self._parser.parse(src)
        result = ParsedFile(file_path, repo_id)
        self._visit_root(tree.root_node, src, result)
        return result

    # ------------------------------------------------------------------
    # Internal visitors
    # ------------------------------------------------------------------

    def _visit_root(self, root: Node, src: bytes, result: ParsedFile):
        for node in root.children:
            if node.type == "package_declaration":
                self._handle_package(node, src, result)
            elif node.type == "import_declaration":
                self._handle_import(node, src, result)
            elif node.type in ("class_declaration", "interface_declaration",
                               "enum_declaration", "annotation_type_declaration"):
                self._handle_type_declaration(node, src, result, parent_fqn=None)

    def _handle_package(self, node: Node, src: bytes, result: ParsedFile):
        # package com.example.foo;
        for child in node.children:
            if child.type == "scoped_identifier" or child.type == "identifier":
                result.package_fqn = _text(child, src)
                return

    def _handle_import(self, node: Node, src: bytes, result: ParsedFile):
        for child in node.children:
            if child.type in ("scoped_identifier", "identifier"):
                result.imports.append(_text(child, src))

    def _handle_type_declaration(
        self,
        node: Node,
        src: bytes,
        result: ParsedFile,
        parent_fqn: Optional[str],
    ):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        pkg = result.package_fqn or ""
        fqn = f"{pkg}.{name}" if pkg else name
        if parent_fqn:
            fqn = f"{parent_fqn}${name}"   # inner class convention

        kind_map = {
            "class_declaration": "class",
            "interface_declaration": "interface",
            "enum_declaration": "enum",
            "annotation_type_declaration": "annotation",
        }
        kind = kind_map.get(node.type, "class")
        modifiers = _collect_modifiers(node, src)
        if "abstract" in modifiers:
            kind = "abstract"
        annotations = _collect_annotations(node, src)
        javadoc = _extract_javadoc(node, src)

        type_node = {
            "fqn": fqn,
            "name": name,
            "package_fqn": pkg,
            "repo_id": result.repo_id,
            "kind": kind,
            "file_path": result.file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "source_chars": node.end_byte - node.start_byte,
            "annotations": annotations,
            "modifiers": modifiers,
            "javadoc": javadoc,
        }
        result.classes.append(type_node)

        # superclass
        superclass_node = node.child_by_field_name("superclass")
        if superclass_node:
            super_name = _text(superclass_node, src).replace("extends", "").strip()
            result.edges.append({
                "source": fqn,
                "target": super_name,   # may be unqualified — resolved at write time
                "type": "EXTENDS",
                "unresolved": True,
            })

        # interfaces
        interfaces_node = node.child_by_field_name("interfaces")
        if interfaces_node:
            for iface in interfaces_node.children:
                if iface.type in ("type_list", "interface_type_list"):
                    for t in iface.children:
                        if t.type not in (",", "implements", "extends"):
                            iface_name = _text(t, src).strip()
                            if iface_name:
                                result.edges.append({
                                    "source": fqn,
                                    "target": iface_name,
                                    "type": "IMPLEMENTS",
                                    "unresolved": True,
                                })

        # import edges
        for imp in result.imports:
            result.edges.append({
                "source": fqn,
                "target": imp,
                "type": "IMPORTS",
                "unresolved": False,
            })

        # body members
        body = node.child_by_field_name("body")
        if body:
            for member in body.children:
                if member.type == "method_declaration":
                    self._handle_method(member, src, result, fqn)
                elif member.type == "field_declaration":
                    self._handle_field(member, src, result, fqn)
                elif member.type == "constructor_declaration":
                    self._handle_method(member, src, result, fqn, is_constructor=True)
                elif member.type in ("class_declaration", "interface_declaration",
                                     "enum_declaration"):
                    self._handle_type_declaration(member, src, result, parent_fqn=fqn)

    def _handle_method(
        self,
        node: Node,
        src: bytes,
        result: ParsedFile,
        class_fqn: str,
        is_constructor: bool = False,
    ):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        fqn = f"{class_fqn}#{name}"

        return_type = None
        if not is_constructor:
            rt_node = node.child_by_field_name("type")
            if rt_node:
                return_type = _text(rt_node, src)

        params = []
        params_node = node.child_by_field_name("parameters")
        if params_node:
            for p in params_node.children:
                if p.type == "formal_parameter":
                    ptype = p.child_by_field_name("type")
                    pname = p.child_by_field_name("name")
                    if ptype and pname:
                        params.append(f"{_text(ptype, src)} {_text(pname, src)}")

        result.methods.append({
            "fqn": fqn,
            "name": name,
            "class_fqn": class_fqn,
            "return_type": return_type,
            "parameters": params,
            "modifiers": _collect_modifiers(node, src),
            "annotations": _collect_annotations(node, src),
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
        })

        # collect method invocations → CALLS edges
        self._collect_calls(node, src, result, fqn)

    def _collect_calls(self, node: Node, src: bytes, result: ParsedFile, caller_fqn: str):
        """Walk the method body and emit a CALLS edge for every method invocation."""
        queue = list(node.children)
        while queue:
            n = queue.pop()
            if n.type == "method_invocation":
                method_name_node = n.child_by_field_name("name")
                if method_name_node:
                    called = _text(method_name_node, src)
                    obj_node = n.child_by_field_name("object")
                    obj = _text(obj_node, src) if obj_node else None
                    target = f"{obj}#{called}" if obj else f"?#{called}"
                    result.edges.append({
                        "source": caller_fqn,
                        "target": target,
                        "type": "CALLS",
                        "unresolved": True,
                    })
            queue.extend(n.children)

    def _handle_field(self, node: Node, src: bytes, result: ParsedFile, class_fqn: str):
        type_node = node.child_by_field_name("type")
        type_name = _text(type_node, src) if type_node else None

        for child in node.children:
            if child.type == "variable_declarator":
                name_node = child.child_by_field_name("name")
                if name_node:
                    name = _text(name_node, src)
                    result.fields.append({
                        "fqn": f"{class_fqn}#{name}",
                        "name": name,
                        "class_fqn": class_fqn,
                        "type_name": type_name,
                        "modifiers": _collect_modifiers(node, src),
                    })
