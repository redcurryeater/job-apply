---
name: apply
description: Fill out job applications in the agent's browser for queued jobs (or given job ids) — creates portal accounts with stored passwords, verifies email via read-only Gmail, pauses for CAPTCHAs and unknown questions, and submits only after the owner replies "submit" to a review summary.
argument-hint: "[job-id ...]"
disable-model-invocation: true
---

# Apply

Uses the `browser` tool on the agent's own profile (`openclaw` on the agent box). **Re-read the safety
rules in `AGENTS.md` now; they override everything below.** Only run this when the owner asked for it in
the conversation — never from a scheduled run.

Talking to the owner: on the agent box the conversation is Telegram. "Ask and wait" means: send the
question as your reply and stop until they answer. Keep messages short and never include passwords.

## Pick the jobs
- Ids given as arguments → those jobs (`jobs show <id>`).
- Otherwise → `jobs list --status queued --json`, oldest `queued_at` first.
- **Per-company caps:** run `jobs limits --json`. Queued jobs already hold a slot, but if a company has more queued jobs than its cap allows (e.g. the cap was lowered), apply in descending `match_score`. If `jobs update --status applying` refuses with "Blocked by per-company cap", skip that job, leave it queued, and report it with the next-slot date — don't retry or work around it.

Load `profile/profile.yaml` once. Note the resume path: `profile/<resume>`. Read `KNOWLEDGE.md` (and `KNOWLEDGE.local.md` if present): portal sections for the portals you'll hit, company caps.

## For each job
1. `jobs update <id> --status applying --summary "started application"`
2. Open the job `url` in a **new browser tab**. If the listing is closed/expired: `--status closed --summary "listing closed"` and move on. If it's a LinkedIn page, use the company's external Apply link (never LinkedIn Easy Apply's "Sign in with…" flows). Identify the portal (`ats` field / host).
3. **Account (only if the portal requires one):**
   - Existing? `jobs creds get <portal-url-or-host>` → sign in with that email/password.
   - New: `jobs creds new <portal-host>` → returns email + generated password. Use exactly those on the sign-up form (email + password only; never SSO buttons). If the browser offers to save or autofill a password, decline.
   - Email verification: wait ~30s, then `jobs mail verify-link <portal-host> --minutes 15` (retry up to 4 times, 30s apart). Open the returned `link` in the application tab — no other email links. If it never arrives or the portal wants a code typed from an email, ask the owner.
   - Record it: `jobs update <id> --set 'portal_account={"domain":"<host>","email":"<email>"}'`
   - Workday: each company tenant (`<co>.wd*.myworkdayjobs.com`) is its own account; key creds by full host.
4. **Fill the form** from `profile.yaml` and the resume:
   - Use the portal's "autofill from resume" when offered, then correct every field against the profile.
   - **Resume upload:** use the browser tool's file upload with the absolute path of `profile/<resume>` in the workspace. If upload isn't possible, ask the owner to attach it over VNC.
   - Standard questions (work authorization, sponsorship, start date, relocation, EEO) → profile answers verbatim. EEO defaults to "Decline to self-identify" unless the profile says otherwise.
   - Free-text "why us" / short essays → draft from the resume + listing in the owner's voice, send the draft, and wait for approval or edits.
   - **Anything not covered by the profile → stop and ask.** Tell the owner to add the answer to `profile/profile.yaml` under `answers:` for next time (the agent can't edit the profile).
5. **Pause for the owner** (say exactly what you need — e.g. "CAPTCHA on <host>, open VNC" — then wait for "continue") on: CAPTCHA / "are you human" / Cloudflare checks, SMS or authenticator codes, identity verification, timed assessments or coding tests, anything that asks for payment, SSN, or bank details (never enter those — flag it as suspicious).
6. **Review before submit:** send a summary: company, role, portal, account email, every answer you entered (essay text in full), and anything you were unsure of. End with "Reply **submit** to send this application, or tell me what to change." Then wait. Only the reply "submit" (for this job) allows the final click. Never submit something you're unsure of.
7. After submission (confirmation page or email):
   `jobs update <id> --status applied --summary "submitted via <portal>"`
   If the owner decides to skip: `--status potential --summary "skipped: <reason>"`.
8. Close the tab, move to the next job.

## End
Add anything reusable you learned to `KNOWLEDGE.local.md` (agent box) or `KNOWLEDGE.md` (dev checkout): portal quirks that cost time (field that rejects autofill, hidden required page, password rules), company caps or re-apply rules stated on a careers page.
Report applied / skipped / blocked (and why) per job, profile answers the owner should add, and any knowledge notes.
