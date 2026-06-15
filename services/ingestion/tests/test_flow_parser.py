"""Tests for the Salesforce Flow metadata parser."""
import textwrap
from pathlib import Path

import pytest

from parser.flow_parser import FlowParser, _component_name_to_fqn


# ---------------------------------------------------------------------------
# _component_name_to_fqn helper
# ---------------------------------------------------------------------------

def test_component_fqn_c_namespace():
    assert _component_name_to_fqn("c__MyComponent") == "lwc/myComponent"


def test_component_fqn_custom_namespace():
    assert _component_name_to_fqn("myns__MyWidget") == "lwc/myWidget"


def test_component_fqn_pascal_no_namespace():
    assert _component_name_to_fqn("MyComponent") == "lwc/myComponent"


# ---------------------------------------------------------------------------
# Flow XML fixtures
# ---------------------------------------------------------------------------

AUTOLAUNCH_FLOW = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <Flow xmlns="http://soap.sforce.com/2006/04/metadata">
        <apiVersion>57.0</apiVersion>
        <processType>AutolaunchedFlow</processType>
        <label>Update Account Score</label>
        <description>Calls Apex to recalculate account score after opportunity close.</description>
        <actionCalls>
            <name>CallScoreCalculator</name>
            <actionName>AccountScoreCalculator</actionName>
            <actionType>apex</actionType>
        </actionCalls>
        <recordUpdates>
            <name>UpdateAccount</name>
            <object>Account</object>
        </recordUpdates>
    </Flow>
""")

RECORD_TRIGGERED_FLOW = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <Flow xmlns="http://soap.sforce.com/2006/04/metadata">
        <processType>RecordTriggeredFlow</processType>
        <label>Case Escalation</label>
        <start>
            <object>Case</object>
            <triggerType>RecordAfterSave</triggerType>
        </start>
        <actionCalls>
            <name>EscalateCase</name>
            <actionName>CaseEscalationService</actionName>
            <actionType>apex</actionType>
        </actionCalls>
        <subflows>
            <name>NotifyTeam</name>
            <flowName>SendTeamNotification</flowName>
        </subflows>
    </Flow>
""")

SCREEN_FLOW = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <Flow xmlns="http://soap.sforce.com/2006/04/metadata">
        <processType>Flow</processType>
        <label>Onboarding Wizard</label>
        <screens>
            <name>Step1</name>
            <fields>
                <name>CustomerForm</name>
                <componentName>c__CustomerForm</componentName>
                <fieldType>ComponentInstance</fieldType>
            </fields>
        </screens>
        <recordLookups>
            <name>GetContact</name>
            <object>Contact</object>
        </recordLookups>
    </Flow>
""")

SUBFLOW_ONLY = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <Flow xmlns="http://soap.sforce.com/2006/04/metadata">
        <processType>AutolaunchedFlow</processType>
        <label>Parent Flow</label>
        <subflows>
            <name>Child1</name>
            <flowName>ChildFlowA</flowName>
        </subflows>
        <subflows>
            <name>Child2</name>
            <flowName>ChildFlowB</flowName>
        </subflows>
    </Flow>
""")


