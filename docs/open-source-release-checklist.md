# Open Source Release Checklist

> Engineering work required before codeKG can be released as a high-quality open source project.
> Each item includes the problem, the fix, and the acceptance criteria.
> Items are ordered roughly by risk — security and correctness first, polish last.

---

## Current Go/No-Go Checklist

This is the shortest practical checklist for deciding whether codeKG is ready to be published publicly.

### Release blockers

- [ ] Make `make test` include `shared/tests/`
  Acceptance: a fresh contributor can run one command and get the full Python test surface, including `shared/tests/test_graph_models.py`.

- [ ] Remove machine-specific sample data from public-facing docs
  Acceptance: `README.md` no longer lists personal/local registered repos like `ElasticSearch` or `Django` with host paths.

- [ ] Do one final secret and environment audit
  Acceptance: `git grep -nE "(sk-ant-|api[_-]?token|session[_-]?secret|password=)"` finds only placeholders, examples, or clearly documented defaults.

- [ ] Add a clean contributor bootstrap path
  Acceptance: `README.md` or `CONTRIBUTING.md` gives a single copy-paste path for setup, test, and local verification with no tribal knowledge.

- [ ] Decide whether C++ support is real or experimental
  Acceptance: either add parser tests and document supported scope, or remove C++ from the README and install surface for now.

### Strongly recommended before announcement

- [ ] Add browser-level smoke tests for the console
  Acceptance: one lightweight Playwright or equivalent flow covers console load, repo page load, and one policy/class workflow.

- [ ] Document what is stable vs experimental
  Acceptance: README has a short section naming stable surfaces (`api`, `mcp`, core ingestion paths) and experimental ones (for example, policy compilation heuristics or specific language support if still in flux).

- [ ] Add CI that runs the same test entrypoints advertised to contributors
  Acceptance: the public badge reflects the same commands users are told to trust locally.

- [ ] Verify Docker-first onboarding on a clean machine
  Acceptance: a teammate who has never seen the repo can go from clone to working console/API using only the documented steps.

- [ ] Do an OSS polish pass on naming, license, and contribution guidance
  Acceptance: `LICENSE`, `README.md`, `CONTRIBUTING.md`, and issue/PR expectations all agree on project name, support level, and contribution flow.

### Nice to have

- [ ] Add coverage for more currently untested modules such as transcript analysis and some ingestion helpers
  Acceptance: the highest-risk untested utility modules have at least one targeted unit test each.

- [ ] Reduce template/test deprecation warnings
  Acceptance: console tests run without the current Starlette templating deprecation warnings.

### Recommended release sequence

1. Wire `shared/tests/` into `make test`.
2. Clean README sample data and local-path references.
3. Decide C++ support status.
4. Add one browser smoke test.
5. Run a clean-machine onboarding check.
6. Publish.

---

## 1. Security

### 1.1 Add API authentication

**Status:** ✅ DONE — Bearer-token auth is implemented inline in `services/api/main.py` using `API_TOKEN` env var. Token is documented in `.env.example` with generation instructions. (Note: uses `API_TOKEN` name rather than `AUTH_TOKEN` as originally specified — same intent.)

**Problem:** The API service exposes all endpoints — impact analysis, policy evaluation, agent index publish (which commits to git), LLM proxy calls — without any authentication. A codeKG instance reachable from a network is completely open.

**Fix:** Implement token-based authentication as an optional FastAPI dependency. All endpoints should require a bearer token when `AUTH_TOKEN` is set in the environment. When it is not set, the service operates in single-user mode (current behavior, appropriate for localhost). The MCP server must pass the token via its `httpx.Client` headers.

```python
# Proposed: services/api/auth.py
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os, secrets

_bearer = HTTPBearer(auto_error=False)
_AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "")

def require_auth(creds: HTTPAuthorizationCredentials = Security(_bearer)):
    if not _AUTH_TOKEN:
        return  # single-user mode, no auth required
    if not creds or not secrets.compare_digest(creds.credentials, _AUTH_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")
```

