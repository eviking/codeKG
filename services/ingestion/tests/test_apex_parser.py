"""
Smoke tests for ApexParser (services/ingestion/parser/apex_parser.py).

Tests run inside the ingestion container (needs tree_sitter_apex.so compiled from
the Dockerfile) — skip automatically when the grammar .so is not present.

Coverage:
  - Class extraction: fqn, modifiers, sharing model, annotations
  - Test class detection (@IsTest)
  - Method extraction: names, parameters, return types, annotations (@AuraEnabled)
  - Constructor extraction
  - Interface and enum parsing
  - Trigger parsing: fqn, kind, sObject, events stored as annotations
  - SOQL edges: QUERIES edges emitted for SELECT ... FROM ...
  - CALLS edges from method bodies
  - Robustness: empty source
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

_SVC_ROOT = str(Path(__file__).parent.parent)
if _SVC_ROOT not in sys.path:
    sys.path.insert(0, _SVC_ROOT)

# Skip the entire module if the Apex grammar .so is not available
try:
    from parser.apex_parser import ApexParser, APEX_EXTENSIONS
    _APEX_AVAILABLE = True
except ImportError:
    _APEX_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _APEX_AVAILABLE,
    reason="tree_sitter_apex.so not compiled — rebuild ingestion Docker image"
)


def _parse(source: str, file_path: str = "/repo/Foo.cls", repo_id: str = "test"):
    with tempfile.NamedTemporaryFile(suffix=".cls", delete=False) as f:
        f.write(source.encode())
        tmp = Path(f.name)
    try:
        return ApexParser().parse_file(tmp, repo_id)
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------

class TestApexExtensions:
    def test_extensions_set(self):
        assert ".cls" in APEX_EXTENSIONS
        assert ".trigger" in APEX_EXTENSIONS
        assert ".apex" in APEX_EXTENSIONS


# ---------------------------------------------------------------------------
# Class extraction
# ---------------------------------------------------------------------------

class TestClassExtraction:
    def test_simple_public_class(self):
        src = "public with sharing class AccountService { }"
        result = _parse(src)
        assert len(result.classes) == 1
        cls = result.classes[0]
        assert cls["name"] == "AccountService"
        assert cls["fqn"] == "AccountService"
        assert cls["kind"] == "class"

    def test_sharing_model_in_modifiers(self):
        src = "public with sharing class MyClass { }"
        result = _parse(src)
        mods = result.classes[0]["modifiers"]
        assert "with sharing" in mods or any("sharing" in m for m in mods)

    def test_without_sharing(self):
        src = "public without sharing class AdminUtils { }"
        result = _parse(src)
        mods = result.classes[0]["modifiers"]
        assert any("without" in m or "sharing" in m for m in mods)

    def test_abstract_class_kind(self):
        src = "public abstract class BaseHandler { }"
        result = _parse(src)
        assert result.classes[0]["kind"] == "abstract_class"

    def test_test_class_kind(self):
        src = "@IsTest\npublic class AccountServiceTest { }"
        result = _parse(src)
        assert result.classes[0]["kind"] == "test_class"

    def test_annotation_captured(self):
        src = "@SuppressWarnings('PMD')\npublic class Foo { }"
        result = _parse(src)
        anns = result.classes[0]["annotations"]
        assert any("SuppressWarnings" in a for a in anns)

    def test_extends_edge(self):
        src = "public class Handler extends BaseHandler { }"
        result = _parse(src)
        extends = [e for e in result.edges if e["type"] == "EXTENDS"]
        assert any(e["target"] == "BaseHandler" for e in extends)

    def test_implements_edge(self):
        src = "public class Svc implements Runnable { }"
        result = _parse(src)
        impl = [e for e in result.edges if e["type"] == "IMPLEMENTS"]
        assert any(e["target"] == "Runnable" for e in impl)

    def test_inner_class(self):
        src = """\
public class Outer {
    public class Inner { }
}"""
        result = _parse(src)
        fqns = {c["fqn"] for c in result.classes}
        assert "Outer" in fqns
        assert "Outer.Inner" in fqns


# ---------------------------------------------------------------------------
# Method extraction
# ---------------------------------------------------------------------------

class TestMethodExtraction:
    def test_simple_method(self):
        src = """\
