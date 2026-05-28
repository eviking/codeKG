"""
Query API — the core HTTP layer consumed by the MCP server, the architecture
console, and CI/CD pipelines.
"""
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from neo4j import GraphDatabase

app = FastAPI(title="CodeKG Query API", version="0.1.0")

NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USER = os.environ["NEO4J_USER"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def run_query(cypher: str, **params) -> list[dict]:
    with driver.session() as s:
        result = s.run(cypher, **params)
        return [dict(r) for r in result]


# ------------------------------------------------------------------
# Repository endpoints
# ------------------------------------------------------------------

@app.get("/repos")
def list_repos():
    return run_query("MATCH (r:Repository) RETURN r.repo_id AS repo_id, r.name AS name, r.last_commit AS last_commit")


@app.get("/repos/{repo_id}")
def get_repo(repo_id: str):
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
def module_context(module_id: str):
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
def class_context(fqn: str):
    """Full context for a single class including its methods, fields, and relationships."""
    cls = run_query("MATCH (c {fqn: $fqn}) RETURN c", fqn=fqn)
    if not cls:
        raise HTTPException(404, f"Class {fqn} not found")
    methods = run_query(
        "MATCH (c {fqn: $fqn})-[:CONTAINS]->(m:Method) RETURN m.fqn AS fqn, m.name AS name, m.return_type AS return_type, m.parameters AS parameters",
        fqn=fqn,
    )
    fields = run_query(
        "MATCH (c {fqn: $fqn})-[:CONTAINS]->(f:Field) RETURN f.fqn AS fqn, f.name AS name, f.type_name AS type_name",
        fqn=fqn,
    )
    extends = run_query(
        "MATCH (c {fqn: $fqn})-[:EXTENDS]->(p) RETURN p.fqn AS fqn, p.name AS name",
        fqn=fqn,
    )
    implements = run_query(
        "MATCH (c {fqn: $fqn})-[:IMPLEMENTS]->(i) RETURN i.fqn AS fqn, i.name AS name",
        fqn=fqn,
    )
    callers = run_query(
        """
        MATCH (caller:Method)-[:CALLS]->(m:Method)
        WHERE m.class_fqn = $fqn
        RETURN caller.fqn AS caller_fqn
        LIMIT 20
        """,
        fqn=fqn,
    )
    return {
        "class": cls[0]["c"],
        "methods": methods,
        "fields": fields,
        "extends": extends,
        "implements": implements,
        "callers": callers,
    }


@app.get("/context/feature")
def feature_context(classes: str = Query(..., description="Comma-separated FQNs")):
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
def list_violations(repo_id: Optional[str] = None, severity: Optional[str] = None):
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
def pr_violations(files: str = Query(..., description="Comma-separated file paths changed in the PR")):
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
def list_policies(status: Optional[str] = "active"):
    params: dict = {}
    where = ""
    if status:
        where = "WHERE ap.status = $status"
        params["status"] = status
    return run_query(f"MATCH (ap:ArchPolicy) {where} RETURN ap ORDER BY ap.title", **params)


@app.get("/policies/{policy_id}")
def get_policy(policy_id: str):
    rows = run_query("MATCH (ap:ArchPolicy {policy_id: $pid}) RETURN ap", pid=policy_id)
    if not rows:
        raise HTTPException(404, f"Policy {policy_id} not found")
    return rows[0]["ap"]


# ------------------------------------------------------------------
# Search
# ------------------------------------------------------------------

@app.get("/search/class")
def search_class(q: str, repo_id: Optional[str] = None):
    params: dict = {"q": f"(?i).*{q}.*"}
    extra = "AND c.repo_id = $repo_id" if repo_id else ""
    if repo_id:
        params["repo_id"] = repo_id
    return run_query(
        f"""
        MATCH (c:Class)
        WHERE c.name =~ $q {extra}
        RETURN c.fqn AS fqn, c.name AS name, c.kind AS kind, c.module AS module
        LIMIT 20
        """,
        **params,
    )


@app.get("/health")
def health():
    return {"status": "ok"}


# ------------------------------------------------------------------
# Change Impact Engine
# ------------------------------------------------------------------

@app.get("/impact/files")
def impact_files(
    files: str = Query(..., description="Comma-separated file paths"),
    repo_id: str = Query(..., description="Repository ID"),
    commit_sha: Optional[str] = None,
):
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
):
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
):
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
def repo_provenance(repo_id: str):
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
def get_template(repo_id: str):
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
