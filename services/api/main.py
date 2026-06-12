"""
Query API — the core HTTP layer consumed by the MCP server, the architecture
console, and CI/CD pipelines.

Authentication
--------------
When API_TOKEN is set in the environment all requests must carry:
    Authorization: Bearer <token>

When API_TOKEN is not set the API operates in open/single-user mode — all
requests are permitted without credentials.  This preserves the existing
localhost behaviour for users who haven't configured auth.

The /health endpoint is always unauthenticated.
"""
# ── Load persistent config overrides before anything else ─────────────────────
import os as _os
from pathlib import Path as _Path

_env_file = _Path(_os.environ.get("REPOS_PATH", "/repos")) / "codekg.env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#"):
            continue
        if "=" in _line:
            _k, _, _v = _line.partition("=")
            _k = _k.strip()
            _v = _v.strip().strip('"').strip("'")
            if _k not in _os.environ:
                _os.environ[_k] = _v
# ─────────────────────────────────────────────────────────────────────────────

import json as _json
import os
import secrets
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from neo4j import GraphDatabase
from starlette.middleware.base import BaseHTTPMiddleware

from shared.config import cfg
from shared.codekg_logging.codekg_logger import get_logger

log = get_logger(__name__, service="api")

app = FastAPI(title="CodeKG Query API", version="0.1.0")

driver = GraphDatabase.driver(cfg.neo4j.uri, auth=(cfg.neo4j.user, cfg.neo4j.password))

# Keep module-level alias so references deeper in the file keep working
_API_TOKEN: str = cfg.services.api_token


def _check_api_token(request: Request) -> bool:
    """Return True if the request carries a valid API token, or if auth is disabled."""
    if not _API_TOKEN:
        return True   # auth disabled — single-user mode
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False
    provided = auth_header[len("Bearer "):].strip()
    return secrets.compare_digest(provided, _API_TOKEN)


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Logs API requests with latency and status details. Watch out for noisy paths here, because this middleware runs on every request except the health check."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        if request.url.path != "/health":
            log.info("HTTP request",
                     method=request.method,
                     path=request.url.path,
                     status=response.status_code,
                     elapsed_ms=elapsed_ms)
        return response


class ApiTokenMiddleware(BaseHTTPMiddleware):
    """
    Enforce bearer-token authentication when API_TOKEN is configured.
    /health is always permitted.
    """
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        if not _check_api_token(request):
            log.warning("Unauthorized API request", path=request.url.path,
                        remote=request.client.host if request.client else "unknown")
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)


app.add_middleware(ApiTokenMiddleware)
app.add_middleware(RequestLogMiddleware)


def run_query(cypher: str, **params) -> list[dict]:
    with driver.session() as s:
        result = s.run(cypher, **params)
        return [dict(r) for r in result]


# ------------------------------------------------------------------
# Repository endpoints
# ------------------------------------------------------------------

@app.get("/repos")
def list_repos() -> list[dict]:
    return run_query("MATCH (r:Repository) RETURN r.repo_id AS repo_id, r.name AS name, r.last_commit AS last_commit")


@app.get("/repos/{repo_id}")
def get_repo(repo_id: str) -> dict:
    rows = run_query(
        "MATCH (r:Repository {repo_id: $repo_id}) RETURN r.repo_id AS repo_id, r.last_commit AS last_commit, r.name AS name",
        repo_id=repo_id,
    )
    if not rows:
        raise HTTPException(404, f"Repo {repo_id} not found")
    return rows[0]


# ------------------------------------------------------------------
# Context endpoints — used by MCP to inject pre-computed context
# ------------------------------------------------------------------

@app.get("/context/module/{module_id}")
def module_context(module_id: str) -> dict:
    """
    Return everything known about a logical module: its packages, classes,
    key methods, and any active architectural policies targeting it.
    Designed to be injected as context into a coding tool session.
    """
    classes = run_query(
        """
        MATCH (c:Class {module: $module_id})
        RETURN c.fqn AS fqn, c.name AS name, c.kind AS kind,
               c.file_path AS file_path, c.annotations AS annotations
        ORDER BY c.fqn
        """,
        module_id=module_id,
    )
    policies = run_query(
        """
        MATCH (ap:ArchPolicy)-[:TARGETS]->(mod:Module {module_id: $module_id})
        WHERE ap.status = 'active'
        RETURN ap.policy_id AS policy_id, ap.title AS title,
               ap.natural_language AS description, ap.severity AS severity
        """,
        module_id=module_id,
    )
    violations = run_query(
        """
        MATCH (c:Class {module: $module_id})-[:VIOLATES]->(ap:ArchPolicy)
        RETURN c.fqn AS violator, ap.policy_id AS policy_id, ap.title AS policy_title
        LIMIT 50
        """,
        module_id=module_id,
    )
    return {"module": module_id, "classes": classes, "policies": policies, "violations": violations}


@app.get("/context/class/{fqn:path}")
def class_context(fqn: str) -> dict:
    """
    Full object model snapshot for a class.
    Returns the pre-built object_model JSON if available (populated at scan time),
    otherwise falls back to live KG queries.
    """
    import json as _json
    row = run_query(
        "MATCH (c:Class {fqn: $fqn}) RETURN c.object_model AS om, c",
        fqn=fqn,
    )
    if not row:
        # Fuzzy fallback: match by simple class name (last segment of FQN)
        simple_name = fqn.split(".")[-1]
        row = run_query(
            "MATCH (c:Class {name: $name}) RETURN c.object_model AS om, c ORDER BY c.fqn LIMIT 1",
            name=simple_name,
        )
        if not row:
            raise HTTPException(404, f"Class {fqn} not found")

    # Fast path — pre-built snapshot exists
    if row[0].get("om"):
        try:
            snap = _json.loads(row[0]["om"])
            # Merge in live node properties not stored in the snapshot
            node = dict(row[0]["c"])
            if node.get("javadoc"):
                snap.setdefault("javadoc", node["javadoc"])
            if node.get("summary"):
                snap["summary"]       = node["summary"]
                snap["summary_model"] = node.get("summary_model")
                snap["summary_ts"]    = node.get("summary_ts")
            return snap
        except Exception:
            pass  # fall through to live queries

    # Fallback — build live (no object_model yet, e.g. before first scan completes)
    cls_node = dict(row[0]["c"])
    methods = run_query(
        "MATCH (c:Class {fqn: $fqn})-[:HAS_METHOD]->(m:Method) "
        "RETURN m.name AS name, m.return_type AS return_type, "
        "m.parameters AS parameters, m.modifiers AS modifiers, "
        "m.annotations AS annotations",
        fqn=fqn,
    )
    fields = run_query(
        "MATCH (c:Class {fqn: $fqn})-[:HAS_FIELD]->(f:Field) "
        "RETURN f.name AS name, f.type_name AS type, f.modifiers AS modifiers",
        fqn=fqn,
    )
    extends = run_query(
        "MATCH (c:Class {fqn: $fqn})-[:EXTENDS]->(p) RETURN p.name AS name",
        fqn=fqn,
    )
    implements = run_query(
        "MATCH (c:Class {fqn: $fqn})-[:IMPLEMENTS]->(i) RETURN i.name AS name",
        fqn=fqn,
    )
    dependents = run_query(
        "MATCH (caller:Class)-[:IMPORTS]->(c:Class {fqn: $fqn}) "
        "RETURN caller.name AS name LIMIT 10",
        fqn=fqn,
    )
    imports = run_query(
        "MATCH (c:Class {fqn: $fqn})-[:IMPORTS]->(imp:Class) "
        "RETURN imp.fqn AS fqn LIMIT 20",
        fqn=fqn,
    )
    patterns = run_query(
        "MATCH (c:Class {fqn: $fqn})-[:EXHIBITS]->(ap:ArchPattern) "
        "RETURN ap.name AS name, ap.anti_pattern AS anti",
        fqn=fqn,
    )
    return {
        "fqn":         cls_node.get("fqn"),
        "name":        cls_node.get("name"),
        "kind":        cls_node.get("kind"),
        "package":     cls_node.get("package_fqn"),
        "file_path":   cls_node.get("file_path"),
        "annotations": cls_node.get("annotations", []),
        "javadoc":     cls_node.get("javadoc"),
        "summary":     cls_node.get("summary"),
        "summary_model": cls_node.get("summary_model"),
        "summary_ts":  cls_node.get("summary_ts"),
        "superclass":  extends[0]["name"] if extends else None,
        "interfaces":  [r["name"] for r in implements],
        "methods":     methods,
        "fields":      fields,
        "imports":     [r["fqn"] for r in imports],
        "dependencies": [r["fqn"].split(".")[-1] for r in imports],
        "dependents":  [r["name"] for r in dependents],
        "patterns":    [{"name": r["name"], "anti": r["anti"]} for r in patterns],
        "method_count": len(methods),
        "object_model_built": False,
    }


@app.get("/context/feature")
def feature_context(classes: str = Query(..., description="Comma-separated FQNs")) -> dict:
    """
    Aggregate context for a set of classes (e.g. all classes involved in a feature).
    Returns a compact summary suitable for LLM context injection.
    """
    fqn_list = [f.strip() for f in classes.split(",")]
    result = []
    for fqn in fqn_list:
        try:
            result.append(class_context(fqn))
        except HTTPException:
            pass
    return {"feature_classes": result}


