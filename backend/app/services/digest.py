from datetime import datetime, timedelta, timezone
import logging
from typing import Any
import httpx
from app.config import settings
from app.db import get_db, get_parsed_config

logger = logging.getLogger(__name__)


async def build_daily_digest(hours: int = 24, limit: int = 5) -> dict[str, Any]:
    db = get_db()
    _, preferences, _ = await get_parsed_config()
    min_score = int(preferences.get("min_score_default_filter") or 7)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    cursor = (
        db.jobs.find(
            {
                "status": {"$ne": "filtered_out"},
                "match_score": {"$gte": min_score},
                "first_seen_at": {"$gte": since},
            },
            {"_id": 0},
        )
        .sort([("match_score", -1), ("first_seen_at", -1)])
        .limit(limit)
    )
    jobs = await cursor.to_list(length=limit)

    # If no new high-match jobs in the past 24h, fall back to top 'new' jobs overall for preview convenience
    used_fallback_window = False
    if not jobs:
        used_fallback_window = True
        cursor = (
            db.jobs.find(
                {
                    "status": "new",
                    "match_score": {"$gte": min_score},
                },
                {"_id": 0},
            )
            .sort([("match_score", -1), ("first_seen_at", -1)])
            .limit(limit)
        )
        jobs = await cursor.to_list(length=limit)

    lines = [
        "🎯 *Personal Job Radar — Daily High-Signal Digest*",
        f"_Top matches (Score ≥ {min_score})_",
        "",
    ]

    if not jobs:
        lines.append("No high-scoring roles (≥ 7) currently waiting in `New`.")
    else:
        for idx, job in enumerate(jobs, start=1):
            score = job.get("match_score", "?")
            company = job.get("company", "")
            title = job.get("title", "")
            loc = job.get("location_policy") or job.get("location_raw") or "Unspecified"
            track = job.get("role_track") or ""
            analysis = job.get("llm_analysis") or {}
            summary = analysis.get("summary") or ""
            urls = job.get("source_urls") or []
            apply_url = urls[0].get("url") if urls else settings.dashboard_public_url

            lines.append(f"*{idx}. [{score}/10] {company} — {title}*")
            lines.append(f"📍 {loc} | 🏷 {track}")
            if summary:
                lines.append(f"💡 {summary}")
            if apply_url:
                lines.append(f"🔗 [Apply / View Posting]({apply_url})")
            lines.append("")

    lines.append(f"🖥 [Open Job Radar Kanban Dashboard]({settings.dashboard_public_url})")
    message_text = "\n".join(lines)

    return {
        "count": len(jobs),
        "min_score": min_score,
        "used_fallback_window": used_fallback_window,
        "telegram_configured": bool(settings.telegram_bot_token and settings.telegram_chat_id),
        "message": message_text,
        "jobs": jobs,
    }


async def send_daily_digest() -> dict[str, Any]:
    digest = await build_daily_digest()
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        return {
            **digest,
            "sent": False,
            "note": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured in .env; returning digest preview only.",
        }

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": digest["message"],
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return {**digest, "sent": True}
    except Exception as exc:
        logger.warning("Failed to send Telegram digest: %s", exc)
        return {**digest, "sent": False, "error": str(exc)}