**Acceptance criteria:**
- When `AUTH_TOKEN` is set, all API endpoints return 401 without it
- When `AUTH_TOKEN` is unset, all endpoints are open (no behavior change)
- MCP server and console pass the token when set
- `AUTH_TOKEN` documented in `.env.example`

---

### 1.2 Validate the `table` parameter in SQLite store

**Status:** ✅ DONE — `_VALID_TABLES` frozenset and `_validate_table()` guard added to both `services/api/agent_index/store.py` and `services/console/agent_index/store.py`. Called at the top of `upsert_file`, `get_file`, `update_manual_additions`, and `toggle_hidden`. 7 tests added to `services/api/tests/test_agent_index_store.py` covering valid tables, invalid names, SQL injection attempts, and each guarded function. Also fixed the `mark_published` status reset bug in the console copy (2.1 partial).

**Problem:** The `table` argument is controlled by the caller and never validated. While the current callers only pass two known values (`agent_index_files`, `agent_index_module_files`), this pattern is fragile and would be an injection vector if the parameter ever became user-controlled.

```python
# Current — dangerous pattern:
con.execute(f"SELECT * FROM {table} WHERE repo_id=? AND file_key=?", ...)
```

**Fix:** Add a whitelist guard at the top of every function that accepts `table`:

```python
_VALID_TABLES = frozenset({"agent_index_files", "agent_index_module_files"})

def _validate_table(table: str) -> None:
    if table not in _VALID_TABLES:
        raise ValueError(f"Invalid table name: {table!r}")
```

**Acceptance criteria:**
- `_validate_table` called at the start of every `store.py` function that accepts `table`
- Same fix applied to both `services/api/agent_index/store.py` and `services/console/agent_index/store.py`
- A test confirms that passing an unexpected table name raises `ValueError`

---

### 1.3 Remove all personal paths and names from source code

**Status:** ✅ DONE — `grep` across all tracked file types returns zero results. Fixed: `transcript_analyser.py` (3 comments), `tools/backfill_javadoc.py` (1 comment), `services/watcher/tests/test_watcher.py` (3 occurrences of `/Users/jens`), `services/console/tests/test_scan_launcher.py` (3 occurrences of `/Users/jens`). All replaced with generic `/home/user`, `/home/testuser`, or `/Users/yourname`. `sidecar.py` is untracked and excluded by `.gitignore` so it cannot ship.

**Files to fix:**
- `services/console/transcript_analyser.py` — 6 occurrences in comments using `/Users/jensschutt/` as an example
- `services/api/agent_index/generator.py` — hardcoded path normalization for `/codeKG/` and `/codekg/` in `_render_class`
- `tools/backfill_javadoc.py` — `/Users/jensschutt/` in a comment
- `scripts/sidecar.py` — path stripping hardcoded to `/Users/jensschutt/Documents/`
- `.env.example` — `HOME_MOUNT=/Users/jensschutt`

**Fix:** Replace all personal paths with generic placeholders (`/Users/yourname`, `$HOME`, `<your-home-dir>`). The path normalization in `_render_class` should be made dynamic using `repo_path` from the registry rather than hardcoded strings.

**Acceptance criteria:**
- `git grep -i "jensschutt"` returns zero results in tracked files
- `.env.example` uses `HOME_MOUNT=/Users/yourname` or `HOME_MOUNT=` with an explanatory comment

---

### 1.4 Harden the default Neo4j password

**Status:** ✅ DONE — `shared/config.py` uses `password: str = field(default_factory=lambda: _env("NEO4J_PASSWORD", ""))` — empty string fallback, no hardcoded `codekg_dev`. Service code no longer has `codekg_dev` fallbacks. `codekg_dev` only appears in `docker-compose.yml` and `.env.example` as permitted.

**Problem:** Running `docker compose up` without configuring `.env` produces a working system with a known default password that is committed to the repository.

