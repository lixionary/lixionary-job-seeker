import json
import logging
import re
from typing import Any
import httpx
from app.config import settings
from app.models import LLMAnalysis, RawJob

logger = logging.getLogger(__name__)


def extract_json_object(raw_text: str) -> dict[str, Any]:
    """Strip reasoning blocks (<think>...</think>), code fences, and extract JSON object."""
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw_text or "", flags=re.IGNORECASE).strip()
    fence_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", cleaned)
    if fence_match:
        cleaned = fence_match.group(1)
    else:
        brace_match = re.search(r"\{[\s\S]*\}", cleaned)
        if brace_match:
            cleaned = brace_match.group(0)
    return json.loads(cleaned)


def heuristic_score_job(job: RawJob, cv_md: str, preferences: dict[str, Any]) -> LLMAnalysis:
    title_l = (job.title or "").lower()
    desc_l = (job.description or "").lower()
    loc_raw = (job.location_raw or "").strip()
    loc_l = loc_raw.lower()

    is_qa = any(k in title_l for k in ["qa", "quality", "test", "sdet", "automation"])
    is_exec = any(k in title_l for k in ["head of", "vp", "vice president", "director", "chief", "cto"])
    is_mgr = any(k in title_l for k in ["manager", "em", "lead"])
    is_principal = any(k in title_l for k in ["principal", "staff", "architect", "devex", "platform"])

    if is_qa and (is_exec or is_mgr):
        role_track = "Quality Engineering Leadership"
    elif is_exec or is_mgr:
        role_track = "Engineering Leadership"
    elif is_qa:
        role_track = "Quality Engineering Leadership"
    else:
        role_track = "Hands-on Strategic IC"

    score = 5
    reasons: list[str] = []
    red_flags: list[str] = []

    if is_exec:
        score += 2
        reasons.append("Executive/Director leadership scope aligns with Head of Engineering & QA Director track record.")
    elif is_mgr or is_principal:
        score += 1
        reasons.append("Senior management / strategic IC scope aligns with 10+ years leadership progression.")

    if is_qa or "test automation" in desc_l or "quality engineering" in desc_l:
        score += 1
        reasons.append("Strong alignment with 92% test automation coverage (23K+ tests) and scaling 41-person QA org.")

    if any(k in desc_l for k in ["ai", "llm", "copilot", "developer productivity", "devex", "cycle time", "platform"]):
        score += 1
        reasons.append("Values AI-assisted engineering workflows / developer productivity (matches 75% cycle-time reduction).")

    if any(k in desc_l for k in ["logistics", "supply chain", "fleet", "delivery", "operations", "e-commerce", "fintech"]):
        score += 1
        reasons.append("High domain overlap with high-scale logistics & multi-product operations technology.")

    # Geography analysis
    if any(k in loc_l for k in ["jakarta", "indonesia"]):
        location_policy = f"Indonesia ({loc_raw or 'Jakarta'})"
        relocation_note = "Local Indonesia role — immediate fit without visa barrier."
        score += 1
        reasons.append("Located in Jakarta/Indonesia target geography.")
    elif "singapore" in loc_l:
        location_policy = f"Singapore ({loc_raw})"
        relocation_note = "Singapore role — regional SEA leadership experience (ID/VN) is highly relevant."
        reasons.append("Singapore / SEA regional technology hub.")
    elif any(k in loc_l for k in ["apac", "asia", "vietnam", "bangkok", "thailand", "malaysia", "remote"]):
        location_policy = loc_raw or "Remote / APAC"
        relocation_note = "APAC / Remote compatible timezone (UTC+7 / UTC+8)."
        reasons.append("APAC or remote-compatible location policy.")
    else:
        location_policy = loc_raw or "Unspecified"
        relocation_note = "Verify APAC remote eligibility or visa sponsorship requirements."

    if any(k in desc_l for k in ["rust", "c++", "embedded", "firmware", "ios only", "solidity"]):
        red_flags.append("Mentions specialized systems/language requirements outside primary stack.")
    if not is_exec and not is_mgr and not is_principal:
        score = min(score, 6)
        red_flags.append("Role appears to be mid/senior IC rather than Engineering/QA Leadership or Staff/Principal level.")

    score = max(1, min(10, score))
    if not reasons:
        reasons.append("General software engineering or quality alignment with baseline profile.")

    if role_track == "Quality Engineering Leadership":
        tailoring_angle = (
            "Emphasize scaling the 41-engineer QA organization across Indonesia & Vietnam, "
            "achieving 92% automation across 23K tests, and saving $23K/yr via custom TCM & device farm."
        )
    elif role_track == "Engineering Leadership":
        tailoring_angle = (
            "Highlight progression to Head of Engineering in logistics tech, cross-country (ID/VN) org ownership, "
            "and 75% cycle-time reduction via AI-assisted SDLC workflows."
        )
    else:
        tailoring_angle = (
            "Focus on internal platform & DevEx tooling (custom device farm, in-house test management saving $23K/yr) "
            "and AI-assisted engineering workflow automation."
        )

    summary = (
        f"{job.title} at {job.company} ({location_policy}) maps to the {role_track} track "
        f"with a match score of {score}/10 based on seniority, domain, and technical leadership criteria."
    )

    return LLMAnalysis(
        match_score=score,
        role_track=role_track,
        location_policy=location_policy,
        relocation_or_visa_note=relocation_note,
        summary=summary,
        match_reasons=reasons[:4],
        red_flags=red_flags[:3],
        tailoring_angle=tailoring_angle,
        scored_by="heuristic_fallback",
    )


