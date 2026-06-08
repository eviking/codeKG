# =============================================================================
# codeKG Operations Makefile
#
# Usage:  make <target> [VAR=value ...]
#         make help            — print this reference
#
# All targets operate on the project root where this Makefile lives.
# Docker Compose and the Docker CLI must be installed.
# =============================================================================

.DEFAULT_GOAL := help
SHELL         := /bin/bash
.SHELLFLAGS   := -euo pipefail -c

# ── Project layout ─────────────────────────────────────────────────────────────
ROOT          := $(shell pwd)
REPOS_DIR     := $(ROOT)/repos
BACKUPS_DIR   := $(ROOT)/backups
SCRIPTS       := $(ROOT)/scripts
OPS           := $(ROOT)/ops

# ── Compose & container names ──────────────────────────────────────────────────
COMPOSE       := docker compose
SERVICES      := neo4j api console mcp watcher

NEO4J         := codekg-neo4j
API           := codekg-api
CONSOLE       := codekg-console
MCP           := codekg-mcp
WATCHER       := codekg-watcher
INGESTION     := codekg-ingestion

API_URL       ?= http://localhost:8000
CONSOLE_URL   ?= http://localhost:8080

# ── Optional variables (pass on command line) ──────────────────────────────────
# REPO=codeKG            — repo ID for per-repo targets
# TAG=pre-release        — extra label for backup filename
# KEEP=10                — number of backups to retain
# FILTER=                — pytest -k filter expression

REPO   ?=
TAG    ?=
KEEP   ?= 10
FILTER ?=


# =============================================================================
# HELP
# =============================================================================

