"""
Agent Indexing routes — UI only. All regen/publish operations proxy to the API.
"""
from __future__ import annotations


import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse

from shared.config import cfg
from deps import _template_ctx, templates, run_query, _api_headers
from agent_index import store

router = APIRouter()

_http = httpx.Client(base_url=cfg.services.api_url, timeout=120.0, headers=_api_headers())


def _api_post(path: str, body: dict) -> dict:
    try:
        r = _http.post(path, json=body)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", e.response.text)
        except ValueError:
            detail = e.response.text
        raise HTTPException(status_code=e.response.status_code, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _table_for_key(file_key: str) -> str:
    return "agent_index_module_files" if file_key.startswith("modules/") or file_key.startswith("insights/module/") else "agent_index_files"


# ── Pages ─────────────────────────────────────────────────────────────────────

@router.get("/agent-index", response_class=HTMLResponse)
async def agent_index_overview(request: Request):
    ctx = _template_ctx(request)
    repo_id = ctx["selected_repo"]
    files = store.list_files(repo_id) if repo_id else []

    # Separate standard files from module-specific files
    standard_files = [f for f in files if not (
        f["file_key"].startswith("modules/") or
        f["file_key"].startswith("insights/module/")
    )]
    module_file_list = [f for f in files if (
        f["file_key"].startswith("modules/") or
        f["file_key"].startswith("insights/module/")
    )]

    # Group standard files by directory for card grid
    standard_grouped: dict[str, list] = {}
    for f in standard_files:
        d = f.get("directory") or "root"
        standard_grouped.setdefault(d, []).append(f)

    # Annotate files with is_empty flag (hidden files with very little content)
    _EMPTY_PHRASES = ("_No ", "not found", "No insights recorded", "No violations detected",
                      "No active policies", "No significant hotspots")
    def _mark_empty(f: dict) -> dict:
        content = f.get("content") or ""
        body_lines = [ln for ln in content.splitlines()
                      if ln.strip() and not ln.startswith("#") and not ln.startswith("_Generated")]
        body = "\n".join(body_lines).strip()
        f["is_empty"] = f.get("hidden") and (
            len(body) < 80 or any(p in body for p in _EMPTY_PHRASES)
        )
        return f
    standard_files   = [_mark_empty(f) for f in standard_files]
    module_file_list = [_mark_empty(f) for f in module_file_list]

    # Module files as a lookup dict for the table
    module_files = {f["file_key"]: f for f in module_file_list}

    modules = run_query(
        "MATCH (m:Module {repo_id: $repo_id}) RETURN m.module_id AS id, m.name AS name ORDER BY m.module_id",
        repo_id=repo_id,
    ) if repo_id else []

    return templates.TemplateResponse("agent_index_overview.html", {
        **ctx,
        "files": files,
        "standard_grouped": standard_grouped,
        "module_files": module_files,
        "modules": modules,
        "has_files": len(standard_files) > 0,
    })


@router.get("/agent-index/file/{file_key:path}", response_class=HTMLResponse)
async def agent_index_file_view(request: Request, file_key: str):
    ctx = _template_ctx(request)
    repo_id = ctx["selected_repo"]
    table = _table_for_key(file_key)
    f = store.get_file(repo_id, file_key, table=table) if repo_id else None
    if not f:
        # Fallback: find by file_key across all repos (first match)
        from agent_index.store import _con
        con = _con()
        row = con.execute(f"SELECT * FROM {table} WHERE file_key=? ORDER BY generated_at DESC LIMIT 1",
                          (file_key,)).fetchone()
        con.close()
        f = dict(row) if row else None
    if not f:
        raise HTTPException(status_code=404, detail="File not found — generate it first")
    import markdown as _md
    import re as _re
    content_html = _md.markdown(
        f.get("content") or "",
        extensions=["tables", "fenced_code"],
    )
    # Strip injected <style> and <script> blocks that bleed from raw HTML
    # in markdown content (e.g. HTML snippets in table cells).
    content_html = _re.sub(r'<style[^>]*>.*?</style>', '', content_html, flags=_re.DOTALL | _re.IGNORECASE)
    content_html = _re.sub(r'<script[^>]*>.*?</script>', '', content_html, flags=_re.DOTALL | _re.IGNORECASE)
    return templates.TemplateResponse("agent_index_file.html", {
        **ctx, "file": f, "file_key": file_key, "content_html": content_html,
    })


# ── API ───────────────────────────────────────────────────────────────────────

@router.post("/api/agent-index/regen-all")
async def api_regen_all(request: Request):
    body    = await request.json()
    repo_id = body.get("repo_id") or ""
    if not repo_id:
        raise HTTPException(status_code=400, detail="repo_id required")
    return _api_post("/agent-index/regen", {"repo_id": repo_id})


@router.post("/api/agent-index/regen")
async def api_regen_file(request: Request):
    body     = await request.json()
    repo_id  = body.get("repo_id") or ""
    file_key = body.get("file_key") or ""
    if not repo_id or not file_key:
        raise HTTPException(status_code=400, detail="repo_id and file_key required")
    return _api_post("/agent-index/regen", {"repo_id": repo_id, "file_key": file_key})


@router.post("/api/agent-index/manual-additions")
async def api_manual_additions(request: Request):
    body     = await request.json()
    repo_id  = body.get("repo_id") or ""
    file_key = body.get("file_key") or ""
    text     = body.get("text") or ""
    table = _table_for_key(file_key)
    ok = store.update_manual_additions(repo_id, file_key, text, table=table)
    return {"ok": ok}


@router.post("/api/agent-index/toggle-hidden")
async def api_toggle_hidden(request: Request):
    body     = await request.json()
    repo_id  = body.get("repo_id") or ""
    file_key = body.get("file_key") or ""
    hidden   = bool(body.get("hidden", False))
    table = _table_for_key(file_key)
    ok = store.toggle_hidden(repo_id, file_key, hidden, table=table)
    return {"ok": ok}


@router.post("/api/agent-index/publish")
async def api_publish(request: Request):
    body    = await request.json()
    repo_id = body.get("repo_id") or ""
    if not repo_id:
        raise HTTPException(status_code=400, detail="repo_id required")
    return _api_post("/agent-index/publish", {"repo_id": repo_id})
