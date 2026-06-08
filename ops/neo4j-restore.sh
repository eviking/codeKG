#!/usr/bin/env bash
# =============================================================================
# neo4j-restore.sh — Load a dump file into a CodeKG Neo4j instance.
#
# Works for:
#   • Local restore (dev machine or CI)
#   • Remote restore to Railway / any Docker host via SSH
#
# Usage:
#   ./ops/neo4j-restore.sh ./backups/neo4j-20240529-120000.dump
#   ./ops/neo4j-restore.sh ./backups/neo4j-20240529-120000.dump --remote user@railway-host
#   ./ops/neo4j-restore.sh --latest                             # auto-pick newest dump
#   ./ops/neo4j-restore.sh --latest --remote user@host
#
# WARNING: this OVERWRITES the target database. All existing data will be lost.
# =============================================================================
set -euo pipefail

CONTAINER="${NEO4J_CONTAINER:-codekg-neo4j}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-codekg_dev}"
DATABASE="neo4j"
BACKUPS_DIR="$(cd "$(dirname "$0")/.." && pwd)/backups"
DUMP_FILE=""
REMOTE=""   # user@host — if set, copies dump via scp then restores over SSH
LATEST=0

# ── parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --latest)  LATEST=1;        shift ;;
    --remote)  REMOTE="$2";     shift 2 ;;
    --container) CONTAINER="$2"; shift 2 ;;
    --help|-h)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    -*)
      echo "Unknown option: $1"; exit 1 ;;
    *)
      DUMP_FILE="$1"; shift ;;
  esac
done

# ── resolve dump file ──────────────────────────────────────────────────────────
if [[ "$LATEST" -eq 1 ]]; then
  DUMP_FILE="$(ls -1t "${BACKUPS_DIR}/${DATABASE}"*.dump 2>/dev/null | head -1)"
  if [[ -z "$DUMP_FILE" ]]; then
    echo "ERROR: no dump files found in $BACKUPS_DIR"
    exit 1
  fi
  echo "Auto-selected latest dump: $DUMP_FILE"
fi

if [[ -z "$DUMP_FILE" ]]; then
  echo "ERROR: no dump file specified. Pass a path or use --latest."
  echo "Usage: $0 <dump-file> [--remote user@host]"
  exit 1
fi

if [[ ! -f "$DUMP_FILE" ]]; then
  echo "ERROR: dump file not found: $DUMP_FILE"
  exit 1
fi

DUMP_ABS="$(cd "$(dirname "$DUMP_FILE")" && pwd)/$(basename "$DUMP_FILE")"
DUMP_BASENAME="$(basename "$DUMP_FILE")"
SIZE="$(du -sh "$DUMP_ABS" | cut -f1)"

echo "════════════════════════════════════════════════════════"
echo "  CodeKG Neo4j Restore"
echo "  Dump file : $DUMP_ABS  ($SIZE)"
echo "  Database  : $DATABASE"
echo "  Container : $CONTAINER"
if [[ -n "$REMOTE" ]]; then
echo "  Remote    : $REMOTE"
fi
echo "════════════════════════════════════════════════════════"
echo ""
echo "⚠  WARNING: this will OVERWRITE the '$DATABASE' database."
read -r -p "   Type YES to continue: " CONFIRM
if [[ "$CONFIRM" != "YES" ]]; then
  echo "Aborted."
  exit 0
fi

# ── helpers ───────────────────────────────────────────────────────────────────
_docker() {
  if [[ -n "$REMOTE" ]]; then
    ssh "$REMOTE" "docker $*"
  else
    docker "$@"
  fi
}

_docker_exec() {
  if [[ -n "$REMOTE" ]]; then
    ssh "$REMOTE" "docker exec $CONTAINER $*"
  else
    docker exec "$CONTAINER" "$@"
  fi
}

# ── copy dump to target host ───────────────────────────────────────────────────
DUMP_CONTAINER="/var/lib/neo4j/backups/${DUMP_BASENAME}"

if [[ -n "$REMOTE" ]]; then
  echo "▸ Copying dump to remote host $REMOTE…"
  ssh "$REMOTE" "docker exec $CONTAINER mkdir -p /var/lib/neo4j/backups"
  # stream through docker cp via SSH
  cat "$DUMP_ABS" | ssh "$REMOTE" \
    "docker exec -i $CONTAINER bash -c 'cat > ${DUMP_CONTAINER}'"
  echo "  ✓ copied ($SIZE)"
else
  echo "▸ Copying dump into container…"
  docker exec "$CONTAINER" mkdir -p /var/lib/neo4j/backups
  docker cp "$DUMP_ABS" "${CONTAINER}:${DUMP_CONTAINER}"
  echo "  ✓ copied"
fi

# ── stop database, load, restart ──────────────────────────────────────────────
echo "▸ Stopping Neo4j container…"
if [[ -n "$REMOTE" ]]; then
  ssh "$REMOTE" "docker stop $CONTAINER"
else
  docker stop "$CONTAINER"
fi

echo "▸ Loading dump (this may take a few minutes for large databases)…"
if [[ -n "$REMOTE" ]]; then
  ssh "$REMOTE" "docker run --rm \
    --volumes-from $CONTAINER \
    --entrypoint neo4j-admin \
    neo4j:5-community \
    database load \
      --from-path=/var/lib/neo4j/backups \
      --overwrite-destination \
      $DATABASE"
else
  docker run --rm \
    --volumes-from "$CONTAINER" \
    neo4j:5-community \
    bash -c "neo4j-admin database load \
      --from-path=/var/lib/neo4j/backups \
      --overwrite-destination \
      $DATABASE"
fi

echo "▸ Starting Neo4j container…"
if [[ -n "$REMOTE" ]]; then
  ssh "$REMOTE" "docker start $CONTAINER"
else
  docker start "$CONTAINER"
fi

echo "▸ Waiting for Neo4j to be ready…"
for i in $(seq 1 30); do
  READY=$(_docker_exec neo4j status 2>/dev/null | grep -c "running" || true)
  if [[ "$READY" -gt 0 ]]; then echo "  ✓ Neo4j is up (${i}s)"; break; fi
  echo "  waiting… (${i}s)"; sleep 2
done

# ── verify ────────────────────────────────────────────────────────────────────
echo "▸ Verifying restore…"
sleep 3
COUNTS=$(_docker_exec \
  cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" \
    "MATCH (n) RETURN count(n) AS nodes;" --format plain 2>/dev/null || echo "?")
echo "  Node count: $COUNTS"

echo ""
echo "✓ Restore complete."
if [[ -n "$REMOTE" ]]; then
  echo "  Remote database $REMOTE is ready."
else
  echo "  Local database is ready."
fi