async def score_job_with_llm(job: RawJob, cv_md: str, preferences: dict[str, Any]) -> tuple[LLMAnalysis, int]:
    """
    Score a job against cv.md and preferences.yaml.
    Returns (LLMAnalysis, total_tokens_used).
    Falls back to deterministic heuristic scorer if LLM_API_KEY is not configured or API call fails.
    """
    if not settings.llm_enabled:
        return heuristic_score_job(job, cv_md, preferences), 0

    system_prompt = (
        "You are an executive technical career advisor evaluating job postings against a candidate CV. "
        "Respond ONLY with a valid JSON object matching this exact schema:\n"
        "{\n"
        '  "match_score": <integer 1-10>,\n'
        '  "role_track": "Engineering Leadership" | "Quality Engineering Leadership" | "Hands-on Strategic IC",\n'
        '  "location_policy": "<string e.g. Hybrid - Jakarta / Remote APAC / Singapore>",\n'
        '  "relocation_or_visa_note": "<string>",\n'
        '  "summary": "<2-sentence explanation of why this role fits or does not fit>",\n'
        '  "match_reasons": ["<string>", ...],\n'
        '  "red_flags": ["<string>", ...],\n'
        '  "tailoring_angle": "<1-2 sentence advice on which CV metrics to highlight>"\n'
        "}"
    )

    user_prompt = (
        f"### Candidate CV:\n{cv_md}\n\n"
        f"### Candidate Preferences:\n{json.dumps(preferences, indent=2)}\n\n"
        f"### Job Posting:\n"
        f"Company: {job.company}\n"
        f"Title: {job.title}\n"
        f"Location: {job.location_raw}\n"
        f"Description:\n{(job.description or '')[:8000]}\n"
    )

    base_url = settings.llm_base_url.rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            tokens = int(usage.get("total_tokens") or (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)))
            parsed = extract_json_object(content)
            parsed["scored_by"] = settings.llm_model
            parsed["match_score"] = max(1, min(10, int(parsed.get("match_score", 5))))
            return LLMAnalysis(**parsed), tokens
    except Exception as exc:
        logger.warning("LLM scoring failed for %s - %s (%s); using heuristic fallback", job.company, job.title, exc)
        return heuristic_score_job(job, cv_md, preferences), 0