# ------------------------------------------------------------------
# Violation endpoints — used by CI/CD and code review
# ------------------------------------------------------------------

@app.get("/violations")
def list_violations(repo_id: Optional[str] = None, severity: Optional[str] = None) -> list[dict]:
    filters = []
    params: dict = {}
    if repo_id:
        filters.append("c.repo_id = $repo_id")
        params["repo_id"] = repo_id
    if severity:
        filters.append("ap.severity = $severity")
        params["severity"] = severity
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    return run_query(
        f"""
        MATCH (c)-[:VIOLATES]->(ap:ArchPolicy)
        {where}
        RETURN c.fqn AS violator, c.file_path AS file_path,
               ap.policy_id AS policy_id, ap.title AS policy_title,
               ap.severity AS severity
        ORDER BY ap.severity, c.fqn
        """,
        **params,
    )


@app.get("/violations/pr")
def pr_violations(files: str = Query(..., description="Comma-separated file paths changed in the PR")) -> list[dict]:
    """
    Given a list of files changed in a PR, return any architectural violations
    in those files. Designed to be called from a CI/CD pipeline.
    """
    file_list = [f.strip() for f in files.split(",")]
    return run_query(
        """
        MATCH (c)-[:VIOLATES]->(ap:ArchPolicy)
        WHERE c.file_path IN $files
        RETURN c.fqn AS violator, c.file_path AS file_path,
               ap.policy_id AS policy_id, ap.title AS policy_title,
               ap.severity AS severity
        ORDER BY ap.severity
        """,
        files=file_list,
    )


# ------------------------------------------------------------------
# Architecture policy endpoints
# ------------------------------------------------------------------

@app.get("/policies")
def list_policies(status: Optional[str] = "active") -> list[dict]:
    params: dict = {}
    where = ""
    if status:
        where = "WHERE ap.status = $status"
        params["status"] = status
    rows = run_query(f"MATCH (ap:ArchPolicy) {where} RETURN ap ORDER BY ap.title", **params)
    return [dict(r["ap"]) for r in rows]


@app.get("/policies/{policy_id}")
def get_policy(policy_id: str) -> dict:
    rows = run_query("MATCH (ap:ArchPolicy {policy_id: $pid}) RETURN ap", pid=policy_id)
    if not rows:
        raise HTTPException(404, f"Policy {policy_id} not found")
    return dict(rows[0]["ap"])


# ------------------------------------------------------------------
# Search
# ------------------------------------------------------------------

@app.get("/search/class")
def search_class(q: str, repo_id: Optional[str] = None, limit: int = 20) -> list[dict]:
    """
    Search classes by name (case-insensitive substring).
    Returns object_model snapshots when available, otherwise basic class info.
    """
    import json as _json
    params: dict = {"q": f"(?i).*{q}.*", "limit": limit}
    extra = "AND c.repo_id = $repo_id" if repo_id else ""
    if repo_id:
        params["repo_id"] = repo_id
    rows = run_query(
        f"""
        MATCH (c:Class)
        WHERE c.name =~ $q {extra}
        RETURN c.fqn AS fqn, c.name AS name, c.kind AS kind,
               c.package_fqn AS package_fqn, c.repo_id AS repo_id,
               c.object_model AS om
        ORDER BY c.name
        LIMIT $limit
        """,
        **params,
    )
    results = []
    for r in rows:
        if r.get("om"):
            try:
                results.append(_json.loads(r["om"]))
                continue
            except ValueError:
                pass
        results.append({
            "fqn":      r["fqn"],
            "name":     r["name"],
            "kind":     r["kind"],
            "package":  r["package_fqn"],
            "repo_id":  r["repo_id"],
            "object_model_built": False,
        })
    return results


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/llm/providers")
def llm_providers() -> dict:
    """List known LLM provider names."""
    from shared.llm import llm as _llm
    return {"providers": _llm.provider_names()}


@app.get("/llm/models/{provider}")
def llm_models(provider: str) -> JSONResponse:
    """
    List models available from the given provider.
    Queries the provider live — returns the real model list.
    Returns {models: [...]} on success or {error: "..."} when not configured.
    """
    from shared.llm import llm as _llm
    try:
        models = _llm.list_models(provider)
        return {"provider": provider, "models": models}
    except RuntimeError as exc:
        return JSONResponse({"provider": provider, "models": [], "error": str(exc)}, status_code=200)
    except Exception as exc:
        return JSONResponse({"provider": provider, "models": [], "error": str(exc)}, status_code=200)


@app.get("/patterns")
def get_patterns(repo_id: Optional[str] = None) -> list[dict]:
    scope = "AND ap.repo_id = $repo_id" if repo_id else ""
    rows = run_query(f"""
        MATCH (ap:ArchPattern) WHERE 1=1 {scope}
        RETURN ap
        ORDER BY ap.anti_pattern DESC, ap.severity, ap.match_count DESC
    """, repo_id=repo_id)
    import json as _json
    results = []
    for row in rows:
        ap = dict(row["ap"])
        top_packages = ap.get("top_packages", "[]")
        if isinstance(top_packages, str):
            try:
                top_packages = _json.loads(top_packages)
            except ValueError:
                top_packages = []
        results.append({
            "id": ap.get("pattern_id"),
            "name": ap.get("name"),
            "source": ap.get("source"),
            "category": ap.get("category"),
            "intent": ap.get("intent"),
            "anti_pattern": ap.get("anti_pattern", False),
            "severity": ap.get("severity", "info"),
            "match_count": ap.get("match_count", 0),
            "repo_id": ap.get("repo_id"),
            "top_packages": top_packages,
        })
    return results


# ------------------------------------------------------------------
# Change Impact Engine
# ------------------------------------------------------------------

@app.get("/impact/files")
def impact_files(
    files: str = Query(..., description="Comma-separated file paths"),
    repo_id: str = Query(..., description="Repository ID"),
    commit_sha: Optional[str] = None,
) -> dict:
    """
    Compute blast radius for a set of changed files.
    Returns: directly affected classes, callers, transitive dependents,
    affected modules, exposed endpoints, relevant policies, suggested tests,
    and a heuristic risk score.
    """
    from impact.engine import ImpactEngine
    file_list = [f.strip() for f in files.split(",") if f.strip()]
    engine = ImpactEngine(driver)
    report = engine.compute(repo_id=repo_id, changed_files=file_list, commit_sha=commit_sha)
    return report.to_dict()


@app.get("/impact/pr")
def impact_pr(
    files: str = Query(..., description="Comma-separated file paths changed in the PR"),
    repo_id: str = Query(..., description="Repository ID"),
    commit_sha: Optional[str] = None,
) -> dict:
    """
    CI/CD-friendly endpoint: given files changed in a PR, return the full
    impact report. Identical to /impact/files but named for PR context.
    """
    return impact_files(files=files, repo_id=repo_id, commit_sha=commit_sha)


@app.get("/impact/commit")
def impact_commit(
    repo_id: str,
    from_sha: str = Query(..., description="Base commit SHA"),
    to_sha: str = Query(..., description="Head commit SHA"),
) -> dict:
    """
    Compute impact for all files changed between two commits.
    Requires the repo to be accessible at the path stored in the KG.
    """
    import git
    from impact.engine import ImpactEngine

    rows = run_query(
        "MATCH (r:Repository {repo_id: $rid}) RETURN r.path AS path",
        rid=repo_id,
    )
    if not rows or not rows[0].get("path"):
        raise HTTPException(404, f"Repo {repo_id} not found or has no path")

    try:
        repo = git.Repo(rows[0]["path"])
        diff = repo.commit(from_sha).diff(to_sha)
        changed_files = []
        for d in diff:
            p = d.b_path or d.a_path
            if p:
                changed_files.append(str(rows[0]["path"]) + "/" + p)
    except Exception as exc:
        raise HTTPException(400, f"Could not compute diff: {exc}")

    engine = ImpactEngine(driver)
    report = engine.compute(repo_id=repo_id, changed_files=changed_files, commit_sha=to_sha)
    return report.to_dict()


# ------------------------------------------------------------------
# Freshness / provenance endpoint
# ------------------------------------------------------------------

@app.get("/provenance/{repo_id:path}")
def repo_provenance(repo_id: str) -> dict:
    """Return provenance summary: how fresh is the KG for this repo?"""
    rows = run_query(
        """
        MATCH (r:Repository {repo_id: $rid})
        RETURN r.last_commit AS last_commit,
               r.prov_freshness_ts AS freshness_ts,
               r.prov_commit_sha AS prov_commit_sha
        """,
        rid=repo_id,
    )
    if not rows:
        raise HTTPException(404, f"Repo {repo_id} not found")
    stale_nodes = run_query(
        """
        MATCH (c:Class {repo_id: $rid})
        WHERE c.prov_commit_sha <> $commit OR c.prov_commit_sha IS NULL
        RETURN count(c) AS stale_count
        """,
        rid=repo_id,
        commit=rows[0].get("last_commit", ""),
    )
    return {
        **rows[0],
        "stale_node_count": stale_nodes[0]["stale_count"] if stale_nodes else 0,
    }


