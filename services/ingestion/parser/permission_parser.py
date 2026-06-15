"""
Salesforce Permission Set / Profile metadata parser.

File types handled:
  *.permissionSet-meta.xml  — named permission set
  *.profile-meta.xml        — user profile (superset of permission set)

Each permission set / profile is emitted as a class with kind='permission_set'
or kind='profile'. Edges emitted:

  GRANTS  source=permission_set/MyPS   target=apex/MyClass    (classAccesses)
  GRANTS  source=permission_set/MyPS   target=sobject/Account (objectPermissions)
  GRANTS  source=permission_set/MyPS   target=flow/MyFlow     (flowAccesses)

Field-level security (fieldPermissions) is stored as annotations on the
permission set class rather than as separate edges — there are too many to
make useful graph edges.

Output schema matches ParsedFile from java_parser.py — KGWriter unchanged.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

PERMISSION_EXTENSIONS = {".permissionSet-meta.xml", ".profile-meta.xml"}

_SF_NS = "http://soap.sforce.com/2006/04/metadata"


class ParsedFile:
    """All extracted facts from a single permission set / profile file."""

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


class PermissionParser:
    """
    Parses Salesforce permission set and profile metadata files.
    Emits GRANTS edges from the permission set to the Apex classes,
    sObjects, and Flows it grants access to.
    """

    def parse_file(self, path: Path, repo_id: str) -> ParsedFile:
        result = ParsedFile(str(path), repo_id)
        name_lower = path.name.lower()
        if name_lower.endswith(".permissionset-meta.xml"):
            kind = "permission_set"
            pkg  = "permission_set"
            obj_name = path.name[: -len(".permissionSet-meta.xml")]
        elif name_lower.endswith(".profile-meta.xml"):
            kind = "profile"
            pkg  = "profile"
            obj_name = path.name[: -len(".profile-meta.xml")]
        else:
            return result

        try:
            root = ET.fromstring(path.read_bytes())
        except ET.ParseError:
            return result

        ns  = {"sf": _SF_NS}
        fqn = f"{pkg}/{obj_name}"

        label_el = _find_one(root, "label", ns)
        desc_el  = _find_one(root, "description", ns)
        label    = label_el.text if label_el is not None else obj_name

        # Collect field-level security as annotations (too granular for edges)
        field_annots: list[str] = []
        for fp in _find_all(root, "fieldPermissions", ns):
            field = _child_text(fp, "field", ns)
            readable = _child_text(fp, "readable", ns) == "true"
            editable = _child_text(fp, "editable", ns) == "true"
            if field and (readable or editable):
                perms = []
                if readable:
                    perms.append("r")
                if editable:
                    perms.append("w")
                field_annots.append(f"@field({field}:{'+'.join(perms)})")

        result.classes.append({
            "fqn": fqn,
            "name": obj_name,
            "package_fqn": pkg,
            "repo_id": repo_id,
            "kind": kind,
            "file_path": str(path),
            "start_line": 1,
            "end_line": 1,
            "annotations": field_annots,
            "modifiers": [],
            "javadoc": (desc_el.text if desc_el is not None else None) or label,
        })

        # ── Apex class access → GRANTS edges ─────────────────────────────
        for el in _find_all(root, "classAccesses", ns):
            apex_class = _child_text(el, "apexClass", ns)
            enabled    = _child_text(el, "enabled", ns) == "true"
            if apex_class and enabled:
                result.edges.append({
                    "source": fqn,
                    "target": apex_class,
                    "type": "GRANTS",
                    "unresolved": True,
                })

        # ── sObject access → GRANTS edges ────────────────────────────────
        for el in _find_all(root, "objectPermissions", ns):
            sobject  = _child_text(el, "object", ns)
            readable = _child_text(el, "allowRead", ns) == "true"
            if sobject and readable:
                result.edges.append({
                    "source": fqn,
                    "target": f"sobject/{sobject}",
                    "type": "GRANTS",
                    "unresolved": True,
                })

        # ── Flow access → GRANTS edges ────────────────────────────────────
        for el in _find_all(root, "flowAccesses", ns):
            flow    = _child_text(el, "flow", ns)
            enabled = _child_text(el, "enabled", ns) == "true"
            if flow and enabled:
                result.edges.append({
                    "source": fqn,
                    "target": f"flow/{flow}",
                    "type": "GRANTS",
                    "unresolved": True,
                })

        # ── Page access (Visualforce/Aura) → GRANTS edges ────────────────
        for el in _find_all(root, "pageAccesses", ns):
            page    = _child_text(el, "apexPage", ns)
            enabled = _child_text(el, "enabled", ns) == "true"
            if page and enabled:
                result.edges.append({
                    "source": fqn,
                    "target": f"page/{page}",
                    "type": "GRANTS",
                    "unresolved": True,
                })

        return result


# ------------------------------------------------------------------
# Helpers (same pattern as flow_parser.py)
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
