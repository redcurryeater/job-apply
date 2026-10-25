"""`jobs fetch`: pull every configured source, filter, score, upsert as potential."""

import sys
from dataclasses import dataclass, field

from .match import SearchConfig, passes_filters, score
from .models import Job, JobsFile
from .sources import ats_boards, client, github_trackers
from .store import upsert


@dataclass
class FetchReport:
    seen: int = 0
    kept: list[Job] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def collect(cfg: SearchConfig, only: str | None = None) -> FetchReport:
    report = FetchReport()
    keep = lambda job: passes_filters(job, cfg) is None
    candidates: list[tuple[Job, str]] = []
    with client() as http:
        if only in (None, "simplify"):
            for repo in cfg.simplify_repos:
                try:
                    print(f"simplify: {repo} ...", file=sys.stderr)
                    candidates += github_trackers.parse(github_trackers.fetch(repo, http), repo, cfg.simplify_categories)
                except Exception as e:  # one broken source shouldn't stop the rest
                    report.errors.append(f"simplify {repo}: {e}")
        for kind, fetcher in ats_boards.FETCHERS.items():
            if only not in (None, kind):
                continue
            for entry in cfg.ats.get(kind, []):
                board, _, name = entry.partition(":")  # "openai:OpenAI" sets the display name
                try:
                    print(f"{kind}: {board} ...", file=sys.stderr)
                    found = fetcher(board.strip(), http, keep)
                    for job, _desc in found:
                        job.company = name.strip() or job.company
                    candidates += found
                except Exception as e:
                    report.errors.append(f"{kind} {board}: {e}")

    report.seen = len(candidates)
    for job, desc in candidates:
        if not keep(job):
            continue
        s, hits = score(job, cfg, desc)
        if s < cfg.min_score:
            continue
        job.match_score = s
        job.match_notes = "keywords: " + ", ".join(hits) if hits else None
        report.kept.append(job)
    return report


def merge(jf: JobsFile, jobs: list[Job]) -> dict[str, int]:
    counts = {"added": 0, "updated": 0, "unchanged": 0}
    for job in jobs:
        counts[upsert(jf, job.model_copy(deep=True))[0]] += 1
    return counts
