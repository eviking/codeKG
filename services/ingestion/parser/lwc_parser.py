"""
Salesforce Lightning Web Component (LWC) parser.

Handles the three files that make up an LWC bundle:
  - <name>.js   — already parsed by JsParser; this parser handles the other two
  - <name>.html — template: component composition (<c-foo-bar>), event bindings
                  (@api/@wire/@track used in JS but surfaced here), directives
  - <name>.js-meta.xml — targets (lightning__RecordPage, etc.), API version

Strategy: group files by component directory, then emit one synthetic class
per component that aggregates what all three files contribute. The JS class
from JsParser is emitted separately — the LWC class emitted here uses
kind='lwc_component' and records composition (USES edges to child components)
and target exposure (annotations).

Output schema matches ParsedFile from java_parser.py — KGWriter unchanged.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional


LWC_EXTENSIONS = {".html"}

# LWC HTML template directives we care about
_EVENT_RE = re.compile(r'on(\w+)=')
_LWCIF_RE = re.compile(r'lwc:if|lwc:elseif|lwc:else|if:true|if:false')
_FOR_RE   = re.compile(r'for:each|iterator:\w+|lwc:for')

# Component tag pattern: <c-foo-bar> or <c_foo_bar> or namespace prefixes
_COMPONENT_TAG_RE = re.compile(
    r'<([a-z][a-z0-9]*(?:[_-][a-z0-9]+)+)(?:\s|>|/)',
    re.IGNORECASE,
)

# JS-meta XML namespace
_META_NS = "http://soap.sforce.com/2006/04/metadata"


class ParsedFile:
    """All extracted facts from an LWC bundle file (.html or .js-meta.xml)."""

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


class LwcParser:
    """
    Parses LWC template (.html) and metadata (.js-meta.xml) files.
    Emits a synthetic class per component bundle that records child component
    usage (USES edges) and deployment targets (annotations).
    """

    def parse_file(self, path: Path, repo_id: str) -> ParsedFile:
        result = ParsedFile(str(path), repo_id)
        suffix = path.suffix.lower()
        if suffix == ".html":
            self._parse_template(path, repo_id, result)
        elif path.name.lower().endswith(".js-meta.xml"):
            self._parse_meta(path, repo_id, result)
        return result

    # ------------------------------------------------------------------
    # HTML template
    # ------------------------------------------------------------------

    def _parse_template(self, path: Path, repo_id: str, result: ParsedFile):
        try:
            text = path.read_text(errors="replace")
        except OSError:
            return

        component_name = path.stem          # e.g. "myComponent"
        component_dir  = path.parent.name   # e.g. "myComponent"
        fqn = f"lwc/{component_dir}"

        # Child components referenced in the template
        child_tags: set[str] = set()
        for m in _COMPONENT_TAG_RE.finditer(text):
            tag = m.group(1).lower()
            # Skip standard HTML tags (no hyphen means no namespace)
            if "-" in tag or "_" in tag:
                child_tags.add(tag)

        # Annotations: event handlers, directives
        annotations: list[str] = []
        for ev in set(_EVENT_RE.findall(text)):
            annotations.append(f"@on{ev}")
        if _LWCIF_RE.search(text):
            annotations.append("@conditional")
        if _FOR_RE.search(text):
            annotations.append("@iteration")

        result.classes.append({
            "fqn": fqn,
            "name": component_dir,
            "package_fqn": "lwc",
            "repo_id": repo_id,
            "kind": "lwc_component",
            "file_path": str(path),
            "start_line": 1,
            "end_line": text.count("\n") + 1,
            "annotations": annotations,
            "modifiers": [],
            "javadoc": None,
        })

        for tag in child_tags:
            # Normalise: c-foo-bar → lwc/fooBar (camelCase) for FQN lookup,
            # but also store the raw tag so the edge is human-readable.
            child_fqn = _tag_to_fqn(tag)
            result.edges.append({
                "source": fqn,
                "target": child_fqn,
                "type": "USES",
                "unresolved": True,
            })

    # ------------------------------------------------------------------
    # js-meta.xml
    # ------------------------------------------------------------------

    def _parse_meta(self, path: Path, repo_id: str, result: ParsedFile):
        try:
            text = path.read_text(errors="replace")
        except OSError:
            return

        component_dir = path.parent.name
        fqn = f"lwc/{component_dir}"

        # Try namespace-aware parse first, then strip-namespace fallback
        targets: list[str] = []
        api_version: Optional[str] = None

        try:
            root = ET.fromstring(text)
            ns = {"sf": _META_NS}
            targets = [t.text for t in root.findall(".//sf:targets/sf:target", ns)
                       if t.text]
            api_node = root.find("sf:apiVersion", ns)
            if api_node is None:
                api_node = root.find("apiVersion")
            api_version = api_node.text if api_node is not None else None
        except ET.ParseError:
            # Regex fallback for malformed XML
            targets = re.findall(r'<target>([^<]+)</target>', text)
            m = re.search(r'<apiVersion>([^<]+)</apiVersion>', text)
            api_version = m.group(1) if m else None

        annotations = [f"@target({t})" for t in targets]
        if api_version:
            annotations.append(f"@apiVersion({api_version})")

        exposed_targets = [t for t in targets if "Page" in t or "App" in t]
        modifiers = ["exposed"] if exposed_targets else []

        result.classes.append({
            "fqn": fqn,
            "name": component_dir,
            "package_fqn": "lwc",
            "repo_id": repo_id,
            "kind": "lwc_component",
            "file_path": str(path),
            "start_line": 1,
            "end_line": text.count("\n") + 1,
            "annotations": annotations,
            "modifiers": modifiers,
            "javadoc": f"LWC component — targets: {', '.join(targets)}" if targets else None,
        })


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _tag_to_fqn(tag: str) -> str:
    """
    Convert an LWC HTML tag to a graph FQN.
      c-foo-bar   → lwc/fooBar
      lightning-button → lwc/lightningButton  (standard components)
    """
    parts = re.split(r'[-_]', tag)
    if not parts:
        return f"lwc/{tag}"
    # Drop single-char namespace prefix (c, x, etc.)
    if len(parts[0]) == 1:
        parts = parts[1:]
    if not parts:
        return f"lwc/{tag}"
    camel = parts[0] + "".join(p.capitalize() for p in parts[1:])
    return f"lwc/{camel}"
