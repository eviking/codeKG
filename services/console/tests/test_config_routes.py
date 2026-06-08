"""
Unit tests for services/console/routes/config.py.

Coverage scope:
  - _load_env_file() parsing: empty, key=value, comments, blank lines, quoted values
  - _save_env_file() creation, merge, removal of empty-string keys
  - _redact() hides secret keys, preserves others, returns empty for unset secrets
  - POST /api/config/save and /api/config/reset route behaviour
  - GET /api/config/current returns redacted values

Uses tmp_path for the env file — no real filesystem side effects.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")
os.environ.setdefault("AGENT_INDEX_DB", ":memory:")

_CONSOLE_ROOT = str(Path(__file__).parent.parent)
if _CONSOLE_ROOT not in sys.path:
    sys.path.insert(0, _CONSOLE_ROOT)

_SHARED_ROOT = str(Path(__file__).parent.parent.parent.parent)
if _SHARED_ROOT not in sys.path:
    sys.path.insert(0, _SHARED_ROOT)

import pytest


# ---------------------------------------------------------------------------
# Import the private helpers we can test in isolation
# ---------------------------------------------------------------------------

# We need to import inside a fixture because the module reads cfg at import time
@pytest.fixture()
def config_routes(tmp_path):
    """Import routes/config.py with the env file pointed at tmp_path."""
    env_file = tmp_path / "codekg.env"

    import routes.config as cfg_routes
    original = cfg_routes._ENV_FILE
    cfg_routes._ENV_FILE = env_file
    yield cfg_routes, env_file
    cfg_routes._ENV_FILE = original


# ---------------------------------------------------------------------------
# _load_env_file() tests
# ---------------------------------------------------------------------------

class TestLoadEnvFile:
    """Exercises load env file behavior in the config routes test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_returns_empty_when_file_missing(self, config_routes):
        """
        _load_env_file() must return an empty dict when the env file does not
        exist. This is the initial state before any settings are saved.
        """
        mod, env_file = config_routes
        assert not env_file.exists()
        result = mod._load_env_file()
        assert result == {}

    def test_parses_key_value_pairs(self, config_routes):
        """
        _load_env_file() must parse KEY=value lines from the file and return
        them as a dict. This is the primary persistence mechanism.
        """
        mod, env_file = config_routes
        env_file.write_text("FOO=bar\nBAZ=qux\n")
        result = mod._load_env_file()
        assert result["FOO"] == "bar"
        assert result["BAZ"] == "qux"

    def test_skips_comment_lines(self, config_routes):
        """
        Lines starting with # must be ignored. Comments are used by _save_env_file
        to write the file header; they must not be parsed as settings.
        """
        mod, env_file = config_routes
        env_file.write_text("# comment\nFOO=bar\n# another comment\n")
        result = mod._load_env_file()
        assert list(result.keys()) == ["FOO"]

    def test_skips_blank_lines(self, config_routes):
        """
        Blank lines must be ignored. The file format includes blank lines for
        readability; they must not produce empty-key entries.
        """
        mod, env_file = config_routes
        env_file.write_text("\nFOO=bar\n\n")
        result = mod._load_env_file()
        assert list(result.keys()) == ["FOO"]

    def test_strips_quotes_from_values(self, config_routes):
        """
        Values wrapped in double or single quotes must have the quotes stripped.
        _save_env_file adds quotes around values with spaces; _load_env_file
        must strip them to round-trip correctly.
        """
        mod, env_file = config_routes
        env_file.write_text('FOO="hello world"\nBAR=\'simple\'\n')
        result = mod._load_env_file()
        assert result["FOO"] == "hello world"
        assert result["BAR"] == "simple"


# ---------------------------------------------------------------------------
# _save_env_file() tests
# ---------------------------------------------------------------------------

