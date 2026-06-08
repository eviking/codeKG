"""
Python source file parser using Tree-sitter.

Extracts structural information from .py files:
  - Classes (with base classes, docstrings, decorators)
  - Methods / functions (with type hints, docstrings, decorators)
  - Instance fields (self.x assignments in __init__)
  - Module-level functions (indexed as methods of a synthetic module node)
  - Import dependencies
  - CALLS edges from method bodies

The output schema matches ParsedFile from java_parser.py so the KG writer
works unchanged.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Node

PYTHON_LANGUAGE = Language(tspython.language())


def _text(node: Node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _extract_docstring(body_node: Node, src: bytes) -> Optional[str]:
    """Return the first string literal in a function/class body if it's a docstring."""
    if body_node is None:
        return None
    for child in body_node.children:
        if child.type == "expression_statement":
            for sub in child.children:
                if sub.type == "string":
                    raw = _text(sub, src)
                    # Strip quotes: """, ''', ", '
                    for q in ('"""', "'''", '"', "'"):
                        if raw.startswith(q) and raw.endswith(q) and len(raw) > 2 * len(q):
                            inner = raw[len(q):-len(q)]
                            # Clean up indentation
                            lines = [ln.strip() for ln in inner.splitlines() if ln.strip()]
                            return " ".join(lines)[:500] if lines else None
        elif child.type not in ("comment", "\n", "pass_statement"):
            break  # Past the docstring position
    return None


def _extract_decorators(node: Node, src: bytes) -> list[str]:
    decorators = []
    for child in node.children:
        if child.type == "decorator":
            decorators.append(_text(child, src).strip())
    return decorators


def _collect_base_classes(bases_node: Node, src: bytes) -> list[str]:
    """Parse the argument_list of a class definition for base class names."""
    if bases_node is None:
        return []
    bases = []
    for child in bases_node.children:
        if child.type in ("identifier", "attribute"):
            bases.append(_text(child, src))
    return bases


def _type_hint(node: Node, src: bytes) -> Optional[str]:
    """Extract type annotation text from a typed_parameter or return annotation."""
    if node is None:
        return None
    return _text(node, src)


def _module_to_fqn(file_path: str, repo_path: str) -> str:
    """
    Convert a file path to a Python dotted module name.
    e.g. /repos/django/django/db/models/base.py → django.db.models.base
    """
    try:
        rel = Path(file_path).relative_to(repo_path)
        parts = list(rel.parts)
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
        elif parts[-1].endswith(".py"):
            parts[-1] = parts[-1][:-3]
        return ".".join(parts)
    except ValueError:
        # Fallback: just use the stem
        return Path(file_path).stem


class ParsedFile:
    """Holds all extracted facts from a single .py file."""

    def __init__(self, file_path: str, repo_id: str):
        self.file_path = file_path
        self.repo_id = repo_id
        self.package_fqn: Optional[str] = None   # module dotted path
        self.imports: list[str] = []
        self.classes: list[dict] = []
        self.interfaces: list[dict] = []
        self.enums: list[dict] = []
        self.methods: list[dict] = []
        self.fields: list[dict] = []
        self.edges: list[dict] = []


