from datetime import datetime, timezone
import logging
from typing import Any
import httpx
from app.config import settings
from app.models import TailoredPitch
from app.services.scorer import extract_json_object

logger = logging.getLogger(__name__)


def heuristic_tailor_pitch(job_doc: dict[str, Any], cv_md: str) -> TailoredPitch:
    company = job_doc.get("company", "your organization")
    title = job_doc.get("title", "Engineering Leader")
    role_track = job_doc.get("role_track") or "Engineering Leadership"

    if "Quality" in role_track or "QA" in title or "Quality" in title:
        cv_summary = (
            f"Head of Engineering & Quality Engineering Leader with 10+ years scaling high-velocity logistics tech orgs. "
            f"Built and led a 41-engineer cross-country (Indonesia & Vietnam) Quality organization, driving 92% automated test coverage "
            f"across 23,000+ tests while saving $23K/year through custom in-house Test Case Management and Device Farm platforms. "
            f"Excited to bring automation-first quality governance and AI-accelerated testing workflows to {company} as {title}."
        )
        bullets = [
            "Scaled and led a 41-person QA & Quality Engineering organization across Indonesia and Vietnam, reaching 92% automation coverage across 23,000+ regression tests.",
            "Architected an in-house Test Case Management platform and custom mobile device farm, reducing external SaaS spend by $23,000/year while accelerating release verification.",
            "Pioneered AI-assisted SDLC & automated test generation workflows that reduced end-to-end engineering cycle time by up to 75%.",
        ]
    else:
        cv_summary = (
            f"Hands-on Head of Engineering with 10+ years of experience scaling multi-product logistics technology platforms across Indonesia and Vietnam. "
            f"Proven track record leading cross-functional Backend, Mobile, Web, and 41-person Quality Engineering teams, "
            f"cutting delivery cycle times by up to 75% via AI-assisted engineering workflows and pragmatic internal platform tooling. "
            f"Ready to drive high-reliability delivery and engineering excellence as {title} at {company}."
        )
        bullets = [
            "Progressed from QA Automation Engineer to Head of Engineering in high-scale logistics tech, leading cross-border Engineering & QA teams across Indonesia and Vietnam.",
            "Designed and rolled out AI-assisted engineering workflows across coding, review, and testing, achieving up to 75% cycle-time reduction.",
            "Established automation-first release governance (92% test automation across 23,000+ tests) and custom internal developer tooling saving $23,000/year.",
        ]

    outreach = (
        f"Hi [Hiring Manager / Recruiter],\n\n"
        f"I recently came across the {title} opening at {company} and noticed a strong overlap with my background leading cross-country "
        f"Engineering and Quality organizations in high-scale logistics tech.\n\n"
        f"Over the past 10+ years—progressing from QA Automation Engineer to Head of Engineering—I've scaled teams up to 41 QA engineers "
        f"across Indonesia and Vietnam, reached 92% automation coverage across 23K+ tests, and cut feature cycle times by 75% using AI-assisted SDLC workflows. "
        f"I'd love to share how these frameworks could support {company}'s roadmap. Would you be open to a brief introductory chat this week?"
    )

    return TailoredPitch(
        cv_summary=cv_summary,
        emphasized_bullets=bullets,
        outreach_message=outreach,
        generated_by="template_fallback",
        generated_at=datetime.now(timezone.utc),
    )


async def generate_tailored_pitch(job_doc: dict[str, Any], cv_md: str) -> TailoredPitch:
    if not settings.llm_enabled:
        return heuristic_tailor_pitch(job_doc, cv_md)

    system_prompt = (
        "You are an executive technical resume writer and career coach. "
        "Given the candidate CV and target job posting, generate a tailored application pitch. "
        "Respond ONLY with valid JSON matching this schema:\n"
        "{\n"
        '  "cv_summary": "<3-4 line tailored executive CV summary aligned to this specific role>",\n'
        '  "emphasized_bullets": ["<bullet 1 with concrete metrics>", "<bullet 2>", "<bullet 3>"],\n'
        '  "outreach_message": "<concise, high-signal LinkedIn/email message to the hiring manager or recruiter>"\n'
        "}"
    )

    user_prompt = (
        f"### Candidate CV:\n{cv_md}\n\n"
        f"### Target Role:\n"
        f"Company: {job_doc.get('company')}\n"
        f"Title: {job_doc.get('title')}\n"
        f"Location: {job_doc.get('location_raw')}\n"
        f"Prior Analysis: {job_doc.get('llm_analysis')}\n"
        f"Job Description:\n{(job_doc.get('description') or '')[:8000]}\n"
    )

    base_url = settings.llm_base_url.rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_tailor_model or settings.llm_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            parsed = extract_json_object(content)
            return TailoredPitch(
                cv_summary=parsed.get("cv_summary", ""),
                emphasized_bullets=parsed.get("emphasized_bullets") or [],
                outreach_message=parsed.get("outreach_message", ""),
                generated_by=settings.llm_tailor_model or settings.llm_model,
                generated_at=datetime.now(timezone.utc),
            )
    except Exception as exc:
        logger.warning("LLM tailoring failed for job %s (%s); using fallback", job_doc.get("id"), exc)
        return heuristic_tailor_pitch(job_doc, cv_md)
