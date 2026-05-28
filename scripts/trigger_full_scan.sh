#!/usr/bin/env bash
# Trigger a full baseline scan for a registered repo via the ingestion API.
# Usage: ./scripts/trigger_full_scan.sh <repo_id> <repo_path>
# Example: ./scripts/trigger_full_scan.sh org/my-service /repos/my-service

set -e
REPO_ID=${1:?Usage: $0 <repo_id> <repo_path>}
REPO_PATH=${2:?Usage: $0 <repo_id> <repo_path>}
INGESTION_URL=${INGESTION_URL:-http://localhost:8001}

curl -s -X POST "$INGESTION_URL/scan/full" \
  -H "Content-Type: application/json" \
  -d "{\"repo_id\": \"$REPO_ID\", \"repo_path\": \"$REPO_PATH\"}" | python3 -m json.tool
