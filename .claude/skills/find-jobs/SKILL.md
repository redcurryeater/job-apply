---
name: find-jobs
description: Find new job listings (GitHub trackers, company boards, LinkedIn via Claude in Chrome), score them against the user's resume, and add them to the tracker as potential.
argument-hint: "[--no-linkedin] [extra keywords]"
---

# Find jobs

Goal: add fresh, relevant listings to the user's tracker as `potential`, each with an honest `match_score` (0-100) and one-line `match_notes`. Read `CLAUDE.md` safety rules first.

## 1. Pull the structured sources
```
uv run jobs fetch
```
This reads `data/search.toml` (Simplify GitHub trackers + Greenhouse/Lever/Ashby company boards), filters and keyword-scores listings, and merges them into `data/jobs.json` (deduped; never overwrites the user's status/notes). Report the added/updated counts and any source errors.

## 2. LinkedIn (skip if `--no-linkedin` or Chrome isn't connected)
Needs Claude in Chrome (`claude --chrome`, or `/chrome`) and the user already signed in to LinkedIn in that browser. If LinkedIn shows a login page, stop and ask the user to sign in themselves — never type their LinkedIn password.

For each entry in `[[linkedin.searches]]` of `data/search.toml` (plus any extra keywords given as arguments):
1. Open `https://www.linkedin.com/jobs/search/?keywords=<urlencoded>&location=<urlencoded>&f_TPR=r604800&sortBy=DD` (past week, newest first).
2. Read the result list; for promising cards open the job and read title, company, location, posted date, any listed pay, and the description. Use the canonical `https://www.linkedin.com/jobs/view/<id>` URL. If "Apply" goes to an external site, prefer that external URL as `url` and put the LinkedIn URL in `notes`.
3. Apply the same judgement as `search.toml` filters (title include/exclude, locations, age, sponsorship).
4. Be gentle: at most ~40 job pages per run, pause a few seconds between pages, don't paginate past page 3. Stop if LinkedIn shows a warning or CAPTCHA and tell the user.

Add them in one batch:
```
uv run jobs add --json - <<'EOF'
[{"company": "...", "role": "...", "url": "...", "location": ["..."], "source": "linkedin",
  "date_posted": "YYYY-MM-DD", "salary": {"min": 0, "max": 0, "basis": "listed"}, "level": "new grad"}]
EOF
```
Omit fields you don't know (don't guess dates).

## 3. Score against the resume
1. `uv run jobs resume-text` (and skim `profile/profile.yaml` for degree, graduation date, work authorization).
2. `uv run jobs list --status potential --sort posted --limit 60 --json` — focus on jobs without `match_notes` from you yet (fetch only writes `keywords: ...`).
3. For each, judge fit honestly: required skills/degree/level vs. the resume, sponsorship vs. work authorization, location. Use listing text where available (open the URL in Chrome only for the top candidates if needed). Then:
```
uv run jobs update <id> --set match_score=78 --set 'match_notes="Strong: PyTorch, CV research. Gap: wants Go."'
```
4. If there's no listed pay, add an estimate from the role/level/location you are reasonably confident about, marked estimated:
```
uv run jobs update <id> --set 'salary={"min":120000,"max":150000,"basis":"estimated"}'
```
5. Clearly irrelevant jobs (wrong field, senior-only, excluded location): `uv run jobs update <id> --status closed --summary "not a fit: <reason>"`.

## 4. Report
Summarize: how many new jobs, the top ~10 by match (company, role, score, closes date if any), and anything closing within 7 days. Remind the user they can queue jobs on the dashboard and run `/apply`.
