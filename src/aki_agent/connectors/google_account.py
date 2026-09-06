"""One Google account, several powers, granted one at a time.

WHY THIS FILE EXISTS
--------------------

Calendar was first because it was the only one that could not be done any
other way: reading a calendar needs nothing but a subscription address, but
*adding* an event needs the API, which needs OAuth. Everything the sign-in
needed -- PKCE, the refresh token, the token store, the callback -- was
written inside `google_calendar.py`, where nothing else could reach it.

So this module is that machinery lifted out, and nothing more. It is not a
rewrite: `google_calendar`'s public functions are unchanged and now call in
here, which is the same move `channels.py` made when the seams went in.

ONE SIGN-IN PER POWER, NOT ONE FOR ALL OF THEM
----------------------------------------------
The obvious design is a single "Connect Google" button asking for every scope
at once. It is rejected here for the reason the calendar scope is
`calendar.events` rather than `calendar`: a person turning on their diary
should not thereby hand over their mail.

Each service has its own scope and its own refresh token, and connecting one
neither implies nor enables the others. Disconnecting one leaves the others
alone. The client id and secret ARE shared, because those identify the
application, not the permission.

WHY THE SHARED KEYS ARE STILL NAMED `google_calendar_*`
--------------------------------------------------------
They were saved under those names by every copy already installed, and this
package's credential store is the operating system's, not a file we control.
Renaming them would silently lose the client somebody already registered and
send them back to the Google Cloud console for no reason. A name that is
merely historical costs a comment; a rename costs the user an evening.
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets as _stdlib_secrets
import urllib.parse
from dataclasses import dataclass

from .. import secrets

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_HELP = "https://myaccount.google.com/permissions"

# The application's identity, shared by every service below. See the module
# docstring for why these two are named after the first thing that used them.
KEY_CLIENT_ID = "google_calendar_client_id"
KEY_CLIENT_SECRET = "google_calendar_client_secret"

# The dashboard hosts the redirect. A Google "Desktop app" client accepts any
# loopback port, so there is nothing to register and nothing to keep in step.
REDIRECT_PATH = "/connections/google/callback"


class GoogleError(Exception):
    """A Google problem, phrased for a person rather than for a log."""


@dataclass(frozen=True)
class Service:
    """One power, one scope, one token.

    `identifies` asks Google, alongside the real scope, which account is
    signing in. Gmail needs it: a refresh token is granted for one mailbox,
    and a token belonging to somebody's other address would fail at login
    with an error naming neither address. Calendar does not -- it acts on
    "the account", and there is no second thing it could be confused with.
    """

    key: str
    label: str
    scope: str
    refresh_key: str
    done: str
    identifies: bool = False

    @property
    def address_key(self) -> str:
        return f"google_{self.key}_address"


CALENDAR = Service(
    key="calendar",
    label="Google Calendar",
    # Read and change events. Not "manage calendars", not "everything in your
    # account". The narrowest scope that can do what was asked.
    scope="https://www.googleapis.com/auth/calendar.events",
    refresh_key="google_calendar_refresh_token",
    done="Connected. Your assistant can now read and change events.",
)

GMAIL = Service(
    key="gmail",
    label="Gmail",
    # IMAP and SMTP over OAuth need this one scope, and Google offers no
    # narrower one that they accept. It is worth being plain about what it
    # means, which the guide is: full access to that mailbox.
    #
    # The alternative was the Gmail API's own scopes -- but reading would
    # still be `gmail.readonly`, which Google also classes as restricted, and
    # taking it would mean a second implementation of everything mail.py
    # already does over IMAP. Same permission, more code, more to be wrong.
    scope="https://mail.google.com/ openid email",
    refresh_key="google_gmail_refresh_token",
    done="Connected. That mailbox now signs in with Google, not a password.",
    identifies=True,
)

DRIVE = Service(
    key="drive",
    label="Google Drive",
    # Read only. This connection exists to reach what the synced folder
    # cannot -- files that live only in the cloud, and search across the whole
    # drive -- and nothing about that needs permission to change anything.
    #
    # Google offers no narrower read: `drive.file` sees only files this app
    # itself created, which is none of them, and `drive.metadata.readonly`
    # cannot open a document. So this asks for the narrowest scope that can
    # answer the question, and the guide says plainly what it covers.
    scope="https://www.googleapis.com/auth/drive.readonly",
    refresh_key="google_drive_refresh_token",
    done="Connected. Your assistant can now search and read your Drive.",
)

SERVICES = {one.key: one for one in (CALENDAR, GMAIL, DRIVE)}


def service(key: str) -> Service:
    found = SERVICES.get((key or "").strip())
    if found is None:
        raise GoogleError(f"There is no Google connection called {key!r}.")
    return found


# ---------------------------------------------------------------------------
# The application's own credentials
# ---------------------------------------------------------------------------

def save_client(client_id: str, client_secret: str) -> tuple[bool, str]:
    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    if not client_id or not client_secret:
        return False, "Both the Client ID and the Client secret are needed."
    if not client_id.endswith(".apps.googleusercontent.com"):
        # Not a security check -- a typo check. Pasting the project number
        # instead of the Client ID is the usual mistake and produces an
        # unhelpful error from Google an hour later.
        return False, ("That does not look like a Client ID — it should end "
                       "in .apps.googleusercontent.com")
    secrets.set_secret(KEY_CLIENT_ID, client_id)
    secrets.set_secret(KEY_CLIENT_SECRET, client_secret)
    return True, "Saved. Now press Connect to sign in to Google."


def app_credentials() -> tuple[str | None, str | None]:
    return (secrets.get_secret(KEY_CLIENT_ID),
            secrets.get_secret(KEY_CLIENT_SECRET))


def connected(one: Service) -> bool:
    return bool(secrets.get_secret(one.refresh_key))


def account_address(one: Service) -> str:
    """Which account this connection was granted by, if it says so."""
    return secrets.get_secret(one.address_key) or ""


def disconnect(one: Service) -> tuple[bool, str]:
    """Forget the token here. Says what that does and does not do.

    Deleting the refresh token stops this machine using the account. It does
    **not** withdraw the permission at Google's end, and telling somebody they
    are disconnected when a token could still be reissued would be the same
    half-truth as removing a mailbox row and keeping its password.
    """
    had = secrets.delete_secret(one.refresh_key)
    secrets.delete_secret(one.address_key)
    if not had:
        return False, "There was nothing signed in."
    return True, ("Signed out on this computer. To withdraw the permission at "
                  f"Google as well, remove it at {REVOKE_HELP}")


def forget_everything() -> None:
    """Every token, and the client itself. Used when starting over."""
    for one in SERVICES.values():
        secrets.delete_secret(one.refresh_key)
        secrets.delete_secret(one.address_key)
    secrets.delete_secret(KEY_CLIENT_ID)
    secrets.delete_secret(KEY_CLIENT_SECRET)


# ---------------------------------------------------------------------------
# The sign-in
# ---------------------------------------------------------------------------

# One flow at a time, in memory only. The verifier is worthless once used and
# must never reach disk. The service is remembered beside it so that the one
# callback route can tell what it is finishing -- the alternative, putting it
# in the redirect URI, would mean registering a URI per service.
_PENDING: dict[str, tuple[str, str]] = {}


def _random(length: int = 48) -> str:
    return base64.urlsafe_b64encode(
        _stdlib_secrets.token_bytes(length)).decode("ascii").rstrip("=")


def start(one: Service, redirect_uri: str) -> tuple[str, str]:
    """The URL to send the browser to, and the `state` that must come back.

    PKCE, which for a desktop client is what stops a code intercepted on the
    way back from being worth anything to whoever intercepted it. The verifier
    stays in this process and is never written down.
    """
    import hashlib

    client_id, _ = app_credentials()
    if not client_id:
        raise GoogleError("No Google Client ID saved yet.")

    verifier = _random()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    state = _random(16)
    _PENDING.clear()
    _PENDING[state] = (verifier, one.key)

    query = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": one.scope,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # Without both of these Google returns no refresh token on a second
        # authorisation, and the connection silently lasts one hour.
        "access_type": "offline",
        "prompt": "consent",
    })
    return f"{AUTH_URL}?{query}", state


def finish(code: str, state: str,
           redirect_uri: str) -> tuple[bool, str, Service | None]:
    """Swap the code for tokens. Called by the dashboard's callback route.

    Returns the service as well, so the page can send somebody back to the
    tab they pressed the button on.
    """
    pending = _PENDING.pop(state, None)
    if pending is None:
        return False, ("That sign-in did not start here, so it was refused. "
                       "Press Connect again."), None
    verifier, key = pending
    one = service(key)

    client_id, client_secret = app_credentials()
    if not client_id or not client_secret:
        return False, "The Google Client ID and secret are no longer saved.", one

    try:
        answer = post(TOKEN_URL, {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        })
    except GoogleError as exc:
        return False, str(exc), one

    refresh = answer.get("refresh_token")
    if not refresh:
        # Almost always a re-authorisation without `prompt=consent`. Say the
        # cause rather than "something went wrong".
        return False, ("Google did not send a lasting token. Remove this app "
                       f"at {REVOKE_HELP} and connect again."), one

    secrets.set_secret(one.refresh_key, refresh)

    done = one.done
    if one.identifies:
        address = _address_in(answer.get("id_token"))
        if address:
            secrets.set_secret(one.address_key, address)
            done = f"{done.rstrip('.')} Signed in as {address}."
    return True, done, one


def _address_in(id_token) -> str:
    """The email inside Google's id_token, or "" if there is not one.

    Read, not verified: this token was handed back by Google's own token
    endpoint over TLS in response to a code we generated, so there is no
    third party in the exchange whose signature there would be anything to
    check. It is also used for one thing only -- knowing which mailbox the
    refresh token belongs to -- and a wrong answer fails visibly at the next
    login rather than granting anything.
    """
    if not isinstance(id_token, str) or id_token.count(".") != 2:
        return ""
    body = id_token.split(".")[1]
    body += "=" * (-len(body) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(body))
    except (ValueError, binascii.Error):
        return ""
    address = claims.get("email")
    return address.strip() if isinstance(address, str) else ""


def access_token(one: Service) -> str:
    """A fresh access token, bought with the stored refresh token."""
    refresh = secrets.get_secret(one.refresh_key)
    if not refresh:
        raise GoogleError(f"Not signed in to {one.label} yet.")
    client_id, client_secret = app_credentials()
    if not client_id or not client_secret:
        raise GoogleError("The Google Client ID and secret are missing.")

    answer = post(TOKEN_URL, {
        "refresh_token": refresh,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
    })
    token = answer.get("access_token")
    if not token:
        raise GoogleError("Google would not renew the sign-in. Connect again.")
    return str(token)


# ---------------------------------------------------------------------------
# Talking to Google
# ---------------------------------------------------------------------------

def post(url: str, fields: dict) -> dict:
    import urllib.request

    body = urllib.parse.urlencode(fields).encode("ascii")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    return send(request)


def send(request) -> dict:
    """One request, with Google's own error text kept when it gives one."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(request, timeout=20) as answer:
            raw = answer.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            problem = json.loads(exc.read().decode("utf-8"))
            detail = (problem.get("error", {}).get("message")
                      or problem.get("error_description")
                      or problem.get("error") or "")
        except Exception:                                 # noqa: BLE001
            detail = ""
        raise GoogleError(
            f"Google refused that ({exc.code}). {detail}".strip()) from exc
    except OSError as exc:
        raise GoogleError(f"Could not reach Google. ({exc})") from exc

    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise GoogleError("Google sent something this could not read.") from exc
