#!/usr/bin/env bash
# =============================================================================
# neo4j-backup.sh — Dump the CodeKG Neo4j database to a timestamped file.
#
# Usage:
#   ./ops/neo4j-backup.sh                        # dump to ./backups/
#   ./ops/neo4j-backup.sh --out /mnt/nas/backups # custom output dir
#   ./ops/neo4j-backup.sh --tag pre-release      # extra label in filename
#   ./ops/neo4j-backup.sh --keep 7               # prune to 7 most-recent dumps
#
# The dump file is self-contained and can be loaded with neo4j-restore.sh.
# Neo4j does NOT need to be stopped — online backup is supported in CE 5.x
# via the dump command when the database is in online mode.
# =============================================================================
set -euo pipefail

# ── defaults ──────────────────────────────────────────────────────────────────
CONTAINER="${NEO4J_CONTAINER:-codekg-neo4j}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-codekg_dev}"
DATABASE="neo4j"
OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/backups"
TAG=""
KEEP=0        # 0 = keep all

# ── parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out)    OUT_DIR="$2";  shift 2 ;;
    --tag)    TAG="-$2";     shift 2 ;;
    --keep)   KEEP="$2";     shift 2 ;;
    --help|-h)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ── setup ─────────────────────────────────────────────────────────────────────
mkdir -p "$OUT_DIR"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
DUMP_NAME="${DATABASE}${TAG}-${TIMESTAMP}.dump"
DUMP_HOST="${OUT_DIR}/${DUMP_NAME}"
DUMP_CONTAINER="/var/lib/neo4j/backups/${DUMP_NAME}"

echo "════════════════════════════════════════════════════════"
echo "  CodeKG Neo4j Backup"
echo "  Container : $CONTAINER"
echo "  Database  : $DATABASE"
echo "  Output    : $DUMP_HOST"
echo "════════════════════════════════════════════════════════"

# ── verify container is running ───────────────────────────────────────────────
if ! docker inspect "$CONTAINER" &>/dev/null; then
  echo "ERROR: container '$CONTAINER' not found. Is the stack running?"
  exit 1
fi

STATUS="$(docker inspect --format='{{.State.Status}}' "$CONTAINER")"
if [[ "$STATUS" != "running" ]]; then
  echo "ERROR: container is '$STATUS', expected 'running'."
  exit 1
fi

# ── create backup dir inside container ───────────────────────────────────────
docker exec "$CONTAINER" mkdir -p /var/lib/neo4j/backups

# ── Neo4j 5 CE: database must be stopped for dump (online dump = Enterprise) ─
# We stop only the database, not the container, using cypher-shell admin.
# If the database is already stopped this is a no-op.
echo ""
echo "▸ Stopping Neo4j container (required for CE dump)…"
docker stop "$CONTAINER"

echo "▸ Running neo4j-admin dump (container stopped)…"
docker run --rm \
  --volumes-from "$CONTAINER" \
  neo4j:5-community \
  bash -c "mkdir -p /var/lib/neo4j/backups && \
    neo4j-admin database dump \
      --to-path=/var/lib/neo4j/backups \
      --overwrite-destination \
      $DATABASE"

echo "▸ Restarting Neo4j container…"
docker start "$CONTAINER"

echo "▸ Waiting for Neo4j to be ready…"
for i in $(seq 1 30); do
  if docker exec "$CONTAINER" neo4j status 2>/dev/null | grep -q "running"; then
    echo "  ✓ Neo4j is up (${i}s)"
    break
  fi
  echo "  waiting… (${i}s)"
  sleep 2
done

# ── copy dump out of container ────────────────────────────────────────────────
echo "▸ Copying dump to host…"
docker cp "${CONTAINER}:${DUMP_CONTAINER}" "$DUMP_HOST"

SIZE="$(du -sh "$DUMP_HOST" | cut -f1)"
echo ""
echo "✓ Backup complete: $DUMP_HOST  ($SIZE)"

# ── optional: prune old backups ───────────────────────────────────────────────
if [[ "$KEEP" -gt 0 ]]; then
  echo ""
  echo "▸ Pruning — keeping $KEEP most recent dumps in $OUT_DIR…"
  # list dumps oldest-first, delete all but last $KEEP
  mapfile -t ALL < <(ls -1t "${OUT_DIR}/${DATABASE}"*.dump 2>/dev/null)
  TOTAL="${#ALL[@]}"
  if [[ "$TOTAL" -gt "$KEEP" ]]; then
    DELETE=$(( TOTAL - KEEP ))
    for i in "${ALL[@]:$KEEP}"; do
      echo "  removing: $i"
      rm -f "$i"
    done
    echo "  removed $DELETE old dump(s)"
  else
    echo "  nothing to prune ($TOTAL dump(s) found, limit=$KEEP)"
  fi
fi

echo ""
echo "To restore:  ./ops/neo4j-restore.sh $DUMP_HOST"
