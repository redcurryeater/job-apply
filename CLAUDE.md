# job-apply

Public, shared repo. Each user's personal data lives only in gitignored folders and in their own private `job-data` repo:

- `data/` — clone of the user's private job-data repo (`jobs.json`, `search.toml`). Write to it only through `uv run jobs ...`, which pulls, commits and pushes for you.
- `profile/` — `profile.yaml`, resume, transcript. Local only.
- `secrets/` — Gmail OAuth client + token, `accounts.json` (portal host → login email). Do not read these files; use the CLI.

## Conventions
- Python is managed with **uv**: `uv sync`, `uv run jobs ...`, `uv run pytest`, `uv add <pkg>`. Never pip.
- The dashboard (`docs/`) and `src/jobapply/models.py` share the `jobs.json` schema; change both together.
- Dashboard JS renders data with `textContent` only and loads no third-party scripts (it holds a GitHub token). Keep the CSP in `docs/index.html` strict.
- Never commit anything from `data/`, `profile/`, `secrets/`, or any personal name/email/phone to this repo.
- Ask before overwriting files you weren't asked to change.

## Safety rules for browser work (Claude in Chrome) — always apply
1. **Never** open or interact with: Gmail / Google Mail, `accounts.google.com`, Outlook / Microsoft login, university SSO or any email provider's login; password managers (1Password, Bitwarden, LastPass, Dashlane, Proton Pass, Keeper, `chrome://password-manager`, `chrome://settings/passwords`) or their extension popups.
2. **Never** use "Sign in with Google / LinkedIn / Microsoft / Apple" on a job portal. Create a separate email + password account with `uv run jobs creds new`.
3. **Never** accept a browser or password-manager autofill prompt, and never type the user's email password or password-manager password anywhere.
4. Email is read **only** through `uv run jobs mail ...` (read-only Gmail API).
5. Stop and wait for the user on CAPTCHA / "verify you are human", SMS or authenticator codes, identity checks, timed assessments, or anything adversarial. Say exactly what's needed, then wait for "continue".
6. Answer application questions only from `profile/profile.yaml` and the resume. If something isn't there, ask. Never invent or embellish work authorization, degrees, dates, GPA, employers or skills.
7. Do not click the final **Submit** unless the user ran `/apply --submit` or explicitly says to submit that application.