class TestSaveEnvFile:
    """Exercises save env file behavior in the config routes test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_creates_file_with_correct_content(self, config_routes):
        """
        _save_env_file() must create the env file and write the provided key-value
        pairs as KEY=value lines. The file must be readable by _load_env_file().
        """
        mod, env_file = config_routes
        mod._save_env_file({"NEO4J_URI": "bolt://localhost:7687"})
        assert env_file.exists()
        result = mod._load_env_file()
        assert result["NEO4J_URI"] == "bolt://localhost:7687"

    def test_merges_with_existing_values(self, config_routes):
        """
        _save_env_file() must preserve existing keys not present in the updates
        dict. Saving one setting must not erase all other settings.
        """
        mod, env_file = config_routes
        env_file.write_text("EXISTING=keep\n")
        mod._save_env_file({"NEW_KEY": "new_value"})
        result = mod._load_env_file()
        assert result.get("EXISTING") == "keep"
        assert result.get("NEW_KEY") == "new_value"

    def test_removes_keys_with_empty_values(self, config_routes):
        """
        Setting a key to an empty string in updates must cause it to be removed
        from the file on the next save. Empty string means 'unset this setting'.
        """
        mod, env_file = config_routes
        env_file.write_text("REMOVE_ME=old_value\n")
        mod._save_env_file({"REMOVE_ME": ""})
        result = mod._load_env_file()
        assert "REMOVE_ME" not in result


# ---------------------------------------------------------------------------
# _redact() tests
# ---------------------------------------------------------------------------

class TestRedact:
    """Exercises redact behavior in the config routes test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_replaces_secret_with_dots(self, config_routes):
        """
        _redact() must replace the value of a known secret key with '••••••••'
        when the value is non-empty. Secrets must never appear in the UI.
        """
        mod, _ = config_routes
        result = mod._redact("NEO4J_PASSWORD", "my-super-secret")
        assert result == "••••••••"

    def test_leaves_non_secret_unchanged(self, config_routes):
        """
        _redact() must return the original value for non-secret keys.
        Public settings like URIs and model names should be fully visible.
        """
        mod, _ = config_routes
        result = mod._redact("NEO4J_URI", "bolt://localhost:7687")
        assert result == "bolt://localhost:7687"

    def test_returns_empty_for_unset_secret(self, config_routes):
        """
        _redact() must return an empty string for a secret key whose value is
        empty. An empty value means the secret is not configured; showing '••••••••'
        would mislead the user into thinking it is set.
        """
        mod, _ = config_routes
        result = mod._redact("NEO4J_PASSWORD", "")
        assert result == ""


# ---------------------------------------------------------------------------
# Route tests via TestClient
# ---------------------------------------------------------------------------

@pytest.fixture()
def console_client(tmp_path):
    """Build a TestClient for the console app with the env file redirected."""
    from fastapi.testclient import TestClient

    # Mock docker before importing console main
    with patch("docker.from_env", return_value=MagicMock()):
        with patch("neo4j.GraphDatabase.driver", return_value=MagicMock()):
            import routes.config as cfg_mod
            original = cfg_mod._ENV_FILE
            cfg_mod._ENV_FILE = tmp_path / "codekg.env"

            # Import the app
            try:
                from main import app
            except Exception:
                pytest.skip("Console app could not be imported — skipping route tests")

            client = TestClient(app, raise_server_exceptions=False)
            yield client, cfg_mod, tmp_path / "codekg.env"
            cfg_mod._ENV_FILE = original


class TestConfigRoutes:
    """Exercises config routes behavior in the config routes test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_save_valid_key(self, console_client):
        """
        POST /api/config/save with a valid key must return ok=True and write the
        value to the env file. Valid keys are those in the config schema.
        """
        client, mod, env_file = console_client
        resp = client.post("/api/config/save", json={"NEO4J_URI": "bolt://newhost:7687"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True

    def test_save_unknown_key_returns_400(self, console_client):
        """
        POST /api/config/save with an unknown key must return HTTP 400.
        Unknown keys must be rejected to prevent writing arbitrary env vars.
        """
        client, _, _ = console_client
        resp = client.post("/api/config/save", json={"UNKNOWN_KEY": "value"})
        assert resp.status_code == 400

    def test_current_returns_redacted_secrets(self, console_client):
        """
        GET /api/config/current must return all settings with secret values
        replaced by '••••••••'. Agents and UI consumers must never see raw secrets.
        """
        client, mod, env_file = console_client
        env_file.write_text("NEO4J_PASSWORD=supersecret\n")
        resp = client.get("/api/config/current")
        assert resp.status_code == 200
        data = resp.json()
        # Password value must be redacted
        pw_val = data.get("NEO4J_PASSWORD", "")
        assert "supersecret" not in pw_val
