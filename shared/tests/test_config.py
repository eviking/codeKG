"""
Unit tests for shared/config.py.

Coverage scope:
  - Default values returned when env vars are absent
  - Env vars override defaults when set
  - _env_int() default on missing var and on non-integer value
  - _env_bool() truth table for truthy/falsy string values
  - cfg.auth.enabled derived from GITHUB_CLIENT_ID + GITHUB_CLIENT_SECRET
  - cfg.auth.allowed_users parsed from comma-separated string

All tests run in pure Python — no external services.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_SHARED_ROOT = str(Path(__file__).parent.parent.parent)
if _SHARED_ROOT not in sys.path:
    sys.path.insert(0, _SHARED_ROOT)

import pytest

from shared.config import _env_int, _env_bool


# ---------------------------------------------------------------------------
# _env_int() tests
# ---------------------------------------------------------------------------

class TestEnvInt:
    """Exercises env int behavior in the config test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_returns_default_when_var_missing(self, monkeypatch):
        """
        _env_int() should return the default value when the environment variable
        is not set. This ensures safe operation without any explicit configuration.
        """
        monkeypatch.delenv("_TEST_INT_VAR", raising=False)
        assert _env_int("_TEST_INT_VAR", 42) == 42

    def test_returns_int_when_var_set(self, monkeypatch):
        """
        _env_int() should parse and return the integer value when the env var
        contains a valid integer string.
        """
        monkeypatch.setenv("_TEST_INT_VAR", "99")
        assert _env_int("_TEST_INT_VAR", 0) == 99

    def test_returns_default_when_not_integer(self, monkeypatch):
        """
        _env_int() should return the default when the env var contains a
        non-integer value (e.g. 'abc'). This prevents startup crashes from
        misconfigured env vars.
        """
        monkeypatch.setenv("_TEST_INT_VAR", "not-a-number")
        assert _env_int("_TEST_INT_VAR", 7) == 7

    def test_returns_default_when_empty_string(self, monkeypatch):
        """
        _env_int() should return the default when the env var is set to an
        empty string. Empty string means 'not configured'.
        """
        monkeypatch.setenv("_TEST_INT_VAR", "")
        assert _env_int("_TEST_INT_VAR", 5) == 5


# ---------------------------------------------------------------------------
# _env_bool() tests
# ---------------------------------------------------------------------------

class TestEnvBool:
    """Exercises env bool behavior in the config test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    @pytest.mark.parametrize("value", ["true", "1", "yes", "on"])
    def test_truthy_values(self, monkeypatch, value):
        """
        _env_bool() must return True for 'true', '1', 'yes', 'on' (case-insensitive).
        These are the standard truthy representations for boolean env vars.
        """
        monkeypatch.setenv("_TEST_BOOL_VAR", value)
        assert _env_bool("_TEST_BOOL_VAR", False) is True

    @pytest.mark.parametrize("value", ["false", "0", "no", ""])
    def test_falsy_values(self, monkeypatch, value):
        """
        _env_bool() must return False for 'false', '0', 'no', and empty string.
        Empty string is treated as 'not configured' and falls through to the default.
        """
        monkeypatch.setenv("_TEST_BOOL_VAR", value)
        result = _env_bool("_TEST_BOOL_VAR", False)
        assert result is False

    def test_returns_default_when_var_missing(self, monkeypatch):
        """
        _env_bool() should return the default when the variable is not set.
        """
        monkeypatch.delenv("_TEST_BOOL_VAR", raising=False)
        assert _env_bool("_TEST_BOOL_VAR", True) is True


# ---------------------------------------------------------------------------
# cfg.auth tests — re-instantiate _Config after each test
# ---------------------------------------------------------------------------

class TestAuthConfig:
    """Exercises auth config behavior in the config test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def _make_auth(self, **env_overrides):
        """Helper: create a fresh _AuthConfig with controlled env vars."""
        from shared.config import _AuthConfig
        old = {}
        for k, v in env_overrides.items():
            old[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            return _AuthConfig()
        finally:
            for k, prev in old.items():
                if prev is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = prev

    def test_auth_disabled_when_client_id_not_set(self, monkeypatch):
        """
        cfg.auth.enabled must be False when GITHUB_CLIENT_ID is not set.
        This preserves the single-user localhost behaviour without any config.
        """
        monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
        monkeypatch.delenv("GITHUB_CLIENT_SECRET", raising=False)
        from shared.config import _AuthConfig
        auth = _AuthConfig()
        assert auth.enabled is False

    def test_auth_enabled_when_both_keys_set(self, monkeypatch):
        """
        cfg.auth.enabled must be True only when BOTH GITHUB_CLIENT_ID and
        GITHUB_CLIENT_SECRET are set. Missing either one means auth is off.
        """
        monkeypatch.setenv("GITHUB_CLIENT_ID", "client-id")
        monkeypatch.setenv("GITHUB_CLIENT_SECRET", "client-secret")
        from shared.config import _AuthConfig
        auth = _AuthConfig()
        assert auth.enabled is True

    def test_allowed_users_parsed_from_comma_string(self, monkeypatch):
        """
        cfg.auth.allowed_users must return a frozenset of usernames parsed from
        the ALLOWED_GITHUB_USERS comma-separated env var. Extra whitespace must
        be stripped and empty segments ignored.
        """
        monkeypatch.setenv("ALLOWED_GITHUB_USERS", "alice, bob , charlie")
        from shared.config import _AuthConfig
        auth = _AuthConfig()
        assert auth.allowed_users == frozenset({"alice", "bob", "charlie"})

    def test_allowed_users_empty_when_not_set(self, monkeypatch):
        """
        cfg.auth.allowed_users must return an empty frozenset when
        ALLOWED_GITHUB_USERS is not configured.
        """
        monkeypatch.delenv("ALLOWED_GITHUB_USERS", raising=False)
        from shared.config import _AuthConfig
        auth = _AuthConfig()
        assert auth.allowed_users == frozenset()


class TestDefaultValues:
    """Exercises default values behavior in the config test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_neo4j_defaults(self, monkeypatch):
        """
        When no NEO4J_* env vars are set, the config should return safe defaults.
        Defaults ensure the system can start and fail gracefully rather than crash.
        """
        monkeypatch.delenv("NEO4J_URI", raising=False)
        monkeypatch.delenv("NEO4J_USER", raising=False)
        monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
        from shared.config import _Neo4jConfig
        neo = _Neo4jConfig()
        assert neo.uri == "bolt://neo4j:7687"
        assert neo.user == "neo4j"
        assert neo.password == ""

    def test_env_var_overrides_default(self, monkeypatch):
        """
        When an env var is set, its value must override the compiled-in default.
        This is the fundamental requirement for operator-controlled configuration.
        """
        monkeypatch.setenv("NEO4J_URI", "bolt://myhost:7687")
        from shared.config import _Neo4jConfig
        neo = _Neo4jConfig()
        assert neo.uri == "bolt://myhost:7687"
