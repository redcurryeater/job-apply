import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from jobapply import creds
from jobapply.gmail import _find_code
from jobapply.match import SearchConfig, passes_filters, score
from jobapply.models import Job, JobsFile, Status, detect_ats, job_id, normalize_url, same_place
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


def test_place_matching_across_location_formats():
    assert same_place(["San Francisco, CA"], ["San Francisco, California, United States"])
    assert same_place(["San Francisco Bay Area"], ["Seattle, WA", "San Francisco, CA"])
    assert same_place(["New York City Metropolitan Area"], ["NYC"])
    assert same_place(["Remote (US)"], ["United States (Remote)"])
    assert same_place(["United States"], ["Austin, TX"]) and same_place([], ["Austin, TX"])
    assert not same_place(["Austin, TX"], ["San Francisco, CA"])
    assert not same_place(["Remote"], ["San Francisco, CA"])


def test_upsert_merges_linkedin_copy_of_board_job_but_not_other_cities():
    jf = JobsFile()
    upsert(jf, Job(company="Acme", role="Software Engineer, New Grad", url="https://job-boards.greenhouse.io/acme/jobs/1",
                   location=["San Francisco, California, United States"], source="greenhouse"))
    li = Job(company="Acme", role="Software Engineer - New Grad", url="https://www.linkedin.com/jobs/view/4012345678",
             location=["San Francisco Bay Area"], source="linkedin", match_score=80)
    assert upsert(jf, li)[0] == "updated" and len(jf.jobs) == 1 and jf.jobs[0].match_score == 80
    nyc = li.model_copy(update={"url": "https://www.linkedin.com/jobs/view/4012345679", "location": ["New York, NY"]})
    assert upsert(jf, nyc)[0] == "added" and len(jf.jobs) == 2


def test_unseen_prints_only_untracked_cards(tmp_path):
    import os
    data = tmp_path / "data"
    data.mkdir()
    Store(data).save(JobsFile(jobs=[
        Job(company="Acme", role="SWE", url="https://www.linkedin.com/jobs/view/111", status=Status.closed),
        Job(company="Beta", role="ML Engineer", url="https://jobs.lever.co/beta/1", location=["Seattle, WA"]),
    ]))
    cards = [{"company": "Acme", "role": "SWE", "url": "https://www.linkedin.com/jobs/view/swe-at-acme-111"},
             {"company": "Beta", "role": "ML Engineer", "url": "https://www.linkedin.com/jobs/view/222",
              "location": ["Greater Seattle Area"]},
             {"company": "Gamma", "role": "SWE", "url": "https://www.linkedin.com/jobs/view/333", "location": ["Remote"]}]
    (tmp_path / "cards.json").write_text(json.dumps(cards))
    r = subprocess.run(["uv", "run", "jobs", "unseen", "--json", "cards.json"], capture_output=True, text=True,
                       env={**os.environ, "JOBAPPLY_HOME": str(tmp_path)}, cwd=Path(__file__).parents[1])
    assert r.returncode == 0, r.stderr
    assert [c["company"] for c in json.loads(r.stdout)] == ["Gamma"]


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
    austin = ok.model_copy(update={"location": ["Austin, TX"]})
    assert passes_filters(austin, CFG, today) is None  # locations only rank unless only_preferred_locations
    strict = CFG.__class__(**{**CFG.__dict__, "only_preferred_locations": True})
    assert passes_filters(austin, strict, today) == "location"
    paris = ok.model_copy(update={"location": ["Paris, France"], "remote": True})
    assert passes_filters(paris, strict, today) == "location"
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


@pytest.fixture
def creds_dir(tmp_path, monkeypatch):
    d = tmp_path / "s"
    monkeypatch.setattr(creds, "ACCOUNTS", d / "accounts.json")
    monkeypatch.setattr(creds, "PASSWORDS", d / "passwords.json")
    monkeypatch.setattr(creds.paths, "SECRETS", d)
    return d


