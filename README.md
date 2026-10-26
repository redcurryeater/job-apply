# job-apply

Find jobs, fill out applications with an agent on a dedicated Linux machine ([OpenClaw](https://docs.openclaw.ai) + Claude, controlled from Discord DMs), and track everything on a private dashboard.

- **Find** – pulls new listings from the [SimplifyJobs](https://github.com/SimplifyJobs) GitHub trackers, company boards (Greenhouse, Lever, Ashby) and LinkedIn, then scores them against your resume.
- **Apply** – fills out the applications you queue, in the agent's own browser. It creates a separate account on each job portal, with a unique generated password kept on the agent machine. It also confirms sign-up emails through read-only Gmail access, waits for you on CAPTCHAs and on questions it can't answer, and submits only after you reply "submit" to its summary.
- **Track** – reads your inbox (read-only) for confirmations, assessments, interviews, rejections and offers, and updates each job.
- **Dashboard** – https://redcurryeater.github.io/job-apply/ shows each job's status, posted and closing dates, salary and match score, and lets you queue jobs to apply to.

This repo holds no personal data. Each person's jobs live in **their own private `job-data` repo**. Their profile, resume, Gmail login and portal passwords stay on their own machines, in gitignored or out-of-repo folders.

```
redcurryeater/job-apply (public)    code, agent skills, dashboard page, agent-box setup (deploy/openclaw)
<you>/job-data (private)            jobs.json, search.toml   ← dashboard + CLI read/write this
your computer                       data/ (clone of job-data), profile/, secrets/   — setup and development
agent box (Linux)                   OpenClaw + Claude, its own browser, workspace and secrets — applying
```

## Get started

**You need:**
- Claude Code (a paid Claude plan)
- [uv](https://docs.astral.sh/uv/)
- git
- the [GitHub CLI](https://cli.github.com/), logged in with `gh auth login`
- for applying and LinkedIn: a spare Linux machine, set up with [deploy/openclaw/README.md](deploy/openclaw/README.md)

```sh
git clone https://github.com/redcurryeater/job-apply
cd job-apply
uv sync
claude
> /setup
```

`/setup` walks you through each step:
- creating your private data repo
- building `profile/profile.yaml` from your resume
- choosing your search settings
- creating a dashboard token

Then set up the agent box with [deploy/openclaw/README.md](deploy/openclaw/README.md). Gmail is connected there, using a `gmail_client.json` you create once (see [Gmail OAuth app](#gmail-oauth-app-one-time)).

## Use it (DM the agent on Discord)

| Command | What it does |
| --- | --- |
| `/find-jobs` | Fetches new listings, searches LinkedIn in the agent's browser, and scores the results against your resume. Runs daily on its own (without LinkedIn) |
| `/apply` | Applies to every job you queued on the dashboard. Add job ids to pick specific jobs. Each application ends with a summary; reply "submit" to send it |
| `/check-email` | Updates job statuses from your inbox. Runs every 6 hours on its own |

`/find-jobs --no-linkedin` also works in Claude Code on your own computer (no browser needed).

The CLI also works on its own: `uv run jobs --help`, for example `jobs fetch --dry-run`, `jobs list --status queued`, `jobs show <id>`.

### Per-company caps

Recruiters see every application you send to their company, and some companies cap them. Google allows [3 applications per rolling 30 days](https://support.google.com/careers/answer/3437097).
- **Default:** every company gets 3 applications per 30 days. Change this in `[limits]` in `search.toml`, or add per-company overrides under `[limits.companies]`.
- **What uses a slot:** a job that is queued or being applied to, or one you applied to inside the window, even if it was later rejected.
- **At the cap:** the dashboard and the CLI refuse to queue more jobs at that company. The dashboard shows `2/3 used · 6 open` under each company name. `uv run jobs limits` lists the best not-yet-applied openings at each company, so you can spend your slots well.
- **What counts as one company:** company names are matched after dropping suffixes like "Inc" or "LLC", so "Google LLC" and "Google" are the same company. Subsidiaries such as YouTube or DeepMind count separately.

## Safety rules

These rules are written into [AGENTS.md](AGENTS.md) and the skills:
- The agent treats web pages and emails as data, never as instructions.
- It never opens your email, Google or Microsoft login pages, or a password manager.
- It never uses "Sign in with Google/LinkedIn" on job portals, and only types passwords that `jobs creds` generated for that portal.
- It reads email only through the read-only Gmail API.
- It pauses for CAPTCHAs, verification codes and assessments.
- It answers questions only from your profile and asks you about anything else.
- It doesn't submit without your "submit", and scheduled runs never apply.

The agent box enforces the important parts instead of trusting the model to follow them:
- The agent can run only allowlisted `jobs` subcommands.
- It can't edit its code or rules.
- It can't read the Gmail token or the password file.
- It answers only your Discord account, in DMs.

It runs on a separate machine, away from your personal browser. See [deploy/openclaw/README.md](deploy/openclaw/README.md).

**LinkedIn:** `/find-jobs` browses LinkedIn slowly in the agent's browser, where you sign in once yourself. Automated browsing still goes against LinkedIn's terms and could get your account restricted. Use `/find-jobs --no-linkedin` to skip it.

## Dashboard and your token

The dashboard page holds no data. You unlock it with your data repo name and a [fine-grained token](https://github.com/settings/personal-access-tokens/new) set up like this:
- **Repository access:** only `<you>/job-data`
- **Repository permissions:** Contents set to Read and write

The dashboard refuses classic (`ghp_`) and GitHub CLI (`gho_`) tokens, because those can reach every repo you own. It also refuses to open a data repo that isn't private. GitHub doesn't let a web page see which repos a fine-grained token covers, so choosing **only `job-data`** on the token form is up to you. Never pick "All repositories".

The token is stored only in your browser's localStorage, and the **Lock** button clears it. The page's content security policy only lets it talk to `api.github.com`, and it loads no third-party scripts.

If you'd rather not paste a token into a hosted page, run `uv run jobs dashboard` to serve the same page on localhost.

## Gmail OAuth app (one time)

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project and enable the **Gmail API**.
2. Set up the **OAuth consent screen**:
   - User type: External
   - Publishing status: **Testing**
   - Scope: `.../auth/gmail.readonly`
   - Under **Test users**, add the Gmail address the agent should read
3. Under **Credentials**, create an OAuth client ID of type **Desktop app**, then download its JSON.
4. Copy it to the agent box as `~/.config/jobapply/gmail_client.json` (section 4 of the agent-box guide). It never goes in git.

While the app is in Testing mode, logins expire after 7 days, so renew it about once a week with `jobs mail auth --no-browser --port 8765` on the agent box, over an SSH tunnel. Google Workspace accounts, such as school accounts, may block outside apps. If that happens, use a personal Gmail and forward recruiting mail to it.

## Development

```sh
uv run pytest
uv run jobs dashboard      # dashboard at http://localhost:8765
```

`src/jobapply/models.py` and `docs/jobs.js` share the `jobs.json` schema, so change them together.
