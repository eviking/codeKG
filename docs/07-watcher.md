# Watcher Service

> A lightweight async loop that polls registered git repositories every 30 seconds, detects new commits, and launches ephemeral ingestion containers to keep the knowledge graph current.

---

## What the watcher does

```
every 30 seconds:
  for each registered repo:
    1. Read HEAD commit from local git clone
    2. Compare to last known commit (from api /last-commit/{repo_id})
    3. If new commit detected:
       a. Check no scan is already running for this repo
       b. Launch docker run codekg-ingestion with env vars
       c. Wait for container exit (async, non-blocking for other repos)
       d. Notify API of scan completion
       e. Trigger agent index regen + publish
```

Each repo is polled independently. A slow scan on one repo doesn't delay polling on another.

---

## Repo registry

The watcher loads repos from `/repos/repos.json`:

```json
{
  "my-service":    "/host-home/code/my-service",
  "another-repo":  "/host-home/code/another-repo"
}
```

The `/host-home/` prefix corresponds to the `HOME_MOUNT` env var — the host directory mounted into the container. If `HOME_MOUNT=/Users/yourname`, then `/host-home/code/my-service` maps to `/Users/yourname/code/my-service` on the host.

If the file doesn't exist, the watcher falls back to discovering repos by scanning `/repos/` for directories containing `.git`. Repos can be added at runtime — the registry is re-read on each poll cycle.

---

## Scan container lifecycle

```python
def _launch_scan(repo_id: str, repo_path: str, scan_type: str = "full",
                 from_commit: str = "", to_commit: str = ""):
    client = docker.from_env()
    container = client.containers.run(
        image=INGESTION_IMAGE,                    # "codekg-ingestion"
        environment={
            "REPO_ID":       repo_id,
            "REPO_PATH":     repo_path,
            "SCAN_TYPE":     scan_type,           # "full" or "incremental"
            "FROM_COMMIT":   from_commit,
            "TO_COMMIT":     to_commit,
            "NEO4J_URI":     NEO4J_URI,
            "NEO4J_USER":    NEO4J_USER,
            "NEO4J_PASSWORD": NEO4J_PASSWORD,
        },
        volumes={
            HOME_MOUNT: {"bind": "/host-home", "mode": "rw"},
        },
        network=DOCKER_NETWORK,
        labels={"codekg.repo_id": repo_id},      # used to detect running scans
        detach=True,
        remove=True,                              # container auto-deleted on exit
    )
    return container
```

The `remove=True` flag means completed containers are automatically cleaned up. No container accumulation.

---

## Incremental vs full scan

| Scan type | When | What happens |
|-----------|------|-------------|
| `full` | First time a repo is registered | Parse every file in the repo |
| `incremental` | Every subsequent commit | Parse only files changed between `from_commit` and `to_commit` |

The watcher determines scan type by checking whether the repo has been scanned before (via `GET /last-commit/{repo_id}`). If the API returns no commit, it's a fresh repo — full scan.

For incremental scans, `from_commit` and `to_commit` are passed to the ingestion engine, which uses `git diff` to identify changed files.

---

## Overlap prevention

```python
def _is_scan_running(repo_id: str) -> bool:
    client = docker.from_env()
    containers = client.containers.list(
        filters={"label": f"codekg.repo_id={repo_id}"}
    )
    return bool(containers)
```

If a scan container is still running for a repo when the next poll detects a new commit, the new scan is skipped. The watcher logs a warning and waits for the next cycle.

This prevents:
- Concurrent writes to Neo4j from the same repo
- Race conditions in `delete_file_nodes` + `wire_edges`
- Doubled scans when a repo receives rapid commits

---

## Post-scan flow

After the ingestion container exits successfully:

```python
# 1. Notify API that scan completed
await api.post(f"/scan-complete/{repo_id}", json={"commit_sha": to_commit})

# 2. Trigger agent index regeneration
await api.post("/agent-index/regen", json={"repo_id": repo_id})

# 3. Trigger agent index publish (writes .codekg/ + git commit)
await api.post("/agent-index/publish", json={"repo_id": repo_id})
```

