from typing import Any
import yaml
from fastapi import APIRouter, HTTPException
from app.config import settings
from app.db import ensure_config_loaded, save_app_config
from app.models import AppConfigPayload

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
async def get_config() -> dict[str, Any]:
    doc = await ensure_config_loaded()
    return {
        "cv_markdown": doc.get("cv_markdown", ""),
        "preferences_yaml": doc.get("preferences_yaml", ""),
        "companies_yaml": doc.get("companies_yaml", ""),
        "updated_at": doc.get("updated_at"),
        "llm_enabled": settings.llm_enabled,
        "llm_model": settings.llm_model,
        "llm_base_url": settings.llm_base_url,
    }


@router.put("")
async def update_config(payload: AppConfigPayload) -> dict[str, Any]:
    try:
        yaml.safe_load(payload.preferences_yaml)
        yaml.safe_load(payload.companies_yaml)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid YAML syntax: {exc}") from exc

    doc = await save_app_config(
        cv_markdown=payload.cv_markdown,
        preferences_yaml=payload.preferences_yaml,
        companies_yaml=payload.companies_yaml,
    )
    return {
        "status": "saved",
        "cv_markdown": doc.get("cv_markdown", ""),
        "preferences_yaml": doc.get("preferences_yaml", ""),
        "companies_yaml": doc.get("companies_yaml", ""),
        "updated_at": doc.get("updated_at"),
    }
