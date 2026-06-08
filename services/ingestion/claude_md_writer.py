"""
claude_md_writer.py — generates .claude/CLAUDE.md inside the indexed repo.

Called at the end of every full scan and incremental update. Queries the KG
for live data (dangerous classes, module structure, patterns) and combines it
with language-aware conventions to produce a CLAUDE.md that Claude Code reads
automatically when working in that repo.

Static content (never changes):
  - Architecture layer rules (language-appropriate)
  - Language conventions (per language)
  - Build commands (per build tool / language)
  - Rule: use CodeKG MCP before reading files

Dynamic content (queried from KG, updated every scan):
  - Module tree (top-level modules with class counts)
  - Dangerous classes (coupling > 0.6 or blast_size > 50)
  - Detected anti-patterns
  - Build tool and language version
  - Entry points
"""
from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime, timezone

try:
    from shared.config import cfg as _cfg
    from shared.codekg_logging.codekg_logger import get_logger
except ImportError:
    import logging
    class _FL:
        """Tiny logger shim used by the standalone markdown writer. Watch out for method coverage here, because the script only implements the logging calls it actually needs."""

        def __init__(self, n): self._l = logging.getLogger(n)
        def info(self, m, **k): self._l.info(m)
        def warning(self, m, **k): self._l.warning(m)
    def get_logger(n, **k): return _FL(n)
    # Fallback cfg when shared is unavailable
    class _FakeCfg:
        """Minimal config stand-in for running the markdown writer outside the full service stack. Watch out for drift here, because it mirrors only a narrow slice of the real configuration object."""

        class paths:
            """Namespace for path-related config values used by the script shim. Watch out for attribute naming here, because call sites expect it to resemble `cfg.paths`."""

            host_home = os.environ.get("HOST_HOME", "")
    _cfg = _FakeCfg()

log = get_logger(__name__, service="ingestion")


# ── KG queries ────────────────────────────────────────────────────────────────

def _run(driver, cypher: str, **params) -> list[dict]:
    with driver.session() as s:
        return [dict(r) for r in s.run(cypher, **params)]


def _fetch_repo(driver, repo_id: str) -> dict:
    rows = _run(driver,
        "MATCH (r:Repository {repo_id: $rid}) RETURN r", rid=repo_id)
    return dict(rows[0]["r"]) if rows else {}


def _fetch_modules(driver, repo_id: str) -> list[dict]:
    return _run(driver, """
        MATCH (m:Module {repo_id: $rid})
        OPTIONAL MATCH (c:Class {repo_id: $rid})
        WHERE c.file_path IS NOT NULL AND c.file_path STARTS WITH m.path
        WITH m, count(c) AS class_count
        ORDER BY m.module_id
        RETURN m.module_id AS module_id, m.name AS name,
               m.path AS path, m.build_tool AS build_tool,
               class_count
    """, rid=repo_id)


def _fetch_dangerous(driver, repo_id: str) -> list[dict]:
    """Classes with high coupling OR high blast radius — the ones to warn about."""
    return _run(driver, """
        MATCH (c:Class {repo_id: $rid})
        WHERE (c.coupling > 0.6 OR c.blast_size > 50)
          AND NOT c.kind IN ['module']
          AND NOT c.fqn CONTAINS '$'
        RETURN c.name AS name, c.fqn AS fqn, c.role AS role,
               c.coupling AS coupling, c.blast_size AS blast_size,
               c.file_path AS file_path
        ORDER BY c.blast_size DESC, c.coupling DESC
        LIMIT 15
    """, rid=repo_id)


def _fetch_antipatterns(driver, repo_id: str) -> list[dict]:
    return _run(driver, """
        MATCH (ap:ArchPattern {repo_id: $rid, anti_pattern: true})
        WHERE ap.match_count > 0
        RETURN ap.name AS name, ap.match_count AS hits
        ORDER BY ap.match_count DESC
        LIMIT 8
    """, rid=repo_id)


