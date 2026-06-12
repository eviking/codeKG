"""
Smoke tests for AbapParser (services/ingestion/parser/abap_parser.py).

Covers SAP ABAP class and subroutine parsing. Run inside the ingestion
container (needs tree_sitter_abap.so compiled from source).

Coverage:
  - ABAP_EXTENSIONS set
  - Class DEFINITION: name, fqn, kind
  - Abstract class kind
  - INHERITING FROM → EXTENDS edge
  - INTERFACES declaration → IMPLEMENTS edge
  - Interface definition kind
  - Method extraction from IMPLEMENTATION: name, parameters, return type
  - Constructor → <init>
  - Method modifiers (visibility)
  - Field extraction (DATA, CLASS-DATA)
  - FORM subroutines → synthetic module class
  - CALLS edges from method bodies
  - Comment extraction (docstrings)
  - Robustness: empty source, non-ABAP content
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

_SVC_ROOT = str(Path(__file__).parent.parent)
if _SVC_ROOT not in sys.path:
    sys.path.insert(0, _SVC_ROOT)

try:
    from parser.abap_parser import AbapParser, ABAP_EXTENSIONS, _load_abap_language
    _load_abap_language()
    _ABAP_AVAILABLE = True
except (ImportError, OSError):
    _ABAP_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _ABAP_AVAILABLE,
    reason="tree_sitter_abap.so not compiled — see parser/abap_parser.py for instructions",
)


def _parse(source: str, repo_id: str = "test") -> object:
    with tempfile.NamedTemporaryFile(suffix=".abap", delete=False) as f:
        f.write(source.encode())
        tmp = Path(f.name)
    try:
        return AbapParser().parse_file(tmp, repo_id)
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------

class TestExtensions:
    def test_abap_extension(self):
        assert ".abap" in ABAP_EXTENSIONS

    def test_no_java_extension(self):
        assert ".java" not in ABAP_EXTENSIONS


# ---------------------------------------------------------------------------
# Class extraction
# ---------------------------------------------------------------------------

class TestClassExtraction:
    def test_simple_class(self):
        src = "CLASS zcl_foo DEFINITION PUBLIC FINAL CREATE PUBLIC.\nENDCLASS."
        result = _parse(src)
        assert any(c["name"] == "ZCL_FOO" or c["name"] == "zcl_foo" for c in result.classes)

    def test_class_kind(self):
        src = "CLASS zcl_foo DEFINITION PUBLIC CREATE PUBLIC.\nENDCLASS."
        result = _parse(src)
        cls = result.classes[0]
        assert cls["kind"] == "class"

    def test_abstract_class_kind(self):
        src = "CLASS zcl_base DEFINITION PUBLIC ABSTRACT CREATE PUBLIC.\nENDCLASS."
        result = _parse(src)
        cls = result.classes[0]
        assert cls["kind"] == "abstract_class"

    def test_class_fqn(self):
        src = "CLASS zcl_foo DEFINITION PUBLIC CREATE PUBLIC.\nENDCLASS."
        result = _parse(src)
        assert result.classes[0]["fqn"] == result.classes[0]["name"]

    def test_extends_edge(self):
        src = """\
CLASS zcl_child DEFINITION PUBLIC INHERITING FROM zcl_base CREATE PUBLIC.
ENDCLASS."""
        result = _parse(src)
        extends = [e for e in result.edges if e["type"] == "EXTENDS"]
        assert any(e["target"] == "zcl_base" for e in extends)

    def test_implements_edge(self):
        src = """\
CLASS zcl_svc DEFINITION PUBLIC CREATE PUBLIC.
  PUBLIC SECTION.
    INTERFACES zif_runnable.
ENDCLASS."""
        result = _parse(src)
        impl = [e for e in result.edges if e["type"] == "IMPLEMENTS"]
        assert any(e["target"] == "zif_runnable" for e in impl)


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

class TestInterface:
    def test_interface_kind(self):
        src = """\
INTERFACE zif_runnable PUBLIC.
  METHODS run.
ENDINTERFACE."""
        result = _parse(src)
        assert any(c["kind"] == "interface" for c in result.classes)

    def test_interface_name(self):
        src = "INTERFACE zif_runnable PUBLIC.\nENDINTERFACE."
        result = _parse(src)
        iface = next(c for c in result.classes if c["kind"] == "interface")
        assert "zif_runnable" in iface["name"] or "ZIF_RUNNABLE" in iface["name"]


# ---------------------------------------------------------------------------
# Method extraction
# ---------------------------------------------------------------------------

class TestMethodExtraction:
    def test_method_name(self):
        src = """\
CLASS zcl_svc DEFINITION PUBLIC CREATE PUBLIC.
  PUBLIC SECTION.
    METHODS get_data RETURNING VALUE(rv_result) TYPE string.
ENDCLASS.
CLASS zcl_svc IMPLEMENTATION.
  METHOD get_data.
    rv_result = 'ok'.
  ENDMETHOD.
ENDCLASS."""
        result = _parse(src)
        assert any(m["name"] == "get_data" for m in result.methods)

    def test_method_parameters(self):
        src = """\
CLASS zcl_svc DEFINITION PUBLIC CREATE PUBLIC.
  PUBLIC SECTION.
    METHODS process
      IMPORTING iv_id TYPE string
                iv_mode TYPE i.
ENDCLASS.
CLASS zcl_svc IMPLEMENTATION.
  METHOD process.
  ENDMETHOD.
