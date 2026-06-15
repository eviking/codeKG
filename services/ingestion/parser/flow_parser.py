"""
Salesforce Flow metadata parser (.flow-meta.xml).

Flows are declarative XML automation files. Each Flow is emitted as a
synthetic class with kind='flow'. The parser extracts:

  - Flow type (AutolaunchedFlow, ScreenFlow, RecordTriggeredFlow, etc.)
  - Apex action calls → CALLS edges to the @InvocableMethod class
  - Subflow references → CALLS edges to other flows
  - Record operations (Create/Update/Delete/Lookup) → QUERIES edges to sObjects
  - Screen elements (component references) → USES edges to LWC components
  - Trigger object + events (for RecordTriggeredFlow) stored as annotations

No tree-sitter required — Flows are well-formed XML with a published schema.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional


FLOW_EXTENSIONS = {".flow-meta.xml"}

_FLOW_NS = "http://soap.sforce.com/2006/04/metadata"

# Flow element types that mean "call an Apex class"
_APEX_CALL_TYPES = {
    "actionCalls",           # Apex action / @InvocableMethod
    "apexPluginCalls",       # legacy Apex plugin
}

# Record operation element names → QUERIES edge type label
_RECORD_OPS = {
    "recordCreates":  "QUERIES",
    "recordUpdates":  "QUERIES",
    "recordDeletes":  "QUERIES",
    "recordLookups":  "QUERIES",
}


class ParsedFile:
    """All extracted facts from a single .flow-meta.xml file."""

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


class FlowParser:
    """
    Parses Salesforce Flow metadata files.
    Emits a synthetic class per flow and relationship edges to Apex,
    other flows, sObjects, and LWC screen components.
    """

    def parse_file(self, path: Path, repo_id: str) -> ParsedFile:
        result = ParsedFile(str(path), repo_id)
        try:
            text = path.read_bytes()
            root = ET.fromstring(text)
        except ET.ParseError:
            return result

        ns = {"sf": _FLOW_NS}

        # Derive flow name from filename: MyFlow.flow-meta.xml → MyFlow
        flow_name = path.name
        for suffix in (".flow-meta.xml", ".flow"):
            if flow_name.endswith(suffix):
                flow_name = flow_name[: -len(suffix)]
                break

        fqn = f"flow/{flow_name}"

        # Flow type
        flow_type_el = _find_one(root, "processType", ns)
        flow_type = flow_type_el.text if flow_type_el is not None else "Flow"

        # Trigger object + events (RecordTriggeredFlow)
        annotations: list[str] = [f"@flowType({flow_type})"]
        _tobj1 = _find_one(root, "triggerOrder/objectApiName", ns)
        _tobj2 = _find_one(root, "start/object", ns)
        trigger_obj_el = _tobj1 if _tobj1 is not None else _tobj2
        trigger_event_el = _find_one(root, "start/triggerType", ns)
        if trigger_obj_el is not None and trigger_obj_el.text:
            annotations.append(f"@triggerObject({trigger_obj_el.text})")
        if trigger_event_el is not None and trigger_event_el.text:
            annotations.append(f"@triggerEvent({trigger_event_el.text})")

        # Label / description
        label_el    = _find_one(root, "label", ns)
        desc_el     = _find_one(root, "description", ns)
        label       = label_el.text  if label_el  is not None else flow_name
        description = desc_el.text   if desc_el   is not None else None

        result.classes.append({
            "fqn": fqn,
            "name": flow_name,
            "package_fqn": "flow",
            "repo_id": repo_id,
            "kind": "flow",
            "file_path": str(path),
            "start_line": 1,
            "end_line": 1,
            "annotations": annotations,
            "modifiers": [],
            "javadoc": description or label,
        })

        # ── Apex action calls → CALLS edges ──────────────────────────────
        for tag in _APEX_CALL_TYPES:
            for el in _find_all(root, tag, ns):
                apex_class = _child_text(el, "actionName", ns)
                if apex_class:
                    result.edges.append({
                        "source": fqn,
                        "target": apex_class,
                        "type": "CALLS",
                        "unresolved": True,
                    })

        # ── Subflow references → CALLS edges ─────────────────────────────
        for el in _find_all(root, "subflows", ns):
            ref = _child_text(el, "flowName", ns)
            if ref:
                result.edges.append({
                    "source": fqn,
                    "target": f"flow/{ref}",
                    "type": "CALLS",
                    "unresolved": True,
                })

        # ── Record operations → QUERIES edges ────────────────────────────
        for tag in _RECORD_OPS:
            for el in _find_all(root, tag, ns):
                # recordLookups uses "object"; recordCreates/Updates/Deletes use "object" too
                sobject = _child_text(el, "object", ns)
                if sobject:
                    result.edges.append({
                        "source": fqn,
                        "target": sobject,
                        "type": "QUERIES",
                        "unresolved": True,
                    })

        # ── Screen components → USES edges ───────────────────────────────
        for screen_el in _find_all(root, "screens", ns):
            for field_el in _find_all(screen_el, "fields", ns):
                component = _child_text(field_el, "componentName", ns)
                if component:
                    lwc_fqn = _component_name_to_fqn(component)
                    result.edges.append({
                        "source": fqn,
                        "target": lwc_fqn,
                        "type": "USES",
                        "unresolved": True,
                    })

        return result


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _find_all(parent: ET.Element, tag: str, ns: dict) -> list[ET.Element]:
    """Find all children with tag, trying namespaced then bare form."""
    results = parent.findall(f"sf:{tag}", ns)
    if not results:
        results = parent.findall(tag)
    return results


def _find_one(parent: ET.Element, path: str, ns: dict) -> Optional[ET.Element]:
    """Find a single element by path, trying namespaced then bare form."""
    ns_path = "/".join(f"sf:{p}" for p in path.split("/"))
    el = parent.find(ns_path, ns)
    if el is None:
        el = parent.find(path)
    return el


def _child_text(parent: ET.Element, tag: str, ns: dict) -> Optional[str]:
    """Get text content of a direct child element."""
    el = _find_one(parent, tag, ns)
    return el.text.strip() if el is not None and el.text else None


def _component_name_to_fqn(name: str) -> str:
    """
    Convert a Salesforce screen component name to a graph FQN.
      c__MyComponent  → lwc/myComponent
      c__my_component → lwc/myComponent
    """
    # Strip namespace prefix (c__, myNs__, etc.)
    clean = re.sub(r'^[a-zA-Z0-9]+__', '', name)
    if not clean:
        clean = name
    # Convert PascalCase or snake_case to camelCase
    if "_" in clean:
        parts = clean.split("_")
        clean = parts[0].lower() + "".join(p.capitalize() for p in parts[1:] if p)
    else:
        clean = clean[0].lower() + clean[1:]
    return f"lwc/{clean}"
