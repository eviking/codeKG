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
                    # Detect BAdI implementations and annotate the class
                    badi_iface = self._detect_badi_definition(node, src)
                    if badi_iface:
                        cls.setdefault("annotations", []).append(f"@BAdI({badi_iface})")
                    result.classes.append(cls)
                    result.edges.extend(extra.get("edges", []))
                    class_specs[cls["name"].upper()] = extra
            elif node.type == "interface_definition":
                iface = self._handle_interface_def(node, src, lines, repo_id)
                if iface:
                    result.classes.append(iface)

        # Second pass: implementations, FORMs, top-level INCLUDEs, and
        # event blocks (START-OF-SELECTION, etc.) that contain PERFORM/CALL FUNCTION
        free_methods: list[dict] = []
        include_edges: list[dict] = []
        for node in tree.root_node.named_children:
            if node.type == "class_implementation":
                self._handle_class_impl(node, src, lines, repo_id,
                                        class_specs, result)
            elif node.type == "form_definition":
                m = self._handle_form(node, src, lines, repo_id, module_stem)
                if m:
                    result.edges.extend(m.pop("_edges", []))
                    free_methods.append(m)
            elif node.type == "include_statement":
                self._collect_includes(node, src, module_stem, repo_id, include_edges)
            elif node.type in (
                "start_of_selection_event", "end_of_selection_event",
                "at_selection_screen_event", "initialization_event",
                "load_of_program_event", "top_of_page_event",
                "end_of_page_event", "at_line_selection_event",
                "at_user_command_event",
            ):
                # ABAP report event blocks — collect CALLS/SQL from their statement blocks
                for child in node.named_children:
                    if child.type == "statement_block":
                        self._collect_calls(child, src, module_stem, repo_id, include_edges)
                        self._collect_sql(child, src, module_stem, repo_id, include_edges)

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

        result.edges.extend(include_edges)

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
        caller = f"{class_fqn}.{name}"
        body = _first_child_of_type(node, "method_body")
        if body:
            self._collect_calls(body, src, caller, repo_id, edges)
            self._collect_sql(body, src, caller, repo_id, edges)
        # Also scan ERROR recovery nodes for method calls
        for child in node.named_children:
            if child.type == "ERROR":
                self._collect_calls(child, src, caller, repo_id, edges)
                self._collect_sql(child, src, caller, repo_id, edges)

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
        caller = f"{module_stem}.{name}"
        body = _first_child_of_type(node, "form_body")
        if body:
            self._collect_calls(body, src, caller, repo_id, edges)
            self._collect_sql(body, src, caller, repo_id, edges)

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
    # CALLS edge collection — walks recursively, handles:
    #   CALL METHOD <name>           (OO method call statement)
    #   <obj>->method( )             (inline chained call)
    #   CALL FUNCTION 'FM_NAME'      (function module / BAPI call)
    #   PERFORM <form_name>          (legacy FORM subroutine call)
    #   CALL BADI <badi_name>        (BAdI invocation)
    #   GET BADI <badi_handle>       (BAdI instantiation — marks invisible caller)
    # ------------------------------------------------------------------

    def _collect_calls(self, node: Node, src: bytes, caller_fqn: str,
                       repo_id: str, edges: list) -> None:
        if node.type == "call_method_statement":
            ids = [c for c in node.named_children if c.type == "identifier"]
            if ids:
                edges.append({
                    "type": "CALLS",
                    "source": caller_fqn,
                    "target": _text(ids[-1], src).strip(),
                    "repo_id": repo_id,
                })
        elif node.type == "function_call":
            # me->method( ) and lo_obj->method( ) both parse as function_call
            # with a `name` field (identifier) holding the method name.
            name_node = node.child_by_field_name("name")
            if name_node:
                edges.append({
                    "type": "CALLS",
                    "source": caller_fqn,
                    "target": _text(name_node, src).strip(),
                    "repo_id": repo_id,
                })
        elif node.type == "call_function_statement":
            # CALL FUNCTION 'FM_NAME' — function name is a string_literal child
            for child in node.named_children:
                if child.type in ("string_literal", "string"):
                    fm_name = _text(child, src).strip("'\"").strip()
                    if fm_name:
                        edges.append({
                            "type": "CALLS",
                            "source": caller_fqn,
                            "target": fm_name,
                            "repo_id": repo_id,
                        })
                    break
        elif node.type == "perform_statement":
            # PERFORM form_name — grammar wraps name in subroutine_spec > identifier
            for child in node.named_children:
                if child.type == "subroutine_spec":
                    form_id = _first_identifier(child, src)
                    if form_id:
                        edges.append({
                            "type": "CALLS",
                            "source": caller_fqn,
                            "target": form_id,
                            "repo_id": repo_id,
                        })
                    break
                elif child.type == "identifier":
                    # fallback for grammar variants
                    edges.append({
                        "type": "CALLS",
                        "source": caller_fqn,
                        "target": _text(child, src).strip(),
                        "repo_id": repo_id,
                    })
                    break
        elif node.type in ("call_badi_statement", "get_badi_statement"):
            # CALL BADI <handle> / GET BADI <handle> — first identifier is the handle
            for child in node.named_children:
                if child.type == "identifier":
                    badi_name = _text(child, src).strip()
                    if badi_name:
                        edges.append({
                            "type": "CALLS",
                            "source": caller_fqn,
                            "target": badi_name,
                            "repo_id": repo_id,
                        })
                    break

        for child in node.named_children:
            self._collect_calls(child, src, caller_fqn, repo_id, edges)

    # ------------------------------------------------------------------
    # Open SQL edge collection — the tree-sitter-abap grammar does NOT
    # produce structured nodes for SELECT/INSERT/UPDATE/DELETE statements
    # (they fall into ERROR or assignment nodes). We therefore use regex
    # on the raw body text, which is reliable for ABAP's fixed-keyword SQL.
    # ------------------------------------------------------------------

    _SQL_RE = import_re = None  # lazy compile

    @staticmethod
    def _get_sql_re():
        import re as _re
        # Patterns that reliably anchor the table name:
        #   SELECT ... FROM <table>
        #   INSERT INTO <table> / INSERT <table>
        #   UPDATE <table> SET / UPDATE <table> FROM
        #   DELETE FROM <table>
        #   MODIFY <table>
        return _re.compile(
            r'\b(?:'
            r'SELECT\b[^.]*?\bFROM\s+([A-Za-z]\w*)'       # SELECT … FROM table
            r'|INSERT\s+INTO\s+([A-Za-z]\w*)'             # INSERT INTO table
            r'|INSERT\s+([A-Za-z]\w*)\s+(?:VALUES|FROM)'  # INSERT table VALUES/FROM
            r'|UPDATE\s+([A-Za-z]\w*)\s+(?:SET|FROM)'     # UPDATE table SET/FROM
            r'|DELETE\s+FROM\s+([A-Za-z]\w*)'             # DELETE FROM table
            r'|MODIFY\s+([A-Za-z]\w*)\b'                  # MODIFY table
            r')',
            _re.IGNORECASE | _re.DOTALL,
        )

    def _collect_sql(self, node: Node, src: bytes, caller_fqn: str,
                     repo_id: str, edges: list) -> None:
        """Scan the raw text of a method/form body for Open SQL statements."""
        body_text = src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        sql_re = self._get_sql_re()
        seen: set[str] = set()
        _skip = {"INTO", "TABLE", "WHERE", "SET", "FROM", "SINGLE",
                 "ALL", "FIELDS", "UP", "CLIENT", "DISTINCT", "INNER",
                 "LEFT", "RIGHT", "JOIN", "ON", "AS"}
        for m in sql_re.finditer(body_text):
            # Multiple capture groups — take the first non-None one
            table = next((g for g in m.groups() if g), None)
            if not table:
                continue
            table = table.strip().upper()
            if table in _skip:
                continue
            if table not in seen:
                seen.add(table)
                edges.append({
                    "type": "QUERIES",
                    "source": caller_fqn,
                    "target": table,
                    "repo_id": repo_id,
                })

    # ------------------------------------------------------------------
    # INCLUDE tracking — emits CALLS edge from the including program/class
    # to the included object so include files don't appear as orphans.
    # ------------------------------------------------------------------

    def _collect_includes(self, node: Node, src: bytes, caller_fqn: str,
                          repo_id: str, edges: list) -> None:
        if node.type == "include_statement":
            for child in node.named_children:
                if child.type == "identifier":
                    include_name = _text(child, src).strip().upper()
                    if include_name:
                        edges.append({
                            "type": "CALLS",
                            "source": caller_fqn,
                            "target": include_name,
                            "repo_id": repo_id,
                        })
                    break
        for child in node.named_children:
            self._collect_includes(child, src, caller_fqn, repo_id, edges)

    # ------------------------------------------------------------------
    # BAdI definition detection — marks a class as a BAdI implementation
    # so its methods don't appear as dead code even with no direct callers.
    # ------------------------------------------------------------------

    def _detect_badi_definition(self, node: Node, src: bytes) -> Optional[str]:
        """Return BAdI name if this class_definition implements a BAdI interface."""
        if node.type != "class_definition":
            return None
        body = _first_child_of_type(node, "class_body")
        if not body:
            return None
        for section in body.named_children:
            for child in section.named_children:
                if child.type == "interfaces_declaration":
                    iface = _first_identifier(child, src)
                    # BAdI implementations always start with ZCL_IM_ or Y/ZCL_ by convention;
                    # the interface name starts with ZIF_EX_ or IF_EX_ (exit interface prefix)
                    if iface and ("_EX_" in iface.upper() or iface.upper().startswith("IF_EX")):
                        return iface
        return None
