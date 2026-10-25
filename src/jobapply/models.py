"""Job tracker schema. jobs.json is shared with the dashboard (docs/jobs.js), keep both in sync."""

import hashlib
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1


class Status(StrEnum):
    potential = "potential"
    queued = "queued"
    applying = "applying"
    applied = "applied"
    assessment = "assessment"
    interview = "interview"
    offer = "offer"
    rejected = "rejected"
    withdrawn = "withdrawn"
    closed = "closed"


def now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class Salary(BaseModel):
    model_config = ConfigDict(extra="allow")
    min: int | None = None
    max: int | None = None
    currency: str = "USD"
    period: Literal["year", "month", "hour"] = "year"
    basis: Literal["listed", "estimated"] = "listed"


class Event(BaseModel):
    model_config = ConfigDict(extra="allow")
    date: datetime = Field(default_factory=now)
    type: str  # status name, "email", "note", ...
    summary: str = ""
    email_id: str | None = None


class PortalAccount(BaseModel):
    domain: str
    email: str


class Job(BaseModel):
    # extra="allow" so fields added by the dashboard or newer versions survive a round trip.
    model_config = ConfigDict(extra="allow")

    id: str = ""
    company: str
    role: str
    url: str
    location: list[str] = []
    remote: bool | None = None
    source: str = "manual"
    date_posted: date | None = None
    closes_at: date | None = None
    salary: Salary | None = None
    level: str | None = None
    sponsorship: str | None = None
    match_score: float | None = None
    match_notes: str | None = None
    status: Status = Status.potential
    queued_at: datetime | None = None
    applied_at: datetime | None = None
    ats: str | None = None
    portal_account: PortalAccount | None = None
    events: list[Event] = []
    notes: str = ""
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)

    def model_post_init(self, _ctx) -> None:
        if not self.id:
            self.id = job_id(self.url)
        if not self.ats:
            self.ats = detect_ats(self.url)

    def set_status(self, status: Status, summary: str = "", email_id: str | None = None) -> None:
        if status == self.status and not summary:
            return
        self.status = status
        if status == Status.queued and not self.queued_at:
            self.queued_at = now()
        if status == Status.applied and not self.applied_at:
            self.applied_at = now()
        self.events.append(Event(type=status.value, summary=summary, email_id=email_id))
        self.touch()

    def touch(self) -> None:
        self.updated_at = now()


class JobsFile(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: int = SCHEMA_VERSION
    last_email_scan: datetime | None = None
    processed_emails: list[str] = []  # email ids classified as irrelevant, so scans skip them
    jobs: list[Job] = []

    def get(self, id_or_prefix: str) -> Job:
        matches = [j for j in self.jobs if j.id.startswith(id_or_prefix)]
        if len(matches) != 1:
            raise KeyError(f"{len(matches)} jobs match id {id_or_prefix!r}")
        return matches[0]

    def seen_email_ids(self) -> set[str]:
        ids = set(self.processed_emails)
        for j in self.jobs:
            ids.update(e.email_id for e in j.events if e.email_id)
        return ids


TRACKING_PARAMS = {"ref", "refid", "src", "source", "trk", "trackingid", "lipi", "gh_src", "lever-source",
                   "lever-origin", "jobsource"}


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    if "linkedin.com" in host and "/jobs/view/" in path:
        # /jobs/view/<slug>-<id> and /jobs/view/<id> are the same posting
        path = "/jobs/view/" + path.rsplit("-", 1)[-1].rsplit("/", 1)[-1]
        return urlunsplit(("https", host, path, "", ""))
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS]
    return urlunsplit(("https", host, path, urlencode(sorted(query)), ""))


def job_id(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode()).hexdigest()[:10]


def dedupe_key(company: str, role: str) -> str:
    norm = lambda s: " ".join("".join(c if c.isalnum() else " " for c in s.lower()).split())
    return f"{norm(company)}|{norm(role)}"


ATS_HOSTS = {
    "myworkdayjobs.com": "workday", "myworkdaysite.com": "workday", "greenhouse.io": "greenhouse",
    "lever.co": "lever", "ashbyhq.com": "ashby", "icims.com": "icims", "taleo.net": "taleo",
    "smartrecruiters.com": "smartrecruiters", "successfactors.com": "successfactors",
    "jobvite.com": "jobvite", "workable.com": "workable", "oraclecloud.com": "oracle",
    "linkedin.com": "linkedin", "eightfold.ai": "eightfold", "bamboohr.com": "bamboohr",
}


def detect_ats(url: str) -> str | None:
    host = urlsplit(url).netloc.lower()
    return next((ats for h, ats in ATS_HOSTS.items() if host == h or host.endswith("." + h)), None)