def test_creds_round_trip(creds_dir):
    host, pw = creds.new("https://acme.wd1.myworkdayjobs.com/x", "me@example.com")
    assert creds.get("acme.wd1.myworkdayjobs.com") == (host, "me@example.com", pw)
    assert creds.get("other.example.com") is None
    with pytest.raises(SystemExit):
        creds.new(host, "me@example.com")
    assert "password" not in (creds_dir / "accounts.json").read_text()
    assert json.loads((creds_dir / "passwords.json").read_text()) == {host: pw}


def test_creds_files_are_owner_only(creds_dir):
    import os
    import stat
    creds.new("jobs.lever.co", "me@example.com")
    if os.name == "posix":
        assert stat.S_IMODE((creds_dir / "passwords.json").stat().st_mode) == 0o600
        assert stat.S_IMODE(creds_dir.stat().st_mode) == 0o700


def test_paths_split_code_workspace_and_secrets(tmp_path):
    import os
    import sys
    env = {**os.environ, "JOBAPPLY_HOME": str(tmp_path / "home"), "JOBAPPLY_SECRETS": str(tmp_path / "sec")}
    r = subprocess.run([sys.executable, "-c", "from jobapply import paths; "
                        "print(paths.DATA, paths.SECRETS, paths.TEMPLATES, sep='\\n')"],
                       capture_output=True, text=True, env=env, cwd=tmp_path, check=True)
    data, secrets_dir, templates = map(Path, r.stdout.splitlines())
    assert data == (tmp_path / "home" / "data").resolve()
    assert secrets_dir == (tmp_path / "sec").resolve()
    assert (templates / "search.example.toml").exists()   # from the code checkout, not JOBAPPLY_HOME


def test_add_json_only_reads_workspace_files(tmp_path, monkeypatch):
    from jobapply import cli
    monkeypatch.setattr(cli.paths, "ROOT", tmp_path / "home")
    monkeypatch.setattr(cli.paths, "SECRETS", tmp_path / "home" / "secrets")
    (tmp_path / "home" / "secrets").mkdir(parents=True)
    (tmp_path / "home" / "new.json").write_text('[{"x": 1}]')
    (tmp_path / "home" / "secrets" / "passwords.json").write_text('{"a": "b"}')
    (tmp_path / "outside.json").write_text('{"a": "b"}')
    assert cli.read_json_arg(str(tmp_path / "home" / "new.json")) == [{"x": 1}]
    for bad in (tmp_path / "outside.json", tmp_path / "home" / "secrets" / "passwords.json",
                tmp_path / "home" / ".." / "outside.json"):
        with pytest.raises(SystemExit):
            cli.read_json_arg(str(bad))


def test_stage_resume_copies_only_the_profile_resume(tmp_path, monkeypatch):
    from jobapply import cli
    profile = tmp_path / "home" / "profile"
    profile.mkdir(parents=True)
    monkeypatch.setattr(cli.paths, "PROFILE", profile)
    monkeypatch.setattr(cli.paths, "PROFILE_FILE", profile / "profile.yaml")
    monkeypatch.setattr(cli.paths, "UPLOADS", tmp_path / "inbound")
    (profile / "cv.pdf").write_bytes(b"%PDF-1.4 resume")
    (profile / "profile.yaml").write_text("resume: cv.pdf\n")
    cli.stage_resume()
    assert (tmp_path / "inbound" / "cv.pdf").read_bytes() == b"%PDF-1.4 resume"
    (tmp_path / "secret.json").write_text("{}")
    (profile / "profile.yaml").write_text("resume: ../../secret.json\n")
    with pytest.raises(SystemExit):
        cli.stage_resume()
    assert not (tmp_path / "inbound" / "secret.json").exists()


# --- per-company caps -------------------------------------------------------------
from datetime import datetime, timedelta, timezone  # noqa: E402

from jobapply.limits import cap_for, check_transition, company_key, usage  # noqa: E402

TODAY = date(2026, 10, 24)


