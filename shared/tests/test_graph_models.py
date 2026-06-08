"""
Unit tests for shared/models/graph.py.

Coverage scope:
  - Provenance confidence tier thresholds
  - Provenance serialisation
  - dataclass default factories stay isolated between instances
  - enum values match the graph wire format
"""
from __future__ import annotations

from shared.models.graph import (
    ArchPolicyNode,
    ClassNode,
    ConfidenceTier,
    Edge,
    EdgeType,
    Provenance,
)


class TestProvenance:
    """Exercises provenance behavior in the graph models test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_tier_thresholds(self):
        assert Provenance("sha", "2026-01-01T00:00:00Z", confidence=0.95).tier() == ConfidenceTier.HIGH
        assert Provenance("sha", "2026-01-01T00:00:00Z", confidence=0.75).tier() == ConfidenceTier.MEDIUM
        assert Provenance("sha", "2026-01-01T00:00:00Z", confidence=0.2).tier() == ConfidenceTier.LOW

    def test_to_dict_preserves_values(self):
        prov = Provenance(
            commit_sha="abc123",
            freshness_ts="2026-01-01T00:00:00Z",
            confidence=0.88,
            source_tool="manual",
        )
        assert prov.to_dict() == {
            "commit_sha": "abc123",
            "freshness_ts": "2026-01-01T00:00:00Z",
            "confidence": 0.88,
            "source_tool": "manual",
        }


class TestDataclassDefaults:
    """Exercises dataclass defaults behavior in the graph models test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_classnode_annotations_do_not_leak_between_instances(self):
        left = ClassNode("pkg.Left", "Left", "pkg", "repo")
        right = ClassNode("pkg.Right", "Right", "pkg", "repo")
        left.annotations.append("@Service")
        assert right.annotations == []

    def test_edge_properties_do_not_leak_between_instances(self):
        first = Edge("a", "b", EdgeType.CALLS)
        second = Edge("x", "y", EdgeType.IMPORTS)
        first.properties["reason"] = "unit-test"
        assert second.properties == {}

    def test_archpolicy_targets_do_not_leak_between_instances(self):
        first = ArchPolicyNode("p1", "No cycles", "No cycles", "MATCH ...")
        second = ArchPolicyNode("p2", "No leaks", "No leaks", "MATCH ...")
        first.module_targets.append("billing")
        assert second.module_targets == []


class TestEnumValues:
    """Exercises enum values behavior in the graph models test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_edge_types_keep_wire_format_values(self):
        assert EdgeType.CALLS.value == "CALLS"
        assert EdgeType.VIOLATES.value == "VIOLATES"
