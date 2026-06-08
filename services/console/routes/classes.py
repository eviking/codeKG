"""Console routes for class-level drill-down pages. Watch out for long-running background jobs and path validation here, because these handlers mix UI rendering with on-demand analysis."""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from shared.config import cfg
from deps import run_query, _template_ctx, templates

router = APIRouter()

# ── Active summarisation jobs ─────────────────────────────────────────────────
# job_id → {"status": "running"|"done"|"error", "log": [...], "done": int, "total": int}
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


@router.get("/classes", response_class=HTMLResponse)
async def classes_list(
    request:     Request,
    q:           str = "",
    role:        str = "",
    repo_id:     str = "",
    sort:        str = "coupling",
    has_summary: str = "false",
    page:        int = 1,
):
    ctx           = _template_ctx(request)
    effective_repo = repo_id or ctx["selected_repo"]

    PAGE_SIZE = 50
    skip      = (page - 1) * PAGE_SIZE

    filters = ["NOT c.kind IN ['module']"]
    params: dict = {"skip": skip, "limit": PAGE_SIZE}
    if q:
        filters.append("toLower(c.name) CONTAINS toLower($q)"); params["q"] = q
    if role:
        filters.append("c.role = $role"); params["role"] = role
    if effective_repo:
        filters.append("c.repo_id = $repo_id"); params["repo_id"] = effective_repo
    has_summary_bool = has_summary in ("true", "1", "yes")
    if has_summary_bool:
        filters.append("c.summary IS NOT NULL")

    where = " AND ".join(filters)
    order = {
        "coupling":   "c.coupling DESC",
        "blast":      "c.blast_size DESC",
        "name":       "c.name",
        "role":       "c.role, c.name",
        "summary_ts": "c.summary_ts DESC",
    }.get(sort, "c.coupling DESC")

    rows = run_query(
        f"""
        MATCH (c:Class) WHERE {where}
        RETURN c.fqn AS fqn, c.name AS name, c.role AS role,
               c.coupling AS coupling, c.blast_size AS blast_size,
               c.repo_id AS repo_id, c.summary AS summary,
               c.summary_model AS summary_model, c.summary_ts AS summary_ts,
               c.object_model AS om
        ORDER BY {order} SKIP $skip LIMIT $limit
        """,
        **params,
    )

    classes = []
    for r in rows:
        om = {}
        if r.get("om"):
            try:
                om = json.loads(r["om"])
            except ValueError:
                pass
        classes.append({
            "fqn":           r["fqn"],
            "name":          r["name"],
            "role":          r["role"],
            "coupling":      round(r["coupling"] or 0, 3),
            "blast_size":    r["blast_size"] or 0,
            "repo_id":       r["repo_id"],
            "module_id":     om.get("module_id", ""),
            "warnings":      om.get("warnings", []),
            "summary":       r.get("summary") or "",
            "summary_model": r.get("summary_model") or "",
            "summary_ts":    (r.get("summary_ts") or "")[:16].replace("T", " "),
        })

    count_rows = run_query(
        f"MATCH (c:Class) WHERE {where} RETURN count(c) AS n",
        **{k: v for k, v in params.items() if k not in ("skip", "limit")},
    )
    total = count_rows[0]["n"] if count_rows else 0

    # Progress bar: scoped to the active repo so the denominator is accurate
    if effective_repo:
        summary_count_rows = run_query(
            "MATCH (c:Class) WHERE c.repo_id = $repo_id AND NOT c.kind IN ['module'] "
            "AND c.summary IS NOT NULL RETURN count(c) AS n",
            repo_id=effective_repo,
        )
        class_total_rows = run_query(
            "MATCH (c:Class) WHERE c.repo_id = $repo_id AND NOT c.kind IN ['module'] "
            "RETURN count(c) AS n",
            repo_id=effective_repo,
        )
    else:
        summary_count_rows = run_query(
            "MATCH (c:Class) WHERE c.repo_id IS NOT NULL AND NOT c.kind IN ['module'] "
            "AND c.summary IS NOT NULL RETURN count(c) AS n"
        )
        class_total_rows = run_query(
            "MATCH (c:Class) WHERE c.repo_id IS NOT NULL AND NOT c.kind IN ['module'] "
            "RETURN count(c) AS n"
        )
    summary_total = summary_count_rows[0]["n"] if summary_count_rows else 0
    class_total   = class_total_rows[0]["n"]   if class_total_rows   else 0

    roles = run_query(
        "MATCH (c:Class) WHERE c.role IS NOT NULL RETURN DISTINCT c.role AS role ORDER BY role"
    )
    repos = run_query(
        "MATCH (c:Class) WHERE c.repo_id IS NOT NULL RETURN DISTINCT c.repo_id AS repo_id ORDER BY repo_id"
    )

    return templates.TemplateResponse("classes.html", {
        **ctx,
        "classes":       classes,
        "total":         total,
        "page":          page,
        "pages":         max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
        "page_size":     PAGE_SIZE,
        "q":             q,
        "role":          role,
        "repo_id":       effective_repo,
        "sort":          sort,
        "has_summary":   has_summary_bool,
        "summary_total": summary_total,
        "class_total":   class_total,
        "roles":         [r["role"] for r in roles],
        "repos":         [r["repo_id"] for r in repos],
    })


