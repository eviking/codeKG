"""
Combines signal results into per-vector scores using weights from config.

Score formula per vector:
    raw      = sum(signal_value * weight  for each enabled, fired signal)
    max_raw  = sum(weight                 for each enabled signal)
    score    = min(1.0, raw / max_raw) if max_raw > 0 else 0.0

A score of 1.0 means every enabled signal fired at full strength.
Weights above 1.0 amplify individual signals; they don't break the [0,1] ceiling.
"""
from __future__ import annotations

from shared.impact_config import ImpactVectorConfig, VectorConfig
from shared.impact_signals import SIGNAL_REGISTRY


def _score_vector(
    vector_name: str,
    vec_cfg: VectorConfig,
    diff_lines: list[str],
    graph: dict,
) -> tuple[float, list[dict]]:
    """
    Run all enabled signals for one vector.
    Returns (score 0-1, list of fired-signal dicts for the rationale UI).
    """
    fired: list[dict] = []
    raw = 0.0
    max_raw = 0.0

    for sig_name, sig_cfg in vec_cfg.signals.items():
        if not sig_cfg.enabled:
            continue

        w = sig_cfg.weight
        max_raw += w

        fn = SIGNAL_REGISTRY.get(sig_name)
        if fn is None:
            continue

        try:
            value, detail = fn(diff_lines, graph, sig_cfg)
        except Exception:
            value, detail = 0.0, ""

        if value > 0:
            raw += value * w
            fired.append({
                "name":   sig_name,
                "value":  round(value, 3),
                "weight": w,
                "detail": detail,
            })

    score = min(1.0, raw / max_raw) if max_raw > 0 else 0.0
    return round(score, 4), fired


def score_all_vectors(
    diff_lines: list[str],
    graph: dict,
    config: ImpactVectorConfig,
) -> dict:
    """
    Run all six vectors. Returns a dict with scores and per-vector signal details.

    graph keys expected:
        direct      — list of directly affected class dicts
        callers     — list of caller class dicts
        transitive  — list of transitive dependent dicts
        endpoints   — list of exposed endpoint dicts
        policies    — list of relevant policy dicts
        tests       — list of suggested test dicts
    """
    vectors = [
        ("security",      config.security),
        ("availability",  config.availability),
        ("performance",   config.performance),
        ("observability", config.observability),
        ("operations",    config.operations),
        ("dependencies",  config.dependencies),
    ]

    scores: dict[str, float] = {}
    signals_detail: dict[str, list[dict]] = {}

    for vec_name, vec_cfg in vectors:
        score, fired = _score_vector(vec_name, vec_cfg, diff_lines, graph)
        scores[vec_name] = score
        signals_detail[vec_name] = fired

    # Overall risk: weighted average of all vector scores,
    # with availability and security weighted higher.
    weights = {
        "security":      2.0,
        "availability":  2.0,
        "performance":   1.0,
        "observability": 1.0,
        "operations":    1.5,
        "dependencies":  1.0,
    }
    total_w = sum(weights.values())
    risk_raw = sum(scores[v] * weights[v] for v in scores)
    risk_score = round(min(1.0, risk_raw / total_w), 4)

    # Also factor in raw graph size so that large blast-radius commits
    # can't score zero just because no diff signals fired.
    n_direct   = len(graph.get("direct", []))
    n_callers  = len(graph.get("callers", []))
    n_trans    = len(graph.get("transitive", []))
    n_endpoints = len(graph.get("endpoints", []))
    n_policies  = len(graph.get("policies", []))
    graph_risk = min(1.0, (
        n_direct    * 0.04 +
        n_callers   * 0.02 +
        n_trans     * 0.01 +
        n_endpoints * 0.10 +
        n_policies  * 0.05
    ))
    # Blend: signal-based risk (70%) + graph-size risk (30%)
    risk_score = round(min(1.0, risk_score * 0.7 + graph_risk * 0.3), 4)

    total_affected = len(set(
        [r.get("fqn", "") for r in graph.get("direct", [])] +
        [r.get("fqn", "") for r in graph.get("callers", [])] +
        [r.get("fqn", "") for r in graph.get("transitive", [])]
    ))

    return {
        "risk_score":           risk_score,
        "total_affected":       total_affected,
        "security_score":       scores["security"],
        "availability_score":   scores["availability"],
        "performance_score":    scores["performance"],
        "observability_score":  scores["observability"],
        "ops_score":            scores["operations"],
        "deps_score":           scores["dependencies"],
        "signals":              signals_detail,
    }