def _fetch_entry_points(driver, repo_id: str, language: str) -> list[dict]:
    """Fetch entry point classes — strategy varies by language."""
    if language == "python":
        # Django: Views and ViewSets are the entry points
        return _run(driver, """
            MATCH (c:Class {repo_id: $rid})
            WHERE (c.name ENDS WITH 'View' OR c.name ENDS WITH 'ViewSet'
                   OR c.name ENDS WITH 'APIView')
              AND NOT c.fqn CONTAINS '$'
            RETURN c.name AS name, c.fqn AS fqn, c.file_path AS file_path
            ORDER BY c.name
            LIMIT 10
        """, rid=repo_id)
    else:
        # Java: TRANSPORT role classes
        return _run(driver, """
            MATCH (c:Class {repo_id: $rid, role: 'TRANSPORT'})
            WHERE c.coupling IS NOT NULL
            RETURN c.name AS name, c.fqn AS fqn, c.file_path AS file_path
            ORDER BY c.coupling DESC
            LIMIT 10
        """, rid=repo_id)


def _fetch_stats(driver, repo_id: str) -> dict:
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $rid})
        WHERE NOT c.kind IN ['module']
        RETURN count(c) AS total,
               sum(CASE WHEN c.summary IS NOT NULL THEN 1 ELSE 0 END) AS summarised,
               sum(CASE WHEN c.javadoc IS NOT NULL THEN 1 ELSE 0 END) AS with_docstring
    """, rid=repo_id)
    return rows[0] if rows else {}


def _fetch_key_patterns(driver, repo_id: str) -> list[dict]:
    """Fetch detected (non-anti) patterns for context."""
    return _run(driver, """
        MATCH (ap:ArchPattern {repo_id: $rid, anti_pattern: false})
        WHERE ap.match_count > 0
        RETURN ap.name AS name, ap.match_count AS hits, ap.category AS category
        ORDER BY ap.match_count DESC
        LIMIT 10
    """, rid=repo_id)


# ── Markdown builder ──────────────────────────────────────────────────────────

def _rel_path(file_path: str | None, repo_path: str) -> str:
    """Convert absolute file_path stored in KG to a repo-relative path."""
    if not file_path:
        return ""
    fp = file_path
    if fp.startswith("/host-home"):
        home = _cfg.paths.host_home or os.path.expanduser("~")
        fp = home + fp[len("/host-home"):]
    if repo_path and fp.startswith(repo_path):
        fp = fp[len(repo_path):].lstrip("/")
    return fp


def _build_module_tree(modules: list[dict]) -> str:
    """Render top-level modules as a directory-style tree."""
    if not modules:
        return "_No modules detected_"
    lines = []
    seen = set()
    for m in modules:
        mid = m.get("module_id", "")
        parts = mid.split("/")
        top = "/".join(parts[:2]) if len(parts) > 1 else parts[0]
        if top in seen:
            continue
        seen.add(top)
        count = m.get("class_count", 0) or ""
        count_str = f"  ({count} classes)" if count else ""
        lines.append(f"  {top}/{count_str}")
    return "\n".join(lines)


# ── Language-specific content ─────────────────────────────────────────────────

def _build_commands(build_tool: str, language: str) -> str:
    bt = build_tool.lower() if build_tool else ""
    if "gradle" in bt:
        return """\
./gradlew build                          # full build
./gradlew test                           # all tests
./gradlew check                          # build + test + style (run before PR)
./gradlew compileJava                    # compile only
./gradlew assemble -x test               # build artifact, skip tests
# Module-specific tests:
./gradlew :server:test
./gradlew :server:test --tests "org.example.MyTest"
"""
    elif "maven" in bt:
        return """\
mvn package                             # full build
mvn test                                # all tests
mvn verify                              # build + test + checks (run before PR)
mvn -pl server test                     # module-specific tests
"""
    elif language == "python":
        return """\
