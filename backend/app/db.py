from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import yaml
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.config import settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def get_db() -> AsyncIOMotorDatabase:
    global _client, _db
    if _db is None:
        _client = AsyncIOMotorClient(settings.mongo_uri)
        _db = _client[settings.mongo_db]
    return _db


def apply_integrations_to_runtime(integrations: dict[str, Any]) -> None:
    """Apply persisted integration settings onto the in-memory settings singleton."""
    if not integrations:
        return
    if "llm_base_url" in integrations and integrations["llm_base_url"]:
        settings.llm_base_url = str(integrations["llm_base_url"]).strip()
    if "llm_api_key" in integrations:
        settings.llm_api_key = str(integrations["llm_api_key"] or "").strip()
    if "llm_model" in integrations and integrations["llm_model"]:
        settings.llm_model = str(integrations["llm_model"]).strip()
    if "llm_tailor_model" in integrations and integrations["llm_tailor_model"]:
        settings.llm_tailor_model = str(integrations["llm_tailor_model"]).strip()
    if "max_llm_scores_per_run" in integrations and integrations["max_llm_scores_per_run"] is not None:
        settings.max_llm_scores_per_run = int(integrations["max_llm_scores_per_run"])
    if "apify_token" in integrations:
        settings.apify_token = str(integrations["apify_token"] or "").strip()
    if "serpapi_key" in integrations:
        settings.serpapi_key = str(integrations["serpapi_key"] or "").strip()
    if "telegram_bot_token" in integrations:
        settings.telegram_bot_token = str(integrations["telegram_bot_token"] or "").strip()
    if "telegram_chat_id" in integrations:
        settings.telegram_chat_id = str(integrations["telegram_chat_id"] or "").strip()
    if "dashboard_public_url" in integrations and integrations["dashboard_public_url"]:
        settings.dashboard_public_url = str(integrations["dashboard_public_url"]).strip()


def current_integrations_dict() -> dict[str, Any]:
    return {
        "llm_base_url": settings.llm_base_url,
        "llm_api_key": settings.llm_api_key,
        "llm_model": settings.llm_model,
        "llm_tailor_model": settings.llm_tailor_model,
        "max_llm_scores_per_run": settings.max_llm_scores_per_run,
        "apify_token": settings.apify_token,
        "serpapi_key": settings.serpapi_key,
        "telegram_bot_token": settings.telegram_bot_token,
        "telegram_chat_id": settings.telegram_chat_id,
        "dashboard_public_url": settings.dashboard_public_url,
    }


async def init_db() -> None:
    db = get_db()
    await db.jobs.create_index("id", unique=True)
    await db.jobs.create_index("dedup_hash", unique=True)
    await db.jobs.create_index([("status", 1), ("match_score", -1), ("first_seen_at", -1)])
    await db.scrape_runs.create_index([("started_at", -1)])
    await ensure_config_loaded(db)


def _read_disk_file(filename: str, default: str = "") -> str:
    path = settings.resolved_config_dir / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return default


def _write_disk_file(filename: str, content: str) -> None:
    cfg_dir: Path = settings.resolved_config_dir
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / filename).write_text(content, encoding="utf-8")


async def ensure_config_loaded(db: AsyncIOMotorDatabase | None = None) -> dict[str, Any]:
    if db is None:
        db = get_db()
    doc = await db.settings.find_one({"_id": "global"})
    cv_disk = _read_disk_file("cv.md", "# Candidate CV\n")
    pref_disk = _read_disk_file("preferences.yaml", "min_score_default_filter: 7\n")
    comp_disk = _read_disk_file("companies.yaml", "greenhouse: []\nlever: []\nashby: []\n")

    if not doc:
        doc = {
            "_id": "global",
            "cv_markdown": cv_disk,
            "preferences_yaml": pref_disk,
            "companies_yaml": comp_disk,
            "integrations": current_integrations_dict(),
            "updated_at": datetime.now(timezone.utc),
        }
        await db.settings.insert_one(doc)
    else:
        if "integrations" in doc and isinstance(doc["integrations"], dict):
            apply_integrations_to_runtime(doc["integrations"])
        else:
            doc["integrations"] = current_integrations_dict()
            await db.settings.update_one(
                {"_id": "global"},
                {"$set": {"integrations": doc["integrations"]}},
            )
    return doc


async def save_app_config(
    cv_markdown: str,
    preferences_yaml: str,
    companies_yaml: str,
    integrations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Validate YAML before saving
    yaml.safe_load(preferences_yaml)
    yaml.safe_load(companies_yaml)

    _write_disk_file("cv.md", cv_markdown)
    _write_disk_file("preferences.yaml", preferences_yaml)
    _write_disk_file("companies.yaml", companies_yaml)

    if integrations is not None:
        apply_integrations_to_runtime(integrations)

    db = get_db()
    now = datetime.now(timezone.utc)
    update_fields: dict[str, Any] = {
        "cv_markdown": cv_markdown,
        "preferences_yaml": preferences_yaml,
        "companies_yaml": companies_yaml,
        "integrations": current_integrations_dict(),
        "updated_at": now,
    }
    await db.settings.update_one(
        {"_id": "global"},
        {"$set": update_fields},
        upsert=True,
    )
    return await ensure_config_loaded(db)


async def get_parsed_config() -> tuple[str, dict[str, Any], dict[str, Any]]:
    doc = await ensure_config_loaded()
    cv_md = doc.get("cv_markdown", "")
    preferences = yaml.safe_load(doc.get("preferences_yaml", "")) or {}
    companies = yaml.safe_load(doc.get("companies_yaml", "")) or {}
    return cv_md, preferences, companies
