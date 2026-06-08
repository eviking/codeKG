"""
Unit tests for the ImpactEngine — all graph traversals mocked.

Covers:
- empty changed_files short-circuits early
- each component query (directly_affected, callers, transitive_dependents, etc.)
- risk_score boundaries (0.0 and 1.0)
- to_dict serialisation
"""
from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from impact.engine import ImpactEngine, ImpactReport, ImpactedNode, ImpactedEndpoint, ImpactedPolicy, SuggestedTest


def _make_driver(side_effect=None, return_value=None):
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    if side_effect is not None:
        session.run.side_effect = side_effect
    else:
        result = MagicMock()
        result.__iter__ = MagicMock(return_value=iter(return_value or []))
        session.run.return_value = result
    return driver


def _engine_with_run(responses: list[list[dict]]) -> ImpactEngine:
    """Create an ImpactEngine whose _run() returns successive lists."""
    driver = MagicMock()
    engine = ImpactEngine(driver)
    engine._run = MagicMock(side_effect=responses)
    return engine


# ---------------------------------------------------------------------------
# Empty input guard
# ---------------------------------------------------------------------------

def test_empty_files_returns_empty_report():
    engine = _engine_with_run([])
    report = engine.compute(repo_id="r", changed_files=[])
    assert report.directly_affected == []
    assert report.callers == []
    assert report.risk_score == 0.0
    engine._run.assert_not_called()


def test_no_directly_affected_classes_short_circuits():
    engine = _engine_with_run([[]])  # directly_affected returns []
    report = engine.compute(repo_id="r", changed_files=["/Foo.java"])
    assert report.directly_affected == []
    assert report.callers == []
    assert engine._run.call_count == 1


# ---------------------------------------------------------------------------
# directly_affected
# ---------------------------------------------------------------------------

def test_directly_affected_maps_rows():
    rows = [{"fqn": "com.A", "name": "A", "kind": "class",
             "file_path": "/A.java", "module": "auth", "confidence": 0.9}]
    engine = _engine_with_run([
        rows,   # directly_affected
        [],     # callers
        [],     # transitive_dependents
        [],     # exposed_endpoints
        [],     # affected_modules
        [],     # relevant_policies
        [],     # name_tests (suggested_tests)
    ])
    report = engine.compute(repo_id="r", changed_files=["/A.java"])
    assert len(report.directly_affected) == 1
    n = report.directly_affected[0]
    assert n.fqn == "com.A"
    assert n.hop_distance == 0
    assert n.reason == "direct"


# ---------------------------------------------------------------------------
# callers
# ---------------------------------------------------------------------------

def test_callers_hop_distance_is_one():
    direct_rows = [{"fqn": "com.A", "name": "A", "kind": "class",
                    "file_path": "/A.java", "module": None, "confidence": 1.0}]
    caller_rows = [{"fqn": "com.B", "name": "B", "kind": "class",
                    "file_path": "/B.java", "module": None, "confidence": 0.8}]
    engine = _engine_with_run([direct_rows, caller_rows, [], [], [], [], []])
    report = engine.compute(repo_id="r", changed_files=["/A.java"])
    assert len(report.callers) == 1
    assert report.callers[0].hop_distance == 1
    assert report.callers[0].reason == "caller"


# ---------------------------------------------------------------------------
# transitive_dependents
# ---------------------------------------------------------------------------

def test_transitive_dependents_use_hops_from_row():
    direct_rows = [{"fqn": "com.A", "name": "A", "kind": "class",
                    "file_path": "/A.java", "module": None, "confidence": 1.0}]
    trans_rows = [{"fqn": "com.C", "name": "C", "kind": "class",
                   "file_path": "/C.java", "module": None, "hops": 3, "confidence": 0.75}]
    engine = _engine_with_run([direct_rows, [], trans_rows, [], [], [], []])
    report = engine.compute(repo_id="r", changed_files=["/A.java"])
    assert report.transitive_dependents[0].hop_distance == 3
    assert report.transitive_dependents[0].reason == "transitive-import"


# ---------------------------------------------------------------------------
# exposed_endpoints
# ---------------------------------------------------------------------------

def test_exposed_endpoints_mapped():
    direct_rows = [{"fqn": "com.A", "name": "A", "kind": "class",
                    "file_path": "/A.java", "module": None, "confidence": 1.0}]
    ep_rows = [{"endpoint_id": "ep-1", "http_method": "GET", "path": "/api/foo",
                "handler_class": "com.A", "handler_method": "getAll",
                "file_path": "/A.java", "confidence": 0.9}]
    engine = _engine_with_run([direct_rows, [], [], ep_rows, [], [], []])
    report = engine.compute(repo_id="r", changed_files=["/A.java"])
    assert len(report.exposed_endpoints) == 1
    assert report.exposed_endpoints[0].path == "/api/foo"


