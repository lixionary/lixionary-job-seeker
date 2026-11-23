from datetime import datetime, timezone
import logging
from typing import Any
import uuid
from app.config import settings
from app.connectors.apify_linkedin import ApifyLinkedInConnector
from app.connectors.ashby import AshbyConnector
from app.connectors.base import BaseConnector
from app.connectors.greenhouse import GreenhouseConnector
from app.connectors.lever import LeverConnector
from app.connectors.serpapi_google import SerpApiGoogleJobsConnector
from app.db import get_db, get_parsed_config
from app.models import JobDocument, RawJob, ScrapeRunDocument, SourceUrl
from app.services.prefilter import (
    compute_dedup_hash,
    priority_rank_for_scoring,
    should_prefilter_out,
)
from app.services.scorer import score_job_with_llm

logger = logging.getLogger(__name__)

_ingest_lock = False


def is_ingest_running() -> bool:
    return _ingest_lock


async def upsert_and_score_raw_job(
    raw_job: RawJob,
    cv_md: str,
    preferences: dict[str, Any],
    remaining_llm_budget: int,
    bypass_prefilter: bool = False,
) -> tuple[str, int, dict[str, Any]]:
    """
    Process a single RawJob:
    - If dedup_hash exists: append source_url if new, update last_seen_at, return ("duplicate", 0, existing_doc).
    - If new: apply pre-filter (unless bypass_prefilter=True).
    - If passes pre-filter: score via LLM/fallback and insert.
    Returns (outcome, tokens_used, job_dict) where outcome in {"duplicate", "filtered", "scored"}.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    dedup_hash = compute_dedup_hash(raw_job.company, raw_job.title)

    existing = await db.jobs.find_one({"dedup_hash": dedup_hash})
    if existing:
        source_urls = existing.get("source_urls") or []
        already_has_url = any(s.get("url") == raw_job.url for s in source_urls if raw_job.url)
        update_fields: dict[str, Any] = {"last_seen_at": now}
        if raw_job.url and not already_has_url:
            source_urls.append({"source": raw_job.source, "url": raw_job.url})
            update_fields["source_urls"] = source_urls
        await db.jobs.update_one({"_id": existing["_id"]}, {"$set": update_fields})
        existing.update(update_fields)
        existing.pop("_id", None)
        return "duplicate", 0, existing

    job_id = str(uuid.uuid4())
    source_list = [SourceUrl(source=raw_job.source, url=raw_job.url)] if raw_job.url else [SourceUrl(source=raw_job.source, url="")]

    if not bypass_prefilter:
        filtered, reason = should_prefilter_out(raw_job, preferences)
        if filtered:
            doc = JobDocument(
                id=job_id,
                dedup_hash=dedup_hash,
                company=raw_job.company,
                title=raw_job.title,
                location_raw=raw_job.location_raw,
                description=raw_job.description,
                source_urls=source_list,
                status="filtered_out",
                filter_reason=reason,
                first_seen_at=now,
                last_seen_at=now,
                updated_at=now,
            ).model_dump()
            await db.jobs.insert_one(dict(doc))
            return "filtered", 0, doc

    # Score job (if LLM budget exhausted while LLM is enabled, still fall back to heuristic scorer so no job is left blank)
    if remaining_llm_budget > 0:
        analysis, tokens = await score_job_with_llm(raw_job, cv_md, preferences)
    else:
        from app.services.scorer import heuristic_score_job
        analysis = heuristic_score_job(raw_job, cv_md, preferences)
        tokens = 0

    doc = JobDocument(
        id=job_id,
        dedup_hash=dedup_hash,
        company=raw_job.company,
        title=raw_job.title,
        location_raw=raw_job.location_raw,
        description=raw_job.description,
        source_urls=source_list,
        status="new",
        match_score=analysis.match_score,
        role_track=analysis.role_track,
        location_policy=analysis.location_policy,
        llm_analysis=analysis,
        first_seen_at=now,
        last_seen_at=now,
        updated_at=now,
    ).model_dump()
    await db.jobs.insert_one(dict(doc))
    return "scored", tokens, doc


async def run_all_connectors() -> list[dict[str, Any]]:
    global _ingest_lock
    if _ingest_lock:
        logger.info("Ingest run already in progress; skipping concurrent trigger.")
        return []

    _ingest_lock = True
    run_summaries: list[dict[str, Any]] = []
    try:
        db = get_db()
        cv_md, preferences, companies_cfg = await get_parsed_config()
        max_scores = int(preferences.get("max_llm_scores_per_run") or settings.max_llm_scores_per_run or 50)
        remaining_budget = max_scores

        connectors: list[tuple[BaseConnector, bool]] = [
            (GreenhouseConnector(companies_cfg.get("greenhouse") or []), True),
            (LeverConnector(companies_cfg.get("lever") or []), True),
            (AshbyConnector(companies_cfg.get("ashby") or []), True),
        ]

        apify = ApifyLinkedInConnector(companies_cfg.get("search_queries") or [])
        connectors.append((apify, apify.is_configured))

        serp = SerpApiGoogleJobsConnector(companies_cfg.get("search_queries") or [])
        connectors.append((serp, serp.is_configured))

        for connector, enabled in connectors:
            run_id = str(uuid.uuid4())
            started = datetime.now(timezone.utc)
            if not enabled:
                skip_doc = ScrapeRunDocument(
                    id=run_id,
                    connector_name=connector.name,
                    started_at=started,
                    finished_at=started,
                    status="skipped",
                    error_message="API key not configured in .env (gracefully skipped)",
                ).model_dump()
                await db.scrape_runs.insert_one(dict(skip_doc))
                run_summaries.append(skip_doc)
                continue

            run_doc = ScrapeRunDocument(
                id=run_id,
                connector_name=connector.name,
                started_at=started,
                status="running",
            ).model_dump()
            await db.scrape_runs.insert_one(dict(run_doc))

            try:
                raw_jobs = await connector.fetch_jobs()
                # Sort by priority rank so highest-fit leadership/QA/APAC roles are scored first
                raw_jobs.sort(key=priority_rank_for_scoring, reverse=True)

                jobs_new = 0
                jobs_scored = 0
                jobs_filtered = 0
                tokens_used = 0

                for rjob in raw_jobs:
                    outcome, tok, _ = await upsert_and_score_raw_job(
                        rjob,
                        cv_md=cv_md,
                        preferences=preferences,
                        remaining_llm_budget=remaining_budget,
                    )
                    tokens_used += tok
                    if outcome == "scored":
                        jobs_new += 1
                        jobs_scored += 1
                        if remaining_budget > 0:
                            remaining_budget -= 1
                    elif outcome == "filtered":
                        jobs_new += 1
                        jobs_filtered += 1

                finished = datetime.now(timezone.utc)
                update = {
                    "finished_at": finished,
                    "status": "success",
                    "jobs_fetched": len(raw_jobs),
                    "jobs_new": jobs_new,
                    "jobs_scored": jobs_scored,
                    "jobs_filtered": jobs_filtered,
                    "tokens_used": tokens_used,
                }
                await db.scrape_runs.update_one({"id": run_id}, {"$set": update})
                run_doc.update(update)
                run_summaries.append(run_doc)
            except Exception as exc:
                logger.exception("Connector %s failed", connector.name)
                finished = datetime.now(timezone.utc)
                update = {
                    "finished_at": finished,
                    "status": "failed",
                    "error_message": str(exc),
                }
                await db.scrape_runs.update_one({"id": run_id}, {"$set": update})
                run_doc.update(update)
                run_summaries.append(run_doc)
    finally:
        _ingest_lock = False

    return run_summaries
