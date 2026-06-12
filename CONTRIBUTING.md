# Contributing to codeKG

Thanks for your interest in contributing. This guide gets you from `git clone` to a passing test suite and your first PR.

---

## Prerequisites

- **Docker** and **Docker Compose** v2+ (`docker compose version`)
- **Python 3.12** (for running tests locally without Docker)
- **Make** (standard on macOS/Linux)
- **Ollama** (optional — only needed for NL class summarisation)
- An **Anthropic API key** (optional — only needed for NL query and tribal knowledge features)

---

## Local setup

```bash
git clone https://github.com/your-org/codekg.git
cd codekg
cp .env.example .env
```

Edit `.env` — at minimum set:
```bash
NEO4J_PASSWORD=<something-not-default>
REPOS_PATH=./repos
```

Start the stack:
```bash
make up
```

Wait for Neo4j to be ready (10–15 seconds), then open:
- Console: http://localhost:8080
- API docs: http://localhost:8000/docs

---

## Running tests

No Docker required for the test suite. Install dependencies and run all tests:

```bash
make test
```

Run a single service:
```bash
make test-api
make test-console
```

Run with a filter:
```bash
make test FILTER=test_java_parser
```

All five services have test suites under `services/<name>/tests/`.

---

## Running a full scan on a sample repo

1. Register a repo in the console → **Repositories → Add**
   - Repo ID: any short identifier (e.g. `myapp`)
   - Path: absolute host path to the repo (or `/host-home/...` if inside your `HOME_MOUNT`)

2. Trigger a full scan from the repo detail page, or via Make:
   ```bash
   make scan REPO=myapp
   ```

3. Once ingestion completes, the console's **Modules** and **Classes** pages will show the indexed content.

---

## Code style

codeKG uses **ruff** for linting and formatting.

```bash
make lint          # check
make lint-fix      # auto-fix
```

Key rules:
- Line length: 100 characters
- Import order: stdlib → third-party → local (ruff handles this)
- No unused imports (ruff will catch them)

---

## Commit messages

Use the conventional commits format:

```
<type>: <short summary>

<optional body>
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`

Examples:
```
feat: add Go parser support
fix: mark_published now resets status to current in console store
docs: document SCAN_REPO_ID env var in .env.example
```

---

## Branch and PR conventions

- Branch from `main`, name your branch `<type>/<short-description>` (e.g. `fix/store-mark-published`)
- One logical change per PR — don't bundle unrelated fixes
- PRs must pass `make test` and `make lint` before review
- Keep PRs under 400 lines of diff where possible; split larger changes

---

## Adding a new language parser

1. Create `services/ingestion/parser/<lang>_parser.py`
2. Implement the same interface as `JavaParser` and `PythonParser`:
   - `EXTENSIONS: frozenset[str]` — file extensions to handle
   - `parse_file(path: Path, repo_id: str) -> ParsedFile`
3. Register in `services/ingestion/ingestion_engine.py` alongside the existing parsers
4. Add tests in `services/ingestion/tests/test_<lang>_parser.py` covering:
   - Class with methods (verify FQN, method names, parameter types, return types)
   - Inheritance / implements
   - Annotations / decorators
   - Empty file (should not raise)
   - Add a skip guard so tests are skipped gracefully when the grammar is absent
5. Update the supported languages table in `README.md`

**If the grammar has no PyPI package** (like Salesforce Apex), use the lazy-load pattern:
- Do **not** import the native grammar at module level — wrap it in a `_load_<lang>_language()` function called only on first parser instantiation
- Support a `TREE_SITTER_<LANG>_SO` env var to override the `.so` path; default to the `parser/` directory first, then the Docker path (`/usr/local/lib/`)
- Add the compiled `.so` to `.gitignore`
- Add `gcc` + compile steps to the Dockerfile and `.github/workflows/ci.yml`
- In the test skip guard, probe by **calling the loader function** (not just importing the module) — a bare import succeeds even when the `.so` is absent

**Local setup for Apex grammar (one-time):**
```bash
git clone --depth=1 https://github.com/aheber/tree-sitter-sfapex.git /tmp/tree-sitter-sfapex
gcc -shared -fPIC -o services/ingestion/parser/tree_sitter_apex.so \
  /tmp/tree-sitter-sfapex/apex/src/parser.c
```

---

## Adding a new MCP tool

1. Add the tool handler in `services/mcp/main.py`
2. Write the description following the three-part format:
   - What it returns (one sentence, specific)
   - Primary use case (one sentence)
   - When NOT to use it (if there is a common misuse)
3. Add a test in `services/mcp/tests/test_mcp_tools.py` that mocks the API response and verifies the response shape
4. Document the tool in the MCP tools table in `README.md`

---

## Project structure

```
services/
  api/          REST API — KG queries, agent index, policy evaluation
  console/      Web UI (FastAPI + Jinja2 templates)
  ingestion/    Repo parser and Neo4j writer
  mcp/          MCP server (SSE transport)
  watcher/      Git change monitor, triggers re-ingestion
shared/         Config, logging, models — imported by all services
scripts/        Operational utilities (healthcheck, repo registration)
```

See `.codekg/architecture/modules.md` for a full module map with class counts.

---

## License

By contributing, you agree that your contributions will be licensed under the [Apache 2.0 License](LICENSE).