# ------------------------------------------------------------------
# Codebase Intelligence Template renderer
# ------------------------------------------------------------------

@app.get("/template/{repo_id:path}", response_class=PlainTextResponse)
def get_template(repo_id: str) -> PlainTextResponse:
    """
    Render a filled-out Codebase Intelligence Template for the given repo.
    Returns Markdown — designed to be injected as LLM session context or
    saved as a living document alongside the codebase.
    """
    from renderers.template_renderer import render_template
    rows = run_query(
        "MATCH (r:Repository {repo_id: $rid}) RETURN r.repo_id AS repo_id",
        rid=repo_id,
    )
    if not rows:
        raise HTTPException(404, f"Repo {repo_id} not found")
    return render_template(driver, repo_id)


# ------------------------------------------------------------------
# Insights (formerly "tribal knowledge" — node label TribalKnowledge preserved in Neo4j)
# ------------------------------------------------------------------

@app.post("/insights")
def store_insights(body: dict) -> dict:
    """
    Store insight entries from a Claude Code session.
    Body: {entries: [{tk_id, insight, scope, applies_to, confidence, repo_id}],
           session_id, commit_sha}
    """
    import datetime
    entries    = body.get("entries", [])
    session_id = body.get("session_id", "unknown")
    commit_sha = body.get("commit_sha", "unknown")
    if not entries:
        return {"stored": 0}
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    # Ensure schema exists
    with driver.session() as s:
        s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (tk:TribalKnowledge) REQUIRE tk.tk_id IS UNIQUE")
        s.run("CREATE INDEX IF NOT EXISTS FOR (tk:TribalKnowledge) ON (tk.applies_to)")
        s.run("CREATE INDEX IF NOT EXISTS FOR (tk:TribalKnowledge) ON (tk.staleness)")
    with driver.session() as s:
        for e in entries:
            s.run(
                """
                MERGE (tk:TribalKnowledge {tk_id: $tk_id})
                SET tk.insight             = $insight,
                    tk.scope               = $scope,
                    tk.applies_to          = $applies_to,
                    tk.confidence          = $confidence,
                    tk.importance          = CASE WHEN $importance IS NOT NULL THEN $importance ELSE coalesce(tk.importance, 50) END,
                    tk.technical_debt      = CASE WHEN $technical_debt IS NOT NULL THEN $technical_debt ELSE coalesce(tk.technical_debt, null) END,
                    tk.staleness           = coalesce(tk.staleness, 0.0),
                    tk.approved            = coalesce(tk.approved, false),
                    tk.repo_id             = $repo_id,
                    tk.session_id          = $session_id,
                    tk.saved_at            = $ts,
                    tk.last_touched_commit = $commit_sha
                WITH tk
                OPTIONAL MATCH (target {fqn: $applies_to})
                FOREACH (_ IN CASE WHEN target IS NOT NULL THEN [1] ELSE [] END |
                    MERGE (tk)-[:APPLIES_TO]->(target)
                )
                """,
                tk_id=e["tk_id"],
                insight=e["insight"],
                scope=e.get("scope", "class"),
                applies_to=e["applies_to"],
                confidence=float(e.get("confidence", 0.7)),
                importance=e.get("importance"),
                technical_debt=e.get("technical_debt"),
                repo_id=e.get("repo_id", ""),
                session_id=session_id,
                ts=ts,
                commit_sha=commit_sha,
            )
    return {"stored": len(entries)}


@app.get("/insights")
def get_insights(applies_to: str, min_confidence: float = 0.5, max_staleness: float = 0.6) -> list[dict]:
    """
    Fetch insights relevant to a given FQN or file path.
    Returns entries ordered by confidence desc.
    """
    rows = run_query(
        """
        MATCH (tk:TribalKnowledge)
        WHERE (tk.applies_to = $fqn OR tk.applies_to STARTS WITH $fqn)
          AND tk.confidence  >= $min_conf
          AND tk.staleness   <= $max_stale
        RETURN tk
        ORDER BY tk.confidence DESC
        LIMIT 10
        """,
        fqn=applies_to,
        min_conf=min_confidence,
        max_stale=max_staleness,
    )
    return [dict(r["tk"]) for r in rows]


@app.get("/insights/for-classes")
def get_insights_for_classes(fqns: str, min_confidence: float = 0.5, max_staleness: float = 0.6) -> list[dict]:
    """
    Fetch insights for a comma-separated list of FQNs.
    Used by answer_question to enrich responses.
    """
    fqn_list = [f.strip() for f in fqns.split(",") if f.strip()]
    if not fqn_list:
        return []
    rows = run_query(
        """
        MATCH (tk:TribalKnowledge)
        WHERE tk.applies_to IN $fqns
          AND tk.confidence  >= $min_conf
          AND tk.staleness   <= $max_stale
        RETURN tk
        ORDER BY tk.confidence DESC
        LIMIT 20
        """,
        fqns=fqn_list,
        min_conf=min_confidence,
        max_stale=max_staleness,
    )
    return [dict(r["tk"]) for r in rows]


@app.post("/insights/update-staleness")
def update_insight_staleness(body: dict) -> dict:
    """Called by the watcher after a commit lands to age affected insights."""
    changed_files = body.get("changed_files", [])
    commit_sha    = body.get("commit_sha", "unknown")
    if not changed_files:
        return {"updated": 0}
    with driver.session() as s:
        s.run(
            """
            MATCH (tk:TribalKnowledge)-[:APPLIES_TO]->(target)
            WHERE target.file_path IN $files
            SET tk.staleness = CASE
                WHEN tk.staleness + 0.2 >= 1.0 THEN 1.0
                ELSE tk.staleness + 0.2
            END,
            tk.last_touched_commit = $commit_sha
            """,
            files=changed_files, commit_sha=commit_sha,
        )
        s.run(
            """
            MATCH (tk:TribalKnowledge)
            WHERE tk.applies_to IN $files AND tk.staleness < 1.0
            SET tk.staleness = CASE
                WHEN tk.staleness + 0.2 >= 1.0 THEN 1.0
                ELSE tk.staleness + 0.2
            END,
            tk.last_touched_commit = $commit_sha
            """,
            files=changed_files, commit_sha=commit_sha,
        )
    return {"updated": len(changed_files)}


@app.get("/insights/all")
def list_insights(repo_id: Optional[str] = None, include_hidden: bool = False, pending_only: bool = False) -> list[dict]:
    """List all Insight nodes grouped by scope, ordered system→module→class→method."""
    extra = "AND tk.repo_id = $repo_id" if repo_id else ""
    hidden_filter = "" if include_hidden else "AND coalesce(tk.hidden, false) = false"
    pending_filter = "AND coalesce(tk.approved, false) = false" if pending_only else ""
    rows = run_query(
        f"""
        MATCH (tk:TribalKnowledge)
        WHERE 1=1 {extra} {hidden_filter} {pending_filter}
        RETURN tk
        ORDER BY tk.scope, tk.applies_to, tk.confidence DESC
        """,
        repo_id=repo_id or "",
    )
    return [dict(r["tk"]) for r in rows]


@app.patch("/insights/{tk_id}")
def update_insight(tk_id: str, body: dict) -> dict:
    """Update editable fields of an Insight node: insight, confidence, hidden, approved, importance."""
    EDITABLE = {"insight", "technical_debt", "confidence", "hidden", "approved", "importance"}
    sets = []
    params: dict = {"tk_id": tk_id}
    for key, val in body.items():
        if key in EDITABLE:
            sets.append(f"tk.{key} = ${key}")
            params[key] = val
    if not sets:
        raise HTTPException(400, "No editable fields provided")
    run_query(
        f"MATCH (tk:TribalKnowledge {{tk_id: $tk_id}}) SET {', '.join(sets)}",
        **params,
    )
    return {"ok": True, "tk_id": tk_id}


@app.delete("/insights/{tk_id}")
def delete_insight(tk_id: str) -> dict:
    """Permanently delete an Insight node."""
    run_query(
        "MATCH (tk:TribalKnowledge {tk_id: $tk_id}) DETACH DELETE tk",
        tk_id=tk_id,
    )
    return {"ok": True, "tk_id": tk_id}


