"""
Architecture Console — web UI for the architecture team.
Route modules live under routes/; shared state lives in deps.py.
"""
# ── Load persistent config overrides before anything else ─────────────────────
# The file /repos/codekg.env is written by the Configuration page and persists
# across container rebuilds (it lives on the host-mounted /repos volume).
# We load it before importing shared.config so its values override defaults.
import os as _os
from pathlib import Path as _Path

_env_file = _Path(_os.environ.get("REPOS_PATH", "/repos")) / "codekg.env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#"):
            continue
        if "=" in _line:
            _k, _, _v = _line.partition("=")
            _k = _k.strip()
            _v = _v.strip().strip('"').strip("'")
            # Only set if not already present in the process environment
            # (environment always wins over the file)
            if _k not in _os.environ:
                _os.environ[_k] = _v
# ─────────────────────────────────────────────────────────────────────────────

import time
import uuid as _uuid

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

import deps as _deps_module
from deps import (
    log,
    run_query as _deps_run_query,
    _load_registry as _deps_load_registry,
    _save_registry as _deps_save_registry,
    _to_container_path as _deps_to_container_path,
    _validate_repo_path as _deps_validate_repo_path,
    _repo_git_info as _deps_repo_git_info,
    HOST_HOME as _deps_host_home,
    driver as _deps_driver,
)
from auth import (
    AUTH_ENABLED, BYPASS_PATHS,
    current_user, router as auth_router,
)
from routes import (
    repos, dashboard, policies, modules, classes,
    patterns, ask, mcp_audit, system_health, audit_log,
    insights, hygiene, agent_index, telemetry, config, getstarted,
)

app = FastAPI(title="CodeKG Architecture Console")


# ---------------------------------------------------------------------------
# Backwards-compatible test patch points
# ---------------------------------------------------------------------------

HOST_HOME = _deps_host_home
driver = _deps_driver
uuid = _uuid

_patterns_read_catalog = patterns._read_catalog
_patterns_write_catalog = patterns._write_catalog
_patterns_load_from_kg = patterns._load_patterns_from_kg
_mcp_audit_query_impl = mcp_audit._query


def run_query(*args, **kwargs):
    return _deps_run_query(*args, **kwargs)


def _load_registry(*args, **kwargs):
    return _deps_load_registry(*args, **kwargs)


def _save_registry(*args, **kwargs):
    return _deps_save_registry(*args, **kwargs)


def _to_container_path(*args, **kwargs):
    if args:
        user_path = args[0]
        if HOST_HOME and user_path.startswith(HOST_HOME):
            return "/host-home" + user_path[len(HOST_HOME):]
        return user_path
    return _deps_to_container_path(*args, **kwargs)


def _validate_repo_path(*args, **kwargs):
    return _deps_validate_repo_path(*args, **kwargs)


def _repo_git_info(*args, **kwargs):
    return _deps_repo_git_info(*args, **kwargs)


def _read_catalog(*args, **kwargs):
    return _patterns_read_catalog(*args, **kwargs)


def _write_catalog(*args, **kwargs):
    return _patterns_write_catalog(*args, **kwargs)


def _load_patterns_from_kg(*args, **kwargs):
    return _patterns_load_from_kg(*args, **kwargs)


def _mcp_audit_query(*args, **kwargs):
    return _mcp_audit_query_impl(*args, **kwargs)


def _run_query_proxy(*args, **kwargs):
    return run_query(*args, **kwargs)


def _load_registry_proxy(*args, **kwargs):
    return _load_registry(*args, **kwargs)


def _save_registry_proxy(*args, **kwargs):
    return _save_registry(*args, **kwargs)


def _to_container_path_proxy(*args, **kwargs):
    return _to_container_path(*args, **kwargs)


def _validate_repo_path_proxy(*args, **kwargs):
    return _validate_repo_path(*args, **kwargs)


def _repo_git_info_proxy(*args, **kwargs):
    return _repo_git_info(*args, **kwargs)


def _read_catalog_proxy(*args, **kwargs):
    return _read_catalog(*args, **kwargs)


