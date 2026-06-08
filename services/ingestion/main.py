"""
Ingestion service — minimal FastAPI stub.

Scan jobs are now run as ephemeral Docker containers (run_scan.py).
This service only exists for the claude-md/refresh endpoint which the
console calls after a scan completes to regenerate CLAUDE.md.
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from shared.config import cfg
from shared.codekg_logging.codekg_logger import get_logger
from kg.writer import KGWriter

log = get_logger(__name__, service="ingestion")

app = FastAPI(title="CodeKG Ingestion Service")

writer = KGWriter(cfg.neo4j.uri, cfg.neo4j.user, cfg.neo4j.password)


@app.on_event("startup")
async def startup():
    writer.ensure_schema()
    log.info("Ingestion service ready")


class RepoRequest(BaseModel):
    """Validates ingestion requests for a repository path and identifier. Watch out for trust boundaries here, because these values come from external callers and drive filesystem access."""

    repo_path: str
    repo_id: str


@app.post("/claude-md/refresh")
async def refresh_claude_md(req: RepoRequest):
    from claude_md_writer import write_claude_md
    ok = write_claude_md(writer._driver, req.repo_id, req.repo_path)
    if ok:
        log.info("CLAUDE.md refreshed", repo_id=req.repo_id)
        return {"status": "ok", "repo_id": req.repo_id}
    return JSONResponse(status_code=500, content={"status": "error", "repo_id": req.repo_id})


@app.get("/health")
async def health():
    return {"status": "ok"}
