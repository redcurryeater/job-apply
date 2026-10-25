"""Job-portal accounts (Workday, iCIMS, ...). Passwords live only in the OS keyring
(Windows Credential Manager / macOS Keychain), never in files or the user's password manager.
secrets/accounts.json maps portal host -> login email so a password can be looked up."""

import json
import secrets
import string
from urllib.parse import urlsplit

import keyring

from . import paths

ACCOUNTS = paths.SECRETS / "accounts.json"
SYMBOLS = "!@#$%^&*"  # accepted by every portal we've seen; some reject quotes/brackets


def portal_host(domain_or_url: str) -> str:
    """Workday tenants (acme.wd5.myworkdayjobs.com) each need their own account, so key by full host."""
    s = domain_or_url.strip().lower()
    host = urlsplit(s if "://" in s else f"https://{s}").netloc
    return host.removeprefix("www.")


def _service(host: str) -> str:
    return f"jobapply:{host}"


def _accounts() -> dict[str, str]:
    return json.loads(ACCOUNTS.read_text(encoding="utf-8")) if ACCOUNTS.exists() else {}


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
    keyring.set_password(_service(host), email, pw)
    accounts[host] = email
    paths.SECRETS.mkdir(exist_ok=True)
    ACCOUNTS.write_text(json.dumps(accounts, indent=2, sort_keys=True), encoding="utf-8")
    return host, pw


def get(domain_or_url: str) -> tuple[str, str, str] | None:
    host = portal_host(domain_or_url)
    email = _accounts().get(host)
    if not email:
        return None
    pw = keyring.get_password(_service(host), email)
    return (host, email, pw) if pw else None


def list_hosts() -> dict[str, str]:
    return _accounts()
