"""
CodeKG Hygiene Scoring — AI cost-of-poor-hygiene signal.

Runs after enrichment at the end of every full scan. All inputs come
from properties already stored on Class nodes (coupling, blast_size,
method count, docstring presence) — no LLM calls, no file reads.

Score model (0–100, higher = healthier):
  Each class is scored on four equally-weighted dimensions (25 pts each):

  1. Size (method count)
     ≤ 10  → 25   ≤ 20  → 18   ≤ 30  → 10   ≤ 60  → 4    > 60 → 0

  2. Blast radius
     0     → 25   ≤ 5   → 20   ≤ 20  → 12   ≤ 50  → 5    ≤ 100 → 2   > 100 → 0

  3. Coupling score (0–1 float from enrichment)
     < 0.1 → 25   < 0.2 → 20   < 0.35 → 12  < 0.5 → 6    ≥ 0.5 → 0

  4. Documentation (docstring / javadoc presence)
     present → 25   absent → 0

Repo-level score = weighted average of all non-TEST, non-GENERATED classes.
God-class penalty applied at repo level: subtract 2 pts per god class
above 1% of total classes (capped at 20 pt deduction).

Letter grades:  A ≥ 80   B ≥ 65   C ≥ 50   D ≥ 35   F < 35

AI cost estimate:
  Baseline tokens per task on a class = 500 (clean small class).
  Multiplier table:
    score 80–100 → 1.0×    score 60–79 → 1.8×
    score 40–59  → 3.5×    score 20–39 → 7×    score 0–19 → 15×
  Repo estimate = sum(class_baseline × multiplier) across all non-test classes.
  Used to show "estimated extra tokens per task" due to hygiene debt.
"""
from __future__ import annotations

import json
import logging
from neo4j import Driver

try:
    from shared.codekg_logging.codekg_logger import get_logger
except ImportError:
    class _FB:
        """Fallback logger for hygiene scoring helpers. Watch out for reduced observability here, because score generation still proceeds even if structured logging is absent."""

        def __init__(self, n): self._l = logging.getLogger(n)
        def info(self, m, **k): self._l.info(m)
        def warning(self, m, **k): self._l.warning(m)
        def error(self, m, **k): self._l.error(m)
    def get_logger(n, **k): return _FB(n)

log = get_logger(__name__, service="ingestion")

_BATCH = 500
_BASE_TOKENS = 500          # tokens per task on a perfectly clean class
_SKIP_ROLES  = {"TEST", "GENERATED"}


# ── Per-class scoring helpers ─────────────────────────────────────────────────

def _score_size(method_count: int) -> int:
    if method_count <= 10: return 25
    if method_count <= 20: return 18
    if method_count <= 30: return 10
    if method_count <= 60: return 4
    return 0


def _score_blast(blast_size: int) -> int:
    if blast_size == 0:   return 25
    if blast_size <= 5:   return 20
    if blast_size <= 20:  return 12
    if blast_size <= 50:  return 5
    if blast_size <= 100: return 2
    return 0


def _score_coupling(coupling: float) -> int:
    if coupling < 0.10: return 25
    if coupling < 0.20: return 20
    if coupling < 0.35: return 12
    if coupling < 0.50: return 6
    return 0


def _score_docs(has_doc: bool) -> int:
    """Raw docstring only — 25 if present, 0 if absent."""
    return 25 if has_doc else 0


def _score_docs_with_summary(has_doc: bool, has_summary: bool) -> int:
    """Secondary score used for the 'with AI summaries' footnote."""
    if has_doc and has_summary: return 25
    if has_doc:                 return 20
    if has_summary:             return 18
    return 0


def _class_score(method_count: int, blast_size: int,
                 coupling: float, has_doc: bool) -> int:
    return (
        _score_size(method_count)
        + _score_blast(blast_size)
        + _score_coupling(coupling)
        + _score_docs(has_doc)
    )


def _letter_grade(score: float) -> str:
    if score >= 80: return "A"
    if score >= 65: return "B"
    if score >= 50: return "C"
    if score >= 35: return "D"
    return "F"


