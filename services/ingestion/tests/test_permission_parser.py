"""Tests for the Salesforce Permission Set / Profile parser."""
import textwrap
from pathlib import Path

from parser.permission_parser import PermissionParser


PERMISSION_SET = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <PermissionSet xmlns="http://soap.sforce.com/2006/04/metadata">
        <label>Sales Rep Permissions</label>
        <description>Permissions for the sales rep role.</description>
        <classAccesses>
            <apexClass>AccountScoreCalculator</apexClass>
            <enabled>true</enabled>
        </classAccesses>
        <classAccesses>
            <apexClass>LeadConverter</apexClass>
            <enabled>false</enabled>
        </classAccesses>
        <objectPermissions>
            <object>Account</object>
            <allowRead>true</allowRead>
            <allowCreate>true</allowCreate>
        </objectPermissions>
        <objectPermissions>
            <object>Lead</object>
            <allowRead>false</allowRead>
        </objectPermissions>
        <flowAccesses>
            <flow>UpdateAccountScore</flow>
            <enabled>true</enabled>
        </flowAccesses>
        <fieldPermissions>
            <field>Account.Score__c</field>
            <readable>true</readable>
            <editable>true</editable>
        </fieldPermissions>
    </PermissionSet>
""")

PROFILE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <Profile xmlns="http://soap.sforce.com/2006/04/metadata">
        <classAccesses>
            <apexClass>CaseEscalationService</apexClass>
            <enabled>true</enabled>
        </classAccesses>
        <pageAccesses>
            <apexPage>AccountSummaryPage</apexPage>
            <enabled>true</enabled>
        </pageAccesses>
    </Profile>
""")


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# Permission set basics
# ---------------------------------------------------------------------------

def test_permission_set_emits_class(tmp_path):
    path = _write(tmp_path, "SalesRep.permissionSet-meta.xml", PERMISSION_SET)
    result = PermissionParser().parse_file(path, "repo1")
    assert len(result.classes) == 1
    cls = result.classes[0]
    assert cls["kind"] == "permission_set"
    assert cls["fqn"] == "permission_set/SalesRep"
    assert cls["package_fqn"] == "permission_set"


def test_permission_set_description_as_javadoc(tmp_path):
    path = _write(tmp_path, "SalesRep.permissionSet-meta.xml", PERMISSION_SET)
    result = PermissionParser().parse_file(path, "repo1")
    assert "sales rep" in result.classes[0]["javadoc"].lower()


# ---------------------------------------------------------------------------
# GRANTS edges — Apex
# ---------------------------------------------------------------------------

def test_enabled_apex_class_emits_grants_edge(tmp_path):
    path = _write(tmp_path, "SalesRep.permissionSet-meta.xml", PERMISSION_SET)
    result = PermissionParser().parse_file(path, "repo1")
    grants = {e["target"] for e in result.edges if e["type"] == "GRANTS"}
    assert "AccountScoreCalculator" in grants


def test_disabled_apex_class_does_not_emit_edge(tmp_path):
    path = _write(tmp_path, "SalesRep.permissionSet-meta.xml", PERMISSION_SET)
    result = PermissionParser().parse_file(path, "repo1")
    grants = {e["target"] for e in result.edges if e["type"] == "GRANTS"}
    assert "LeadConverter" not in grants


# ---------------------------------------------------------------------------
# GRANTS edges — sObject
# ---------------------------------------------------------------------------

def test_readable_sobject_emits_grants_edge(tmp_path):
    path = _write(tmp_path, "SalesRep.permissionSet-meta.xml", PERMISSION_SET)
    result = PermissionParser().parse_file(path, "repo1")
    grants = {e["target"] for e in result.edges if e["type"] == "GRANTS"}
    assert "sobject/Account" in grants


def test_non_readable_sobject_does_not_emit_edge(tmp_path):
    path = _write(tmp_path, "SalesRep.permissionSet-meta.xml", PERMISSION_SET)
    result = PermissionParser().parse_file(path, "repo1")
    grants = {e["target"] for e in result.edges if e["type"] == "GRANTS"}
    assert "sobject/Lead" not in grants


# ---------------------------------------------------------------------------
# GRANTS edges — Flow
# ---------------------------------------------------------------------------

def test_enabled_flow_emits_grants_edge(tmp_path):
    path = _write(tmp_path, "SalesRep.permissionSet-meta.xml", PERMISSION_SET)
    result = PermissionParser().parse_file(path, "repo1")
    grants = {e["target"] for e in result.edges if e["type"] == "GRANTS"}
    assert "flow/UpdateAccountScore" in grants


# ---------------------------------------------------------------------------
# Field-level security as annotations
# ---------------------------------------------------------------------------

def test_field_permissions_stored_as_annotations(tmp_path):
    path = _write(tmp_path, "SalesRep.permissionSet-meta.xml", PERMISSION_SET)
    result = PermissionParser().parse_file(path, "repo1")
    annotations = result.classes[0]["annotations"]
    assert any("Account.Score__c" in a for a in annotations)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def test_profile_emits_profile_class(tmp_path):
    path = _write(tmp_path, "Admin.profile-meta.xml", PROFILE)
    result = PermissionParser().parse_file(path, "repo1")
    assert result.classes[0]["kind"] == "profile"
    assert result.classes[0]["fqn"] == "profile/Admin"


def test_profile_apex_class_emits_grants_edge(tmp_path):
    path = _write(tmp_path, "Admin.profile-meta.xml", PROFILE)
    result = PermissionParser().parse_file(path, "repo1")
    grants = {e["target"] for e in result.edges if e["type"] == "GRANTS"}
    assert "CaseEscalationService" in grants


def test_profile_page_emits_grants_edge(tmp_path):
    path = _write(tmp_path, "Admin.profile-meta.xml", PROFILE)
    result = PermissionParser().parse_file(path, "repo1")
    grants = {e["target"] for e in result.edges if e["type"] == "GRANTS"}
    assert "page/AccountSummaryPage" in grants


# ---------------------------------------------------------------------------
# Malformed XML
# ---------------------------------------------------------------------------

def test_malformed_xml_returns_empty_result(tmp_path):
    path = tmp_path / "Broken.permissionSet-meta.xml"
    path.write_text("<PermissionSet><unclosed>")
    result = PermissionParser().parse_file(path, "repo1")
    assert result.classes == []
    assert result.edges == []