def _write_catalog_proxy(*args, **kwargs):
    return _write_catalog(*args, **kwargs)


def _load_patterns_from_kg_proxy(*args, **kwargs):
    return _load_patterns_from_kg(*args, **kwargs)


def _mcp_audit_query_proxy(*args, **kwargs):
    return _mcp_audit_query(*args, **kwargs)


class _AttrProxy:
    def __init__(self, attr_name: str):
        self._attr_name = attr_name

    def __getattr__(self, name: str):
        return getattr(globals()[self._attr_name], name)


_deps_module.run_query = _run_query_proxy
_deps_module._load_registry = _load_registry_proxy
_deps_module._save_registry = _save_registry_proxy
_deps_module._to_container_path = _to_container_path_proxy
_deps_module._validate_repo_path = _validate_repo_path_proxy
_deps_module._repo_git_info = _repo_git_info_proxy
_deps_module.HOST_HOME = HOST_HOME
_deps_module.driver = _AttrProxy("driver")

for _mod in (dashboard, policies, modules, classes, hygiene, agent_index, patterns):
    if hasattr(_mod, "run_query"):
        _mod.run_query = _run_query_proxy

repos._load_registry = _load_registry_proxy
repos._save_registry = _save_registry_proxy
repos._to_container_path = _to_container_path_proxy
repos._validate_repo_path = _validate_repo_path_proxy
repos._repo_git_info = _repo_git_info_proxy
policies.driver = _AttrProxy("driver")
policies.uuid = _AttrProxy("uuid")
modules.driver = _AttrProxy("driver")
patterns.driver = _AttrProxy("driver")
patterns._read_catalog = _read_catalog_proxy
patterns._write_catalog = _write_catalog_proxy
patterns._load_patterns_from_kg = _load_patterns_from_kg_proxy
patterns.HOST_HOME = HOST_HOME
repos.uuid = _AttrProxy("uuid")
mcp_audit._query = _mcp_audit_query_proxy


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Logs console requests along with response timing. Watch out for static-asset noise here, because the middleware intentionally skips those paths."""

    async def dispatch(self, request: Request, call_next):
        start    = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        if not request.url.path.startswith("/static"):
            log.info("HTTP request",
                     method=request.method,
                     path=request.url.path,
                     status=response.status_code,
                     elapsed_ms=elapsed_ms)
        return response


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Gate all console pages behind GitHub OAuth when AUTH_ENABLED.
    Bypassed for the auth routes themselves and /health.
    When auth is disabled (GITHUB_CLIENT_ID not set) every request passes through.
    """
    async def dispatch(self, request: Request, call_next):
        if not AUTH_ENABLED:
            return await call_next(request)
        if request.url.path in BYPASS_PATHS:
            return await call_next(request)

        user = current_user(request)
        if user is None:
            # Redirect to login, preserving the intended destination
            next_url = request.url.path
            if request.url.query:
                next_url += f"?{request.url.query}"
            resp = RedirectResponse(f"/auth/login?next={next_url}")
            return resp

        return await call_next(request)


app.add_middleware(AuthMiddleware)
app.add_middleware(RequestLogMiddleware)

app.include_router(auth_router)
app.include_router(dashboard.router)
app.include_router(repos.router)
app.include_router(policies.router)
app.include_router(modules.router)
app.include_router(classes.router)
app.include_router(patterns.router)
app.include_router(ask.router)
app.include_router(mcp_audit.router)
app.include_router(system_health.router)
app.include_router(audit_log.router)
app.include_router(insights.router)
app.include_router(hygiene.router)
app.include_router(agent_index.router)
app.include_router(telemetry.router)
app.include_router(config.router)
app.include_router(getstarted.router)


@app.get("/health")
def health():
    return {"status": "ok"}


# Run DB migrations once at startup
mcp_audit.migrate(mcp_audit.MCP_AUDIT_DB)
from agent_index.store import init_db as _init_agent_index_db
try:
    _init_agent_index_db()
except OSError as exc:
    log.warning("Failed to init agent-index DB", exc=exc)
