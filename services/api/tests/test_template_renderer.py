"""
Unit tests for services/api/renderers/template_renderer.py.

Coverage scope:
  - primary language detection from repository metadata
  - fallback language detection from indexed class names
  - render_template() joins only non-empty sections

All tests stub the graph query helpers; no live Neo4j connection is used.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

_SVC_ROOT = str(Path(__file__).parent.parent)
_PROJECT_ROOT = str(Path(__file__).parent.parent.parent.parent)
for _path in (_PROJECT_ROOT, _SVC_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from renderers import template_renderer


class TestDetectLanguage:
    """Exercises detect language behavior in the template renderer test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_prefers_repo_metadata(self, monkeypatch):
        monkeypatch.setattr(template_renderer, "_repo", lambda driver, repo_id: {"language": "Python"})
        assert template_renderer._detect_language(object(), "repo1") == "Python"

    def test_falls_back_to_java_like_fqns(self, monkeypatch):
        monkeypatch.setattr(template_renderer, "_repo", lambda driver, repo_id: {})
        monkeypatch.setattr(
            template_renderer,
            "_q",
            lambda driver, cypher, **params: [{"fqn": "com.example.Foo"}, {"fqn": "org.example.Bar"}],
        )
        assert template_renderer._detect_language(object(), "repo1") == "Java"

    def test_falls_back_to_python_like_fqns(self, monkeypatch):
        monkeypatch.setattr(template_renderer, "_repo", lambda driver, repo_id: {})
        monkeypatch.setattr(
            template_renderer,
            "_q",
            lambda driver, cypher, **params: [{"fqn": "services.api.main"}, {"fqn": "standalone_module"}],
        )
        assert template_renderer._detect_language(object(), "repo1") == "Python"


class TestRenderTemplate:
    """Exercises render template behavior in the template renderer test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_skips_empty_sections_when_joining(self, monkeypatch):
        monkeypatch.setattr(template_renderer, "_header", lambda driver, repo_id: "HEADER")
        monkeypatch.setattr(template_renderer, "_section_agent_protocol", lambda repo_id: "")
        monkeypatch.setattr(template_renderer, "_section_identity", lambda driver, repo_id: "IDENTITY")
        monkeypatch.setattr(template_renderer, "_section_scale", lambda driver, repo_id: "")
        monkeypatch.setattr(template_renderer, "_section_role_distribution", lambda driver, repo_id: "")
        monkeypatch.setattr(template_renderer, "_section_subsystems", lambda driver, repo_id: "")
        monkeypatch.setattr(template_renderer, "_section_danger_zones", lambda driver, repo_id: "")
        monkeypatch.setattr(template_renderer, "_section_call_chains", lambda driver, repo_id: "")
        monkeypatch.setattr(template_renderer, "_section_extension_points", lambda driver, repo_id: "")
        monkeypatch.setattr(template_renderer, "_section_transport_layer", lambda driver, repo_id: "")
        monkeypatch.setattr(template_renderer, "_section_patterns", lambda driver, repo_id: "")
        monkeypatch.setattr(template_renderer, "_section_generated_code", lambda driver, repo_id: "")
        monkeypatch.setattr(template_renderer, "_section_test_architecture", lambda driver, repo_id: "")
        monkeypatch.setattr(template_renderer, "_section_build", lambda driver, repo_id: "")
        monkeypatch.setattr(template_renderer, "_section_policies", lambda driver, repo_id: "")
        monkeypatch.setattr(template_renderer, "_section_working_rules", lambda driver, repo_id: "")
        monkeypatch.setattr(template_renderer, "_footer", lambda driver, repo_id: "FOOTER")

        rendered = template_renderer.render_template(object(), "repo1")
        assert rendered == "HEADER\n\nIDENTITY\n\nFOOTER"
