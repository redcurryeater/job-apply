# Knowledge

What Claude has learned while finding jobs, applying and reading email, so the next session
doesn't rediscover it. Read the relevant section before starting; add to it before you finish.

## Rules for this file
- **Public repo.** No names, emails, phone numbers, job ids, account details, answers from
  `profile/`, or anything else about a particular user. Facts about portals and companies only.
- One bullet per fact: `- <fact> — <how you know: link, or "seen on <host>">, YYYY-MM-DD`.
- Only write what you saw or read from an official source. Hearsay (forums, Glassdoor, a
  recruiter's offhand remark) is allowed only if marked `(unconfirmed)`.
- If something here turns out wrong or stale, fix or delete it, don't append a contradiction.
- Keep it terse and grouped under the headings below; add a heading for a new portal/company.
- In a dev checkout, edit this file directly (it's code, not data), then tell the user it changed so they
  can commit. On the OpenClaw agent box it's read-only: append to `KNOWLEDGE.local.md` in the workspace,
  same rules, and the user merges entries in here.

## Company application limits
Official caps also go into `DEFAULT_COMPANIES` in `src/jobapply/limits.py` so they're enforced.
Unconfirmed caps stay here only; users can add them to `[limits.companies]` in `search.toml`.

| Company | Cap | Source | Checked |
|---|---|---|---|
| Google | 3 applications / 30 days | https://support.google.com/careers/answer/3437097 | 2026-10-24 |

## Portals

### Workday (`<co>.wd*.myworkdayjobs.com`)
- Every company tenant is a separate account; key creds by the full host, not `myworkdayjobs.com`
  — Workday tenant model, 2026-10-24

### Greenhouse (`boards.greenhouse.io`, `job-boards.greenhouse.io`)

### Lever (`jobs.lever.co`)

### Ashby (`jobs.ashbyhq.com`)

### Other portals

## Companies
Per-company quirks beyond caps (separate careers site, referral-only, re-apply rules, etc.).

## Email
Sender/subject patterns that `/check-email` misread or that identify a portal.
