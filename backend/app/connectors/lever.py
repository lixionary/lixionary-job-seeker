import logging
from typing import Any
import httpx
from app.connectors.base import BaseConnector, clean_html_to_text
from app.models import RawJob

logger = logging.getLogger(__name__)


class LeverConnector(BaseConnector):
    name = "lever"

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
                url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        logger.warning("Lever board %s returned HTTP %s", slug, resp.status_code)
                        continue
                    postings = resp.json()
                    if not isinstance(postings, list):
                        continue
                    for post in postings:
                        title = (post.get("text") or "").strip()
                        if not title:
                            continue
                        categories = post.get("categories") or {}
                        loc_parts = [
                            categories.get("location") or "",
                            post.get("workplaceType") or "",
                        ]
                        loc = " · ".join(p for p in loc_parts if p).strip()
                        desc_plain = post.get("descriptionPlain") or clean_html_to_text(post.get("description") or "")
                        lists_text = []
                        for lst in post.get("lists") or []:
                            header = lst.get("text") or ""
                            content = clean_html_to_text(lst.get("content") or "")
                            if header or content:
                                lists_text.append(f"{header}\n{content}".strip())
                        full_desc = "\n\n".join(p for p in [desc_plain, *lists_text] if p)
                        job_url = (post.get("hostedUrl") or post.get("applyUrl") or "").strip()
                        results.append(
                            RawJob(
                                company=company_name,
                                title=title,
                                location_raw=loc,
                                description=full_desc[:15000],
                                source=self.name,
                                url=job_url,
                            )
                        )
                except Exception as exc:
                    logger.warning("Lever connector failed for %s: %s", slug, exc)
        return results