@app.post("/insights/analyse")
def analyse_insights(body: dict) -> dict:
    """
    Analyse all TribalKnowledge entries for a repo using Claude Haiku.
    Returns structured findings: conflicts, redundancies, uplift candidates,
    and rewrite suggestions.

    Body: {repo_id: str, model?: str}
    Returns: {findings: [...], entry_count: int}

    Each finding:
      type: "conflict" | "redundant" | "uplift" | "rewrite"
      title: str
      description: str
      affected_ids: [tk_id, ...]
      suggested_scope: str | null      (for uplift)
      suggested_applies_to: str | null (for uplift)
      suggested_insight: str | null    (for rewrite/merge)
      confidence: float
    """
    import json as _json
    from shared.llm import llm as _llm

    repo_id = body.get("repo_id", "")
    model   = body.get("model", cfg.llm.nl_query_model)

    # Load all non-hidden entries for the repo
    extra = "AND tk.repo_id = $repo_id" if repo_id else ""
    rows = run_query(
        f"""
        MATCH (tk:TribalKnowledge)
        WHERE coalesce(tk.hidden, false) = false {extra}
        RETURN tk
        ORDER BY tk.scope, tk.applies_to, tk.confidence DESC
        """,
        repo_id=repo_id or "",
    )
    entries = [dict(r["tk"]) for r in rows]
    if not entries:
        return {"findings": [], "entry_count": 0}

    # Build a compact numbered list for the prompt
    entry_lines = []
    for i, e in enumerate(entries):
        line = (
            f"[{i}] tk_id={e['tk_id']} scope={e['scope']} "
            f"applies_to={e['applies_to']} confidence={e.get('confidence',0.7):.2f}\n"
            f"    {e['insight']}"
        )
        entry_lines.append(line)

    entries_text = "\n\n".join(entry_lines)

    prompt = f"""You are reviewing a list of insights captured by AI coding agents about the codebase.

Your job is to find quality issues across these entries. Look for:

1. **CONFLICT** — two entries that directly contradict each other (e.g. one says X is true, another says X is false). Only flag genuine logical contradictions, not just different aspects of the same topic.

2. **REDUNDANT** — two or more entries that say essentially the same thing at the same or different scopes. Identify the best one to keep and which to retire.

3. **UPLIFT** — an insight that is stated at a narrow scope (class/method) but actually applies at a broader scope (module/system). Suggest the broader scope and applies_to value.

4. **REWRITE** — an insight that is now stale (the text says "was broken", "before the fix", "prior to", "old behaviour") or that contains outdated phrasing that should be updated to present tense. Suggest a rewritten version.

Here are the {len(entries)} entries (numbered for reference):

{entries_text}

Respond with a JSON array of findings. Each finding must have these exact keys:
  "type": one of "conflict", "redundant", "uplift", "rewrite"
  "title": short label (max 8 words)
  "description": explanation of the issue (1-3 sentences)
  "affected_ids": array of tk_id strings from the list above
  "suggested_scope": new scope string for uplift findings, else null
  "suggested_applies_to": new applies_to FQN for uplift findings, else null
  "suggested_insight": merged/rewritten insight text for rewrite/redundant findings, else null
  "confidence": float 0.0-1.0 how certain you are this is a real issue

Only report genuine issues. It is better to return 0 findings than to fabricate ones. Do not report issues where entries are just complementary facts about the same thing.

Return only the JSON array, no preamble."""

    message = _llm.chat(model=model, prompt=prompt, max_tokens=cfg.llm.summarise_max_tokens)
    raw = message.text.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0].strip()

    try:
        findings = _json.loads(raw)
    except _json.JSONDecodeError:
        # Try to extract a JSON array from the text
        import re as _re
        m = _re.search(r'\[.*\]', raw, _re.DOTALL)
        findings = _json.loads(m.group(0)) if m else []

    return {
        "findings":    findings,
        "entry_count": len(entries),
        "model":       model,
        "tokens_in":   message.usage.input_tokens,
        "tokens_out":  message.usage.output_tokens,
    }


@app.post("/insights/apply-finding")
def apply_insight_finding(body: dict) -> dict:
    """
    Apply a single finding from the analysis:
      - uplift: update scope + applies_to on affected entries
      - rewrite/redundant: update insight on first entry, hide the rest
      - conflict: hide lower-confidence entry

    Body: {finding: {...}, action: "apply"|"dismiss"}
    """
    import datetime as _dt

    finding = body.get("finding", {})
    action  = body.get("action", "apply")
    if action != "apply":
        return {"ok": True, "action": "dismissed"}

    ftype        = finding.get("type")
    affected_ids = finding.get("affected_ids", [])
    if not affected_ids:
        return {"ok": False, "error": "no affected_ids"}

    ts = _dt.datetime.now(_dt.timezone.utc).isoformat()

    with driver.session() as s:
        if ftype == "uplift":
            new_scope      = finding.get("suggested_scope")
            new_applies_to = finding.get("suggested_applies_to")
            if new_scope and new_applies_to:
                for tk_id in affected_ids:
                    s.run(
                        "MATCH (tk:TribalKnowledge {tk_id: $id}) "
                        "SET tk.scope = $scope, tk.applies_to = $at, tk.saved_at = $ts",
                        id=tk_id, scope=new_scope, at=new_applies_to, ts=ts,
                    )

        elif ftype in ("rewrite", "redundant"):
            new_insight = finding.get("suggested_insight")
            if new_insight and affected_ids:
                # Rewrite the first (highest-confidence) entry
                s.run(
                    "MATCH (tk:TribalKnowledge {tk_id: $id}) SET tk.insight = $insight, tk.saved_at = $ts",
                    id=affected_ids[0], insight=new_insight, ts=ts,
                )
            # Hide the duplicates (all but the first for redundant)
            to_hide = affected_ids[1:] if ftype == "redundant" else []
            for tk_id in to_hide:
                s.run(
                    "MATCH (tk:TribalKnowledge {tk_id: $id}) SET tk.hidden = true",
                    id=tk_id,
                )

        elif ftype == "conflict":
            # Load both, hide the lower-confidence one
            if len(affected_ids) >= 2:
                rows = run_query(
                    "MATCH (tk:TribalKnowledge) WHERE tk.tk_id IN $ids "
                    "RETURN tk.tk_id AS id, tk.confidence AS conf ORDER BY conf ASC",
                    ids=affected_ids,
                )
                if rows:
                    s.run(
                        "MATCH (tk:TribalKnowledge {tk_id: $id}) SET tk.hidden = true",
                        id=rows[0]["id"],
                    )

    return {"ok": True, "type": ftype, "affected": affected_ids}


# ------------------------------------------------------------------
# Natural-language answer
# ------------------------------------------------------------------

from pydantic import BaseModel as _BaseModel

class _AnswerRequest(_BaseModel):
    """Validates the payload for natural-language answer generation. Watch out for optional repo scoping here, because the same endpoint supports both global and repository-specific questions."""

    question: str
    repo_id: str | None = None

@app.post("/answer")
def answer_question(body: _AnswerRequest) -> dict:
    from nl_query import ask
    result = ask(question=body.question, driver=driver, repo_id=body.repo_id)
    result.pop("request", None)
    return result


# ------------------------------------------------------------------
# Agent Index — regen + publish
# ------------------------------------------------------------------

REPOS_REGISTRY = cfg.paths.repos_registry

def _load_registry() -> dict:
    import json as _json
    try:
        with open(REPOS_REGISTRY) as f:
            return _json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("Failed to load repos registry", path=REPOS_REGISTRY, exc=e)
        return {}


def _init_agent_index() -> None:
    """Wire up run_query into the generator and initialise the DB."""
    from agent_index import generator as _gen, store as _store
    _gen.run_query = run_query
    _store.init_db()

_init_agent_index()


def _ai_regen_file(repo_id: str, file_key: str) -> dict:
    from agent_index import generator as gen, store
    entry = next((f for f in gen.FILE_REGISTRY if f["key"] == file_key), None)
    if entry:
        try:
            if entry["key"] == "index":
                files = store.list_files(repo_id)
                content = gen.generate_index(repo_id, files)
            elif entry["key"] == "architecture/datastores":
                repo_path = (_load_registry().get(repo_id) or "")
                content = gen.generate_datastores_index(repo_id, repo_path)
            elif entry["key"] == "architecture/screens":
                repo_path = (_load_registry().get(repo_id) or "")
                content = gen.generate_screens_index(repo_id, repo_path)
            elif entry["key"] == "architecture/recent_changes":
                repo_path = (_load_registry().get(repo_id) or "")
                content = gen.generate_recent_changes(repo_id, repo_path)
            elif entry["key"] == "claude_md":
                visible = {f["file_key"] for f in store.list_files(repo_id) if not f.get("hidden")}
                content = gen.generate_claude_md_snippet(repo_id, visible_keys=visible)
            elif entry["key"] == "agents_md":
                visible = {f["file_key"] for f in store.list_files(repo_id) if not f.get("hidden")}
                content = gen.generate_agents_md_snippet(repo_id, visible_keys=visible)
            else:
                content = entry["generator"](repo_id)
            store.upsert_file(
                repo_id=repo_id, file_key=entry["key"],
                directory=entry["directory"], filename=entry["filename"],
                description=entry["description"], content=content,
                trigger=entry["trigger"],
            )
            return {"ok": True, "content": content}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    if file_key.startswith("modules/"):
        module_id = file_key[len("modules/"):]
        safe = module_id.replace("/", "--")
        try:
            content = gen.generate_module_file(repo_id, module_id)
            store.upsert_file(repo_id=repo_id, file_key=file_key, directory="modules",
                              filename=f"{safe}.md",
                              description=f"Classes and structure for module `{module_id}`",
                              content=content, trigger="scan_complete",
                              table="agent_index_module_files")
            return {"ok": True, "content": content}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    if file_key.startswith("insights/module/"):
        module_id = file_key[len("insights/module/"):]
        safe = module_id.replace("/", "--")
        try:
            content = gen.generate_insights_module(repo_id, module_id)
            store.upsert_file(repo_id=repo_id, file_key=file_key, directory="insights",
                              filename=f"{safe}.md",
                              description=f"Captured insights for module `{module_id}`",
                              content=content, trigger="insight_added",
                              table="agent_index_module_files")
            return {"ok": True, "content": content}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return {"ok": False, "error": f"Unknown file key: {file_key}"}


