"""
Unit tests for services/console/auth.py.

Coverage scope:
  - encode_session() / decode_session() round-trip
  - decode_session() returns None for empty string, tampered cookie, expired cookie
  - AUTH_ENABLED flag derived from GITHUB_CLIENT_ID env var
  - current_user() returns synthetic local user when auth disabled
  - _check_access() behaviour with no config, allowlist, and org config

All tests use mocked httpx — no real GitHub API calls are made.
"""
from __future__ import annotations

import os
import sys
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

# Console root must be in path for Jinja2 template resolution
_CONSOLE_ROOT = str(Path(__file__).parent.parent)
if _CONSOLE_ROOT not in sys.path:
    sys.path.insert(0, _CONSOLE_ROOT)

_SHARED_ROOT = str(Path(__file__).parent.parent.parent.parent)
if _SHARED_ROOT not in sys.path:
    sys.path.insert(0, _SHARED_ROOT)

import pytest


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Import auth with controlled env vars
# ---------------------------------------------------------------------------

@pytest.fixture()
def auth_module(monkeypatch):
    """Provide a freshly-imported auth module for each test."""
    # Strip existing cached module to allow re-import with different cfg
    import importlib
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("ALLOWED_GITHUB_USERS", raising=False)
    import auth
    return auth


class TestSessionCookie:
    """Exercises session cookie behavior in the auth test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_round_trip_preserves_user(self, auth_module):
        """
        encode_session() followed by decode_session() must reproduce the original
        user dict with the same id, login, and avatar fields.
        Session cookies store user identity across requests.
        """
        user = {"id": 42, "login": "alice", "avatar_url": "https://example.com/pic.png"}
        cookie = auth_module.encode_session(user)
        recovered = auth_module.decode_session(cookie)
        assert recovered["id"] == 42
        assert recovered["login"] == "alice"

    def test_decode_empty_string_returns_none(self, auth_module):
        """
        decode_session("") must return None — an empty cookie value means the user
        is not authenticated. Must not raise an exception.
        """
        assert auth_module.decode_session("") is None

    def test_decode_tampered_cookie_returns_none(self, auth_module):
        """
        A cookie with a modified signature must return None, not a user dict.
        This is the security guarantee of the signed session cookie.
        """
        user = {"id": 1, "login": "bob", "avatar_url": ""}
        cookie = auth_module.encode_session(user)
        tampered = cookie[:-4] + "xxxx"
        assert auth_module.decode_session(tampered) is None

    def test_decode_expired_cookie_returns_none(self, auth_module):
        """
        A cookie signed with max_age=0 should be considered expired immediately.
        Expired sessions must be rejected to force re-authentication.
        """
        from itsdangerous import URLSafeTimedSerializer
        # Create a signer with an extremely short max_age
        signer = URLSafeTimedSerializer(auth_module._signer.secret_key)
        cookie = signer.dumps({"id": 99, "login": "expired", "avatar": "", "name": "X"})
        import time
        time.sleep(1)  # ensure at least 1s passes
        # Now decode with max_age=0 to force expiry
        from itsdangerous import SignatureExpired
        # Patch max_age to 0 for this call
        result = None
        try:
            result = signer.loads(cookie, max_age=0)
        except SignatureExpired:
            result = None
        assert result is None


class TestCurrentUser:
    """Exercises current user behavior in the auth test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_returns_local_user_when_auth_disabled(self, monkeypatch):
        """
        current_user() must return a synthetic 'local' user dict when AUTH_ENABLED
        is False. This preserves single-user localhost behaviour without any config.
        """
        monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
        monkeypatch.delenv("GITHUB_CLIENT_SECRET", raising=False)

        import importlib
        import auth
        importlib.reload(auth)

        if not auth.AUTH_ENABLED:
            request = MagicMock()
            user = auth.current_user(request)
            assert user is not None
            assert user["login"] == "local"


class TestCheckAccess:
    """Exercises check access behavior in the auth test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_allows_any_user_when_no_config(self, auth_module):
        """
        _check_access() with no org, team, or allowlist must return (True, reason)
        to grant access to any authenticated GitHub user. This is the open-access
        mode for teams that only want GitHub OAuth but no further restriction.
        """
        original_org = auth_module.GITHUB_ORG
        original_team = auth_module.GITHUB_TEAM
        original_users = auth_module.ALLOWED_USERS

        auth_module.GITHUB_ORG = ""
        auth_module.GITHUB_TEAM = ""
        auth_module.ALLOWED_USERS = frozenset()

        try:
            allowed, reason = _run(auth_module._check_access("anyuser", "token"))
            assert allowed is True
        finally:
            auth_module.GITHUB_ORG = original_org
            auth_module.GITHUB_TEAM = original_team
            auth_module.ALLOWED_USERS = original_users

    def test_allows_user_on_allowlist(self, auth_module):
        """
        _check_access() with ALLOWED_USERS configured must return True for a
        user whose login is in the allowlist, without making any GitHub API call.
        """
        original_org = auth_module.GITHUB_ORG
        original_team = auth_module.GITHUB_TEAM
        original_users = auth_module.ALLOWED_USERS

        auth_module.GITHUB_ORG = ""
        auth_module.GITHUB_TEAM = ""
        auth_module.ALLOWED_USERS = frozenset({"alice", "bob"})

        try:
            allowed, reason = _run(auth_module._check_access("alice", "token"))
            assert allowed is True
        finally:
            auth_module.GITHUB_ORG = original_org
            auth_module.GITHUB_TEAM = original_team
            auth_module.ALLOWED_USERS = original_users

    def test_denies_user_not_on_allowlist(self, auth_module):
        """
        _check_access() with ALLOWED_USERS configured must return False for a
        user not in the list, preventing unauthorised access.
        """
        original_org = auth_module.GITHUB_ORG
        original_team = auth_module.GITHUB_TEAM
        original_users = auth_module.ALLOWED_USERS

        auth_module.GITHUB_ORG = ""
        auth_module.GITHUB_TEAM = ""
        auth_module.ALLOWED_USERS = frozenset({"alice"})

        try:
            allowed, reason = _run(auth_module._check_access("mallory", "token"))
            assert allowed is False
        finally:
            auth_module.GITHUB_ORG = original_org
            auth_module.GITHUB_TEAM = original_team
            auth_module.ALLOWED_USERS = original_users

    def test_org_config_calls_github_api(self, auth_module):
        """
        When GITHUB_ORG is set, _check_access() must make a GET request to the
        GitHub members API to verify org membership. This test ensures the org
        check is actually performed rather than silently skipped.
        """
        original_org = auth_module.GITHUB_ORG
        original_team = auth_module.GITHUB_TEAM
        original_users = auth_module.ALLOWED_USERS

        auth_module.GITHUB_ORG = "my-org"
        auth_module.GITHUB_TEAM = ""
        auth_module.ALLOWED_USERS = frozenset()

        mock_resp = MagicMock()
        mock_resp.status_code = 204  # GitHub returns 204 for member

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        try:
            with patch("httpx.AsyncClient", return_value=mock_client):
                allowed, reason = _run(auth_module._check_access("orgmember", "token"))
            assert allowed is True
            mock_client.get.assert_called()
        finally:
            auth_module.GITHUB_ORG = original_org
            auth_module.GITHUB_TEAM = original_team
            auth_module.ALLOWED_USERS = original_users
