"""
codeKG unified LLM client.

Wraps Anthropic, OpenAI, and Ollama behind a single interface so every call
site in the codebase can stay provider-agnostic.

Usage
-----
    from shared.llm import llm, LLMResponse

    resp: LLMResponse = llm.chat(
        model="claude-haiku-4-5",          # or "gpt-4o-mini" or "ollama/qwen2.5-coder:7b"
        system="You are a helpful assistant.",
        prompt="Explain Neo4j indexes.",
        max_tokens=600,
    )
    text  = resp.text
    usage = resp.usage   # LLMUsage(input=123, output=456, cache_read=0)

Provider selection
------------------
The provider is inferred from the model string:

  Model prefix           Provider
  ──────────────────     ────────
  gpt-* / o1-* / o3-*   OpenAI
  ollama/<name>          Ollama   (prefix stripped before sending to Ollama)
  (anything else)        Anthropic

Adding a new provider
---------------------
1. Create a class that extends ``_Provider`` and implements ``chat()`` and
   ``list_models()``.
2. Add an entry to ``_REGISTRY`` at the bottom of this file.
3. Optionally add a config entry in ``shared/config.py`` for its API key / URL.

No changes to any call site are needed.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from shared.config import cfg


# ── Normalised response types ─────────────────────────────────────────────────

@dataclass
class LLMUsage:
    """Tracks token usage for one LLM call. Watch out for field completeness here, because cost reporting and audits depend on this record."""

    input_tokens:      int = 0
    output_tokens:     int = 0
    cache_read_tokens: int = 0   # Anthropic prompt-cache reads; 0 for others


@dataclass
class LLMResponse:
    """Normalized response returned by the shared LLM router. Watch out for provider-specific extras here, because callers should rely on this shape instead of raw SDK payloads."""

    text:  str
    model: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    raw:   Any      = field(default=None, repr=False)   # original SDK response


# ── Provider base class ───────────────────────────────────────────────────────

class _Provider(ABC):
    """Implement these two methods to add a new LLM provider."""

    @abstractmethod
    def chat(
        self,
        model: str,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Send a chat completion and return a normalised LLMResponse."""

    @abstractmethod
    def list_models(self) -> list[str]:
        """
        Return a list of model identifiers available from this provider.
        Called live — do not cache here; the router caches the result.
        Raise ``RuntimeError`` with a human-readable message if the provider
        is not configured (missing API key, unreachable server, etc.).
        """


# ── Anthropic ─────────────────────────────────────────────────────────────────

class _AnthropicProvider(_Provider):
    """Anthropic-backed implementation of the shared provider interface. Watch out for model and message-shape differences here, because this adapter smooths them into the repo's common contract."""

    _client = None

    def _get(self):
        if self._client is None:
            import anthropic as _sdk
            key = cfg.llm.anthropic_api_key
            if not key:
                raise RuntimeError("ANTHROPIC_API_KEY is not set")
            self._client = _sdk.Anthropic(api_key=key, timeout=60.0)
        return self._client

    def chat(self, model, prompt, *, system="", max_tokens=1024, temperature=0.0) -> LLMResponse:
        client = self._get()
        kwargs: dict = dict(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system
        # temperature=0 is the default for Anthropic; passing 0 explicitly is fine
        raw = client.messages.create(**kwargs)
        usage = raw.usage
        return LLMResponse(
            text=raw.content[0].text if raw.content else "",
            model=raw.model,
            usage=LLMUsage(
                input_tokens=getattr(usage, "input_tokens", 0),
                output_tokens=getattr(usage, "output_tokens", 0),
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0),
            ),
            raw=raw,
        )

    def list_models(self) -> list[str]:
        client = self._get()
        # Anthropic SDK v0.25+ exposes client.models.list()
        try:
            page = client.models.list()
            return sorted(m.id for m in page.data)
        except Exception:
            # Older SDK or API hiccup — return a stable fallback list
            return [
                "claude-haiku-4-5",
                "claude-haiku-3-5",
                "claude-sonnet-4-5",
                "claude-sonnet-4",
                "claude-opus-4-5",
                "claude-opus-4",
            ]


# ── OpenAI ────────────────────────────────────────────────────────────────────

