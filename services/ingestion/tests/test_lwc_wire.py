"""Tests for LWC @wire adapter extraction in the JS parser."""
import textwrap
from pathlib import Path

from parser.js_parser import JsParser


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


# LWC component JS with @wire decorators
WIRE_COMPONENT = textwrap.dedent("""\
    import { LightningElement, wire } from 'lwc';
    import { getRecord, getFieldValue } from 'lightning/uiRecordApi';
    import ACCOUNT_NAME from '@salesforce/schema/Account.Name';
    import ACCOUNT_RATING from '@salesforce/schema/Account.Rating';
    import getAccounts from '@salesforce/apex/AccountController.getAccounts';

    export default class AccountDetail extends LightningElement {
        @wire(getRecord, { recordId: '$recordId', fields: [ACCOUNT_NAME, ACCOUNT_RATING] })
        account;

        @wire(getAccounts)
        accounts;
    }
""")

WIRE_WITH_SOBJECT_STRING = textwrap.dedent("""\
    import { LightningElement, wire } from 'lwc';
    import { getRelatedListRecords } from 'lightning/uiRelatedListApi';

    export default class RelatedList extends LightningElement {
        @wire(getRelatedListRecords, {
            parentRecordId: '$recordId',
            relatedListId: 'Contacts',
            fields: ['Contact.Name', 'Contact.Email']
        })
        contacts;
    }
""")

NO_WIRE_COMPONENT = textwrap.dedent("""\
    import { LightningElement } from 'lwc';

    export default class Simple extends LightningElement {
        connectedCallback() {}
    }
""")


def test_wire_adapter_emits_calls_edge(tmp_path):
    path = _write(tmp_path, "accountDetail.js", WIRE_COMPONENT)
    result = JsParser().parse_file(path, "repo1")
    calls = {e["target"] for e in result.edges if e["type"] == "CALLS"}
    assert "getRecord" in calls


def test_apex_wire_adapter_emits_calls_edge(tmp_path):
    path = _write(tmp_path, "accountDetail.js", WIRE_COMPONENT)
    result = JsParser().parse_file(path, "repo1")
    calls = {e["target"] for e in result.edges if e["type"] == "CALLS"}
    assert "getAccounts" in calls


def test_wire_schema_token_emits_queries_edge(tmp_path):
    path = _write(tmp_path, "accountDetail.js", WIRE_COMPONENT)
    result = JsParser().parse_file(path, "repo1")
    queries = {e["target"] for e in result.edges if e["type"] == "QUERIES"}
    assert "sobject/Account" in queries


def test_wire_sobject_string_field_emits_queries_edge(tmp_path):
    path = _write(tmp_path, "relatedList.js", WIRE_WITH_SOBJECT_STRING)
    result = JsParser().parse_file(path, "repo1")
    queries = {e["target"] for e in result.edges if e["type"] == "QUERIES"}
    assert "sobject/Contact" in queries


def test_no_wire_no_wire_edges(tmp_path):
    path = _write(tmp_path, "simple.js", NO_WIRE_COMPONENT)
    result = JsParser().parse_file(path, "repo1")
    wire_calls = [e for e in result.edges
                  if e["type"] == "CALLS" and e.get("target") in ("getRecord", "getAccounts")]
    assert wire_calls == []
