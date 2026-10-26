"""Locations of per-user files. Everything personal lives in gitignored folders of the clone, or — on the
OpenClaw agent box — in a separate workspace (JOBAPPLY_HOME) and secrets folder (JOBAPPLY_SECRETS)."""

import os
from pathlib import Path

CODE = Path(__file__).resolve().parents[2]  # the checkout: templates/, docs/, skills


def _find_root() -> Path:
    if env := os.environ.get("JOBAPPLY_HOME"):
        return Path(env).expanduser().resolve()
    here = Path.cwd().resolve()
    for d in (here, *here.parents):
        if (d / "pyproject.toml").exists() and (d / "src" / "jobapply").exists():
            return d
    # Installed elsewhere: fall back to the package's own checkout.
    return CODE


ROOT = _find_root()
DATA = ROOT / "data"          # clone of the user's private job-data repo
PROFILE = ROOT / "profile"    # profile.yaml, resume.pdf — never committed anywhere
# gmail client + token, portal account index, file password store. Kept outside the agent's workspace on the
# agent box so its file tools can't read them; only the CLI can.
SECRETS = Path(os.environ["JOBAPPLY_SECRETS"]).expanduser().resolve() if os.environ.get("JOBAPPLY_SECRETS") \
    else ROOT / "secrets"
TEMPLATES = CODE / "templates"
DOCS = CODE / "docs"

JOBS_FILE = DATA / "jobs.json"
SEARCH_FILE = DATA / "search.toml"
PROFILE_FILE = PROFILE / "profile.yaml"


def ensure_secrets() -> Path:
    SECRETS.mkdir(mode=0o700, parents=True, exist_ok=True)
    return SECRETS


def write_secret(path: Path, text: str) -> None:
    """Write atomically, readable by the owner only (0600 on POSIX; Windows ignores the mode)."""
    ensure_secrets()
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)  # a leftover could carry looser permissions
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
