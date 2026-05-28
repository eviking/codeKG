"""
Architecture Console — web UI for the architecture team to:
  - Register and manage repositories
  - View the current state of the knowledge graph
  - Author and manage architectural policies
  - Review violations across repositories
"""
import json
import os
import uuid
from pathlib import Path
from typing import Optional

import git
import httpx
from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from neo4j import GraphDatabase

app = FastAPI(title="CodeKG Architecture Console")
templates = Jinja2Templates(directory="templates")

API_URL = os.environ.get("API_URL", "http://api:8000")
INGESTION_URL = os.environ.get("INGESTION_URL", "http://ingestion:8001")
NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USER = os.environ["NEO4J_USER"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
REPOS_PATH = os.environ.get("REPOS_PATH", "/repos")
REPOS_REGISTRY = os.environ.get("REPOS_REGISTRY", "/repos/repos.json")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
api_client = httpx.Client(base_url=API_URL, timeout=30.0)
ingestion_client = httpx.Client(base_url=INGESTION_URL, timeout=10.0)


# ------------------------------------------------------------------
# Registry helpers
# ------------------------------------------------------------------

def _load_registry() -> dict[str, str]:
    p = Path(REPOS_REGISTRY)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}


def _save_registry(registry: dict[str, str]):
    p = Path(REPOS_REGISTRY)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(registry, indent=2))


def _validate_repo_path(path: str) -> tuple[bool, str]:
    """Return (ok, error_message). Checks path exists and is a git repo."""
    p = Path(path)
    if not p.exists():
        return False, f"Path does not exist: {path}"
    if not p.is_dir():
        return False, f"Path is not a directory: {path}"
    if not (p / ".git").exists():
        return False, f"No .git directory found at: {path} — is this a git repository?"
    return True, ""


def _repo_git_info(path: str) -> dict:
    """Return basic git metadata for display."""
    try:
        repo = git.Repo(path)
        return {
            "branch": repo.active_branch.name if not repo.head.is_detached else "detached",
            "last_commit": repo.head.commit.hexsha[:12],
            "last_message": repo.head.commit.message.strip().split("\n")[0][:80],
            "last_author": repo.head.commit.author.name,
        }
    except Exception as e:
        return {"error": str(e)}


def run_query(cypher: str, **params) -> list[dict]:
    with driver.session() as s:
        return [dict(r) for r in s.run(cypher, **params)]


# ------------------------------------------------------------------
# Repository management
# ------------------------------------------------------------------

@app.get("/repos", response_class=HTMLResponse)
async def repos_list(request: Request):
    registry = _load_registry()
    # Enrich with KG data (last indexed commit, class count)
    kg_repos = {}
    try:
        for r in api_client.get("/repos").json():
            kg_repos[r["repo_id"]] = r
    except Exception:
        pass

    repos = []
    for repo_id, repo_path in registry.items():
        entry = {
            "repo_id": repo_id,
            "path": repo_path,
            "git": _repo_git_info(repo_path),
            "kg": kg_repos.get(repo_id, {}),
        }
        repos.append(entry)

    # Also show repos in KG that are no longer in registry
    for repo_id, kg in kg_repos.items():
        if repo_id not in registry:
            repos.append({
                "repo_id": repo_id,
                "path": kg.get("path", ""),
                "git": {},
                "kg": kg,
                "orphaned": True,
            })

    return templates.TemplateResponse("repos.html", {
        "request": request,
        "repos": repos,
        "repos_path": REPOS_PATH,
    })


@app.post("/repos")
async def register_repo(
    repo_id: str = Form(...),
    repo_path: str = Form(...),
    trigger_scan: str = Form("yes"),
):
    ok, err = _validate_repo_path(repo_path)
    if not ok:
        raise HTTPException(400, err)

    registry = _load_registry()
    registry[repo_id] = repo_path
    _save_registry(registry)

    if trigger_scan == "yes":
        try:
            ingestion_client.post("/scan/full", json={
                "repo_id": repo_id,
                "repo_path": repo_path,
            })
        except Exception:
            pass  # scan is async; watcher will pick it up on next poll

    return RedirectResponse(f"/repos/{repo_id}", status_code=303)