python manage.py test                   # full test suite (Django)
python manage.py test <app>             # single app tests
pytest                                  # if pytest is configured
pytest tests/<module>/                  # module-specific tests
python manage.py migrate                # apply migrations
python manage.py check                  # system checks
"""
    elif language == "cpp":
        return """\
cmake --build build/                    # full build
ctest --test-dir build/                 # run tests
make -C build/ -j$(nproc)              # parallel build
"""
    else:
        return f"# Build tool: {build_tool or 'unknown'} — check the project README\n"


def _arch_layers(language: str, build_tool: str) -> str:
    if language == "python":
        bt = (build_tool or "").lower()
        if "django" in bt or True:  # Django is the dominant Python framework here
            return """\
## Architecture layers

Django follows an MTV (Model-Template-View) pattern. The typical request flow:

```
URL dispatcher  → routes incoming HTTP request to a View
                        ↓
View / ViewSet  → authenticates, validates input, calls services
                        ↓
Service / Manager → business logic, orchestration (keep views thin)
                        ↓
Model / QuerySet → ORM data access, database reads/writes
```

**Key rules:**
- Views should be thin — validate input via Forms/Serializers, call a service, return a response
- Business logic belongs in service functions or model methods, NOT in views
- Use custom Managers/QuerySets for reusable query logic — never repeat filters across views
- Write migrations for every model change — never edit the database directly
- Middleware is for cross-cutting concerns (auth, logging, rate limiting) — not business logic
"""
    elif language == "cpp":
        return """\
## Architecture layers

```
Public API headers  → stable interface surface (include/)
                            ↓
Implementation      → translation units (src/)
                            ↓
Utilities / Helpers → shared low-level code
```

**Key rules:**
- Never expose implementation details in public headers
- RAII for all resource management — no naked new/delete in business logic
- Prefer value semantics; use smart pointers for ownership transfer
"""
    else:
        # Java default
        return """\
## Architecture layers

Every operation flows through these layers in order — never skip layers:

```
TRANSPORT   → outermost request handlers (receive external requests)
                ↓
COMMAND     → orchestrate a single operation
                ↓
SERVICE     → core business logic, stateful domain services
                ↓
REPOSITORY  → data access: reads/writes storage or external services
```

**Key rules:**
- Dependencies are constructor-injected — no service locator, no static state
- Async methods use `ActionListener<T>` callbacks, not futures or blocking calls
- Never modify a layer by reaching past it — always go through the interface above
"""


def _conventions(language: str) -> str:
    if language == "python":
        return """\
## Python / Django conventions

- **Models** — thin, focused on data. Complex logic in service functions, not `save()` overrides
- **Serializers** — validate ALL incoming API data before it reaches any service
- **Views** — authenticate → validate (serializer) → call service → return response
- **Tests** — use `django.test.TestCase` for DB tests; `pytest` for unit tests without DB
- **Imports** — absolute imports preferred; avoid circular imports via apps
- **Migrations** — always auto-generate with `makemigrations`; never hand-edit migration files
- **Settings** — use environment variables for secrets; never hardcode credentials
- **QuerySets** — lazy by default; call `.count()` not `len()`, use `.exists()` not `bool()`
"""
    elif language == "cpp":
        return """\
## C++ conventions

- **Headers** — use `#pragma once`; keep includes minimal in headers
- **Memory** — `std::unique_ptr` / `std::shared_ptr` for heap objects; RAII everywhere
- **Error handling** — use exceptions or `std::expected`; avoid raw error codes
- **Naming** — snake_case for functions/variables, PascalCase for classes
- **Tests** — Google Test or Catch2; one test file per source file
"""
    else:
        return """\
## Java conventions