ENDCLASS."""
        result = _parse(src)
        m = next((x for x in result.methods if x["name"] == "process"), None)
        assert m is not None
        assert len(m["parameters"]) == 2

    def test_method_return_type(self):
        src = """\
CLASS zcl_svc DEFINITION PUBLIC CREATE PUBLIC.
  PUBLIC SECTION.
    METHODS get_count RETURNING VALUE(rv_count) TYPE i.
ENDCLASS.
CLASS zcl_svc IMPLEMENTATION.
  METHOD get_count.
    rv_count = 1.
  ENDMETHOD.
ENDCLASS."""
        result = _parse(src)
        m = next((x for x in result.methods if x["name"] == "get_count"), None)
        assert m is not None
        assert m["return_type"] is not None
        assert "i" in m["return_type"].lower() or "TYPE" not in m["return_type"]

    def test_constructor_becomes_init(self):
        src = """\
CLASS zcl_svc DEFINITION PUBLIC CREATE PUBLIC.
  PUBLIC SECTION.
    METHODS constructor IMPORTING iv_name TYPE string.
ENDCLASS.
CLASS zcl_svc IMPLEMENTATION.
  METHOD constructor.
  ENDMETHOD.
ENDCLASS."""
        result = _parse(src)
        ctors = [m for m in result.methods if m["name"] == "<init>"]
        assert len(ctors) == 1
        assert "constructor" in ctors[0]["modifiers"]

    def test_method_visibility_public(self):
        src = """\
CLASS zcl_svc DEFINITION PUBLIC CREATE PUBLIC.
  PUBLIC SECTION.
    METHODS run.
ENDCLASS.
CLASS zcl_svc IMPLEMENTATION.
  METHOD run.
  ENDMETHOD.
ENDCLASS."""
        result = _parse(src)
        m = next((x for x in result.methods if x["name"] == "run"), None)
        assert m is not None
        assert "public" in m["modifiers"]

    def test_method_visibility_private(self):
        src = """\
CLASS zcl_svc DEFINITION PUBLIC CREATE PUBLIC.
  PRIVATE SECTION.
    METHODS helper.
ENDCLASS.
CLASS zcl_svc IMPLEMENTATION.
  METHOD helper.
  ENDMETHOD.
ENDCLASS."""
        result = _parse(src)
        m = next((x for x in result.methods if x["name"] == "helper"), None)
        assert m is not None
        assert "private" in m["modifiers"]


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------

class TestFields:
    def test_data_field_extracted(self):
        src = """\
CLASS zcl_repo DEFINITION PUBLIC CREATE PUBLIC.
  PRIVATE SECTION.
    DATA mv_count TYPE i.
ENDCLASS.
CLASS zcl_repo IMPLEMENTATION.
ENDCLASS."""
        result = _parse(src)
        assert any(f["name"] == "mv_count" for f in result.fields)

    def test_class_data_static(self):
        src = """\
CLASS zcl_repo DEFINITION PUBLIC CREATE PUBLIC.
  PUBLIC SECTION.
    CLASS-DATA mv_pool TYPE i.
ENDCLASS.
CLASS zcl_repo IMPLEMENTATION.
ENDCLASS."""
        result = _parse(src)
        f = next((x for x in result.fields if x["name"] == "mv_pool"), None)
        assert f is not None
        assert "static" in f["modifiers"]


# ---------------------------------------------------------------------------
# FORM subroutines
# ---------------------------------------------------------------------------

class TestFormSubroutines:
    def test_form_becomes_method(self):
        src = """\
FORM process_input USING p_val TYPE string.
ENDFORM."""
        result = _parse(src)
        assert any(m["name"] == "process_input" for m in result.methods)

    def test_form_creates_module_class(self):
        src = "FORM do_work.\nENDFORM."
        result = _parse(src)
        assert any(c["kind"] == "module" for c in result.classes)

    def test_no_module_class_without_forms(self):
        src = "CLASS zcl_foo DEFINITION PUBLIC CREATE PUBLIC.\nENDCLASS."
        result = _parse(src)
        assert not any(c["kind"] == "module" for c in result.classes)


# ---------------------------------------------------------------------------
# CALLS edges
# ---------------------------------------------------------------------------

class TestCallsEdges:
    def test_method_call_emits_calls_edge(self):
        src = """\
CLASS zcl_svc DEFINITION PUBLIC CREATE PUBLIC.
  PUBLIC SECTION.
    METHODS run.
    METHODS helper.
ENDCLASS.
CLASS zcl_svc IMPLEMENTATION.
  METHOD run.
    me->helper( ).
  ENDMETHOD.
  METHOD helper.
  ENDMETHOD.
ENDCLASS."""
        result = _parse(src)
        calls = [e for e in result.edges if e["type"] == "CALLS"]
        assert any(e["target"] == "helper" for e in calls)


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------

class TestRobustness:
    def test_empty_source(self):
        result = _parse("")
        assert result.classes == []
        assert result.methods == []
        assert result.edges == []

    def test_non_abap_does_not_crash(self):
        result = _parse("this is %%% not abap !!!")
        assert isinstance(result.classes, list)

    def test_class_definition_without_implementation(self):
        src = "CLASS zcl_foo DEFINITION PUBLIC CREATE PUBLIC.\nENDCLASS."
        result = _parse(src)
        assert any(c["kind"] == "class" for c in result.classes)
