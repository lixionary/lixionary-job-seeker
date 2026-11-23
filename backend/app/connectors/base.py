from abc import ABC, abstractmethod
import html
import re
from bs4 import BeautifulSoup
from app.models import RawJob


def clean_html_to_text(raw_html: str) -> str:
    if not raw_html:
        return ""
    unescaped = html.unescape(raw_html)
    soup = BeautifulSoup(unescaped, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


class BaseConnector(ABC):
    name: str = "base"

    @abstractmethod
    async def fetch_jobs(self) -> list[RawJob]:
        """Fetch and normalize jobs from this source."""
        raise NotImplementedError