_EMPTY_PHRASES = (
    "_No ", "not found", "No insights recorded", "No violations detected",
    "No active policies", "No significant hotspots",
)

def _content_is_empty(content: str) -> bool:
    """True if a generated file has no meaningful data beyond its header."""
    if not content:
        return True
    # Strip header lines (# title, _Generated ..., blank lines)
    body_lines = [ln for ln in content.splitlines()
                  if ln.strip() and not ln.startswith("#") and not ln.startswith("_Generated")]
    body = "\n".join(body_lines).strip()
    if len(body) < 80:
        return True
    # Only check the first 200 chars for empty-file sentinel phrases — not the full
    # content, since real insight text can contain words like "not found"
    return any(phrase in body[:200] for phrase in _EMPTY_PHRASES)


def _ai_regen_all(repo_id: str) -> dict:
    from agent_index import generator as gen, store
    results = {}
    for entry in gen.FILE_REGISTRY:
        if entry["key"] == "index":
            continue
        results[entry["key"]] = _ai_regen_file(repo_id, entry["key"])

    modules = run_query("MATCH (m:Module {repo_id: $repo_id}) RETURN m.module_id AS id",
                        repo_id=repo_id)
    for m in modules:
        mid = m["id"]
        results[f"modules/{mid}"] = _ai_regen_file(repo_id, f"modules/{mid}")

    # Auto-hide empty files; auto-unhide files that now have content
    for file_key, result in results.items():
        if not result.get("ok"):
            continue
        content = result.get("content") or ""
        table = "agent_index_module_files" if (
            file_key.startswith("modules/") or file_key.startswith("insights/module/")
        ) else "agent_index_files"
        if _content_is_empty(content):
            store.toggle_hidden(repo_id, file_key, hidden=True, table=table)
            result["empty"] = True
        else:
            store.toggle_hidden(repo_id, file_key, hidden=False, table=table)

    # Index last — only references non-hidden files
    # Pull recent commits for the index recent-changes section
    import subprocess as _sp2
    repo_path_for_git = _load_registry().get(repo_id, "")
    recent_commits: list[dict] = []
    if repo_path_for_git:
        try:
            r = _sp2.run(
                ["git", "-C", repo_path_for_git, "log",
                 "--pretty=format:%H|%ad|%an|%s", "--date=short", "-20"],
                capture_output=True, text=True, timeout=10,
            )
            for line in r.stdout.strip().splitlines():
                parts = line.split("|", 3)
                if len(parts) == 4:
                    recent_commits.append({
                        "sha": parts[0][:8], "date": parts[1],
                        "author": parts[2], "message": parts[3],
                    })
        except (OSError, _sp2.SubprocessError) as e:
            log.warning("Failed to read git log for agent index", repo_id=repo_id, exc=e)

    files = [f for f in store.list_files(repo_id) if not f.get("hidden")]
    index_content = gen.generate_index(repo_id, files, recent_commits=recent_commits)
    store.upsert_file(repo_id=repo_id, file_key="index", directory="",
                      filename="INDEX.md", description="Master navigation file — read first",
                      content=index_content, trigger="any_change")
    results["index"] = {"ok": True, "content": index_content}
    return results


import re as _re_refs

# Matches any .codekg/ path token inside content — backtick, paren, plain text.
# Captures the part after .codekg/ so we can look it up in the bundle.
_CODEKG_REF_RE = _re_refs.compile(r'\.codekg/([^\s`\)\]\'",]+)')


def _validate_index_refs(visible: list[dict]) -> list[tuple[str, str]]:
    """
    Scan every file in the publish bundle for .codekg/ path references.
    Returns a list of (source_file_key, referenced_path) pairs where the
    referenced path is NOT present in the bundle.

    Only flags references that look like index file paths (contain a dot,
    end with .md, or are a known directory prefix) — ignores incidental
    mentions of .codekg/ as a directory name.
    """
    # Build the set of .codekg/-relative paths that will actually exist on disk.
    # Each visible file produces one path: "<directory>/<filename>" or "<filename>".
    bundle_paths: set[str] = set()
    for f in visible:
        if f["file_key"] in ("claude_md", "agents_md"):
            # these write to repo root or .codekg/ root — not into a subdirectory
            continue
        directory = (f.get("directory") or "").strip("/")
        filename  = f["filename"]
        rel = f"{directory}/{filename}" if directory else filename
        bundle_paths.add(rel)

    dangling: list[tuple[str, str]] = []
    for f in visible:
        content    = (f.get("content") or "") + (f.get("manual_additions") or "")
        source_key = f["file_key"]
        for m in _CODEKG_REF_RE.finditer(content):
            ref = m.group(1).rstrip(".")  # strip trailing punctuation
            # Only validate paths that look like index files (have an extension
            # or match a known subdir prefix) — skip bare directory mentions.
            if "." not in ref and "/" not in ref:
                continue
            # Skip intentional placeholder tokens like modules/<name>.md
            if "<" in ref or ">" in ref:
                continue
            if ref not in bundle_paths:
                dangling.append((source_key, ref))

    # Deduplicate — same dangling ref may appear many times in one file
    seen: set[tuple[str, str]] = set()
    result = []
    for item in dangling:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _ai_publish(repo_id: str, repo_path: str) -> dict:
    import subprocess
    from pathlib import Path
    from agent_index import generator as gen, store
    from agent_index.generator import apply_claude_md_section

    # Inject current HEAD SHA into the generator so all files embed it in their headers
    try:
        _head = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        gen._current_publish_sha = _head or "unpublished"
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("Failed to resolve HEAD SHA for publish", repo_id=repo_id, exc=e)
        gen._current_publish_sha = "unpublished"

    files = store.list_files(repo_id)
    visible = [f for f in files if not f.get("hidden")]
    if not visible:
        return {"ok": False, "error": "No visible files to publish"}

    codekg_dir = Path(repo_path) / ".codekg"
    codekg_dir.mkdir(exist_ok=True)

    written = []
    for f in visible:
        content = f.get("content") or ""
        manual  = (f.get("manual_additions") or "").strip()
        if manual:
            content = content.rstrip() + "\n\n---\n## Additional notes\n\n" + manual

        if f["file_key"] in ("claude_md", "agents_md"):
            # claude_md → CLAUDE.md, agents_md → AGENTS.md
            target_name = "CLAUDE.md" if f["file_key"] == "claude_md" else "AGENTS.md"
            root_file = Path(repo_path) / target_name
            if root_file.exists():
                existing = root_file.read_text(encoding="utf-8")
                merged = apply_claude_md_section(existing, content)
                root_file.write_text(merged, encoding="utf-8")
                written.append(target_name)
            else:
                dest = codekg_dir / target_name
                dest.write_text(content, encoding="utf-8")
                written.append(f".codekg/{target_name}")
            continue

        directory = f.get("directory") or ""
        if directory:
            (codekg_dir / directory).mkdir(parents=True, exist_ok=True)
            dest = codekg_dir / directory / f["filename"]
        else:
            dest = codekg_dir / f["filename"]
        dest.write_text(content, encoding="utf-8")
        written.append(str(dest.relative_to(repo_path)))

    # Build set of paths that should exist on disk (visible files only)
    expected_paths: set[Path] = set()
    for f in visible:
        if f["file_key"] in ("claude_md", "agents_md"):
            # Written to repo root or .codekg/ root — not inside a subdirectory to track
            target_name = "CLAUDE.md" if f["file_key"] == "claude_md" else "AGENTS.md"
            expected_paths.add(codekg_dir / target_name)
            continue
        directory = f.get("directory") or ""
        expected_paths.add(
            (codekg_dir / directory / f["filename"]) if directory else (codekg_dir / f["filename"])
        )

    # Delete any .codekg/ file not in the expected set — covers hidden files AND
    # files removed from the store entirely (e.g. old per-module insight files)
    deleted = []
    for existing_file in codekg_dir.rglob("*"):
        if not existing_file.is_file():
            continue
        if existing_file not in expected_paths:
            existing_file.unlink()
            deleted.append(str(existing_file.relative_to(repo_path)))

    # ── Validate: check that every .codekg/ path referenced in any file
    # actually exists in the bundle being published. Dangling references waste
    # Claude Code context on files that don't exist.
    dangling_refs = _validate_index_refs(visible)

    try:
        subprocess.run(["git", "-C", repo_path, "add", "-f", ".codekg/"], check=True, capture_output=True, text=True)
        result = subprocess.run(
            ["git", "-C", repo_path, "commit",
             "-m", "chore: update CodeKG agent index [skip ci]", "--allow-empty"],
            check=True, capture_output=True, text=True,
        )
        sha = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()

        # Patch the commit SHA into the files that embed it — they were written
        # before the commit so they contained "unpublished" as a placeholder.
        for _fname in ("INDEX.md", "architecture/recent_changes.md"):
            _fpath = codekg_dir / _fname
            if _fpath.exists():
                _txt = _fpath.read_text(encoding="utf-8")
                _patched = _txt.replace("`unpublished`", f"`{sha}`", 1)
                if _patched != _txt:
                    _fpath.write_text(_patched, encoding="utf-8")
        # Amend the commit to include the patched SHA references
        subprocess.run(
            ["git", "-C", repo_path, "add", "-f", ".codekg/INDEX.md",
             ".codekg/architecture/recent_changes.md"],
            capture_output=True, text=True,
        )
        subprocess.run(
            ["git", "-C", repo_path, "commit", "--amend", "--no-edit"],
            capture_output=True, text=True,
        )
        # Re-read SHA after amend
        sha = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()

        store.mark_published(repo_id, sha)
        result_payload = {"ok": True, "files_written": len(written), "files_deleted": len(deleted),
                          "sha": sha, "commit_output": result.stdout.strip()}
        if dangling_refs:
            result_payload["warnings"] = [
                f"Dangling reference in '{src}': `.codekg/{ref}` is not in the published bundle"
                for src, ref in dangling_refs
            ]
        return result_payload
    except subprocess.CalledProcessError as e:
        stderr = e.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return {"ok": False, "error": stderr or str(e)}


