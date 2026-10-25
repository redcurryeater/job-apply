"""Per-company application caps. docs/jobs.js implements the same rules — keep them in sync.

A slot is used by a job that is queued/applying (reserved) or whose applied_at falls inside
the company's rolling window, whatever its status now. Google's official rule is 3 per 30 days:
https://support.google.com/careers/answer/3437097
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .models import Job, JobsFile, Status

DEFAULT_PER_COMPANY = 3
DEFAULT_WINDOW_DAYS = 30
DEFAULT_COMPANIES = {"google": {"max": 3, "days": 30}}
RESERVED = {Status.queued, Status.applying}
LEGAL_SUFFIXES = {"inc", "llc", "ltd", "corp", "corporation", "co", "company", "plc", "gmbh"}


def company_key(name: str) -> str:
    """'Google LLC' -> 'google'. Subsidiaries (YouTube, DeepMind) stay separate."""
    words = re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
    while len(words) > 1 and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def cap_for(company: str, limits: dict) -> tuple[int, int]:
    """(max applications, window days) for a company."""
    per = int(limits.get("per_company", DEFAULT_PER_COMPANY))
    days = int(limits.get("window_days", DEFAULT_WINDOW_DAYS))
    merged = DEFAULT_COMPANIES | (limits.get("companies") or {})
    overrides = {company_key(k): v for k, v in merged.items()}
    o = overrides.get(company_key(company))
    if isinstance(o, dict):
        return int(o.get("max", per)), int(o.get("days", days))
    if o is not None:
        return int(o), days
    return per, days


@dataclass
class Usage:
    company: str
    used: int
    max: int
    days: int
    next_free: date | None  # None when nothing applied in-window frees up (all slots are queued)
    open: list[Job]         # potential/queued jobs, best match first

    @property
    def full(self) -> bool:
        return self.used >= self.max

    def message(self) -> str:
        msg = f"{self.company}: {self.used}/{self.max} applications used in {self.days} days"
        if not self.full:
            return msg
        return msg + (f" · next slot {self.next_free.isoformat()}" if self.next_free
                      else " · unqueue one to free a slot")


def _applied_on(job: Job) -> date | None:
    return job.applied_at.date() if isinstance(job.applied_at, datetime) else None


def usage(jf: JobsFile, company: str, limits: dict, today: date | None = None) -> Usage:
    today = today or date.today()
    key = company_key(company)
    cap, days = cap_for(company, limits)
    jobs = [j for j in jf.jobs if company_key(j.company) == key]
    start = today - timedelta(days=days)
    in_window, reserved = [], 0
    for j in jobs:  # each job holds at most one slot
        if (d := _applied_on(j)) and d > start:
            in_window.append(d)
        elif j.status in RESERVED:
            reserved += 1
    in_window.sort()
    used = reserved + len(in_window)
    next_free = in_window[0] + timedelta(days=days) if in_window else None
    open_ = sorted((j for j in jobs if j.status in (Status.potential, Status.queued)),
                   key=lambda j: -(j.match_score or 0))
    return Usage(company=company, used=used, max=cap, days=days, next_free=next_free, open=open_)


def check_transition(jf: JobsFile, job: Job, to: Status, limits: dict, today: date | None = None) -> str | None:
    """Reason the move is blocked, or None. Only moves *into* a reserved slot are capped."""
    if to not in RESERVED or job.status in RESERVED:
        return None
    u = usage(jf, job.company, limits, today)
    return u.message() if u.full else None
