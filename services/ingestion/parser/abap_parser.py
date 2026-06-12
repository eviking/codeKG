"""
SAP ABAP source file parser using Tree-sitter (tree-sitter-abap).

Parses .abap files. Extracts:
  - Classes (DEFINITION section for structure; IMPLEMENTATION for method bodies)
  - Interfaces
  - Methods: parameters, return type, visibility modifiers
  - Constructor → <init>
  - FORMs (legacy subroutines — collected under a synthetic module class)
  - INHERITING FROM → EXTENDS edges
  - INTERFACES declaration → IMPLEMENTS edges
  - DATA / CLASS-DATA field declarations
  - CALL METHOD and method_call chains → CALLS edges
  - Comment lines starting with " directly above a node (docstrings)

ABAP specifics:
  - Visibility: PUBLIC / PROTECTED / PRIVATE SECTION maps to modifiers
  - No import statements — ABAP uses inline type references
  - Grammar: kennyhml/tree-sitter-abap (compiled to tree_sitter_abap.so)

Output schema matches ParsedFile from java_parser.py — KGWriter works unchanged.
"""
from __future__ import annotations

import ctypes
import os
import warnings
from pathlib import Path
from typing import Optional

from tree_sitter import Language, Parser, Node

ABAP_EXTENSIONS = frozenset({".abap"})


def _load_abap_language() -> Language:
    _default = os.path.join(os.path.dirname(__file__), "tree_sitter_abap.so")
    so_path = os.environ.get("TREE_SITTER_ABAP_SO") or (
        _default if os.path.exists(_default) else "/usr/local/lib/tree_sitter_abap.so"
    )
    if not os.path.exists(so_path):
        raise ImportError(
            f"ABAP grammar .so not found at {so_path}. "
            "Compile it from https://github.com/kennyhml/tree-sitter-abap:\n"
            "  git clone --depth=1 https://github.com/kennyhml/tree-sitter-abap.git /tmp/ts-abap\n"
            "  gcc -shared -fPIC -o services/ingestion/parser/tree_sitter_abap.so "
            "/tmp/ts-abap/src/parser.c /tmp/ts-abap/src/scanner.c"
        )
    lib = ctypes.CDLL(so_path)
    lib.tree_sitter_abap.restype = ctypes.c_void_p
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return Language(lib.tree_sitter_abap())


_ABAP_LANGUAGE: Optional[Language] = None


def _get_abap_language() -> Language:
    global _ABAP_LANGUAGE
    if _ABAP_LANGUAGE is None:
        _ABAP_LANGUAGE = _load_abap_language()
    return _ABAP_LANGUAGE


