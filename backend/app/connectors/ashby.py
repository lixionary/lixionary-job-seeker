import logging
from typing import Any
import httpx
from app.connectors.base import BaseConnector, clean_html_to_text
from app.models import RawJob

logger = logging.getLogger(__name__)


class AshbyConnector(BaseConnector):
    name = "ashby"

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
                url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        logger.warning("Ashby board %s returned HTTP %s", slug, resp.status_code)
                        continue
                    payload = resp.json()
                    for job in payload.get("jobs", []):
                        title = (job.get("title") or "").strip()
                        if not title:
                            continue
                        loc = (job.get("location") or "").strip()
                        if job.get("isRemote"):
                            loc = f"{loc} (Remote)".strip()
                        desc = (job.get("descriptionPlain") or "").strip()
                        if not desc:
                            desc = clean_html_to_text(job.get("descriptionHtml") or "")
                        job_url = (job.get("jobUrl") or job.get("applyUrl") or "").strip()
                        results.append(
                            RawJob(
                                company=company_name,
                                title=title,
                                location_raw=loc,
                                description=desc[:15000],
                                source=self.name,
                                url=job_url,
                            )
                        )
                except Exception as exc:
                    logger.warning("Ashby connector failed for %s: %s", slug, exc)
        return results
