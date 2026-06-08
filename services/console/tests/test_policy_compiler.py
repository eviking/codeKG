"""
Unit tests for the policy compiler.

The compiler is pure Python with no external dependencies — tests run fully offline.
"""
from __future__ import annotations

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from policy_compiler import compile_policy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_placeholder(cypher: str) -> bool:
    return cypher.strip().startswith("//")


# ---------------------------------------------------------------------------
# Cross-module call restriction
# ---------------------------------------------------------------------------

class TestModuleMustNotCall:
    """Exercises module must not call behavior in the policy compiler test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_basic_match(self):
        cypher = compile_policy("auth module must not call billing")
        assert "MATCH" in cypher
        assert "'auth'" in cypher
        assert "'billing'" in cypher
        assert not _is_placeholder(cypher)

    def test_directly_variant(self):
        cypher = compile_policy("auth module must not directly call billing")
        assert not _is_placeholder(cypher)

    def test_services_in_prefix(self):
        cypher = compile_policy("services in payments module must not call fraud")
        assert not _is_placeholder(cypher)

    def test_returns_fqn_column(self):
        cypher = compile_policy("auth module must not call billing")
        assert "fqn" in cypher.lower()


# ---------------------------------------------------------------------------
# Layer dependency restriction
# ---------------------------------------------------------------------------

class TestLayerMustNotDependOn:
    """Exercises layer must not depend on behavior in the policy compiler test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_basic_match(self):
        cypher = compile_policy("controller layer must not depend on repository")
        assert "MATCH" in cypher
        assert not _is_placeholder(cypher)

    def test_quoted_names(self):
        cypher = compile_policy("'controller' layer must not depend on 'service'")
        assert not _is_placeholder(cypher)

    def test_returns_fqn(self):
        cypher = compile_policy("web layer must not depend on data")
        assert "fqn" in cypher


# ---------------------------------------------------------------------------
# Annotation requirement
# ---------------------------------------------------------------------------

class TestAnnotationRequired:
    """Exercises annotation required behavior in the policy compiler test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_basic_match(self):
        cypher = compile_policy("all classes in service module must have annotation @Transactional")
        assert not _is_placeholder(cypher)
        assert "Transactional" in cypher

    def test_without_at_prefix(self):
        cypher = compile_policy("all classes in web module must have annotation Service")
        assert not _is_placeholder(cypher)
        assert "Service" in cypher

    def test_case_insensitive(self):
        cypher = compile_policy("All Classes In Auth Module Must Have Annotation @Secured")
        assert not _is_placeholder(cypher)


# ---------------------------------------------------------------------------
# Controllers must not call repositories
# ---------------------------------------------------------------------------

class TestControllerRepoRestriction:
    """Exercises controller repo restriction behavior in the policy compiler test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_standard_phrasing(self):
        cypher = compile_policy("Controllers must not directly call repositories")
        assert not _is_placeholder(cypher)
        assert "controller" in cypher.lower()
        assert "repository" in cypher.lower()

    def test_without_directly(self):
        cypher = compile_policy("controllers must not call repositories")
        assert not _is_placeholder(cypher)


# ---------------------------------------------------------------------------
# Service must not extend
# ---------------------------------------------------------------------------

class TestServiceMustNotExtend:
    """Exercises service must not extend behavior in the policy compiler test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_basic_match(self):
        cypher = compile_policy("service classes must not extend BaseEntity")
        assert not _is_placeholder(cypher)
        assert "BaseEntity" in cypher


# ---------------------------------------------------------------------------
# Public method annotation requirement
# ---------------------------------------------------------------------------

class TestPublicMethodAnnotation:
    """Exercises public method annotation behavior in the policy compiler test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_basic_match(self):
        # Pattern matches "in <module> must [be] annotated with" — no "module" keyword
        cypher = compile_policy("all public methods in api must be annotated with @Logged")
        assert not _is_placeholder(cypher)
        assert "Logged" in cypher
        assert "public" in cypher

    def test_must_annotated_variant(self):
        cypher = compile_policy("all public methods in api must annotated with @Logged")
        assert not _is_placeholder(cypher)

    def test_module_keyword_in_phrase_is_not_matched(self):
        # "in api module must" is NOT matched (module keyword not in regex)
        # This documents a known gap in the compiler patterns
        cypher = compile_policy("all public methods in api module must be annotated with @Logged")
        assert isinstance(cypher, str)  # must not raise regardless

    def test_without_at_prefix(self):
        cypher = compile_policy("all public methods in core must annotated with Audited")
        assert not _is_placeholder(cypher)
        assert "Audited" in cypher


# ---------------------------------------------------------------------------
# Unrecognised input → placeholder comment
# ---------------------------------------------------------------------------

class TestUnknownPolicy:
    """Exercises unknown policy behavior in the policy compiler test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_gibberish_returns_placeholder(self):
        cypher = compile_policy("frobble the widget in a clockwise manner")
        assert _is_placeholder(cypher)

    def test_empty_string_returns_placeholder(self):
        cypher = compile_policy("")
        assert _is_placeholder(cypher)

    def test_placeholder_contains_original_text(self):
        nl = "something unrecognised"
        cypher = compile_policy(nl)
        assert nl in cypher

    def test_placeholder_has_fqn_comment(self):
        cypher = compile_policy("unknown constraint")
        assert "fqn" in cypher.lower()


# ---------------------------------------------------------------------------
# Output safety — no template injection
# ---------------------------------------------------------------------------

class TestOutputSafety:
    """Exercises output safety behavior in the policy compiler test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_curly_braces_in_input_do_not_cause_key_error(self):
        """Malformed input with stray braces must not raise KeyError."""
        try:
            result = compile_policy("auth {module} must not call {billing}")
            assert isinstance(result, str)
        except KeyError:
            pytest.fail("compile_policy raised KeyError on input with curly braces")
