"""Console routes for repository inventory pages. Watch out for host-path handling here, because these handlers bridge browser input, local files, and backend APIs."""

from __future__ import annotations

import subprocess
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from deps import (
    _load_registry, _save_registry, _to_container_path, _validate_repo_path,
    _repo_git_info, _template_ctx, templates, api_client,
    API_URL, REPOS_PATH, log,
)
from scan_launcher import launch_scan, list_active_scans

router = APIRouter()

_clone_jobs: dict[str, dict] = {}


@router.get("/repos", response_class=HTMLResponse)
async def repos_list(request: Request):
    registry = _load_registry()
    kg_repos = {}
    try:
        for r in api_client.get("/repos").json():
            kg_repos[r["repo_id"]] = r
    except Exception as e:
        log.warning("Failed to fetch repos from API", exc=e)

    active_scans = {s["repo_id"] for s in list_active_scans()}

    repos = []
    for repo_id, repo_path in registry.items():
        repos.append({
            "repo_id":   repo_id,
            "path":      repo_path,
            "git":       _repo_git_info(repo_path),
            "kg":        kg_repos.get(repo_id, {}),
            "scanning":  repo_id in active_scans,
        })
    for repo_id, kg in kg_repos.items():
        if repo_id not in registry:
            repos.append({"repo_id": repo_id, "path": kg.get("path", ""),
                          "git": {}, "kg": kg, "orphaned": True, "scanning": repo_id in active_scans})

    return templates.TemplateResponse("repos.html", {
        **_template_ctx(request),
        "repos": repos,
        "repos_path": REPOS_PATH,
    })


@router.post("/repos")
async def register_repo(
    repo_id:      str = Form(...),
    repo_path:    str = Form(...),
    trigger_scan: str = Form("yes"),
):
    container_path = _to_container_path(repo_path)
    ok, err = _validate_repo_path(container_path)
    if not ok:
        raise HTTPException(400, err)

    registry = _load_registry()
    registry[repo_id] = container_path
    _save_registry(registry)
    log.info("Repo registered", repo_id=repo_id, path=repo_path)

    if trigger_scan == "yes":
        try:
            launch_scan(repo_id, container_path)
        except Exception as e:
            log.warning("Could not launch scan container", repo_id=repo_id, error=str(e))

    return RedirectResponse(f"/repos/{repo_id}", status_code=303)


@router.post("/repos/clone")
async def clone_repo(
    repo_id:      str = Form(...),
    github_url:   str = Form(...),
    clone_path:   str = Form(...),
    trigger_scan: str = Form("yes"),
):
    url = github_url.strip()
    if not (url.startswith("https://") or url.startswith("git@")):
        raise HTTPException(400, "GitHub URL must start with https:// or git@")

    container_dest = _to_container_path(clone_path.rstrip("/"))
    dest = Path(container_dest)
    if dest.exists() and (dest / ".git").exists():
        raise HTTPException(400, f"A git repo already exists at {clone_path}")

    job_id = uuid.uuid4().hex
    _clone_jobs[job_id] = {"status": "cloning", "message": f"Cloning {url}…", "repo_id": repo_id}

    def _do_clone():
        try:
            dest.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                ["git", "clone", "--depth=1", url, str(dest)],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                _clone_jobs[job_id] = {"status": "error",
                                       "message": result.stderr.strip() or "Clone failed",
                                       "repo_id": repo_id}
                return

            registry = _load_registry()
            registry[repo_id] = container_dest
            _save_registry(registry)
            _clone_jobs[job_id] = {"status": "done",
                                   "message": f"Cloned and registered as {repo_id}",
                                   "repo_id": repo_id, "path": container_dest}
            log.info("Repo cloned", repo_id=repo_id, path=container_dest)

            if trigger_scan == "yes":
                try:
                    launch_scan(repo_id, container_dest)
                except Exception as e:
                    log.warning("Could not launch scan container after clone",
                                repo_id=repo_id, error=str(e))

        except subprocess.TimeoutExpired:
            _clone_jobs[job_id] = {"status": "error",
                                   "message": "Clone timed out (5 min limit)", "repo_id": repo_id}
        except Exception as exc:
            _clone_jobs[job_id] = {"status": "error", "message": str(exc), "repo_id": repo_id}

    threading.Thread(target=_do_clone, daemon=True).start()
    return JSONResponse({"job_id": job_id})


@router.get("/repos/clone/status/{job_id}")
async def clone_status(job_id: str):
    job = _clone_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Clone job not found")
    return JSONResponse(job)


@router.get("/repos/{repo_id:path}", response_class=HTMLResponse)
async def repo_detail(request: Request, repo_id: str):
    from deps import run_query
    registry = _load_registry()
    repo_path = registry.get(repo_id)
    kg_data: dict = {}
    provenance: dict = {}
    stats: dict = {}

    try:
        r = api_client.get(f"/repos/{repo_id}")
        if r.status_code == 200:
            kg_data = r.json()
    except Exception as e:
        log.warning("Failed to fetch repo detail from API", repo_id=repo_id, exc=e)

    try:
        p = api_client.get(f"/provenance/{repo_id}")
        if p.status_code == 200:
            provenance = p.json()
    except Exception as e:
        log.warning("Failed to fetch provenance from API", repo_id=repo_id, exc=e)

    if repo_path or kg_data.get("path"):
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

    active_scans = {s["repo_id"] for s in list_active_scans()}
    git_info = _repo_git_info(repo_path) if repo_path else {}

    return templates.TemplateResponse("repo_detail.html", {
        **_template_ctx(request),
        "repo_id":     repo_id,
        "repo_path":   repo_path,
        "git":         git_info,
        "kg":          kg_data,
        "provenance":  provenance,
        "stats":       stats,
        "in_registry": repo_id in registry,
        "scanning":    repo_id in active_scans,
        "api_url":     API_URL.replace("http://api:8000", "http://localhost:8000"),
    })


@router.post("/repos/{repo_id:path}/scan")
async def trigger_scan(repo_id: str):
    registry = _load_registry()
    repo_path = registry.get(repo_id)
    if not repo_path:
        raise HTTPException(404, f"{repo_id} not in registry")
    try:
        launch_scan(repo_id, repo_path)
        log.info("Manual scan launched", repo_id=repo_id, path=repo_path)
        return RedirectResponse(f"/repos/{repo_id}?scan=started", status_code=303)
    except Exception as e:
        raise HTTPException(502, f"Could not launch scan container: {e}")


@router.post("/repos/{repo_id:path}/scan/cancel")
async def cancel_repo_scan(repo_id: str):
    from scan_launcher import cancel_scan
    ok = cancel_scan(repo_id)
    return JSONResponse({"cancelled": ok, "repo_id": repo_id})


@router.post("/repos/{repo_id:path}/remove")
async def remove_repo(repo_id: str):
    registry = _load_registry()
    registry.pop(repo_id, None)
    _save_registry(registry)
    log.info("Repo removed from registry", repo_id=repo_id)
    return RedirectResponse("/repos", status_code=303)


@router.get("/api/repos/{repo_id:path}/scan-status")
async def scan_status(repo_id: str):
    active_scans = {s["repo_id"]: s for s in list_active_scans()}
    scanning = repo_id in active_scans
    try:
        r = api_client.get(f"/repos/{repo_id}")
        data = r.json() if r.status_code == 200 else {}
    except Exception as e:
        log.warning("Failed to fetch repo status from API", repo_id=repo_id, exc=e)
        data = {}
    return JSONResponse({**data, "scanning": scanning})