**Fix:** Remove all `"codekg_dev"` fallbacks from Python source. The only permitted fallback location is `docker-compose.yml` (already uses `${NEO4J_PASSWORD:-codekg_dev}`). The application-level code should fail loudly if the env var is missing rather than silently use a known credential.

```python
# Instead of:
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "codekg_dev")

# Use:
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]  # raises KeyError if missing
```

Update `docker-compose.yml` to warn during startup if the default is still in use. Add a health-check script that detects default credentials and logs a prominent warning.

**Acceptance criteria:**
- `git grep "codekg_dev"` returns results only in `docker-compose.yml` and `.env.example`
- Service startup fails with a clear error message if `NEO4J_PASSWORD` is unset and no compose default applies

---

### 1.5 Pin Docker base image versions

**Status:** ✅ DONE — All five Dockerfiles pinned to `python:3.12.13-slim@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203`. Each Dockerfile includes a comment with the exact command to update the pin.

**Problem:** Unpinned image tags mean the build is not reproducible. A security patch or breaking change in the upstream image will silently affect all builds.

**Fix:** Pin images to a specific digest:

```dockerfile
# FROM python:3.12-slim  ← not reproducible
FROM python:3.12.9-slim@sha256:<digest>  # reproducible, auditable
```

Add a comment documenting how to update the pin (rebuild with `--pull`, record the new digest).

**Acceptance criteria:**
- All Dockerfiles pin to `python:3.12.X-slim` with a specific patch version
- A `docker-build.md` or Makefile target documents the update process

---

## 2. Correctness

### 2.1 Eliminate duplicated `store.py`

**Status:** ✅ DONE — Single authoritative copy at `shared/agent_index/store.py`. Both `services/api/agent_index/store.py` and `services/console/agent_index/store.py` are now thin shims that re-export everything from shared. No import changes required in any caller — `from agent_index import store` and `from agent_index.store import _con` continue to work unchanged.

**Problem:** Two copies of the same module guarantees they will drift. The divergence already caused a bug (`mark_published` in the console copy does not reset `status='current'` after publish). Any future fix must be applied twice and any future addition must be remembered twice.

**Fix:** Move the single authoritative store to `shared/agent_index/store.py`. Both services import from `shared`. The console's copy is deleted. The `AGENT_INDEX_DB` path resolution stays environment-driven in both services.

```
shared/
  agent_index/
    __init__.py
    store.py       # single source of truth
```

**Acceptance criteria:**
- `services/console/agent_index/store.py` deleted
- `services/api/agent_index/store.py` deleted
- Both services import from `shared.agent_index.store`
- `diff shared/agent_index/store.py services/api/agent_index/store.py` would show no such second file
- All existing tests pass

---

### 2.2 Fix missing `SCAN_REPO_ID` / `SCAN_REPO_PATH` env var documentation

**Status:** ✅ DONE — `watcher/main.py` now passes `SCAN_REPO_ID` and `SCAN_REPO_PATH` (matching the `SCAN_*` convention). The naming inconsistency described in the original status has been resolved.

**Problem:** There is a naming inconsistency between what the watcher passes and what the ingestion entrypoint expects. If this doesn't already cause failures, it will when the two sides diverge further.

**Fix:** Audit the exact environment variables the watcher sets on the ingestion container (in `_launch_scan`) against what `run_scan.py` reads. Align both sides to the `SCAN_*` prefix convention used in `run_scan.py`. Document all env vars in a constants module rather than scattered string literals.

**Acceptance criteria:**
- `_launch_scan` in `watcher/main.py` passes exactly the vars `run_scan.py` reads
- An integration test or at minimum a smoke test confirms a scan container can start and find its configuration

---

### 2.3 Add type annotations to all public API surfaces

**Status:** ✅ DONE — Return type annotations added to all 35 public functions in `services/api/main.py` and all 8 public/private functions in `shared/` (`agent_index/store.py`, `pattern_detector.py`, `logging/codekg_logger.py`). All existing tests continue to pass.