- **Naming** — PascalCase classes, camelCase methods/fields, UPPER_SNAKE constants
- **Dependencies** — constructor injection only; no field injection, no static state
- **Async** — `ActionListener<T>` for async callbacks; never block on a network/IO thread
- **Tests** — extend `ESTestCase` / `ESSingleNodeTestCase`; mock at service boundaries
- **Logging** — use the class-level `logger`; no `System.out.println`
- **Nulls** — return empty collections, not null; use `Optional` for absent values
"""


def _entry_points_heading(language: str) -> str:
    if language == "python":
        return "## Entry points (Views / ViewSets)"
    elif language == "cpp":
        return "## Entry points (Public API)"
    else:
        return "## Entry points (TRANSPORT layer)"


def _entry_points_description(language: str) -> str:
    if language == "python":
        return "Where HTTP requests enter the system — start here when tracing a request flow:"
    elif language == "cpp":
        return "The public API surface — start here when tracing usage:"
    else:
        return "Where requests enter the system — start here when tracing a request flow:"


def _source_file_ext(language: str) -> str:
    if language == "python":
        return ".py"
    elif language == "cpp":
        return ".cpp / .h"
    else:
        return ".java"


# ── Main generator ────────────────────────────────────────────────────────────

def generate(driver, repo_id: str, repo_path: str) -> str:
    """
    Query the KG and render the full CLAUDE.md content.
    Returns the markdown string.
    """
    repo         = _fetch_repo(driver, repo_id)
    language     = (repo.get("language") or "java").lower()
    build_tool   = repo.get("build_tool") or ("python" if language == "python" else "Gradle")
    last_commit  = (repo.get("last_commit") or repo.get("prov_commit_sha") or "")[:12]

    modules      = _fetch_modules(driver, repo_id)
    dangerous    = _fetch_dangerous(driver, repo_id)
    antipatterns = _fetch_antipatterns(driver, repo_id)
    entry_pts    = _fetch_entry_points(driver, repo_id, language)
    stats        = _fetch_stats(driver, repo_id)
    patterns     = _fetch_key_patterns(driver, repo_id)

    total        = stats.get("total", 0)
    summarised   = stats.get("summarised", 0)
    with_docs    = stats.get("with_docstring", 0)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    module_tree  = _build_module_tree(modules)
    src_ext      = _source_file_ext(language)

    # ── Dangerous classes section ──
    dangerous_lines = []
    for c in dangerous:
        fp = _rel_path(c.get("file_path"), repo_path)
        coupling = f"{c['coupling']:.2f}" if c.get("coupling") else "—"
        blast    = c.get("blast_size") or 0
        role     = f" ({c['role']})" if c.get("role") else ""
        dangerous_lines.append(
            f"- **`{c['name']}`**{role}  \n"
            f"  `{fp}`  \n"
            f"  coupling={coupling}, blast_radius={blast} classes"
        )
    dangerous_section = "\n".join(dangerous_lines) if dangerous_lines \
        else "_No high-risk classes detected_"

    # ── Anti-patterns section ──
    ap_lines = [f"- {ap['name']} ({ap['hits']} hits)" for ap in antipatterns]
    ap_section = "\n".join(ap_lines) if ap_lines else "_None detected_"

    # ── Detected patterns section ──
    pat_lines = [f"- {p['name']} ({p['hits']} classes) — {p['category']}" for p in patterns]
    pat_section = "\n".join(pat_lines) if pat_lines else "_Run pattern detection to populate_"

    # ── Entry points section ──
    ep_lines = []
    for ep in entry_pts:
        fp = _rel_path(ep.get("file_path"), repo_path)
        ep_lines.append(f"- `{ep['name']}` → `{fp}`")
    ep_section = "\n".join(ep_lines) if ep_lines else "_None detected_"

    # ── Build commands ──
    build_cmds = _build_commands(build_tool, language)

    # ── Language-specific sections ──
    arch_layers  = _arch_layers(language, build_tool)
    conventions  = _conventions(language)
    ep_heading   = _entry_points_heading(language)
    ep_desc      = _entry_points_description(language)

    # ── Version line ──
    if language == "java":
        java_version = repo.get("java_version") or "21"
        version_line = f"Build tool: **{build_tool}** | Java: **{java_version}**"
    elif language == "python":
        version_line = f"Language: **Python** | Build tool / framework: **{build_tool}**"
    elif language == "cpp":
        version_line = f"Language: **C++** | Build tool: **{build_tool}**"
    else:
        version_line = f"Language: **{language}** | Build tool: **{build_tool}**"

    return f"""\