class _RegenRequest(_BaseModel):
    """Validates requests to regenerate derived content. Watch out for identifier fields here, because regeneration targets existing stored artifacts rather than raw source files."""

    repo_id: str
    file_key: str = ""

@app.post("/agent-index/regen")
def ai_regen(body: _RegenRequest) -> dict:
    if not body.repo_id:
        raise HTTPException(400, "repo_id required")
    if body.file_key:
        result = _ai_regen_file(body.repo_id, body.file_key)
        if not result["ok"]:
            raise HTTPException(500, result.get("error"))
        return {"ok": True, "chars": len(result.get("content") or "")}
    results = _ai_regen_all(body.repo_id)
    ok_count  = sum(1 for r in results.values() if r.get("ok"))
    err_count = sum(1 for r in results.values() if not r.get("ok"))
    return {"ok": True, "generated": ok_count, "errors": err_count,
            "detail": {k: ("ok" if v.get("ok") else v.get("error")) for k, v in results.items()}}


class _PublishRequest(_BaseModel):
    """Validates requests that publish reviewed agent-index content. Watch out for versioning assumptions here, because publishing mutates state that other services may already be reading."""

    repo_id: str

@app.post("/agent-index/publish")
def ai_publish(body: _PublishRequest) -> dict:
    if not body.repo_id:
        raise HTTPException(400, "repo_id required")
    registry = _load_registry()
    repo_path = registry.get(body.repo_id)
    if not repo_path:
        raise HTTPException(404, f"Repo {body.repo_id} not found in registry")
    result = _ai_publish(body.repo_id, repo_path)
    if not result["ok"]:
        raise HTTPException(500, result.get("error"))
    return result


# ------------------------------------------------------------------
# Telemetry DB
# ------------------------------------------------------------------

import sqlite3 as _sq
import threading as _threading
from datetime import datetime, timezone

_TELEMETRY_DB   = cfg.paths.telemetry_db
_telemetry_lock = _threading.Lock()
_telemetry_con: _sq.Connection | None = None


