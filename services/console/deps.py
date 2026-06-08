"""
Shared dependencies injected into every route module.
Import from here — never from main.py.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import git
import httpx
from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from neo4j import GraphDatabase

from shared.config import cfg
from shared.logging.codekg_logger import get_logger

# Imported lazily to avoid circular imports (auth imports deps indirectly via logger)
def _get_current_user(request):
    from auth import current_user
    return current_user(request)

log = get_logger(__name__, service="console")

# Expose top-level aliases used by route modules
API_URL        = cfg.services.api_url
INGESTION_URL  = cfg.services.ingestion_url
REPOS_PATH     = cfg.paths.repos_path
REPOS_REGISTRY = cfg.paths.repos_registry
HOST_HOME      = cfg.paths.host_home


def _api_headers() -> dict:
    """Authorization headers for requests to the API service."""
    if cfg.services.api_token:
        return {"Authorization": f"Bearer {cfg.services.api_token}"}
    return {}


driver           = GraphDatabase.driver(cfg.neo4j.uri, auth=(cfg.neo4j.user, cfg.neo4j.password))
api_client       = httpx.Client(base_url=API_URL,      timeout=30.0, headers=_api_headers())
ingestion_client = httpx.Client(base_url=INGESTION_URL, timeout=10.0)
templates      = Jinja2Templates(directory="templates")


def _highlight_filter(text: str, query: str) -> Markup:
    escaped = escape(text)
    if not query:
        return escaped
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    highlighted = pattern.sub(
        lambda m: f'<mark style="background:#fef08a;color:#1e293b;border-radius:2px;padding:0 1px">{escape(m.group())}</mark>',
        str(escaped),
    )
    return Markup(highlighted)


templates.env.filters["highlight"] = _highlight_filter


def run_query(cypher: str, **params) -> list[dict]:
    with driver.session() as s:
        return [dict(r) for r in s.run(cypher, **params)]


def _load_registry() -> dict[str, str]:
    p = Path(REPOS_REGISTRY)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            return {}
    return {}


def _save_registry(registry: dict[str, str]):
    p = Path(REPOS_REGISTRY)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(registry, indent=2))


def _to_container_path(user_path: str) -> str:
    if HOST_HOME and user_path.startswith(HOST_HOME):
        return "/host-home" + user_path[len(HOST_HOME):]
    return user_path


def _validate_repo_path(path: str) -> tuple[bool, str]:
    p = Path(path)
    if not p.exists():
        return False, f"Path does not exist: {path}"
    if not p.is_dir():
        return False, f"Path is not a directory: {path}"
    if not (p / ".git").exists():
        return False, f"No .git directory found at: {path} — is this a git repository?"
    return True, ""


def _repo_git_info(path: str) -> dict:
    try:
        repo = git.Repo(path)
        return {
            "branch": repo.active_branch.name if not repo.head.is_detached else "detached",
            "last_commit": repo.head.commit.hexsha[:12],
            "last_message": repo.head.commit.message.strip().split("\n")[0][:80],
            "last_author": repo.head.commit.author.name,
        }
    except Exception as e:
        return {"error": str(e)}


def _template_ctx(request: Request, **extra) -> dict:
    registry  = _load_registry()
    all_repos = list(registry.keys())
    selected_repo = (
        request.query_params.get("repo_id")
        or request.cookies.get("selected_repo")
        or (all_repos[0] if all_repos else "")
    )
    if selected_repo and selected_repo not in all_repos:
        selected_repo = all_repos[0] if all_repos else ""
    ctx = {
        "request":       request,
        "current_path":  request.url.path,
        "selected_repo": selected_repo,
        "all_repos":     all_repos,
        "current_user":  _get_current_user(request),
    }
    ctx.update(extra)
    return ctx
