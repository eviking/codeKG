"""Console routes for captured insights and summaries. Watch out for payload shape changes here, because templates expect a stable summary structure."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from deps import _template_ctx, templates, api_client, log

router = APIRouter()

_SCOPE_ORDER = {"system": 0, "module": 1, "class": 2, "method": 3}


_SORT_KEYS = {
    "newest":     lambda e: e.get("saved_at") or "",
    "oldest":     lambda e: e.get("saved_at") or "",
    "confidence": lambda e: e.get("confidence", 0),
    "staleness":  lambda e: e.get("staleness", 0),
}
_SORT_REVERSE = {"newest": True, "oldest": False, "confidence": True, "staleness": True}


@router.get("/insights", response_class=HTMLResponse)
async def insights_page(request: Request):
    ctx = _template_ctx(request)
    include_hidden = request.query_params.get("include_hidden") == "1"
    q    = request.query_params.get("q", "").strip()
    sort = request.query_params.get("sort", "newest")
    if sort not in _SORT_KEYS:
        sort = "newest"

    try:
        params = {"include_hidden": str(include_hidden).lower()}
        repo_id = ctx.get("selected_repo")
        if repo_id:
            params["repo_id"] = repo_id
        entries = api_client.get("/insights/all", params=params).json()
    except Exception as e:
        log.warning("Failed to fetch insights from API", exc=e)
        entries = []

    pending_count = sum(1 for e in entries if not e.get("approved", False))

    if q:
        ql = q.lower()
        entries = [
            e for e in entries
            if ql in (e.get("insight") or "").lower()
            or ql in (e.get("applies_to") or "").lower()
            or ql in (e.get("scope") or "").lower()
        ]

    entries = sorted(entries, key=_SORT_KEYS[sort], reverse=_SORT_REVERSE[sort])

    grouped: dict = {}
    for e in entries:
        scope = e.get("scope", "class")
        key   = e.get("applies_to", "unknown")
        grouped.setdefault(scope, {}).setdefault(key, []).append(e)

    sections = sorted(grouped.items(), key=lambda x: _SCOPE_ORDER.get(x[0], 99))

    return templates.TemplateResponse("insights.html", {
        **ctx,
        "sections":       sections,
        "total":          len(entries),
        "include_hidden": include_hidden,
        "q":              q,
        "sort":           sort,
        "pending_count":  pending_count,
    })


@router.patch("/api/insights/{tk_id}")
async def update_insight(tk_id: str, request: Request):
    body = await request.json()
    try:
        r = api_client.patch(f"/insights/{tk_id}", json=body)
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.delete("/api/insights/{tk_id}")
async def delete_insight(tk_id: str):
    try:
        r = api_client.delete(f"/insights/{tk_id}")
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/api/insights/analyse")
async def analyse_insights(request: Request):
    body = await request.json()
    try:
        r = api_client.post("/insights/analyse", json=body, timeout=120)
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/insights/apply-finding")
async def apply_finding(request: Request):
    body = await request.json()
    try:
        r = api_client.post("/insights/apply-finding", json=body)
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
