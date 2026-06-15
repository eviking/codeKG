"""
Salesforce sObject schema parser (*.object-meta.xml, *.field-meta.xml).

Two file types handled:

  *.object-meta.xml  — full custom object definition: fields, relationships,
                       record types, list views. One ParsedFile per file.
  *.field-meta.xml   — individual field definition (used when fields are
                       stored in separate files under /fields/).

Each sObject is emitted as a class with kind='sobject'. Its fields are emitted
as class fields. Cross-object relationships (lookup/master-detail) produce
REFERENCES edges to the target sObject.

Output schema matches ParsedFile from java_parser.py — KGWriter unchanged.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

SOBJECT_EXTENSIONS = {".object-meta.xml", ".field-meta.xml"}

_SF_NS = "http://soap.sforce.com/2006/04/metadata"

# Field types that create cross-object edges
_RELATIONSHIP_FIELD_TYPES = {"Lookup", "MasterDetail", "MetadataRelationship", "Hierarchy"}


class ParsedFile:
    """All extracted facts from a single sObject metadata file."""

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


class SObjectParser:
    """
    Parses Salesforce sObject metadata files.
    Emits one 'sobject' class per object, its fields, and REFERENCES edges
    for lookup/master-detail relationships.
    """

    def parse_file(self, path: Path, repo_id: str) -> ParsedFile:
        result = ParsedFile(str(path), repo_id)
        name_lower = path.name.lower()
        if name_lower.endswith(".object-meta.xml"):
            self._parse_object(path, repo_id, result)
        elif name_lower.endswith(".field-meta.xml"):
            self._parse_field_file(path, repo_id, result)
        return result

    # ------------------------------------------------------------------
    # Full object file
    # ------------------------------------------------------------------

    def _parse_object(self, path: Path, repo_id: str, result: ParsedFile):
        try:
            root = ET.fromstring(path.read_bytes())
        except ET.ParseError:
            return

        ns = {"sf": _SF_NS}
        object_name = path.name[: -len(".object-meta.xml")]
        fqn = f"sobject/{object_name}"

        label_el = _find_one(root, "label", ns)
        desc_el  = _find_one(root, "description", ns)
        label    = label_el.text if label_el is not None else object_name

        result.classes.append({
            "fqn": fqn,
            "name": object_name,
            "package_fqn": "sobject",
            "repo_id": repo_id,
            "kind": "sobject",
            "file_path": str(path),
            "start_line": 1,
            "end_line": 1,
            "annotations": [],
            "modifiers": [],
            "javadoc": (desc_el.text if desc_el is not None else None) or label,
        })

        for field_el in _find_all(root, "fields", ns):
            self._emit_field(field_el, fqn, object_name, repo_id, result, ns)

    # ------------------------------------------------------------------
    # Standalone field file (fields/<FieldName>.field-meta.xml)
    # ------------------------------------------------------------------

    def _parse_field_file(self, path: Path, repo_id: str, result: ParsedFile):
        try:
            root = ET.fromstring(path.read_bytes())
        except ET.ParseError:
            return

        ns = {"sf": _SF_NS}
        # Parent object is two levels up: objects/<ObjectName__c>/fields/<Field.field-meta.xml>
        object_name = path.parent.parent.name
        fqn = f"sobject/{object_name}"

        # Ensure the parent sobject class exists (minimal stub — real data comes
        # from the .object-meta.xml file if present in the same repo)
        result.classes.append({
            "fqn": fqn,
            "name": object_name,
            "package_fqn": "sobject",
            "repo_id": repo_id,
            "kind": "sobject",
            "file_path": str(path),
            "start_line": 1,
            "end_line": 1,
            "annotations": [],
            "modifiers": [],
            "javadoc": None,
        })

        self._emit_field(root, fqn, object_name, repo_id, result, ns)

    # ------------------------------------------------------------------
    # Field element → field dict + optional REFERENCES edge
    # ------------------------------------------------------------------

    def _emit_field(self, field_el: ET.Element, object_fqn: str,
                    object_name: str, repo_id: str,
                    result: ParsedFile, ns: dict):
        fname = _child_text(field_el, "fullName", ns) or _child_text(field_el, "name", ns)
        if not fname:
            return

        ftype    = _child_text(field_el, "type", ns) or "Text"
        label    = _child_text(field_el, "label", ns) or fname
        required = _child_text(field_el, "required", ns) == "true"
        unique   = _child_text(field_el, "unique", ns) == "true"

        modifiers: list[str] = []
        if required:
            modifiers.append("required")
        if unique:
            modifiers.append("unique")
        if ftype in ("MasterDetail",):
            modifiers.append("cascade_delete")

        result.fields.append({
            "name": fname,
            "class_fqn": object_fqn,
            "type": ftype,
            "modifiers": modifiers,
            "repo_id": repo_id,
        })

        # Relationship fields → REFERENCES edge
        if ftype in _RELATIONSHIP_FIELD_TYPES:
            ref_to_el = _find_one(field_el, "referenceTo", ns)
            ref_to    = ref_to_el.text.strip() if ref_to_el is not None and ref_to_el.text else None
            if ref_to:
                result.edges.append({
                    "source": object_fqn,
                    "target": f"sobject/{ref_to}",
                    "type": "REFERENCES",
                    "unresolved": True,
                })


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _find_all(parent: ET.Element, tag: str, ns: dict) -> list[ET.Element]:
    results = parent.findall(f"sf:{tag}", ns)
    if not results:
        results = parent.findall(tag)
    return results


def _find_one(parent: ET.Element, path: str, ns: dict) -> Optional[ET.Element]:
    ns_path = "/".join(f"sf:{p}" for p in path.split("/"))
    el = parent.find(ns_path, ns)
    if el is None:
        el = parent.find(path)
    return el


def _child_text(parent: ET.Element, tag: str, ns: dict) -> Optional[str]:
    el = _find_one(parent, tag, ns)
    return el.text.strip() if el is not None and el.text else None
