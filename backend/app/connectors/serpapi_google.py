import logging
import httpx
from app.config import settings
from app.connectors.base import BaseConnector
from app.models import RawJob

logger = logging.getLogger(__name__)


class SerpApiGoogleJobsConnector(BaseConnector):
    name = "serpapi_google_jobs"

    def __init__(self, queries: list[str] | None = None) -> None:
        self.queries = queries or ["Head of Engineering Jakarta Indonesia"]

    @property
    def is_configured(self) -> bool:
        return bool((settings.serpapi_key or "").strip())

    async def fetch_jobs(self) -> list[RawJob]:
        if not self.is_configured:
            return []
        results: list[RawJob] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for query in self.queries[:4]:
                try:
                    resp = await client.get(
                        "https://serpapi.com/search.json",
                        params={
                            "engine": "google_jobs",
                            "q": query,
                            "api_key": settings.serpapi_key,
                        },
                    )
                    if resp.status_code != 200:
                        continue
                    for item in resp.json().get("jobs_results", []):
                        company = (item.get("company_name") or "").strip()
                        title = (item.get("title") or "").strip()
                        if not company or not title:
                            continue
                        apply_options = item.get("apply_options") or []
                        link = apply_options[0].get("link") if apply_options else item.get("share_link", "")
                        results.append(
                            RawJob(
                                company=company,
                                title=title,
                                location_raw=(item.get("location") or "").strip(),
                                description=(item.get("description") or "")[:15000],
                                source=self.name,
                                url=(link or "").strip(),
                            )
                        )
                except Exception as exc:
                    logger.warning("SerpApi Google Jobs error for query '%s': %s", query, exc)
        return results
