import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from jobapply import creds
from jobapply.match import SearchConfig, passes_filters, score
from jobapply.models import Job, JobsFile, Status, detect_ats, job_id, normalize_url
from jobapply.sources import ats_boards, github_trackers
from jobapply.store import Store, upsert

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


# --- models -------------------------------------------------------------------
def test_normalize_url_strips_tracking_and_keeps_real_params():
    a = "https://www.Example.com/jobs/123/?utm_source=Simplify&ref=Simplify&gh_jid=55#apply"
    assert normalize_url(a) == "https://example.com/jobs/123?gh_jid=55"
    assert job_id(a) == job_id("https://example.com/jobs/123?gh_jid=55")


def test_linkedin_urls_collapse_to_job_number():
    assert normalize_url("https://www.linkedin.com/jobs/view/software-engineer-at-acme-4012345678/?trk=x") \
        == normalize_url("https://linkedin.com/jobs/view/4012345678")


def test_detect_ats():
    assert detect_ats("https://acme.wd5.myworkdayjobs.com/en-US/External/job/X") == "workday"
    assert detect_ats("https://job-boards.greenhouse.io/anthropic/jobs/1") == "greenhouse"
    assert detect_ats("https://acme.com/careers") is None


def test_set_status_records_event_and_timestamps():
    j = Job(company="A", role="SWE", url="https://a.com/1")
    j.set_status(Status.queued)
    j.set_status(Status.applied, "submitted")
    assert j.queued_at and j.applied_at
    assert [e.type for e in j.events] == ["queued", "applied"]


# --- upsert -------------------------------------------------------------------
def test_upsert_dedupes_by_url_and_company_role_without_clobbering_user_fields():
    jf = JobsFile()
    a = Job(company="Acme", role="Software Engineer", url="https://jobs.lever.co/acme/1", location=["NYC"])
    assert upsert(jf, a)[0] == "added"
    jf.jobs[0].set_status(Status.applied)
    jf.jobs[0].notes = "mine"

    same_url = Job(company="Acme", role="Software Engineer", url="https://jobs.lever.co/acme/1?lever-source=x",
                   closes_at=date(2030, 1, 1))
    assert upsert(jf, same_url)[0] == "updated"
    other_board = Job(company="ACME", role="Software  Engineer", url="https://linkedin.com/jobs/view/9",
                      location=["NYC"], source="linkedin")
    assert upsert(jf, other_board)[0] == "unchanged"
    assert len(jf.jobs) == 1
    j = jf.jobs[0]
    assert j.status == Status.applied and j.notes == "mine" and j.closes_at == date(2030, 1, 1)


def test_extra_fields_round_trip():
    jf = JobsFile.model_validate({"jobs": [{"company": "A", "role": "R", "url": "https://a.com", "starred": True}]})
    assert jf.model_dump(mode="json")["jobs"][0]["starred"] is True


