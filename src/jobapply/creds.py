"""Job-portal accounts (Workday, iCIMS, ...). Each gets a unique generated password, never the user's own.

Passwords live in the OS keyring (Windows Credential Manager / macOS Keychain / Secret Service) by default.
On a headless agent box with no keyring, set JOBAPPLY_PASSWORD_STORE=file to keep them in
secrets/passwords.json (0600, outside the agent's workspace). secrets/accounts.json maps portal host ->
login email so a password can be looked up. There is deliberately no command that prints every password.
"""

import json
import os
import secrets
import string
from urllib.parse import urlsplit

import keyring
from keyring.errors import NoKeyringError

from . import paths

ACCOUNTS = paths.SECRETS / "accounts.json"
PASSWORDS = paths.SECRETS / "passwords.json"
SYMBOLS = "!@#$%^&*"  # accepted by every portal we've seen; some reject quotes/brackets
NO_KEYRING = ("No OS keyring is available. On a headless machine set JOBAPPLY_PASSWORD_STORE=file "
              "(passwords then go in a 0600 file in the secrets folder).")


def portal_host(domain_or_url: str) -> str:
    """Workday tenants (acme.wd5.myworkdayjobs.com) each need their own account, so key by full host."""
    s = domain_or_url.strip().lower()
    host = urlsplit(s if "://" in s else f"https://{s}").netloc
    return host.removeprefix("www.")


def _service(host: str) -> str:
    return f"jobapply:{host}"


def _read(path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _accounts() -> dict[str, str]:
    return _read(ACCOUNTS)


def _file_store() -> bool:
    return os.environ.get("JOBAPPLY_PASSWORD_STORE", "keyring").lower() == "file"


def _save_password(host: str, email: str, pw: str) -> None:
    if _file_store():
        pws = _read(PASSWORDS)
        pws[host] = pw
        paths.write_secret(PASSWORDS, json.dumps(pws, indent=2, sort_keys=True))
        return
    try:
        keyring.set_password(_service(host), email, pw)
    except NoKeyringError:
        raise SystemExit(NO_KEYRING)


def _load_password(host: str, email: str) -> str | None:
    if _file_store():
        return _read(PASSWORDS).get(host)
    try:
        return keyring.get_password(_service(host), email)
    except NoKeyringError:
        raise SystemExit(NO_KEYRING)


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
    _save_password(host, email, pw)
    accounts[host] = email
    paths.write_secret(ACCOUNTS, json.dumps(accounts, indent=2, sort_keys=True))
    return host, pw


def get(domain_or_url: str) -> tuple[str, str, str] | None:
    host = portal_host(domain_or_url)
    email = _accounts().get(host)
    if not email:
        return None
    pw = _load_password(host, email)
    return (host, email, pw) if pw else None


def list_hosts() -> dict[str, str]:
    return _accounts()