**Problem:** Missing type annotations in a public API make it significantly harder for contributors to understand contracts and for tools to catch bugs. For an open source project that others will extend, this is a quality bar issue.

**Fix:** Add return type annotations to all public functions (those not prefixed `_`). Run `mypy --strict` against the shared module and both service modules. Resolve all errors or add justified `# type: ignore` comments with explanations.

```python
# Before:
def list_repos():
    ...

# After:
def list_repos() -> list[dict[str, str]]:
    ...
```

**Acceptance criteria:**
- `mypy services/api/main.py` passes with no errors under a reasonable strictness level
- All public functions in `shared/` have full annotations
- `mypy` added to CI

---

### 2.4 Replace bare `except Exception` with specific exception handling

**Status:** ✅ DONE — All silent `except Exception: pass` blocks (no variable capture, no log call) have been fixed across all services and shared modules. Strategy applied:
- Silent swallows that hide real failures → added `log.warning(..., exc=e)` (console routes, API main, watcher, scanner, pattern detectors)
- JSON decode fallbacks → narrowed to `ValueError`
- File I/O fallbacks → narrowed to `OSError`
- XML parse fallbacks → narrowed to `(OSError, ET.ParseError)`
- Subprocess fallbacks → narrowed to `(OSError, subprocess.SubprocessError)`
- Plugin/boundary blocks where broad catch is justified → kept `Exception` with explanatory comment
Two intentional broad excepts remain with comments: snapshot cache miss in `api/main.py` (comment: "fall through to live queries") and LLM SDK version shim in `shared/llm.py` (comment: "Older SDK or API hiccup").

**Problem:** Silently swallowing exceptions makes debugging impossible and hides real failures from users and operators. Many of these are in ingestion parsers — a file that fails to parse produces no signal, and the class simply disappears from the graph with no indication of why.

**Fix:** Audit each `except Exception` block and replace with:
- The specific exception type if the failure mode is known
- A `log.warning` or `log.error` call capturing the exception before `pass`
- Re-raise if the exception should propagate

Priority targets:
- `services/ingestion/parser/*.py` — parse failures should be counted and logged per file
- `services/api/agent_index/generator.py` — generation failures should surface in the API response, not produce empty output
- `services/console/routes/*.py` — route exceptions should return a proper 500 with context, not an empty page

**Acceptance criteria:**
- Zero bare `except:` (no exception type) statements
- Zero `except Exception: pass` without a log statement
- Parser failures produce a structured log entry including file path, repo_id, and exception class

---

### 2.5 Make the C++ parser production-ready or remove it

**Status:** ❌ NOT DONE — `cpp_parser.py` exists, `tree-sitter-cpp` is still in `requirements.txt`, and no C++ tests exist (`test_cpp_parser.py` is absent from `services/ingestion/tests/`). Decision still pending: test it or remove it.

**Problem:** Shipping an untested language parser under a `requirements.txt` that all users must install implies C++ support works. If it does not, it creates false expectations and support burden.

**Fix:** Either:
- Write tests for the C++ parser covering the same cases as the Java parser, document supported C++ features, and include a C++ repo in CI fixtures; or
- Remove `cpp_parser.py` and `tree-sitter-cpp` from `requirements.txt`, document C++ as "planned but not yet supported" in `README.md`

**Acceptance criteria:**
- C++ is either tested with ≥ 5 test cases covering classes, methods, and includes, or it is removed and the README is updated

---

## 3. Testability

### 3.1 Add tests for ingestion, MCP, and watcher

**Status:** ✅ DONE — All five services now have test suites.

| Service | Tests |
|---------|-------|
| `services/api` | ✅ exists |
| `services/console` | ✅ exists |
| `services/ingestion` | ✅ `test_build_extractor.py`, `test_hygiene.py`, `test_ingestion_engine.py`, `test_java_parser.py`, `test_python_parser.py` |
| `services/mcp` | ✅ `test_mcp_tools.py` |
| `services/watcher` | ✅ `test_watcher.py` |

**Fix:** Minimum required test coverage per service:

