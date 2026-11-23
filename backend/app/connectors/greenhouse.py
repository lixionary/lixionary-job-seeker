import logging
from typing import Any
import httpx
from app.connectors.base import BaseConnector, clean_html_to_text
from app.models import RawJob

logger = logging.getLogger(__name__)


class GreenhouseConnector(BaseConnector):
    name = "greenhouse"

    def __init__(self, companies: list[dict[str, Any]]) -> None:
        self.companies = companies or []

    async def fetch_jobs(self) -> list[RawJob]:
        results: list[RawJob] = []
        if not self.companies:
            return results

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            for item in self.companies:
                slug = (item.get("slug") or "").strip()
                company_name = (item.get("name") or slug).strip()
                if not slug:
                    continue
                url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        logger.warning("Greenhouse board %s returned HTTP %s", slug, resp.status_code)
                        continue
                    payload = resp.json()
                    for job in payload.get("jobs", []):
                        title = (job.get("title") or "").strip()
                        if not title:
                            continue
                        loc = ""
                        if isinstance(job.get("location"), dict):
                            loc = (job["location"].get("name") or "").strip()
                        content_html = job.get("content") or ""
                        description = clean_html_to_text(content_html)
                        job_url = (job.get("absolute_url") or "").strip()
                        results.append(
                            RawJob(
                                company=company_name,
                                title=title,
                                location_raw=loc,
                                description=description[:15000],
                                source=self.name,
                                url=job_url,
                            )
                        )
                except Exception as exc:
                    logger.warning("Greenhouse connector failed for %s: %s", slug, exc)
        return results
