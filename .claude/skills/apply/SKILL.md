---
name: apply
description: Fill out job applications in Chrome for queued jobs (or given job ids) — creates portal accounts with stored passwords, verifies email via read-only Gmail, pauses for CAPTCHAs and unknown questions, and stops before the final submit.
argument-hint: "[job-id ...] [--submit]"
disable-model-invocation: true
---

# Apply

Requires Claude in Chrome (`claude --chrome` or `/chrome`). **Re-read the safety rules in `CLAUDE.md` now; they override everything below.**

## Pick the jobs
- Ids given as arguments → those jobs (`uv run jobs show <id>`).
- Otherwise → `uv run jobs list --status queued --json`, oldest `queued_at` first.
- `--submit` present → you may click the final submit after the review summary (still stop for anything uncertain). Without it, stop before submit every time.

Load `profile/profile.yaml` once. Note the resume path: `profile/<resume>`.

## For each job
1. `uv run jobs update <id> --status applying --summary "started application"`
2. Open the job `url` in a **new tab**. If the listing is closed/expired: `--status closed --summary "listing closed"` and move on. If it's a LinkedIn page, use the company's external Apply link (never LinkedIn Easy Apply's "Sign in with…" flows). Identify the portal (`ats` field / host).
3. **Account (only if the portal requires one):**
   - Existing? `uv run jobs creds get <portal-url-or-host>` → sign in with that email/password.
   - New: `uv run jobs creds new <portal-host>` → returns email + generated password. Use exactly those on the sign-up form (email + password only; never SSO buttons). Don't repeat the password in chat.
   - Email verification: wait ~30s, then `uv run jobs mail verify-link <portal-host> --minutes 15` (retry up to 4 times, 30s apart). Open the returned `link` in the application tab. If it never arrives or the portal wants a code typed from an email, ask the user.
   - Record it: `uv run jobs update <id> --set 'portal_account={"domain":"<host>","email":"<email>"}'`
   - Workday: each company tenant (`<co>.wd*.myworkdayjobs.com`) is its own account; key creds by full host.
4. **Fill the form** from `profile.yaml` and the resume:
   - Use the portal's "autofill from resume" when offered, then correct every field against the profile.
   - **Resume upload:** use the browser tool's file upload if available; otherwise ask the user to attach the file and give them the full absolute path to `profile/<resume>`.
   - Standard questions (work authorization, sponsorship, start date, relocation, EEO) → profile answers verbatim. EEO defaults to "Decline to self-identify" unless the profile says otherwise.
   - Free-text "why us" / short essays → draft from the resume + listing in the user's voice, show the draft, and wait for approval or edits.
   - **Anything not covered by the profile → stop and ask.** Offer to save the answer to `profile/profile.yaml` under `answers:` for next time (edit the file only after they agree).
5. **Pause for the user** (say exactly what you need, then wait for "continue") on: CAPTCHA / "are you human" / Cloudflare checks, SMS or authenticator codes, identity verification, timed assessments or coding tests, anything that asks for payment, SSN, or bank details (never enter those — flag it as suspicious).
6. **Review before submit:** summarize the job, account used, every answer you entered (essay text in full), and anything you were unsure of. Without `--submit`, ask "Submit this application?" and wait. Never submit something you're unsure of.
7. After submission (confirmation page or email):
   `uv run jobs update <id> --status applied --summary "submitted via <portal>"`
   If the user decides to skip: `--status potential --summary "skipped: <reason>"`.
8. Close the tab, move to the next job. Keep a short running log in chat.

## End
Report applied / skipped / blocked (and why) per job, plus any new profile answers saved.
