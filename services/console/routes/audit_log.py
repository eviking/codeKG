"""Console routes for audit-log views. Watch out for pagination and filtering assumptions here, because operators use these pages to investigate real activity."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from deps import _template_ctx, templates

router = APIRouter()


@router.get("/audit", response_class=HTMLResponse)
async def audit_log(request: Request, source: str = "", limit: int = 200, hours: int = 24):
    from llm_audit import recent_calls, aggregate_stats
    return templates.TemplateResponse("audit.html", {
        **_template_ctx(request),
        "calls":         recent_calls(limit=limit, source_filter=source, hours=hours),
        "stats":         aggregate_stats(hours=hours),
        "source_filter": source,
        "limit":         limit,
        "hours":         hours,
    })
