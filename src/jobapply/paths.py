"""Locations of per-user files. Everything personal lives in gitignored folders of the clone."""

import os
from pathlib import Path


def _find_root() -> Path:
    if env := os.environ.get("JOBAPPLY_HOME"):
        return Path(env).resolve()
    here = Path.cwd().resolve()
    for d in (here, *here.parents):
        if (d / "pyproject.toml").exists() and (d / "src" / "jobapply").exists():
            return d
    # Installed elsewhere: fall back to the package's own checkout.
    return Path(__file__).resolve().parents[2]


ROOT = _find_root()
DATA = ROOT / "data"          # clone of the user's private job-data repo
PROFILE = ROOT / "profile"    # profile.yaml, resume.pdf — never committed anywhere
SECRETS = ROOT / "secrets"    # gmail client + token, portal account index
TEMPLATES = ROOT / "templates"
DOCS = ROOT / "docs"

JOBS_FILE = DATA / "jobs.json"
SEARCH_FILE = DATA / "search.toml"
PROFILE_FILE = PROFILE / "profile.yaml"