# ── NL Summary generation ─────────────────────────────────────────────────────
# These three routes MUST be registered before the catch-all /classes/{fqn:path}
# below, otherwise FastAPI matches "summarise/..." as an FQN.

@router.post("/classes/summarise", response_class=HTMLResponse)
async def start_summarise(
    request:            Request,
    repo_id:            str  = Form(...),
    model:              str  = Form(""),
    role:               str  = Form(""),
    limit:              str  = Form(""),
    force:              str  = Form(""),
    include_modules:    str  = Form(""),
    include_skip_roles: str  = Form(""),
    ollama_url:         str  = Form(""),
):
    import uuid, sys, importlib.util, subprocess, shutil

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {"status": "starting", "log": [], "done": 0, "total": 0}

    neo4j_uri  = cfg.neo4j.uri
    neo4j_user = cfg.neo4j.user
    neo4j_pass = cfg.neo4j.password
    eff_ollama = ollama_url.strip() or cfg.llm.ollama_url
    eff_model  = model.strip() or cfg.llm.summary_model

    def _run_job():
        try:
            # Import summarise_classes — search in order:
            # 1. Explicit env var override (SUMMARISE_TOOL_PATH)
            # 2. /app/tools/ (baked into the container image)
            # 3. /host-home/<rel-path> where rel-path comes from the codeKG
            #    registry entry (works on any machine where codeKG is registered)
            import json as _json2
            from shared.config import cfg as _cfg2
            _tool_name = "tools/summarise_classes.py"
            _env_override = os.environ.get("SUMMARISE_TOOL_PATH", "")
            _dynamic_paths = []
            try:
                _reg = _json2.loads(open(cfg.paths.repos_registry).read())
                for _rpath in _reg.values():
                    # rpath may be /host-home/... or a local path
                    _candidate = _rpath.rstrip("/") + "/" + _tool_name
                    _dynamic_paths.append(_candidate)
            except (OSError, ValueError):
                pass
            tool_paths = list(filter(None, [
                _env_override or None,
                "/app/tools/summarise_classes.py",
                "/tools/summarise_classes.py",
            ] + _dynamic_paths))
            tool_path = next((p for p in tool_paths if os.path.exists(p)), None)

            if tool_path is None:
                # Fall back to subprocess with the script path via docker exec if not found
                with _jobs_lock:
                    _jobs[job_id]["status"] = "error"
                    _jobs[job_id]["log"].append("ERROR: summarise_classes.py not found in expected locations.")
                return

            # Load the module source and strip the self-bootstrap block before executing.
            # The bootstrap tries to create a venv on the host filesystem which fails
            # inside the container. All deps (neo4j, requests) are already installed.
            import types
            source = open(tool_path).read()
            # Remove everything between the two bootstrap sentinel comments
            import re as _re
            source = _re.sub(
                r"# -{10,}\n# Self-bootstrap.*?# -{10,}\n",
                "",
                source,
                flags=_re.DOTALL,
            )
            # Also neutralise the runtime bootstrap guard that calls os.execv
            source = source.replace(
                "if _missing():",
                "if False:  # bootstrap disabled — deps pre-installed in container",
            )
            sc = types.ModuleType("summarise_classes")
            sc.__file__ = tool_path
            exec(compile(source, tool_path, "exec"), sc.__dict__)

            import argparse, logging

            args = argparse.Namespace(
                repo=repo_id,
                model=eff_model,
                role=role or None,
                fqn=None,
                limit=int(limit) if limit.strip() else None,
                force=force == "yes",
                resume=True,
                stats=False,
                dry_run=False,
                debug=False,
                include_skip_roles=include_skip_roles == "yes",
                include_modules=include_modules == "yes",
                workers=1,
                timeout=120,
                retries=3,
                delay=0.0,
                error_backoff=10.0,
                report_every=10,
                rate_estimate=8.0,
                neo4j_uri=neo4j_uri,
                neo4j_user=neo4j_user,
                neo4j_pass=neo4j_pass,
                ollama_url=eff_ollama,
            )

            # Patch logger so messages go into _jobs[job_id]["log"]
            class _JobHandler(logging.Handler):
                """Small HTTP handler used to receive background job progress. Watch out for shared mutable state here, because class drill-down pages poll this object while work is still running."""

                def emit(self, record):
                    msg = self.format(record)
                    with _jobs_lock:
                        _jobs[job_id]["log"].append(msg)
                        if "Progress:" in msg or "Written:" in msg:
                            pass  # parsed below
                        # parse "Progress: X/Y" lines
                        import re
                        m = re.search(r"Progress: (\d+)/(\d+)", msg)
                        if m:
                            _jobs[job_id]["done"]  = int(m.group(1))
                            _jobs[job_id]["total"] = int(m.group(2))
                        m2 = re.search(r"Written:\s+(\d+)", msg)
                        if m2:
                            _jobs[job_id]["done"] = int(m2.group(1))

            log = sc._setup_logging(repo_id, debug=False)
            h = _JobHandler()
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
            log.addHandler(h)

            with _jobs_lock:
                _jobs[job_id]["status"] = "running"

            sc._run(args, log)

            with _jobs_lock:
                _jobs[job_id]["status"] = "done"

        except Exception as e:
            with _jobs_lock:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["log"].append(f"ERROR: {e}")

    threading.Thread(target=_run_job, daemon=True, name=f"summarise-{job_id}").start()

    # Redirect to the progress page
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/classes/summarise/{job_id}", status_code=303)


