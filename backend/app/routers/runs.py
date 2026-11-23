from typing import Any
from fastapi import APIRouter, BackgroundTasks
from app.db import get_db
from app.services.digest import build_daily_digest, send_daily_digest
from app.services.ingest import is_ingest_running, run_all_connectors

router = APIRouter(prefix="/api", tags=["runs & digest"])


@router.get("/runs")
async def list_scrape_runs(limit: int = 30) -> dict[str, Any]:
    db = get_db()
    cursor = db.scrape_runs.find({}, {"_id": 0}).sort("started_at", -1).limit(limit)
    items = await cursor.to_list(length=limit)
    return {
        "is_running": is_ingest_running(),
        "items": items,
    }


@router.post("/runs/trigger")
async def trigger_scrape_run(background_tasks: BackgroundTasks, wait: bool = False) -> dict[str, Any]:
    if is_ingest_running():
        return {"status": "already_running", "message": "An ingestion run is already in progress."}
    if wait:
        summaries = await run_all_connectors()
        for s in summaries:
            s.pop("_id", None)
        return {"status": "completed", "runs": summaries}

    background_tasks.add_task(run_all_connectors)
    return {"status": "started", "message": "Ingestion connectors started in the background."}


@router.get("/digest/preview")
async def preview_digest() -> dict[str, Any]:
    return await build_daily_digest()


@router.post("/digest/send")
async def trigger_digest_send() -> dict[str, Any]:
    return await send_daily_digest()
