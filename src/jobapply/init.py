"""`jobs init`: create this user's private job-data repo, clone it into data/, seed it."""

import json
import shutil
import subprocess
from urllib.parse import urlencode

from . import paths
from .models import JobsFile


def _run(*args: str, check: bool = True, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), capture_output=True, text=True, check=check, cwd=cwd)


def gh_login() -> str:
    r = _run("gh", "api", "user", "--jq", ".login", check=False)
    if r.returncode != 0:
        raise SystemExit("GitHub CLI isn't logged in. Run `gh auth login` first.")
    return r.stdout.strip()


def token_url(owner: str, repo: str) -> str:
    """Pre-filled fine-grained token form. The repository itself still has to be picked by hand."""
    q = {"name": f"jobapply dashboard ({repo})", "description": "Read/write jobs.json from the job-apply dashboard",
         "target_name": owner, "expires_in": "90", "contents": "write"}
    return "https://github.com/settings/personal-access-tokens/new?" + urlencode(q)


def init(repo: str = "job-data") -> list[str]:
    log = []
    owner = gh_login()
    full = f"{owner}/{repo}"

    if _run("gh", "repo", "view", full, check=False).returncode != 0:
        _run("gh", "repo", "create", full, "--private",
             "--description", "Private job-application tracker data (jobs.json) for job-apply")
        log.append(f"created private repo {full}")
    else:
        visibility = _run("gh", "repo", "view", full, "--json", "visibility", "--jq", ".visibility").stdout.strip()
        if visibility != "PRIVATE":
            raise SystemExit(f"{full} exists but is {visibility}. It must be private; pick another --repo name.")
        log.append(f"using existing private repo {full}")

    if not (paths.DATA / ".git").exists():
        if paths.DATA.exists() and any(paths.DATA.iterdir()):
            raise SystemExit("data/ exists and isn't a git clone; move it aside first.")
        _run("gh", "repo", "clone", full, str(paths.DATA))
        log.append(f"cloned into {paths.DATA}")

    seeded = []
    attrs = paths.DATA / ".gitattributes"
    if not attrs.exists():
        # The dashboard writes LF through the API; keep Windows checkouts from flipping line endings.
        attrs.write_text("* text=auto eol=lf\n", encoding="utf-8", newline="\n")
        seeded.append(".gitattributes")
    if not paths.JOBS_FILE.exists():
        paths.JOBS_FILE.write_text(json.dumps(JobsFile().model_dump(mode="json"), indent=2) + "\n",
                                   encoding="utf-8", newline="\n")
        seeded.append("jobs.json")
    if not paths.SEARCH_FILE.exists():
        shutil.copy(paths.TEMPLATES / "search.example.toml", paths.SEARCH_FILE)
        seeded.append("search.toml")
    if seeded:
        git = lambda *a: _run("git", "-C", str(paths.DATA), *a)
        git("add", *seeded)
        git("commit", "-m", "Initialize job tracker")
        git("branch", "-M", "main")
        git("push", "-u", "origin", "main")
        log.append(f"seeded {', '.join(seeded)} and pushed")

    paths.PROFILE.mkdir(exist_ok=True)
    paths.SECRETS.mkdir(exist_ok=True)
    if not paths.PROFILE_FILE.exists():
        shutil.copy(paths.TEMPLATES / "profile.example.yaml", paths.PROFILE_FILE)
        log.append(f"created {paths.PROFILE_FILE} from the template (fill it in)")

    log.append(f"dashboard repo: {full}")
    log.append(f"create a dashboard token (select only {full}, Contents: read & write): {token_url(owner, repo)}")
    return log
