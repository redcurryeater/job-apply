"""Read/write data/jobs.json and keep it in sync with the user's private job-data repo.

The dashboard edits the same file through the GitHub API, so every write here is
pull -> mutate -> commit -> push, retried from a fresh copy if the push is rejected.
"""

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from . import paths
from .models import Job, JobsFile, dedupe_key, now, same_place

T = TypeVar("T")


class Store:
    def __init__(self, data_dir: Path = paths.DATA, sync: bool = True):
        self.dir = data_dir
        self.file = data_dir / "jobs.json"
        self.sync = sync and (data_dir / ".git").exists()

    # --- file ---------------------------------------------------------------
    def load(self) -> JobsFile:
        if not self.file.exists():
            if not self.dir.exists():
                raise SystemExit("No data/ folder. Run `uv run jobs init` first.")
            return JobsFile()
        return JobsFile.model_validate_json(self.file.read_text(encoding="utf-8"))

    def save(self, jf: JobsFile) -> None:
        text = json.dumps(jf.model_dump(mode="json", exclude_none=True), indent=2, ensure_ascii=False)
        self.file.write_text(text + "\n", encoding="utf-8", newline="\n")

    # --- git ----------------------------------------------------------------
    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(self.dir), *args], capture_output=True, text=True, check=check)

    def _has_remote(self) -> bool:
        return bool(self.git("remote", check=False).stdout.strip())

    def pull(self) -> None:
        if self.sync and self._has_remote():
            r = self.git("pull", "--rebase", "--autostash", "--quiet", check=False)
            if r.returncode != 0 and "couldn't find remote ref" not in r.stderr:
                self.git("rebase", "--abort", check=False)
                raise RuntimeError(f"git pull failed in data/: {r.stderr.strip()}")

    def _commit_push(self, message: str, files: list[str]) -> bool:
        """Returns False if the push was rejected (remote moved on)."""
        if not self.sync:
            return True
        self.git("add", *files)
        if not self.git("status", "--porcelain", check=False).stdout.strip():
            return True
        self.git("commit", "--quiet", "-m", message)
        if not self._has_remote():
            return True
        return self.git("push", "--quiet", "origin", "HEAD", check=False).returncode == 0

    def _reset_to_remote(self) -> None:
        self.git("fetch", "--quiet", "origin")
        branch = self.git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        self.git("reset", "--hard", "--quiet", f"origin/{branch}")

    def mutate(self, fn: Callable[[JobsFile], T], message: str) -> T:
        """Apply fn to the freshest jobs.json, save, commit and push. fn must be safe to re-run."""
        for _ in range(3):
            self.pull()
            jf = self.load()
            result = fn(jf)
            self.save(jf)
            if self._commit_push(message, ["jobs.json"]):
                return result
            self._reset_to_remote()
        raise RuntimeError("Could not push data/ after 3 attempts; check `git -C data status`.")


def find_existing(jf: JobsFile, job: Job) -> Job | None:
    """The stored job with the same url, else the same company+role in a compatible location."""
    key = dedupe_key(job.company, job.role)
    return next((j for j in jf.jobs if j.id == job.id), None) or next(
        (j for j in jf.jobs if dedupe_key(j.company, j.role) == key and same_place(j.location, job.location)), None)


def upsert(jf: JobsFile, job: Job) -> tuple[str, Job]:
    """Add job, or merge it into an existing one (see find_existing).

    Returns ("added" | "updated" | "unchanged", stored_job). Never overwrites a user's
    status, notes or events; only fills in fields that are empty on the stored job.
    """
    existing = find_existing(jf, job)
    if existing is None:
        jf.jobs.append(job)
        return "added", job

    changed = False
    incoming = job.model_dump(exclude_unset=True, exclude={"id", "status", "events", "notes", "created_at", "updated_at"})
    for field, value in incoming.items():
        if value in (None, "", [], {}):
            continue
        current = getattr(existing, field, None)
        if current in (None, "", [], {}):
            setattr(existing, field, getattr(job, field))
            changed = True
    if changed:
        existing.updated_at = now()
    return ("updated" if changed else "unchanged"), existing
