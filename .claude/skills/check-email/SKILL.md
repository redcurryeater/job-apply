---
name: check-email
description: Scan the user's Gmail (read-only API) for application confirmations, rejections, assessments, interview invites and offers, and update the matching jobs in the tracker.
argument-hint: "[--days N]"
---

# Check email

Email is read only through the CLI (read-only Gmail API). Never open Gmail in the browser.

1. Scan:
   ```
   uv run jobs mail scan            # or: uv run jobs mail scan --days N
   ```
   If it says the login expired, tell the user to run `uv run jobs mail auth` (needed weekly) and stop.
   Output: `scanned_at` and a list of emails (`email_id`, `date`, `from`, `subject`, `snippet`, `body`) not processed before.

2. Load the tracker: `uv run jobs list --sort updated --limit 500 --json`.

3. For each email decide:
   - **Which job**: match company name (from sender display name, sender domain, subject, body) and role title against jobs that are `applying` / `applied` / `assessment` / `interview` first, then any status. If several roles at the same company could match and the email doesn't say which, pick the most recently applied one and mention the ambiguity in the summary.
   - **What it is** → status:
     - application received / thank you for applying → `applied` (only if currently `queued`/`applying`/`potential`; otherwise just an event)
     - online assessment / coding challenge / HireVue → `assessment`
     - interview invite, scheduling request, recruiter call → `interview`
     - rejection ("unfortunately", "not moving forward", "other candidates") → `rejected`
     - offer → `offer`
     - anything else relevant (e.g. "position filled", status update) → event only
   - Never move a job *backwards* (e.g. a late "application received" must not undo `interview`); record it as an event instead.

4. Apply each one (one email per command so dedup by `email_id` works):
   ```
   uv run jobs update <job-id> --status interview --email-id <email_id> --summary "Interview invite from <sender>: <key detail, e.g. deadline/date>"
   uv run jobs update <job-id> --event email --email-id <email_id> --summary "..."      # event only
   ```
   Recruiting email for a job not in the tracker (e.g. applied outside this tool): add it with `uv run jobs add --company ... --role ... --url <best link or careers page> --source email`, then update as above.

5. Finish the scan (records the cursor and the emails that matched nothing, so they aren't shown again):
   ```
   uv run jobs mail done --scanned-at <scanned_at> --ignore <email_id> --ignore <email_id> ...
   ```

6. Report: a short table of changes (company, role, old → new status, one-line detail), deadlines (assessments due, interview times) prominently, and anything ambiguous.