@router.get("/classes/summarise/{job_id}", response_class=HTMLResponse)
async def summarise_progress(request: Request, job_id: str):
    if job_id not in _jobs:
        raise HTTPException(404, "Job not found")
    ctx = _template_ctx(request)
    job = _jobs[job_id]
    return templates.TemplateResponse("summarise_progress.html", {
        **ctx,
        "job_id":  job_id,
        "status":  job["status"],
        "done":    job["done"],
        "total":   job["total"],
        "log":     job["log"][-80:],  # last 80 lines
    })


@router.get("/classes/summarise/{job_id}/stream")
async def summarise_stream(job_id: str):
    """SSE endpoint — streams log lines and progress until job completes."""
    if job_id not in _jobs:
        raise HTTPException(404, "Job not found")

    async def _generate():
        sent = 0
        while True:
            job = _jobs.get(job_id, {})
            log = job.get("log", [])
            new = log[sent:]
            for line in new:
                yield f"data: {json.dumps({'type': 'log', 'msg': line, 'done': job.get('done',0), 'total': job.get('total',0)})}\n\n"
            sent += len(new)
            if job.get("status") in ("done", "error"):
                yield f"data: {json.dumps({'type': 'done', 'status': job['status'], 'done': job.get('done',0), 'total': job.get('total',0)})}\n\n"
                break
            await __import__("asyncio").sleep(0.5)

    return StreamingResponse(_generate(), media_type="text/event-stream")


# ── Class detail — catch-all MUST be last ─────────────────────────────────────

@router.get("/classes/{fqn:path}", response_class=HTMLResponse)
async def class_detail(request: Request, fqn: str):
    rows = run_query(
        """MATCH (c:Class {fqn: $fqn})
           RETURN c, c.javadoc AS javadoc, c.summary AS summary,
                  c.summary_model AS summary_model, c.summary_ts AS summary_ts""",
        fqn=fqn,
    )
    if not rows:
        raise HTTPException(404, detail=f"Class {fqn} not found")
    c = dict(rows[0]["c"])
    c["javadoc"]       = rows[0].get("javadoc")       or c.get("javadoc")
    c["summary"]       = rows[0].get("summary")       or c.get("summary")
    c["summary_model"] = rows[0].get("summary_model") or c.get("summary_model")
    c["summary_ts"]    = rows[0].get("summary_ts")    or c.get("summary_ts")

    om = {}
    if c.get("object_model"):
        try:
            om = json.loads(c["object_model"])
        except ValueError:
            pass

    blast_fqns   = om.get("blast_radius", [])[:20]
    blast_details = []
    if blast_fqns:
        blast_details = run_query(
            """
            UNWIND $fqns AS fqn
            MATCH (c:Class {fqn: fqn})
            RETURN c.fqn AS fqn, c.name AS name, c.role AS role, c.coupling AS coupling
            ORDER BY c.coupling DESC
            """,
            fqns=blast_fqns,
        )

    appears_in = om.get("appears_in_chains", [])[:10]
    appears_details = []
    if appears_in:
        appears_details = run_query(
            "UNWIND $fqns AS fqn MATCH (c:Class {fqn: fqn}) RETURN c.fqn AS fqn, c.name AS name, c.role AS role",
            fqns=appears_in,
        )

    return templates.TemplateResponse("class_detail.html", _template_ctx(
        request,
        c=c, om=om,
        blast_details=blast_details,
        appears_details=appears_details,
        fqn=fqn,
    ))
