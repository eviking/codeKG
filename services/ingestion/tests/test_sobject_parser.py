"""Tests for the Salesforce sObject metadata parser."""
import textwrap
from pathlib import Path

import pytest

from parser.sobject_parser import SObjectParser


ACCOUNT_OBJECT = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <CustomObject xmlns="http://soap.sforce.com/2006/04/metadata">
        <label>Account Score</label>
        <description>Tracks account engagement score.</description>
        <fields>
            <fullName>Score__c</fullName>
            <label>Score</label>
            <type>Number</type>
            <required>true</required>
        </fields>
        <fields>
            <fullName>PrimaryContact__c</fullName>
            <label>Primary Contact</label>
            <type>Lookup</type>
            <referenceTo>Contact</referenceTo>
        </fields>
        <fields>
            <fullName>ParentAccount__c</fullName>
            <label>Parent Account</label>
            <type>MasterDetail</type>
            <referenceTo>Account</referenceTo>
        </fields>
    </CustomObject>
""")

FIELD_ONLY = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
        <fullName>Region__c</fullName>
        <label>Region</label>
        <type>Picklist</type>
        <required>false</required>
    </CustomField>
""")


def _write(tmp_path: Path, rel: str, content: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# Full object file
# ---------------------------------------------------------------------------

def test_object_emits_sobject_class(tmp_path):
    path = _write(tmp_path, "AccountScore__c.object-meta.xml", ACCOUNT_OBJECT)
    result = SObjectParser().parse_file(path, "repo1")
    assert len(result.classes) == 1
    cls = result.classes[0]
    assert cls["kind"] == "sobject"
    assert cls["fqn"] == "sobject/AccountScore__c"
    assert cls["package_fqn"] == "sobject"


def test_object_uses_description_as_javadoc(tmp_path):
    path = _write(tmp_path, "AccountScore__c.object-meta.xml", ACCOUNT_OBJECT)
    result = SObjectParser().parse_file(path, "repo1")
    assert "engagement score" in result.classes[0]["javadoc"]


def test_object_emits_fields(tmp_path):
    path = _write(tmp_path, "AccountScore__c.object-meta.xml", ACCOUNT_OBJECT)
    result = SObjectParser().parse_file(path, "repo1")
    field_names = {f["name"] for f in result.fields}
    assert "Score__c" in field_names
    assert "PrimaryContact__c" in field_names
    assert "ParentAccount__c" in field_names


def test_object_required_field_has_modifier(tmp_path):
    path = _write(tmp_path, "AccountScore__c.object-meta.xml", ACCOUNT_OBJECT)
    result = SObjectParser().parse_file(path, "repo1")
    score = next(f for f in result.fields if f["name"] == "Score__c")
    assert "required" in score["modifiers"]


def test_lookup_field_emits_references_edge(tmp_path):
    path = _write(tmp_path, "AccountScore__c.object-meta.xml", ACCOUNT_OBJECT)
    result = SObjectParser().parse_file(path, "repo1")
    refs = {e["target"] for e in result.edges if e["type"] == "REFERENCES"}
    assert "sobject/Contact" in refs


def test_master_detail_emits_references_edge_with_cascade_modifier(tmp_path):
    path = _write(tmp_path, "AccountScore__c.object-meta.xml", ACCOUNT_OBJECT)
    result = SObjectParser().parse_file(path, "repo1")
    refs = {e["target"] for e in result.edges if e["type"] == "REFERENCES"}
    assert "sobject/Account" in refs
    parent = next(f for f in result.fields if f["name"] == "ParentAccount__c")
    assert "cascade_delete" in parent["modifiers"]


# ---------------------------------------------------------------------------
# Standalone field file
# ---------------------------------------------------------------------------

def test_field_file_emits_parent_sobject_stub(tmp_path):
    path = _write(tmp_path, "objects/Opportunity__c/fields/Region__c.field-meta.xml", FIELD_ONLY)
    result = SObjectParser().parse_file(path, "repo1")
    assert any(c["fqn"] == "sobject/Opportunity__c" for c in result.classes)


def test_field_file_emits_field(tmp_path):
    path = _write(tmp_path, "objects/Opportunity__c/fields/Region__c.field-meta.xml", FIELD_ONLY)
    result = SObjectParser().parse_file(path, "repo1")
    assert any(f["name"] == "Region__c" for f in result.fields)


# ---------------------------------------------------------------------------
# Malformed XML
# ---------------------------------------------------------------------------

def test_malformed_xml_returns_empty_result(tmp_path):
    path = tmp_path / "Broken__c.object-meta.xml"
    path.write_text("<CustomObject><unclosed>")
    result = SObjectParser().parse_file(path, "repo1")
    assert result.classes == []
    assert result.fields == []