@app.get("/repos/{repo_id:path}", response_class=HTMLResponse)
async def repo_detail(request: Request, repo_id: str):
    registry = _load_registry()
    repo_path = registry.get(repo_id)

    kg_data: dict = {}
    provenance: dict = {}
    stats: dict = {}

    try:
        r = api_client.get(f"/repos/{repo_id}")
        if r.status_code == 200:
            kg_data = r.json()
    except Exception:
        pass

    try:
        p = api_client.get(f"/provenance/{repo_id}")
        if p.status_code == 200:
            provenance = p.json()
    except Exception:
        pass

    if repo_path or kg_data.get("path"):
        path = repo_path or kg_data.get("path", "")
        stats_rows = run_query(
            """
            MATCH (c:Class {repo_id: $rid}) WITH count(c) AS classes
            MATCH (m:Method {repo_id: $rid}) WITH classes, count(m) AS methods
            MATCH (p:Package {repo_id: $rid}) WITH classes, methods, count(p) AS packages
            RETURN classes, methods, packages
            """,
            rid=repo_id,
        )
        stats = stats_rows[0] if stats_rows else {}

    git_info = _repo_git_info(repo_path) if repo_path else {}

    return templates.TemplateResponse("repo_detail.html", {
        "request": request,
        "repo_id": repo_id,
        "repo_path": repo_path,
        "git": git_info,
        "kg": kg_data,
        "provenance": provenance,
        "stats": stats,
        "in_registry": repo_id in registry,
        "api_url": API_URL.replace("http://api:8000", "http://localhost:8000"),
    })


@app.post("/repos/{repo_id:path}/scan")
async def trigger_scan(repo_id: str):
    registry = _load_registry()
    repo_path = registry.get(repo_id)
    if not repo_path:
        raise HTTPException(404, f"{repo_id} not in registry")
    try:
        resp = ingestion_client.post("/scan/full", json={
            "repo_id": repo_id,
            "repo_path": repo_path,
        }, timeout=10.0)
        return RedirectResponse(f"/repos/{repo_id}?scan=started", status_code=303)
    except Exception as e:
        raise HTTPException(502, f"Could not reach ingestion service: {e}")


@app.post("/repos/{repo_id:path}/remove")
async def remove_repo(repo_id: str):
    registry = _load_registry()
    registry.pop(repo_id, None)
    _save_registry(registry)
    return RedirectResponse("/repos", status_code=303)


@app.get("/api/repos/{repo_id:path}/scan-status")
async def scan_status(repo_id: str):
    """Polled by the UI to check whether a scan has completed."""
    try:
        r = api_client.get(f"/repos/{repo_id}")
        if r.status_code == 200:
            return JSONResponse(r.json())
    except Exception:
        pass
    return JSONResponse({"last_commit": None})


# ------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    repos = api_client.get("/repos").json()
    violations = api_client.get("/violations", params={"severity": "error"}).json()
    policies = api_client.get("/policies").json()
    stats = run_query("""
        MATCH (c:Class) WITH count(c) AS classes
        MATCH (m:Method) WITH classes, count(m) AS methods
        MATCH (p:Package) WITH classes, methods, count(p) AS packages
        RETURN classes, methods, packages
    """)
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "repos": repos,
        "violations": violations[:20],
        "policies": policies,
        "stats": stats[0] if stats else {},
    })


# ------------------------------------------------------------------
# Policy management
# ------------------------------------------------------------------

@app.get("/policies", response_class=HTMLResponse)
async def policies_list(request: Request):
    policies = api_client.get("/policies", params={"status": None}).json()
    modules = run_query("MATCH (m:Module) RETURN m.module_id AS module_id ORDER BY module_id")
    return templates.TemplateResponse("policies.html", {
        "request": request,
        "policies": policies,
        "modules": [r["module_id"] for r in modules],
    })


