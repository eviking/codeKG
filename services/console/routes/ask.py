"""Console routes for the natural-language ask workflow. Watch out for API timeouts and markdown rendering here, because this module turns raw answer payloads into user-facing HTML."""

from __future__ import annotations


import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from shared.config import cfg
from deps import _template_ctx, templates, _api_headers

router = APIRouter()

_http = httpx.Client(base_url=cfg.services.api_url, timeout=120.0, headers=_api_headers())


@router.get("/ask", response_class=HTMLResponse)
async def ask_get(request: Request):
    return templates.TemplateResponse("ask.html", {**_template_ctx(request), "result": None})


@router.post("/ask", response_class=HTMLResponse)
async def ask_post(
    request:  Request,
    question: str = Form(...),
    repo_id:  str = Form(""),
):
    import markdown as md

    ctx            = _template_ctx(request)
    effective_repo = repo_id or ctx["selected_repo"] or None

    try:
        resp = _http.post("/answer", json={"question": question, "repo_id": effective_repo})
        result = resp.json() if resp.status_code == 200 else {"error": f"API error {resp.status_code}", "summary": ""}
    except Exception as exc:
        result = {"error": str(exc), "summary": ""}

    if result.get("summary"):
        result["summary_html"] = md.markdown(
            result["summary"],
            extensions=["fenced_code", "tables", "nl2br"],
        )

    return templates.TemplateResponse("ask.html", {
        **ctx,
        "question": question,
        "repo_id":  effective_repo or "",
        "result":   result,
    })


@router.post("/api/ask")
async def ask_api(request: Request):
    body     = await request.json()
    question = body.get("question", "").strip()
    repo_id  = body.get("repo_id", "") or None
    if not question:
        return JSONResponse({"error": "question is required"}, status_code=400)
    try:
        resp = _http.post("/answer", json={"question": question, "repo_id": repo_id})
        result = resp.json() if resp.status_code == 200 else {"error": f"API error {resp.status_code}"}
    except Exception as exc:
        result = {"error": str(exc)}
    result.pop("request", None)
    return JSONResponse(result)
