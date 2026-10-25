"""Public job-board APIs for a company watchlist: Greenhouse, Lever, Ashby.

`prefilter` is applied before any per-job request, so details (descriptions, pay) are
only fetched for jobs that could be kept.
"""

from collections.abc import Callable
from datetime import datetime, timezone

import httpx

from ..models import Job, Salary
from . import html_to_text, split_locations

Prefilter = Callable[[Job], bool]

PERIODS = {"year": "year", "yearly": "year", "1 year": "year", "per-year-salary": "year",
           "hour": "hour", "hourly": "hour", "1 hour": "hour", "per-hour-wage": "hour",
           "month": "month", "1 month": "month", "per-month-salary": "month"}


def _date(iso: str | None):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).date() if iso else None


def _remote(locs: list[str]) -> bool | None:
    return any("remote" in l.lower() for l in locs) or None


# --- Greenhouse -------------------------------------------------------------
GH_LIST = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
GH_JOB = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}?pay_transparency=true"


def parse_greenhouse_list(data: dict, board: str) -> list[Job]:
    jobs = []
    for j in data.get("jobs", []):
        locs = split_locations((j.get("location") or {}).get("name"))
        jobs.append(Job(
            company=j.get("company_name") or board, role=j["title"].strip(), url=j["absolute_url"],
            location=locs, remote=_remote(locs), source="greenhouse",
            date_posted=_date(j.get("first_published") or j.get("updated_at")),
            closes_at=_date(j.get("application_deadline")),
            gh_id=j["id"],
        ))
    return jobs


def apply_greenhouse_detail(job: Job, detail: dict) -> str:
    for p in detail.get("pay_input_ranges") or []:
        if p.get("min_cents"):
            job.salary = Salary(min=p["min_cents"] // 100, max=(p.get("max_cents") or p["min_cents"]) // 100,
                                currency=p.get("currency_type") or "USD")
            break
    return html_to_text(detail.get("content", ""))


def greenhouse(board: str, http: httpx.Client, prefilter: Prefilter) -> list[tuple[Job, str]]:
    r = http.get(GH_LIST.format(board=board))
    r.raise_for_status()
    out = []
    for job in filter(prefilter, parse_greenhouse_list(r.json(), board)):
        gh_id = job.__pydantic_extra__.pop("gh_id")
        d = http.get(GH_JOB.format(board=board, id=gh_id))
        desc = apply_greenhouse_detail(job, d.json()) if d.is_success else ""
        out.append((job, desc))
    return out


# --- Lever ------------------------------------------------------------------
LEVER_LIST = "https://api.lever.co/v0/postings/{board}?mode=json"


def parse_lever(data: list[dict], board: str) -> list[tuple[Job, str]]:
    out = []
    for j in data:
        cat = j.get("categories") or {}
        locs = cat.get("allLocations") or split_locations(cat.get("location"))
        sal = j.get("salaryRange") or {}
        job = Job(
            company=board.replace("-", " ").title(), role=j["text"].strip(), url=j["hostedUrl"],
            location=locs, remote=(j.get("workplaceType") == "remote") or _remote(locs), source="lever",
            date_posted=datetime.fromtimestamp(j["createdAt"] / 1000, timezone.utc).date() if j.get("createdAt") else None,
            salary=Salary(min=int(sal["min"]), max=int(sal.get("max") or sal["min"]), currency=sal.get("currency") or "USD",
                          period=PERIODS.get(str(sal.get("interval", "")).lower(), "year")) if sal.get("min") else None,
        )
        desc = "\n".join(filter(None, [j.get("descriptionPlain"), j.get("additionalPlain"),
                                       *(html_to_text(l.get("content", "")) for l in j.get("lists") or [])]))
        out.append((job, desc))
    return out


def lever(board: str, http: httpx.Client, prefilter: Prefilter) -> list[tuple[Job, str]]:
    r = http.get(LEVER_LIST.format(board=board))
    r.raise_for_status()
    return [c for c in parse_lever(r.json(), board) if prefilter(c[0])]


# --- Ashby ------------------------------------------------------------------
ASHBY_LIST = "https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true"


def parse_ashby(data: dict, board: str) -> list[tuple[Job, str]]:
    out = []
    for j in data.get("jobs", []):
        if not j.get("isListed", True):
            continue
        locs = [j.get("location") or "", *(s.get("location", "") for s in j.get("secondaryLocations") or [])]
        locs = [l for l in locs if l]
        salary = None
        for c in (j.get("compensation") or {}).get("summaryComponents") or []:
            if c.get("compensationType") == "Salary" and c.get("minValue"):
                salary = Salary(min=int(c["minValue"]), max=int(c.get("maxValue") or c["minValue"]),
                                currency=c.get("currencyCode") or "USD",
                                period=PERIODS.get(str(c.get("interval", "")).lower(), "year"))
                break
        job = Job(
            company=board.replace("-", " ").title(), role=j["title"].strip(), url=j["jobUrl"],
            location=locs, remote=j.get("isRemote") or _remote(locs), source="ashby",
            date_posted=_date(j.get("publishedAt")), salary=salary,
        )
        out.append((job, j.get("descriptionPlain") or ""))
    return out


def ashby(board: str, http: httpx.Client, prefilter: Prefilter) -> list[tuple[Job, str]]:
    r = http.get(ASHBY_LIST.format(board=board))
    r.raise_for_status()
    return [c for c in parse_ashby(r.json(), board) if prefilter(c[0])]


FETCHERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}
