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
            "updated_at": datetime.now(timezone.utc),
        }
        await db.settings.insert_one(doc)
    return doc


async def save_app_config(cv_markdown: str, preferences_yaml: str, companies_yaml: str) -> dict[str, Any]:
    # Validate YAML before saving
    yaml.safe_load(preferences_yaml)
    yaml.safe_load(companies_yaml)

    _write_disk_file("cv.md", cv_markdown)
    _write_disk_file("preferences.yaml", preferences_yaml)
    _write_disk_file("companies.yaml", companies_yaml)

    db = get_db()
    now = datetime.now(timezone.utc)
    await db.settings.update_one(
        {"_id": "global"},
        {
            "$set": {
                "cv_markdown": cv_markdown,
                "preferences_yaml": preferences_yaml,
                "companies_yaml": companies_yaml,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    return await ensure_config_loaded(db)


async def get_parsed_config() -> tuple[str, dict[str, Any], dict[str, Any]]:
    doc = await ensure_config_loaded()
    cv_md = doc.get("cv_markdown", "")
    preferences = yaml.safe_load(doc.get("preferences_yaml", "")) or {}
    companies = yaml.safe_load(doc.get("companies_yaml", "")) or {}
    return cv_md, preferences, companies
