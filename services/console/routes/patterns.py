"""Console routes for pattern catalog pages. Watch out for detector output shape changes here, because the templates assume named buckets and counts."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from deps import run_query, _template_ctx, templates, driver, HOST_HOME

router = APIRouter()

_CATALOG_FILE = Path(__file__).parent.parent / "pattern_catalog.json"


# ------------------------------------------------------------------
# Pattern catalog helpers
# ------------------------------------------------------------------

def _read_catalog() -> dict:
    return json.loads(_CATALOG_FILE.read_text())


def _write_catalog(data: dict):
    _CATALOG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    for sibling in [
        _CATALOG_FILE.parent.parent / "ingestion" / "pattern_catalog.json",
        _CATALOG_FILE.parent.parent.parent / "shared" / "pattern_catalog.json",
    ]:
        try:
            if sibling.exists():
                sibling.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except OSError:
            pass


def _build_github_url(repo_path: str, last_commit: str, file_path: str) -> str | None:
    try:
        import git as _git
        host_home  = HOST_HOME
        local_path = repo_path
        if local_path.startswith("/host-home") and host_home:
            local_path = host_home + local_path[len("/host-home"):]
        repo       = _git.Repo(local_path)
        remote_url = repo.remotes.origin.url
        remote_url = remote_url.replace("git@github.com:", "https://github.com/")
        remote_url = remote_url.removesuffix(".git")
        abs_repo   = str(Path(local_path).resolve())
        abs_file   = file_path
        if abs_file.startswith("/host-home") and host_home:
            abs_file = host_home + abs_file[len("/host-home"):]
        abs_file = str(Path(abs_file).resolve())
        if abs_file.startswith(abs_repo):
            rel = abs_file[len(abs_repo):].lstrip("/")
            sha = last_commit[:40] if last_commit else "main"
            return f"{remote_url}/blob/{sha}/{rel}"
    except Exception:  # git operations can raise many types — URL is optional
        pass
    return None


def _load_patterns_from_kg(repo_id: str) -> list[dict]:
    from pattern_detector import _load_catalog as _cat_loader
    scope = "AND ap.repo_id = $repo_id" if repo_id else ""
    rows  = run_query(
        f"MATCH (ap:ArchPattern) WHERE 1=1 {scope} RETURN ap "
        "ORDER BY ap.anti_pattern DESC, ap.severity, ap.match_count DESC",
        repo_id=repo_id,
    )
    if not rows:
        return []

    repo_rows  = run_query(
        "MATCH (r:Repository {repo_id: $rid}) RETURN r.path AS path, r.last_commit AS commit",
        rid=repo_id,
    ) if repo_id else []
    repo_path  = repo_rows[0]["path"]   if repo_rows else None
    last_commit = repo_rows[0]["commit"] if repo_rows else None

    sample_scope = "AND ap.repo_id = $repo_id" if repo_id else ""
    sample_rows  = run_query(
        f"MATCH (c)-[:EXHIBITS]->(ap:ArchPattern) WHERE 1=1 {sample_scope} "
        "RETURN ap.pattern_id AS pattern_id, c.fqn AS fqn, c.file_path AS file_path, c.name AS name "
        "ORDER BY ap.pattern_id, c.fqn",
        repo_id=repo_id,
    )

    samples_by_pattern: dict = defaultdict(list)
    for sr in sample_rows:
        pid = sr["pattern_id"]
        fp  = sr.get("file_path") or ""
        github_url = _build_github_url(repo_path, last_commit, fp) if (repo_path and fp) else None
        samples_by_pattern[pid].append({
            "fqn": sr["fqn"], "name": sr["name"],
            "file_path": fp, "github_url": github_url,
        })

    catalog = {p["id"]: p for p in _cat_loader()}
    results = []
    for row in rows:
        ap  = dict(row["ap"])
        pid = ap.get("pattern_id", "")
        rid = ap.get("repo_id", "")
        catalog_key = pid[: -(len(rid) + 1)] if rid and pid.endswith(f"-{rid}") else pid
        catalog_entry = catalog.get(catalog_key) or {
            "id": catalog_key, "name": ap.get("name", ""),
            "source": ap.get("source", "Custom"), "category": ap.get("category", ""),
            "intent": ap.get("intent", ""), "anti_pattern": ap.get("anti_pattern", False),
            "severity": ap.get("severity", "info"), "signals": {},
        }
        top_packages = ap.get("top_packages", "[]")
        if isinstance(top_packages, str):
            try:
                top_packages = json.loads(top_packages)
            except ValueError:
                top_packages = []
        results.append({
            "pattern":       catalog_entry,
            "match_count":   ap.get("match_count", 0),
            "sample_classes": [s["fqn"] for s in samples_by_pattern.get(pid, [])],
            "top_packages":  top_packages,
            "matches":       samples_by_pattern.get(pid, []),
        })
    return results


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@router.get("/patterns", response_class=HTMLResponse)
async def patterns_list(request: Request):
    ctx           = _template_ctx(request)
    effective_repo = ctx["selected_repo"]
    return templates.TemplateResponse("patterns.html", {
        **ctx,
        "repo_id": effective_repo,
        "results": _load_patterns_from_kg(effective_repo) or None,
    })


@router.post("/patterns", response_class=HTMLResponse)
async def patterns_detect(request: Request, repo_id: str = Form("")):
    from pattern_detector import detect_patterns, save_patterns_to_kg
    ctx           = _template_ctx(request)
    effective_repo = repo_id or ctx["selected_repo"]
    results = detect_patterns(driver, repo_id=effective_repo or None)
    save_patterns_to_kg(driver, results, repo_id=effective_repo or None)
    return templates.TemplateResponse("patterns.html", {
        **ctx,
        "repo_id": effective_repo,
        "results": results,
    })


@router.get("/pattern-catalog", response_class=HTMLResponse)
async def pattern_catalog_page(request: Request):
    ctx      = _template_ctx(request)
    catalog  = _read_catalog()
    patterns = catalog.get("patterns", [])
    for p in patterns:
        p.setdefault("enabled", True)
        p.setdefault("description", "")
        p.setdefault("when_to_apply", "")
    return templates.TemplateResponse("pattern_catalog.html", {
        **ctx,
        "patterns":      patterns,
        "patterns_json": json.dumps(patterns),
    })


@router.patch("/pattern-catalog/{pattern_id}")
async def pattern_catalog_update(pattern_id: str, request: Request):
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"ok": False, "error": "invalid JSON"}, status_code=400)

    EDITABLE = {"name", "source", "category", "language", "severity",
                "anti_pattern", "intent", "description", "when_to_apply"}
    catalog  = _read_catalog()
    patterns = catalog.get("patterns", [])
    matched  = next((p for p in patterns if p["id"] == pattern_id), None)
    if not matched:
        return JSONResponse({"ok": False, "error": "pattern not found"}, status_code=404)
    for key, val in body.items():
        if key in EDITABLE:
            matched[key] = val
    try:
        _write_catalog(catalog)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    return JSONResponse({"ok": True, "id": pattern_id})


@router.post("/pattern-catalog/{pattern_id}/toggle")
async def pattern_catalog_toggle(pattern_id: str, request: Request):
    try:
        body    = await request.json()
        enabled = bool(body.get("enabled", True))
    except ValueError:
        return JSONResponse({"ok": False, "error": "invalid JSON"}, status_code=400)

    catalog  = _read_catalog()
    patterns = catalog.get("patterns", [])
    for p in patterns:
        if p["id"] == pattern_id:
            p["enabled"] = enabled
            try:
                _write_catalog(catalog)
            except Exception as exc:
                return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
            return JSONResponse({"ok": True, "id": pattern_id, "enabled": enabled})
    return JSONResponse({"ok": False, "error": "pattern not found"}, status_code=404)
