"""Console routes for code-hygiene insights and refactors. Watch out for generated advice here, because these pages blend stored metrics with synthesized recommendations."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from deps import run_query, _template_ctx, templates

router = APIRouter()


def _parse_stats(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {}


@router.get("/hygiene", response_class=HTMLResponse)
async def hygiene_overview(request: Request):
    """All repos — hygiene score overview."""
    repos = run_query("""
        MATCH (r:Repository)
        RETURN r.repo_id       AS repo_id,
               r.hygiene_score AS score,
               r.hygiene_grade AS grade,
               r.hygiene_stats AS stats_json
        ORDER BY r.hygiene_score ASC
    """)
    repo_list = []
    for r in repos:
        stats = _parse_stats(r.get("stats_json"))
        repo_list.append({
            "repo_id":      r["repo_id"],
            "score":        r.get("score") or 0,
            "grade":        r.get("grade") or "?",
            "stats":        stats,
        })
    return templates.TemplateResponse("hygiene_overview.html", {
        **_template_ctx(request),
        "repos": repo_list,
    })


def _refactor_reasons(c: dict) -> list[dict]:
    """
    Derive a list of concrete refactoring reasons from a class's hygiene metrics.
    Each reason has: id, title, detail, expected_outcome, severity (high/medium/low).
    """
    reasons = []
    score       = c.get("score") or 0
    tier        = c.get("tier") or "small"
    coupling    = c.get("coupling") or 0
    blast       = c.get("blast_size") or 0
    methods     = c.get("method_count") or 0
    has_doc     = c.get("has_doc", False)
    grade       = c.get("grade") or "?"
    name        = c.get("name") or ""

    if tier == "god":
        reasons.append({
            "id": "god_class",
            "title": "God class — too many responsibilities",
            "detail": (
                f"`{name}` has {methods} methods and spans multiple concerns. "
                "God classes are expensive to load into AI context (3–15× token cost) and "
                "hard to reason about. They should be split into smaller, focused classes "
                "each with a single responsibility."
            ),
            "expected_outcome": (
                "Each extracted class fits in 1–2× token budget. Blast radius drops as "
                "dependents only import the specific class they need. Testability improves."
            ),
            "severity": "high",
        })

    if tier == "large":
        reasons.append({
            "id": "large_class",
            "title": "Large class — consider decomposition",
            "detail": (
                f"`{name}` is larger than typical and likely mixes several concerns. "
                f"With {methods} methods it exceeds the recommended size threshold. "
                "Extract cohesive groups of methods into separate classes or mixins."
            ),
            "expected_outcome": (
                "Smaller, focused classes are easier to test, understand, and load "
                "selectively into AI context. Token cost per interaction drops."
            ),
            "severity": "medium",
        })

    if coupling > 0.35:
        reasons.append({
            "id": "high_coupling",
            "title": f"High coupling ({coupling:.3f}) — reduce dependencies",
            "detail": (
                f"`{name}` has a coupling score of {coupling:.3f} (threshold: 0.35). "
                "High coupling means this class imports from or is tightly bound to many "
                "others, making changes risky and context expensive. Introduce interfaces, "
                "dependency injection, or break circular imports."
            ),
            "expected_outcome": (
                "Lower coupling reduces the number of files that must be loaded together "
                "for AI to reason about this class. Change risk decreases."
            ),
            "severity": "high" if coupling > 0.6 else "medium",
        })

    if blast > 50:
        reasons.append({
            "id": "high_blast",
            "title": f"High blast radius ({blast} dependents) — decouple",
            "detail": (
                f"{blast} other classes depend on `{name}`. Any change here ripples "
                "widely. Introduce an abstraction layer (interface or abstract base class) "
                "so dependents bind to a stable contract rather than the concrete class."
            ),
            "expected_outcome": (
                "Changes to `{name}` stop cascading. Dependents only need to know the "
                "interface, reducing required context per change."
            ),
            "severity": "high",
        })
    elif blast > 20:
        reasons.append({
            "id": "medium_blast",
            "title": f"Elevated blast radius ({blast} dependents)",
            "detail": (
                f"`{name}` is depended on by {blast} classes. Consider extracting a "
                "stable interface or splitting the class so dependents bind to a smaller surface."
            ),
            "expected_outcome": "Change blast radius reduced; easier to evolve in isolation.",
            "severity": "medium",
        })

    if not has_doc:
        reasons.append({
            "id": "missing_docs",
            "title": "Missing documentation — add docstrings",
            "detail": (
                f"`{name}` has no class-level docstring or javadoc. Without documentation "
                "AI tools must infer intent from implementation, which increases token usage "
                "and reduces accuracy. Add a class-level docstring and document all public methods."
            ),
            "expected_outcome": (
                "Documentation reduces hallucination risk when AI tools reason about this "
                "class. The docs dimension of the hygiene score improves, boosting overall grade."
            ),
            "severity": "medium",
        })

    if methods > 20 and tier not in ("god",):
        reasons.append({
            "id": "too_many_methods",
            "title": f"Too many methods ({methods}) — extract responsibilities",
            "detail": (
                f"`{name}` has {methods} methods, suggesting it handles multiple concerns. "
                "Group related methods and extract them into collaborating classes. "
                "Aim for ≤15 public methods per class."
            ),
            "expected_outcome": (
                "Each class becomes easier to understand in isolation. AI context for a "
                "single operation shrinks to the relevant class only."
            ),
            "severity": "low",
        })

    # Sort: high → medium → low
    order = {"high": 0, "medium": 1, "low": 2}
    reasons.sort(key=lambda r: order.get(r["severity"], 9))
    return reasons


def _benefit_score(c: dict, reasons: list[dict]) -> float:
    """
    Estimate refactoring benefit: how much AI token cost could be reduced.
    Higher = more benefit. Based on blast radius, tier, and score gap.
    """
    blast   = c.get("blast_size") or 0
    score   = c.get("score") or 0
    tier    = c.get("tier") or "small"
    tier_w  = {"god": 10, "large": 4, "medium": 2, "small": 1, "tiny": 0.5}.get(tier, 1)
    high_r  = sum(1 for r in reasons if r["severity"] == "high")
    return round((100 - score) * tier_w * (1 + blast * 0.05) * (1 + high_r * 0.3), 1)


@router.get("/hygiene/{repo_id}/refactor", response_class=HTMLResponse)
async def hygiene_refactor(request: Request, repo_id: str):
    """Refactoring plan — ranked list of classes worth refactoring with actionable reasons."""
    import json as _json

    classes = run_query("""
        MATCH (c:Class {repo_id: $repo_id})
        WHERE c.hygiene_grade IN ['C','D','F']
          AND NOT c.role IN ['TEST', 'GENERATED']
        OPTIONAL MATCH (c)-[:BELONGS_TO]->(mod:Module)
        WITH c, mod
        OPTIONAL MATCH (c)-[:HAS_METHOD]->(m)
        WITH c, mod, count(m) AS method_count
        RETURN
            c.fqn           AS fqn,
            c.name          AS name,
            c.hygiene_score AS score,
            c.hygiene_grade AS grade,
            c.hygiene_tier  AS tier,
            c.coupling      AS coupling,
            c.blast_size    AS blast_size,
            c.javadoc       AS javadoc,
            c.docstring     AS docstring,
            c.file_path     AS file_path,
            c.package_fqn   AS package_fqn,
            c.summary       AS summary,
            c.object_model  AS object_model,
            method_count,
            mod.module_id   AS module_id
        LIMIT 500
    """, repo_id=repo_id)

    # Batch-fetch callers and test coverage for all classes in one query each
    all_fqns = [c["fqn"] for c in classes if c.get("fqn")]

    callers_rows = run_query("""
        MATCH (caller:Class {repo_id: $repo_id})-[:IMPORTS]->(c:Class {repo_id: $repo_id})
        WHERE c.fqn IN $fqns
        RETURN c.fqn AS fqn, caller.fqn AS caller_fqn,
               caller.name AS caller_name, caller.file_path AS caller_file
        ORDER BY c.fqn, caller.name
    """, repo_id=repo_id, fqns=all_fqns) if all_fqns else []

    callers_by_fqn: dict[str, list[dict]] = {}
    for r in callers_rows:
        callers_by_fqn.setdefault(r["fqn"], []).append({
            "fqn":  r["caller_fqn"],
            "name": r["caller_name"],
            "file": r["caller_file"] or "",
        })

    tested_fqns: set[str] = set()
    if all_fqns:
        test_rows = run_query("""
            MATCH (t:Class {repo_id: $repo_id})-[:IMPORTS]->(c:Class {repo_id: $repo_id})
            WHERE c.fqn IN $fqns AND t.role IN ['TEST', 'test', 'Test']
            RETURN DISTINCT c.fqn AS fqn
        """, repo_id=repo_id, fqns=all_fqns)
        tested_fqns = {r["fqn"] for r in test_rows}

    class_list = []
    for c in classes:
        fqn = c["fqn"]

        # Extract public method signatures from object_model
        methods: list[str] = []
        om_raw = c.get("object_model")
        if om_raw:
            try:
                om = _json.loads(om_raw) if isinstance(om_raw, str) else om_raw
                for m in (om.get("methods") or []):
                    mods = " ".join(m.get("modifiers") or [])
                    if "private" in mods or "protected" in mods:
                        continue
                    name_str  = m.get("name", "")
                    params    = ", ".join(m.get("parameters") or [])
                    ret       = m.get("return_type") or ""
                    sig = f"{name_str}({params})"
                    if ret and ret != "void":
                        sig += f" → {ret}"
                    methods.append(sig)
            except (ValueError, KeyError, TypeError):
                pass

        obj = {
            "fqn":          fqn,
            "name":         c["name"] or fqn.split(".")[-1],
            "score":        c.get("score") or 0,
            "grade":        c.get("grade") or "?",
            "tier":         c.get("tier") or "small",
            "coupling":     round(c.get("coupling") or 0, 3),
            "blast_size":   c.get("blast_size") or 0,
            "has_doc":      bool(c.get("javadoc") or c.get("docstring")),
            "method_count": c.get("method_count") or 0,
            "package":      c.get("package_fqn") or "",
            "module_id":    c.get("module_id") or "",
            "file_path":    c.get("file_path") or "",
            "summary":      c.get("summary") or "",
            "methods":      methods[:20],   # cap at 20 for prompt size
            "callers":      callers_by_fqn.get(fqn, [])[:10],
            "has_tests":    fqn in tested_fqns,
        }
        obj["reasons"] = _refactor_reasons(obj)
        obj["benefit"] = _benefit_score(obj, obj["reasons"])
        class_list.append(obj)

    class_list.sort(key=lambda x: x["benefit"], reverse=True)

    # Module index path hint for the agent
    module_index_path = ".codekg/modules/<name>.md"

    return templates.TemplateResponse("hygiene_refactor.html", {
        **_template_ctx(request),
        "repo_id":           repo_id,
        "classes":           class_list,
        "module_index_path": module_index_path,
    })


@router.get("/hygiene/{repo_id:path}", response_class=HTMLResponse)
async def hygiene_detail(request: Request, repo_id: str):
    """Per-repo hygiene drill-down — all classes with scores."""

    # Repo-level summary
    repo_rows = run_query("""
        MATCH (r:Repository {repo_id: $repo_id})
        RETURN r.hygiene_score AS score,
               r.hygiene_grade AS grade,
               r.hygiene_stats AS stats_json
    """, repo_id=repo_id)
    if not repo_rows:
        return templates.TemplateResponse("hygiene_detail.html", {
            **_template_ctx(request),
            "repo_id": repo_id,
            "repo_score": None,
            "classes": [],
            "stats": {},
        })

    repo = repo_rows[0]
    stats = _parse_stats(repo.get("stats_json"))

    # All non-test classes with hygiene data, linked to module
    classes = run_query("""
        MATCH (c:Class {repo_id: $repo_id})
        WHERE c.hygiene_score IS NOT NULL
          AND NOT c.role IN ['TEST', 'GENERATED']
        OPTIONAL MATCH (c)-[:BELONGS_TO]->(mod:Module)
        WITH c, mod
        OPTIONAL MATCH (c)-[:HAS_METHOD]->(m)
        WITH c, mod, count(m) AS method_count
        RETURN
            c.fqn            AS fqn,
            c.name           AS name,
            c.role           AS role,
            c.hygiene_score  AS score,
            c.hygiene_grade  AS grade,
            c.hygiene_tier   AS tier,
            c.coupling       AS coupling,
            c.blast_size     AS blast_size,
            c.javadoc        AS javadoc,
            c.docstring      AS docstring,
            c.package_fqn    AS package_fqn,
            method_count,
            mod.module_id    AS module_id
        ORDER BY c.hygiene_score ASC
        LIMIT 2000
    """, repo_id=repo_id)

    class_list = []
    for c in classes:
        class_list.append({
            "fqn":         c["fqn"],
            "name":        c["name"] or c["fqn"].split(".")[-1],
            "role":        c.get("role") or "CLASS",
            "score":       c.get("score") or 0,
            "grade":       c.get("grade") or "?",
            "tier":        c.get("tier") or "small",
            "coupling":    round(c.get("coupling") or 0, 3),
            "blast_size":  c.get("blast_size") or 0,
            "has_doc":     bool(c.get("javadoc") or c.get("docstring")),
            "method_count": c.get("method_count") or 0,
            "package":     c.get("package_fqn") or "",
            "module_id":   c.get("module_id") or "",
        })

    return templates.TemplateResponse("hygiene_detail.html", {
        **_template_ctx(request),
        "repo_id":    repo_id,
        "repo_score": repo.get("score") or 0,
        "repo_grade": repo.get("grade") or "?",
        "stats":      stats,
        "classes":    class_list,
    })