class _OpenAIProvider(_Provider):
    """OpenAI-backed implementation of the shared provider interface. Watch out for API response drift here, because this adapter translates provider-native payloads into the shared response shape."""

    _client = None

    def _get(self):
        if self._client is None:
            import openai as _sdk
            key = cfg.llm.openai_api_key
            if not key:
                raise RuntimeError("OPENAI_API_KEY is not set")
            self._client = _sdk.OpenAI(api_key=key, timeout=60.0)
        return self._client

    def chat(self, model, prompt, *, system="", max_tokens=1024, temperature=0.0) -> LLMResponse:
        client = self._get()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        raw = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        choice = raw.choices[0]
        usage  = raw.usage
        return LLMResponse(
            text=choice.message.content or "",
            model=raw.model,
            usage=LLMUsage(
                input_tokens=getattr(usage, "prompt_tokens", 0),
                output_tokens=getattr(usage, "completion_tokens", 0),
            ),
            raw=raw,
        )

    def list_models(self) -> list[str]:
        client = self._get()
        models = client.models.list()
        # Filter to chat-capable models only (GPT and o-series)
        chat_prefixes = ("gpt-", "o1-", "o3-", "o4-", "chatgpt-")
        return sorted(
            m.id for m in models.data
            if any(m.id.startswith(p) for p in chat_prefixes)
        )


# ── Ollama ────────────────────────────────────────────────────────────────────

class _OllamaProvider(_Provider):
    """
    Calls a local Ollama server via its REST API.
    Model names are passed with the "ollama/" prefix stripped.
    """

    def _url(self) -> str:
        return cfg.llm.ollama_url.rstrip("/")

    def chat(self, model, prompt, *, system="", max_tokens=1024, temperature=0.0) -> LLMResponse:
        import requests as _req
        # Strip "ollama/" prefix if present
        bare_model = model.removeprefix("ollama/")
        payload: dict = {
            "model":  bare_model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }
        if system:
            payload["system"] = system
        url = f"{self._url()}/api/generate"
        raw = _req.post(url, json=payload, timeout=120).json()
        text = raw.get("response", "")
        # Ollama doesn't report token counts in all versions
        prompt_eval = raw.get("prompt_eval_count", 0) or 0
        eval_count  = raw.get("eval_count", 0) or 0
        return LLMResponse(
            text=text,
            model=bare_model,
            usage=LLMUsage(input_tokens=prompt_eval, output_tokens=eval_count),
            raw=raw,
        )

    def list_models(self) -> list[str]:
        import requests as _req
        url = f"{self._url()}/api/tags"
        try:
            data = _req.get(url, timeout=5).json()
            return sorted(
                f"ollama/{m['name']}" for m in data.get("models", [])
            )
        except Exception as exc:
            raise RuntimeError(
                f"Cannot reach Ollama at {self._url()} — is it running? ({exc})"
            )


# ── Provider registry ─────────────────────────────────────────────────────────
# Map from model-string prefix → provider instance.
# Entries are checked in order; the last entry (empty prefix "") is the fallback.
#
# To add a new provider:
#   1. Create a class above that extends _Provider
#   2. Add it here with its model-string prefix(es)

_REGISTRY: list[tuple[str, _Provider]] = [
    ("gpt-",      _OpenAIProvider()),
    ("o1-",       _OpenAIProvider()),
    ("o3-",       _OpenAIProvider()),
    ("o4-",       _OpenAIProvider()),
    ("chatgpt-",  _OpenAIProvider()),
    ("ollama/",   _OllamaProvider()),
    ("",          _AnthropicProvider()),   # fallback — catches claude-* and anything else
]

# Deduplicated provider instances for list_models()
_PROVIDERS: dict[str, _Provider] = {
    "anthropic": _AnthropicProvider(),
    "openai":    _OpenAIProvider(),
    "ollama":    _OllamaProvider(),
}


def _provider_for(model: str) -> _Provider:
    """Return the right provider for a given model string."""
    for prefix, provider in _REGISTRY:
        if model.startswith(prefix):
            return provider
    return _AnthropicProvider()   # ultimate fallback


# ── Public router ─────────────────────────────────────────────────────────────

class _LLMRouter:
    """
    Single call point used everywhere in the codebase.

        from shared.llm import llm
        resp = llm.chat(model="gpt-4o-mini", prompt="hello")
    """

    def chat(
        self,
        model: str,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        provider = _provider_for(model)
        return provider.chat(
            model, prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def list_models(self, provider_name: str) -> list[str]:
        """
        List models available from a specific provider.
        ``provider_name`` must be a key in _PROVIDERS.
        Raises ``RuntimeError`` with a user-friendly message when not configured.
        """
        p = _PROVIDERS.get(provider_name)
        if p is None:
            raise RuntimeError(f"Unknown provider: {provider_name!r}")
        return p.list_models()

    def provider_names(self) -> list[str]:
        """Return the list of known provider names."""
        return list(_PROVIDERS.keys())


# Module-level singleton
llm = _LLMRouter()