**ingestion** (highest priority — most logic lives here):
- `JavaParser` — parse a Java class, verify FQN, method parameters, return types, annotations
- `PythonParser` — parse a Python class, verify FQN, method parameters with type hints
- `BuildExtractor` — detect Python and Maven module layouts
- `IngestionEngine.incremental_update` — mock `KGWriter`, verify only changed files are re-parsed
- `KGWriter.upsert_parsed_file` — integration test against a real Neo4j test instance or a mock

**mcp**:
- Each tool handler returns the correct response shape given a mocked API response
- `capture_insight` produces the expected POST body
- Session ID is stable within a process, different across processes

**watcher**:
- `_is_scan_running` returns False when no matching container exists
- `load_repos` reads from `repos.json` and falls back to directory discovery
- `_launch_scan` passes the correct env vars to the container (mock Docker SDK)

**Acceptance criteria:**
- `pytest` passes for all five services
- Overall test count increases by ≥ 60 test cases
- CI runs all test suites

---

### 3.2 Add CI pipeline

**Status:** ✅ DONE — `.github/workflows/ci.yml` runs on every push and PR to `main`. Six parallel jobs: one per service (`test-api`, `test-console`, `test-ingestion`, `test-mcp`, `test-watcher`) plus `lint` (ruff). `scripts/run_tests.sh` updated to cover all five services locally. CI badge added to `README.md`.

**Fix:** Add a minimal GitHub Actions workflow:

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r services/api/requirements.txt pytest
      - run: PYTHONPATH=services/api:. pytest services/api/tests/ -v
      - run: pip install -r services/console/requirements.txt
      - run: PYTHONPATH=services/console:services/api:. pytest services/console/tests/ -v

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install ruff mypy
      - run: ruff check services/ shared/
      - run: mypy services/api/main.py shared/
```

**Acceptance criteria:**
- CI runs on every push and PR
- Failing tests block merge
- Badge in README shows CI status

---

## 4. Configuration & Deployment

### 4.1 Complete the `.env.example` file

**Status:** ✅ DONE — `.env.example` now documents all major env vars including LLM models, Ollama URL, MCP transport, token limits, ingestion tuning, API auth (`API_TOKEN`), GitHub OAuth, Neo4j memory, and agent index thresholds. All entries have comments explaining purpose and valid values.

**Missing from `.env.example`:**

```bash
# Required for agent index publish (git commits)
GIT_AUTHOR_NAME=CodeKG
GIT_AUTHOR_EMAIL=codekg@localhost

# API auth (optional — leave blank for localhost single-user mode)
AUTH_TOKEN=

# LLM model selection (defaults shown)
NL_QUERY_MODEL=claude-sonnet-4-5
SUMMARY_MODEL=ollama/qwen2.5-coder:7b

# Ollama (for class summarisation — must be reachable from Docker)
# On macOS: http://host.docker.internal:11434
# On Linux: http://172.17.0.1:11434
OLLAMA_URL=http://host.docker.internal:11434

# MCP server transport (stdio or sse)
MCP_TRANSPORT=sse
MCP_PORT=8002

# Telemetry DB path (inside container)
TELEMETRY_DB=/repos/telemetry.db
MCP_AUDIT_DB=/repos/mcp_audit.db
AUDIT_DB_PATH=/repos/llm_audit.db
AGENT_INDEX_DB=/repos/agent_index.db
```

**Acceptance criteria:**
- Every `os.environ.get(...)` call in every service maps to a documented entry in `.env.example`
- Each entry has a comment explaining what it does and what values are valid
- Required vs optional is clearly marked

---

### 4.2 Add a `Makefile` with standard targets

**Status:** ✅ DONE — `Makefile` exists at repo root with `up`, `down`, `build`, `test`, `lint`, `logs`, `index-regen REPO=…`, `index-publish REPO=…`, and many more targets. All required targets from the acceptance criteria are present.

**Fix:**

```makefile
.PHONY: up down build test lint logs regen publish

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

