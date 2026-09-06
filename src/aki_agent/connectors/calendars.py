"""Calendars, read through the one door every service leaves open: ICS.

WHY ICS AND NOT THE GOOGLE CALENDAR API
---------------------------------------
Every calendar service -- Google, Outlook, iCloud, Fastmail, university and
work systems -- can publish a calendar as an ICS URL. It is a plain text file
over HTTPS. No OAuth application, no client secret, no developer account, and
therefore no broken promise.

The cost is honest and worth stating up front: **ICS is read-only.** This
connector can tell the user what is on today. It cannot create, move or cancel
anything. Writing needs the provider's API, which needs OAuth, which needs an
application to be registered.

A SECURITY NOTE THAT IS EASY TO MISS
------------------------------------
An ICS subscription URL is a *credential*. Anyone holding it can read the
calendar -- most services generate a long unguessable URL and treat possession
as authentication. So the URL goes into the OS credential store like any other
secret, and is never written into config, a log or a message.

The parser is deliberately small and written by hand rather than pulled in as
a dependency. ICS has corners this does not handle -- recurrence rules beyond
simple cases, timezone databases, attachments. What it does handle is "what is
on my calendar today", which is the question actually being asked, and it does
it with no dependency and no surprises.
"""

from __future__ import annotations

import datetime as _dt
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field as dataclass_field

from .. import secrets

SECRET_KEY_TEMPLATE = "calendar:{name}"

# A calendar file that is enormous is either a mistake or an attack. Ten
# megabytes is far more than any personal calendar and far less than anything
# that would hurt.
MAX_BYTES = 10 * 1024 * 1024
FETCH_TIMEOUT = 30


@dataclass
class Event:
    """One thing on the calendar."""

    summary: str
    start: _dt.datetime | None
    end: _dt.datetime | None = None
    location: str = ""
    all_day: bool = False
    description: str = ""

    def describe(self) -> str:
        """A line for a human. Redacted -- see the note below."""
        if self.all_day or self.start is None:
            when = "all day"
        else:
            when = self.start.strftime("%H:%M")
        line = f"{when}  {self.summary}"
        if self.location:
            line += f"  ({self.location})"
        # A meeting invitation is a place other people write text that this
        # assistant will read. Dial-in details and one-time codes end up in
        # calendar entries constantly.
        return secrets.redact(line)


@dataclass
class Calendar:
    """One subscribed calendar."""

    name: str
    # The URL is a secret and is NOT stored on this object. It lives in the
    # OS credential store, fetched only when needed.
    colour: str = ""

    @property
    def secret_key(self) -> str:
        return SECRET_KEY_TEMPLATE.format(name=self.name)

    def save_url(self, url: str) -> str:
        return secrets.set_secret(self.secret_key, url.strip())

    def url(self) -> str | None:
        return secrets.get_secret(self.secret_key)

    def forget(self) -> bool:
        return secrets.delete_secret(self.secret_key)


