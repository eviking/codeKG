"""
Get Started wizard — shown when no repos are registered.
Walks the user through every step needed to get value from codeKG:
  1. Required config (ANTHROPIC_API_KEY, HOME_MOUNT)
  2. Register + scan a repo
  3. Publish the agent index
  4. Connect the MCP server to Claude Code
  5. (Optional) Generate NL summaries via Ollama
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from shared.config import cfg
from deps import (
    _template_ctx, _load_registry, _to_container_path,
    _validate_repo_path, templates, api_client, log,
)

router = APIRouter()

_ENV_FILE = Path(os.environ.get("REPOS_PATH", "/repos")) / "codekg.env"
_SECRET_KEYS = frozenset({"NEO4J_PASSWORD", "ANTHROPIC_API_KEY", "API_TOKEN",
                           "GITHUB_CLIENT_SECRET", "SESSION_SECRET"})


def _load_env_file() -> dict[str, str]:
    result: dict[str, str] = {}
    if not _ENV_FILE.exists():
        return result
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def _save_env_file(updates: dict[str, str]):
    existing = _load_env_file()
    merged = {**existing, **updates}
    merged = {k: v for k, v in merged.items() if v != ""}
    lines = ["# codeKG persistent configuration", "# Managed by the console", ""]
    for k, v in sorted(merged.items()):
        if " " in v or "#" in v or not v:
            v = f'"{v}"'
        lines.append(f"{k}={v}")
    lines.append("")
    _ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ENV_FILE.write_text("\n".join(lines))


def _wizard_state() -> dict:
    """Compute which steps are done/missing."""
    env = _load_env_file()

    # Step 1: required config
    anthropic_key = cfg.llm.anthropic_api_key or env.get("ANTHROPIC_API_KEY", "")
    home_mount = cfg.paths.host_home or env.get("HOME_MOUNT", "")
    repos_path = cfg.paths.repos_path or env.get("REPOS_PATH", "")
    neo4j_pw = cfg.neo4j.password or env.get("NEO4J_PASSWORD", "")
    config_ok = bool(anthropic_key and home_mount)

    # Step 2: repo registered + scanned
    registry = _load_registry()
    has_repos = len(registry) > 0
    repo_scanned = False
    if has_repos:
        try:
            kg_repos = {r["repo_id"]: r for r in api_client.get("/repos").json()}
            repo_scanned = any(
                kg_repos.get(rid, {}).get("last_commit") for rid in registry
            )
        except Exception:
            repo_scanned = False

    # Step 3: agent index published (any .codekg/INDEX.md exists in any registered repo)
    index_published = False
    for repo_path in registry.values():
        host_path = repo_path
        if host_path.startswith("/host-home") and cfg.paths.host_home:
            host_path = cfg.paths.host_home + host_path[len("/host-home"):]
        if Path(host_path, ".codekg", "INDEX.md").exists():
            index_published = True
            break

    # Step 4: MCP wired (we can't detect this reliably — just track via cookie/session)
    # We return False and let the page show instructions

    return {
        "config_ok": config_ok,
        "has_repos": has_repos,
        "repo_scanned": repo_scanned,
        "index_published": index_published,
        "registry": registry,
        # raw values for the form (redacted display is done in template)
        "anthropic_key_set": bool(anthropic_key),
        "home_mount": home_mount,
        "repos_path": repos_path,
        "neo4j_pw_set": bool(neo4j_pw),
    }


@router.get("/getstarted", response_class=HTMLResponse)
async def getstarted(request: Request):
    state = _wizard_state()
    return templates.TemplateResponse("getstarted.html", {
        **_template_ctx(request),
        **state,
    })


@router.post("/getstarted/config")
async def wizard_save_config(
    request: Request,
    anthropic_api_key: str = Form(""),
    home_mount:        str = Form(""),
    repos_path:        str = Form(""),
    neo4j_password:    str = Form(""),
):
    updates: dict[str, str] = {}
    if anthropic_api_key.strip():
        updates["ANTHROPIC_API_KEY"] = anthropic_api_key.strip()
    if home_mount.strip():
        updates["HOME_MOUNT"] = home_mount.strip().rstrip("/")
    if repos_path.strip():
        updates["REPOS_PATH"] = repos_path.strip().rstrip("/")
    if neo4j_password.strip():
        updates["NEO4J_PASSWORD"] = neo4j_password.strip()
    if updates:
        _save_env_file(updates)
        log.info("Wizard saved config", keys=list(updates.keys()))
    return JSONResponse({"ok": True, "saved": list(updates.keys()),
                         "restart_required": bool(updates)})


@router.post("/getstarted/register")
async def wizard_register_repo(
    request: Request,
    repo_id:   str = Form(...),
    repo_path: str = Form(...),
):
    from scan_launcher import launch_scan
    container_path = _to_container_path(repo_path.strip())
    ok, err = _validate_repo_path(container_path)
    if not ok:
        return JSONResponse({"ok": False, "error": err}, status_code=400)

    from deps import _save_registry
    registry = _load_registry()
    registry[repo_id.strip()] = container_path
    _save_registry(registry)
    log.info("Wizard registered repo", repo_id=repo_id, path=repo_path)

    try:
        launch_scan(repo_id.strip(), container_path)
        return JSONResponse({"ok": True, "scanning": True})
    except Exception as e:
        log.warning("Wizard could not launch scan", repo_id=repo_id, exc=e)
        return JSONResponse({"ok": True, "scanning": False,
                             "warning": f"Registered but scan failed to launch: {e}"})


@router.post("/getstarted/publish")
async def wizard_publish_index(request: Request):
    """Trigger agent index publish for the first registered repo."""
    registry = _load_registry()
    if not registry:
        return JSONResponse({"ok": False, "error": "No repos registered yet"}, status_code=400)
    repo_id = next(iter(registry))
    try:
        r = api_client.post(f"/agent-index/publish?repo_id={repo_id}")
        r.raise_for_status()
        return JSONResponse({"ok": True, "repo_id": repo_id})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/getstarted/status")
async def wizard_status():
    """Polled by JS to refresh step completion state."""
    state = _wizard_state()
    return JSONResponse(state)
