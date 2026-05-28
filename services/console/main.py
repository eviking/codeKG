"""
Architecture Console — web UI for the architecture team to:
  - View the current state of the knowledge graph
  - Author and manage architectural policies
  - Review violations across repositories
"""
import os
import uuid
from typing import Optional

import httpx
from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from neo4j import GraphDatabase

app = FastAPI(title="CodeKG Architecture Console")
templates = Jinja2Templates(directory="templates")

API_URL = os.environ.get("API_URL", "http://api:8000")
NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USER = os.environ["NEO4J_USER"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
api_client = httpx.Client(base_url=API_URL, timeout=30.0)


def run_query(cypher: str, **params) -> list[dict]:
    with driver.session() as s:
        return [dict(r) for r in s.run(cypher, **params)]


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
