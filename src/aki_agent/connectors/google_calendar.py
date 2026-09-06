"""Writing to a Google Calendar — adding, moving and cancelling.

WHY THIS EXISTS AND WHY IT IS SEPARATE (reported 2026-08-20)
----------------------------------------------------------
*"要呀,要有 option 可以寫"*.

The subscription this package already supports cannot do it, and not because
nobody implemented it: **an ICS subscription address is a file to download.**
There is no "write" in that protocol at all. Wanting to add an appointment is
wanting a different connection, not a better use of the one that is there.

For Google there is exactly one route: sign in with the person's own Google
account. That is a bigger ask than pasting an address — it needs a Google
Cloud project, which takes about ten minutes once — so it is offered
**alongside** the read-only subscription rather than replacing it:

    subscription (ICS)      two minutes, reads only
    Google account (OAuth)  a one-off setup, reads and writes

Most people want the first. Somebody who wants their assistant to book things
needs the second, and should be told plainly what it costs.

WHAT IS ASKED FOR, AND WHAT IS NOT
----------------------------------
One scope: `calendar.events`. That is permission to read and change events —
**not** to create or delete whole calendars, and not to touch anything else in
the account. It is the narrowest scope that can do the job, which is the only
defensible choice when the thing being handed over is somebody's real diary.

NO THIRD-PARTY LIBRARY
----------------------
Google publish a client library. This does not use it: OAuth and four REST
calls are a few dozen lines of `urllib`, against several megabytes of
dependency that would have to be installed, pinned, and kept current on a
machine belonging to somebody who did not ask for any of it.

WHERE THE SECRETS LIVE
----------------------
Client id, Client secret and the refresh token all go to the OS credential
store, never to the config file. The refresh token is the one that matters:
it stands in for the person's Google sign-in until it is revoked, and it is
revocable from their own Google account page — which the dashboard says,
because somebody handing over that much needs to know how to take it back.
"""

from __future__ import annotations

import datetime as _dt
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from . import calendars as ics
from . import google_account
from .. import secrets  # noqa: F401  (kept: callers import it from here)

# The sign-in itself now lives in `google_account`, which several services
# share. Nothing about the calendar
# connection changed: same scope, same credential-store keys, same flow. What
# changed is that Gmail can use it too instead of a second copy.
#
# These names stay because other modules and the dashboard import them from
# here, and moving a name is a rename wearing a refactor's clothes.
GoogleError = google_account.GoogleError
AUTH_URL = google_account.AUTH_URL
TOKEN_URL = google_account.TOKEN_URL
REVOKE_HELP = google_account.REVOKE_HELP
REDIRECT_PATH = google_account.REDIRECT_PATH
SERVICE = google_account.CALENDAR
SCOPE = SERVICE.scope
KEY_CLIENT_ID = google_account.KEY_CLIENT_ID
KEY_CLIENT_SECRET = google_account.KEY_CLIENT_SECRET
KEY_REFRESH = SERVICE.refresh_key

API_ROOT = "https://www.googleapis.com/calendar/v3"


# ---------------------------------------------------------------------------
# Credentials and the sign-in, all of it delegated
# ---------------------------------------------------------------------------

save_client = google_account.save_client
app_credentials = google_account.app_credentials


def connected() -> bool:
    return google_account.connected(SERVICE)


def disconnect() -> tuple[bool, str]:
    return google_account.disconnect(SERVICE)


def forget_everything() -> None:
    """Every Google secret on this machine, not only the calendar's.

    Unchanged in effect: this always removed the shared client id and secret,
    which were never the calendar's alone.
    """
    google_account.forget_everything()


def start(redirect_uri: str) -> tuple[str, str]:
    return google_account.start(SERVICE, redirect_uri)


def finish(code: str, state: str, redirect_uri: str) -> tuple[bool, str]:
    """Two values, because that is what this module has always returned."""
    ok, message, _service = google_account.finish(code, state, redirect_uri)
    return ok, message


def _access_token() -> str:
    return google_account.access_token(SERVICE)


def _call(method: str, path: str, payload: dict | None = None,
          params: dict | None = None) -> dict:
    url = API_ROOT + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {_access_token()}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    return _send(request)


def _send(request) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            body = json.loads(exc.read().decode("utf-8"))
            detail = ((body.get("error") or {}).get("message")
                      or body.get("error_description") or "")
        except Exception:                                 # noqa: BLE001
            pass
        raise GoogleError(detail or f"Google refused that ({exc.code}).")
    except urllib.error.URLError as exc:
        raise GoogleError(f"Could not reach Google ({exc.reason}).")


# ---------------------------------------------------------------------------
# The four things anybody actually wants
# ---------------------------------------------------------------------------

@dataclass
class Booking:
    """One event, in the terms the rest of this package speaks."""

    event_id: str
    summary: str
    start: _dt.datetime | None
    end: _dt.datetime | None = None
    location: str = ""
    all_day: bool = False
    link: str = ""


def _when(value: dict | None) -> tuple[_dt.datetime | None, bool]:
    if not value:
        return None, False
    if value.get("date"):
        try:
            day = _dt.date.fromisoformat(value["date"])
        except ValueError:
            return None, True
        return _dt.datetime.combine(day, _dt.time()), True
    stamp = value.get("dateTime")
    if not stamp:
        return None, False
    try:
        return _dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")), False
    except ValueError:
        return None, False


