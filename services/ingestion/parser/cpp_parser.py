"""
C++ source file parser using Tree-sitter.

Parses both .h/.hpp (headers) and .cpp/.cc files. Extracts:
  - Classes and structs (with base classes, Doxygen comments)
  - Methods (with return types, parameters, const/virtual/override)
  - Member fields
  - Namespaces → package_fqn
  - #include dependencies
  - CALLS edges from method bodies

The output schema matches ParsedFile from java_parser.py so the KG writer
works unchanged.

C++ specifics handled:
  - Template classes: class Foo<T> → name stored as "Foo", template params in modifiers
  - Anonymous structs/unions: skipped
  - Multiple inheritance: all bases emitted as EXTENDS edges
  - Doxygen: /** */ and /// comments extracted as docstring equivalent
  - Namespace nesting: foo::bar::Baz → package_fqn = foo::bar
  - Forward declarations: skipped (no body)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import tree_sitter_cpp as tscpp
from tree_sitter import Language, Parser, Node

CPP_LANGUAGE = Language(tscpp.language())

# File extensions this parser handles
CPP_EXTENSIONS = {".cpp", ".cc", ".cxx", ".c++", ".h", ".hpp", ".hh", ".hxx", ".h++"}


def _text(node: Node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _extract_doxygen(node: Node, src: bytes) -> Optional[str]:
    """
    Find a /** ... */ or /// comment immediately preceding this node
    in the parent's children list.
    """
    parent = node.parent
    if parent is None:
        return None
    siblings = list(parent.children)
    try:
        idx = siblings.index(node)
    except ValueError:
        return None

    lines_collected = []
    for i in range(idx - 1, -1, -1):
        sib = siblings[i]
        if sib.type == "comment":
            text = _text(sib, src).strip()
            if text.startswith("/**"):
                # Block doxygen
                inner = text[3:]
                if inner.endswith("*/"):
                    inner = inner[:-2]
                cleaned = []
                for line in inner.splitlines():
                    line = line.strip().lstrip("*").strip()
                    if line:
                        cleaned.append(line)
                return " ".join(cleaned) if cleaned else None
            elif text.startswith("///") or text.startswith("//!"):
                lines_collected.insert(0, text.lstrip("/!").strip())
                continue
            elif text.startswith("//"):
                break  # plain comment, not doxygen
        elif sib.is_named and sib.type != "comment":
            break

    return " ".join(lines_collected) if lines_collected else None


def _collect_base_classes(node: Node, src: bytes) -> list[tuple[str, str]]:
    """
    Parse base_class_clause → list of (access_specifier, name).
    e.g. class Foo : public Bar, protected Baz
    """
    bases = []
    for child in node.children:
        if child.type == "base_class_clause":
            access = "public"
            for item in child.children:
                if item.type in ("public", "protected", "private"):
                    access = _text(item, src)
                elif item.type in ("type_identifier", "qualified_identifier",
                                   "template_type", "dependent_type"):
                    name = _text(item, src)
                    # Strip template args: Foo<T> → Foo
                    name = re.sub(r"<.*>", "", name).strip()
                    if name:
                        bases.append((access, name))
    return bases


def _namespace_prefix(node: Node, src: bytes) -> str:
    """Walk up parent chain collecting namespace names."""
    parts = []
    cur = node.parent
    while cur:
        if cur.type == "namespace_definition":
            name_node = cur.child_by_field_name("name")
            if name_node:
                parts.insert(0, _text(name_node, src))
        cur = cur.parent
    return "::".join(parts)


class ParsedFile:
    """Holds all extracted facts from a single C++ file."""

    def __init__(self, file_path: str, repo_id: str):
        self.file_path = file_path
        self.repo_id = repo_id
        self.package_fqn: Optional[str] = None   # outermost namespace
        self.imports: list[str] = []              # #include paths
        self.classes: list[dict] = []
        self.interfaces: list[dict] = []
        self.enums: list[dict] = []
        self.methods: list[dict] = []
        self.fields: list[dict] = []
        self.edges: list[dict] = []


class CppParser:
    """
    Parses C++ source files using Tree-sitter and extracts structural facts
    ready for writing into Neo4j. Output schema is compatible with JavaParser.
    """

    def __init__(self):
        self._parser = Parser(CPP_LANGUAGE)

    def parse_file(self, path: Path, repo_id: str) -> ParsedFile:
        src = path.read_bytes()
        tree = self._parser.parse(src)
        result = ParsedFile(str(path), repo_id)
        self._visit_root(tree.root_node, src, result)
        return result

    # ------------------------------------------------------------------
    # Visitors
    # ------------------------------------------------------------------

    def _visit_root(self, root: Node, src: bytes, result: ParsedFile):
        for node in root.children:
            self._visit_node(node, src, result, namespace="")

    def _visit_node(self, node: Node, src: bytes, result: ParsedFile, namespace: str):
        if node.type == "preproc_include":
            self._handle_include(node, src, result)
        elif node.type in ("class_specifier", "struct_specifier"):
            self._handle_class(node, src, result, namespace=namespace)
        elif node.type == "enum_specifier":
            self._handle_enum(node, src, result, namespace=namespace)
        elif node.type == "namespace_definition":
            self._handle_namespace(node, src, result, namespace=namespace)
        elif node.type == "function_definition":
            # Top-level / out-of-class method definitions (e.g. Foo::bar() {})
            self._handle_free_function(node, src, result, namespace=namespace)
        elif node.type == "template_declaration":
            # template<typename T> class Foo { ... }
            # tree-sitter stores the inner declaration as a direct child, not a named field
            inner = node.child_by_field_name("declaration") or node.child_by_field_name("definition")
            if inner is None:
                for child in node.children:
                    if child.type in ("class_specifier", "struct_specifier",
                                      "function_definition"):
                        inner = child
                        break
            if inner and inner.type in ("class_specifier", "struct_specifier"):
                self._handle_class(inner, src, result, namespace=namespace,
                                   is_template=True)
            elif inner and inner.type == "function_definition":
                self._handle_free_function(inner, src, result, namespace=namespace)
        elif node.type == "declaration":
            # May contain class_specifier inline: class Foo {} foo;
            for child in node.children:
                if child.type in ("class_specifier", "struct_specifier"):
                    self._handle_class(child, src, result, namespace=namespace)

    def _handle_include(self, node: Node, src: bytes, result: ParsedFile):
        for child in node.children:
            if child.type in ("string_literal", "system_lib_string"):
                inc = _text(child, src).strip('"<>')
                result.imports.append(inc)

    def _handle_namespace(self, node: Node, src: bytes, result: ParsedFile, namespace: str):
        name_node = node.child_by_field_name("name")
        ns_name = _text(name_node, src) if name_node else ""
        full_ns = f"{namespace}::{ns_name}" if namespace and ns_name else (ns_name or namespace)

        if not result.package_fqn and full_ns:
            result.package_fqn = full_ns.split("::")[0]

        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                self._visit_node(child, src, result, namespace=full_ns)

    def _handle_class(self, node: Node, src: bytes, result: ParsedFile,
                      namespace: str, is_template: bool = False):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return  # anonymous struct/union — skip
        name = _text(name_node, src)
        # Strip template specialisation: Foo<int> → Foo
        name = re.sub(r"<.*>", "", name).strip()
        if not name:
            return

        fqn = f"{namespace}::{name}" if namespace else name

        # Has a body? If not it's a forward declaration — skip
        body = node.child_by_field_name("body")
        if body is None:
            return

        kind = "class" if node.type == "class_specifier" else "struct"
        if is_template:
            kind = f"template_{kind}"

        bases = _collect_base_classes(node, src)
        doxygen = _extract_doxygen(node, src)

        modifiers = ["template"] if is_template else []

        cls_entry = {
            "fqn": fqn,
            "name": name,
            "package_fqn": namespace or "",
            "repo_id": result.repo_id,
            "kind": kind,
            "file_path": result.file_path,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "annotations": [],
            "modifiers": modifiers,
            "javadoc": doxygen,
        }
        result.classes.append(cls_entry)

        # Inheritance edges
        for access, base_name in bases:
            result.edges.append({
                "source": fqn,
                "target": base_name,
                "type": "EXTENDS",
                "unresolved": True,
            })

        # Include edges (all classes in file share the includes)
        for inc in result.imports:
            result.edges.append({
                "source": fqn,
                "target": inc,
                "type": "IMPORTS",
                "unresolved": False,
            })

        # Members
        default_access = "private" if node.type == "class_specifier" else "public"
        current_access = default_access

        for member in body.children:
            if member.type == "access_specifier":
                spec = _text(member, src).rstrip(":").strip()
                current_access = spec
            elif member.type in ("class_specifier", "struct_specifier"):
                self._handle_class(member, src, result, namespace=fqn)
            elif member.type == "enum_specifier":
                self._handle_enum(member, src, result, namespace=fqn)
            elif member.type == "function_definition":
                self._handle_method(member, src, result, class_fqn=fqn,
                                    access=current_access)
            elif member.type in ("declaration", "field_declaration"):
                self._handle_member_declaration(member, src, result,
                                                class_fqn=fqn, access=current_access)
            elif member.type == "template_declaration":
                inner = (member.child_by_field_name("declaration") or
                         member.child_by_field_name("definition"))
                if inner:
                    if inner.type == "function_definition":
                        self._handle_method(inner, src, result, class_fqn=fqn,
                                            access=current_access, is_template=True)
                    elif inner.type in ("class_specifier", "struct_specifier"):
                        self._handle_class(inner, src, result, namespace=fqn,
                                           is_template=True)

    def _handle_method(self, node: Node, src: bytes, result: ParsedFile,
                       class_fqn: str, access: str = "public",
                       is_template: bool = False):
        declarator = node.child_by_field_name("declarator")
        if declarator is None:
            return

        # Navigate into pointer/reference declarators
        while declarator and declarator.type in (
                "pointer_declarator", "reference_declarator",
                "abstract_pointer_declarator"):
            declarator = declarator.child_by_field_name("declarator") or (
                declarator.children[-1] if declarator.children else None)

        if declarator is None:
            return

        # Get function name — may be qualified: Foo::bar
        name = None
        if declarator.type == "function_declarator":
            name_node = declarator.child_by_field_name("declarator")
            if name_node:
                raw = _text(name_node, src)
                name = raw.split("::")[-1]  # unqualified name
                name = re.sub(r"~", "~", name)  # keep destructor ~
        if not name:
            return

        fqn = f"{class_fqn}#{name}"

        # Return type
        type_node = node.child_by_field_name("type")
        return_type = _text(type_node, src) if type_node else None

        # Parameters
        params = []
        if declarator.type == "function_declarator":
            params_node = declarator.child_by_field_name("parameters")
            if params_node:
                for p in params_node.children:
                    if p.type == "parameter_declaration":
                        ptype_node = p.child_by_field_name("type")
                        pdecl_node = p.child_by_field_name("declarator")
                        ptype = _text(ptype_node, src) if ptype_node else ""
                        pname = ""
                        if pdecl_node:
                            raw = _text(pdecl_node, src)
                            # Strip pointer/ref chars
                            pname = re.sub(r"[*&\s]", "", raw.split("=")[0]).strip()
                        params.append(f"{ptype} {pname}".strip() if ptype else pname)

        # Modifiers
        modifiers = [access]
        if is_template:
            modifiers.append("template")
        full_text = _text(node, src)
        if "virtual" in full_text[:200]:
            modifiers.append("virtual")
        if "override" in full_text:
            modifiers.append("override")
        if "static" in full_text[:200]:
            modifiers.append("static")
        if "const" in full_text[:200]:
            modifiers.append("const")
        if name.startswith("~"):
            modifiers.append("destructor")
        elif name == _text(node.child_by_field_name("declarator") or node, src).split("::")[-1].split("(")[0]:
            # same name as class → constructor (rough check)
            pass

        doxygen = _extract_doxygen(node, src)

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
            "docstring": doxygen,
        })

        # CALLS edges
        body = node.child_by_field_name("body")
        if body:
            self._collect_calls(body, src, result, fqn)

    def _handle_member_declaration(self, node: Node, src: bytes, result: ParsedFile,
                                   class_fqn: str, access: str):
        """Extract field declarations and pure virtual method declarations."""
        type_node = node.child_by_field_name("type")
        ftype = _text(type_node, src) if type_node else "auto"
        ftype = re.sub(r"\s+", " ", ftype).strip()
        node_text = _text(node, src)

        for child in node.children:
            fname = None
            if child.type == "field_identifier":
                # field_declaration: primitive_type field_identifier ;
                fname = _text(child, src).strip()
            elif child.type in ("init_declarator", "declarator",
                                "pointer_declarator", "reference_declarator",
                                "function_declarator"):
                raw = _text(child, src).split("=")[0].split("(")[0]
                fname = re.sub(r"[*&\s]", "", raw).strip()
            if fname and re.match(r"^[a-zA-Z_]\w*$", fname):
                modifiers = [access]
                if "static" in node_text[:100]:
                    modifiers.append("static")
                result.fields.append({
                    "name": fname,
                    "class_fqn": class_fqn,
                    "type": ftype,
                    "modifiers": modifiers,
                })

    def _handle_enum(self, node: Node, src: bytes, result: ParsedFile, namespace: str):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        fqn = f"{namespace}::{name}" if namespace else name
        body = node.child_by_field_name("body")
        if body is None:
            return

        doxygen = _extract_doxygen(node, src)
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
            "javadoc": doxygen,
        })

    def _handle_free_function(self, node: Node, src: bytes, result: ParsedFile,
                              namespace: str):
        """Top-level function definitions outside any class."""
        declarator = node.child_by_field_name("declarator")
        if not declarator:
            return
        # May be Foo::methodName() — already handled via _handle_method for the class
        # Only index truly free functions (no :: in name)
        while declarator and declarator.type in ("pointer_declarator",
                                                  "reference_declarator"):
            declarator = declarator.children[-1] if declarator.children else None
        if not declarator or declarator.type != "function_declarator":
            return
        name_node = declarator.child_by_field_name("declarator")
        if not name_node:
            return
        raw_name = _text(name_node, src)
        if "::" in raw_name:
            return  # out-of-class method def — class already indexed from header
        name = raw_name.split("(")[0].strip()
        if not name or not re.match(r"^[a-zA-Z_]\w*$", name):
            return

        # Emit as a synthetic module-level class per file if needed
        module_fqn = f"{namespace}::{Path(result.file_path).stem}" if namespace else Path(result.file_path).stem
        # Ensure module node exists
        if not any(c["fqn"] == module_fqn for c in result.classes):
            result.classes.append({
                "fqn": module_fqn,
                "name": Path(result.file_path).stem,
                "package_fqn": namespace or "",
                "repo_id": result.repo_id,
                "kind": "module",
                "file_path": result.file_path,
                "start_line": 1,
                "end_line": 0,
                "annotations": [],
                "modifiers": [],
                "javadoc": None,
            })

        fqn = f"{module_fqn}#{name}"
        type_node = node.child_by_field_name("type")
        return_type = _text(type_node, src) if type_node else None
        doxygen = _extract_doxygen(node, src)

        # Extract parameters (same logic as _handle_method)
        params = []
        if declarator.type == "function_declarator":
            params_node = declarator.child_by_field_name("parameters")
            if params_node:
                for p in params_node.children:
                    if p.type == "parameter_declaration":
                        ptype_node = p.child_by_field_name("type")
                        pdecl_node = p.child_by_field_name("declarator")
                        ptype = _text(ptype_node, src) if ptype_node else ""
                        pname = ""
                        if pdecl_node:
                            raw = _text(pdecl_node, src)
                            pname = re.sub(r"[*&\s]", "", raw.split("=")[0]).strip()
                        params.append(f"{ptype} {pname}".strip() if ptype else pname)

        result.methods.append({
            "fqn": fqn,
            "name": name,
            "class_fqn": module_fqn,
            "repo_id": result.repo_id,
            "return_type": return_type,
            "parameters": params,
            "modifiers": ["public"],
            "annotations": [],
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "docstring": doxygen,
        })

        body = node.child_by_field_name("body")
        if body:
            self._collect_calls(body, src, result, fqn)

    def _collect_calls(self, node: Node, src: bytes, result: ParsedFile, caller_fqn: str):
        """Walk a function body emitting CALLS edges for call_expressions."""
        queue = list(node.children)
        while queue:
            n = queue.pop(0)
            if n.type == "call_expression":
                func = n.child_by_field_name("function")
                if func:
                    callee_text = _text(func, src)
                    # Unqualified name: foo(), ns::foo() → foo
                    callee = callee_text.split("::")[-1].split("(")[0].strip()
                    if callee and re.match(r"^[a-zA-Z_]\w*$", callee):
                        result.edges.append({
                            "source": caller_fqn,
                            "target": callee,
                            "type": "CALLS",
                            "unresolved": True,
                        })
            queue.extend(n.children)