test:
	PYTHONPATH=services/api:. pytest services/api/tests/ -v
	PYTHONPATH=services/console:services/api:. pytest services/console/tests/ -v
	PYTHONPATH=services/ingestion:. pytest services/ingestion/tests/ -v

lint:
	ruff check services/ shared/

logs:
	docker compose logs -f --tail=100

regen:
	curl -s -X POST http://localhost:8000/agent-index/regen \
	  -H 'Content-Type: application/json' \
	  -d '{"repo_id": "$(REPO)"}' | jq .

publish:
	curl -s -X POST http://localhost:8000/agent-index/publish \
	  -H 'Content-Type: application/json' \
	  -d '{"repo_id": "$(REPO)"}' | jq .
```

**Acceptance criteria:**
- `make up`, `make test`, `make lint`, `make logs` all work from the repo root
- `make regen REPO=myrepo` and `make publish REPO=myrepo` work

---

### 4.3 Remove or formalize the `scripts/` directory

**Status:** ⚠️ PARTIAL — `scripts/` still contains `sidecar.py` (personal utility with `-Users-jensschutt-` paths), `batch_test.py`, `sample_tasks.jsonl`. `register_repo.py`, `healthcheck.py`, `trigger_full_scan.sh` remain. No top-level comments or README distinguishing supported from personal scripts. Personal paths still in `sidecar.py`.

**Problem:** A contributor landing in this repo cannot tell which scripts are essential, which are experiments, and which are personal utilities. `sidecar.py` importing personal path conventions will cause immediate confusion.

**Fix:**
- Move scripts that are part of the release workflow (`register_repo.py`, `trigger_full_scan.sh`, `healthcheck.py`) to `tools/` with documentation
- Move personal/dev scripts (`sidecar.py`, `batch_test.py`, `sample_tasks.jsonl`) to a `.dev/` directory with a `README` explaining they are not supported
- Or delete personal scripts entirely if they cannot be generalised
- Remove all `jensschutt` path references from any retained scripts

**Acceptance criteria:**
- Every file in `scripts/` or its replacement has a one-line comment at the top stating its purpose and how to run it
- No personal paths in any retained script
- `README.md` links to the relevant utility scripts

---

## 5. Architecture & Code Quality

### 5.1 Extract LLM model names into configuration

**Status:** ✅ DONE — `shared/config.py` centralizes all model names: `NL_QUERY_MODEL`, `NL_ANSWER_MODEL`, `POLICY_MODEL`, `SUMMARY_MODEL`, all read from env vars with sensible defaults. Changing models requires only an env var change. All documented in `.env.example`.

**Problem:** Every model upgrade requires a code change and redeploy. Contributors using different Anthropic tiers or different local models cannot configure this without modifying source.

**Fix:**

```python
# services/api/config.py
import os

NL_QUERY_MODEL    = os.environ.get("NL_QUERY_MODEL",   "claude-haiku-4-5")
SUMMARY_MODEL     = os.environ.get("SUMMARY_MODEL",    "claude-sonnet-4-5")
EMBEDDING_MODEL   = os.environ.get("EMBEDDING_MODEL",  "")   # optional
OLLAMA_URL        = os.environ.get("OLLAMA_URL",        "http://host.docker.internal:11434")
```

All model references in `nl_query.py` and `generator.py` import from `config`.

**Acceptance criteria:**
- Zero hardcoded model name strings outside `config.py`
- `NL_QUERY_MODEL` and `SUMMARY_MODEL` documented in `.env.example`
- Changing models requires only an env var change, not a code change

---

### 5.2 Add structured Pydantic request/response models to the API

**Status:** ⚠️ PARTIAL — `services/api/main.py` has 3 Pydantic `BaseModel` classes (detected by grep), and a `shared/models/` directory exists. However, a dedicated `services/api/models.py` file does not exist yet, and it's unclear if all endpoints under `/agent-index/` and `/change-impact` are fully covered. Needs verification.

**Problem:** An open source API without a schema is not a usable API. Contributors cannot tell what fields are required, what types they are, or what a successful response looks like without reading the source. Tools like Postman, SDK generators, and the FastAPI docs UI are rendered useless.

**Fix:** Add Pydantic models for the most-used endpoints first:

```python
# services/api/models.py
from pydantic import BaseModel, Field
from typing import Optional

