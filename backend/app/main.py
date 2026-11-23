from contextlib import asynccontextmanager
import logging
from typing import Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.db import get_db, init_db
from app.routers.config_router import router as config_router
from app.routers.jobs import router as jobs_router
from app.routers.runs import router as runs_router
from app.services.digest import send_daily_digest
from app.services.ingest import is_ingest_running, run_all_connectors

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=settings.tz)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Schedule twice-daily scrape (07:30 and 19:30 WIB) and 08:30 WIB daily digest
    scheduler.add_job(
        run_all_connectors,
        CronTrigger(hour="7,19", minute=30, timezone=settings.tz),
        id="scheduled_ingest",
        replace_existing=True,
    )
    scheduler.add_job(
        send_daily_digest,
        CronTrigger(hour=8, minute=30, timezone=settings.tz),
        id="scheduled_digest",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Personal Job Radar backend initialized (LLM enabled: %s, model: %s)", settings.llm_enabled, settings.llm_model)
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Personal Job Radar & Application Triage API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router)
app.include_router(runs_router)
app.include_router(config_router)


@app.get("/api/health")
async def health_check() -> dict[str, Any]:
    db = get_db()
    await db.command("ping")
    total_jobs = await db.jobs.count_documents({})
    return {
        "status": "ok",
        "database": "connected",
        "total_jobs": total_jobs,
        "ingest_running": is_ingest_running(),
        "llm_enabled": settings.llm_enabled,
        "llm_model": settings.llm_model if settings.llm_enabled else "heuristic_fallback",
        "llm_base_url": settings.llm_base_url,
        "telegram_enabled": bool(settings.telegram_bot_token and settings.telegram_chat_id),
    }
