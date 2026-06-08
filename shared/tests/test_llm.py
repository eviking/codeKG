"""
Unit tests for shared/llm.py.

Coverage scope:
  - _provider_for() selects the correct provider class for each model prefix
  - llm.chat() delegates to the right provider based on model string
  - LLMResponse and LLMUsage normalise Anthropic and OpenAI SDK responses
  - llm.provider_names() returns the three configured providers
  - _AnthropicProvider.list_models() raises RuntimeError when API key absent
  - _OllamaProvider.list_models() prepends 'ollama/' prefix
  - _OllamaProvider.chat() raises RuntimeError when server is unreachable

All SDK calls are mocked — no real API keys or network required.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_SHARED_ROOT = str(Path(__file__).parent.parent.parent)
if _SHARED_ROOT not in sys.path:
    sys.path.insert(0, _SHARED_ROOT)

import pytest
from shared.llm import (
    _provider_for,
    _AnthropicProvider,
    _OpenAIProvider,
    _OllamaProvider,
    LLMResponse,
    LLMUsage,
    llm,
)


class TestProviderSelection:
    """Exercises provider selection behavior in the llm test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_claude_model_returns_anthropic(self):
        """
        A model string starting with 'claude-' must route to _AnthropicProvider.
        Anthropic is the fallback/default provider.
        """
        provider = _provider_for("claude-haiku-4-5")
        assert isinstance(provider, _AnthropicProvider)

    def test_gpt_model_returns_openai(self):
        """
        A model string starting with 'gpt-' must route to _OpenAIProvider.
        """
        provider = _provider_for("gpt-4o-mini")
        assert isinstance(provider, _OpenAIProvider)

    def test_ollama_prefix_returns_ollama(self):
        """
        A model string starting with 'ollama/' must route to _OllamaProvider.
        The prefix is stripped before the model name is sent to the Ollama API.
        """
        provider = _provider_for("ollama/qwen2.5-coder:7b")
        assert isinstance(provider, _OllamaProvider)

    def test_o1_prefix_returns_openai(self):
        """
        OpenAI reasoning models (o1-*, o3-*) must route to _OpenAIProvider.
        """
        provider = _provider_for("o1-preview")
        assert isinstance(provider, _OpenAIProvider)

    def test_unknown_model_falls_back_to_anthropic(self):
        """
        An unrecognised model prefix must fall through to _AnthropicProvider
        as the ultimate fallback, rather than raising an exception.
        """
        provider = _provider_for("some-unknown-model")
        assert isinstance(provider, _AnthropicProvider)


class TestAnthropicProvider:
    """Exercises anthropic provider behavior in the llm test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_chat_produces_correct_response(self):
        """
        _AnthropicProvider.chat() must return an LLMResponse with the text from
        the first content block and correctly mapped usage fields.
        """
        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50
        mock_usage.cache_read_input_tokens = 20

        mock_content = MagicMock()
        mock_content.text = "Hello from Claude"

        mock_raw = MagicMock()
        mock_raw.content = [mock_content]
        mock_raw.model = "claude-haiku-4-5"
        mock_raw.usage = mock_usage

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_raw

        provider = _AnthropicProvider()
        provider._client = mock_client

        resp = provider.chat("claude-haiku-4-5", "Hi", system="You are helpful.")

        assert isinstance(resp, LLMResponse)
        assert resp.text == "Hello from Claude"
        assert resp.usage.input_tokens == 100
        assert resp.usage.output_tokens == 50
        assert resp.usage.cache_read_tokens == 20

    def test_list_models_raises_when_no_api_key(self, monkeypatch):
        """
        _AnthropicProvider.list_models() must raise RuntimeError when
        ANTHROPIC_API_KEY is not set, so operators get a clear error message
        rather than an obscure SDK exception.
        """
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        # Reset cached client so it re-evaluates the key
        provider = _AnthropicProvider()
        provider._client = None

        with patch("shared.config.cfg.llm.anthropic_api_key", ""):
            with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                provider.list_models()


class TestOpenAIProvider:
    """Exercises openai provider behavior in the llm test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_chat_normalises_prompt_tokens_to_input_tokens(self):
        """
        OpenAI's SDK uses 'prompt_tokens' for input; LLMUsage must normalise this
        to input_tokens so callers don't have to know which provider is in use.
        """
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 80
        mock_usage.completion_tokens = 40

        mock_choice = MagicMock()
        mock_choice.message.content = "GPT response"

        mock_raw = MagicMock()
        mock_raw.choices = [mock_choice]
        mock_raw.model = "gpt-4o-mini"
        mock_raw.usage = mock_usage

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_raw

        provider = _OpenAIProvider()
        provider._client = mock_client

        resp = provider.chat("gpt-4o-mini", "Hello")

        assert resp.text == "GPT response"
        assert resp.usage.input_tokens == 80
        assert resp.usage.output_tokens == 40


class TestOllamaProvider:
    """Exercises ollama provider behavior in the llm test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_list_models_prepends_ollama_prefix(self):
        """
        _OllamaProvider.list_models() must prepend 'ollama/' to every model name
        returned by the Ollama API. This prefix is what callers pass to llm.chat()
        to select the Ollama provider.
        """
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"models": [{"name": "qwen2.5-coder:7b"}, {"name": "llama3"}]}

        with patch("requests.get", return_value=mock_resp):
            provider = _OllamaProvider()
            models = provider.list_models()

        assert "ollama/qwen2.5-coder:7b" in models
        assert "ollama/llama3" in models

    def test_list_models_raises_when_server_unreachable(self):
        """
        _OllamaProvider.list_models() must raise RuntimeError when the Ollama
        server is not reachable, with a helpful message pointing to the URL.
        """
        import requests
        with patch("requests.get", side_effect=requests.exceptions.ConnectionError("refused")):
            provider = _OllamaProvider()
            with pytest.raises(RuntimeError):
                provider.list_models()


class TestLLMRouter:
    """Exercises llm router behavior in the llm test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_provider_names_returns_three_providers(self):
        """
        llm.provider_names() must return a list containing 'anthropic', 'openai',
        and 'ollama'. This drives the provider dropdown in the console UI.
        """
        names = llm.provider_names()
        assert "anthropic" in names
        assert "openai" in names
        assert "ollama" in names

    def test_chat_delegates_to_correct_provider(self):
        """
        llm.chat() with a 'gpt-' model must delegate to _OpenAIProvider, not
        _AnthropicProvider. This ensures the router dispatches correctly.
        """
        mock_resp = LLMResponse(text="ok", model="gpt-4o-mini", usage=LLMUsage())

        with patch.object(_OpenAIProvider, "chat", return_value=mock_resp) as mock_chat:
            resp = llm.chat("gpt-4o-mini", "test")

        mock_chat.assert_called_once()
        assert resp.text == "ok"