@app.post("/policies")
async def create_policy(
    title: str = Form(...),
    natural_language: str = Form(...),
    severity: str = Form("warning"),
    module_targets: str = Form(""),
):
    """
    Create a new architectural policy from natural language.
    The cypher_constraint is compiled from the NL using the policy compiler.
    """
    from policy_compiler import compile_policy

    policy_id = f"policy-{uuid.uuid4().hex[:8]}"
    cypher = compile_policy(natural_language)
    targets = [t.strip() for t in module_targets.split(",") if t.strip()]

    with driver.session() as s:
        s.run(
            """
            MERGE (ap:ArchPolicy {policy_id: $policy_id})
            SET ap.title = $title,
                ap.natural_language = $nl,
                ap.cypher_constraint = $cypher,
                ap.severity = $severity,
                ap.status = 'draft'
            """,
            policy_id=policy_id, title=title, nl=natural_language,
            cypher=cypher, severity=severity,
        )
        for mod_id in targets:
            s.run(
                """
                MATCH (ap:ArchPolicy {policy_id: $policy_id})
                MERGE (mod:Module {module_id: $mod_id})
                MERGE (ap)-[:TARGETS]->(mod)
                """,
                policy_id=policy_id, mod_id=mod_id,
            )

    return RedirectResponse(f"/policies/{policy_id}", status_code=303)


@app.get("/policies/{policy_id}", response_class=HTMLResponse)
async def policy_detail(request: Request, policy_id: str):
    rows = run_query("MATCH (ap:ArchPolicy {policy_id: $pid}) RETURN ap", pid=policy_id)
    if not rows:
        raise HTTPException(404)
    violations = run_query(
        """
        MATCH (c)-[:VIOLATES]->(ap:ArchPolicy {policy_id: $pid})
        RETURN c.fqn AS fqn, c.file_path AS file_path
        LIMIT 100
        """,
        pid=policy_id,
    )
    return templates.TemplateResponse("policy_detail.html", {
        "request": request,
        "policy": rows[0]["ap"],
        "violations": violations,
    })


@app.post("/policies/{policy_id}/activate")
async def activate_policy(policy_id: str):
    run_query("MATCH (ap:ArchPolicy {policy_id: $pid}) SET ap.status = 'active'", pid=policy_id)
    return RedirectResponse(f"/policies/{policy_id}", status_code=303)


@app.post("/policies/{policy_id}/run")
async def run_policy(policy_id: str):
    """Evaluate the policy's Cypher constraint and write VIOLATES edges."""
    rows = run_query("MATCH (ap:ArchPolicy {policy_id: $pid}) RETURN ap.cypher_constraint AS cypher", pid=policy_id)
    if not rows:
        raise HTTPException(404)

    cypher = rows[0]["cypher"]
    # The constraint query is expected to return (violator) nodes
    violators = run_query(cypher)
    count = 0
    with driver.session() as s:
        for row in violators:
            violator_fqn = row.get("fqn") or row.get("violator")
            if violator_fqn:
                s.run(
                    """
                    MATCH (c {fqn: $fqn})
                    MATCH (ap:ArchPolicy {policy_id: $pid})
                    MERGE (c)-[:VIOLATES]->(ap)
                    """,
                    fqn=violator_fqn, pid=policy_id,
                )
                count += 1

    return {"policy_id": policy_id, "violations_found": count}


# ------------------------------------------------------------------
# Module management
# ------------------------------------------------------------------

@app.get("/modules", response_class=HTMLResponse)
async def modules_list(request: Request):
    modules = run_query(
        """
        MATCH (mod:Module)
        OPTIONAL MATCH (p:Package)-[:OWNS]->(mod)
        RETURN mod.module_id AS module_id, mod.description AS description,
               collect(p.fqn) AS packages
        ORDER BY mod.module_id
        """
    )
    return templates.TemplateResponse("modules.html", {"request": request, "modules": modules})


@app.post("/modules")
async def create_module(
    module_id: str = Form(...),
    description: str = Form(""),
    packages: str = Form(""),
):
    pkg_list = [p.strip() for p in packages.split(",") if p.strip()]
    with driver.session() as s:
        s.run(
            "MERGE (mod:Module {module_id: $mid}) SET mod.description = $desc",
            mid=module_id, desc=description,
        )
        for pkg_fqn in pkg_list:
            s.run(
                """
                MATCH (mod:Module {module_id: $mid})
                MERGE (p:Package {fqn: $pkg})
                MERGE (mod)-[:OWNS]->(p)
                MERGE (p)-[:BELONGS_TO_MODULE]->(mod)
                """,
                mid=module_id, pkg=pkg_fqn,
            )
    return RedirectResponse("/modules", status_code=303)


@app.get("/health")
def health():
    return {"status": "ok"}
