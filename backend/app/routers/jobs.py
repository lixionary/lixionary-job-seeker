from datetime import datetime, timezone
from typing import Any, Optional
import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException, Query
from app.connectors.base import clean_html_to_text
from app.db import get_db, get_parsed_config
from app.models import JobUpdateRequest, ManualJobRequest, RawJob
from app.services.ingest import upsert_and_score_raw_job
from app.services.scorer import score_job_with_llm
from app.services.tailor import generate_tailored_pitch

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(
    status: Optional[str] = Query(default=None),
    min_score: Optional[int] = Query(default=None),
    include_filtered: bool = Query(default=False),
    role_track: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=300, le=1000),
) -> dict[str, Any]:
    db = get_db()
    query: dict[str, Any] = {}

    if status:
        query["status"] = status
    elif not include_filtered:
        query["status"] = {"$ne": "filtered_out"}

    if min_score is not None:
        query["$or"] = [
            {"match_score": {"$gte": min_score}},
            {"status": {"$in": ["shortlisted", "applied", "interviewing"]}},
        ]

    if role_track:
        query["role_track"] = role_track

    if search:
        regex = {"$regex": search.strip(), "$options": "i"}
        query["$and"] = [
            {
                "$or": [
                    {"company": regex},
                    {"title": regex},
                    {"location_raw": regex},
                    {"location_policy": regex},
                    {"notes": regex},
                ]
            }
        ]

    cursor = (
        db.jobs.find(query, {"_id": 0})
        .sort([("match_score", -1), ("updated_at", -1)])
        .limit(limit)
    )
    items = await cursor.to_list(length=limit)

    # Aggregate status counts for dashboard header metrics
    pipeline = [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]
    counts_raw = await db.jobs.aggregate(pipeline).to_list(length=20)
    counts = {row["_id"]: row["count"] for row in counts_raw if row.get("_id")}

    return {
        "items": items,
        "total": len(items),
        "counts": counts,
    }


@router.get("/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    db = get_db()
    doc = await db.jobs.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    return doc


@router.patch("/{job_id}")
async def update_job(job_id: str, payload: JobUpdateRequest) -> dict[str, Any]:
    db = get_db()
    existing = await db.jobs.find_one({"id": job_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Job not found")

    updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if payload.status is not None:
        updates["status"] = payload.status
    if payload.notes is not None:
        updates["notes"] = payload.notes

    await db.jobs.update_one({"id": job_id}, {"$set": updates})
    doc = await db.jobs.find_one({"id": job_id}, {"_id": 0})
    return doc or {}


@router.post("/manual")
async def create_manual_job(payload: ManualJobRequest) -> dict[str, Any]:
    company = (payload.company or "").strip()
    title = (payload.title or "").strip()
    location_raw = (payload.location_raw or "").strip()
    url = (payload.url or "").strip()
    description = (payload.description or "").strip()

    # If user pasted a URL and left description or title blank, attempt to fetch page text
    if url and (not description or not title or not company):
        try:
            async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (JobRadar/1.0)"})
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    page_title = (soup.title.string if soup.title and soup.title.string else "").strip()
                    if not title and page_title:
                        title = page_title.split("|")[0].split(" - ")[0].strip()
                    if not company and page_title and (" at " in page_title or " - " in page_title):
                        parts = page_title.replace(" at ", " - ").split(" - ")
                        if len(parts) > 1:
                            company = parts[-1].strip()
                    if not description:
                        description = clean_html_to_text(resp.text)[:15000]
        except Exception:
            pass

    if not company:
        company = "Manual Entry"
    if not title:
        raise HTTPException(status_code=400, detail="Please provide a job title (or a reachable job URL).")

    cv_md, preferences, _ = await get_parsed_config()
    raw_job = RawJob(
        company=company,
        title=title,
        location_raw=location_raw,
        description=description,
        source="manual",
        url=url,
    )
    outcome, _, doc = await upsert_and_score_raw_job(
        raw_job,
        cv_md=cv_md,
        preferences=preferences,
        remaining_llm_budget=1,
        bypass_prefilter=True,
    )
    doc.pop("_id", None)
    return {"outcome": outcome, "job": doc}


@router.post("/{job_id}/tailor")
async def tailor_job_pitch(job_id: str) -> dict[str, Any]:
    db = get_db()
    doc = await db.jobs.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")

    cv_md, _, _ = await get_parsed_config()
    pitch = await generate_tailored_pitch(doc, cv_md)
    pitch_dict = pitch.model_dump()
    now = datetime.now(timezone.utc)

    await db.jobs.update_one(
        {"id": job_id},
        {"$set": {"tailored_pitch": pitch_dict, "updated_at": now}},
    )
    updated = await db.jobs.find_one({"id": job_id}, {"_id": 0})
    return updated or {}


@router.post("/{job_id}/rescore")
async def rescore_job(job_id: str) -> dict[str, Any]:
    db = get_db()
    doc = await db.jobs.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")

    cv_md, preferences, _ = await get_parsed_config()
    urls = doc.get("source_urls") or []
    first_url = urls[0].get("url", "") if urls else ""
    first_src = urls[0].get("source", "manual") if urls else "manual"

    raw_job = RawJob(
        company=doc.get("company", ""),
        title=doc.get("title", ""),
        location_raw=doc.get("location_raw", ""),
        description=doc.get("description", ""),
        source=first_src,
        url=first_url,
    )
    analysis, _ = await score_job_with_llm(raw_job, cv_md, preferences)
    now = datetime.now(timezone.utc)
    new_status = "new" if doc.get("status") == "filtered_out" else doc.get("status", "new")

    updates = {
        "status": new_status,
        "match_score": analysis.match_score,
        "role_track": analysis.role_track,
        "location_policy": analysis.location_policy,
        "llm_analysis": analysis.model_dump(),
        "updated_at": now,
    }
    await db.jobs.update_one({"id": job_id}, {"$set": updates})
    updated = await db.jobs.find_one({"id": job_id}, {"_id": 0})
    return updated or {}