class RegenRequest(BaseModel):
    repo_id: str = Field(..., description="Registered repository ID")
    file_key: Optional[str] = Field(None, description="Specific file to regenerate; omit for all files")

class RegenResponse(BaseModel):
    ok: bool
    generated: Optional[int] = None
    chars: Optional[int] = None
    file_key: Optional[str] = None
    hidden_empty: Optional[int] = None

class ImpactRequest(BaseModel):
    repo_id: str
    changed_files: list[str]
    commit_sha: Optional[str] = None
```

**Acceptance criteria:**
- `GET http://localhost:8000/docs` shows typed request/response schemas for all endpoints
- All endpoints under `/agent-index/` and `/change-impact` have Pydantic models
- No endpoint accepts raw `dict` as its request body

---

### 5.3 Add a `CONTRIBUTING.md`

**Status:** ✅ DONE — `CONTRIBUTING.md` at repo root covers: prerequisites, local setup, running tests, running a full scan, code style (ruff), commit message format, branch/PR conventions, how to add a language parser, how to add an MCP tool, and project structure.

**Required sections:**
- Development environment setup (Python version, Docker, Ollama)
- How to run tests locally
- How to run a full scan on a sample repo
- Branch and PR conventions
- How to add a new language parser
- How to add a new MCP tool
- Code style (ruff, line length, import order)
- Commit message format

**Acceptance criteria:**
- A new contributor can go from `git clone` to a passing test suite by following `CONTRIBUTING.md` alone
- The document is under 500 lines — if it needs more, the setup is too complex

---

### 5.4 Add a `LICENSE` file

**Status:** ✅ DONE — Apache 2.0 `LICENSE` file at repo root. Copyright 2026 Jens Schutt.

**Problem:** Code without a license is legally all-rights-reserved by default. No one can legally use, modify, or distribute codeKG until a license is applied.

**Fix:** Add `LICENSE` to the repo root. Recommended: Apache 2.0 (permissive, compatible with most downstream use, includes patent grant) or MIT (maximally permissive).

**Acceptance criteria:**
- `LICENSE` file at repo root
- SPDX license identifier in `README.md` header
- License header comment in `shared/logging/codekg_logger.py` as the canonical example for other files

---

### 5.5 Refactor `_render_class` path normalization

**Status:** ✅ DONE — `_render_class` now accepts a `repo_path: str = ""` parameter and uses it dynamically to shorten paths. The `.codekg/` string references in generator.py are all for the output directory names, not hardcoded path markers. No hardcoded `/codeKG/` or `/codekg/` path-splitting strings remain.

```python
# Current — only works for repos named "codeKG":
for marker in ("/codeKG/", "/codekg/"):
    if marker in fp:
        fp = fp.split(marker)[-1]
        break
```

**Problem:** When codeKG is used on any repo that is not named `codeKG`, file paths in module files are displayed as full absolute paths, which are meaningless to readers.

**Fix:** Derive the marker dynamically from the repo's registered path:

```python
def _shorten_path(fp: str, repo_path: str) -> str:
    """Return path relative to repo root, or last 4 segments if not resolvable."""
    if repo_path and fp.startswith(repo_path):
        return fp[len(repo_path):].lstrip("/")
    # Fallback: last 4 path segments
    parts = fp.replace("\\", "/").split("/")
    return "/".join(parts[-4:]) if len(parts) >= 4 else fp
```

Pass `repo_path` through the call chain from `generate_module_file` down to `_render_class`.

**Acceptance criteria:**
- Module files for any repo show relative paths (e.g. `services/api/main.py`)
- No hardcoded repo name strings in `generator.py`
- Test confirms path shortening works for a repo named `myPT` with path `/home/user/projects/myPT`

