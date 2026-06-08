"""
GitHub OAuth2 authentication for the codeKG console.

Access control (evaluated in priority order):
  1. GITHUB_ORG + GITHUB_TEAM  — org team membership
  2. GITHUB_ORG                — org membership
  3. ALLOWED_GITHUB_USERS      — comma-separated allowlist
  4. (nothing set)             — any authenticated GitHub user

Auth is completely disabled (all requests pass through) when GITHUB_CLIENT_ID
is not set — preserving the existing single-user localhost behaviour.

Session:
  Stored in a signed, timed cookie ("session"). The cookie payload contains
  GitHub user id, login, and avatar_url. No server-side session store required.
  Cookies are signed with SESSION_SECRET via itsdangerous; tampering is detected
  and treated as unauthenticated.
"""
from __future__ import annotations

import secrets
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from shared.config import cfg
from shared.logging.codekg_logger import get_logger

log = get_logger(__name__, service="console")

# ── Configuration (sourced from shared cfg) ───────────────────────────────────

GITHUB_CLIENT_ID     = cfg.auth.github_client_id
GITHUB_CLIENT_SECRET = cfg.auth.github_client_secret
GITHUB_ORG           = cfg.auth.github_org
GITHUB_TEAM          = cfg.auth.github_team
ALLOWED_USERS        = cfg.auth.allowed_users

AUTH_ENABLED = cfg.auth.enabled

# Paths that bypass auth entirely (callback + health)
BYPASS_PATHS = frozenset({"/auth/login", "/auth/callback", "/auth/logout", "/health"})

_SESSION_MAX_AGE = cfg.auth.session_max_age

_signer = URLSafeTimedSerializer(cfg.auth.session_secret)

# ── GitHub OAuth scope ────────────────────────────────────────────────────────
# read:user  — always required (username, avatar)
# read:org   — required when GITHUB_ORG is set (org/team membership checks)

def _oauth_scope() -> str:
    return "read:user read:org" if GITHUB_ORG else "read:user"


# ── Session helpers ───────────────────────────────────────────────────────────

def encode_session(user: dict) -> str:
    """Sign a session payload for storage in a cookie."""
    payload = {
        "id":     user["id"],
        "login":  user["login"],
        "avatar": user.get("avatar_url", ""),
        "name":   user.get("name") or user["login"],
    }
    return _signer.dumps(payload)