class PythonParser:
    """
    Parses Python source files using Tree-sitter and extracts structural facts
    ready for writing into Neo4j. Output schema is compatible with JavaParser.
    """

    def __init__(self):
        self._parser = Parser(PYTHON_LANGUAGE)

    def parse_file(self, path: Path, repo_id: str, repo_path: str = "") -> ParsedFile:
        src = path.read_bytes()
        tree = self._parser.parse(src)
        result = ParsedFile(str(path), repo_id)
        module_fqn = _module_to_fqn(str(path), repo_path)
        result.package_fqn = module_fqn
        self._visit_module(tree.root_node, src, result, module_fqn)
        return result

    # ------------------------------------------------------------------
    # Visitors
    # ------------------------------------------------------------------

    def _visit_module(self, root: Node, src: bytes, result: ParsedFile, module_fqn: str):
        """Visit top-level statements."""
        module_functions = []  # collect top-level functions

        for node in root.children:
            if node.type in ("import_statement", "import_from_statement"):
                self._handle_import(node, src, result)
            elif node.type == "class_definition":
                self._handle_class(node, src, result, parent_fqn=None,
                                   module_fqn=module_fqn)
            elif node.type == "decorated_definition":
                inner = node.child_by_field_name("definition")
                if inner and inner.type == "class_definition":
                    self._handle_class(inner, src, result, parent_fqn=None,
                                       module_fqn=module_fqn, decorators_node=node)
                elif inner and inner.type == "function_definition":
                    module_functions.append((inner, node))
            elif node.type == "function_definition":
                module_functions.append((node, None))

        # Emit a synthetic module node for top-level functions if any exist
        if module_functions:
            mod_name = module_fqn.split(".")[-1]
            # Extract the module-level docstring from the first expression in the file
            mod_doc = _extract_docstring(root, src)
            mod_node = {
                "fqn": module_fqn,
                "name": mod_name,
                "package_fqn": ".".join(module_fqn.split(".")[:-1]),
                "repo_id": result.repo_id,
                "kind": "module",
                "file_path": result.file_path,
                "start_line": 1,
                "end_line": 0,
                "annotations": [],
                "modifiers": [],
                "javadoc": mod_doc,
            }
            result.classes.append(mod_node)
            for fn_node, deco_node in module_functions:
                self._handle_function(fn_node, src, result, class_fqn=module_fqn,
                                      decorators_node=deco_node)

    def _handle_import(self, node: Node, src: bytes, result: ParsedFile):
        """Extract imported module names as dependency strings."""
        if node.type == "import_statement":
            # import foo, import foo.bar
            for child in node.children:
                if child.type in ("dotted_name", "identifier"):
                    result.imports.append(_text(child, src))
                elif child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    if name_node:
                        result.imports.append(_text(name_node, src))
        elif node.type == "import_from_statement":
            # from foo.bar import Baz
            mod_node = node.child_by_field_name("module_name")
            if mod_node:
                mod = _text(mod_node, src)
                result.imports.append(mod)
                # Also add qualified names: from django.db import models → django.db.models
                for child in node.children:
                    if child.type == "import_statement" or child.type == "dotted_name":
                        pass
                    elif child.type == "identifier":
                        result.imports.append(f"{mod}.{_text(child, src)}")
                    elif child.type == "aliased_import":
                        name_node = child.child_by_field_name("name")
                        if name_node:
                            result.imports.append(f"{mod}.{_text(name_node, src)}")

    def _handle_class(self, node: Node, src: bytes, result: ParsedFile,
                      parent_fqn: Optional[str], module_fqn: str,
                      decorators_node: Optional[Node] = None):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        fqn = f"{parent_fqn}.{name}" if parent_fqn else f"{module_fqn}.{name}"

        # Base classes → EXTENDS / IMPLEMENTS edges
        args_node = node.child_by_field_name("superclasses")
        bases = _collect_base_classes(args_node, src)

        # Docstring
        body = node.child_by_field_name("body")
        docstring = _extract_docstring(body, src)

        # Decorators
        decorators = []
        if decorators_node:
            decorators = _extract_decorators(decorators_node, src)
        else:
            decorators = _extract_decorators(node, src)

        # Kind: detect ABC / Protocol / Enum subclasses
        kind = "class"
        for base in bases:
            base_simple = base.split(".")[-1]
            if base_simple in ("ABC", "ABCMeta"):
                kind = "abstract"
            elif base_simple in ("IntEnum", "Enum", "Flag", "IntFlag"):
                kind = "enum"
            elif base_simple == "Protocol":
                kind = "interface"

        cls_entry = {
            "fqn": fqn,
            "name": name,
            "package_fqn": module_fqn,
            "repo_id": result.repo_id,
            "kind": kind,
            "file_path": result.file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "annotations": decorators,
            "modifiers": [],
            "javadoc": docstring,
        }
        result.classes.append(cls_entry)

        # Inheritance edges
        for base in bases:
            if base not in ("object",):
                result.edges.append({
                    "source": fqn,
                    "target": base,
                    "type": "EXTENDS",
                    "unresolved": True,
                })

        # Import edges
        for imp in result.imports:
            result.edges.append({
                "source": fqn,
                "target": imp,
                "type": "IMPORTS",
                "unresolved": False,
            })

        # Members
        if body:
            for member in body.children:
                if member.type == "function_definition":
                    self._handle_function(member, src, result, class_fqn=fqn)
                elif member.type == "decorated_definition":
                    inner = member.child_by_field_name("definition")
                    if inner and inner.type == "function_definition":
                        self._handle_function(inner, src, result, class_fqn=fqn,
                                              decorators_node=member)
                elif member.type == "class_definition":
                    self._handle_class(member, src, result,
                                       parent_fqn=fqn, module_fqn=module_fqn)
                elif member.type in ("expression_statement", "assignment"):
                    # Class-level variable annotations
                    self._handle_class_var(member, src, result, class_fqn=fqn)

    def _handle_function(self, node: Node, src: bytes, result: ParsedFile,
                         class_fqn: str,
                         decorators_node: Optional[Node] = None):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        fqn = f"{class_fqn}#{name}"

        # Return type annotation
        return_type = None
        ret_node = node.child_by_field_name("return_type")
        if ret_node:
            return_type = _text(ret_node, src).lstrip("->").strip()

        # Parameters (skip 'self', 'cls')
        params = []
        params_node = node.child_by_field_name("parameters")
        if params_node:
            for p in params_node.children:
                if p.type == "identifier":
                    pname = _text(p, src)
                    if pname not in ("self", "cls"):
                        params.append(pname)
                elif p.type == "typed_parameter":
                    pname_node = p.child_by_field_name("name") or (
                        p.children[0] if p.children else None)
                    ptype_node = p.child_by_field_name("type")
                    if pname_node:
                        pname = _text(pname_node, src)
                        if pname not in ("self", "cls"):
                            ptype = _text(ptype_node, src) if ptype_node else "Any"
                            params.append(f"{ptype} {pname}")
                elif p.type == "default_parameter":
                    pname_node = p.child_by_field_name("name")
                    if pname_node:
                        pname = _text(pname_node, src)
                        if pname not in ("self", "cls"):
                            params.append(pname)
                elif p.type == "typed_default_parameter":
                    pname_node = p.child_by_field_name("name")
                    ptype_node = p.child_by_field_name("type")
                    if pname_node:
                        pname = _text(pname_node, src)
                        if pname not in ("self", "cls"):
                            ptype = _text(ptype_node, src) if ptype_node else "Any"
                            params.append(f"{ptype} {pname}")

        # Decorators
        decorators = []
        if decorators_node:
            decorators = _extract_decorators(decorators_node, src)

        # Modifiers derived from name / decorators
        modifiers = []
        if name.startswith("__") and name.endswith("__"):
            modifiers.append("dunder")
        if any("staticmethod" in d for d in decorators):
            modifiers.append("static")
        if any("classmethod" in d for d in decorators):
            modifiers.append("classmethod")
        if any("abstractmethod" in d for d in decorators):
            modifiers.append("abstract")
        if not name.startswith("_"):
            modifiers.append("public")
        elif name.startswith("__") and not name.endswith("__"):
            modifiers.append("private")
        else:
            modifiers.append("protected")

        # Docstring
        body = node.child_by_field_name("body")
        docstring = _extract_docstring(body, src)

        result.methods.append({
            "fqn": fqn,
            "name": name,
            "class_fqn": class_fqn,
            "repo_id": result.repo_id,
            "return_type": return_type,
            "parameters": params,
            "modifiers": modifiers,
            "annotations": decorators,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "docstring": docstring,
        })

        # Extract self.x = ... fields from __init__
        if name == "__init__" and body:
            self._extract_instance_fields(body, src, result, class_fqn)

        # CALLS edges
        if body:
            self._collect_calls(body, src, result, fqn)

    def _handle_class_var(self, node: Node, src: bytes, result: ParsedFile, class_fqn: str):
        """Extract class-level annotated assignments: x: int = 5"""
        if node.type == "expression_statement":
            for child in node.children:
                if child.type == "assignment":
                    node = child
                    break
                elif child.type == "augmented_assignment":
                    return
        # typed_assignment: name: Type = value
        if node.type == "assignment":
            left = node.child_by_field_name("left")
            right_type = node.child_by_field_name("type")
            if left and left.type == "identifier":
                fname = _text(left, src)
                if not fname.startswith("__"):
                    ftype = _text(right_type, src) if right_type else "Any"
                    result.fields.append({
                        "name": fname,
                        "class_fqn": class_fqn,
                        "type": ftype,
                        "modifiers": [] if not fname.startswith("_") else ["private"],
                    })

    def _extract_instance_fields(self, body: Node, src: bytes, result: ParsedFile,
                                  class_fqn: str):
        """Extract self.x = ... assignments from __init__ body."""
        queue = list(body.children)
        while queue:
            node = queue.pop(0)
            if node.type == "assignment":
                left = node.child_by_field_name("left")
                if left and left.type == "attribute":
                    obj = left.child_by_field_name("object")
                    attr = left.child_by_field_name("attribute")
                    if obj and _text(obj, src) == "self" and attr:
                        fname = _text(attr, src)
                        # Try to infer type from right-hand side annotation
                        type_node = node.child_by_field_name("type")
                        ftype = _text(type_node, src) if type_node else "Any"
                        result.fields.append({
                            "name": fname,
                            "class_fqn": class_fqn,
                            "type": ftype,
                            "modifiers": [] if not fname.startswith("_") else ["private"],
                        })
            elif node.type in ("if_statement", "for_statement", "with_statement", "block"):
                queue.extend(node.children)

    def _collect_calls(self, node: Node, src: bytes, result: ParsedFile, caller_fqn: str):
        """Walk function body and emit CALLS edges for function/method calls."""
        queue = list(node.children)
        while queue:
            n = queue.pop(0)
            if n.type == "call":
                func = n.child_by_field_name("function")
                if func:
                    callee = _text(func, src)
                    # Normalise: self.foo() → foo, obj.foo() → foo
                    if "." in callee:
                        callee = callee.split(".")[-1]
                    if callee and re.match(r"^[a-zA-Z_]\w*$", callee):
                        result.edges.append({
                            "source": caller_fqn,
                            "target": callee,
                            "type": "CALLS",
                            "unresolved": True,
                        })
            queue.extend(n.children)
