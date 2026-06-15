"""Tests for the Salesforce Aura component parser."""
import textwrap
from pathlib import Path

from parser.aura_parser import AuraParser, _aura_tag_to_fqn


# ---------------------------------------------------------------------------
# _aura_tag_to_fqn helper
# ---------------------------------------------------------------------------

def test_fqn_c_namespace():
    assert _aura_tag_to_fqn("c", "accountCard") == "aura/accountCard"


def test_fqn_lightning_maps_to_lwc():
    assert _aura_tag_to_fqn("lightning", "button") == "lwc/lightningButton"


def test_fqn_custom_namespace():
    assert _aura_tag_to_fqn("myns", "widget") == "aura/myns/widget"


# ---------------------------------------------------------------------------
# .cmp fixtures
# ---------------------------------------------------------------------------

CMP_WITH_CHILDREN = textwrap.dedent("""\
    <aura:component controller="AccountController" implements="force:appHostable">
        <aura:handler name="init" value="{!this}" action="{!c.doInit}"/>
        <c:accountCard recordId="{!v.recordId}"/>
        <lightning:button label="Save" onclick="{!c.save}"/>
        <aura:if isTrue="{!v.showDetails}">
            <c:detailView/>
        </aura:if>
    </aura:component>
""")

CMP_MINIMAL = textwrap.dedent("""\
    <aura:component>
        <p>Hello World</p>
    </aura:component>
""")

APP_MARKUP = textwrap.dedent("""\
    <aura:application extends="force:slds">
        <c:mainDashboard/>
    </aura:application>
""")

DESIGN_FILE = textwrap.dedent("""\
    <design:component label="Account Card">
        <design:attribute name="recordId" label="Record ID" />
        <design:attribute name="showDetails" label="Show Details" />
    </design:component>
""")


def _write(tmp_path: Path, component: str, filename: str, content: str) -> Path:
    comp_dir = tmp_path / component
    comp_dir.mkdir(parents=True, exist_ok=True)
    p = comp_dir / filename
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# .cmp parsing
# ---------------------------------------------------------------------------

def test_cmp_emits_aura_component_class(tmp_path):
    path = _write(tmp_path, "accountCard", "accountCard.cmp", CMP_WITH_CHILDREN)
    result = AuraParser().parse_file(path, "repo1")
    assert len(result.classes) == 1
    cls = result.classes[0]
    assert cls["kind"] == "aura_component"
    assert cls["fqn"] == "aura/accountCard"
    assert cls["package_fqn"] == "aura"


def test_cmp_emits_uses_edges_for_child_components(tmp_path):
    path = _write(tmp_path, "accountCard", "accountCard.cmp", CMP_WITH_CHILDREN)
    result = AuraParser().parse_file(path, "repo1")
    uses = {e["target"] for e in result.edges if e["type"] == "USES"}
    assert "aura/accountCard" in uses
    assert "aura/detailView" in uses
    assert "lwc/lightningButton" in uses


def test_cmp_apex_controller_emits_calls_edge(tmp_path):
    path = _write(tmp_path, "accountCard", "accountCard.cmp", CMP_WITH_CHILDREN)
    result = AuraParser().parse_file(path, "repo1")
    calls = {e["target"] for e in result.edges if e["type"] == "CALLS"}
    assert "AccountController" in calls


def test_cmp_apex_controller_stored_as_annotation(tmp_path):
    path = _write(tmp_path, "accountCard", "accountCard.cmp", CMP_WITH_CHILDREN)
    result = AuraParser().parse_file(path, "repo1")
    annotations = result.classes[0]["annotations"]
    assert "@apexController(AccountController)" in annotations


def test_cmp_event_handler_stored_as_annotation(tmp_path):
    path = _write(tmp_path, "accountCard", "accountCard.cmp", CMP_WITH_CHILDREN)
    result = AuraParser().parse_file(path, "repo1")
    annotations = result.classes[0]["annotations"]
    assert "@handles(init)" in annotations


def test_cmp_no_children_produces_no_uses_edges(tmp_path):
    path = _write(tmp_path, "simple", "simple.cmp", CMP_MINIMAL)
    result = AuraParser().parse_file(path, "repo1")
    uses = [e for e in result.edges if e["type"] == "USES"]
    assert uses == []


def test_aura_framework_tags_excluded_from_uses(tmp_path):
    path = _write(tmp_path, "accountCard", "accountCard.cmp", CMP_WITH_CHILDREN)
    result = AuraParser().parse_file(path, "repo1")
    uses = {e["target"] for e in result.edges if e["type"] == "USES"}
    # aura:component, aura:handler, aura:if should NOT be USES edges
    assert not any("aura/" in t and t.startswith("aura/aura") for t in uses)


# ---------------------------------------------------------------------------
# .app parsing
# ---------------------------------------------------------------------------

def test_app_emits_aura_app_class(tmp_path):
    path = _write(tmp_path, "mainApp", "mainApp.app", APP_MARKUP)
    result = AuraParser().parse_file(path, "repo1")
    assert result.classes[0]["kind"] == "aura_app"
    assert result.classes[0]["fqn"] == "aura/mainApp"


def test_app_emits_uses_edges(tmp_path):
    path = _write(tmp_path, "mainApp", "mainApp.app", APP_MARKUP)
    result = AuraParser().parse_file(path, "repo1")
    uses = {e["target"] for e in result.edges if e["type"] == "USES"}
    assert "aura/mainDashboard" in uses


# ---------------------------------------------------------------------------
# .design parsing
# ---------------------------------------------------------------------------

def test_design_emits_aura_component_class(tmp_path):
    path = _write(tmp_path, "accountCard", "accountCard.design", DESIGN_FILE)
    result = AuraParser().parse_file(path, "repo1")
    assert result.classes[0]["kind"] == "aura_component"
    assert result.classes[0]["fqn"] == "aura/accountCard"


def test_design_attributes_stored_as_annotations(tmp_path):
    path = _write(tmp_path, "accountCard", "accountCard.design", DESIGN_FILE)
    result = AuraParser().parse_file(path, "repo1")
    annotations = result.classes[0]["annotations"]
    assert "@designAttr(recordId)" in annotations
    assert "@designAttr(showDetails)" in annotations


def test_design_exposed_modifier_when_attributes_exist(tmp_path):
    path = _write(tmp_path, "accountCard", "accountCard.design", DESIGN_FILE)
    result = AuraParser().parse_file(path, "repo1")
    assert "exposed" in result.classes[0]["modifiers"]


def test_design_label_as_javadoc(tmp_path):
    path = _write(tmp_path, "accountCard", "accountCard.design", DESIGN_FILE)
    result = AuraParser().parse_file(path, "repo1")
    assert result.classes[0]["javadoc"] == "Account Card"
