"""
Pure signal functions for commit impact scoring.

Each function takes graph results and/or diff lines and returns a value in [0.0, 1.0].
They are stateless and have no side-effects — safe to call from any context.

Diff lines are the raw unified-diff lines for all files in the commit
(the output of `git diff parent sha` split by newline).
"""
from __future__ import annotations

import re
from typing import Any


# ── Helpers ───────────────────────────────────────────────────────────────────

def _added(diff_lines: list[str]) -> list[str]:
    """Lines added in this commit (start with '+', not '+++')."""
    return [l[1:] for l in diff_lines if l.startswith("+") and not l.startswith("+++")]


def _removed(diff_lines: list[str]) -> list[str]:
    """Lines removed in this commit (start with '-', not '---')."""
    return [l[1:] for l in diff_lines if l.startswith("-") and not l.startswith("---")]


def _any_match(lines: list[str], patterns: list[str], flags: int = re.IGNORECASE) -> list[str]:
    """Return lines matching any of the given regex patterns."""
    combined = "|".join(f"(?:{p})" for p in patterns)
    rx = re.compile(combined, flags)
    return [l for l in lines if rx.search(l)]


def _filenames(diff_lines: list[str]) -> list[str]:
    """Extract filenames from diff --git a/... b/... headers."""
    names = []
    for l in diff_lines:
        m = re.match(r"^diff --git a/(.+) b/(.+)$", l)
        if m:
            names.append(m.group(2))
    return names


# ── Security signals ──────────────────────────────────────────────────────────

