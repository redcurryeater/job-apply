# job-apply

Find jobs, fill out applications with [Claude in Chrome](https://claude.com/chrome), and track everything on a private dashboard.

- **Find** – pulls new listings from the [SimplifyJobs](https://github.com/SimplifyJobs) GitHub trackers, company boards (Greenhouse, Lever, Ashby) and LinkedIn, then scores them against your resume.
- **Apply** – fills out the applications you queue. It creates a separate account on each job portal, with a unique password kept in your OS keyring. It also confirms sign-up emails through read-only Gmail access, waits for you on CAPTCHAs and on questions it can't answer, and stops before the final submit.
- **Track** – reads your inbox (read-only) for confirmations, assessments, interviews, rejections and offers, and updates each job.
- **Dashboard** – https://redcurryeater.github.io/job-apply/ shows each job's status, posted and closing dates, salary and match score, and lets you queue jobs to apply to.

This repo holds no personal data. Each person's jobs live in **their own private `job-data` repo**. Their profile, resume and Gmail login stay on their own computer, in the gitignored `profile/` and `secrets/` folders.

```
redcurryeater/job-apply (public)    code, Claude skills, dashboard page
<you>/job-data (private)            jobs.json, search.toml   ← dashboard + CLI read/write this
your computer                       data/ (clone of job-data), profile/, secrets/
```

## Get started

**You need:**
- Claude Code (Pro or Max plan) with the Claude in Chrome extension
- [uv](https://docs.astral.sh/uv/)
- git
- the [GitHub CLI](https://cli.github.com/), logged in with `gh auth login`

```sh
git clone https://github.com/redcurryeater/job-apply
cd job-apply
uv sync
claude --chrome
> /setup
```

`/setup` walks you through each step:
- creating your private data repo
- building `profile/profile.yaml` from your resume
- choosing your search settings
- connecting Gmail
- creating a dashboard token

For Gmail you need `gmail_client.json` from the project owner, and the owner has to add your Gmail address as a tester first. Ask them for both.

## Use it (inside `claude --chrome` in this folder)

| Command | What it does |
| --- | --- |
| `/find-jobs` | Fetches new listings, searches LinkedIn in your browser, and scores the results against your resume |
| `/apply` | Applies to every job you queued on the dashboard. Add job ids to pick specific jobs, or `--submit` to let it click submit after showing you a summary |
| `/check-email` | Updates job statuses from your inbox. Run it on a schedule with `/loop 6h /check-email` |

The CLI also works on its own: `uv run jobs --help`, for example `jobs fetch --dry-run`, `jobs list --status queued`, `jobs show <id>`, `jobs creds get <portal>`.

## Safety rules

These rules are written into [CLAUDE.md](CLAUDE.md) and the `/apply` skill:
- Claude never opens your email, Google or Microsoft login pages, or your password manager.
- It never uses "Sign in with Google/LinkedIn" on job portals.
- It never enters your email password.
- It reads email only through the read-only Gmail API.
- It pauses for CAPTCHAs, verification codes and assessments.
- It answers questions only from your profile and asks you about anything else.
- It doesn't submit without your OK.

As a second layer, block these sites in the Claude in Chrome extension settings:
- `mail.google.com`
- `accounts.google.com`
- Outlook and Microsoft login pages
- your school's single sign-on page
- your password manager's web vault

**LinkedIn:** `/find-jobs` browses LinkedIn slowly in your own logged-in session. Automated browsing still goes against LinkedIn's terms and could get your account restricted. Use `/find-jobs --no-linkedin` to skip it.

## Dashboard and your token

The dashboard page holds no data. You unlock it with your data repo name and a [fine-grained token](https://github.com/settings/personal-access-tokens/new) set up like this:
- **Repository access:** only `<you>/job-data`
- **Repository permissions:** Contents set to Read and write

The dashboard refuses classic (`ghp_`) and GitHub CLI (`gho_`) tokens, because those can reach every repo you own. It also refuses to open a data repo that isn't private. GitHub doesn't let a web page see which repos a fine-grained token covers, so choosing **only `job-data`** on the token form is up to you. Never pick "All repositories".

The token is stored only in your browser's localStorage, and the **Lock** button clears it. The page's content security policy only lets it talk to `api.github.com`, and it loads no third-party scripts.

If you'd rather not paste a token into a hosted page, run `uv run jobs dashboard` to serve the same page on localhost.

## For the owner: the shared Gmail OAuth app (one time)

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project and enable the **Gmail API**.
2. Set up the **OAuth consent screen**:
   - User type: External
   - Publishing status: **Testing**
   - Scope: `.../auth/gmail.readonly`
   - Under **Test users**, add each friend's Gmail address (up to 100)
3. Under **Credentials**, create an OAuth client ID of type **Desktop app**, then download its JSON.
4. Send that JSON privately to each friend, who saves it as `secrets/gmail_client.json`. It never goes in git.

While the app is in Testing mode, logins expire after 7 days, so everyone runs `uv run jobs mail auth` again about once a week. Google Workspace accounts, such as school accounts, may block outside apps. If that happens, use a personal Gmail and forward recruiting mail to it.

## Development

```sh
uv run pytest
uv run jobs dashboard      # dashboard at http://localhost:8765
```

`src/jobapply/models.py` and `docs/jobs.js` share the `jobs.json` schema, so change them together.