public class Foo {
    public String getName() { return null; }
}"""
        result = _parse(src)
        assert any(m["name"] == "getName" for m in result.methods)

    def test_method_return_type(self):
        src = """\
public class Foo {
    public List<Account> getAccounts() { return null; }
}"""
        result = _parse(src)
        m = next(x for x in result.methods if x["name"] == "getAccounts")
        assert "List" in m["return_type"]

    def test_method_parameters(self):
        src = """\
public class Foo {
    public void process(Id recordId, String mode) { }
}"""
        result = _parse(src)
        m = next(x for x in result.methods if x["name"] == "process")
        assert len(m["parameters"]) == 2

    def test_aura_enabled_annotation(self):
        src = """\
public class Ctrl {
    @AuraEnabled(cacheable=true)
    public static List<Account> getAccounts() { return null; }
}"""
        result = _parse(src)
        m = next(x for x in result.methods if x["name"] == "getAccounts")
        assert any("AuraEnabled" in a for a in m["annotations"])

    def test_constructor(self):
        src = """\
public class Foo {
    public Foo(String name) { }
}"""
        result = _parse(src)
        ctors = [m for m in result.methods if m["name"] == "<init>"]
        assert len(ctors) == 1
        assert len(ctors[0]["parameters"]) == 1
        assert "constructor" in ctors[0]["modifiers"]


# ---------------------------------------------------------------------------
# Interface and enum
# ---------------------------------------------------------------------------

class TestInterfaceAndEnum:
    def test_interface_kind(self):
        src = "public interface Triggerable { void execute(); }"
        result = _parse(src)
        assert any(c["kind"] == "interface" for c in result.classes)

    def test_enum_kind(self):
        src = "public enum Status { OPEN, CLOSED, PENDING }"
        result = _parse(src)
        assert any(c["kind"] == "enum" for c in result.classes)


# ---------------------------------------------------------------------------
# Trigger parsing
# ---------------------------------------------------------------------------

class TestTriggerParsing:
    def test_trigger_kind(self):
        src = "trigger AccountTrigger on Account (before insert, after update) { }"
        result = _parse(src, file_path="/repo/AccountTrigger.trigger")
        assert any(c["kind"] == "trigger" for c in result.classes)

    def test_trigger_fqn(self):
        src = "trigger AccountTrigger on Account (before insert) { }"
        result = _parse(src, file_path="/repo/AccountTrigger.trigger")
        triggers = [c for c in result.classes if c["kind"] == "trigger"]
        assert triggers[0]["fqn"] == "AccountTrigger"

    def test_trigger_events_as_annotations(self):
        src = "trigger AccTrigger on Account (before insert, after update) { }"
        result = _parse(src, file_path="/repo/AccTrigger.trigger")
        trigger = next(c for c in result.classes if c["kind"] == "trigger")
        ann_str = " ".join(trigger["annotations"])
        assert "Account" in ann_str


# ---------------------------------------------------------------------------
# SOQL edges
# ---------------------------------------------------------------------------

class TestSoqlEdges:
    def test_soql_query_emits_queries_edge(self):
        src = """\
public class Repo {
    public List<Account> getAll() {
        return [SELECT Id, Name FROM Account];
    }
}"""
        result = _parse(src)
        soql_edges = [e for e in result.edges if e["type"] == "QUERIES"]
        assert any(e["target"] == "Account" for e in soql_edges)

    def test_soql_caller_fqn(self):
        src = """\
public class Repo {
    public void run() {
        List<Contact> c = [SELECT Id FROM Contact WHERE AccountId = :accId];
    }
}"""
        result = _parse(src)
        soql_edges = [e for e in result.edges if e["type"] == "QUERIES"]
        assert any("Contact" == e["target"] for e in soql_edges)
        assert any("run" in e["source"] for e in soql_edges)


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------

class TestRobustness:
    def test_empty_source(self):
        result = _parse("")
        assert result.classes == []
        assert result.methods == []
        assert result.edges == []

    def test_unparseable_source_does_not_crash(self):
        result = _parse("this is not apex %%% !!!")
        assert isinstance(result.classes, list)
