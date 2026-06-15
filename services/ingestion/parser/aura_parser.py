"""
Salesforce Aura (Lightning Components) parser.

Handles the files that make up an Aura bundle under aura/<ComponentName>/:

  <Name>.cmp          — XML component markup (template equivalent)
  <Name>.app          — XML application markup
  <Name>Controller.js — client-side controller (already handled by JsParser)
  <Name>.design       — design attributes (used by App Builder)
  <Name>.auradoc      — documentation markup (skipped)

This parser handles .cmp, .app, and .design files only. The JS files
in the same directory are picked up by JsParser automatically.

Each Aura component/app is emitted as kind='aura_component' or kind='aura_app'.
Child component references (<c:myComp>, <lightning:button>) produce USES edges.
Design attributes are stored as annotations.

Output schema matches ParsedFile from java_parser.py — KGWriter unchanged.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

AURA_EXTENSIONS = {".cmp", ".app", ".design"}

# Aura component tag: <c:myComp> <lightning:button> <namespace:name>
_AURA_TAG_RE = re.compile(
    r'<([a-zA-Z][a-zA-Z0-9]*:[a-zA-Z][a-zA-Z0-9]*)(?:\s|>|/)',
)

# Standard HTML / Aura framework prefixes to ignore for composition edges
_SKIP_PREFIXES = {
    "aura", "ui", "force", "forceChatter", "forceContent",
    "forceCommunity", "forceRecord",
}


class ParsedFile:
    """All extracted facts from a single Aura bundle file."""

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


class AuraParser:
    """
    Parses Salesforce Aura component (.cmp, .app) and design (.design) files.
    """

    def parse_file(self, path: Path, repo_id: str) -> ParsedFile:
        result = ParsedFile(str(path), repo_id)
        ext = path.suffix.lower()
        if ext in (".cmp", ".app"):
            self._parse_markup(path, repo_id, result, ext)
        elif ext == ".design":
            self._parse_design(path, repo_id, result)
        return result

    # ------------------------------------------------------------------
    # .cmp / .app markup
    # ------------------------------------------------------------------

    def _parse_markup(self, path: Path, repo_id: str, result: ParsedFile, ext: str):
        try:
            text = path.read_text(errors="replace")
        except OSError:
            return

        component_dir  = path.parent.name
        kind           = "aura_app" if ext == ".app" else "aura_component"
        fqn            = f"aura/{component_dir}"

        # Child component references
        child_tags: set[str] = set()
        for m in _AURA_TAG_RE.finditer(text):
            tag = m.group(1)                 # e.g. "c:accountCard" or "lightning:button"
            ns_part, _ = tag.split(":", 1)
            if ns_part.lower() not in _SKIP_PREFIXES:
                child_tags.add(tag)

        # Event handlers: aura:handler name="init" or action="{!c.doInit}"
        event_annots: list[str] = []
        for ev in re.findall(r'aura:handler[^>]+name="([^"]+)"', text):
            event_annots.append(f"@handles({ev})")

        # Apex controller: controller="MyApexClass"
        apex_ctrl = re.search(r'controller="([A-Za-z][A-Za-z0-9_]*)"', text)
        if apex_ctrl:
            event_annots.append(f"@apexController({apex_ctrl.group(1)})")

        result.classes.append({
            "fqn": fqn,
            "name": component_dir,
            "package_fqn": "aura",
            "repo_id": repo_id,
            "kind": kind,
            "file_path": str(path),
            "start_line": 1,
            "end_line": text.count("\n") + 1,
            "annotations": event_annots,
            "modifiers": [],
            "javadoc": None,
        })

        for tag in child_tags:
            ns_part, comp_name = tag.split(":", 1)
            child_fqn = _aura_tag_to_fqn(ns_part, comp_name)
            result.edges.append({
                "source": fqn,
                "target": child_fqn,
                "type": "USES",
                "unresolved": True,
            })

        # Apex controller → CALLS edge (Aura controllers are wired in markup)
        if apex_ctrl:
            result.edges.append({
                "source": fqn,
                "target": apex_ctrl.group(1),
                "type": "CALLS",
                "unresolved": True,
            })

    # ------------------------------------------------------------------
    # .design file — exposes design attributes for App Builder
    # ------------------------------------------------------------------

    def _parse_design(self, path: Path, repo_id: str, result: ParsedFile):
        try:
            text = path.read_text(errors="replace")
        except OSError:
            return

        component_dir = path.parent.name
        fqn           = f"aura/{component_dir}"

        # Extract design:attribute names as annotations
        annotations: list[str] = []
        for attr in re.findall(r'design:attribute[^>]+name="([^"]+)"', text):
            annotations.append(f"@designAttr({attr})")

        # Label from design:component label="..."
        label_m = re.search(r'design:component[^>]+label="([^"]+)"', text)
        label   = label_m.group(1) if label_m else None

        result.classes.append({
            "fqn": fqn,
            "name": component_dir,
            "package_fqn": "aura",
            "repo_id": repo_id,
            "kind": "aura_component",
            "file_path": str(path),
            "start_line": 1,
            "end_line": text.count("\n") + 1,
            "annotations": annotations,
            "modifiers": ["exposed"] if annotations else [],
            "javadoc": label,
        })


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _aura_tag_to_fqn(namespace: str, component: str) -> str:
    """
    Convert an Aura tag to a graph FQN.
      c:accountCard      → aura/accountCard   (same org custom component)
      lightning:button   → lwc/lightningButton (Lightning base components
                           map to LWC in Spring '19+ orgs)
    """
    if namespace == "lightning":
        # Lightning base components ship as LWC in modern orgs
        camel = component[0].upper() + component[1:]
        return f"lwc/lightning{camel}"
    if namespace in ("c", "x"):
        return f"aura/{component}"
    return f"aura/{namespace}/{component}"