def decode_session(cookie: str) -> Optional[dict]:
    """
    Verify and decode a session cookie.
    Returns None if the cookie is missing, expired, or tampered with.
    """
    if not cookie:
        return None
    try:
        return _signer.loads(cookie, max_age=_SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def current_user(request: Request) -> Optional[dict]:
    """Extract the authenticated user from the request, or None."""
    if not AUTH_ENABLED:
        return {"id": 0, "login": "local", "avatar": "", "name": "Local User"}
    return decode_session(request.cookies.get("session", ""))


# ── Access control ────────────────────────────────────────────────────────────

async def _check_access(login: str, access_token: str) -> tuple[bool, str]:
    """
    Check whether a GitHub user is permitted to access this codeKG instance.
    Returns (allowed, reason).
    """
    async with httpx.AsyncClient(timeout=10.0) as gh:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        # ── Priority 1: org + team ────────────────────────────────────────────
        if GITHUB_ORG and GITHUB_TEAM:
            r = await gh.get(
                f"https://api.github.com/orgs/{GITHUB_ORG}/teams/{GITHUB_TEAM}/memberships/{login}",
                headers=headers,
            )
            if r.status_code == 200 and r.json().get("state") == "active":
                return True, f"member of {GITHUB_ORG}/{GITHUB_TEAM}"
            return False, f"not an active member of team {GITHUB_ORG}/{GITHUB_TEAM}"

        # ── Priority 2: org only ──────────────────────────────────────────────
        if GITHUB_ORG:
            r = await gh.get(
                f"https://api.github.com/orgs/{GITHUB_ORG}/members/{login}",
                headers=headers,
            )
            if r.status_code == 204:
                return True, f"member of {GITHUB_ORG}"
            return False, f"not a member of {GITHUB_ORG}"

        # ── Priority 3: allowlist ─────────────────────────────────────────────
        if ALLOWED_USERS:
            if login in ALLOWED_USERS:
                return True, "on allowlist"
            return False, f"@{login} is not on the allowed users list"

    # ── Priority 4: any authenticated GitHub user ─────────────────────────────
    return True, "open access"


# ── Login page template ───────────────────────────────────────────────────────

def _access_denied_html(login: str, reason: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Access Denied — CodeKG</title>
<style>
  body {{ font-family: Inter, system-ui, sans-serif; background: #f8f9fb;
         display: flex; align-items: center; justify-content: center;
         min-height: 100vh; margin: 0; }}
  .card {{ background: #fff; border: 1px solid #e2e7ef; border-radius: 12px;
           padding: 2.5rem 3rem; text-align: center; max-width: 420px;
           box-shadow: 0 4px 12px rgba(15,23,42,.08); }}
  h1 {{ font-size: 1.25rem; color: #0f172a; margin-bottom: .5rem; }}
  p  {{ color: #64748b; font-size: .9rem; margin-bottom: 1.5rem; line-height: 1.6; }}
  .user {{ color: #0f172a; font-weight: 600; }}
  a  {{ display: inline-block; padding: .55rem 1.25rem;
        background: #16a34a; color: #fff; border-radius: 8px;
        font-size: .875rem; font-weight: 500; text-decoration: none; }}
  a:hover {{ background: #15803d; }}
</style></head>
<body>
<div class="card">
  <h1>Access Denied</h1>
  <p>Signed in as <span class="user">@{login}</span> but {reason}.</p>
  <p>Contact your codeKG administrator to request access.</p>
  <a href="/auth/logout">Sign out</a>
</div>
</body></html>"""


def _login_page_html(next_url: str = "/") -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Sign in — CodeKG</title>
<style>
  body {{ font-family: Inter, system-ui, sans-serif; background: #f8f9fb;
         display: flex; align-items: center; justify-content: center;
         min-height: 100vh; margin: 0; }}
  .card {{ background: #fff; border: 1px solid #e2e7ef; border-radius: 12px;
           padding: 2.5rem 3rem; text-align: center; max-width: 380px;
           box-shadow: 0 4px 12px rgba(15,23,42,.08); }}
  .brand {{ font-size: 1.5rem; font-weight: 700; color: #0f172a; margin-bottom: .25rem; }}
  .brand span {{ color: #16a34a; }}
  p {{ color: #64748b; font-size: .875rem; margin: .75rem 0 1.75rem; }}
  a.gh-btn {{
    display: inline-flex; align-items: center; gap: .5rem;
    padding: .6rem 1.4rem; background: #0f172a; color: #fff;
    border-radius: 8px; font-size: .875rem; font-weight: 500;
    text-decoration: none; transition: background .15s;
  }}
  a.gh-btn:hover {{ background: #1e293b; }}
  a.gh-btn svg {{ flex-shrink: 0; }}
</style></head>
<body>
<div class="card">
  <div class="brand">Code<span>KG</span></div>
  <p>Sign in to access the codebase intelligence console.</p>
  <a class="gh-btn" href="/auth/login?next={next_url}">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57
               0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695
               -.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99
               .105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225
               -.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405
               c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225
               0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3
               0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
    </svg>
    Continue with GitHub
  </a>
</div>
</body></html>"""


# ── Router ────────────────────────────────────────────────────────────────────

router = APIRouter()


@router.get("/auth/login", include_in_schema=False)
async def login(request: Request, next: str = "/"):
    if not AUTH_ENABLED:
        return RedirectResponse(next or "/")

    state = secrets.token_urlsafe(20)
    scope = _oauth_scope()
    github_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&scope={scope}"
        f"&state={state}"
    )
    resp = RedirectResponse(github_url)
    resp.set_cookie("oauth_state", state, max_age=300, httponly=True, samesite="lax")
    resp.set_cookie("oauth_next",  next,  max_age=300, httponly=True, samesite="lax")
    return resp


@router.get("/auth/callback", include_in_schema=False)
async def callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        log.warning("GitHub OAuth error", error=error)
        return RedirectResponse("/auth/login")

    # CSRF check
    expected_state = request.cookies.get("oauth_state", "")
    if not secrets.compare_digest(state, expected_state) if expected_state else True:
        log.warning("OAuth state mismatch — possible CSRF", remote=request.client.host)
        return RedirectResponse("/auth/login")

    next_url = request.cookies.get("oauth_next", "/")

    async with httpx.AsyncClient(timeout=15.0) as gh:
        # Exchange code for access token
        token_resp = await gh.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id":     GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code":          code,
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            log.error("Token exchange failed", status=token_resp.status_code)
            return RedirectResponse("/auth/login")

        token_data   = token_resp.json()
        access_token = token_data.get("access_token", "")
        if not access_token:
            log.error("No access_token in GitHub response", resp=str(token_data)[:200])
            return RedirectResponse("/auth/login")

        # Fetch user profile
        user_resp = await gh.get(
            "https://api.github.com/user",
            headers={
                "Authorization":        f"Bearer {access_token}",
                "Accept":               "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if user_resp.status_code != 200:
            log.error("GitHub /user failed", status=user_resp.status_code)
            return RedirectResponse("/auth/login")
        user = user_resp.json()

    login_name = user.get("login", "")
    log.info("GitHub auth callback", login=login_name)

    # Access control
    allowed, reason = await _check_access(login_name, access_token)
    if not allowed:
        log.warning("Access denied", login=login_name, reason=reason)
        return HTMLResponse(_access_denied_html(login_name, reason), status_code=403)

    log.info("Access granted", login=login_name, reason=reason)

    session_cookie = encode_session(user)
    resp = RedirectResponse(next_url or "/", status_code=302)
    resp.set_cookie(
        "session",
        session_cookie,
        max_age=_SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,   # set True when behind HTTPS in production
    )
    resp.delete_cookie("oauth_state")
    resp.delete_cookie("oauth_next")
    return resp


@router.get("/auth/logout", include_in_schema=False)
async def logout():
    resp = RedirectResponse("/auth/login")
    resp.delete_cookie("session")
    return resp