.PHONY: help
help:  ## Print this help
	@echo ""
	@echo "  codeKG Operations"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"; section=""} \
	      /^## / {gsub(/^## /, "", $$0); section=$$0; printf "\n  \033[1;37m%s\033[0m\n", section} \
	      /^[a-zA-Z0-9_-]+:.*##/ {printf "    \033[36m%-28s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""


# =============================================================================
## Stack lifecycle
# =============================================================================

.PHONY: up down restart stop pull
up: ## Start all services (detached)
	$(COMPOSE) up -d
	@echo "→ Console:  $(CONSOLE_URL)"
	@echo "→ API:      $(API_URL)"
	@echo "→ Neo4j:    http://localhost:7474"
	@echo "→ MCP SSE:  http://localhost:8002"

down: ## Stop and remove all containers (data volumes preserved)
	$(COMPOSE) down

stop: ## Stop containers without removing them
	$(COMPOSE) stop

restart: ## Restart all services
	$(COMPOSE) restart

restart-api: ## Restart API service only
	$(COMPOSE) restart api

restart-console: ## Restart console service only
	$(COMPOSE) restart console

restart-mcp: ## Restart MCP service only
	$(COMPOSE) restart mcp

restart-watcher: ## Restart watcher service only
	$(COMPOSE) restart watcher

pull: ## Pull latest images from registry
	$(COMPOSE) pull


# =============================================================================
## Build
# =============================================================================

.PHONY: build build-api build-console build-mcp build-ingestion build-watcher

build: ## Build all service images
	$(COMPOSE) build

build-api: ## Build API image only
	$(COMPOSE) build api

build-console: ## Build console image only
	$(COMPOSE) build console

build-mcp: ## Build MCP image only
	$(COMPOSE) build mcp

build-ingestion: ## Build ingestion image only
	$(COMPOSE) build ingestion

build-watcher: ## Build watcher image only
	$(COMPOSE) build watcher

rebuild: ## Build all images without cache, then start
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d


# =============================================================================
## Development workflow
# =============================================================================

.PHONY: dev deploy deploy-api deploy-console deploy-mcp

dev: ## Build and start everything, then tail logs
	$(COMPOSE) up -d --build
	$(COMPOSE) logs -f --tail=50

deploy-api: ## Build + restart API (no downtime on other services)
	$(COMPOSE) build api
	$(COMPOSE) up -d api

deploy-console: ## Build + restart console
	$(COMPOSE) build console
	$(COMPOSE) up -d console

deploy-mcp: ## Build + restart MCP
	$(COMPOSE) build mcp
	$(COMPOSE) up -d mcp

deploy: deploy-api deploy-console deploy-mcp ## Build + restart api, console, mcp


# =============================================================================
## Health & status
# =============================================================================

.PHONY: status health ps logs logs-api logs-console logs-mcp logs-watcher logs-neo4j

status: ## Show container states (compact)
	$(COMPOSE) ps

ps: status

health: ## Run the full stack health inspector
	@python3 $(SCRIPTS)/healthcheck.py

health-json: ## Run health inspector and emit JSON
	@python3 $(SCRIPTS)/healthcheck.py --json

ping-api: ## Curl the API health endpoint
	@curl -sf $(API_URL)/health | python3 -m json.tool || echo "API not reachable at $(API_URL)"

ping-console: ## Curl the console health endpoint
	@curl -sf $(CONSOLE_URL)/health | python3 -m json.tool || echo "Console not reachable at $(CONSOLE_URL)"

logs: ## Tail logs from all services (Ctrl-C to stop)
	$(COMPOSE) logs -f --tail=100

logs-api: ## Tail API logs
	$(COMPOSE) logs -f --tail=100 api

logs-console: ## Tail console logs
	$(COMPOSE) logs -f --tail=100 console

logs-mcp: ## Tail MCP logs
	$(COMPOSE) logs -f --tail=100 mcp

logs-watcher: ## Tail watcher logs
	$(COMPOSE) logs -f --tail=100 watcher

logs-neo4j: ## Tail Neo4j logs
	$(COMPOSE) logs -f --tail=100 neo4j

logs-pretty: ## Tail all logs through the JSON pretty-printer
	$(COMPOSE) logs -f --tail=200 | python3 $(SCRIPTS)/log_pretty.py


# =============================================================================
## Repository management
# =============================================================================

.PHONY: repos repo-add repo-remove repo-list scan scan-all

repo-list: ## List all registered repositories
	@python3 -c "import json,pathlib; \
	  p=pathlib.Path('$(REPOS_DIR)/repos.json'); \
	  d=json.loads(p.read_text()) if p.exists() else {}; \
	  [print(f'  {k:<30} {v}') for k,v in d.items()] if d else print('  No repos registered')"

repo-add: ## Register a repo  (REPO=id PATH=/host-home/...)
	@test -n "$(REPO)"  || (echo "ERROR: REPO=<id> required" && exit 1)
	@test -n "$(PATH_)"  || (echo "ERROR: PATH_=/host-home/... required" && exit 1)
	@python3 $(SCRIPTS)/register_repo.py --id "$(REPO)" --path "$(PATH_)"
	@echo "→ Registered $(REPO) → $(PATH_)"

repo-remove: ## Unregister a repo  (REPO=id)
	@test -n "$(REPO)" || (echo "ERROR: REPO=<id> required" && exit 1)
	@python3 $(SCRIPTS)/register_repo.py --id "$(REPO)" --remove
	@echo "→ Removed $(REPO)"

scan: ## Trigger full scan for one repo  (REPO=id)
	@test -n "$(REPO)" || (echo "ERROR: REPO=<id> required" && exit 1)
	@REPO_PATH=$$(python3 -c "import json,pathlib; \
	  d=json.loads(pathlib.Path('$(REPOS_DIR)/repos.json').read_text()); \
	  print(d.get('$(REPO)',''))"); \
	 test -n "$$REPO_PATH" || (echo "ERROR: $(REPO) not found in registry" && exit 1); \
	 echo "→ Triggering full scan: $(REPO)"; \
	 curl -sf -X POST $(API_URL)/scan/full \
	   -H "Content-Type: application/json" \
	   -d "{\"repo_id\":\"$(REPO)\",\"repo_path\":\"$$REPO_PATH\"}" | python3 -m json.tool

scan-all: ## Trigger full scan for all registered repos
	@python3 -c "import json,pathlib,subprocess,sys; \
	  d=json.loads(pathlib.Path('$(REPOS_DIR)/repos.json').read_text()); \
	  [subprocess.run(['make','scan',f'REPO={k}'],check=True) for k in d]"


# =============================================================================
## Agent index
# =============================================================================

.PHONY: index-regen index-regen-file index-publish index-status

index-regen: ## Regenerate all agent index files  (REPO=id)
	@test -n "$(REPO)" || (echo "ERROR: REPO=<id> required" && exit 1)
	@echo "→ Regenerating all index files for $(REPO)…"
	@curl -sf -X POST $(API_URL)/agent-index/regen \
	  -H "Content-Type: application/json" \
	  -d '{"repo_id":"$(REPO)"}' | python3 -m json.tool

index-regen-file: ## Regenerate one index file  (REPO=id FILE=modules/services--api)
	@test -n "$(REPO)"   || (echo "ERROR: REPO=<id> required"  && exit 1)
	@test -n "$(FILE)"   || (echo "ERROR: FILE=<key> required"  && exit 1)
	@curl -sf -X POST $(API_URL)/agent-index/regen \
	  -H "Content-Type: application/json" \
	  -d '{"repo_id":"$(REPO)","file_key":"$(FILE)"}' | python3 -m json.tool

index-publish: ## Publish agent index to repo  (REPO=id)
	@test -n "$(REPO)" || (echo "ERROR: REPO=<id> required" && exit 1)
	@echo "→ Publishing agent index for $(REPO)…"
	@curl -sf -X POST $(API_URL)/agent-index/publish \
	  -H "Content-Type: application/json" \
	  -d '{"repo_id":"$(REPO)"}' | python3 -m json.tool

index-regen-publish: ## Regenerate then publish  (REPO=id)
	@$(MAKE) index-regen REPO=$(REPO)
	@$(MAKE) index-publish REPO=$(REPO)

index-status: ## Show agent index file statuses  (REPO=id)
	@test -n "$(REPO)" || (echo "ERROR: REPO=<id> required" && exit 1)
	@curl -sf "$(API_URL)/agent-index/files?repo_id=$(REPO)" | \
	  python3 -c "import json,sys; \
	    files=json.load(sys.stdin); \
	    [print(f\"  {f['status']:10} {f['file_key']}\") for f in files]" 2>/dev/null \
	  || echo "  (endpoint unavailable — check console UI)"


# =============================================================================
## Neo4j database
# =============================================================================

.PHONY: neo4j-shell neo4j-status neo4j-memory neo4j-backup neo4j-restore neo4j-wipe

neo4j-shell: ## Open an interactive Cypher shell
	docker exec -it $(NEO4J) cypher-shell -u neo4j -p "$${NEO4J_PASSWORD:-codekg_dev}"

neo4j-status: ## Show Neo4j node and relationship counts per repo
	@docker exec $(NEO4J) cypher-shell -u neo4j -p "$${NEO4J_PASSWORD:-codekg_dev}" \
	  --format plain \
	  "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC;" \
	  2>/dev/null | column -t || echo "Neo4j not reachable"

neo4j-repos: ## Show registered repos and class counts in the graph
	@docker exec $(NEO4J) cypher-shell -u neo4j -p "$${NEO4J_PASSWORD:-codekg_dev}" \
	  --format plain \
	  "MATCH (r:Repository) OPTIONAL MATCH (c:Class {repo_id:r.repo_id}) \
	   RETURN r.repo_id AS repo, count(c) AS classes ORDER BY repo;" \
	  2>/dev/null | column -t || echo "Neo4j not reachable"

neo4j-memory: ## Show current Neo4j heap and page-cache usage
	@docker exec $(NEO4J) cypher-shell -u neo4j -p "$${NEO4J_PASSWORD:-codekg_dev}" \
	  --format plain \
	  "CALL dbms.queryJmx('java.lang:type=Memory') YIELD attributes \
	   RETURN attributes.HeapMemoryUsage.value AS heap;" \
	  2>/dev/null || docker stats $(NEO4J) --no-stream --format \
	  "  Mem: {{.MemUsage}}  CPU: {{.CPUPerc}}"

neo4j-backup: ## Backup Neo4j database  (TAG=label KEEP=N)
	@bash $(OPS)/neo4j-backup.sh \
	  --out "$(BACKUPS_DIR)" \
	  $(if $(TAG),--tag "$(TAG)",) \
	  $(if $(KEEP),--keep "$(KEEP)",)

neo4j-restore: ## Restore Neo4j from a dump file  (FILE=path/to/dump)
	@test -n "$(FILE)" || (echo "ERROR: FILE=<path> required" && exit 1)
	@bash $(OPS)/neo4j-restore.sh "$(FILE)"

neo4j-wipe-repo: ## Delete all nodes for one repo from the graph  (REPO=id)
	@test -n "$(REPO)" || (echo "ERROR: REPO=<id> required" && exit 1)
	@echo "WARNING: This will permanently delete all graph data for $(REPO)."
	@read -rp "  Type the repo ID to confirm: " confirm; \
	 test "$$confirm" = "$(REPO)" || (echo "Aborted." && exit 1)
	@docker exec $(NEO4J) cypher-shell -u neo4j -p "$${NEO4J_PASSWORD:-codekg_dev}" \
	  "MATCH (n {repo_id:'$(REPO)'}) DETACH DELETE n;" && \
	 echo "→ All nodes for $(REPO) deleted."

neo4j-wipe-all: ## ⚠ Delete the ENTIRE graph — all repos (requires double confirmation)
	@echo "WARNING: This will permanently wipe the ENTIRE Neo4j database."
	@read -rp "  Type 'wipe everything' to confirm: " confirm; \
	 test "$$confirm" = "wipe everything" || (echo "Aborted." && exit 1)
	@docker exec $(NEO4J) cypher-shell -u neo4j -p "$${NEO4J_PASSWORD:-codekg_dev}" \
	  "MATCH (n) DETACH DELETE n;" && \
	 echo "→ Graph wiped."


# =============================================================================
## SQLite databases
# =============================================================================

.PHONY: db-sizes db-backup db-shell-telemetry db-shell-audit db-prune-telemetry

db-sizes: ## Show sizes of all SQLite databases
	@echo "  SQLite databases in $(REPOS_DIR):"
	@ls -lh $(REPOS_DIR)/*.db 2>/dev/null | awk '{print "  " $$5 "\t" $$9}' || echo "  none found"

db-backup: ## Copy all SQLite databases to backups/  (TAG=label)
	@mkdir -p $(BACKUPS_DIR)
	@TS=$$(date +%Y%m%d_%H%M%S); \
	 LABEL=$${TAG:+-$$TAG}; \
	 DEST="$(BACKUPS_DIR)/sqlite-$$TS$$LABEL"; \
	 mkdir -p "$$DEST"; \
	 cp $(REPOS_DIR)/*.db "$$DEST/" 2>/dev/null && \
	 echo "→ Backed up SQLite DBs to $$DEST" || echo "No .db files found"

db-shell-telemetry: ## Open sqlite3 shell on telemetry.db
	@sqlite3 $(REPOS_DIR)/telemetry.db

db-shell-audit: ## Open sqlite3 shell on llm_audit.db
	@sqlite3 $(REPOS_DIR)/llm_audit.db

db-shell-mcp: ## Open sqlite3 shell on mcp_audit.db
	@sqlite3 $(REPOS_DIR)/mcp_audit.db

db-shell-index: ## Open sqlite3 shell on agent_index.db
	@sqlite3 $(REPOS_DIR)/agent_index.db

db-prune-telemetry: ## Delete telemetry rows older than N days  (DAYS=90)
	@DAYS=$${DAYS:-90}; \
	 CUTOFF=$$(date -d "-$$DAYS days" +%s 2>/dev/null || date -v -"$$DAYS"d +%s); \
	 echo "→ Deleting telemetry rows older than $$DAYS days…"; \
	 sqlite3 $(REPOS_DIR)/telemetry.db \
	   "DELETE FROM tool_calls WHERE created_at < datetime('now','-$$DAYS days'); \
	    DELETE FROM sessions WHERE started_at < datetime('now','-$$DAYS days'); \
	    VACUUM;" && echo "  Done."

db-prune-audit: ## Delete llm_audit rows older than N days  (DAYS=90)
	@DAYS=$${DAYS:-90}; \
	 sqlite3 $(REPOS_DIR)/llm_audit.db \
	   "DELETE FROM llm_calls WHERE created_at < datetime('now','-$$DAYS days'); \
	    VACUUM;" && echo "→ Deleted llm_audit rows older than $$DAYS days."


# =============================================================================
## Testing
# =============================================================================

.PHONY: test test-api test-console test-watch lint

test: ## Run all tests (no Docker required)
	@bash $(SCRIPTS)/run_tests.sh $(if $(FILTER),-k "$(FILTER)",)

test-api: ## Run API tests only
	@bash $(SCRIPTS)/run_tests.sh $(if $(FILTER),-k "$(FILTER)",) \
	  2>&1 | grep -A9999 "API unit tests" | head -9999 || true

test-console: ## Run console tests only
	@bash $(SCRIPTS)/run_tests.sh $(if $(FILTER),-k "$(FILTER)",) \
	  2>&1 | grep -A9999 "Console tests" | head -9999 || true

test-watch: ## Run tests in watch mode (requires pytest-watch)
	@VENV="$(ROOT)/.venv-test"; \
	 PYTHONPATH="$(ROOT)/services/api:$(ROOT)/services/console:$(ROOT)" \
	 "$$VENV/bin/ptw" $(ROOT)/services/ -- -v --tb=short

lint: ## Run ruff linter across all service and shared code
	@ruff check services/ shared/ || true


# =============================================================================
## Environment & configuration
# =============================================================================

.PHONY: env-check env-template config-show

env-check: ## Validate that required env vars are set in .env
	@python3 $(SCRIPTS)/healthcheck.py --env-check 2>/dev/null || \
	  python3 -c "\
import os,pathlib; \
req=['NEO4J_PASSWORD','REPOS_PATH','HOME_MOUNT']; \
rec=['ANTHROPIC_API_KEY','API_TOKEN','SESSION_SECRET']; \
[os.environ.setdefault(k.strip(),v.strip()) for l in (pathlib.Path('.env').read_text().splitlines() if pathlib.Path('.env').exists() else []) if '=' in l and not l.startswith('#') for k,_,v in [l.partition('=')] ]; \
miss=[k for k in req if not os.environ.get(k)]; \
warn=[k for k in rec if not os.environ.get(k)]; \
miss and print('MISSING (required):',', '.join(miss)); \
warn and print('MISSING (recommended):',', '.join(warn)); \
miss and exit(1) or print('OK — all required vars present')"

env-template: ## Write .env from .env.example if .env does not exist
	@test -f .env && echo ".env already exists — not overwriting" || \
	 (cp .env.example .env && echo "→ Created .env from .env.example — edit before starting")

config-show: ## Print live configuration loaded by the API container
	@docker exec $(API) python3 -c \
	  "from shared.config import cfg; import dataclasses as dc, json; \
	   _s = lambda k: '***' if any(w in k.lower() for w in ('password','secret','key','token')) else None; \
	   _d = lambda o: {f.name: _s(f.name) or _d(getattr(o,f.name)) if dc.is_dataclass(getattr(o,f.name)) else _s(f.name) if _s(f.name) else getattr(o,f.name) for f in dc.fields(o)} if dc.is_dataclass(o) else o; \
	   print(json.dumps(_d(cfg), indent=2))" 2>/dev/null | python3 -m json.tool


# =============================================================================
## Secrets & tokens
# =============================================================================

.PHONY: gen-token gen-session-secret

gen-token: ## Generate a random API bearer token (copy into .env → API_TOKEN)
	@python3 -c "import secrets; print(secrets.token_urlsafe(32))"

gen-session-secret: ## Generate a random session signing secret (copy into .env → SESSION_SECRET)
	@python3 -c "import secrets; print(secrets.token_urlsafe(32))"


# =============================================================================
## Ingestion & parsing
# =============================================================================

.PHONY: scan-status watcher-poll

scan-status: ## Show recent scan log entries
	@sqlite3 -column -header $(REPOS_DIR)/scan_log.db \
	  "SELECT repo_id, scan_type, status, started_at, duration_s \
	   FROM scan_log ORDER BY started_at DESC LIMIT 20;" 2>/dev/null \
	  || echo "scan_log.db not found or empty"

watcher-poll: ## Manually trigger one watcher poll cycle (forces commit-check now)
	@docker exec $(WATCHER) python3 -c \
	  "import asyncio,sys; sys.path.insert(0,'/app'); import main as w; asyncio.run(w.poll_once())" \
	  2>/dev/null || echo "watcher container not running or poll_once not exported"


# =============================================================================
## MCP
# =============================================================================

.PHONY: mcp-test mcp-tools

mcp-tools: ## List tools exposed by the MCP server
	@curl -sf $(API_URL)/llm/providers | python3 -m json.tool 2>/dev/null || \
	 echo "API not reachable — start the stack first"

mcp-test: ## Send a test tool call to the MCP API  (REPO=id)
	@test -n "$(REPO)" || (echo "ERROR: REPO=<id> required" && exit 1)
	@curl -sf -X GET "$(API_URL)/repos/$(REPO)" | python3 -m json.tool


# =============================================================================
## Cleanup
# =============================================================================

.PHONY: clean clean-images clean-volumes prune

clean: ## Remove stopped containers and dangling images
	docker system prune -f

clean-images: ## Remove all codekg-* images
	@docker images --filter "reference=codekg-*" -q | xargs -r docker rmi -f && \
	 echo "→ codeKG images removed" || true

clean-volumes: ## ⚠ Remove Neo4j data volumes (loses ALL graph data)
	@echo "WARNING: This destroys all Neo4j data. Backup first with: make neo4j-backup"
	@read -rp "  Type 'delete volumes' to confirm: " confirm; \
	 test "$$confirm" = "delete volumes" || (echo "Aborted." && exit 1)
	$(COMPOSE) down -v
	@echo "→ Volumes removed."

clean-pycache: ## Remove all __pycache__ directories from the project
	@find $(ROOT) -type d -name __pycache__ -not -path "*/.venv*" -exec rm -rf {} + 2>/dev/null; \
	 echo "→ __pycache__ cleaned"

prune: ## Docker system prune (removes all unused resources)
	docker system prune -af --volumes


# =============================================================================
## Repo backups  (Neo4j + agent_index + scan_log per repo_id)
# =============================================================================

.PHONY: repo-backup repo-restore repo-backup-list

repo-backup: ## Bundle all data for one repo  (REPO=id [TAG=label])
	@test -n "$(REPO)" || (echo "ERROR: REPO=<id> required" && exit 1)
	@python3 $(SCRIPTS)/repo_backup.py backup \
	  --repo "$(REPO)" \
	  --out  "$(BACKUPS_DIR)" \
	  $(if $(TAG),--tag "$(TAG)",)

repo-restore: ## Restore a repo bundle  (FILE=path/to/bundle.tar.gz [YES=1])
	@test -n "$(FILE)" || (echo "ERROR: FILE=<path> required" && exit 1)
	@python3 $(SCRIPTS)/repo_backup.py restore \
	  --file "$(FILE)" \
	  $(if $(filter 1 yes true,$(YES)),--yes,)

repo-backup-list: ## List all per-repo backup bundles
	@python3 $(SCRIPTS)/repo_backup.py list --dir "$(BACKUPS_DIR)"


# =============================================================================
## Backups (full-stack)
# =============================================================================

.PHONY: backup restore backup-list

backup: ## Full backup: Neo4j dump + all SQLite databases  (TAG=label)
	@$(MAKE) neo4j-backup TAG=$(TAG)
	@$(MAKE) db-backup     TAG=$(TAG)
	@echo "→ Backup complete. Files in $(BACKUPS_DIR)/"

backup-list: ## List all full-stack backup files
	@echo "Neo4j dumps:"
	@ls -lht $(BACKUPS_DIR)/*.dump 2>/dev/null | head -10 | awk '{print "  " $$6" "$$7" "$$9}' || echo "  none"
	@echo "SQLite snapshots:"
	@ls -dt $(BACKUPS_DIR)/sqlite-* 2>/dev/null | head -5 | awk '{print "  " $$0}' || echo "  none"
	@echo "Repo bundles:"
	@ls -lht $(BACKUPS_DIR)/codekg-backup-*.tar.gz 2>/dev/null | head -10 | awk '{print "  " $$5" "$$6" "$$7" "$$9}' || echo "  none"

restore: ## Restore Neo4j from a full dump  (FILE=path/to/dump)
	@$(MAKE) neo4j-restore FILE=$(FILE)


# =============================================================================
## First-time setup
# =============================================================================

.PHONY: setup setup-dirs

setup-dirs: ## Create required host directories
	@mkdir -p $(REPOS_DIR) $(BACKUPS_DIR)
	@echo "→ Directories ready"
	@test -f $(REPOS_DIR)/repos.json || (echo '{}' > $(REPOS_DIR)/repos.json && echo "→ Created empty repos.json")

setup: ## Full first-time setup: dirs + .env + build + start
	@$(MAKE) setup-dirs
	@$(MAKE) env-template
	@echo ""
	@echo "→ Edit .env before continuing (set NEO4J_PASSWORD, HOME_MOUNT, ANTHROPIC_API_KEY)"
	@echo "  Then run: make up"
