"""Job-portal accounts (Workday, iCIMS, ...). Each gets a unique generated password, never the user's own.

Passwords live in secrets/passwords.json (0600; on the agent box the secrets folder sits outside the agent's
workspace, see JOBAPPLY_SECRETS). secrets/accounts.json maps portal host -> login email.
There is deliberately no command that prints every password.
"""

import json
import secrets
import string
from urllib.parse import urlsplit

from . import paths

ACCOUNTS = paths.SECRETS / "accounts.json"
PASSWORDS = paths.SECRETS / "passwords.json"
SYMBOLS = "!@#$%^&*"  # accepted by every portal we've seen; some reject quotes/brackets


def portal_host(domain_or_url: str) -> str:
    """Workday tenants (acme.wd5.myworkdayjobs.com) each need their own account, so key by full host."""
    s = domain_or_url.strip().lower()
    host = urlsplit(s if "://" in s else f"https://{s}").netloc
    return host.removeprefix("www.")


def _read(path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _accounts() -> dict[str, str]:
    return _read(ACCOUNTS)


def generate_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + SYMBOLS
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw) and any(c in SYMBOLS for c in pw)):
            return pw


def new(domain_or_url: str, email: str, overwrite: bool = False) -> tuple[str, str]:
    host = portal_host(domain_or_url)
    accounts = _accounts()
    if host in accounts and not overwrite:
        raise SystemExit(f"An account for {host} already exists; use `jobs creds get {host}` "
                         "(or --overwrite after resetting the password on the site).")
    pw = generate_password()
    pws = _read(PASSWORDS)
    pws[host] = pw
    paths.write_secret(PASSWORDS, json.dumps(pws, indent=2, sort_keys=True))
    accounts[host] = email
    paths.write_secret(ACCOUNTS, json.dumps(accounts, indent=2, sort_keys=True))
    return host, pw


def get(domain_or_url: str) -> tuple[str, str, str] | None:
    host = portal_host(domain_or_url)
    email = _accounts().get(host)
    pw = _read(PASSWORDS).get(host) if email else None
    return (host, email, pw) if pw else None


def list_hosts() -> dict[str, str]:
    return _accounts()