def _init_telemetry_db() -> _sq.Connection | None:
    try:
        con = _sq.connect(_TELEMETRY_DB, check_same_thread=False, timeout=10)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id   TEXT PRIMARY KEY,
                started_at   TEXT NOT NULL,
                last_seen    TEXT NOT NULL,
                client       TEXT,
                cwd          TEXT
            );
            CREATE TABLE IF NOT EXISTS turns (
                turn_id              TEXT PRIMARY KEY,
                session_id           TEXT NOT NULL,
                ts                   TEXT NOT NULL,
                user_prompt          TEXT,
                insights_raw         TEXT,
                input_tokens         INTEGER DEFAULT 0,
                output_tokens        INTEGER DEFAULT 0,
                cache_read_tokens    INTEGER DEFAULT 0,
                cache_creation_tokens INTEGER DEFAULT 0,
                cache_creation_1h_tokens INTEGER DEFAULT 0,
                cache_creation_5m_tokens INTEGER DEFAULT 0,
                tool_call_count      INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS tool_calls (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                turn_id      TEXT NOT NULL,
                session_id   TEXT NOT NULL,
                ts           TEXT NOT NULL,
                tool_name    TEXT NOT NULL,
                input_json   TEXT,
                result_preview TEXT,
                step_tokens  INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
            CREATE INDEX IF NOT EXISTS idx_turns_ts ON turns(ts);
            CREATE INDEX IF NOT EXISTS idx_tool_calls_turn ON tool_calls(turn_id);
        """)
        con.commit()
        # Migrations for existing DBs
        existing = {r[1] for r in con.execute("PRAGMA table_info(tool_calls)").fetchall()}
        if "input_json" not in existing:
            con.execute("ALTER TABLE tool_calls ADD COLUMN input_json TEXT")
        if "step_tokens" not in existing:
            con.execute("ALTER TABLE tool_calls ADD COLUMN step_tokens INTEGER")
        con.commit()
        return con
    except Exception as e:
        log.error("Telemetry DB init failed", error=str(e))
        return None


_telemetry_con = _init_telemetry_db()


@app.post("/telemetry/session")
def telemetry_session(body: dict) -> dict:
    """
    Receive session telemetry from the Claude Code Stop hook.
    Writes sessions, turns, and tool_calls to telemetry.db.
    """
    session_id = (body.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")

    if not _telemetry_con:
        raise HTTPException(status_code=503, detail="Telemetry DB unavailable")

    now        = datetime.now(timezone.utc).isoformat()
    turn_id    = (body.get("turn_id") or f"turn_{session_id}_{now}").strip() or now
    user_prompt= (body.get("user_prompt") or "")[:500]
    insights   = (body.get("insights_raw") or "").strip()
    cwd        = (body.get("cwd") or "")
    usage      = body.get("usage") or {}
    tool_calls = body.get("tool_calls") or []

    try:
        with _telemetry_lock:
            # Upsert session
            _telemetry_con.execute("""
                INSERT INTO sessions (session_id, started_at, last_seen, client, cwd)
                VALUES (?, ?, ?, 'claude-code', ?)
                ON CONFLICT(session_id) DO UPDATE SET last_seen = excluded.last_seen
            """, (session_id, now, now, cwd))

            # Upsert turn
            _telemetry_con.execute("""
                INSERT INTO turns (
                    turn_id, session_id, ts, user_prompt, insights_raw,
                    input_tokens, output_tokens,
                    cache_read_tokens, cache_creation_tokens,
                    cache_creation_1h_tokens, cache_creation_5m_tokens,
                    tool_call_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(turn_id) DO UPDATE SET
                    insights_raw         = excluded.insights_raw,
                    input_tokens         = excluded.input_tokens,
                    output_tokens        = excluded.output_tokens,
                    cache_read_tokens    = excluded.cache_read_tokens,
                    cache_creation_tokens= excluded.cache_creation_tokens,
                    cache_creation_1h_tokens = excluded.cache_creation_1h_tokens,
                    cache_creation_5m_tokens = excluded.cache_creation_5m_tokens,
                    tool_call_count      = excluded.tool_call_count
            """, (
                turn_id, session_id, now, user_prompt, insights,
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
                usage.get("cache_read_tokens", 0),
                usage.get("cache_creation_tokens", 0),
                usage.get("cache_creation_1h_tokens", 0),
                usage.get("cache_creation_5m_tokens", 0),
                len(tool_calls),
            ))

            # Insert tool calls (skip duplicates by turn+name+rowid check)
            for tc in tool_calls:
                raw_input = tc.get("input")
                input_json = _json.dumps(raw_input) if raw_input else None
                _telemetry_con.execute("""
                    INSERT INTO tool_calls (turn_id, session_id, ts, tool_name, input_json, result_preview, step_tokens)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    turn_id, session_id, now,
                    tc.get("tool_name", ""),
                    input_json,
                    tc.get("result_preview", "")[:2000],
                    tc.get("step_tokens"),
                ))

            _telemetry_con.commit()

    except Exception as e:
        log.error("Telemetry write failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

    log.info("Telemetry stored", session_id=session_id, turn_id=turn_id,
             tool_calls=len(tool_calls), has_insights=bool(insights))

    return {"ok": True, "session_id": session_id, "turn_id": turn_id}


# ── Tool categorisation ───────────────────────────────────────────────────────
_OPS_PREFIXES = (
    "docker ", "kubectl ", "systemctl ", "service ", "helm ", "terraform ",
    "ansible ", "aws ", "gcloud ", "az ",
)

def _is_ops_command(input_json_str: str | None) -> bool:
    """True if this Bash call is an ops/infra command (not code exploration)."""
    if not input_json_str:
        return False
    try:
        cmd = _json.loads(input_json_str).get("command", "").lstrip()
        return any(cmd.startswith(p) for p in _OPS_PREFIXES)
    except ValueError:
        return False


# ── Token-savings estimation ──────────────────────────────────────────────────
# Methodology (shown in the UI):
#
# answer_question / CodeKG MCP call:
#   Without CodeKG, Claude would run ~3 grep commands + read ~2 source files
#   to locate the same information.  Median source file in this repo ≈ 2 400 tok
#   (measured from /services/**/*.py).  So: 2 greps×200 tok + 2 reads×2 400 tok
#   = 5 200 tok avoided per KG call.
#
# Agent index file read (.codekg/):
#   The index file is a compact summary of a module.  Without it Claude would
#   read the raw source files in that module.  Each index covers ~3 source files
#   on average → 3 × 2 400 = 7 200 tok avoided.  But the index itself costs
#   ~400 tok to read, so net saving ≈ 7 200 − 400 = 6 800 tok.
#   We use a conservative 5 000 to avoid overstating.
#
# These are estimates — the real avoided work varies per request.
_AVG_SOURCE_FILE_TOKENS  = 2_400   # median .py file in this repo
_SAVINGS_PER_KG_CALL     = 2 * 200 + 2 * _AVG_SOURCE_FILE_TOKENS   # 5 200
_SAVINGS_PER_INDEX_READ  = 5_000   # conservative: 3 source files minus index cost


def _tool_savings(tool_name: str, input_json_str: str | None) -> int:
    """Return estimated tokens saved by this one tool call."""
    if "codekg" in tool_name and not tool_name.endswith("submit_session_telemetry"):
        return _SAVINGS_PER_KG_CALL
    if tool_name == "Read" and input_json_str:
        try:
            fp = _json.loads(input_json_str).get("file_path", "")
            if ".codekg/" in fp:
                return _SAVINGS_PER_INDEX_READ
        except ValueError:
            pass
    return 0


def _compute_session_savings(session_id: str) -> int:
    """Sum estimated token savings across all tool calls in a session."""
    if not _telemetry_con:
        return 0
    rows = _telemetry_con.execute(
        "SELECT tool_name, input_json FROM tool_calls WHERE session_id = ?",
        (session_id,)
    ).fetchall()
    return sum(_tool_savings(r[0], r[1]) for r in rows)


@app.get("/telemetry/sessions")
def telemetry_sessions(limit: int = 50) -> list[dict]:
    if not _telemetry_con:
        raise HTTPException(status_code=503, detail="Telemetry DB unavailable")
    rows = _telemetry_con.execute("""
        SELECT s.session_id, s.started_at, s.last_seen, s.cwd,
               COUNT(t.turn_id) AS turn_count,
               SUM(t.input_tokens) AS total_input,
               SUM(t.cache_read_tokens) AS total_cache_read,
               SUM(t.output_tokens) AS total_output,
               SUM(t.tool_call_count) AS total_tool_calls
        FROM sessions s
        LEFT JOIN turns t ON t.session_id = s.session_id
        GROUP BY s.session_id
        ORDER BY s.last_seen DESC
        LIMIT ?
    """, (limit,)).fetchall()
    result = [dict(zip(
        ["session_id","started_at","last_seen","cwd",
         "turn_count","total_input","total_cache_read","total_output","total_tool_calls"], r
    )) for r in rows]
    for s in result:
        s["tokens_saved"] = _compute_session_savings(s["session_id"])
    return result


@app.get("/telemetry/sessions/{session_id}/query-plan")
def telemetry_query_plan(session_id: str) -> dict:
    """
    Reconstruct the steps Claude would have taken WITHOUT CodeKG or agent index files.
    Returns a per-turn list of hypothetical exploration steps with estimated token costs.
    """
    if not _telemetry_con:
        raise HTTPException(status_code=503, detail="Telemetry DB unavailable")

    turns = _telemetry_con.execute(
        "SELECT turn_id, user_prompt FROM turns WHERE session_id = ? ORDER BY ts DESC",
        (session_id,)
    ).fetchall()

    import re as _re

    _avg_source_tok = 2_400   # fallback when KG has no data
    _grep_tok       = 200     # typical grep command + output
    _tok_per_line   = 2.5     # ~10 chars/line ÷ 4 chars/token

    # Build file→token map from KG: max(end_line) per file_path
    _file_tok_map: dict[str, int] = {}
    try:
        with driver.session() as _ks:
            rows = _ks.run("""
                MATCH (c:Class)
                WHERE c.file_path IS NOT NULL AND c.end_line IS NOT NULL AND c.end_line > 0
                WITH c.file_path AS fp, max(c.end_line) AS loc
                RETURN fp, loc
            """).data()
            for row in rows:
                fp = row["fp"]
                loc = row["loc"] or 0
                _file_tok_map[fp] = max(100, int(loc * _tok_per_line))
    except Exception as e:
        log.warning("Failed to build file token map from KG", exc=e)

    def _tok_for_path(path: str) -> int:
        """Tokens to read this file — from KG LOC if available, else disk size, else average."""
        if path in _file_tok_map:
            return _file_tok_map[path]
        # Try matching by suffix (KG paths use /host-home/... prefix)
        for kp, tok in _file_tok_map.items():
            if kp.endswith(path) or (path and "/" in kp and path.endswith("/" + kp.split("/")[-1])):
                return tok
        try:
            return max(100, os.path.getsize(path) // 4)
        except OSError:
            return _avg_source_tok

    def _keywords_from_question(question: str) -> list[str]:
        stop = {
            "what","where","which","how","does","the","are","is","in","of",
            "to","a","an","for","and","or","it","this","that","with","by",
            "do","have","has","be","at","from","on","as","if","can","get",
            "list","show","find","about","handle","handles","used","using",
            "i","we","you","me","my","want","make","put","see","also","page",
            "same","line","just","now","only","so","but","not","all","more",
        }
        words = _re.findall(r"[A-Za-z_][A-Za-z0-9_]*", question)
        scored = []
        for w in words:
            if len(w) < 3 or w.lower() in stop:
                continue
            score = (2 if w[0].isupper() else 0) + (2 if "_" in w else 0) + (2 if len(w) >= 7 else 1 if len(w) >= 5 else 0)
            scored.append((score, w))
        scored.sort(key=lambda x: -x[0])
        seen: set[str] = set()
        result = []
        for _, w in scored:
            if w.lower() not in seen:
                seen.add(w.lower())
                result.append(w)
            if len(result) == 3:
                break
        parts = question.split()
        return result or ([parts[0][:20]] if parts else ["<query>"])

    # Build a map: index_file_path → source files it covers (real sizes from disk)
    def _get_repo_root_once(index_path: str) -> str:
        # .codekg/ lives directly under repo root
        return os.path.dirname(os.path.dirname(index_path))

    def _file_tok(path: str) -> int:
        return _tok_for_path(path)

    def _strip_repo(path: str, rroot: str) -> str:
        try:
            return os.path.relpath(path, rroot)
        except ValueError:
            return path

    result = []
    for turn_id, user_prompt in turns:
        tcs = _telemetry_con.execute(
            "SELECT tool_name, input_json FROM tool_calls WHERE turn_id = ? ORDER BY id",
            (turn_id,)
        ).fetchall()

        # Collect files actually read/edited this turn — these are what KG helped find
        touched_files: list[tuple[str, int]] = []  # (rel_path, tok)
        for tc_name, tc_input_str in tcs:
            if tc_name in ("Read", "Edit", "Write") and tc_input_str:
                try:
                    fp = _json.loads(tc_input_str).get("file_path", "")
                    if fp and ".codekg/" not in fp:
                        rroot = _get_repo_root_once(fp) if ".codekg" in fp else os.path.dirname(fp)
                        # Find actual repo root by looking for .codekg sibling
                        candidate = fp
                        for _ in range(6):
                            candidate = os.path.dirname(candidate)
                            if os.path.isdir(os.path.join(candidate, ".codekg")):
                                rroot = candidate
                                break
                        rel = _strip_repo(fp, rroot)
                        tok = _file_tok(fp)
                        if (rel, tok) not in touched_files:
                            touched_files.append((rel, tok))
                except ValueError:
                    pass

        plan_steps = []
        for tc_name, tc_input_str in tcs:
            tc_input = _json.loads(tc_input_str) if tc_input_str else None
            inp = tc_input or {}

            steps: list[dict] = []

            # ── answer_question ───────────────────────────────────────────────
            if "answer_question" in tc_name:
                question = inp.get("question", "")
                keywords = _keywords_from_question(question) if question else []
                kw_pattern = "|".join(keywords) if keywords else "<keyword>"
                first_kw   = keywords[0] if keywords else "<keyword>"
                context    = question[:80] if question else "(question not recorded)"

                steps.append({
                    "tool": "Bash",
                    "description": f'grep -r "{kw_pattern}" services/ --include="*.py" -l',
                    "rationale": f"Locate files relevant to: {context}",
                    "est_tokens": _grep_tok,
                })
                steps.append({
                    "tool": "Bash",
                    "description": f'grep -rn "{first_kw}" services/ --include="*.py"',
                    "rationale": "Read matching lines to understand context",
                    "est_tokens": _grep_tok,
                })
                # If we know which files Claude actually ended up working on, use those
                files_to_read = touched_files[:4] if touched_files else []
                if files_to_read:
                    for rel, tok in files_to_read:
                        steps.append({
                            "tool": "Read",
                            "description": rel,
                            "rationale": "File Claude worked on — would need to find and read without KG",
                            "est_tokens": tok,
                        })
                else:
                    steps.append({
                        "tool": "Read",
                        "description": "Top matching file (unknown without running grep)",
                        "est_tokens": _avg_source_tok,
                        "rationale": "Inspect most relevant result",
                    })
                    steps.append({
                        "tool": "Read",
                        "description": "Second matching file for cross-reference",
                        "est_tokens": _avg_source_tok,
                        "rationale": "Verify and cross-check",
                    })

            # ── get_class_context / search_classes ────────────────────────────
            elif "get_class_context" in tc_name or "search_class" in tc_name:
                fqn = inp.get("fqn", inp.get("query", ""))
                class_name = fqn.split(".")[-1] if fqn else "<class>"
                steps.append({
                    "tool": "Bash",
                    "description": f'grep -r "class {class_name}" services/ --include="*.py" -l',
                    "rationale": f"Locate file defining {class_name}",
                    "est_tokens": _grep_tok,
                })
                match = next((f for f, _ in touched_files if class_name.lower() in f.lower()), None)
                steps.append({
                    "tool": "Read",
                    "description": match or f"File containing {class_name}",
                    "rationale": "Inspect class definition, methods, dependencies",
                    "est_tokens": dict(touched_files).get(match, _avg_source_tok) if match else _avg_source_tok,
                })

            # ── get_module_context ────────────────────────────────────────────
            elif "get_module_context" in tc_name:
                module = inp.get("module_id", "")
                steps.append({
                    "tool": "Bash",
                    "description": f'find services/{module} -name "*.py" | head -20',
                    "rationale": f"Discover files in {module} module",
                    "est_tokens": _grep_tok,
                })
                module_files = [(f, t) for f, t in touched_files if module in f] or touched_files[:2]
                for rel, tok in module_files[:3]:
                    steps.append({
                        "tool": "Read",
                        "description": rel,
                        "rationale": "Read module file to understand structure",
                        "est_tokens": tok,
                    })

            # ── agent index file read ─────────────────────────────────────────
            elif tc_name == "Read" and ".codekg/" in (inp.get("file_path") or ""):
                index_path = inp.get("file_path", "")
                rroot = _get_repo_root_once(index_path)

                # Prefer: files Claude actually touched in this turn that belong to this module
                module_slug = os.path.basename(index_path).replace(".md", "").replace("--", "/")
                relevant = [(f, t) for f, t in touched_files if module_slug.split("/")[-1] in f]

                # Fallback: all source files in the module directory
                if not relevant:
                    src_dir = os.path.join(rroot, module_slug)
                    if os.path.isdir(src_dir):
                        for root, _, fnames in os.walk(src_dir):
                            if "__pycache__" in root:
                                continue
                            for fn in sorted(fnames):
                                if fn.endswith(".py"):
                                    full = os.path.join(root, fn)
                                    rel = _strip_repo(full, rroot)
                                    relevant.append((rel, _file_tok(full)))

                index_label = module_slug
                steps.append({
                    "tool": "Bash",
                    "description": f'find services/{module_slug.split("/")[-1]} -name "*.py"',
                    "rationale": f"Discover files in {index_label} module (index gives this instantly)",
                    "est_tokens": _grep_tok,
                })
                for rel, tok in relevant[:6]:
                    steps.append({
                        "tool": "Read",
                        "description": rel,
                        "rationale": "Read source file — index gave class list + descriptions instead",
                        "est_tokens": tok,
                    })
                if len(relevant) > 6:
                    extra_tok = sum(t for _, t in relevant[6:])
                    steps.append({
                        "tool": "note",
                        "description": f"… and {len(relevant) - 6} more files (~{extra_tok:,} tok)",
                        "rationale": "",
                        "est_tokens": extra_tok,
                    })

            if steps:
                actual_input = (
                    inp.get("question") or inp.get("fqn") or
                    inp.get("file_path", "").replace(
                        os.path.join(rroot, "") if (rroot := _get_repo_root_once(
                            inp.get("file_path","")
                        ) if ".codekg" in inp.get("file_path","") else "") else "", ""
                    ) if inp else ""
                )
                plan_steps.append({
                    "actual_tool": tc_name.replace("mcp__codekg__", "⚡ "),
                    "actual_input": str(actual_input)[:120],
                    "steps": steps,
                    "est_tokens": sum(s["est_tokens"] for s in steps),
                })

        # If no CodeKG/index calls but Claude did read/edit files, reconstruct
        # the discovery cost — without KG, Claude would have grepped to find them
        if not plan_steps and touched_files:
            prompt_words = _keywords_from_question(user_prompt or "")
            kw_pattern = "|".join(prompt_words) if prompt_words else "<keyword>"
            steps = [
                {
                    "tool": "Bash",
                    "description": f'grep -r "{kw_pattern}" services/ --include="*.py" -l',
                    "rationale": "Locate relevant files (KG / index skipped this step)",
                    "est_tokens": _grep_tok,
                },
                {
                    "tool": "Bash",
                    "description": f'grep -rn "{prompt_words[0] if prompt_words else kw_pattern}" services/ --include="*.py"',
                    "rationale": "Read matching lines for context",
                    "est_tokens": _grep_tok,
                },
            ]
            # Files Claude actually read/edited — these would still be needed, but
            # the grep steps above are the extra cost without KG navigation
            for rel, tok in touched_files[:4]:
                steps.append({
                    "tool": "Read",
                    "description": rel,
                    "rationale": "Still needed — but finding it required grep first",
                    "est_tokens": tok,
                })
            if len(touched_files) > 4:
                extra = sum(t for _, t in touched_files[4:])
                steps.append({
                    "tool": "note",
                    "description": f"… and {len(touched_files)-4} more files already read (~{extra:,} tok each)",
                    "rationale": "",
                    "est_tokens": 0,  # already counted in actual tokens
                })
            plan_steps.append({
                "actual_tool": "navigation",
                "actual_input": f"found and read {len(touched_files)} file(s) directly via KG/index",
                "steps": steps,
                "est_tokens": _grep_tok * 2,  # only count the extra grep cost, not re-reads
                "note": "Files would still need reading — only grep discovery is extra cost",
            })

        if plan_steps:
            result.append({
                "turn_id": turn_id,
                "user_prompt": user_prompt,
                "plan": plan_steps,
                "total_est_tokens": sum(p["est_tokens"] for p in plan_steps),
            })

    return {"session_id": session_id, "turns": result}


@app.get("/telemetry/sessions/{session_id}")
def telemetry_session_detail(session_id: str) -> dict:
    if not _telemetry_con:
        raise HTTPException(status_code=503, detail="Telemetry DB unavailable")
    turns = _telemetry_con.execute("""
        SELECT turn_id, ts, user_prompt, insights_raw,
               input_tokens, output_tokens, cache_read_tokens,
               cache_creation_tokens, tool_call_count
        FROM turns WHERE session_id = ? ORDER BY ts DESC
    """, (session_id,)).fetchall()
    cols = ["turn_id","ts","user_prompt","insights_raw",
            "input_tokens","output_tokens","cache_read_tokens",
            "cache_creation_tokens","tool_call_count"]
    turn_list = [dict(zip(cols, r)) for r in turns]

    for turn in turn_list:
        tcs = _telemetry_con.execute(
            "SELECT tool_name, input_json, result_preview, ts, step_tokens FROM tool_calls WHERE turn_id = ? ORDER BY id",
            (turn["turn_id"],)
        ).fetchall()
        tcs_parsed = []
        for r in tcs:
            saved  = _tool_savings(r[0], r[1])
            is_ops = r[0] == "Bash" and _is_ops_command(r[1])
            tcs_parsed.append({
                "tool_name": r[0],
                "input": _json.loads(r[1]) if r[1] else None,
                "result_preview": r[2],
                "ts": r[3],
                "step_tokens": r[4],
                "tokens_saved": saved,
                "is_ops": is_ops,
            })
        turn["tool_calls"] = tcs_parsed
        turn["tokens_saved"] = sum(tc["tokens_saved"] for tc in tcs_parsed)
        turn["ops_tokens"]   = sum(
            (tc["step_tokens"] or 0) for tc in tcs_parsed if tc["is_ops"]
        )

    for t in turn_list:
        t["input_context"] = (
            (t.get("input_tokens") or 0)
            + (t.get("cache_read_tokens") or 0)
            + (t.get("cache_creation_tokens") or 0)
        )

    session_tokens_saved = sum(t["tokens_saved"] for t in turn_list)
    total_input_context  = sum(t["input_context"] for t in turn_list)
    total_output         = sum((t.get("output_tokens") or 0) for t in turn_list)
    return {
        "session_id": session_id,
        "turns": turn_list,
        "tokens_saved": session_tokens_saved,
        "total_input_context": total_input_context,
        "total_output_tokens": total_output,
        "estimated_input_without_codekg": total_input_context + session_tokens_saved,
    }
