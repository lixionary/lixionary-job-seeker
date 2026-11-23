import logging
import httpx
from app.config import settings
from app.connectors.base import BaseConnector, clean_html_to_text
from app.models import RawJob

logger = logging.getLogger(__name__)


class ApifyLinkedInConnector(BaseConnector):
    name = "apify_linkedin"

    def __init__(self, queries: list[str] | None = None) -> None:
        self.queries = queries or []

    @property
    def is_configured(self) -> bool:
        return bool((settings.apify_token or "").strip())

    async def fetch_jobs(self) -> list[RawJob]:
        if not self.is_configured:
            return []
        results: list[RawJob] = []
        # Fetches from the user's most recent Apify LinkedIn Jobs dataset run if available
        url = "https://api.apify.com/v2/actor-tasks"
        headers = {"Authorization": f"Bearer {settings.apify_token}"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    return []
                items = resp.json().get("data", {}).get("items", [])
                for task in items[:2]:
                    task_id = task.get("id")
                    if not task_id:
                        continue
                    ds_url = f"https://api.apify.com/v2/actor-tasks/{task_id}/runs/last/dataset/items"
                    ds_resp = await client.get(ds_url, headers=headers)
                    if ds_resp.status_code == 200 and isinstance(ds_resp.json(), list):
                        for row in ds_resp.json():
                            company = (row.get("companyName") or row.get("company") or "").strip()
                            title = (row.get("title") or "").strip()
                            if not company or not title:
                                continue
                            results.append(
                                RawJob(
                                    company=company,
                                    title=title,
                                    location_raw=(row.get("location") or "").strip(),
                                    description=clean_html_to_text(row.get("description") or "")[:15000],
                                    source=self.name,
                                    url=(row.get("jobUrl") or row.get("url") or "").strip(),
                                )
                            )
            except Exception as exc:
                logger.warning("Apify LinkedIn connector error: %s", exc)
        return results