The agent index is regenerated and published automatically on every successful scan. Agents always see fresh `.codekg/` files.

---

## Configuration

| Environment variable | Default | Purpose |
|---------------------|---------|---------|
| `POLL_INTERVAL` | `30` | Seconds between poll cycles |
| `REPOS_REGISTRY` | `/repos/repos.json` | Path to repo registry |
| `REPOS_PATH` | `/repos` | Fallback scan path if no registry |
| `API_URL` | `http://api:8000` | API service URL |
| `INGESTION_IMAGE` | `codekg-ingestion` | Docker image for scan containers |
| `NEO4J_URI` | `bolt://neo4j:7687` | Passed to ingestion container |
| `NEO4J_USER` | `neo4j` | Passed to ingestion container |
| `NEO4J_PASSWORD` | `codekg_dev` | Passed to ingestion container |
| `HOME_MOUNT` | — | Host home directory (mounted into scan containers) |
| `DOCKER_NETWORK` | `codekg_codekg` | Docker network for scan containers |
| `HOST_REPOS_PATH` | — | Host-side repos path for volume mounts |

---

## Volume mounts for scan containers

The watcher mounts the host home directory into each scan container so the ingestion engine can read the actual repo files:

```yaml
# docker-compose.yml (watcher service)
volumes:
  - ${HOME_MOUNT:-/tmp/codekg-empty}:/host-home:rw
  - /var/run/docker.sock:/var/run/docker.sock:ro
  - ${REPOS_PATH:-./repos}:/repos
```

The Docker socket mount (`/var/run/docker.sock`) is required for the watcher to launch containers. This is a privileged operation — treat the watcher container with appropriate security policy.

---

## Monitoring

The watcher logs every event as structured JSON via `codekg_logger`:

```json
{"event": "new_commit_detected", "repo_id": "codeKG", "from": "abc123", "to": "def456", "timestamp": "..."}
{"event": "scan_launched", "repo_id": "codeKG", "scan_type": "incremental", "image": "codekg-ingestion"}
{"event": "scan_complete", "repo_id": "codeKG", "duration_s": 42, "exit_code": 0}
{"event": "scan_skipped", "repo_id": "codeKG", "reason": "scan_already_running"}
{"event": "regen_triggered", "repo_id": "codeKG"}
{"event": "publish_complete", "repo_id": "codeKG", "files_written": 16, "sha": "d4e8f21"}
```

View in real-time: `docker compose logs -f watcher`

System health page in the console shows the last scan time and status per repo.

---

## Adding a new repo

**Via the console UI:**
1. Go to `http://localhost:8080/repos`
2. Click "Add repository"
3. Enter the repo ID and path (must be accessible as `/host-home/...`)

**Directly:**
```bash
# Edit /path/to/repos/repos.json
{"my-service": "/host-home/code/my-service", "new-repo": "/host-home/path/to/new-repo"}
```

The watcher picks up the new entry on its next poll cycle (within 30 seconds) and launches a full scan.

---

## Common issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Scan never triggers | Repo path uses uppercase on Linux | Path case mismatch — normalise to lowercase |
| Container starts but immediately fails | HOME_MOUNT not set or wrong | Check `env HOME_MOUNT` and the docker-compose volume |
| Scan runs but Neo4j is empty | Wrong NEO4J_URI in scan container | Check DOCKER_NETWORK — containers must be on same network |
| Watcher can't launch containers | Docker socket not mounted | Ensure `/var/run/docker.sock:/var/run/docker.sock:ro` in watcher volumes |
| Same repo scanned multiple times | Scan finishes faster than poll interval | Not a problem — overlap prevention handles this |
| Agent index not updating after scan | API regen/publish failing | Check `docker compose logs api` for errors |