def _job(company, n, status=Status.potential, applied_days_ago=None, score=None):
    j = Job(company=company, role=f"Role {n}", url=f"https://x.com/{company}/{n}", status=status, match_score=score)
    if applied_days_ago is not None:
        j.applied_at = datetime(2026, 10, 24, tzinfo=timezone.utc) - timedelta(days=applied_days_ago)
    return j


def test_company_key_and_caps():
    assert company_key("Google LLC") == company_key("google") == "google"
    assert company_key("Acme, Inc.") == "acme" and company_key("Co") == "co"
    assert cap_for("Google LLC", {}) == (3, 30)
    assert cap_for("Acme", {"per_company": 2, "window_days": 60}) == (2, 60)
    # User overrides merge with the built-in Google rule instead of replacing it.
    lim = {"companies": {"Meta": 5, "acme": {"max": 1, "days": 90}}}
    assert cap_for("Meta Platforms Inc", lim) == (3, 30)  # different key: "meta platforms"
    assert cap_for("meta", lim) == (5, 30) and cap_for("Acme", lim) == (1, 90) and cap_for("Google", lim) == (3, 30)


def test_usage_counts_reserved_and_in_window_once():
    jf = JobsFile(jobs=[
        _job("Google", 1, Status.queued),
        _job("Google LLC", 2, Status.rejected, applied_days_ago=10),
        _job("google", 3, Status.applied, applied_days_ago=40),   # outside window
        _job("Google", 4, Status.applying, applied_days_ago=5),    # counted once
        _job("Google", 5, Status.potential, score=90),
    ])
    u = usage(jf, "Google", {}, TODAY)
    assert (u.used, u.max, u.full) == (3, 3, True)
    assert u.next_free == date(2026, 10, 14) + timedelta(days=30)
    assert [j.role for j in u.open] == ["Role 5", "Role 1"]
    assert "next slot 2026-11-13" in u.message()


def test_check_transition_blocks_only_new_reservations():
    jf = JobsFile(jobs=[_job("Acme", i, Status.queued) for i in range(3)] + [_job("Acme", 9)])
    new = jf.jobs[-1]
    assert "3/3" in check_transition(jf, new, Status.queued, {}, TODAY)
    assert "unqueue one" in check_transition(jf, new, Status.applying, {}, TODAY)
    assert check_transition(jf, jf.jobs[0], Status.applying, {}, TODAY) is None   # already holds a slot
    assert check_transition(jf, new, Status.applied, {}, TODAY) is None            # recording a fact


def test_cli_refuses_queue_at_cap(tmp_path):
    import os
    import shutil
    data = tmp_path / "data"
    data.mkdir()
    shutil.copy(Path(__file__).parents[1] / "templates" / "search.example.toml", data / "search.toml")
    jf = JobsFile(jobs=[_job("Google", i, Status.queued) for i in range(3)] + [_job("Google", 9)])
    Store(data).save(jf)
    env = {**os.environ, "JOBAPPLY_HOME": str(tmp_path)}
    run = lambda *a: subprocess.run(["uv", "run", "jobs", *a], capture_output=True, text=True, env=env,
                                     cwd=Path(__file__).parents[1])
    r = run("update", jf.jobs[-1].id, "--status", "queued")
    assert r.returncode != 0 and "per-company cap" in r.stderr and "3/3" in r.stderr
    r = run("update", jf.jobs[-1].id, "--set", "status=queued")
    assert r.returncode != 0
    assert Store(data).load().jobs[-1].status == Status.potential
    assert run("update", jf.jobs[0].id, "--status", "applying").returncode == 0
    r = run("limits", "--json")
    assert '"full": true' in r.stdout


# --- gmail --------------------------------------------------------------------
def test_find_code_after_keyword_or_before_is_your():
    assert _find_code("Your verification code is: 482913. It expires in 10 minutes.") == "482913"
    assert _find_code("Enter this one-time passcode\n\n  AB12CD  \nto continue") == "AB12CD"
    assert _find_code("Subject: 739201 is your Acme sign-in code") == "739201"
    assert _find_code("Your code expires in 10 minutes.") is None
    assert _find_code("Thanks for applying to Acme.") is None
