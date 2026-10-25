---
name: setup
description: First-time setup for a new user of job-apply — creates their private data repo, builds their profile from their resume, configures their search, connects Gmail (read-only), and gets the dashboard unlocked.
disable-model-invocation: true
---

# Setup

Walk the user through this one step at a time; confirm each step worked before moving on. Skip steps that are already done (check for `data/.git`, `profile/profile.yaml`, `secrets/gmail_token.json`).

## 0. Prerequisites
Check: `uv --version`, `git --version`, `gh auth status`. If `gh` isn't logged in, ask the user to run `gh auth login` themselves. Run `uv sync`.

## 1. Private data repo
```
uv run jobs init
```
Creates `<their-github-user>/job-data` (private), clones it into `data/`, seeds `jobs.json` + `search.toml`, and creates `profile/profile.yaml` from the template. Confirm the repo is private.

## 2. Profile
1. Ask for their resume PDF path; copy it to `profile/resume.pdf` (or set `resume:` in the profile to its filename in `profile/`).
2. `uv run jobs resume-text`, then pre-fill `profile/profile.yaml` (name, email, phone, links, education) from it.
3. Ask them to fill in what a resume doesn't say: address, work authorization / sponsorship, start date, relocation, desired salary (optional), EEO preferences (default "Decline to self-identify"). Don't guess any of these.
4. Show the finished profile for review. Remind them it never leaves their computer.

## 3. Search settings
Ask: target roles, level (intern / new grad / experienced), locations or remote, sponsorship needs, companies they especially want. Edit `data/search.toml` accordingly:
- `[simplify] repos`: `SimplifyJobs/New-Grad-Positions` for full-time new grad; the current `SimplifyJobs/Summer<YEAR>-Internships` for internships.
- `[ats]`: board names of dream companies (find them from the company careers URL).
- `[[linkedin.searches]]`: 1-3 searches.
Sanity-check the filters with `uv run jobs fetch --dry-run` (prints matches without saving) and adjust until the list looks right. Then push the settings: `git -C data add search.toml && git -C data commit -m "search settings" && git -C data push`.

## 4. Gmail (read-only)
1. They need `gmail_client.json` from the project owner (who must also add their Gmail address as a test user in Google Cloud). Ask them to save it as `secrets/gmail_client.json` — don't open it.
2. `uv run jobs mail auth` → a browser consent page opens; they approve read-only access. Explain: the app is in testing mode, so this must be repeated about weekly.
3. If their school/work Google account blocks it, suggest a personal Gmail with a forwarding filter for recruiting mail.

## 5. Dashboard
1. `uv run jobs init` printed a token link. Tell them to open it, choose **Only select repositories → job-data**, Repository permissions → **Contents: Read and write**, generate, and copy the token.
2. Open https://redcurryeater.github.io/job-apply/ and enter `<user>/job-data` + the token. (Alternative: `uv run jobs dashboard` for a localhost copy.)

## 6. Browser safety
Tell them to start Claude Code with `claude --chrome` (or `/chrome`) for `/find-jobs` and `/apply`, and in the Claude in Chrome extension settings, block: `mail.google.com`, `accounts.google.com`, `outlook.live.com`, `outlook.office.com`, `login.microsoftonline.com`, their school SSO domain, and their password manager's web vault.

## 7. First run
Offer to run `/find-jobs` now.
