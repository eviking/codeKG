"""Tests for the LWC HTML template and js-meta.xml parser."""
import textwrap
from pathlib import Path

from parser.lwc_parser import LwcParser, _tag_to_fqn


# ---------------------------------------------------------------------------
# _tag_to_fqn helper
# ---------------------------------------------------------------------------

def test_tag_to_fqn_c_prefix():
    assert _tag_to_fqn("c-foo-bar") == "lwc/fooBar"


def test_tag_to_fqn_no_prefix():
    assert _tag_to_fqn("my-widget") == "lwc/myWidget"


def test_tag_to_fqn_lightning():
    assert _tag_to_fqn("lightning-button") == "lwc/lightningButton"


# ---------------------------------------------------------------------------
# HTML template parsing
# ---------------------------------------------------------------------------

TEMPLATE_SIMPLE = textwrap.dedent("""\
    <template>
        <c-account-card record-id={recordId} onselect={handleSelect}></c-account-card>
        <lightning-button label="Save" onclick={save}></lightning-button>
    </template>
""")

TEMPLATE_CONDITIONAL = textwrap.dedent("""\
    <template>
        <template lwc:if={isLoaded}>
            <p>Loaded</p>
        </template>
    </template>
""")

TEMPLATE_ITERATION = textwrap.dedent("""\
    <template>
        <template for:each={items} for:item="item">
            <p key={item.id}>{item.name}</p>
        </template>
    </template>
""")


def _write(tmp_path: Path, component: str, filename: str, content: str) -> Path:
    comp_dir = tmp_path / component
    comp_dir.mkdir(parents=True, exist_ok=True)
    p = comp_dir / filename
    p.write_text(content)
    return p


def test_html_emits_lwc_component_class(tmp_path):
    path = _write(tmp_path, "accountCard", "accountCard.html", TEMPLATE_SIMPLE)
    result = LwcParser().parse_file(path, "repo1")
    assert len(result.classes) == 1
    cls = result.classes[0]
    assert cls["kind"] == "lwc_component"
    assert cls["fqn"] == "lwc/accountCard"
    assert cls["package_fqn"] == "lwc"


def test_html_emits_uses_edges_for_child_components(tmp_path):
    path = _write(tmp_path, "accountCard", "accountCard.html", TEMPLATE_SIMPLE)
    result = LwcParser().parse_file(path, "repo1")
    targets = {e["target"] for e in result.edges if e["type"] == "USES"}
    assert "lwc/accountCard" in targets       # c-account-card
    assert "lwc/lightningButton" in targets   # lightning-button


def test_html_detects_event_annotations(tmp_path):
    path = _write(tmp_path, "accountCard", "accountCard.html", TEMPLATE_SIMPLE)
    result = LwcParser().parse_file(path, "repo1")
    annotations = result.classes[0]["annotations"]
    assert "@onselect" in annotations or "@onclick" in annotations


def test_html_detects_conditional_annotation(tmp_path):
    path = _write(tmp_path, "myComp", "myComp.html", TEMPLATE_CONDITIONAL)
    result = LwcParser().parse_file(path, "repo1")
    assert "@conditional" in result.classes[0]["annotations"]


def test_html_detects_iteration_annotation(tmp_path):
    path = _write(tmp_path, "myComp", "myComp.html", TEMPLATE_ITERATION)
    result = LwcParser().parse_file(path, "repo1")
    assert "@iteration" in result.classes[0]["annotations"]


def test_html_no_children_produces_no_edges(tmp_path):
    path = _write(tmp_path, "simple", "simple.html", "<template><p>Hi</p></template>")
    result = LwcParser().parse_file(path, "repo1")
    assert result.edges == []


# ---------------------------------------------------------------------------
# js-meta.xml parsing
# ---------------------------------------------------------------------------

META_RECORD_PAGE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <LightningComponentBundle xmlns="http://soap.sforce.com/2006/04/metadata">
        <apiVersion>57.0</apiVersion>
        <isExposed>true</isExposed>
        <targets>
            <target>lightning__RecordPage</target>
            <target>lightning__AppPage</target>
        </targets>
    </LightningComponentBundle>
""")

META_UTILITY = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <LightningComponentBundle xmlns="http://soap.sforce.com/2006/04/metadata">
        <apiVersion>57.0</apiVersion>
        <isExposed>false</isExposed>
    </LightningComponentBundle>
""")


def test_meta_emits_lwc_component_class(tmp_path):
    path = _write(tmp_path, "accountCard", "accountCard.js-meta.xml", META_RECORD_PAGE)
    result = LwcParser().parse_file(path, "repo1")
    assert len(result.classes) == 1
    cls = result.classes[0]
    assert cls["kind"] == "lwc_component"
    assert cls["fqn"] == "lwc/accountCard"


def test_meta_emits_target_annotations(tmp_path):
    path = _write(tmp_path, "accountCard", "accountCard.js-meta.xml", META_RECORD_PAGE)
    result = LwcParser().parse_file(path, "repo1")
    annotations = result.classes[0]["annotations"]
    assert "@target(lightning__RecordPage)" in annotations
    assert "@target(lightning__AppPage)" in annotations


def test_meta_emits_api_version_annotation(tmp_path):
    path = _write(tmp_path, "accountCard", "accountCard.js-meta.xml", META_RECORD_PAGE)
    result = LwcParser().parse_file(path, "repo1")
    annotations = result.classes[0]["annotations"]
    assert "@apiVersion(57.0)" in annotations


def test_meta_exposed_modifier_for_page_targets(tmp_path):
    path = _write(tmp_path, "accountCard", "accountCard.js-meta.xml", META_RECORD_PAGE)
    result = LwcParser().parse_file(path, "repo1")
    assert "exposed" in result.classes[0]["modifiers"]


def test_meta_no_exposed_modifier_when_not_exposed(tmp_path):
    path = _write(tmp_path, "myUtil", "myUtil.js-meta.xml", META_UTILITY)
    result = LwcParser().parse_file(path, "repo1")
    assert "exposed" not in result.classes[0]["modifiers"]
