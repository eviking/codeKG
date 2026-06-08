"""
Watcher service — polls registered git repos for new commits and launches
ephemeral ingestion containers per repo. Each repo scans independently —
no blocking, no queue.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import docker as _docker_sdk
import git
import httpx

from shared.config import cfg
from shared.codekg_logging.codekg_logger import get_logger

log = get_logger(__name__, service="watcher")

API_URL         = cfg.services.api_url
REPOS_PATH      = cfg.paths.repos_path
POLL_INTERVAL   = cfg.watcher.poll_interval
REPOS_REGISTRY  = cfg.paths.repos_registry

INGESTION_IMAGE = cfg.ingestion.ingestion_image
NEO4J_URI       = cfg.neo4j.uri
NEO4J_USER      = cfg.neo4j.user
NEO4J_PASSWORD  = cfg.neo4j.password
HOME_MOUNT      = cfg.paths.home_mount
DOCKER_NETWORK  = cfg.services.docker_network
HOST_REPOS_PATH = cfg.paths.host_repos_path


def load_repos() -> dict[str, str]:
    registry = Path(REPOS_REGISTRY)
    if registry.exists():
        try:
            return json.loads(registry.read_text())
        except Exception as e:
            log.warning("Could not read repos registry", error=str(e))
            return {}
    discovered = {}
    for p in Path(REPOS_PATH).iterdir():
        if p.is_dir() and (p / ".git").exists():
            discovered[p.name] = str(p)
    return discovered


def _is_scan_running(repo_id: str) -> bool:
    try:
        client = _docker_sdk.from_env()
        containers = client.containers.list(filters={"label": f"codekg.repo_id={repo_id}"})
        return bool(containers)
    except Exception as e:
        log.warning("Failed to check running scan containers", repo_id=repo_id, exc=e)
        return False


def _launch_scan(repo_id: str, repo_path: str, scan_type: str = "full",
                 from_commit: str = "", to_commit: str = ""):
    client = _docker_sdk.from_env()
    env = {
        "NEO4J_URI":      NEO4J_URI,
        "NEO4J_USER":     NEO4J_USER,
        "NEO4J_PASSWORD": NEO4J_PASSWORD,
        "REPOS_PATH":     "/repos",
        "SCAN_REPO_ID":   repo_id,
        "SCAN_REPO_PATH": repo_path,
        "SCAN_TYPE":      scan_type,
    }
    if scan_type == "incremental":
        env["SCAN_FROM_COMMIT"] = from_commit
        env["SCAN_TO_COMMIT"]   = to_commit

    host_repos = HOST_REPOS_PATH or REPOS_PATH
    volumes = {host_repos: {"bind": "/repos", "mode": "rw"}}
    if HOME_MOUNT:
        volumes[HOME_MOUNT] = {"bind": "/host-home", "mode": "ro"}

    client.containers.run(
        INGESTION_IMAGE,
        command=["python", "run_scan.py"],
        detach=True,
        remove=True,
        environment=env,
        volumes=volumes,
        network=DOCKER_NETWORK,
        name=f"codekg-scan-{repo_id.lower().replace(' ', '-')}",
        labels={
            "codekg.scan":      "true",
            "codekg.repo_id":   repo_id,
            "codekg.scan_type": scan_type,
        },
    )
    log.info("Scan container launched", repo_id=repo_id, type=scan_type)


async def check_repo(client: httpx.AsyncClient, repo_id: str, repo_path: str):
    # Skip if already scanning this repo
    if _is_scan_running(repo_id):
        log.debug("Scan already running — skipping poll", repo_id=repo_id)
        return

    try:
        repo = git.Repo(repo_path)
    except Exception as exc:
        log.warning("Cannot open repo", repo_id=repo_id, path=repo_path, error=str(exc))
        return

    try:
        current_head = repo.head.commit.hexsha
    except Exception as exc:
        log.warning("Cannot read HEAD", repo_id=repo_id, error=str(exc))
        return

    last_commit = None
    try:
        resp = await client.get(f"{API_URL}/repos/{repo_id}", timeout=10.0)
        if resp.status_code == 200:
            last_commit = resp.json().get("last_commit")
    except Exception as exc:
        log.debug("API unreachable", repo_id=repo_id, error=str(exc))

    if last_commit is None:
        log.info("No indexed commit — triggering full scan", repo_id=repo_id)
        try:
            _launch_scan(repo_id, repo_path, scan_type="full")
        except Exception as exc:
            log.error("Failed to launch full scan", repo_id=repo_id, error=str(exc))

    elif last_commit != current_head:
        log.info("New commits detected", repo_id=repo_id,
                 from_commit=last_commit[:8], to_commit=current_head[:8])
        try:
            _launch_scan(repo_id, repo_path, scan_type="incremental",
                         from_commit=last_commit, to_commit=current_head)
        except Exception as exc:
            log.error("Failed to launch incremental scan", repo_id=repo_id, error=str(exc))

        # Age knowledge entries for changed files
        try:
            changed_files = []
            for commit in repo.iter_commits(f"{last_commit}..{current_head}"):
                changed_files.extend(commit.stats.files.keys())
            if changed_files:
                await client.post(
                    f"{API_URL}/insights/update-staleness",
                    json={"changed_files": list(set(changed_files)), "commit_sha": current_head},
                    timeout=10.0,
                )
        except Exception as exc:
            log.warning("Knowledge staleness update failed", repo_id=repo_id, error=str(exc))
    else:
        log.debug("No new commits", repo_id=repo_id, commit=current_head[:8])


async def main():
    log.info("Watcher started", poll_interval_sec=POLL_INTERVAL)
    async with httpx.AsyncClient() as client:
        while True:
            repos = load_repos()
            if not repos:
                log.warning("No repos registered")
            else:
                for repo_id, repo_path in repos.items():
                    await check_repo(client, repo_id, repo_path)
            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
