"""Cheap keyword filter + score. Claude refines the score against the resume in /find-jobs."""

import re
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import paths
from .models import Job


@dataclass
class SearchConfig:
    title_include: list[str] = field(default_factory=list)
    title_exclude: list[str] = field(default_factory=list)
    company_exclude: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    max_age_days: int = 21
    needs_sponsorship: bool = False
    min_score: float = 25
    terms: list[str] = field(default_factory=list)
    simplify_repos: list[str] = field(default_factory=list)
    simplify_categories: list[str] = field(default_factory=list)
    ats: dict[str, list[str]] = field(default_factory=dict)
    linkedin: list[dict] = field(default_factory=list)
    limits: dict = field(default_factory=dict)  # raw [limits] section, see limits.py

    @classmethod
    def load(cls, path: Path = paths.SEARCH_FILE) -> "SearchConfig":
        if not path.exists():
            path = paths.TEMPLATES / "search.example.toml"
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        f, s = raw.get("filters", {}), raw.get("simplify", {})
        return cls(
            title_include=[t.lower() for t in f.get("title_include", [])],
            title_exclude=[t.lower() for t in f.get("title_exclude", [])],
            company_exclude=[t.lower() for t in f.get("company_exclude", [])],
            locations=[t.lower() for t in f.get("locations", [])],
            max_age_days=f.get("max_age_days", 21),
            needs_sponsorship=f.get("needs_sponsorship", False),
            min_score=f.get("min_score", 25),
            terms=[t.lower() for t in raw.get("keywords", {}).get("terms", [])],
            simplify_repos=s.get("repos", []),
            simplify_categories=s.get("categories", []),
            ats=raw.get("ats", {}),
            linkedin=raw.get("linkedin", {}).get("searches", []),
            limits=raw.get("limits", {}),
        )


NO_SPONSOR = ("does not offer sponsorship", "citizenship is required", "no sponsorship")


def _contains(text: str, term: str) -> bool:
    # Short alphanumeric terms ("ml", "ai") must match whole words.
    if len(term.strip()) <= 3:
        return re.search(rf"\b{re.escape(term.strip())}\b", text) is not None
    return term in text


def passes_filters(job: Job, cfg: SearchConfig, today: date | None = None) -> str | None:
    """Return None if the job passes, otherwise the reason it was rejected."""
    title = f" {job.role.lower()} "
    if cfg.title_include and not any(_contains(title, t) for t in cfg.title_include):
        return "title not included"
    if bad := next((t for t in cfg.title_exclude if _contains(title, t)), None):
        return f"title excluded ({bad.strip()})"
    company = f" {job.company.lower()} "
    if bad := next((c for c in cfg.company_exclude if _contains(company, c)), None):
        return f"company excluded ({bad.strip()})"
    if cfg.locations and job.location:
        # Match on the location text only: "remote" jobs are often remote within another country.
        locs = " | ".join(job.location).lower()
        if not any(_contains(locs, l) for l in cfg.locations):
            return "location"
    if job.date_posted and cfg.max_age_days:
        if ((today or date.today()) - job.date_posted).days > cfg.max_age_days:
            return "too old"
    if cfg.needs_sponsorship and job.sponsorship and any(s in job.sponsorship.lower() for s in NO_SPONSOR):
        return "no sponsorship"
    return None


def score(job: Job, cfg: SearchConfig, description: str = "") -> tuple[float, list[str]]:
    """0-100: 30 for a wanted title, up to 70 more from keywords (title hits weigh 3x description hits).

    Tracker listings have no description, so they mostly land near 30; Claude rescores them.
    """
    title, desc = f" {job.role.lower()} ", description.lower()
    base = 30.0 if not cfg.title_include or any(_contains(title, t) for t in cfg.title_include) else 0.0
    if not cfg.terms:
        return base, []
    points, hits = 0.0, []
    for t in cfg.terms:
        if _contains(title, t):
            points += 3
            hits.append(t)
        elif desc and _contains(desc, t):
            points += 1
            hits.append(t)
    # Keyword part maxes out once about a third of the terms hit in the title.
    full = max(3.0, len(cfg.terms))
    return round(base + min(70.0, 70 * points / full), 1), hits
