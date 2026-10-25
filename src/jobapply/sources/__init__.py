"""Job sources. Each fetcher yields (Job, description_text) pairs; filtering and scoring happen in fetch.py."""

import html
import re

import httpx


def client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(30, read=300), follow_redirects=True,
                        headers={"User-Agent": "jobapply (personal job tracker)"})


def html_to_text(s: str) -> str:
    s = html.unescape(html.unescape(s or ""))  # Greenhouse double-escapes
    s = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"[ \t]+", " ", s).strip()


def split_locations(s: str | None) -> list[str]:
    return [p.strip() for p in re.split(r"\s*[|;]\s*", s or "") if p.strip()]
