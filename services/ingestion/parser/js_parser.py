"""
JavaScript and TypeScript source file parser using Tree-sitter.

Handles: .js, .jsx, .mjs, .cjs, .ts, .tsx

Extracts:
  - ES6 classes (extends, implements via TS, decorators, abstract)
  - TypeScript interfaces and enums
  - Class methods (including async, static, get/set accessors)
  - Class fields (public_field_definition, field_definition)
  - Module-level functions (function declarations, arrow functions assigned
    to const/let/var, exported functions) — indexed under a synthetic
    "<module>" class per file
  - Imports: ES module (import … from) and CommonJS (require())
  - Exports: named exports tracked as annotations on synthetic module class
  - CALLS edges from method/function bodies
  - JSDoc block comments (/** … */) on classes and methods

Output schema matches ParsedFile from java_parser.py — KGWriter unchanged.

JS/TS specifics:
  - TypeScript uses tree-sitter-typescript; JS uses tree-sitter-javascript
  - TSX uses language_tsx(); TS uses language_typescript()
  - Decorators stored as annotations (e.g. "@Injectable()")
  - async keyword stored in modifiers
  - Private fields (#name) preserved as-is in field names
  - Arrow functions and function expressions assigned to identifiers are
    captured as module-level methods of the synthetic "<module>" class
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser, Node

JS_LANGUAGE = Language(tsjs.language())
TS_LANGUAGE = Language(tsts.language_typescript())
TSX_LANGUAGE = Language(tsts.language_tsx())

JS_EXTENSIONS = {".js", ".jsx", ".mjs", ".cjs"}
TS_EXTENSIONS = {".ts", ".tsx"}
JS_TS_EXTENSIONS = JS_EXTENSIONS | TS_EXTENSIONS

# Node types that introduce a callable body we want to track
_FUNC_TYPES = frozenset({
    "function_declaration",
    "function_expression",
    "arrow_function",
    "generator_function_declaration",
    "generator_function",
})


def _text(node: Node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _jsdoc(node: Node, src: bytes) -> Optional[str]:
    """Return the JSDoc comment (/** … */) immediately before this node."""
    parent = node.parent
    if parent is None:
        return None
    siblings = list(parent.children)
    idx = next((i for i, c in enumerate(siblings) if c == node), None)
    if idx is None or idx == 0:
        return None
    prev = siblings[idx - 1]
    if prev.type == "comment":
        raw = _text(prev, src)
        if raw.startswith("/**"):
            lines = [ln.strip().lstrip("*").strip() for ln in raw[3:-2].splitlines()]
            return " ".join(ln for ln in lines if ln).strip() or None
    return None


def _extract_string(node: Node, src: bytes) -> Optional[str]:
    """Get the string value from a string literal node."""
    raw = _text(node, src).strip("\"'`")
    return raw if raw else None


class ParsedFile:
    def __init__(self, file_path: str, repo_id: str):
        self.file_path = file_path
        self.repo_id = repo_id
        self.package_fqn: Optional[str] = None
        self.imports: list[str] = []
        self.classes: list[dict] = []
        self.interfaces: list[dict] = []
        self.enums: list[dict] = []
        self.methods: list[dict] = []
        self.fields: list[dict] = []
        self.edges: list[dict] = []


class JsParser:
    """
    Parses JavaScript and TypeScript source files via Tree-sitter.
    Produces the same ParsedFile schema as JavaParser / PythonParser.
    """

    def __init__(self):
        self._js_parser = Parser(JS_LANGUAGE)
        self._ts_parser = Parser(TS_LANGUAGE)
        self._tsx_parser = Parser(TSX_LANGUAGE)

    def parse_file(self, path: Path, repo_id: str) -> ParsedFile:
        src = path.read_bytes()
        ext = path.suffix.lower()
        if ext == ".tsx":
            parser = self._tsx_parser
        elif ext in TS_EXTENSIONS:
            parser = self._ts_parser
        else:
            parser = self._js_parser
        tree = parser.parse(src)
        result = ParsedFile(str(path), repo_id)
        # Derive module FQN from file path (last component without extension)
        module_name = path.stem
        self._visit_program(tree.root_node, src, result, module_name)
        return result

    # ------------------------------------------------------------------
    # Top-level program visitor
    # ------------------------------------------------------------------

    def _visit_program(self, root: Node, src: bytes, result: ParsedFile,
                       module_name: str):
        # Synthetic class representing module-level declarations
        module_fqn = module_name
        module_annotations: list[str] = []
        has_module_level = False

        for node in root.children:
            if node.type == "class_declaration":
                self._handle_class(node, src, result, namespace=module_name)
            elif node.type == "abstract_class_declaration":
                self._handle_class(node, src, result, namespace=module_name,
                                   abstract=True)
            elif node.type in ("interface_declaration",):
                self._handle_interface(node, src, result, namespace=module_name)
            elif node.type == "enum_declaration":
                self._handle_enum(node, src, result, namespace=module_name)
            elif node.type == "type_alias_declaration":
                self._handle_type_alias(node, src, result, namespace=module_name)
            elif node.type == "function_declaration":
                fn_name = self._func_name(node, src)
                if fn_name:
                    has_module_level = True
                    self._handle_function(node, src, result,
                                          class_fqn=module_fqn,
                                          name=fn_name)
            elif node.type == "generator_function_declaration":
                fn_name = self._func_name(node, src)
                if fn_name:
                    has_module_level = True
                    self._handle_function(node, src, result,
                                          class_fqn=module_fqn,
                                          name=fn_name,
                                          extra_modifiers=["generator"])
            elif node.type in ("lexical_declaration", "variable_declaration"):
                # const/let/var foo = () => {} or function() {}
                declared = self._extract_var_funcs(node, src, result, module_fqn)
                if declared:
                    has_module_level = True
            elif node.type == "export_statement":
                exported = self._handle_export(node, src, result,
                                               module_fqn, module_annotations)
                if exported:
                    has_module_level = True
            elif node.type == "import_statement":
                self._handle_import(node, src, result)
            elif node.type == "expression_statement":
                # module.exports = { ... } / module.exports.fn = function() {}
                exported = self._handle_module_exports(node, src, result, module_fqn)
                if exported:
                    has_module_level = True

        if has_module_level:
            result.classes.append({
                "fqn": module_fqn,
                "name": module_name,
                "package_fqn": "",
                "repo_id": result.repo_id,
                "kind": "module",
                "file_path": result.file_path,
                "start_line": 1,
                "end_line": root.end_point[0] + 1,
                "annotations": module_annotations,
                "modifiers": [],
                "javadoc": None,
            })

    # ------------------------------------------------------------------
    # Class
    # ------------------------------------------------------------------

    def _handle_class(self, node: Node, src: bytes, result: ParsedFile,
                      namespace: str, abstract: bool = False,
                      parent_fqn: Optional[str] = None):
        # name node: identifier or type_identifier
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        fqn = f"{parent_fqn}.{name}" if parent_fqn else (
            f"{namespace}.{name}" if namespace else name
        )

        # Decorators (TypeScript)
        decorators = self._collect_decorators(node, src)
        modifiers: list[str] = []
        if abstract:
            modifiers.append("abstract")

        # Superclass — class_heritage > extends > identifier
        heritage = node.child_by_field_name("heritage") or node.child_by_field_name("body")
        heritage_node = next(
            (c for c in node.children if c.type == "class_heritage"), None
        )
        if heritage_node:
            for child in heritage_node.children:
                if child.type in ("extends_clause",):
                    for tc in child.children:
                        if tc.type in ("identifier", "type_identifier", "member_expression"):
                            base = _text(tc, src).strip()
                            result.edges.append({"source": fqn, "target": base,
                                                  "type": "EXTENDS", "unresolved": True})
                elif child.type == "implements_clause":
                    for tc in child.children:
                        if tc.type in ("type_identifier", "identifier", "generic_type"):
                            iface = _text(tc, src).strip()
                            if iface:
                                result.edges.append({"source": fqn, "target": iface,
                                                      "type": "IMPLEMENTS",
                                                      "unresolved": True})
                # JS grammar: heritage is "extends <id>" without explicit sub-nodes
                elif child.type == "identifier":
                    result.edges.append({"source": fqn, "target": _text(child, src),
                                          "type": "EXTENDS", "unresolved": True})

        doc = _jsdoc(node, src)
        kind = "abstract_class" if abstract else "class"

        result.classes.append({
            "fqn": fqn,
            "name": name,
            "package_fqn": namespace,
            "repo_id": result.repo_id,
            "kind": kind,
            "file_path": result.file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "annotations": decorators,
            "modifiers": modifiers,
            "javadoc": doc,
        })

        body = node.child_by_field_name("body")
        if body:
            self._visit_class_body(body, src, result, class_fqn=fqn,
                                   namespace=namespace)

    def _visit_class_body(self, body: Node, src: bytes, result: ParsedFile,
                          class_fqn: str, namespace: str):
        pending_decorators: list[str] = []
        for member in body.children:
            if member.type == "decorator":
                pending_decorators.append(_text(member, src).strip())
                continue
            if member.type == "method_definition":
                self._handle_method_def(member, src, result, class_fqn,
                                        extra_annotations=pending_decorators)
                pending_decorators = []
            elif member.type in ("public_field_definition", "field_definition"):
                self._handle_field_def(member, src, result, class_fqn)
                pending_decorators = []
            elif member.type == "class_declaration":
                self._handle_class(member, src, result, namespace=namespace,
                                   parent_fqn=class_fqn)
                pending_decorators = []
            else:
                pending_decorators = []

    # ------------------------------------------------------------------
    # Interface (TypeScript)
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
        doc = _jsdoc(node, src)
        result.classes.append({
            "fqn": fqn,
            "name": name,
            "package_fqn": namespace,
            "repo_id": result.repo_id,
            "kind": "interface",
            "file_path": result.file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "annotations": [],
            "modifiers": [],
            "javadoc": doc,
        })
        body = node.child_by_field_name("body")
        if body:
            for member in body.children:
                if member.type == "method_signature":
                    self._handle_method_sig(member, src, result, class_fqn=fqn)

    # ------------------------------------------------------------------
    # Enum (TypeScript)
    # ------------------------------------------------------------------

    def _handle_enum(self, node: Node, src: bytes, result: ParsedFile,
                     namespace: str):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        fqn = f"{namespace}.{name}" if namespace else name
        doc = _jsdoc(node, src)
        result.classes.append({
            "fqn": fqn,
            "name": name,
            "package_fqn": namespace,
            "repo_id": result.repo_id,
            "kind": "enum",
            "file_path": result.file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "annotations": [],
            "modifiers": [],
            "javadoc": doc,
        })

    # ------------------------------------------------------------------
    # Type alias (TypeScript) — emitted as a class with kind="type"
    # ------------------------------------------------------------------

    def _handle_type_alias(self, node: Node, src: bytes, result: ParsedFile,
                           namespace: str):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        fqn = f"{namespace}.{name}" if namespace else name
        result.classes.append({
            "fqn": fqn,
            "name": name,
            "package_fqn": namespace,
            "repo_id": result.repo_id,
            "kind": "type",
            "file_path": result.file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "annotations": [],
            "modifiers": [],
            "javadoc": None,
        })

    # ------------------------------------------------------------------
    # Method definition (inside class body)
    # ------------------------------------------------------------------

    def _handle_method_def(self, node: Node, src: bytes, result: ParsedFile,
                           class_fqn: str, extra_annotations: list[str] | None = None):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        if name == "constructor":
            method_name = "<init>"
            fqn = f"{class_fqn}#<init>"
        else:
            method_name = name
            fqn = f"{class_fqn}#{name}"

        modifiers: list[str] = []
        for child in node.children:
            if child.type in ("static", "async", "get", "set", "override",
                              "abstract", "readonly"):
                modifiers.append(child.type)
            elif child.type == "accessibility_modifier":
                modifiers.append(_text(child, src).lower())

        params = self._extract_params(node, src)
        return_type = self._extract_return_type(node, src)
        doc = _jsdoc(node, src)
        annotations = list(extra_annotations or [])

        # TypeScript: gather decorators that are siblings before the method in the class body
        result.methods.append({
            "fqn": fqn,
            "name": method_name,
            "class_fqn": class_fqn,
            "repo_id": result.repo_id,
            "return_type": return_type,
            "parameters": params,
            "modifiers": modifiers,
            "annotations": annotations,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "docstring": doc,
        })

        body = node.child_by_field_name("body") or node.child_by_field_name("value")
        if body:
            self._collect_calls(body, src, result, fqn)

    def _handle_method_sig(self, node: Node, src: bytes, result: ParsedFile,
                           class_fqn: str):
        """Interface method signatures (TypeScript)."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        fqn = f"{class_fqn}#{name}"
        params = self._extract_params(node, src)
        return_type = self._extract_return_type(node, src)
        result.methods.append({
            "fqn": fqn,
            "name": name,
            "class_fqn": class_fqn,
            "repo_id": result.repo_id,
            "return_type": return_type,
            "parameters": params,
            "modifiers": ["abstract"],
            "annotations": [],
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "docstring": None,
        })

    # ------------------------------------------------------------------
    # Field definition (inside class body)
    # ------------------------------------------------------------------

    def _handle_field_def(self, node: Node, src: bytes, result: ParsedFile,
                          class_fqn: str):
        modifiers: list[str] = []
        fname: Optional[str] = None

        for child in node.children:
            if child.type in ("static", "readonly", "abstract", "override",
                              "declare"):
                modifiers.append(child.type)
            elif child.type == "accessibility_modifier":
                modifiers.append(_text(child, src).lower())
            elif child.type in ("property_identifier",
                                "private_property_identifier"):
                # JS grammar: name is a bare property_identifier child
                fname = _text(child, src).strip()
            # TS: name comes from the "name" field
            elif child.type == "identifier" and fname is None:
                fname = _text(child, src).strip()

        # TS grammar exposes name via field
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            fname = _text(name_node, src).strip()

        if not fname:
            return

        type_node = node.child_by_field_name("type")
        ftype = _text(type_node, src).lstrip(":").strip() if type_node else "any"

        result.fields.append({
            "name": fname,
            "class_fqn": class_fqn,
            "type": ftype,
            "modifiers": modifiers,
        })

    # ------------------------------------------------------------------
    # Module-level function declarations
    # ------------------------------------------------------------------

    def _handle_function(self, node: Node, src: bytes, result: ParsedFile,
                         class_fqn: str, name: str,
                         extra_modifiers: list[str] | None = None):
        modifiers: list[str] = list(extra_modifiers or [])
        for child in node.children:
            if child.type == "async":
                modifiers.append("async")
        params = self._extract_params(node, src)
        return_type = self._extract_return_type(node, src)
        doc = _jsdoc(node, src)
        fqn = f"{class_fqn}#{name}"

        result.methods.append({
            "fqn": fqn,
            "name": name,
            "class_fqn": class_fqn,
            "repo_id": result.repo_id,
            "return_type": return_type,
            "parameters": params,
            "modifiers": modifiers,
            "annotations": [],
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "docstring": doc,
        })

        body = node.child_by_field_name("body")
        if body:
            self._collect_calls(body, src, result, fqn)

    # ------------------------------------------------------------------
    # Variable declarations (const fn = () => {}, const fn = function() {})
    # ------------------------------------------------------------------

    def _extract_var_funcs(self, node: Node, src: bytes, result: ParsedFile,
                           module_fqn: str) -> bool:
        """Return True if any function-valued var declarators were found."""
        found = False
        for child in node.children:
            if child.type != "variable_declarator":
                continue
            name_node = child.child_by_field_name("name")
            value_node = child.child_by_field_name("value")
            if name_node is None or value_node is None:
                continue
            if value_node.type not in _FUNC_TYPES:
                continue
            name = _text(name_node, src).strip()
            if not name or not re.match(r"^[a-zA-Z_$][\w$]*$", name):
                continue
            self._handle_function(value_node, src, result,
                                   class_fqn=module_fqn, name=name)
            found = True
        return found

    # ------------------------------------------------------------------
    # Export statements
    # ------------------------------------------------------------------

    def _handle_export(self, node: Node, src: bytes, result: ParsedFile,
                       module_fqn: str,
                       module_annotations: list[str]) -> bool:
        """Process export_statement; return True if any callable was found."""
        found = False
        for child in node.children:
            if child.type == "class_declaration":
                self._handle_class(child, src, result, namespace=module_fqn)
                found = True
            elif child.type == "abstract_class_declaration":
                self._handle_class(child, src, result, namespace=module_fqn,
                                   abstract=True)
                found = True
            elif child.type in ("interface_declaration",):
                self._handle_interface(child, src, result, namespace=module_fqn)
            elif child.type == "enum_declaration":
                self._handle_enum(child, src, result, namespace=module_fqn)
            elif child.type == "type_alias_declaration":
                self._handle_type_alias(child, src, result, namespace=module_fqn)
            elif child.type == "function_declaration":
                fn_name = self._func_name(child, src)
                if fn_name:
                    self._handle_function(child, src, result,
                                           class_fqn=module_fqn, name=fn_name)
                    found = True
            elif child.type in ("lexical_declaration", "variable_declaration"):
                if self._extract_var_funcs(child, src, result, module_fqn):
                    found = True
            elif child.type == "export_clause":
                # export { foo, bar } — track as module annotations
                for spec in child.children:
                    if spec.type == "export_specifier":
                        id_node = spec.child_by_field_name("name") or next(
                            (c for c in spec.children if c.type == "identifier"), None
                        )
                        if id_node:
                            module_annotations.append(f"@export({_text(id_node, src)})")
        return found

    # ------------------------------------------------------------------
    # module.exports = ... (CommonJS)
    # ------------------------------------------------------------------

    def _handle_module_exports(self, node: Node, src: bytes, result: ParsedFile,
                               module_fqn: str) -> bool:
        """Detect module.exports assignments and emit methods for functions."""
        expr = next((c for c in node.children
                     if c.type in ("assignment_expression",)), None)
        if expr is None:
            return False
        left = expr.child_by_field_name("left")
        right = expr.child_by_field_name("right")
        if left is None or right is None:
            return False
        left_text = _text(left, src)
        if not left_text.startswith("module.exports"):
            return False

        found = False
        if right.type in _FUNC_TYPES:
            name = "default"
            self._handle_function(right, src, result,
                                   class_fqn=module_fqn, name=name)
            found = True
        elif right.type == "object":
            for prop in right.children:
                if prop.type in ("pair", "shorthand_property_identifier"):
                    key_node = prop.child_by_field_name("key") or prop
                    val_node = prop.child_by_field_name("value")
                    if key_node and val_node and val_node.type in _FUNC_TYPES:
                        name = _text(key_node, src).strip()
                        if re.match(r"^[a-zA-Z_$][\w$]*$", name):
                            self._handle_function(val_node, src, result,
                                                   class_fqn=module_fqn, name=name)
                            found = True
        return found

    # ------------------------------------------------------------------
    # Import statements
    # ------------------------------------------------------------------

    def _handle_import(self, node: Node, src: bytes, result: ParsedFile):
        """Collect ES module import sources."""
        src_node = node.child_by_field_name("source")
        if src_node:
            val = _extract_string(src_node, src)
            if val:
                result.imports.append(val)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _func_name(self, node: Node, src: bytes) -> Optional[str]:
        name_node = node.child_by_field_name("name")
        return _text(name_node, src).strip() if name_node else None

    def _collect_decorators(self, node: Node, src: bytes) -> list[str]:
        decorators = []
        for child in node.children:
            if child.type == "decorator":
                decorators.append(_text(child, src).strip())
        return decorators

    def _extract_params(self, node: Node, src: bytes) -> list[str]:
        params: list[str] = []
        params_node = node.child_by_field_name("parameters")
        if params_node is None:
            return params
        for p in params_node.children:
            if p.type in ("identifier",):
                params.append(_text(p, src))
            elif p.type in ("required_parameter", "optional_parameter",
                             "rest_pattern", "assignment_pattern"):
                # TS: required_parameter has identifier + optional type_annotation
                name_node = p.child_by_field_name("pattern") or next(
                    (c for c in p.children
                     if c.type in ("identifier", "object_pattern",
                                   "array_pattern")), None
                )
                type_node = p.child_by_field_name("type")
                name = _text(name_node, src) if name_node else ""
                ptype = _text(type_node, src).lstrip(":").strip() if type_node else ""
                params.append(f"{ptype} {name}".strip() if ptype else name)
            elif p.type == "formal_parameters":
                # nested params (destructured) — just emit raw text
                params.append(_text(p, src))
        return params

    def _extract_return_type(self, node: Node, src: bytes) -> Optional[str]:
        # TypeScript return type annotation sits as "return_type" field
        rt = node.child_by_field_name("return_type")
        if rt:
            return _text(rt, src).lstrip(":").strip()
        return None

    def _collect_calls(self, node: Node, src: bytes, result: ParsedFile,
                       caller_fqn: str):
        """Walk a body emitting CALLS edges for call_expressions."""
        queue = list(node.children)
        while queue:
            n = queue.pop(0)
            if n.type == "call_expression":
                fn = n.child_by_field_name("function")
                if fn:
                    fn_text = _text(fn, src)
                    # Get the final identifier (e.g. this.db.find → find)
                    callee = fn_text.split(".")[-1].strip()
                    if callee and re.match(r"^[a-zA-Z_$][\w$]*$", callee):
                        result.edges.append({
                            "source": caller_fqn,
                            "target": callee,
                            "type": "CALLS",
                            "unresolved": True,
                        })
            queue.extend(n.children)
