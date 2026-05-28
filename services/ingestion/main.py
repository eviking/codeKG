"""
Ingestion service — FastAPI app exposing endpoints for the watcher to trigger
full scans and incremental updates.
"""
import logging
import os

from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel

from kg.writer import KGWriter
from ingestion_engine import IngestionEngine

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title="CodeKG Ingestion Service")

NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USER = os.environ["NEO4J_USER"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]

writer = KGWriter(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
engine = IngestionEngine(writer)


@app.on_event("startup")
async def startup():
    writer.ensure_schema()
    log.info("Schema ensured.")


class FullScanRequest(BaseModel):
    repo_path: str
    repo_id: str


class IncrementalRequest(BaseModel):
    repo_path: str
    repo_id: str
    from_commit: str
    to_commit: str


@app.post("/scan/full")
async def full_scan(req: FullScanRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(engine.full_scan, req.repo_path, req.repo_id)
    return {"status": "started", "repo_id": req.repo_id}


@app.post("/scan/incremental")
async def incremental_scan(req: IncrementalRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(
        engine.incremental_update,
        req.repo_path, req.repo_id, req.from_commit, req.to_commit,
    )
    return {"status": "started", "repo_id": req.repo_id,
            "from": req.from_commit, "to": req.to_commit}


@app.get("/health")
async def health():
    return {"status": "ok"}
