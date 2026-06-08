"""Console routes for architectural policy management. Watch out for compiler and persistence coupling here, because edits here can change both saved policy text and generated Cypher."""

from __future__ import annotations

import uuid

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from deps import run_query, _template_ctx, templates, driver, api_client, log

router = APIRouter()


@router.get("/policies", response_class=HTMLResponse)
async def policies_list(request: Request):
    try:
        policies = api_client.get("/policies").json()
    except httpx.HTTPError as e:
        log.warning("API unavailable for policies list", error=str(e))
        policies = []
    modules  = run_query("MATCH (m:Module) RETURN m.module_id AS module_id ORDER BY module_id")
    return templates.TemplateResponse("policies.html", {
        **_template_ctx(request),
        "policies": policies,
        "modules":  [r["module_id"] for r in modules],
    })


@router.post("/policies")
async def create_policy(
    request:          Request,
    title:            str = Form(...),
    natural_language: str = Form(...),
    severity:         str = Form("warning"),
    module_targets:   str = Form(""),
):
    from policy_compiler import compile_policy
    policy_id = f"policy-{uuid.uuid4().hex[:8]}"
    compiled_cypher = compile_policy(natural_language)
    targets   = [t.strip() for t in module_targets.split(",") if t.strip()]
    ctx       = _template_ctx(request)
    repo_id   = ctx.get("selected_repo") or ""
    log.info("Policy created", policy_id=policy_id, title=title, severity=severity)

    with driver.session() as s:
        s.run(
            """
            MERGE (ap:ArchPolicy {policy_id: $policy_id})
            SET ap.title = $title, ap.natural_language = $nl,
                ap.cypher_constraint = $constraint, ap.severity = $severity,
                ap.status = 'draft', ap.repo_id = $repo_id
            """,
            policy_id=policy_id, title=title, nl=natural_language,
            constraint=compiled_cypher, severity=severity, repo_id=repo_id,
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


@router.get("/policies/{policy_id}", response_class=HTMLResponse)
async def policy_detail(request: Request, policy_id: str):
    rows = run_query("MATCH (ap:ArchPolicy {policy_id: $pid}) RETURN ap", pid=policy_id)
    if not rows:
        raise HTTPException(404)
    violations = run_query(
        "MATCH (c)-[:VIOLATES]->(ap:ArchPolicy {policy_id: $pid}) "
        "RETURN c.fqn AS fqn, c.file_path AS file_path LIMIT 100",
        pid=policy_id,
    )
    violations_run = request.query_params.get("violations_run")
    run_error      = request.query_params.get("run_error")
    run_error_msg  = request.query_params.get("msg", "")
    recompiled     = request.query_params.get("recompiled")
    saved          = request.query_params.get("saved")
    policy         = dict(rows[0]["ap"])
    cypher         = policy.get("cypher_constraint") or ""
    has_valid_cypher = bool(cypher.strip()) and not cypher.strip().startswith("//")
    return templates.TemplateResponse("policy_detail.html", {
        **_template_ctx(request),
        "policy":           policy,
        "violations":       violations,
        "violations_run":   int(violations_run) if violations_run is not None else None,
        "run_error":        run_error,
        "run_error_msg":    run_error_msg,
        "recompiled":       recompiled,
        "has_valid_cypher": has_valid_cypher,
        "saved":            saved,
    })


@router.post("/policies/{policy_id}/recompile")
async def recompile_policy(policy_id: str):
    """Re-run the policy compiler (now Claude-backed) on the stored natural language."""
    rows = run_query(
        "MATCH (ap:ArchPolicy {policy_id: $pid}) RETURN ap.natural_language AS nl",
        pid=policy_id,
    )
    if not rows or not rows[0].get("nl"):
        raise HTTPException(404, "Policy not found or has no natural language rule.")
    from policy_compiler import compile_policy
    compiled_cypher = compile_policy(rows[0]["nl"])
    run_query(
        "MATCH (ap:ArchPolicy {policy_id: $pid}) SET ap.cypher_constraint = $constraint",
        pid=policy_id, constraint=compiled_cypher,
    )
    compiled = bool(compiled_cypher.strip()) and not compiled_cypher.strip().startswith("//")
    return RedirectResponse(
        f"/policies/{policy_id}?recompiled={'ok' if compiled else 'fail'}",
        status_code=303,
    )


@router.post("/policies/{policy_id}/activate")
async def activate_policy(policy_id: str):
    run_query("MATCH (ap:ArchPolicy {policy_id: $pid}) SET ap.status = 'active'", pid=policy_id)
    return RedirectResponse(f"/policies/{policy_id}", status_code=303)


@router.post("/policies/{policy_id}/deactivate")
async def deactivate_policy(policy_id: str):
    run_query("MATCH (ap:ArchPolicy {policy_id: $pid}) SET ap.status = 'draft'", pid=policy_id)
    return RedirectResponse(f"/policies/{policy_id}", status_code=303)


@router.post("/policies/{policy_id}/edit")
async def edit_policy(
    policy_id:        str,
    title:            str = Form(...),
    natural_language: str = Form(...),
    severity:         str = Form("warning"),
):
    run_query(
        "MATCH (ap:ArchPolicy {policy_id: $pid}) SET ap.title = $title, ap.natural_language = $nl, ap.severity = $sev",
        pid=policy_id, title=title, nl=natural_language, sev=severity,
    )
    return RedirectResponse(f"/policies/{policy_id}?saved=1", status_code=303)


@router.post("/policies/{policy_id}/delete")
async def delete_policy(policy_id: str):
    run_query("MATCH (ap:ArchPolicy {policy_id: $pid}) DETACH DELETE ap", pid=policy_id)
    return RedirectResponse("/policies", status_code=303)


@router.post("/policies/{policy_id}/run")
async def run_policy(request: Request, policy_id: str):
    rows = run_query(
        "MATCH (ap:ArchPolicy {policy_id: $pid}) RETURN ap.cypher_constraint AS cypher, ap.repo_id AS repo_id",
        pid=policy_id,
    )
    if not rows:
        raise HTTPException(404)
    cypher = rows[0].get("cypher") or ""
    stripped = cypher.strip()
    if not stripped or stripped.startswith("//"):
        return RedirectResponse(
            f"/policies/{policy_id}?run_error=no_cypher", status_code=303
        )
    # Determine which repo to scope to — policy's own repo_id, then selected repo, then unscoped
    ctx = _template_ctx(request)
    repo_id = rows[0].get("repo_id") or ctx.get("selected_repo") or ""
    try:
        violators = run_query(cypher, repo_id=repo_id) if repo_id else run_query(cypher)
    except Exception as e:
        err = str(e)
        # If $repo_id is referenced but we have none, or other param issues — redirect with error
        return RedirectResponse(
            f"/policies/{policy_id}?run_error=cypher_error&msg={err[:120]}",
            status_code=303,
        )
    count = 0
    with driver.session() as s:
        for row in violators:
            fqn = row.get("fqn")
            if fqn is None:
                node = row.get("violator")
                fqn  = dict(node).get("fqn") if (node is not None and not isinstance(node, str)) else node
            if fqn:
                s.run(
                    "MATCH (c:Class {fqn: $fqn, repo_id: $repo_id}) "
                    "MATCH (ap:ArchPolicy {policy_id: $pid}) "
                    "MERGE (c)-[:VIOLATES]->(ap)",
                    fqn=fqn, pid=policy_id, repo_id=repo_id,
                )
                count += 1
    return RedirectResponse(f"/policies/{policy_id}?violations_run={count}", status_code=303)