# {repo_id} — CodeKG Intelligence Layer

> Auto-generated by CodeKG on {generated_at} from commit `{last_commit}`
> KG contains **{total:,} classes** ({summarised:,} with NL summaries, {with_docs:,} with docstrings)

This repository is fully indexed in **CodeKG**, a Neo4j knowledge graph with
pre-computed class relationships, coupling scores, blast radii, call chains,
NL summaries, and docstrings.

## CodeKG Agent Protocol

This repository is indexed in CodeKG. **You MUST follow this protocol for every request — including tasks like "write tests", "fix a bug", "add a feature", "change the UI", or "refactor". Do not skip straight to reading files or writing code.**

### Step 1 — Query the knowledge graph FIRST (mandatory)

Before reading any source file or writing any code, call one of:

- **`answer_question`** — for any question, task, or feature request. Use this to find which classes are relevant, where to make the change, and what the blast radius is.
- **`get_module_context`** — if the task is scoped to a known module.
- **`get_class_context`** — if you already know the exact class FQN.

**Examples of when this applies:**
| User prompt | Call before doing anything |
|---|---|
| "Write tests for the ingestion engine" | `answer_question("Which classes make up the ingestion engine?", repo_id="{repo_id}")` |
| "Fix the bug in wire_edges" | `answer_question("What does wire_edges do and which classes does it touch?", repo_id="{repo_id}")` |
| "Add a new MCP tool" | `answer_question("How are MCP tools registered and what is the pattern?", repo_id="{repo_id}")` |
| "Change the UI on the mcp-audit page" | `answer_question("Which template and route handle the mcp-audit page?", repo_id="{repo_id}")` |
| "Make the table rows expandable" | `answer_question("Where is the mcp audit table rendered and what JS handles it?", repo_id="{repo_id}")` |

The only exceptions are: trivial one-line edits where the file and line are already known, or pure documentation changes.

### Step 2 — Save the IDs

Every codeKG tool response contains two comments at the end:
```
<!-- codekg_request_id: abc123 -->
<!-- codekg_turn_id: abc123 -->
```
**Both values are always identical** — they are the same stable turn ID for all calls in this human turn.
Save them from your **first** codeKG call. They will not change for the rest of this turn.

### Step 3 — Submit telemetry when done

Call `submit_session_telemetry` as your **final step** before returning to the user. Submit:
- `codekg_request_id` and `turn_id`: both set to the same value saved in step 2
- `user_prompt`: the user's request (first 300 chars)
- `turns`: every tool call you made — `{{tool_name, summary, input_tokens, output_tokens, cache_read_tokens}}`
- `total_input_tokens`, `total_output_tokens`, `total_cache_read_tokens`: your best estimate

**After `submit_session_telemetry` succeeds: discard the turn_id. A fresh one will be issued with the next opener call.**

A `Stop` hook enforces this step — if you finish a turn without submitting telemetry after a codeKG call, the hook will block and remind you with the correct IDs to use.

This is how codeKG measures token savings. It only works if you submit even when the session was short.

**repo_id for tool calls:** `{repo_id}`

### If codeKG is unreachable

If a codeKG tool returns an error (MCP container restarting, connectivity issue):
- **Say so explicitly** before proceeding: "I cannot reach codeKG right now because [reason]. Proceeding from file reads."
- Do NOT silently skip the protocol and read files without explanation.
- Try again after the container stabilises.

---

## Hook enforcement

Two Claude Code hooks enforce this protocol automatically. They are installed in `.claude/hooks/`:

- **`require_codekg.py`** (PreToolUse) — blocks `Read`, `Edit`, `Write`, and write-bearing `Bash` if no codeKG tool has been called this turn. Forces consultation before any file operation.
- **`require_telemetry.py`** (Stop) — fires when you finish a response turn. Blocks turn completion if codeKG was used without a following `submit_session_telemetry`. Injects the correct IDs into the reminder so you can't use wrong values.