def _write_flow(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / f"{name}.flow-meta.xml"
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# Basic class emission
# ---------------------------------------------------------------------------

def test_flow_emits_flow_class(tmp_path):
    path = _write_flow(tmp_path, "UpdateAccountScore", AUTOLAUNCH_FLOW)
    result = FlowParser().parse_file(path, "repo1")
    assert len(result.classes) == 1
    cls = result.classes[0]
    assert cls["kind"] == "flow"
    assert cls["fqn"] == "flow/UpdateAccountScore"
    assert cls["package_fqn"] == "flow"


def test_flow_emits_process_type_annotation(tmp_path):
    path = _write_flow(tmp_path, "UpdateAccountScore", AUTOLAUNCH_FLOW)
    result = FlowParser().parse_file(path, "repo1")
    assert "@flowType(AutolaunchedFlow)" in result.classes[0]["annotations"]


def test_flow_uses_description_as_javadoc(tmp_path):
    path = _write_flow(tmp_path, "UpdateAccountScore", AUTOLAUNCH_FLOW)
    result = FlowParser().parse_file(path, "repo1")
    assert "recalculate account score" in result.classes[0]["javadoc"]


# ---------------------------------------------------------------------------
# Apex action CALLS edges
# ---------------------------------------------------------------------------

def test_apex_action_emits_calls_edge(tmp_path):
    path = _write_flow(tmp_path, "UpdateAccountScore", AUTOLAUNCH_FLOW)
    result = FlowParser().parse_file(path, "repo1")
    calls = [e for e in result.edges if e["type"] == "CALLS"]
    targets = {e["target"] for e in calls}
    assert "AccountScoreCalculator" in targets


def test_record_triggered_flow_apex_call(tmp_path):
    path = _write_flow(tmp_path, "CaseEscalation", RECORD_TRIGGERED_FLOW)
    result = FlowParser().parse_file(path, "repo1")
    calls = {e["target"] for e in result.edges if e["type"] == "CALLS"}
    assert "CaseEscalationService" in calls


# ---------------------------------------------------------------------------
# Subflow CALLS edges
# ---------------------------------------------------------------------------

def test_subflow_emits_calls_edge(tmp_path):
    path = _write_flow(tmp_path, "CaseEscalation", RECORD_TRIGGERED_FLOW)
    result = FlowParser().parse_file(path, "repo1")
    calls = {e["target"] for e in result.edges if e["type"] == "CALLS"}
    assert "flow/SendTeamNotification" in calls


def test_multiple_subflows(tmp_path):
    path = _write_flow(tmp_path, "ParentFlow", SUBFLOW_ONLY)
    result = FlowParser().parse_file(path, "repo1")
    calls = {e["target"] for e in result.edges if e["type"] == "CALLS"}
    assert "flow/ChildFlowA" in calls
    assert "flow/ChildFlowB" in calls


# ---------------------------------------------------------------------------
# Record operation QUERIES edges
# ---------------------------------------------------------------------------

def test_record_update_emits_queries_edge(tmp_path):
    path = _write_flow(tmp_path, "UpdateAccountScore", AUTOLAUNCH_FLOW)
    result = FlowParser().parse_file(path, "repo1")
    queries = {e["target"] for e in result.edges if e["type"] == "QUERIES"}
    assert "Account" in queries


def test_record_lookup_emits_queries_edge(tmp_path):
    path = _write_flow(tmp_path, "OnboardingWizard", SCREEN_FLOW)
    result = FlowParser().parse_file(path, "repo1")
    queries = {e["target"] for e in result.edges if e["type"] == "QUERIES"}
    assert "Contact" in queries


# ---------------------------------------------------------------------------
# Screen component USES edges
# ---------------------------------------------------------------------------

def test_screen_component_emits_uses_edge(tmp_path):
    path = _write_flow(tmp_path, "OnboardingWizard", SCREEN_FLOW)
    result = FlowParser().parse_file(path, "repo1")
    uses = {e["target"] for e in result.edges if e["type"] == "USES"}
    assert "lwc/customerForm" in uses


# ---------------------------------------------------------------------------
# Record-triggered flow trigger annotations
# ---------------------------------------------------------------------------

def test_record_triggered_flow_trigger_annotations(tmp_path):
    path = _write_flow(tmp_path, "CaseEscalation", RECORD_TRIGGERED_FLOW)
    result = FlowParser().parse_file(path, "repo1")
    annotations = result.classes[0]["annotations"]
    assert "@triggerObject(Case)" in annotations
    assert "@triggerEvent(RecordAfterSave)" in annotations


# ---------------------------------------------------------------------------
# Malformed XML does not crash
# ---------------------------------------------------------------------------

def test_malformed_xml_returns_empty_result(tmp_path):
    path = tmp_path / "Broken.flow-meta.xml"
    path.write_text("<Flow><unclosed>")
    result = FlowParser().parse_file(path, "repo1")
    assert result.classes == []
    assert result.edges == []
