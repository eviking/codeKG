"""
Provenance helpers — produce Provenance objects for each extractor type
and inject them as Neo4j properties on every MERGE/SET.

Confidence defaults per source tool (matches the research report's confidence tiers):
  tree-sitter-java   → 0.85  (syntax-level facts, no semantic resolution)
  api-extractor      → 0.90  (annotation patterns are reliable for Spring/JAX-RS)
  concurrency-extrac → 0.80  (pattern matching, may miss dynamic thread creation)
  build-extractor    → 0.95  (build file parsing is highly reliable)
  repo-structure     → 0.75  (directory heuristics)
  human              → 1.00  (authored directly by architect)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


TOOL_CONFIDENCE: dict[str, float] = {
    "tree-sitter-java": 0.85,
    "jdt-ls": 0.99,
    "api-extractor": 0.90,
    "concurrency-extractor": 0.80,
    "build-extractor": 0.95,
    "repo-structure": 0.75,
    "maven": 0.97,
    "gradle": 0.97,
    "human": 1.00,
}


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_provenance(
    commit_sha: str,
    source_tool: str,
    confidence: Optional[float] = None,
    freshness_ts: Optional[str] = None,
) -> dict:
    """
    Return a flat dict of provenance properties ready to splat into a Cypher SET.
    Always call this when writing any node — never write a node without provenance.
    """
    return {
        "prov_commit_sha": commit_sha,
        "prov_freshness_ts": freshness_ts or now_utc(),
        "prov_confidence": confidence if confidence is not None else TOOL_CONFIDENCE.get(source_tool, 0.75),
        "prov_source_tool": source_tool,
    }


def provenance_set_clause(prefix: str = "n") -> str:
    """
    Return the Cypher SET fragment that stamps provenance fields onto a node.
    Usage: f"SET {provenance_set_clause('c')}"
    """
    return (
        f"{prefix}.prov_commit_sha = $prov_commit_sha, "
        f"{prefix}.prov_freshness_ts = $prov_freshness_ts, "
        f"{prefix}.prov_confidence = $prov_confidence, "
        f"{prefix}.prov_source_tool = $prov_source_tool"
    )


def is_stale(freshness_ts: str, max_age_minutes: int = 60) -> bool:
    """Check whether a provenance timestamp is older than max_age_minutes."""
    try:
        ts = datetime.strptime(freshness_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds() / 60
        return age > max_age_minutes
    except (ValueError, TypeError):
        return True