If the hooks are not present, install them from the codeKG project:
```bash
cp <codekg_root>/.claude/hooks/require_codekg.py .claude/hooks/
cp <codekg_root>/.claude/hooks/require_telemetry.py .claude/hooks/
```

---

## How to work in this repo

### Rule 1 — Always start with CodeKG, never with the filesystem

Before reading any `{src_ext}` file, before running `find`, before `grep`:
call `answer_question` with your intent as a natural-language question.

The answer gives you: relevant classes ranked by relevance, their file paths,
method signatures, call chains, blast radius, NL summaries, and docstrings —
without reading a single source file.

### Rule 2 — Use the right tool for each job

| What you need | Tool to call |
|---|---|
| Understand where to implement a feature | `answer_question("...", repo_id="{repo_id}")` |
| Get full method signatures for a class | `get_class_context(fqn)` |
| Find a class by name | `search_classes(query, repo_id="{repo_id}")` |
| Check blast radius before changing a file | `get_change_impact(files, repo_id="{repo_id}")` |
| Overall architecture overview | `get_codebase_template("{repo_id}")` |
| Check architectural rules before PR | `check_violations(files)` |

### Rule 3 — Read source files only for the final 20%

CodeKG has method signatures but not method bodies. Once you know *which* class
to modify and *what* the surrounding architecture looks like, then open the source
file. Do NOT open files to "explore" — ask CodeKG first.

---

## Repository structure

```
{module_tree}
```

---

{arch_layers}

---

{conventions}

---

## Build & test

{version_line}

```bash
{build_cmds}
```

---

## High-risk classes — always call `get_change_impact` before modifying

These classes have high coupling or large blast radius. A change here can break
many other classes.

{dangerous_section}

---

## Detected architectural patterns

{pat_section}

---

## Detected anti-patterns

{ap_section}

Address these before adding new code that follows the same pattern.

---

{ep_heading}

{ep_desc}

{ep_section}

---

## Example workflow

**Task:** implement a new feature

1. **Ask CodeKG:**
   ```
   answer_question("Where should I implement X?", repo_id="{repo_id}")
   ```

2. **Get exact signatures** for the identified hook point:
   ```
   get_class_context("<fqn from step 1>")
   ```

3. **Check blast radius** before touching anything:
   ```
   get_change_impact(repo_id="{repo_id}", files="<file from step 1>")
   ```

4. **Open source files** only for the 1-2 classes CodeKG identified.

5. **Implement.** Run the test classes listed in the `get_change_impact` response.

6. **Before PR:**
   ```
   check_violations(files="<comma-separated list of files you changed>")
   ```

---

## Before you open a PR

1. Run the build + checks: see build commands above
2. `check_violations` — architectural policy check via CodeKG
3. `get_change_impact` — confirm blast radius matches expectations
4. Verify tests exist for every class you modified (CodeKG lists them in `get_change_impact`)

---

_This file is auto-generated by CodeKG ingestion. Do not edit manually — changes will be overwritten on the next scan._
"""


# ── Writer ────────────────────────────────────────────────────────────────────

def write_claude_md(driver, repo_id: str, repo_path: str) -> bool:
    """
    Generate and write .claude/CLAUDE.md into the repo directory.
    Returns True on success, False on failure.
    """
    try:
        content = generate(driver, repo_id, repo_path)
        claude_dir = Path(repo_path) / ".claude"
        claude_dir.mkdir(exist_ok=True)
        out = claude_dir / "CLAUDE.md"
        out.write_text(content, encoding="utf-8")
        log.info("CLAUDE.md written", repo_id=repo_id, path=str(out),
                 size=len(content))
        return True
    except Exception as exc:
        log.warning("CLAUDE.md write failed", repo_id=repo_id, exc=str(exc))
        return False