# ---------------------------------------------------------------------------
# relevant_policies
# ---------------------------------------------------------------------------

def test_relevant_policies_mapped():
    direct_rows = [{"fqn": "com.A", "name": "A", "kind": "class",
                    "file_path": "/A.java", "module": "auth", "confidence": 1.0}]
    module_rows = [{"module": "auth"}]
    policy_rows = [{"policy_id": "p-1", "title": "T", "natural_language": "NL",
                    "severity": "error", "is_violated": True}]
    # _suggested_tests makes 2 calls: name_tests + module_tests
    engine = _engine_with_run([direct_rows, [], [], [], module_rows, policy_rows, [], []])
    report = engine.compute(repo_id="r", changed_files=["/A.java"])
    assert len(report.relevant_policies) == 1
    assert report.relevant_policies[0].is_violated is True


def test_relevant_policies_empty_modules_skips_query():
    direct_rows = [{"fqn": "com.A", "name": "A", "kind": "class",
                    "file_path": "/A.java", "module": None, "confidence": 1.0}]
    # modules returns empty → _relevant_policies bails early → suggested_tests still queried
    engine = _engine_with_run([direct_rows, [], [], [], [], [], []])
    report = engine.compute(repo_id="r", changed_files=["/A.java"])
    assert report.relevant_policies == []


# ---------------------------------------------------------------------------
# suggested_tests
# ---------------------------------------------------------------------------

def test_suggested_tests_deduplicates():
    direct_rows = [{"fqn": "com.Foo", "name": "Foo", "kind": "class",
                    "file_path": "/Foo.java", "module": "core", "confidence": 1.0}]
    module_rows = [{"module": "core"}]
    test_row = {"fqn": "com.FooTest", "name": "FooTest", "file_path": "/FooTest.java"}
    # Both name-match and module-match return the same test — should deduplicate
    engine = _engine_with_run([
        direct_rows, [], [], [], module_rows,
        [],            # relevant_policies
        [test_row],    # name_tests
        [test_row],    # module_tests
    ])
    report = engine.compute(repo_id="r", changed_files=["/Foo.java"])
    assert len(report.suggested_tests) == 1


# ---------------------------------------------------------------------------
# Risk score
# ---------------------------------------------------------------------------

def test_risk_score_zero_for_empty_report():
    report = ImpactReport(repo_id="r", changed_files=[], commit_sha=None)
    engine = ImpactEngine(MagicMock())
    score = engine._risk_score(report)
    assert score == 0.0


def test_risk_score_caps_at_one():
    report = ImpactReport(
        repo_id="r", changed_files=[], commit_sha=None,
        total_affected_classes=1000,
        total_affected_modules=100,
        exposed_endpoints=[MagicMock()] * 100,
        relevant_policies=[MagicMock(severity="error")] * 100,
    )
    engine = ImpactEngine(MagicMock())
    score = engine._risk_score(report)
    assert score <= 1.0


def test_risk_score_increases_with_class_count():
    base = ImpactReport(repo_id="r", changed_files=[], commit_sha=None,
                        total_affected_classes=1, total_affected_modules=0)
    large = ImpactReport(repo_id="r", changed_files=[], commit_sha=None,
                         total_affected_classes=50, total_affected_modules=0)
    engine = ImpactEngine(MagicMock())
    assert engine._risk_score(large) > engine._risk_score(base)


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------

def test_to_dict_structure():
    report = ImpactReport(
        repo_id="r", changed_files=["/A.java"], commit_sha="abc",
        directly_affected=[ImpactedNode("com.A", "A", "class", "/A.java", None, 0, "direct")],
        callers=[],
        transitive_dependents=[],
        affected_modules=["auth"],
        exposed_endpoints=[ImpactedEndpoint("ep1", "GET", "/a", "com.A", "getA", "/A.java")],
        relevant_policies=[ImpactedPolicy("p1", "T", "NL", "error", False)],
        suggested_tests=[SuggestedTest("com.ATest", "ATest", "/ATest.java", "name-match")],
        total_affected_classes=1,
        total_affected_modules=1,
        risk_score=0.1,
    )
    d = report.to_dict()
    assert d["repo_id"] == "r"
    assert d["summary"]["directly_affected_classes"] == 1
    assert d["summary"]["affected_modules"] == ["auth"]
    assert len(d["directly_affected"]) == 1
    assert d["directly_affected"][0]["fqn"] == "com.A"
    assert len(d["exposed_endpoints"]) == 1
    assert len(d["relevant_policies"]) == 1
    assert len(d["suggested_tests"]) == 1
