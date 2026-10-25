"""SimplifyJobs trackers (New-Grad-Positions, Summer20XX-Internships) via their listings.json."""

from datetime import datetime, timezone

import httpx

from ..models import Job

RAW_URL = "https://raw.githubusercontent.com/{repo}/dev/.github/scripts/listings.json"


def fetch(repo: str, http: httpx.Client) -> list[dict]:
    r = http.get(RAW_URL.format(repo=repo))
    r.raise_for_status()
    return r.json()


def parse(listings: list[dict], repo: str, categories: list[str] = ()) -> list[tuple[Job, str]]:
    level = "intern" if "intern" in repo.lower() else "new grad"
    cats = [c.lower() for c in categories]
    out = []
    for x in listings:
        if not x.get("active") or not x.get("is_visible", True):
            continue
        cat = (x.get("category") or "").lower()
        if cats and not any(c in cat for c in cats):
            continue
        locs = x.get("locations") or []
        sponsorship = x.get("sponsorship")
        job = Job(
            company=x["company_name"].strip(),
            role=x["title"].strip(),
            url=x["url"],
            location=locs,
            remote=any("remote" in l.lower() for l in locs) or None,
            source="simplify",
            date_posted=datetime.fromtimestamp(x["date_posted"], timezone.utc).date() if x.get("date_posted") else None,
            sponsorship=None if sponsorship in (None, "Other") else sponsorship,
            level=level,
        )
        out.append((job, ""))
    return out