def _text(node: Node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _first_child_of_type(node: Node, *types: str) -> Optional[Node]:
    for child in node.named_children:
        if child.type in types:
            return child
    return None


def _first_identifier(node: Node, src: bytes) -> Optional[str]:
    """Return text of first identifier-typed named child."""
    for child in node.named_children:
        if child.type == "identifier":
            return _text(child, src).strip()
    return None


def _collect_comment_above(node: Node, lines: list[str]) -> Optional[str]:
    start_line = node.start_point[0]
    comments = []
    for i in range(start_line - 1, max(start_line - 6, -1), -1):
        line = lines[i].strip() if i < len(lines) else ""
        if line.startswith('"'):
            comments.insert(0, line.lstrip('"').strip())
        else:
            break
    return " ".join(comments) if comments else None


class ParsedFile:
    __slots__ = ("classes", "methods", "fields", "edges", "imports", "package_fqn")

    def __init__(self):
        self.classes: list[dict] = []
        self.methods: list[dict] = []
        self.fields: list[dict] = []
        self.edges: list[dict] = []
        self.imports: list[str] = []
        self.package_fqn: str = ""


class AbapParser:
    """Parser for SAP ABAP source files (.abap)."""

    def parse_file(self, path: Path, repo_id: str) -> ParsedFile:
        try:
            src = path.read_bytes()
        except OSError:
            return ParsedFile()
        return self._parse(src, str(path), repo_id)

    def parse_source(self, source: str, file_path: str, repo_id: str) -> ParsedFile:
        return self._parse(source.encode("utf-8", errors="replace"), file_path, repo_id)

    def _parse(self, src: bytes, file_path: str, repo_id: str) -> ParsedFile:
        result = ParsedFile()
        if not src.strip():
            return result

        parser = Parser(_get_abap_language())
        tree = parser.parse(src)
        lines = src.decode("utf-8", errors="replace").splitlines()
        module_stem = Path(file_path).stem.upper()

        # First pass: class/interface definitions → collect structure + method specs
        class_specs: dict[str, dict] = {}  # upper(name) → {method_specs, fields, edges}

        for node in tree.root_node.named_children:
            if node.type == "class_definition":
                cls, extra = self._handle_class_def(node, src, lines, repo_id)
                if cls:
                    result.classes.append(cls)
                    result.edges.extend(extra.get("edges", []))
                    class_specs[cls["name"].upper()] = extra
            elif node.type == "interface_definition":
                iface = self._handle_interface_def(node, src, lines, repo_id)
                if iface:
                    result.classes.append(iface)

        # Second pass: implementations and FORMs
        free_methods: list[dict] = []
        for node in tree.root_node.named_children:
            if node.type == "class_implementation":
                self._handle_class_impl(node, src, lines, repo_id,
                                        class_specs, result)
            elif node.type == "form_definition":
                m = self._handle_form(node, src, lines, repo_id, module_stem)
                if m:
                    result.edges.extend(m.pop("_edges", []))
                    free_methods.append(m)

        if free_methods:
            result.methods.extend(free_methods)
            result.classes.append({
                "name": module_stem,
                "fqn": module_stem,
                "kind": "module",
                "modifiers": [],
                "annotations": [],
                "javadoc": None,
                "start_line": 1,
                "end_line": len(lines),
                "repo_id": repo_id,
                "file_path": file_path,
            })

        return result

    # ------------------------------------------------------------------
    # Class definition
    # ------------------------------------------------------------------

    def _handle_class_def(self, node: Node, src: bytes, lines: list[str],
                          repo_id: str) -> tuple[Optional[dict], dict]:
        name = _first_identifier(node, src)
        if not name:
            return None, {}

        modifiers: list[str] = []
        edges: list[dict] = []
        kind = "class"

        options = _first_child_of_type(node, "class_options")
        if options:
            for child in options.named_children:
                if child.type == "public_spec":
                    modifiers.append("public")
                elif child.type == "final_spec":
                    modifiers.append("final")
                elif child.type == "abstract_spec":
                    kind = "abstract_class"
                    modifiers.append("abstract")
                elif child.type == "superclass_spec":
                    parent = _first_identifier(child, src)
                    if parent:
                        edges.append({
                            "type": "EXTENDS",
                            "source": name,
                            "target": parent,
                            "repo_id": repo_id,
                        })

        # Scan body for INTERFACES declarations, DATA fields, and method specs
        method_specs: dict[str, dict] = {}
        fields: list[dict] = []
        body = _first_child_of_type(node, "class_body")
        if body:
            for section in body.named_children:
                visibility = {
                    "public_section": "public",
                    "protected_section": "protected",
                    "private_section": "private",
                }.get(section.type)
                if visibility is None:
                    continue
                for child in section.named_children:
                    if child.type == "interfaces_declaration":
                        iface = _first_identifier(child, src)
                        if iface:
                            edges.append({
                                "type": "IMPLEMENTS",
                                "source": name,
                                "target": iface,
                                "repo_id": repo_id,
                            })
                    elif child.type == "methods_declaration":
                        for spec_node in child.named_children:
                            if spec_node.type == "method_spec":
                                s = self._parse_method_spec(
                                    spec_node, src, visibility, name, repo_id)
                                if s:
                                    method_specs[s["name"].upper()] = s
                            elif spec_node.type == "constructor_spec":
                                s = self._parse_constructor_spec(
                                    spec_node, src, visibility, name, repo_id)
                                if s:
                                    method_specs["CONSTRUCTOR"] = s
                    elif child.type in ("data_declaration", "class_data_declaration"):
                        f = self._handle_field(child, src, name, repo_id, visibility)
                        if f:
                            fields.append(f)

        cls = {
            "name": name,
            "fqn": name,
            "kind": kind,
            "modifiers": modifiers,
            "annotations": [],
            "javadoc": _collect_comment_above(node, lines),
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "repo_id": repo_id,
        }
        extra = {"edges": edges, "method_specs": method_specs, "fields": fields}
        return cls, extra

    # ------------------------------------------------------------------
    # Interface definition
    # ------------------------------------------------------------------

    def _handle_interface_def(self, node: Node, src: bytes, lines: list[str],
                              repo_id: str) -> Optional[dict]:
        name = _first_identifier(node, src)
        if not name:
            return None
        return {
            "name": name,
            "fqn": name,
            "kind": "interface",
            "modifiers": ["public"],
            "annotations": [],
            "javadoc": _collect_comment_above(node, lines),
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "repo_id": repo_id,
        }

    # ------------------------------------------------------------------
    # Class implementation
    # ------------------------------------------------------------------

    def _handle_class_impl(self, node: Node, src: bytes, lines: list[str],
                           repo_id: str, class_specs: dict,
                           result: ParsedFile) -> None:
        name = _first_identifier(node, src)
        if not name:
            return

        extra = class_specs.get(name.upper(), {})
        method_specs: dict = extra.get("method_specs", {})
        for f in extra.get("fields", []):
            result.fields.append(f)

        for child in node.named_children:
            if child.type == "method_implementation":
                m = self._handle_method_impl(
                    child, src, lines, name, repo_id, method_specs)
                if m:
                    result.edges.extend(m.pop("_edges", []))
                    result.methods.append(m)

    def _handle_method_impl(self, node: Node, src: bytes, lines: list[str],
                            class_fqn: str, repo_id: str,
                            method_specs: dict) -> Optional[dict]:
        raw_name = _first_identifier(node, src)
        if not raw_name:
            return None

        is_ctor = raw_name.lower() == "constructor"
        name = "<init>" if is_ctor else raw_name
        spec = method_specs.get(raw_name.upper(), {})

        modifiers = list(spec.get("modifiers", []))
        if is_ctor and "constructor" not in modifiers:
            modifiers.append("constructor")

        edges: list[dict] = []
        body = _first_child_of_type(node, "method_body")
        if body:
            self._collect_calls(body, src, f"{class_fqn}.{name}", repo_id, edges)
        # Also scan ERROR recovery nodes for method calls
        for child in node.named_children:
            if child.type == "ERROR":
                self._collect_calls(child, src, f"{class_fqn}.{name}", repo_id, edges)

        return {
            "name": name,
            "class_fqn": class_fqn,
            "modifiers": modifiers,
            "parameters": spec.get("parameters", []),
            "return_type": spec.get("return_type"),
            "annotations": spec.get("annotations", []),
            "docstring": _collect_comment_above(node, lines),
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "repo_id": repo_id,
            "_edges": edges,
        }

    # ------------------------------------------------------------------
    # Method spec parsing
    # ------------------------------------------------------------------

    def _parse_method_spec(self, node: Node, src: bytes, visibility: str,
                           class_fqn: str, repo_id: str) -> Optional[dict]:
        name = _first_identifier(node, src)
        if not name:
            return None

        modifiers = [visibility]
        for child in node.named_children:
            if child.type == "static_spec":
                modifiers.append("static")
            elif child.type == "abstract_spec":
                modifiers.append("abstract")
            elif child.type == "redefinition_spec":
                modifiers.append("redefined")

        return_type = None
        rv = _first_child_of_type(node, "return_value")
        if rv:
            # return_value has: value_param_spec, then referred_type or abap_type
            type_node = _first_child_of_type(rv, "referred_type", "abap_type")
            if type_node:
                return_type = _text(type_node, src).replace("TYPE", "").strip()

        return {
            "name": name,
            "modifiers": modifiers,
            "parameters": self._extract_params(node, src),
            "return_type": return_type,
            "annotations": [],
            "class_fqn": class_fqn,
            "repo_id": repo_id,
        }

    def _parse_constructor_spec(self, node: Node, src: bytes, visibility: str,
                                class_fqn: str, repo_id: str) -> dict:
        return {
            "name": "constructor",
            "modifiers": [visibility, "constructor"],
            "parameters": self._extract_params(node, src),
            "return_type": None,
            "annotations": [],
            "class_fqn": class_fqn,
            "repo_id": repo_id,
        }

    def _extract_params(self, node: Node, src: bytes) -> list[str]:
        params: list[str] = []
        for child in node.named_children:
            if child.type == "parameter_list":
                for p in child.named_children:
                    if p.type == "parameter":
                        spec = _first_child_of_type(
                            p, "simple_param_spec", "value_param_spec")
                        if spec:
                            pname = _first_identifier(spec, src)
                            if pname:
                                type_node = _first_child_of_type(
                                    p, "abap_type", "referred_type", "reference_type")
                                type_str = ""
                                if type_node:
                                    type_str = " TYPE " + _text(type_node, src).replace("TYPE", "").strip()
                                params.append(pname + type_str)
        return params

    # ------------------------------------------------------------------
    # FORM subroutines
    # ------------------------------------------------------------------

    def _handle_form(self, node: Node, src: bytes, lines: list[str],
                     repo_id: str, module_stem: str) -> Optional[dict]:
        name = _first_identifier(node, src)
        if not name:
            return None

        edges: list[dict] = []
        body = _first_child_of_type(node, "form_body")
        if body:
            self._collect_calls(body, src, f"{module_stem}.{name}", repo_id, edges)

        return {
            "name": name,
            "class_fqn": module_stem,
            "modifiers": ["public"],
            "parameters": self._extract_params(node, src),
            "return_type": None,
            "annotations": [],
            "docstring": _collect_comment_above(node, lines),
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "repo_id": repo_id,
            "_edges": edges,
        }

    # ------------------------------------------------------------------
    # Field declarations
    # ------------------------------------------------------------------

    def _handle_field(self, node: Node, src: bytes, class_fqn: str,
                      repo_id: str, visibility: str) -> Optional[dict]:
        spec_type = "data_spec" if node.type == "data_declaration" else "class_data_spec"
        spec = _first_child_of_type(node, spec_type)
        if not spec:
            return None
        name = _first_identifier(spec, src)
        if not name:
            return None

        modifiers = [visibility]
        if node.type == "class_data_declaration":
            modifiers.append("static")

        type_node = _first_child_of_type(
            spec, "abap_type", "referred_type", "reference_type")
        type_str = _text(type_node, src).replace("TYPE", "").strip() if type_node else None

        return {
            "name": name,
            "class_fqn": class_fqn,
            "type": type_str,
            "modifiers": modifiers,
            "repo_id": repo_id,
        }

    # ------------------------------------------------------------------
    # CALLS edge collection — walks recursively, handles both
    # CALL METHOD <name> and <obj>-><method>( ) patterns
    # ------------------------------------------------------------------

    def _collect_calls(self, node: Node, src: bytes, caller_fqn: str,
                       repo_id: str, edges: list) -> None:
        if node.type == "call_method_statement":
            # CALL METHOD <identifier> — last identifier is the target
            ids = [c for c in node.named_children if c.type == "identifier"]
            if ids:
                edges.append({
                    "type": "CALLS",
                    "source": caller_fqn,
                    "target": _text(ids[-1], src).strip(),
                    "repo_id": repo_id,
                })
        elif node.type == "method_call":
            # <obj>->method( ) — identifiers are [obj, method]; last is target
            ids = [c for c in node.named_children if c.type == "identifier"]
            if len(ids) >= 2:
                edges.append({
                    "type": "CALLS",
                    "source": caller_fqn,
                    "target": _text(ids[-1], src).strip(),
                    "repo_id": repo_id,
                })

        for child in node.named_children:
            self._collect_calls(child, src, caller_fqn, repo_id, edges)
