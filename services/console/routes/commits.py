"""Console routes for commit impact analysis pages."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from deps import _template_ctx, templates, api_client, log

router = APIRouter()


def _fetch_commits(repo_id: str | None = None, limit: int = 200) -> list[dict]:
    try:
        params = {"limit": limit}
        if repo_id:
            params["repo_id"] = repo_id
        r = api_client.get("/impact/commits", params=params)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("Failed to fetch commit analyses", exc=e)
    return []


def _fetch_commit(repo_id: str, commit_sha: str) -> dict | None:
    try:
        r = api_client.get(f"/impact/commits/{repo_id}/{commit_sha}")
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("Failed to fetch commit analysis", commit_sha=commit_sha, exc=e)
    return None


@router.get("/commits", response_class=HTMLResponse)
async def commits_list(request: Request, repo_id: str = ""):
    ctx = _template_ctx(request)
    filter_repo = repo_id or ctx.get("selected_repo") or ""
    commits = _fetch_commits(repo_id=filter_repo or None, limit=200)
    return templates.TemplateResponse("commits.html", {
        **ctx,
        "commits":     commits,
        "filter_repo": filter_repo,
    })


@router.get("/commits/{repo_id}/{commit_sha}", response_class=HTMLResponse)
async def commit_detail(request: Request, repo_id: str, commit_sha: str):
    analysis = _fetch_commit(repo_id, commit_sha)
    return templates.TemplateResponse("commit_impact.html", {
        **_template_ctx(request),
        "analysis":  analysis,
        "repo_id":   repo_id,
        "sha":       commit_sha,
        "diff_url":  f"/commits/{repo_id}/{commit_sha}/diff",
    })


@router.get("/commits/{repo_id}/{commit_sha}/diff")
async def commit_diff(repo_id: str, commit_sha: str):
    """Proxy the diff request to the API so the browser can fetch it from the console origin."""
    from fastapi.responses import JSONResponse
    try:
        r = api_client.get(f"/impact/commits/{repo_id}/{commit_sha}/diff")
        return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as e:
        log.warning("Failed to fetch commit diff", commit_sha=commit_sha, exc=e)
        return JSONResponse(content={"error": str(e)}, status_code=502)