def _cost_multiplier(score: float) -> float:
    if score >= 80: return 1.0
    if score >= 60: return 1.8
    if score >= 40: return 3.5
    if score >= 20: return 7.0
    return 15.0


# ── Neo4j helpers ─────────────────────────────────────────────────────────────

def _run(driver: Driver, cypher: str, **params) -> list[dict]:
    with driver.session() as s:
        return [dict(r) for r in s.run(cypher, **params)]


def _fetch_classes(driver: Driver, repo_id: str) -> list[dict]:
    return _run(driver, """
        MATCH (c:Class {repo_id: $repo_id})
        OPTIONAL MATCH (c)-[:HAS_METHOD]->(m)
        WITH c, count(m) AS method_count
        RETURN
            c.fqn       AS fqn,
            c.role      AS role,
            c.coupling  AS coupling,
            c.blast_size AS blast_size,
            c.javadoc   AS javadoc,
            c.docstring AS docstring,
            c.summary   AS summary,
            method_count
    """, repo_id=repo_id)


def _write_class_scores(driver: Driver, repo_id: str, rows: list[dict]) -> None:
    for i in range(0, len(rows), _BATCH):
        batch = rows[i: i + _BATCH]
        with driver.session() as s:
            s.run("""
                UNWIND $rows AS row
                MATCH (c:Class {fqn: row.fqn, repo_id: $repo_id})
                SET c.hygiene_score = row.score,
                    c.hygiene_grade = row.grade,
                    c.hygiene_tier  = row.tier
            """, rows=batch, repo_id=repo_id)


def _write_repo_score(driver: Driver, repo_id: str, stats: dict) -> None:
    with driver.session() as s:
        s.run("""
            MATCH (r:Repository {repo_id: $repo_id})
            SET r.hygiene_score          = $score,
                r.hygiene_grade          = $grade,
                r.hygiene_stats          = $stats_json,
                r.hygiene_computed_at    = datetime()
        """,
        repo_id=repo_id,
        score=stats["repo_score"],
        grade=stats["repo_grade"],
        stats_json=json.dumps(stats, separators=(",", ":")))


# ── Main entry point ──────────────────────────────────────────────────────────

