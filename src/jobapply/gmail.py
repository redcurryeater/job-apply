"""Read-only Gmail access: recruiting-mail scan and sign-up verification links.

Uses the gmail.readonly scope only — this code can never send, delete or change mail.
secrets/gmail_client.json is the shared OAuth desktop client; secrets/gmail_token.json is
this user's token. While the Google app is in "testing" mode the token lasts 7 days.
"""

import base64
import re
from datetime import datetime, timedelta, timezone
from html import unescape

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from . import paths

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CLIENT_FILE = paths.SECRETS / "gmail_client.json"
TOKEN_FILE = paths.SECRETS / "gmail_token.json"

REAUTH = ("Gmail login expired or missing. Run `jobs mail auth` (headless box: `jobs mail auth --no-browser "
          "--port 8765` over `ssh -L 8765:localhost:8765`); re-consent is needed every 7 days.")

ATS_SENDERS = ["greenhouse.io", "greenhouse-mail.io", "lever.co", "hire.lever.co", "ashbyhq.com", "myworkday.com",
               "myworkdayjobs.com", "workday.com", "icims.com", "taleo.net", "smartrecruiters.com", "jobvite.com",
               "successfactors.com", "eightfold.ai", "hackerrank.com", "codesignal.com", "hirevue.com", "gem.com",
               "rippling.com", "bamboohr.com", "workablemail.com", "oraclecloud.com", "linkedin.com"]
SUBJECT_TERMS = ["application", "applying", "interview", "assessment", "coding challenge", "next steps",
                 "unfortunately", "offer", "your candidacy", "thank you for your interest", "recruiting",
                 "online assessment", "schedule", "position"]


def auth(port: int = 0, open_browser: bool = True) -> str:
    """Consent in a browser. On a headless box pass a fixed port and open_browser=False, forward the port over
    SSH (`ssh -L <port>:localhost:<port> ...`) and open the printed URL in your own browser."""
    if not CLIENT_FILE.exists():
        raise SystemExit(f"Missing {CLIENT_FILE}. Ask the project owner for gmail_client.json.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
    creds = flow.run_local_server(port=port, open_browser=open_browser, prompt="consent")
    paths.write_secret(TOKEN_FILE, creds.to_json())
    profile = build("gmail", "v1", credentials=creds).users().getProfile(userId="me").execute()
    return profile["emailAddress"]


def service():
    if not TOKEN_FILE.exists():
        raise SystemExit(REAUTH)
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError:
            raise SystemExit(REAUTH)
        paths.write_secret(TOKEN_FILE, creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _headers(msg: dict) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}


def _bodies(part: dict) -> tuple[str, str]:
    """(plain, html) text of a message payload."""
    plain, html = "", ""
    data = part.get("body", {}).get("data")
    if data:
        text = base64.urlsafe_b64decode(data + "===").decode("utf-8", "replace")
        if part.get("mimeType") == "text/plain":
            plain += text
        elif part.get("mimeType") == "text/html":
            html += text
    for p in part.get("parts", []) or []:
        a, b = _bodies(p)
        plain, html = plain + a, html + b
    return plain, html


def _text(msg: dict) -> str:
    plain, html = _bodies(msg.get("payload", {}))
    if plain.strip():
        return plain
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html)))


def _list(svc, query: str, limit: int) -> list[str]:
    ids, token = [], None
    while len(ids) < limit:
        r = svc.users().messages().list(userId="me", q=query, maxResults=min(100, limit - len(ids)),
                                        pageToken=token).execute()
        ids += [m["id"] for m in r.get("messages", [])]
        token = r.get("nextPageToken")
        if not token:
            break
    return ids


def scan(since: datetime, skip_ids: set[str] = frozenset(), limit: int = 200, body_chars: int = 1500) -> list[dict]:
    """Recruiting-looking mail received after `since`, newest first, minus already-processed ids."""
    svc = service()
    senders = " OR ".join(f"from:{d}" for d in ATS_SENDERS)
    subjects = " OR ".join(f'subject:"{t}"' for t in SUBJECT_TERMS)
    query = f"after:{int(since.timestamp())} ({senders} OR {subjects}) -in:sent -in:chats -category:promotions"
    out = []
    for mid in _list(svc, query, limit):
        if mid in skip_ids:
            continue
        msg = svc.users().messages().get(userId="me", id=mid, format="full").execute()
        h = _headers(msg)
        out.append({
            "email_id": mid,
            "date": datetime.fromtimestamp(int(msg["internalDate"]) / 1000, timezone.utc).isoformat(),
            "from": h.get("from", ""),
            "subject": h.get("subject", ""),
            "snippet": unescape(msg.get("snippet", "")),
            "body": re.sub(r"\s+", " ", _text(msg))[:body_chars],
        })
    return out


LINK_RE = re.compile(r"https?://[^\s\"'<>)\]]+")
VERIFY_WORDS = ("verify", "verification", "confirm", "activate", "activation", "validate", "registration")


def _registrable(host: str) -> str:
    """acme.wd5.myworkdayjobs.com -> acme ; boards.greenhouse.io -> greenhouse"""
    parts = host.lower().removeprefix("www.").split(".")
    return parts[0] if "myworkday" in host else (parts[-2] if len(parts) >= 2 else host)


def verify_link(domain: str, minutes: int = 15) -> dict | None:
    """Most recent account-verification link related to `domain` received in the last `minutes`."""
    svc = service()
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    words = " OR ".join(VERIFY_WORDS)
    query = f"after:{int(since.timestamp())} ({words})"
    key = _registrable(domain)
    for mid in _list(svc, query, 20):
        msg = svc.users().messages().get(userId="me", id=mid, format="full").execute()
        h = _headers(msg)
        plain, html = _bodies(msg.get("payload", {}))
        links = [unescape(l).rstrip(".,;") for l in LINK_RE.findall(plain + " " + html)]
        verify = [l for l in links if any(w in l.lower() for w in VERIFY_WORDS) or "token" in l.lower()]
        related = key in (h.get("from", "") + " " + " ".join(verify)).lower()
        if verify and related:
            best = next((l for l in verify if key in l.lower()), verify[0])
            return {"email_id": mid, "from": h.get("from", ""), "subject": h.get("subject", ""), "link": best}
    return None
