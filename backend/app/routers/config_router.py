import time
from typing import Any
import httpx
import yaml
from fastapi import APIRouter, HTTPException
from app.config import settings
from app.db import current_integrations_dict, ensure_config_loaded, save_app_config
from app.models import AppConfigPayload, IntegrationSettingsPayload

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
async def get_config() -> dict[str, Any]:
    doc = await ensure_config_loaded()
    return {
        "cv_markdown": doc.get("cv_markdown", ""),
        "preferences_yaml": doc.get("preferences_yaml", ""),
        "companies_yaml": doc.get("companies_yaml", ""),
        "integrations": current_integrations_dict(),
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
        integrations=payload.integrations.model_dump() if payload.integrations else None,
    )
    return {
        "status": "saved",
        "cv_markdown": doc.get("cv_markdown", ""),
        "preferences_yaml": doc.get("preferences_yaml", ""),
        "companies_yaml": doc.get("companies_yaml", ""),
        "integrations": current_integrations_dict(),
        "llm_enabled": settings.llm_enabled,
        "llm_model": settings.llm_model,
        "updated_at": doc.get("updated_at"),
    }


@router.post("/test-llm")
async def test_llm_connection(payload: IntegrationSettingsPayload) -> dict[str, Any]:
    api_key = (payload.llm_api_key or settings.llm_api_key or "").strip()
    base_url = (payload.llm_base_url or settings.llm_base_url or "https://api.minimax.io/v1").rstrip("/")
    model = (payload.llm_model or settings.llm_model or "MiniMax-M1").strip()

    if not api_key:
        return {
            "ok": False,
            "error": "LLM API Key is empty. Enter your MiniMax (or OpenAI-compatible) API key first.",
        }

    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a connectivity check assistant."},
            {"role": "user", "content": "Reply with the exact word: READY"},
        ],
        "max_tokens": 32,
        "temperature": 0.0,
    }

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, headers=headers, json=body)
            latency_ms = int((time.monotonic() - t0) * 1000)
            if resp.status_code != 200:
                return {
                    "ok": False,
                    "status_code": resp.status_code,
                    "latency_ms": latency_ms,
                    "error": f"HTTP {resp.status_code}: {resp.text[:300]}",
                }
            data = resp.json()
            reply = data["choices"][0]["message"]["content"].strip()
            return {
                "ok": True,
                "model": model,
                "base_url": base_url,
                "latency_ms": latency_ms,
                "reply": reply[:120],
            }
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "error": str(exc),
        }
