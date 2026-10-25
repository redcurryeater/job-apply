"""`uv run jobs ...` — the command line the Claude skills (and you) drive."""

import functools
import http.server
import json
import sys
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Optional

import typer
import yaml

from . import paths
from .limits import check_transition
from .match import SearchConfig
from .models import Event, Job, JobsFile, Salary, Status, now
from .store import Store, upsert

# Windows consoles default to cp1252; job titles and emails are full of en dashes and accents.
for stream in (sys.stdout, sys.stderr, sys.stdin):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Job application tracker + agent helpers.")
creds_app = typer.Typer(no_args_is_help=True, help="Job-portal accounts (passwords live in the OS keyring).")
mail_app = typer.Typer(no_args_is_help=True, help="Read-only Gmail: recruiting-mail scan, verification links.")
app.add_typer(creds_app, name="creds")
app.add_typer(mail_app, name="mail")


def out(obj) -> None:
    typer.echo(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def dump(job: Job) -> dict:
    return job.model_dump(mode="json", exclude_none=True)


def read_json_arg(src: str):
    return json.loads(sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8"))


# --- setup ------------------------------------------------------------------
@app.command()
def init(repo: Annotated[str, typer.Option(help="Name of your private data repo.")] = "job-data"):
    """Create your private data repo, clone it into data/, and create profile/ from the template."""
    from .init import init as do_init
    for line in do_init(repo):
        typer.echo(line)


@app.command("resume-text")
def resume_text():
    """Print the text of profile/<resume> so Claude can read it."""
    from pypdf import PdfReader
    resume = "resume.pdf"
    if paths.PROFILE_FILE.exists():
        resume = (yaml.safe_load(paths.PROFILE_FILE.read_text(encoding="utf-8")) or {}).get("resume") or resume
    pdf = paths.PROFILE / resume
    if not pdf.exists():
        raise SystemExit(f"No resume at {pdf}")
    typer.echo("\n".join(page.extract_text() or "" for page in PdfReader(pdf).pages))


# --- tracker ----------------------------------------------------------------
@app.command()
def add(
    json_src: Annotated[Optional[str], typer.Option("--json", help="File or '-' for stdin: a job object or a list.")] = None,
    company: Optional[str] = None, role: Optional[str] = None, url: Optional[str] = None,
    location: Annotated[Optional[list[str]], typer.Option(help="Repeatable.")] = None,
    posted: Annotated[Optional[str], typer.Option(help="YYYY-MM-DD")] = None,
    closes: Annotated[Optional[str], typer.Option(help="YYYY-MM-DD")] = None,
    salary_min: Optional[int] = None, salary_max: Optional[int] = None,
    salary_estimated: Annotated[bool, typer.Option(help="Mark salary as an estimate.")] = False,
    source: str = "manual", notes: str = "",
):
    """Add jobs (merged into existing entries with the same url or company+role)."""
    if json_src:
        raw = read_json_arg(json_src)
        jobs = [Job.model_validate(r) for r in (raw if isinstance(raw, list) else [raw])]
    else:
        if not (company and role and url):
            raise typer.BadParameter("give --json, or --company, --role and --url")
        salary = Salary(min=salary_min, max=salary_max or salary_min,
                        basis="estimated" if salary_estimated else "listed") if salary_min else None
        jobs = [Job(company=company, role=role, url=url, location=location or [], source=source, notes=notes,
                    date_posted=posted, closes_at=closes, salary=salary)]

    def apply(jf: JobsFile):
        return [(r, j.id, j.company, j.role) for r, j in (upsert(jf, job) for job in jobs)]

    results = Store().mutate(apply, f"add {len(jobs)} job(s)")
    out([{"result": r, "id": i, "company": c, "role": ro} for r, i, c, ro in results])


def _coerce(value: str):
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


@app.command()
def update(
    job_id: Annotated[str, typer.Argument(help="Job id or unique prefix.")],
    status: Optional[Status] = None,
    summary: Annotated[str, typer.Option(help="Event text for the timeline.")] = "",
    event: Annotated[Optional[str], typer.Option(help="Add a timeline event of this type without changing status.")] = None,
    email_id: Annotated[Optional[str], typer.Option(help="Gmail message id this update came from.")] = None,
    note: Annotated[Optional[str], typer.Option(help="Append a line to notes.")] = None,
    set_: Annotated[Optional[list[str]], typer.Option("--set", help="field=value (JSON values allowed). Repeatable.")] = None,
):
    """Change a job's status, add a timeline event, append notes or set fields."""

    def apply(jf: JobsFile):
        job = jf.get(job_id)
        if email_id and email_id in jf.seen_email_ids():
            return dump(job) | {"skipped": "email already processed"}
        target = status or next((Status(_coerce(v)) for k, _, v in (kv.partition("=") for kv in set_ or [])
                                 if k.strip() == "status"), None)
        if target and (blocked := check_transition(jf, job, target, SearchConfig.load().limits)):
            raise SystemExit(f"Blocked by per-company cap — {blocked}. Raise it in search.toml [limits] if needed.")
        if set_:
            data = dump(job)
            for kv in set_:
                k, _, v = kv.partition("=")
                data[k.strip()] = _coerce(v)
            new = Job.model_validate(data)
            jf.jobs[jf.jobs.index(job)] = job = new
        if status:
            job.set_status(status, summary, email_id)
        elif event or email_id:
            job.events.append(Event(type=event or "email", summary=summary, email_id=email_id))
        if note:
            job.notes = (job.notes + "\n" if job.notes else "") + note
        job.touch()
        return dump(job)

    out(Store().mutate(apply, f"update {job_id}" + (f" -> {status.value}" if status else "")))


@app.command()
def limits(
    company: Annotated[Optional[str], typer.Argument(help="Only this company.")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    top: Annotated[int, typer.Option(help="Best open jobs to list per company.")] = 3,
):
    """Per-company application caps: slots used, next free slot, best openings to spend them on."""
    from .limits import company_key, usage
    store = Store()
    store.pull()
    jf = store.load()
    cfg = SearchConfig.load().limits
    names: dict[str, str] = {}
    for j in jf.jobs:
        names.setdefault(company_key(j.company), j.company)
    if company:
        names = {company_key(company): company}
    rows = [usage(jf, name, cfg) for name in names.values()]
    rows = [u for u in rows if u.used or u.open]
    rows.sort(key=lambda u: (-u.used, -len(u.open), u.company.lower()))
    if as_json:
        return out([{"company": u.company, "used": u.used, "max": u.max, "days": u.days, "full": u.full,
                     "next_free": u.next_free, "free_slots": max(0, u.max - u.used),
                     "best_open": [{"id": j.id, "role": j.role, "status": j.status.value, "match_score": j.match_score}
                                   for j in u.open[:top]]} for u in rows])
    for u in rows:
        flag = "FULL" if u.full else f"{u.max - u.used} free"
        nxt = f"  next slot {u.next_free}" if u.full and u.next_free else ""
        typer.echo(f"{u.company[:28]:<28} {u.used}/{u.max} per {u.days}d  {flag}{nxt}  ({len(u.open)} open)")
        for j in u.open[:top]:
            score = f"{j.match_score:>5.1f}" if j.match_score is not None else "    -"
            typer.echo(f"    {j.id}  {score}  {j.status.value:<9} {j.role[:70]}")


@app.command("list")
def list_(
    status: Annotated[Optional[list[Status]], typer.Option(help="Repeatable.")] = None,
    sort: Annotated[str, typer.Option(help="match | posted | closes | updated")] = "match",
    limit: int = 50,
    as_json: Annotated[bool, typer.Option("--json")] = False,
):
    """List jobs (default: all, best match first)."""
    store = Store()
    store.pull()
    jobs = [j for j in store.load().jobs if not status or j.status in status]
    keys = {
        "match": lambda j: -(j.match_score or 0),
        "posted": lambda j: -(j.date_posted or date.min).toordinal(),
        "closes": lambda j: (j.closes_at or date.max).toordinal(),
        "updated": lambda j: -j.updated_at.timestamp(),
    }
    jobs = sorted(jobs, key=keys[sort])[:limit]
    if as_json:
        return out([dump(j) for j in jobs])
    for j in jobs:
        score = f"{j.match_score:>5.1f}" if j.match_score is not None else "    -"
        typer.echo(f"{j.id}  {j.status.value:<10} {score}  {j.company[:24]:<24} {j.role[:60]}")


@app.command()
def show(job_id: str):
    """Print one job as JSON."""
    store = Store()
    store.pull()
    out(dump(store.load().get(job_id)))


@app.command()
def fetch(
    dry_run: Annotated[bool, typer.Option(help="Print what would be added without saving.")] = False,
    only: Annotated[Optional[str], typer.Option(help="simplify | greenhouse | lever | ashby")] = None,
):
    """Pull the GitHub trackers and company boards from search.toml; add matches as potential."""
    from .fetch import collect, merge

    report = collect(SearchConfig.load(), only)
    for e in report.errors:
        typer.echo(f"error: {e}", err=True)
    typer.echo(f"{report.seen} listings checked, {len(report.kept)} match your filters", err=True)
    if dry_run:
        for j in sorted(report.kept, key=lambda j: -(j.match_score or 0)):
            typer.echo(f"{j.match_score:>5.1f}  {str(j.date_posted or ''):<10}  {j.company[:24]:<24} {j.role[:60]}")
        return
    counts = Store().mutate(lambda jf: merge(jf, report.kept), f"fetch: {len(report.kept)} matching listings")
    out(counts)


@app.command()
def dashboard(port: int = 8765):
    """Serve the dashboard from docs/ on localhost (same page as the hosted one)."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(paths.DOCS))
    url = f"http://localhost:{port}/"
    typer.echo(f"Serving {paths.DOCS} at {url} (Ctrl+C to stop)")
    webbrowser.open(url)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()


# --- portal accounts --------------------------------------------------------
def _profile_email() -> str | None:
    if paths.PROFILE_FILE.exists():
        return (yaml.safe_load(paths.PROFILE_FILE.read_text(encoding="utf-8")) or {}).get("email") or None
    return None


@creds_app.command("new")
def creds_new(
    domain: Annotated[str, typer.Argument(help="Portal URL or host, e.g. acme.wd5.myworkdayjobs.com")],
    email: Annotated[Optional[str], typer.Option(help="Defaults to email in profile.yaml.")] = None,
    overwrite: bool = False,
):
    """Generate and store a password for a new portal account; prints it for the sign-up form."""
    from . import creds
    email = email or _profile_email()
    if not email:
        raise SystemExit("No email given and none in profile/profile.yaml.")
    host, pw = creds.new(domain, email, overwrite)
    out({"host": host, "email": email, "password": pw})


@creds_app.command("get")
def creds_get(domain: str):
    """Look up the stored login for a portal."""
    from . import creds
    found = creds.get(domain)
    if not found:
        raise SystemExit(f"No stored account for {creds.portal_host(domain)}.")
    host, email, pw = found
    out({"host": host, "email": email, "password": pw})


@creds_app.command("list")
def creds_list():
    """Portal hosts with stored accounts (no passwords)."""
    from . import creds
    out(creds.list_hosts())


# --- gmail ------------------------------------------------------------------
@mail_app.command("auth")
def mail_auth():
    """Sign in to Gmail (read-only) in the browser. Needed once a week."""
    from . import gmail
    typer.echo(f"Authorized read-only access to {gmail.auth()}")


@mail_app.command("scan")
def mail_scan(
    days: Annotated[Optional[int], typer.Option(help="Look back this many days (default: since last scan, else 30).")] = None,
    limit: int = 200,
):
    """Print unprocessed recruiting emails as JSON for classification."""
    from . import gmail
    store = Store()
    store.pull()
    jf = store.load()
    if days is not None:
        since = now() - timedelta(days=days)
    elif jf.last_email_scan:
        since = jf.last_email_scan - timedelta(days=1)  # overlap; processed ids are skipped anyway
    else:
        since = now() - timedelta(days=30)
    emails = gmail.scan(since, jf.seen_email_ids(), limit)
    out({"since": since.isoformat(), "scanned_at": now().isoformat(), "count": len(emails), "emails": emails})


@mail_app.command("done")
def mail_done(
    scanned_at: Annotated[str, typer.Option(help="The scanned_at value printed by `mail scan`.")],
    ignore: Annotated[Optional[list[str]], typer.Option(help="Email ids that matched no job. Repeatable.")] = None,
):
    """Record that a scan was processed so the next scan starts from here."""

    def apply(jf: JobsFile):
        jf.last_email_scan = datetime.fromisoformat(scanned_at)
        jf.processed_emails = (jf.processed_emails + [i for i in ignore or [] if i not in jf.processed_emails])[-2000:]
        return {"last_email_scan": jf.last_email_scan, "ignored": len(ignore or [])}

    out(Store().mutate(apply, "email scan processed"))


@mail_app.command("verify-link")
def mail_verify_link(
    domain: Annotated[str, typer.Argument(help="Portal URL or host you just signed up on.")],
    minutes: int = 15,
):
    """Find the newest account-verification link for a portal (read-only)."""
    from . import gmail
    found = gmail.verify_link(domain, minutes)
    if not found:
        raise SystemExit(f"No verification email for {domain} in the last {minutes} minutes yet.")
    out(found)


if __name__ == "__main__":
    app()
