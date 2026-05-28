"""
§7 API Surface extractor.

Detects REST endpoints from Spring MVC, JAX-RS, and Spring WebFlux annotations.
Extracts: HTTP method, path, handler class+method, request/response types.
No LLM — pure annotation pattern matching on the Tree-sitter AST.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import tree_sitter_java as tsjava
from tree_sitter import Language, Parser, Node

JAVA_LANGUAGE = Language(tsjava.language())

# Spring MVC / WebFlux mapping annotations → HTTP method
SPRING_MAPPING = {
    "RequestMapping": None,     # method specified in annotation attribute
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
}

# JAX-RS HTTP method annotations
JAXRS_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}


@dataclass
class ApiEndpoint:
    http_method: str                    # GET, POST, etc.
    path: str                           # full path (class prefix + method)
    handler_class: str                  # FQN of the controller class
    handler_method: str                 # method name
    path_variables: list[str] = field(default_factory=list)   # {id}, {name}
    request_body_type: Optional[str] = None
    response_type: Optional[str] = None
    annotations: list[str] = field(default_factory=list)
    file_path: Optional[str] = None
    line: Optional[int] = None


def _text(node: Node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _annotation_value(annotation_node: Node, src: bytes, attr: str = "value") -> Optional[str]:
    """Extract a named attribute or the default value from an annotation node."""
    text = _text(annotation_node, src)
    # Try named attribute: @Foo(path = "/bar") or @Foo(value = "/bar")
    m = re.search(rf'{attr}\s*=\s*"([^"]*)"', text)
    if m:
        return m.group(1)
    # Try default value: @Foo("/bar")
    m = re.search(r'@\w+\s*\(\s*"([^"]*)"', text)
    if m:
        return m.group(1)
    return None


def _extract_path_variables(path: str) -> list[str]:
    return re.findall(r"\{(\w+)(?::[^}]*)?\}", path)


class ApiExtractor:

    def __init__(self):
        self._parser = Parser(JAVA_LANGUAGE)

    def extract_file(self, path: Path, repo_id: str) -> list[ApiEndpoint]:
        try:
            src = path.read_bytes()
        except Exception:
            return []
        tree = self._parser.parse(src)
        endpoints: list[ApiEndpoint] = []
        self._visit_root(tree.root_node, src, str(path), endpoints)
        return endpoints

    def _visit_root(self, root: Node, src: bytes, file_path: str, endpoints: list[ApiEndpoint]):
        package_fqn = ""
        for node in root.children:
            if node.type == "package_declaration":
                for child in node.children:
                    if child.type in ("scoped_identifier", "identifier"):
                        package_fqn = _text(child, src)
            elif node.type == "class_declaration":
                self._visit_class(node, src, package_fqn, file_path, endpoints)

    def _visit_class(
        self,
        class_node: Node,
        src: bytes,
        package_fqn: str,
        file_path: str,
        endpoints: list[ApiEndpoint],
    ):
        name_node = class_node.child_by_field_name("name")
        if not name_node:
            return
        class_name = _text(name_node, src)
        class_fqn = f"{package_fqn}.{class_name}" if package_fqn else class_name

        # Detect class-level path prefix (Spring @RequestMapping or JAX-RS @Path)
        class_path_prefix = self._extract_class_path(class_node, src)

        body = class_node.child_by_field_name("body")
        if not body:
            return

        for member in body.children:
            if member.type == "method_declaration":
                eps = self._visit_method(member, src, class_fqn, class_path_prefix, file_path)
                endpoints.extend(eps)

    def _extract_class_path(self, class_node: Node, src: bytes) -> str:
        for child in class_node.children:
            if child.type == "modifiers":
                for mod in child.children:
                    if mod.type in ("annotation", "marker_annotation"):
                        ann_text = _text(mod, src)
                        if "RequestMapping" in ann_text:
                            v = _annotation_value(mod, src, "value") or _annotation_value(mod, src, "path") or ""
                            return v.rstrip("/")
                        if "@Path" in ann_text:
                            v = _annotation_value(mod, src) or ""
                            return "/" + v.strip("/")
        return ""

    def _visit_method(
        self,
        method_node: Node,
        src: bytes,
        class_fqn: str,
        class_path_prefix: str,
        file_path: str,
    ) -> list[ApiEndpoint]:
        name_node = method_node.child_by_field_name("name")
        if not name_node:
            return []
        method_name = _text(name_node, src)

        return_type_node = method_node.child_by_field_name("type")
        return_type = _text(return_type_node, src) if return_type_node else None

        # Scan method annotations for HTTP mapping
        http_method: Optional[str] = None
        method_path: str = ""
        request_body_type: Optional[str] = None
        found_mapping = False

        params_node = method_node.child_by_field_name("parameters")
        request_body_type = self._extract_request_body_type(params_node, src) if params_node else None

        for child in method_node.children:
            if child.type != "modifiers":
                continue
            for mod in child.children:
                if mod.type not in ("annotation", "marker_annotation"):
                    continue
                ann_text = _text(mod, src)

                # Spring MVC
                for ann_name, hm in SPRING_MAPPING.items():
                    if ann_name in ann_text:
                        found_mapping = True
                        http_method = hm
                        if http_method is None:
                            # @RequestMapping — extract method attribute
                            m = re.search(r'method\s*=\s*RequestMethod\.(\w+)', ann_text)
                            http_method = m.group(1) if m else "GET"
                        method_path = (
                            _annotation_value(mod, src, "value")
                            or _annotation_value(mod, src, "path")
                            or ""
                        )
                        break

                # JAX-RS @Path
                if "@Path" in ann_text and not found_mapping:
                    method_path = _annotation_value(mod, src) or ""

                # JAX-RS HTTP method annotation
                for jaxrs_m in JAXRS_METHODS:
                    if f"@{jaxrs_m}" in ann_text:
                        found_mapping = True
                        http_method = jaxrs_m
                        break

        if not found_mapping or not http_method:
            return []

        # Build full path
        sep = "/" if not class_path_prefix.endswith("/") and not method_path.startswith("/") else ""
        if not method_path.startswith("/") and method_path:
            sep = "/"
        full_path = (class_path_prefix + sep + method_path).replace("//", "/") or "/"

        return [ApiEndpoint(
            http_method=http_method,
            path=full_path,
            handler_class=class_fqn,
            handler_method=method_name,
            path_variables=_extract_path_variables(full_path),
            request_body_type=request_body_type,
            response_type=return_type,
            file_path=file_path,
            line=method_node.start_point[0] + 1,
        )]

    def _extract_request_body_type(self, params_node: Node, src: bytes) -> Optional[str]:
        for param in params_node.children:
            if param.type != "formal_parameter":
                continue
            param_text = _text(param, src)
            if "@RequestBody" in param_text or "@Body" in param_text:
                type_node = param.child_by_field_name("type")
                if type_node:
                    return _text(type_node, src)
        return None