def _as_booking(raw: dict) -> Booking:
    start, all_day = _when(raw.get("start"))
    end, _ = _when(raw.get("end"))
    return Booking(
        event_id=str(raw.get("id", "")),
        # Redacted for the same reason the ICS side redacts: an invitation is
        # somewhere other people write text this assistant will read, and
        # dial-in codes live in them constantly.
        summary=secrets.redact(str(raw.get("summary", "")) or "(no title)"),
        start=start, end=end, all_day=all_day,
        location=secrets.redact(str(raw.get("location", "") or "")),
        link=str(raw.get("htmlLink", "")),
    )


def upcoming(calendar_id: str = "primary", days: int = 7,
             limit: int = 25) -> list[Booking]:
    now = _dt.datetime.now(_dt.timezone.utc)
    found = _call("GET", f"/calendars/{urllib.parse.quote(calendar_id)}/events",
                  params={
                      "timeMin": now.isoformat().replace("+00:00", "Z"),
                      "timeMax": (now + _dt.timedelta(days=days)).isoformat()
                                 .replace("+00:00", "Z"),
                      "singleEvents": "true",
                      "orderBy": "startTime",
                      "maxResults": str(limit),
                  })
    return [_as_booking(one) for one in (found.get("items") or [])]


def add(summary: str, start: _dt.datetime, end: _dt.datetime | None = None,
        location: str = "", description: str = "",
        calendar_id: str = "primary",
        confirmed: bool = False) -> tuple[bool, str]:
    """Put something in the diary.

    `confirmed` is not decoration. This writes to a real calendar that real
    people are invited from, and the same rule the mail connector follows
    applies: the person says yes to *this* action, not to a standing
    permission granted once during setup.
    """
    if not confirmed:
        return False, "Not confirmed, so nothing was added."
    if not summary.strip():
        return False, "An event needs a title."

    end = end or (start + _dt.timedelta(hours=1))
    if end <= start:
        return False, "The end is not after the start."

    try:
        made = _call("POST",
                     f"/calendars/{urllib.parse.quote(calendar_id)}/events",
                     payload={
                         "summary": summary.strip(),
                         "location": location.strip() or None,
                         "description": description.strip() or None,
                         "start": {"dateTime": start.isoformat()},
                         "end": {"dateTime": end.isoformat()},
                     })
    except GoogleError as exc:
        return False, str(exc)
    return True, f"Added — {made.get('htmlLink', summary)}"


def change(event_id: str, calendar_id: str = "primary",
           summary: str | None = None, start: _dt.datetime | None = None,
           end: _dt.datetime | None = None, location: str | None = None,
           confirmed: bool = False) -> tuple[bool, str]:
    """Move or retitle something already in the diary.

    A patch rather than a replacement: everything not named here is left as it
    is. Rewriting a whole event to change its time would silently drop the
    guest list, and an assistant that uninvites somebody while moving a
    meeting is worse than one that cannot move meetings.
    """
    if not confirmed:
        return False, "Not confirmed, so nothing was changed."
    if not event_id:
        return False, "Which event? An id is needed."

    patch: dict[str, Any] = {}
    if summary is not None:
        patch["summary"] = summary.strip()
    if location is not None:
        patch["location"] = location.strip()
    if start is not None:
        patch["start"] = {"dateTime": start.isoformat()}
    if end is not None:
        patch["end"] = {"dateTime": end.isoformat()}
    if not patch:
        return False, "Nothing was asked to change."

    try:
        _call("PATCH",
              f"/calendars/{urllib.parse.quote(calendar_id)}"
              f"/events/{urllib.parse.quote(event_id)}", payload=patch)
    except GoogleError as exc:
        return False, str(exc)
    return True, "Changed."


def cancel(event_id: str, calendar_id: str = "primary",
           confirmed: bool = False) -> tuple[bool, str]:
    """Take something out of the diary.

    The one operation here with no undo, so it insists on the same explicit
    yes as the others and says plainly what it did: cancelling notifies the
    other guests, which is not obvious from the word "delete".
    """
    if not confirmed:
        return False, "Not confirmed, so nothing was cancelled."
    if not event_id:
        return False, "Which event? An id is needed."

    try:
        _call("DELETE",
              f"/calendars/{urllib.parse.quote(calendar_id)}"
              f"/events/{urllib.parse.quote(event_id)}")
    except GoogleError as exc:
        return False, str(exc)
    return True, ("Cancelled. Anyone invited to it has been told by Google.")


# ---------------------------------------------------------------------------
# Saying what this is, to somebody deciding whether to set it up
# ---------------------------------------------------------------------------

def how_to_set_up() -> str:
    return (
        "Reading a calendar needs only a subscription address. Changing one "
        "means signing in with your Google account, and Google only allows "
        "that through a project of your own. Once, about ten minutes:\n"
        "\n"
        "  1. Go to console.cloud.google.com and make a project — any name.\n"
        "  2. In that project, enable the Google Calendar API.\n"
        "  3. Under 'APIs & Services' > 'Credentials', create an OAuth "
        "Client ID, and choose Desktop app as the type.\n"
        "  4. Copy the Client ID and Client secret it shows you, and paste "
        "them below.\n"
        "  5. Press Connect. Google asks whether to allow it; that question "
        "is about your own project, so it will warn you it is unverified — "
        "you are the publisher.\n"
        "\n"
        "The assistant is asking for one permission: read and change events. "
        "Not to create or delete calendars, and nothing outside Calendar.\n"
        "\n"
        "You can withdraw it at any time at " + REVOKE_HELP + ", and "
        "disconnecting here deletes the sign-in from this computer."
    )


def read_only_alternative() -> str:
    """For the person who does not need any of the above."""
    return (
        "If you only want to be told what is on, use a subscription address "
        "instead — it takes two minutes and needs no account. "
        + ics.how_to_get_the_address()
    )