# --- store + git ----------------------------------------------------------------
def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_mutate_retries_when_remote_moved(tmp_path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    a, b = tmp_path / "a", tmp_path / "b"
    git(tmp_path, "clone", str(remote), str(a))
    for d in (a,):
        git(d, "config", "user.email", "t@t"), git(d, "config", "user.name", "t")
    Store(a).save(JobsFile())
    git(a, "add", "."), git(a, "commit", "-m", "init"), git(a, "push", "origin", "HEAD:main")
    git(tmp_path, "clone", str(remote), str(b))
    git(b, "config", "user.email", "t@t"), git(b, "config", "user.name", "t")

    # "Dashboard" (clone b) pushes first; clone a must rebase/retry and keep both jobs.
    Store(b).mutate(lambda jf: upsert(jf, Job(company="B", role="R", url="https://b.com")), "b")
    Store(a).mutate(lambda jf: upsert(jf, Job(company="A", role="R", url="https://a.com")), "a")
    Store(b).pull()
    assert {j.company for j in Store(b).load().jobs} == {"A", "B"}


# --- sources --------------------------------------------------------------------
def test_simplify_parse_skips_inactive_and_filters_category():
    jobs = github_trackers.parse(load("simplify.json"), "SimplifyJobs/New-Grad-Positions", ["Software"])
    assert len(jobs) == 3
    j = jobs[0][0]
    assert j.source == "simplify" and j.level == "new grad" and j.date_posted and j.sponsorship is None


def test_greenhouse_parse_and_pay():
    jobs = ats_boards.parse_greenhouse_list(load("greenhouse_list.json"), "anthropic")
    assert len(jobs) == 3 and jobs[0].company == "Anthropic" and jobs[0].date_posted
    assert jobs[0].location == ["San Francisco, CA", "Seattle, WA"]
    desc = ats_boards.apply_greenhouse_detail(jobs[0], load("greenhouse_job.json"))
    assert jobs[0].salary.min == 190000 and jobs[0].salary.max == 230000
    assert "<" not in desc


def test_lever_and_ashby_parse():
    lev = ats_boards.parse_lever(load("lever.json"), "palantir")
    assert lev[0][0].salary.min == 120000 and lev[0][0].salary.period == "year" and lev[0][0].date_posted
    ash = ats_boards.parse_ashby(load("ashby.json"), "ramp")
    j = ash[0][0]
    assert j.role == "Security Engineer, Cloud" and j.salary.min == 211400 and j.remote
    assert "Remote (US)" in j.location


# --- matching -------------------------------------------------------------------
CFG = SearchConfig(title_include=["software", "engineer"], title_exclude=["senior", "staff"],
                   locations=["remote", "ca", "nyc"], max_age_days=30, terms=["python", "backend", "ml"])


def test_filters():
    today = date(2026, 10, 24)
    ok = Job(company="A", role="Software Engineer", url="https://a/1", location=["San Jose, CA"],
             date_posted=date(2026, 10, 20))
    assert passes_filters(ok, CFG, today) is None
    assert passes_filters(ok.model_copy(update={"role": "Senior Software Engineer"}), CFG, today).startswith("title excluded")
    assert passes_filters(ok.model_copy(update={"role": "Accountant"}), CFG, today) == "title not included"
    assert passes_filters(ok.model_copy(update={"location": ["Austin, TX"]}), CFG, today) == "location"
    paris = ok.model_copy(update={"location": ["Paris, France"], "remote": True})
    assert passes_filters(paris, CFG, today) == "location"
    assert passes_filters(ok.model_copy(update={"date_posted": date(2026, 1, 1)}), CFG, today) == "too old"


def test_short_terms_match_whole_words():
    j = Job(company="A", role="ML Engineer", url="https://a/1")
    s, hits = score(j, CFG, "We use python. html is not ml")
    assert "ml" in hits and "python" in hits and 30 < s <= 100
    assert score(Job(company="A", role="Software Engineer", url="https://a/2"), CFG, "")[0] == 30


# --- creds ----------------------------------------------------------------------
def test_portal_host_and_password():
    assert creds.portal_host("https://Acme.wd5.myworkdayjobs.com/en-US/x") == "acme.wd5.myworkdayjobs.com"
    assert creds.portal_host("www.icims.com") == "icims.com"
    pw = creds.generate_password()
    assert len(pw) == 20 and any(c in creds.SYMBOLS for c in pw)


def test_creds_round_trip(tmp_path, monkeypatch):
    store = {}
    monkeypatch.setattr(creds, "ACCOUNTS", tmp_path / "accounts.json")
    monkeypatch.setattr(creds.paths, "SECRETS", tmp_path)
    monkeypatch.setattr(creds.keyring, "set_password", lambda s, u, p: store.__setitem__((s, u), p))
    monkeypatch.setattr(creds.keyring, "get_password", lambda s, u: store.get((s, u)))
    host, pw = creds.new("https://acme.wd1.myworkdayjobs.com/x", "me@example.com")
    assert creds.get("acme.wd1.myworkdayjobs.com") == (host, "me@example.com", pw)
    with pytest.raises(SystemExit):
        creds.new(host, "me@example.com")
    assert "password" not in (tmp_path / "accounts.json").read_text()