def sig_new_external_http_call(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """New external HTTP calls added (requests, httpx, urllib, fetch, axios, curl)."""
    patterns = [
        r"requests\.(get|post|put|patch|delete|head|request)\s*\(",
        r"httpx\.(get|post|put|patch|delete|AsyncClient|Client)\s*\(",
        r"urllib\.request\.(urlopen|urlretrieve)",
        r"urllib2?\.(urlopen|Request)",
        r"\bfetch\s*\(",
        r"axios\.(get|post|put|patch|delete)\s*\(",
        r"curl_exec\s*\(",
        r"http\.(get|post|request)\s*\(",      # Node http module
        r"RestTemplate\b|WebClient\b|HttpClient\b",  # Java
    ]
    hits = _any_match(_added(diff_lines), patterns)
    if not hits:
        return 0.0, ""
    return min(1.0, len(hits) * 0.4), f"{len(hits)} new external HTTP call(s) added"


def sig_crypto_function_changed(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Crypto, hashing, signing, or encryption functions added or removed."""
    patterns = [
        r"\b(encrypt|decrypt|cipher|AES|RSA|DES|hmac|sha\d|md5|bcrypt|scrypt|argon2)\b",
        r"\b(sign|verify|hash|digest)\s*\(",
        r"crypto\.(create|generate|random)",
        r"Cipher|MessageDigest|KeyGenerator|SecretKey",  # Java
        r"hashlib\.(md5|sha|pbkdf2|blake)",
        r"jwt\.(encode|decode|sign|verify)",
        r"SSL\.|TLS\.|ssl\.",
    ]
    added_hits   = _any_match(_added(diff_lines), patterns)
    removed_hits = _any_match(_removed(diff_lines), patterns)
    total = len(added_hits) + len(removed_hits)
    if not total:
        return 0.0, ""
    detail = []
    if added_hits:   detail.append(f"{len(added_hits)} crypto call(s) added")
    if removed_hits: detail.append(f"{len(removed_hits)} crypto call(s) removed")
    return min(1.0, total * 0.35), "; ".join(detail)


def sig_auth_method_changed(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Auth/authz method calls or decorators added or removed."""
    patterns = [
        r"\b(authenticate|authorize|login|logout|is_authenticated|has_permission|"
        r"requires_auth|login_required|permission_required|check_permission|"
        r"verify_token|validate_token|decode_token)\b",
        r"@(login_required|permission_required|requires_auth|authenticated|"
        r"PreAuthorize|Secured|RolesAllowed)",
        r"\b(BasicAuth|BearerToken|OAuth|SAML|LDAP|SSO)\b",
    ]
    added_hits   = _any_match(_added(diff_lines), patterns)
    removed_hits = _any_match(_removed(diff_lines), patterns)
    total = len(added_hits) + len(removed_hits)
    if not total:
        return 0.0, ""
    detail = []
    if added_hits:   detail.append(f"{len(added_hits)} auth call(s) added")
    if removed_hits: detail.append(f"{len(removed_hits)} auth call(s) removed")
    return min(1.0, total * 0.4), "; ".join(detail)


def sig_secret_access_added(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """New secret/credential access patterns added."""
    patterns = [
        r"os\.(environ|getenv)\s*[\[\(]['\"].*?(secret|password|key|token|credential|api_key)",
        r"getenv\s*\(['\"].*?(SECRET|PASSWORD|KEY|TOKEN|API_KEY)",
        r"process\.env\.[A-Z_]*(SECRET|PASSWORD|KEY|TOKEN|API)",
        r"\bSecretManager|ParameterStore|KeyVault|SecretsManager\b",
        r"\.env\b.*?(secret|password|key|token)",
        r"config\[.*(secret|password|api_key|token)",
    ]
    hits = _any_match(_added(diff_lines), patterns)
    if not hits:
        return 0.0, ""
    return min(1.0, len(hits) * 0.5), f"{len(hits)} secret/credential access pattern(s) added"


def sig_new_third_party_lib(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """New import of a third-party library (not stdlib, not relative)."""
    # Look at added import lines — exclude relative imports and known stdlib modules
    _STDLIB = {
        "os", "sys", "re", "io", "abc", "ast", "copy", "math", "json", "csv",
        "time", "uuid", "enum", "typing", "pathlib", "logging", "datetime",
        "hashlib", "itertools", "functools", "collections", "contextlib",
        "threading", "subprocess", "traceback", "unittest", "dataclasses",
    }
    py_imports  = [l for l in _added(diff_lines) if re.match(r"^\s*(import|from)\s+(\w+)", l)]
    new_third_party = []
    for line in py_imports:
        m = re.match(r"^\s*(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)", line)
        if m:
            pkg = m.group(1).split(".")[0]
            if pkg not in _STDLIB and not line.strip().startswith("from ."):
                new_third_party.append(pkg)

    # Also check requirements / package.json added lines
    req_lines = [l for l in _added(diff_lines)
                 if re.match(r"^[a-zA-Z][\w\-]+[>=<!~]", l.strip())]
    total = len(set(new_third_party)) + len(req_lines)
    if not total:
        return 0.0, ""
    pkgs = list(set(new_third_party))[:4]
    detail = f"New imports: {', '.join(pkgs)}" if pkgs else f"{len(req_lines)} new requirement(s)"
    return min(1.0, total * 0.25), detail


def sig_endpoint_exposed(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """HTTP endpoints exposed by affected classes (graph signal)."""
    n = len(graph.get("endpoints", []))
    if n == 0:
        return 0.0, ""
    return min(1.0, n * 0.2), f"{n} HTTP endpoint(s) exposed by affected code"


# ── Availability signals ──────────────────────────────────────────────────────

def sig_high_fan_in(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Affected class has many callers — high blast radius if it breaks."""
    threshold = int(cfg.threshold) if cfg.threshold else 5
    n_callers = len(graph.get("callers", []))
    if n_callers < threshold:
        return 0.0, ""
    return min(1.0, (n_callers - threshold) / 20 + 0.3), \
           f"{n_callers} direct caller(s) — single point of failure risk"


def sig_timeout_param_changed(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Timeout parameters added, removed, or changed."""
    patterns = [
        r"\btimeout\s*=",
        r"\bconnect_timeout\b|\bread_timeout\b|\bwrite_timeout\b",
        r"setTimeout\s*\(|setInterval\s*\(",
        r"\.timeout\s*\(\d",
        r"@Timeout\b|ReadTimeout|ConnectTimeout|SocketTimeout",
    ]
    added_hits   = _any_match(_added(diff_lines), patterns)
    removed_hits = _any_match(_removed(diff_lines), patterns)
    total = len(added_hits) + len(removed_hits)
    if not total:
        return 0.0, ""
    detail = []
    if added_hits:   detail.append(f"{len(added_hits)} timeout param(s) added")
    if removed_hits: detail.append(f"{len(removed_hits)} timeout param(s) removed")
    return min(1.0, total * 0.4), "; ".join(detail)


def sig_retry_pattern_changed(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Retry, circuit-breaker, or fallback logic added or removed."""
    patterns = [
        r"@retry|@Retry|\.retry\(|max_retries\s*=|retry_on\b",
        r"\bcircuit.?breaker\b|CircuitBreaker\b|@CircuitBreaker",
        r"\bfallback\s*=|\bfallbackMethod\b|\.fallback\s*\(",
        r"\bbackoff\b|exponential_backoff|BackoffPolicy",
        r"Resilience4j|Hystrix|Polly\b",
    ]
    added_hits   = _any_match(_added(diff_lines), patterns)
    removed_hits = _any_match(_removed(diff_lines), patterns)
    total = len(added_hits) + len(removed_hits)
    if not total:
        return 0.0, ""
    detail = []
    if added_hits:   detail.append(f"{len(added_hits)} retry/circuit-breaker pattern(s) added")
    if removed_hits: detail.append(f"{len(removed_hits)} retry/circuit-breaker pattern(s) removed")
    return min(1.0, total * 0.45), "; ".join(detail)


def sig_exception_handling_changed(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Exception handling blocks added or removed."""
    patterns = [
        r"^\s*(try\s*:|catch\s*\(|except\s|finally\s*:)",
        r"\bthrows\s+\w+|\braise\s+\w+",
        r"@ExceptionHandler\b|@ControllerAdvice\b",
    ]
    added_hits   = _any_match(_added(diff_lines), patterns)
    removed_hits = _any_match(_removed(diff_lines), patterns)
    total = len(added_hits) + len(removed_hits)
    if not total:
        return 0.0, ""
    detail = []
    if added_hits:   detail.append(f"{len(added_hits)} exception handler(s) added")
    if removed_hits: detail.append(f"{len(removed_hits)} exception handler(s) removed")
    return min(1.0, total * 0.2), "; ".join(detail)


def sig_async_model_changed(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Async/await, Promise, or concurrency model changes."""
    patterns = [
        r"\basync\s+def\b|\basync\s+function\b",
        r"\bawait\s+\w|\bawait\s+\(",
        r"asyncio\.(create_task|gather|run|sleep|wait)",
        r"Promise\.(all|race|allSettled|resolve|reject)",
        r"CompletableFuture\b|@Async\b|ExecutorService\b",
        r"threading\.Thread\b|multiprocessing\.(Process|Pool)",
    ]
    added_hits   = _any_match(_added(diff_lines), patterns)
    removed_hits = _any_match(_removed(diff_lines), patterns)
    total = len(added_hits) + len(removed_hits)
    if not total:
        return 0.0, ""
    detail = []
    if added_hits:   detail.append(f"{len(added_hits)} async/concurrency construct(s) added")
    if removed_hits: detail.append(f"{len(removed_hits)} async/concurrency construct(s) removed")
    return min(1.0, total * 0.3), "; ".join(detail)


# ── Performance signals ───────────────────────────────────────────────────────

def sig_high_transitive_blast(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Many transitive dependents — change propagates far through the import graph."""
    threshold = int(cfg.threshold) if cfg.threshold else 10
    n = len(graph.get("transitive", []))
    if n < threshold:
        return 0.0, ""
    return min(1.0, (n - threshold) / 40 + 0.25), \
           f"{n} transitive dependent(s) in import graph"


def sig_loop_pattern_changed(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Loop constructs added inside methods — potential O(n) or O(n²) cost."""
    patterns = [
        r"^\s+(for\s+\w+\s+in\b|for\s*\(|while\s*\(|forEach\s*\(|\.map\s*\(|\.filter\s*\()",
        r"\.stream\(\).*\.(map|filter|reduce|collect)\(",
    ]
    hits = _any_match(_added(diff_lines), patterns)
    if not hits:
        return 0.0, ""
    return min(1.0, len(hits) * 0.2), f"{len(hits)} loop/iteration construct(s) added"


def sig_parallelism_changed(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Parallel execution constructs added or removed."""
    patterns = [
        r"asyncio\.(gather|create_task|wait|run_in_executor)",
        r"ThreadPoolExecutor|ProcessPoolExecutor|concurrent\.futures",
        r"multiprocessing\.(Pool|Process|Queue)",
        r"Promise\.all\b|Promise\.allSettled\b",
        r"parallelStream\(\)|ForkJoinPool\b|@Parallel\b",
        r"ray\.remote|\.delay\(\)|celery\b",
    ]
    added_hits   = _any_match(_added(diff_lines), patterns)
    removed_hits = _any_match(_removed(diff_lines), patterns)
    total = len(added_hits) + len(removed_hits)
    if not total:
        return 0.0, ""
    detail = []
    if added_hits:   detail.append(f"{len(added_hits)} parallelism construct(s) added")
    if removed_hits: detail.append(f"{len(removed_hits)} parallelism construct(s) removed")
    return min(1.0, total * 0.35), "; ".join(detail)


def sig_caching_changed(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Caching added or removed — can mask bugs or expose memory growth."""
    patterns = [
        r"@(lru_cache|cache|cached_property|Cacheable|CacheEvict|CachePut)\b",
        r"\b(lru_cache|functools\.cache|cachetools)\b",
        r"redis\.(get|set|setex|hget|hset)\s*\(",
        r"memcache|Memcached\b",
        r"\.cache\s*=|Cache\(\)|CacheManager\b",
    ]
    added_hits   = _any_match(_added(diff_lines), patterns)
    removed_hits = _any_match(_removed(diff_lines), patterns)
    total = len(added_hits) + len(removed_hits)
    if not total:
        return 0.0, ""
    detail = []
    if added_hits:   detail.append(f"{len(added_hits)} cache operation(s) added")
    if removed_hits: detail.append(f"{len(removed_hits)} cache operation(s) removed")
    return min(1.0, total * 0.4), "; ".join(detail)


def sig_db_query_changed(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Database query patterns added — potential N+1, missing index, or slow scan."""
    patterns = [
        r"\.(query|execute|fetchall|fetchone|fetch|scalar)\s*\(",
        r"SELECT\s+.+\s+FROM\b",
        r"\.(filter|all|get|annotate|aggregate)\s*\(",   # Django ORM
        r"session\.(query|add|delete|commit|flush)",      # SQLAlchemy
        r"@Query\b|JpaRepository\b|EntityManager\b",     # JPA
        r"db\.(find|findOne|aggregate|insertOne|updateOne)",  # MongoDB
    ]
    hits = _any_match(_added(diff_lines), patterns)
    if not hits:
        return 0.0, ""
    return min(1.0, len(hits) * 0.2), f"{len(hits)} database query pattern(s) added"


def sig_heavy_lib_imported(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Heavy compute library (numpy, torch, etc.) newly imported."""
    libs = cfg.libs or ["numpy", "pandas", "torch", "tensorflow", "scipy", "dask", "ray"]
    pattern = r"^\s*(import|from)\s+(" + "|".join(re.escape(l) for l in libs) + r")\b"
    hits = _any_match(_added(diff_lines), [pattern])
    if not hits:
        return 0.0, ""
    found = list({re.search(pattern, l).group(2) for l in hits if re.search(pattern, l)})
    return min(1.0, len(hits) * 0.4), f"Heavy lib(s) imported: {', '.join(found)}"


# ── Observability signals ─────────────────────────────────────────────────────

def sig_net_log_decrease(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Net decrease in logging calls — reduced visibility in production."""
    log_pattern = [r"\b(log|logger|logging)\.(debug|info|warning|error|critical|warn|exception)\s*\("]
    added_logs   = len(_any_match(_added(diff_lines),   log_pattern))
    removed_logs = len(_any_match(_removed(diff_lines), log_pattern))
    net = removed_logs - added_logs
    if net <= 0:
        return 0.0, ""
    return min(1.0, net * 0.3), f"Net {net} log statement(s) removed (−{removed_logs} +{added_logs})"


def sig_metric_trace_changed(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Metrics or tracing instrumentation added or removed."""
    patterns = [
        r"\b(metrics|statsd|prometheus|datadog|newrelic)\.(inc|gauge|histogram|counter|timing)",
        r"(tracer|span)\.(start|finish|log|set_tag|add_event)",
        r"opentelemetry\.|@Timed\b|@Counted\b|MeterRegistry\b",
        r"Sentry\.(capture|add_breadcrumb)|bugsnag\.",
    ]
    added_hits   = _any_match(_added(diff_lines), patterns)
    removed_hits = _any_match(_removed(diff_lines), patterns)
    total = len(added_hits) + len(removed_hits)
    if not total:
        return 0.0, ""
    detail = []
    if added_hits:   detail.append(f"{len(added_hits)} metric/trace call(s) added")
    if removed_hits: detail.append(f"{len(removed_hits)} metric/trace call(s) removed")
    return min(1.0, total * 0.35), "; ".join(detail)


def sig_silent_exception_added(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Bare except/catch blocks that swallow exceptions silently."""
    patterns = [
        r"^\s+except\s*:\s*$",                    # bare except: pass
        r"^\s+except\s+Exception\s*:\s*$",         # except Exception: (nothing)
        r"^\s+except\s*.*pass\s*$",               # except ...: pass
        r"catch\s*\(\s*\w+\s+\w+\s*\)\s*\{\s*\}", # Java: catch (Exception e) {}
        r"\.catch\s*\(\s*\(\s*\)\s*=>\s*\{\s*\}", # JS: .catch(() => {})
    ]
    hits = _any_match(_added(diff_lines), patterns)
    if not hits:
        return 0.0, ""
    return min(1.0, len(hits) * 0.5), f"{len(hits)} silent exception handler(s) added"


# ── Operations signals ────────────────────────────────────────────────────────

def sig_infra_file_changed(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Infrastructure or CI configuration file changed."""
    patterns = cfg.patterns or [
        "Dockerfile", "docker-compose", ".github/workflows", "Makefile",
        ".gitlab-ci", "Jenkinsfile", "buildspec", "cloudbuild",
    ]
    fnames = _filenames(diff_lines)
    hits = [f for f in fnames if any(p.lower() in f.lower() for p in patterns)]
    if not hits:
        return 0.0, ""
    short = [Path(h).name for h in hits[:3]]
    return min(1.0, len(hits) * 0.4), f"Infra file(s) changed: {', '.join(short)}"


def sig_new_migration(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Database migration file added."""
    fnames = _filenames(diff_lines)
    patterns = [
        r"migrations?/.*\.(py|sql)$",
        r"alembic/versions/",
        r"\d{4}_\d{2}_\d{2}_.*\.sql$",
        r"V\d+__.*\.sql$",   # Flyway
        r"changelog.*\.xml$",  # Liquibase
    ]
    hits = [f for f in fnames if any(re.search(p, f, re.IGNORECASE) for p in patterns)]
    if not hits:
        return 0.0, ""
    return min(1.0, len(hits) * 0.6), f"{len(hits)} migration file(s) added/changed"


def sig_env_var_changed(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Environment variable definitions added or removed."""
    patterns = [
        r"^[A-Z_]{3,}\s*=",                       # .env file lines
        r"os\.(environ\[|getenv\s*\()['\"]([A-Z_]{3,})",
        r"process\.env\.([A-Z_]{3,})",
        r"ENV\s+[A-Z_]{3,}=",                      # Dockerfile ENV
    ]
    added_hits   = _any_match(_added(diff_lines), patterns)
    removed_hits = _any_match(_removed(diff_lines), patterns)
    total = len(added_hits) + len(removed_hits)
    if not total:
        return 0.0, ""
    detail = []
    if added_hits:   detail.append(f"{len(added_hits)} env var(s) added")
    if removed_hits: detail.append(f"{len(removed_hits)} env var(s) removed")
    return min(1.0, total * 0.3), "; ".join(detail)


def sig_policy_violation(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Active architectural policy applies to affected modules (graph signal)."""
    n = len(graph.get("policies", []))
    if n == 0:
        return 0.0, ""
    titles = [p.get("title", "") for p in graph["policies"][:3]]
    return min(1.0, n * 0.25), f"{n} active polic{'y' if n == 1 else 'ies'} apply: {', '.join(titles)}"


# ── Dependency signals ────────────────────────────────────────────────────────

def _dep_manifest_files(diff_lines: list[str]) -> list[str]:
    manifests = [
        "requirements.txt", "requirements-", "pyproject.toml", "setup.py", "Pipfile",
        "package.json", "package-lock.json", "yarn.lock",
        "pom.xml", "build.gradle", "build.gradle.kts",
        "Cargo.toml", "Cargo.lock",
        "go.mod", "go.sum",
        "Gemfile", "Gemfile.lock",
        "composer.json",
    ]
    fnames = _filenames(diff_lines)
    return [f for f in fnames if any(m.lower() in f.lower() for m in manifests)]


def sig_new_package_added(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """New package added to a dependency manifest (not just version bump)."""
    manifest_files = _dep_manifest_files(diff_lines)
    if not manifest_files:
        return 0.0, ""
    # Added lines in manifest files that look like new dependencies
    patterns = [
        r"^[a-zA-Z][\w\-\.]+[>=<!~^]",           # requirements.txt / Pipfile
        r'"[a-zA-Z][\w\-\.]+"\s*:\s*"',           # package.json
        r"<dependency>|<groupId>",                 # pom.xml
        r"^\s+[a-zA-Z][\w\-\.]+\s*=\s*\"",        # Cargo.toml / pyproject
        r"^\s+(gem|pod)\s+['\"]",                  # Gemfile
    ]
    hits = _any_match(_added(diff_lines), patterns)
    if not hits:
        return 0.0, ""
    return min(1.0, len(hits) * 0.4), f"{len(hits)} new package line(s) in {len(manifest_files)} manifest(s)"


def sig_package_removed(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Package removed from a dependency manifest."""
    manifest_files = _dep_manifest_files(diff_lines)
    if not manifest_files:
        return 0.0, ""
    patterns = [
        r"^[a-zA-Z][\w\-\.]+[>=<!~^]",
        r'"[a-zA-Z][\w\-\.]+"\s*:\s*"',
        r"<dependency>|<groupId>",
        r"^\s+[a-zA-Z][\w\-\.]+\s*=\s*\"",
    ]
    hits = _any_match(_removed(diff_lines), patterns)
    if not hits:
        return 0.0, ""
    return min(1.0, len(hits) * 0.35), f"{len(hits)} package line(s) removed from manifest(s)"


def sig_heavy_package_added(diff_lines: list[str], graph: dict, cfg: Any) -> tuple[float, str]:
    """Heavy/large package added to a manifest."""
    libs = cfg.libs or ["torch", "tensorflow", "scipy", "numpy", "pandas", "dask", "ray"]
    manifest_files = _dep_manifest_files(diff_lines)
    if not manifest_files:
        return 0.0, ""
    pattern = r"(?i)\b(" + "|".join(re.escape(l) for l in libs) + r")\b"
    hits = _any_match(_added(diff_lines), [pattern])
    if not hits:
        return 0.0, ""
    found = list({re.search(pattern, l, re.IGNORECASE).group(1) for l in hits
                  if re.search(pattern, l, re.IGNORECASE)})
    return min(1.0, len(hits) * 0.5), f"Heavy package(s) added: {', '.join(found)}"


# ── Signal registry ───────────────────────────────────────────────────────────
# Maps signal name → function. Used by the scorer to call the right function.

from pathlib import Path as _Path  # already imported above; re-alias for clarity

SIGNAL_REGISTRY: dict[str, callable] = {
    # security
    "new_external_http_call":    sig_new_external_http_call,
    "crypto_function_changed":   sig_crypto_function_changed,
    "auth_method_changed":       sig_auth_method_changed,
    "secret_access_added":       sig_secret_access_added,
    "new_third_party_lib":       sig_new_third_party_lib,
    "endpoint_exposed":          sig_endpoint_exposed,
    # availability
    "high_fan_in":               sig_high_fan_in,
    "timeout_param_changed":     sig_timeout_param_changed,
    "retry_pattern_changed":     sig_retry_pattern_changed,
    "exception_handling_changed":sig_exception_handling_changed,
    "async_model_changed":       sig_async_model_changed,
    # performance
    "high_transitive_blast":     sig_high_transitive_blast,
    "loop_pattern_changed":      sig_loop_pattern_changed,
    "parallelism_changed":       sig_parallelism_changed,
    "caching_changed":           sig_caching_changed,
    "db_query_changed":          sig_db_query_changed,
    "heavy_lib_imported":        sig_heavy_lib_imported,
    # observability
    "net_log_decrease":          sig_net_log_decrease,
    "metric_trace_changed":      sig_metric_trace_changed,
    "silent_exception_added":    sig_silent_exception_added,
    # operations
    "infra_file_changed":        sig_infra_file_changed,
    "new_migration":             sig_new_migration,
    "env_var_changed":           sig_env_var_changed,
    "policy_violation":          sig_policy_violation,
    # dependencies
    "new_package_added":         sig_new_package_added,
    "package_removed":           sig_package_removed,
    "heavy_package_added":       sig_heavy_package_added,
}
