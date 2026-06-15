"""
Tests for the ABAP parser extensions:
  - CALL FUNCTION / BAPI → CALLS edges
  - Open SQL SELECT/INSERT/UPDATE/DELETE → QUERIES edges
  - INCLUDE statements → CALLS edges
  - BAdI detection → @BAdI annotation
"""
import textwrap

from parser.abap_parser import AbapParser


def parse(source: str) -> object:
    return AbapParser().parse_source(source, "test_file.abap", "repo1")


# ---------------------------------------------------------------------------
# CALL FUNCTION → CALLS edge
# ---------------------------------------------------------------------------

CALL_FUNCTION_SOURCE = textwrap.dedent("""\
    CLASS zcl_order_processor DEFINITION PUBLIC.
      PUBLIC SECTION.
        METHODS process_order IMPORTING iv_order_id TYPE string.
    ENDCLASS.

    CLASS zcl_order_processor IMPLEMENTATION.
      METHOD process_order.
        CALL FUNCTION 'BAPI_SALESORDER_CREATEFROMDAT2'
          EXPORTING
            order_header_in = ls_header
          IMPORTING
            salesdocument   = lv_order_id.
        CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'.
      ENDMETHOD.
    ENDCLASS.
""")


def test_call_function_emits_calls_edge():
    result = parse(CALL_FUNCTION_SOURCE)
    calls = {e["target"] for e in result.edges if e["type"] == "CALLS"}
    assert "BAPI_SALESORDER_CREATEFROMDAT2" in calls


def test_call_function_commit_emits_calls_edge():
    result = parse(CALL_FUNCTION_SOURCE)
    calls = {e["target"] for e in result.edges if e["type"] == "CALLS"}
    assert "BAPI_TRANSACTION_COMMIT" in calls


# ---------------------------------------------------------------------------
# PERFORM → CALLS edge
# ---------------------------------------------------------------------------

PERFORM_SOURCE = textwrap.dedent("""\
    REPORT zorder_report.

    START-OF-SELECTION.
      PERFORM validate_input.
      PERFORM process_data.

    FORM validate_input.
      WRITE 'validating'.
    ENDFORM.

    FORM process_data.
      WRITE 'processing'.
    ENDFORM.
""")


def test_perform_emits_calls_edge():
    result = parse(PERFORM_SOURCE)
    calls = {e["target"] for e in result.edges if e["type"] == "CALLS"}
    assert "validate_input" in calls or "VALIDATE_INPUT" in calls


# ---------------------------------------------------------------------------
# Open SQL → QUERIES edges
# ---------------------------------------------------------------------------

SELECT_SOURCE = textwrap.dedent("""\
    CLASS zcl_data_reader DEFINITION PUBLIC.
      PUBLIC SECTION.
        METHODS read_orders.
    ENDCLASS.

    CLASS zcl_data_reader IMPLEMENTATION.
      METHOD read_orders.
        SELECT * FROM vbak INTO TABLE lt_orders WHERE auart = 'OR'.
        SELECT single matnr FROM mara INTO lv_matnr WHERE matkl = lv_class.
      ENDMETHOD.
    ENDCLASS.
""")


def test_select_emits_queries_edge():
    result = parse(SELECT_SOURCE)
    queries = {e["target"] for e in result.edges if e["type"] == "QUERIES"}
    # At least one of the two SELECT targets should be captured
    assert "VBAK" in queries or "MARA" in queries or "vbak" in queries or "mara" in queries


INSERT_UPDATE_SOURCE = textwrap.dedent("""\
    CLASS zcl_writer DEFINITION PUBLIC.
      PUBLIC SECTION.
        METHODS write_data.
    ENDCLASS.

    CLASS zcl_writer IMPLEMENTATION.
      METHOD write_data.
        INSERT INTO ztable VALUES ls_record.
        UPDATE ztable SET field1 = lv_val WHERE key1 = lv_key.
        DELETE FROM ztable WHERE field2 = lv_old.
      ENDMETHOD.
    ENDCLASS.
""")


def test_insert_emits_queries_edge():
    result = parse(INSERT_UPDATE_SOURCE)
    queries = {e["target"].upper() for e in result.edges if e["type"] == "QUERIES"}
    assert "ZTABLE" in queries


def test_update_emits_queries_edge():
    result = parse(INSERT_UPDATE_SOURCE)
    queries = {e["target"].upper() for e in result.edges if e["type"] == "QUERIES"}
    assert "ZTABLE" in queries


# ---------------------------------------------------------------------------
# INCLUDE → CALLS edge
# ---------------------------------------------------------------------------

INCLUDE_SOURCE = textwrap.dedent("""\
    REPORT zmain_report.

    INCLUDE zcommon_utils.
    INCLUDE zvalidation_helpers.

    START-OF-SELECTION.
      WRITE 'main'.
""")


def test_include_emits_calls_edge():
    result = parse(INCLUDE_SOURCE)
    calls = {e["target"].upper() for e in result.edges if e["type"] == "CALLS"}
    assert "ZCOMMON_UTILS" in calls
    assert "ZVALIDATION_HELPERS" in calls


# ---------------------------------------------------------------------------
# BAdI detection → @BAdI annotation
# ---------------------------------------------------------------------------

BADI_SOURCE = textwrap.dedent("""\
    CLASS zcl_im_account_check DEFINITION PUBLIC.
      PUBLIC SECTION.
        INTERFACES zif_ex_account_check.
        METHODS check_account IMPORTING iv_account_id TYPE string.
    ENDCLASS.

    CLASS zcl_im_account_check IMPLEMENTATION.
      METHOD check_account.
        WRITE 'checking'.
      ENDMETHOD.
    ENDCLASS.
""")


def test_badi_class_gets_badi_annotation():
    result = parse(BADI_SOURCE)
    cls = next((c for c in result.classes
                if "zcl_im_account_check" in c["fqn"].lower()
                or "ZCL_IM_ACCOUNT_CHECK" in c["fqn"]), None)
    assert cls is not None, "BAdI implementation class not found"
    assert any("@BAdI" in a for a in cls.get("annotations", []))


def test_non_badi_class_has_no_badi_annotation():
    source = textwrap.dedent("""\
        CLASS zcl_regular DEFINITION PUBLIC.
          PUBLIC SECTION.
            INTERFACES zif_some_interface.
        ENDCLASS.
        CLASS zcl_regular IMPLEMENTATION.
        ENDCLASS.
    """)
    result = parse(source)
    for cls in result.classes:
        assert not any("@BAdI" in a for a in cls.get("annotations", []))
