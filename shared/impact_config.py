"""
Load per-repo impact vector configuration from <repo_root>/impact_vectors.yaml.
Falls back to hardcoded defaults if the file is absent or malformed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


# ── Signal definition ─────────────────────────────────────────────────────────

@dataclass
class SignalConfig:
    enabled:   bool  = True
    weight:    float = 1.0
    threshold: float = 0.0          # minimum count before signal fires (for count-based signals)
    libs:      list[str] = field(default_factory=list)   # for library-list signals
    patterns:  list[str] = field(default_factory=list)   # for filename-pattern signals


@dataclass
class VectorConfig:
    signals: dict[str, SignalConfig] = field(default_factory=dict)

    def get(self, name: str) -> SignalConfig:
        return self.signals.get(name, SignalConfig())


@dataclass
class ImpactVectorConfig:
    security:      VectorConfig = field(default_factory=VectorConfig)
    availability:  VectorConfig = field(default_factory=VectorConfig)
    performance:   VectorConfig = field(default_factory=VectorConfig)
    observability: VectorConfig = field(default_factory=VectorConfig)
    operations:    VectorConfig = field(default_factory=VectorConfig)
    dependencies:  VectorConfig = field(default_factory=VectorConfig)


# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULTS: dict[str, dict[str, Any]] = {
    "security": {
        "new_external_http_call":   {"enabled": True,  "weight": 1.5},
        "crypto_function_changed":  {"enabled": True,  "weight": 2.0},
        "auth_method_changed":      {"enabled": True,  "weight": 1.5},
        "secret_access_added":      {"enabled": True,  "weight": 1.5},
        "new_third_party_lib":      {"enabled": True,  "weight": 1.0},
        "endpoint_exposed":         {"enabled": True,  "weight": 1.0},
    },
    "availability": {
        "high_fan_in":               {"enabled": True,  "weight": 1.5, "threshold": 5},
        "timeout_param_changed":     {"enabled": True,  "weight": 1.5},
        "retry_pattern_changed":     {"enabled": True,  "weight": 1.5},
        "exception_handling_changed":{"enabled": True,  "weight": 1.0},
        "async_model_changed":       {"enabled": True,  "weight": 1.0},
    },
    "performance": {
        "high_transitive_blast":  {"enabled": True, "weight": 1.0, "threshold": 10},
        "loop_pattern_changed":   {"enabled": True, "weight": 1.0},
        "parallelism_changed":    {"enabled": True, "weight": 1.5},
        "caching_changed":        {"enabled": True, "weight": 1.5},
        "db_query_changed":       {"enabled": True, "weight": 1.0},
        "heavy_lib_imported":     {
            "enabled": True, "weight": 1.0,
            "libs": ["numpy", "pandas", "torch", "tensorflow", "scipy", "dask", "ray"],
        },
    },
    "observability": {
        "net_log_decrease":      {"enabled": True, "weight": 2.0},
        "metric_trace_changed":  {"enabled": True, "weight": 1.5},
        "silent_exception_added":{"enabled": True, "weight": 2.0},
    },
    "operations": {
        "infra_file_changed": {
            "enabled": True, "weight": 1.5,
            "patterns": ["Dockerfile", "docker-compose", ".github/workflows", "Makefile",
                         ".gitlab-ci", "Jenkinsfile", "buildspec", "cloudbuild"],
        },
        "new_migration":     {"enabled": True, "weight": 1.5},
        "env_var_changed":   {"enabled": True, "weight": 1.0},
        "policy_violation":  {"enabled": True, "weight": 1.5},
    },
    "dependencies": {
        "new_package_added":  {"enabled": True, "weight": 2.0},
        "package_removed":    {"enabled": True, "weight": 1.5},
        "heavy_package_added":{
            "enabled": True, "weight": 1.0,
            "libs": ["torch", "tensorflow", "scipy", "numpy", "pandas", "dask", "ray"],
        },
    },
}


def _build_vector(raw: dict) -> VectorConfig:
    signals: dict[str, SignalConfig] = {}
    for name, cfg in raw.items():
        signals[name] = SignalConfig(
            enabled   = bool(cfg.get("enabled", True)),
            weight    = float(cfg.get("weight", 1.0)),
            threshold = float(cfg.get("threshold", 0.0)),
            libs      = list(cfg.get("libs", [])),
            patterns  = list(cfg.get("patterns", [])),
        )
    return VectorConfig(signals=signals)


def _build_defaults() -> ImpactVectorConfig:
    return ImpactVectorConfig(
        security      = _build_vector(_DEFAULTS["security"]),
        availability  = _build_vector(_DEFAULTS["availability"]),
        performance   = _build_vector(_DEFAULTS["performance"]),
        observability = _build_vector(_DEFAULTS["observability"]),
        operations    = _build_vector(_DEFAULTS["operations"]),
        dependencies  = _build_vector(_DEFAULTS["dependencies"]),
    )


def load_config(repo_path: str) -> ImpactVectorConfig:
    """
    Load impact_vectors.yaml from the root of the given repo.
    Merges with defaults so any omitted signals still get their default weight.
    Returns pure defaults if the file is absent or YAML is not installed.
    """
    defaults = _build_defaults()

    if not _HAS_YAML:
        return defaults

    config_file = Path(repo_path) / "impact_vectors.yaml"
    if not config_file.exists():
        return defaults

    try:
        raw = _yaml.safe_load(config_file.read_text()) or {}
    except Exception:
        return defaults

    vectors_raw = raw.get("vectors", {})

    def _merge(vector_name: str, default_vec: VectorConfig) -> VectorConfig:
        user_signals = vectors_raw.get(vector_name, {}).get("signals", {})
        merged: dict[str, SignalConfig] = {}
        # Start from defaults, overlay user values
        for sig_name, default_sig in default_vec.signals.items():
            user = user_signals.get(sig_name, {})
            merged[sig_name] = SignalConfig(
                enabled   = bool(user.get("enabled",   default_sig.enabled)),
                weight    = float(user.get("weight",   default_sig.weight)),
                threshold = float(user.get("threshold",default_sig.threshold)),
                libs      = list(user.get("libs",      default_sig.libs)),
                patterns  = list(user.get("patterns",  default_sig.patterns)),
            )
        # Also add any user-defined signals not in defaults
        for sig_name, user in user_signals.items():
            if sig_name not in merged:
                merged[sig_name] = SignalConfig(
                    enabled   = bool(user.get("enabled", True)),
                    weight    = float(user.get("weight", 1.0)),
                    threshold = float(user.get("threshold", 0.0)),
                    libs      = list(user.get("libs", [])),
                    patterns  = list(user.get("patterns", [])),
                )
        return VectorConfig(signals=merged)

    return ImpactVectorConfig(
        security      = _merge("security",      defaults.security),
        availability  = _merge("availability",  defaults.availability),
        performance   = _merge("performance",   defaults.performance),
        observability = _merge("observability", defaults.observability),
        operations    = _merge("operations",    defaults.operations),
        dependencies  = _merge("dependencies",  defaults.dependencies),
    )