class CalendarError(Exception):
    """A calendar problem, phrased for a person."""


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch(calendar: Calendar) -> str:
    """Download the calendar. Returns the raw ICS text."""
    url = calendar.url()
    if not url:
        raise CalendarError(
            f"No address saved for the calendar '{calendar.name}'. "
            "Run /aki-agent:setup and add it again."
        )

    # webcal:// is what calendar apps hand out; it is https underneath.
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]

    if not url.startswith("https://"):
        raise CalendarError(
            "A calendar address must start with https:// or webcal://. "
            "An unencrypted one would expose the whole calendar to anyone on "
            "the same network."
        )

    request = urllib.request.Request(
        url, headers={"User-Agent": "aki-agent/0.1"})

    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
            raw = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise CalendarError(
                f"'{calendar.name}' refused the request. The subscription "
                "address may have been reset -- get a fresh one from your "
                "calendar's sharing settings."
            ) from exc
        raise CalendarError(
            f"'{calendar.name}' could not be fetched (error {exc.code})."
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise CalendarError(
            f"'{calendar.name}' could not be reached. If you are offline that "
            "is expected."
        ) from exc

    if len(raw) > MAX_BYTES:
        raise CalendarError(
            f"'{calendar.name}' is unexpectedly large and was not read.")

    return raw.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse(ics_text: str) -> list[Event]:
    """Turn ICS text into events.

    Handles the parts that matter for "what is on today": VEVENT blocks,
    SUMMARY, DTSTART, DTEND, LOCATION, all-day entries, and line folding.

    Does NOT handle: recurrence rules, timezone databases beyond UTC offsets,
    attachments, alarms. Those are real gaps. They are acceptable because the
    question being answered is a simple one, and because a wrong answer here
    would be a missed meeting -- so anything not understood is skipped rather
    than guessed at.
    """
    events: list[Event] = []
    current: dict[str, str] | None = None

    for line in _unfold(ics_text):
        stripped = line.strip()

        if stripped == "BEGIN:VEVENT":
            current = {}
            continue
        if stripped == "END:VEVENT":
            if current is not None:
                event = _build_event(current)
                if event is not None:
                    events.append(event)
            current = None
            continue
        if current is None:
            continue

        name, separator, value = stripped.partition(":")
        if not separator:
            continue
        # Strip parameters: DTSTART;TZID=Europe/London -> DTSTART, keeping
        # the parameter text so all-day detection can use VALUE=DATE.
        key, _, parameters = name.partition(";")
        current[key.upper()] = value
        if parameters:
            current[key.upper() + "_PARAMS"] = parameters

    events.sort(key=lambda event: (event.start is None,
                                   event.start or _dt.datetime.max))
    return events


def _unfold(text: str) -> list[str]:
    """Join ICS continuation lines.

    ICS wraps long lines by starting the continuation with a space or tab.
    Not handling this splits long meeting titles in half, which looks like
    corrupted data.
    """
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _build_event(fields: dict[str, str]) -> Event | None:
    summary = _unescape(fields.get("SUMMARY", "")).strip()
    if not summary:
        summary = "(no title)"

    raw_start = fields.get("DTSTART", "")
    all_day = "VALUE=DATE" in fields.get("DTSTART_PARAMS", "")

    start = _parse_time(raw_start)
    if start is None:
        return None          # unparseable: skip rather than guess

    return Event(
        summary=summary,
        start=start,
        end=_parse_time(fields.get("DTEND", "")),
        location=_unescape(fields.get("LOCATION", "")).strip(),
        all_day=all_day or len(raw_start) == 8,
        description=_unescape(fields.get("DESCRIPTION", "")).strip(),
    )


_TIME_PATTERNS = (
    ("%Y%m%dT%H%M%SZ", True),
    ("%Y%m%dT%H%M%S", False),
    ("%Y%m%d", False),
)


def _parse_time(value: str) -> _dt.datetime | None:
    value = value.strip()
    if not value:
        return None
    for pattern, is_utc in _TIME_PATTERNS:
        try:
            parsed = _dt.datetime.strptime(value, pattern)
        except ValueError:
            continue
        if is_utc:
            # Convert to local time, because "14:00 UTC" shown to somebody in
            # London in summer is an hour wrong and looks authoritative.
            parsed = parsed.replace(tzinfo=_dt.timezone.utc).astimezone()
            return parsed.replace(tzinfo=None)
        return parsed
    return None


def _unescape(value: str) -> str:
    """ICS escapes commas, semicolons and newlines."""
    return (value.replace("\\n", "\n").replace("\\N", "\n")
                 .replace("\\,", ",").replace("\\;", ";")
                 .replace("\\\\", "\\"))


# ---------------------------------------------------------------------------
# Questions people actually ask
# ---------------------------------------------------------------------------

def on_day(events: list[Event], day: _dt.date | None = None) -> list[Event]:
    day = day or _dt.date.today()
    return [event for event in events
            if event.start is not None and event.start.date() == day]


def between(events: list[Event], start: _dt.date,
            end: _dt.date) -> list[Event]:
    return [event for event in events
            if event.start is not None and start <= event.start.date() <= end]


def next_up(events: list[Event], now: _dt.datetime | None = None,
            count: int = 5) -> list[Event]:
    now = now or _dt.datetime.now()
    upcoming = [event for event in events
                if event.start is not None and event.start >= now]
    return upcoming[:count]


def how_to_get_the_address() -> str:
    """Instructions for a non-developer, per service."""
    return (
        "Every calendar can give you a private subscription address. Where to "
        "find it:\n"
        "\n"
        "  Google Calendar   Settings > your calendar > 'Secret address in "
        "iCal format'\n"
        "  Outlook.com       Settings > Calendar > Shared calendars > "
        "Publish, then take the ICS link\n"
        "  Apple / iCloud    Calendar app > right-click the calendar > Share "
        "Calendar > Public Calendar\n"
        "  Fastmail          Calendar settings > the calendar > 'Secret URL'\n"
        "\n"
        "Treat that address like a password. Anyone who has it can read the "
        "whole calendar, so it is stored in your computer's password manager "
        "rather than in a settings file.\n"
        "\n"
        "This is read-only: the assistant can tell you what is on, but cannot "
        "add, move or cancel anything."
    )
