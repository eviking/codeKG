"""
codeKG centralised configuration.

Every tuneable value in the system is defined here.  Each setting is read from
an environment variable with a documented default.  Environment variables always
win — this file is the fallback, not the override.

Usage in any service::

    from shared.config import cfg

    cfg.neo4j_uri          # bolt://neo4j:7687
    cfg.nl_query_model     # claude-haiku-4-5
    cfg.wire_edges_timeout # 90

All services import from this module.  ``docker-compose.yml`` and ``.env`` are
the only places operators need to look to tune the system.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


# ── Neo4j ─────────────────────────────────────────────────────────────────────

@dataclass
class _Neo4jConfig:
    """Holds Neo4j connection and memory-tuning settings. Watch out for container-specific defaults here, because these values are read both locally and inside Docker."""

    uri:      str = field(default_factory=lambda: _env("NEO4J_URI",      "bolt://neo4j:7687"))
    user:     str = field(default_factory=lambda: _env("NEO4J_USER",     "neo4j"))
    password: str = field(default_factory=lambda: _env("NEO4J_PASSWORD", ""))

    # Memory allocated to the neo4j container (passed via docker-compose env vars)
    heap_initial: str = field(default_factory=lambda: _env("NEO4J_HEAP_INITIAL", "2g"))
    heap_max:     str = field(default_factory=lambda: _env("NEO4J_HEAP_MAX",     "4g"))
    pagecache:    str = field(default_factory=lambda: _env("NEO4J_PAGECACHE",    "2g"))


# ── LLM / AI models ───────────────────────────────────────────────────────────

@dataclass
class _LLMConfig:
    """Holds model names, API keys, and token limits for LLM-backed features. Watch out for provider-specific assumptions here, because different services read different subsets of this config."""

    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY", ""))
    openai_api_key:    str = field(default_factory=lambda: _env("OPENAI_API_KEY",    ""))

    # Model used for natural-language → Cypher translation (fast, cheap)
    nl_query_model: str = field(default_factory=lambda: _env("NL_QUERY_MODEL", "claude-haiku-4-5"))

    # Model used for generating free-text answers (more capable)
    nl_answer_model: str = field(default_factory=lambda: _env("NL_ANSWER_MODEL", "claude-sonnet-4-5"))

    # Model used for policy Cypher compilation
    policy_model: str = field(default_factory=lambda: _env("POLICY_MODEL", "claude-haiku-4-5-20251001"))

    # Model used for class summarisation (Ollama local model by default)
    summary_model: str = field(default_factory=lambda: _env("SUMMARY_MODEL", "qwen2.5-coder:7b"))

    # Ollama base URL — must be reachable from inside Docker containers
    # macOS:  http://host.docker.internal:11434
    # Linux:  http://172.17.0.1:11434  (or configure bridge network)
    ollama_url: str = field(default_factory=lambda: _env("OLLAMA_URL", "http://host.docker.internal:11434"))

    # Token limits per call type
    nl_cypher_max_tokens:  int = field(default_factory=lambda: _env_int("NL_CYPHER_MAX_TOKENS",  600))
    nl_answer_max_tokens:  int = field(default_factory=lambda: _env_int("NL_ANSWER_MAX_TOKENS",  800))
    nl_answer_max_tokens_fast: int = field(default_factory=lambda: _env_int("NL_ANSWER_MAX_TOKENS_FAST", 500))
    policy_max_tokens:     int = field(default_factory=lambda: _env_int("POLICY_MAX_TOKENS",     512))
    summarise_max_tokens:  int = field(default_factory=lambda: _env_int("SUMMARISE_MAX_TOKENS",  4096))


# ── Ingestion ─────────────────────────────────────────────────────────────────

@dataclass
class _IngestionConfig:
    """Holds scan-time tuning for ingestion workers and graph writes. Watch out for timeout changes here, because they can turn large-repo scans from slow into broken."""

    # Number of parallel parse workers (0 = use all CPUs)
    worker_count: int = field(default_factory=lambda: _env_int("WORKER_COUNT", 0))

    # Files processed per batch before writing to Neo4j
    parse_batch_size: int = field(default_factory=lambda: _env_int("PARSE_BATCH_SIZE", 200))

    # Per-query timeout for wire_edges() — prevents Neo4j lock on large repos
    # Do not lower below 30s without load-testing on your largest repo
    wire_edges_timeout: int = field(default_factory=lambda: _env_int("WIRE_EDGES_TIMEOUT", 90))

    # Docker image used for ephemeral scan containers
    ingestion_image: str = field(default_factory=lambda: _env("INGESTION_IMAGE", "codekg-ingestion"))

    # Optional explicit path to summarise_classes.py tool
    # Leave empty to auto-discover from the repo registry
    summarise_tool_path: str = field(default_factory=lambda: _env("SUMMARISE_TOOL_PATH", ""))


# ── Agent Index ───────────────────────────────────────────────────────────────

@dataclass
class _AgentIndexConfig:
    """Holds settings for generating and storing the agent index. Watch out for output-path changes here, because published artifacts and local previews share this config."""

    db_path: str = field(default_factory=lambda: _env("AGENT_INDEX_DB", "/repos/agent_index.db"))

    # Repos with total source LOC below this threshold get a single combined
    # module file instead of per-module files (fewer reads for agents)
    combined_loc_threshold: int = field(
        default_factory=lambda: _env_int("AGENT_INDEX_COMBINED_LOC_THRESHOLD", 2_500)
    )

    # Module count above which the modules overview switches to index mode
    # (one bullet per module instead of full detail blocks)
    large_repo_threshold: int = field(
        default_factory=lambda: _env_int("AGENT_INDEX_LARGE_REPO_THRESHOLD", 100)
    )


# ── Paths ─────────────────────────────────────────────────────────────────────

@dataclass
class _PathsConfig:
    """Holds important filesystem roots used across services. Watch out for host-versus-container paths here, because some callers pass these values straight into subprocesses."""

    repos_path:     str = field(default_factory=lambda: _env("REPOS_PATH",     "/repos"))
    repos_registry: str = field(default_factory=lambda: _env("REPOS_REGISTRY", "/repos/repos.json"))
    host_home:      str = field(default_factory=lambda: _env("HOST_HOME",       ""))
    home_mount:     str = field(default_factory=lambda: _env("HOME_MOUNT",      ""))
    host_repos_path: str = field(default_factory=lambda: _env("HOST_REPOS_PATH", ""))

    telemetry_db:   str = field(default_factory=lambda: _env("TELEMETRY_DB",   "/repos/telemetry.db"))
    llm_audit_db:   str = field(default_factory=lambda: _env("AUDIT_DB_PATH",  "/repos/llm_audit.db"))
    mcp_audit_db:   str = field(default_factory=lambda: _env("MCP_AUDIT_DB",   "/repos/mcp_audit.db"))
    scan_log_db:    str = field(default_factory=lambda: _env("SCAN_LOG_DB",    "/repos/scan_log.db"))


# ── Services ──────────────────────────────────────────────────────────────────

@dataclass
class _ServicesConfig:
    """Holds base URLs and tokens for inter-service calls. Watch out for auth propagation here, because console and MCP requests rely on these defaults being correct."""

    api_url:       str = field(default_factory=lambda: _env("API_URL",       "http://api:8000"))
    api_token:     str = field(default_factory=lambda: _env("API_TOKEN",     ""))
    ingestion_url: str = field(default_factory=lambda: _env("INGESTION_URL", "http://ingestion:8001"))
    console_url:   str = field(default_factory=lambda: _env("CONSOLE_URL",   "http://console:8080"))

    docker_network: str = field(default_factory=lambda: _env("DOCKER_NETWORK", "codekg_codekg"))


# ── Watcher ───────────────────────────────────────────────────────────────────

@dataclass
class _WatcherConfig:
    """Holds scheduling and polling settings for the watcher service. Watch out for aggressive intervals here, because they can create noisy rescans on active repos."""

    # Seconds between repo poll cycles
    poll_interval: int = field(default_factory=lambda: _env_int("POLL_INTERVAL", 30))


# ── MCP ───────────────────────────────────────────────────────────────────────

@dataclass
class _MCPConfig:
    """Holds MCP-service settings. Watch out for external-facing identifiers here, because tool clients may cache them."""

    # "stdio" for local Claude Code integration; "sse" for shared/network access
    transport: str = field(default_factory=lambda: _env("MCP_TRANSPORT", "stdio"))
    port:      int = field(default_factory=lambda: _env_int("MCP_PORT", 8002))
    audit_db:  str = field(default_factory=lambda: _env("MCP_AUDIT_DB", "/repos/mcp_audit.db"))


# ── Console auth ──────────────────────────────────────────────────────────────

@dataclass
class _AuthConfig:
    """Holds authentication and session settings. Watch out for secret and callback values here, because small mistakes can break both login and request authorization."""

    github_client_id:     str = field(default_factory=lambda: _env("GITHUB_CLIENT_ID",     ""))
    github_client_secret: str = field(default_factory=lambda: _env("GITHUB_CLIENT_SECRET", ""))
    session_secret:       str = field(default_factory=lambda: _env("SESSION_SECRET",       "dev-secret-change-me"))
    github_org:           str = field(default_factory=lambda: _env("GITHUB_ORG",           ""))
    github_team:          str = field(default_factory=lambda: _env("GITHUB_TEAM",          ""))
    allowed_users_raw:    str = field(default_factory=lambda: _env("ALLOWED_GITHUB_USERS", ""))

    # Session cookie TTL in seconds (default 30 days)
    session_max_age: int = field(default_factory=lambda: _env_int("SESSION_MAX_AGE", 60 * 60 * 24 * 30))

    @property
    def enabled(self) -> bool:
        return bool(self.github_client_id and self.github_client_secret)

    @property
    def allowed_users(self) -> frozenset[str]:
        return frozenset(u.strip() for u in self.allowed_users_raw.split(",") if u.strip())


# ── Root config object ────────────────────────────────────────────────────────

@dataclass
class _Config:
    """Aggregates all service configuration into one importable object. Watch out for startup-side effects here, because most modules import `cfg` at import time."""

    neo4j:       _Neo4jConfig       = field(default_factory=_Neo4jConfig)
    llm:         _LLMConfig         = field(default_factory=_LLMConfig)
    ingestion:   _IngestionConfig   = field(default_factory=_IngestionConfig)
    agent_index: _AgentIndexConfig  = field(default_factory=_AgentIndexConfig)
    paths:       _PathsConfig       = field(default_factory=_PathsConfig)
    services:    _ServicesConfig    = field(default_factory=_ServicesConfig)
    watcher:     _WatcherConfig     = field(default_factory=_WatcherConfig)
    mcp:         _MCPConfig         = field(default_factory=_MCPConfig)
    auth:        _AuthConfig        = field(default_factory=_AuthConfig)


# Module-level singleton — import this everywhere
cfg = _Config()
