"""
Telemetry console page — shows sessions, turns, and tool calls
collected by the Claude Code Stop hook.
"""
from __future__ import annotations

import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
import httpx

from shared.config import cfg
from deps import _template_ctx, templates, _api_headers, log

router = APIRouter()
_http = httpx.Client(base_url=cfg.services.api_url, timeout=10.0, headers=_api_headers())


@router.get("/telemetry", response_class=HTMLResponse)
async def telemetry_index(request: Request):
    ctx = _template_ctx(request)
    try:
        sessions = _http.get("/telemetry/sessions", params={"limit": 50}).json()
    except Exception as e:
        log.warning("Failed to fetch telemetry sessions", exc=e)
        sessions = []
    return templates.TemplateResponse("telemetry.html", {**ctx, "sessions": sessions})


@router.get("/telemetry/{session_id}", response_class=HTMLResponse)
async def telemetry_detail(request: Request, session_id: str):
    ctx = _template_ctx(request)
    try:
        detail = _http.get(f"/telemetry/sessions/{session_id}").json()
    except Exception as e:
        log.warning("Failed to fetch telemetry session detail", session_id=session_id, exc=e)
        detail = {"session_id": session_id, "turns": []}
    return templates.TemplateResponse("telemetry_detail.html", {
        **ctx, "detail": detail
    })