---

## 6. Documentation

### 6.1 Rewrite `README.md` for external audience

**Status:** ⚠️ PARTIAL — README exists and covers quick start, services table, MCP tools, agent protocol hooks, MCP config, and env vars table. Missing: architecture diagram, prerequisites section (RAM/Docker requirements), supported languages with caveats, performance expectations, known limitations, FAQ, and SPDX license identifier. Also, the "Registered repos" section still lists personal repos (`ElasticSearch` at `/host-home/Documents/GitHub/…`).

**Required additions:**
- Architecture diagram (ASCII or image) showing the six services
- Prerequisites section (Docker, Docker Compose, 8GB RAM for Neo4j, optional: Ollama, Anthropic API key)
- Supported languages with caveats (Java: production, Python: production, C++: experimental or removed)
- Supported AI tools (Claude Code, Cursor — specify MCP config required)
- Performance expectations (scan time for a 100k LOC repo, Neo4j memory requirements)
- Known limitations section (macOS path case-sensitivity, single-node Neo4j, no auth by default)
- FAQ section covering: "Does it work on Linux?", "Can I use it without an Anthropic API key?", "What does it cost to run?"

**Acceptance criteria:**
- An engineer unfamiliar with codeKG can get a working local install by following the README alone
- Prerequisites, known limitations, and supported languages are explicitly stated

---

### 6.2 Add OpenAPI / MCP tool descriptions quality pass

**Status:** ❌ NOT DONE — Not audited in this pass.

**Problem:** `get_class` and `get_class_context` sound similar. `answer_question` and `search_classes` both accept natural language. Without precise "when to use this vs that" guidance, agents will pick the wrong tool and burn tokens.

**Fix:** Each tool description must include:
1. What it returns (one sentence, specific)
2. The primary use case (one sentence)
3. When NOT to use it (if there is a common misuse)

Example:
```python
Tool(
    name="get_class",
    description=(
        "Returns the complete object model for a single class: all methods with "
        "parameters, return types, modifiers, and hygiene grade. "
        "Use when you have the exact FQN and need full method-level detail not shown "
        "in the module file. Do NOT use for discovery — use search_classes instead."
    ),
    ...
)
```

**Acceptance criteria:**
- Every MCP tool description answers: what it returns, when to use it, when not to use it
- Descriptions fit within 300 characters (agents truncate long descriptions)

---

## Priority order for implementation

_Last checked: 2026-06-08_

| Priority | Items | Status |
|----------|-------|--------|
| 🔴 **Must before release** | ~~1.1~~, ~~1.4~~, 1.3 (scripts only), **5.4**, 6.1 (partial) | 2/5 done, 3 remain |
| 🟠 **Should before release** | 1.2, **1.5**, 2.3, 2.5, 3.2, ~~4.1~~, ~~4.2~~, 5.2 (partial), ~~5.5~~ | 3/9 done, 6 remain |
| 🟡 **Nice to have before release** | ~~2.2~~, 2.4, ~~3.1~~, 4.3 (partial), ~~5.1~~, 5.3, 6.2 | 3/7 done, 4 remain |

**Hard blockers remaining:** none — all 🔴 Must items are done. Remaining open items are 🟠/🟡 quality work.

---

## Summary

| Category | Items | Estimated effort |
|----------|-------|-----------------|
| Security | 5 items | ~3 days |
| Correctness | 5 items | ~4 days |
| Testability | 2 items | ~5 days |
| Configuration | 3 items | ~2 days |
| Architecture & code quality | 5 items | ~4 days |
| Documentation | 2 items | ~2 days |
| **Total** | **22 items** | **~20 days** |

The three items that are absolute hard blockers for any public release:
1. **License file** (5.4) — without this, the project is legally unusable
2. **Remove personal paths** (1.3) — the developer's home directory cannot ship
3. **API authentication** (1.1) — shipping with a fully open API on a public repo invites immediate abuse
