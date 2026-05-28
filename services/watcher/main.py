"""
Watcher service — polls registered git repos for new commits and triggers
incremental ingestion. On first run (no last_commit recorded), triggers a full scan.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import git
import httpx

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

INGESTION_URL = os.environ.get("INGESTION_URL", "http://ingestion:8001")
REPOS_PATH = os.environ.get("REPOS_PATH", "/repos")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))

# repos.json maps repo_id → local path, e.g.:
# {"org/my-service": "/repos/my-service"}
REPOS_REGISTRY = os.environ.get("REPOS_REGISTRY", "/repos/repos.json")


def load_repos() -> dict[str, str]:
    registry = Path(REPOS_REGISTRY)
    if registry.exists():
        return json.loads(registry.read_text())
    # fallback: auto-discover any git repos under REPOS_PATH
    discovered = {}
    for p in Path(REPOS_PATH).iterdir():
        if p.is_dir() and (p / ".git").exists():
            repo_id = p.name
            discovered[repo_id] = str(p)
    return discovered


async def check_repo(client: httpx.AsyncClient, repo_id: str, repo_path: str):
    try:
        repo = git.Repo(repo_path)
    except Exception as exc:
        log.warning("Cannot open repo %s: %s", repo_path, exc)
        return

    current_head = repo.head.commit.hexsha

    # Ask the API for the last recorded commit
    resp = await client.get(f"{INGESTION_URL.replace('8001', '8000').replace('ingestion', 'api')}/repos/{repo_id}")
    # Fall back to ingestion service direct endpoint
    try:
        resp = await client.get(f"http://api:8000/repos/{repo_id}")
        if resp.status_code == 200:
            last_commit = resp.json().get("last_commit")
        else:
            last_commit = None
    except Exception:
        last_commit = None

    if last_commit is None:
        log.info("No last commit for %s — triggering full scan", repo_id)
        await client.post(
            f"{INGESTION_URL}/scan/full",
            json={"repo_path": repo_path, "repo_id": repo_id},
            timeout=600.0,
        )
    elif last_commit != current_head:
        log.info("New commits for %s: %s → %s", repo_id, last_commit[:8], current_head[:8])
        await client.post(
            f"{INGESTION_URL}/scan/incremental",
            json={
                "repo_path": repo_path,
                "repo_id": repo_id,
                "from_commit": last_commit,
                "to_commit": current_head,
            },
            timeout=300.0,
        )
    else:
        log.debug("No new commits for %s", repo_id)


async def main():
    log.info("Watcher started. Poll interval: %ds", POLL_INTERVAL)
    async with httpx.AsyncClient() as client:
        while True:
            repos = load_repos()
            if not repos:
                log.warning("No repos registered at %s", REPOS_REGISTRY)
            for repo_id, repo_path in repos.items():
                await check_repo(client, repo_id, repo_path)
            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