def compute_hygiene(driver: Driver, repo_id: str) -> dict:
    """
    Score every class and roll up to a repo-level hygiene score.
    Writes hygiene_score / hygiene_grade / hygiene_tier to each Class node
    and hygiene_score / hygiene_grade / hygiene_stats to the Repository node.
    Returns the repo-level stats dict.
    """
    log.info("Computing hygiene scores", repo_id=repo_id)

    classes = _fetch_classes(driver, repo_id)
    if not classes:
        log.warning("No classes found for hygiene scoring", repo_id=repo_id)
        return {}

    class_rows   = []
    scored       = []   # (score, method_count) for non-skip roles
    god_count    = 0
    total_count  = len(classes)

    tier_counts  = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
    tier_tokens  = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}

    # Per-dimension accumulators (non-test classes only)
    dim_size_scores     = []
    dim_blast_scores    = []
    dim_coupling_scores = []
    dim_doc_scores      = []
    dim_doc_ai_scores   = []   # for the "with AI summaries" footnote score
    missing_docs_count    = 0   # neither docstring nor summary
    missing_raw_doc_count = 0   # no raw docstring (may have summary)
    missing_summary_count = 0   # no NL summary (may have docstring)
    has_both_count        = 0   # both docstring and summary
    oversized_count     = 0   # method count > 15
    high_blast_count    = 0   # blast > 5
    high_coupling_count = 0   # coupling >= 0.2

    for cls in classes:
        role        = cls.get("role") or "CLASS"
        mc          = cls.get("method_count") or 0
        blast       = cls.get("blast_size") or 0
        coupling    = cls.get("coupling") or 0.0
        has_doc     = bool(cls.get("javadoc") or cls.get("docstring"))
        has_summary = bool(cls.get("summary"))

        s_size     = _score_size(mc)
        s_blast    = _score_blast(blast)
        s_coupling = _score_coupling(coupling)
        s_doc      = _score_docs(has_doc)                            # real score — docstring only
        s_doc_ai   = _score_docs_with_summary(has_doc, has_summary)  # assisted score — footnote only
        score      = s_size + s_blast + s_coupling + s_doc
        grade      = _letter_grade(score)

        # Tier label for display
        if mc > 60 or blast > 100:
            tier = "god"
            god_count += 1
        elif mc > 30 or blast > 50:
            tier = "large"
        elif mc > 15:
            tier = "medium"
        elif mc > 5:
            tier = "small"
        else:
            tier = "tiny"

        class_rows.append({
            "fqn":   cls["fqn"],
            "score": score,
            "grade": grade,
            "tier":  tier,
        })

        if role not in _SKIP_ROLES:
            scored.append((score, mc))
            tier_counts[grade] += 1
            tier_tokens[grade] += round(_BASE_TOKENS * _cost_multiplier(score))
            # Dimension accumulators
            dim_size_scores.append(s_size)
            dim_blast_scores.append(s_blast)
            dim_coupling_scores.append(s_coupling)
            dim_doc_scores.append(s_doc)
            dim_doc_ai_scores.append(s_doc_ai)
            if not has_doc and not has_summary: missing_docs_count    += 1
            if not has_doc:                      missing_raw_doc_count += 1
            if not has_summary:                  missing_summary_count += 1
            if has_doc and has_summary:          has_both_count        += 1
            if mc > 15:          oversized_count     += 1
            if blast > 5:        high_blast_count    += 1
            if coupling >= 0.2:  high_coupling_count += 1

    # Repo-level score = mean of non-test class scores
    if scored:
        raw_score = sum(s for s, _ in scored) / len(scored)
    else:
        raw_score = 0.0

    # God-class penalty: subtract 2 pts per god class above 1% of total
    threshold   = max(1, round(total_count * 0.01))
    excess_gods = max(0, god_count - threshold)
    penalty     = min(20, excess_gods * 2)
    repo_score  = round(max(0.0, raw_score - penalty), 1)
    repo_grade  = _letter_grade(repo_score)

    total_scored      = len(scored)
    est_tokens_actual = sum(tier_tokens.values())

    # Full-cleanup baseline: every class at grade A (multiplier 1.0)
    est_tokens_clean = total_scored * _BASE_TOKENS

    # Realistic savings: bring C, D, and F classes up to B (score 65, multiplier 1.8×)
    # This represents a realistic refactoring effort — split god classes, add docs, reduce coupling.
    # C classes cost 3.5×, D cost 7×, F cost 15× — all become B at 1.8×.
    cdf_count          = tier_counts["C"] + tier_counts["D"] + tier_counts["F"]
    cdf_tokens_current = tier_tokens["C"] + tier_tokens["D"] + tier_tokens["F"]
    cdf_tokens_at_b    = cdf_count * round(_BASE_TOKENS * _cost_multiplier(65))  # B threshold
    realistic_savings_tokens = max(0, cdf_tokens_current - cdf_tokens_at_b)
    realistic_savings_pct    = round(
        realistic_savings_tokens / max(est_tokens_actual, 1) * 100, 1
    )
    df_count = tier_counts["D"] + tier_counts["F"]

    # Full savings: current → fully clean
    full_savings_tokens = max(0, est_tokens_actual - est_tokens_clean)
    full_savings_pct    = round(
        full_savings_tokens / max(est_tokens_actual, 1) * 100, 1
    )

    n = max(total_scored, 1)

    # Per-dimension average scores (out of 25 each) and pass rates
    dim_size_avg     = round(sum(dim_size_scores)     / n, 1)
    dim_blast_avg    = round(sum(dim_blast_scores)    / n, 1)
    dim_coupling_avg = round(sum(dim_coupling_scores) / n, 1)
    dim_doc_avg      = round(sum(dim_doc_scores)      / n, 1)
    dim_doc_ai_avg   = round(sum(dim_doc_ai_scores)   / n, 1)

    # AI-assisted score: what the score would be if NL summaries counted
    ai_raw_score   = (dim_size_avg + dim_blast_avg + dim_coupling_avg + dim_doc_ai_avg)
    ai_repo_score  = round(max(0.0, ai_raw_score - penalty), 1)
    ai_repo_grade  = _letter_grade(ai_repo_score)

    # "Lost points" per dimension — how much the average class is losing vs perfect (25)
    dim_size_lost     = round(25 - dim_size_avg, 1)
    dim_blast_lost    = round(25 - dim_blast_avg, 1)
    dim_coupling_lost = round(25 - dim_coupling_avg, 1)
    dim_doc_lost      = round(25 - dim_doc_avg, 1)

    # Pct of classes failing each dimension (scoring < 25)
    size_fail_pct     = round(sum(1 for s in dim_size_scores     if s < 25) / n * 100, 1)
    blast_fail_pct    = round(sum(1 for s in dim_blast_scores    if s < 25) / n * 100, 1)
    coupling_fail_pct = round(sum(1 for s in dim_coupling_scores if s < 25) / n * 100, 1)
    doc_fail_pct      = round(missing_docs_count / n * 100, 1)

    # Rank dimensions by lost points — biggest drag first
    dims_ranked = sorted([
        {"name": "Documentation",  "avg": dim_doc_avg,      "lost": dim_doc_lost,      "fail_pct": doc_fail_pct,      "affected": missing_raw_doc_count, "max": 25,
         "what": f"{missing_raw_doc_count:,} classes missing raw docstring",
         "missing_raw_doc": missing_raw_doc_count, "missing_summary": missing_summary_count,
         "has_both": has_both_count, "missing_neither": missing_docs_count,
         "ai_avg": dim_doc_ai_avg},
        {"name": "Class size",     "avg": dim_size_avg,     "lost": dim_size_lost,     "fail_pct": size_fail_pct,     "affected": oversized_count,     "max": 25, "what": f"{oversized_count:,} classes have >15 methods"},
        {"name": "Blast radius",   "avg": dim_blast_avg,    "lost": dim_blast_lost,    "fail_pct": blast_fail_pct,    "affected": high_blast_count,    "max": 25, "what": f"{high_blast_count:,} classes have blast radius >5"},
        {"name": "Coupling",       "avg": dim_coupling_avg, "lost": dim_coupling_lost, "fail_pct": coupling_fail_pct, "affected": high_coupling_count, "max": 25, "what": f"{high_coupling_count:,} classes have coupling ≥0.2"},
    ], key=lambda d: d["lost"], reverse=True)

    stats = {
        "repo_score":              repo_score,
        "repo_grade":              repo_grade,
        "total_classes":           total_count,
        "scored_classes":          total_scored,
        "god_class_count":         god_count,
        "god_class_penalty":       penalty,
        "tier_counts":             tier_counts,
        "tier_tokens":             tier_tokens,
        "est_tokens_actual":       est_tokens_actual,
        "est_tokens_clean":        est_tokens_clean,
        # Savings
        "realistic_savings_pct":   realistic_savings_pct,
        "realistic_savings_tokens": realistic_savings_tokens,
        "full_savings_pct":        full_savings_pct,
        "full_savings_tokens":     full_savings_tokens,
        "df_class_count":          df_count,
        "cdf_class_count":         cdf_count,
        # Score explanation — the "why"
        "score_explanation": {
            "raw_score":        round(raw_score, 1),
            "penalty":          penalty,
            "dims":             dims_ranked,
            "dim_size_avg":     dim_size_avg,
            "dim_blast_avg":    dim_blast_avg,
            "dim_coupling_avg": dim_coupling_avg,
            "dim_doc_avg":      dim_doc_avg,
            # AI-assisted footnote
            "ai_score":         ai_repo_score,
            "ai_grade":         ai_repo_grade,
            "ai_doc_avg":       dim_doc_ai_avg,
            "classes_with_summary_only": total_scored - has_both_count - missing_docs_count,
        },
    }

    log.info("Writing class hygiene scores", repo_id=repo_id, count=len(class_rows))
    _write_class_scores(driver, repo_id, class_rows)
    _write_repo_score(driver, repo_id, stats)

    log.info("Hygiene scoring complete",
             repo_id=repo_id,
             score=repo_score,
             grade=repo_grade,
             god_classes=god_count,
             realistic_savings_pct=realistic_savings_pct,
             full_savings_pct=full_savings_pct)

    return stats
