"""One calendar, however many places it actually lives.

WHY THIS EXISTS (reported 2026-08-26)
-----------------------------------
`aki calendar-add` imported `google_calendar` directly. So "put it in the
diary" silently meant "put it in Google" -- on a machine with an iCloud
subscription connected and no Google account, the command reached for a
service that was not there and failed in the importer's words rather than the
user's.

The agenda command had the other half of the same problem written out by hand:
it asked Google first, printed "(can be changed)" beside those entries, then
read the ICS feeds, because a list that mixes a read-only subscription with a
writable calendar and says nothing invites "move that one to Thursday" against
something that cannot be moved.

That distinction is real and it belongs here, once, rather than in every
command that touches a diary.

WHAT A PROVIDER PROMISES
------------------------
A provider says what it can do and is asked before it is used. Reading is the
floor -- a calendar nobody can read is not a calendar. Writing is declared,
never assumed: `capabilities()` contains `"write"` or it does not, and a
caller that wants to add something asks `writer()` for one that does instead
of picking a module by name.

This is the point of the seam. Adding a CalDAV provider for iCloud is a class
in this file and a name in the defaults. No command changes, and the day a
provider that can write appears, `calendar-add` starts working without being
told.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Protocol

from . import seams


# ---------------------------------------------------------------------------
# What every provider returns
# ---------------------------------------------------------------------------

@dataclass
class Entry:
    """One thing on a calendar, in the terms the rest of the package speaks.

    A superset of what the two existing connectors return, rather than a
    lowest common denominator. `ref` and `link` stay empty for a subscription
    feed -- an ICS event has no address to change it by -- and that emptiness
    is exactly the fact a caller needs, so flattening it away would throw the
    useful part out.
    """

    summary: str
    start: _dt.datetime | None = None
    end: _dt.datetime | None = None
    location: str = ""
    all_day: bool = False
    description: str = ""
    # Which provider it came from, and which named feed within it. `source`
    # is what a listing labels a group with.
    source: str = ""
    # The provider's own handle for this entry, empty when it has none.
    ref: str = ""
    link: str = ""
    changeable: bool = False

    def when(self) -> str:
        """The time, as a person reads it. Empty when there is no time."""
        if self.start is None:
            return ""
        if self.all_day:
            return self.start.strftime("%a %d %b") + "  all day"
        return self.start.strftime("%a %d %b %H:%M")

    def describe(self) -> str:
        """One line, redacted.

        Redaction is not optional here. A meeting invitation is a place other
        people write text that this assistant will read, and dial-in details
        and one-time codes end up in calendar entries constantly. The existing
        ICS connector redacts at exactly this boundary; doing it here means a
        provider that forgets cannot leak through.
        """
        from . import secrets

        line = f"{self.when()}  {self.summary}".strip()
        if self.location:
            line += f"  ({self.location})"
        return secrets.redact(line)


class CalendarProvider(Protocol):
    """What a calendar has to provide.

    `read` returns what it found *and* what went wrong, rather than raising,
    because one unreachable feed must not hide the other three. Printing is
    the caller's business -- a provider that prints cannot be used by the
    dashboard.
    """

    name: str

    def available(self, config=None) -> tuple[bool, str]:
        """Usable right now? If not, the reason, in the user's words."""

    def capabilities(self) -> frozenset[str]:
        """Some of `{"read", "write"}`."""

    def read(self, limit: int = 25, config=None,
             upcoming_only: bool = True) -> tuple[list[Entry], list[str]]:
        """Entries, and any human-readable problems.

        `upcoming_only` is what separates an agenda from a month view. The
        landing page draws a calendar you can page backwards through, so it
        asks for everything; `aki agenda` asks for what is still to come.
        A provider that can only offer the future says so by returning it
        either way rather than pretending.
        """


# ---------------------------------------------------------------------------
# The two that exist today
# ---------------------------------------------------------------------------

@dataclass
class IcsFeeds:
    """Every ICS subscription in the configuration, read fresh.

    ONE PROVIDER, NOT ONE PER FEED
    ------------------------------
    A person may subscribe to four calendars. Registering four providers would
    mean the registry had to be rebuilt every time the configuration changed,
    and a stale registry is a calendar that silently disappeared.

    So this is one provider that reads the feed list when it is asked, which
    is the lesson `FileChannel` already records in `channels`: anything
    derived from configuration is read when it is used, never cached at
    start-up.
    """

    name: str = "ics"

    def _feeds(self, config) -> tuple:
        if config is None:
            return ()
        try:
            return tuple(config.connections.calendars)
        except AttributeError:                            # pragma: no cover
            return ()

    def available(self, config=None) -> tuple[bool, str]:
        """Subscribed AND readable, which are not the same thing.

        Found on the Surface, 2026-08-26: two feeds were named in the
        configuration and every read failed, while this reported "ready".
        Being subscribed is not being usable.

        AND "NO ADDRESS SAVED" IS NOT THE SAME AS "CANNOT READ THE STORE"
        ----------------------------------------------------------------
        The first fix asked `Calendar.url()` and called an empty answer a
        missing address. That is wrong in exactly the situation it was found
        in: `get_secret` returns None both when nothing was stored and when
        Windows Credential Manager cannot be reached at all -- which is what
        happens in any session without an interactive logon, an SSH
        connection included. So the fix would have told somebody their
        calendars were unconfigured when they were merely being read from the
        wrong kind of session.

        `secrets.store_unavailable()` exists for precisely this distinction,
        so it is asked first and its answer is passed straight through.
        """
        from . import secrets
        from .connectors import calendars as ics

        feeds = self._feeds(config)
        if not feeds:
            return False, ("no calendar subscriptions yet — add one with "
                           "connect-calendar --name Work --url <the ICS "
                           "address>")

        cannot_reach = secrets.store_unavailable()
        if cannot_reach:
            return False, (f"{len(feeds)} subscribed, but their addresses "
                           f"cannot be read — {cannot_reach}")

        without = [feed.name for feed in feeds
                   if not ics.Calendar(name=feed.name).url()]
        if len(without) == len(feeds):
            return False, (f"{len(feeds)} subscribed, but no address is saved "
                           f"for any of them ({', '.join(without)}) — add "
                           "them again with connect-calendar")
        return True, ""

    def capabilities(self) -> frozenset[str]:
        # ICS is a published file. There is nothing to write to.
        return frozenset({"read"})

    def read(self, limit: int = 25, config=None,
             upcoming_only: bool = True) -> tuple[list[Entry], list[str]]:
        from .connectors import calendars as ics

        found: list[Entry] = []
        problems: list[str] = []
        for feed in self._feeds(config):
            try:
                text = ics.fetch(ics.Calendar(name=feed.name))
                events = ics.parse(text)
            except Exception as exc:                      # noqa: BLE001
                # One bad feed is one bad feed. The others still have to be
                # readable, and the person still has to be told which failed.
                problems.append(f"{feed.name}: could not be read — {exc}")
                continue
            wanted = (ics.next_up(events, count=limit) if upcoming_only
                      else events)
            for event in wanted:
                found.append(Entry(
                    summary=event.summary,
                    start=event.start,
                    end=event.end,
                    location=event.location,
                    all_day=event.all_day,
                    description=event.description,
                    source=feed.name,
                ))
        return found, problems


@dataclass
class GoogleCalendar:
    """The connected Google account. Reads and writes."""

    name: str = "google"

    def available(self, config=None) -> tuple[bool, str]:
        from .connectors import google_calendar

        if not google_calendar.connected():
            return False, ("Google is not connected — connect it on the "
                           "dashboard's Connections page")
        return True, ""

    def capabilities(self) -> frozenset[str]:
        return frozenset({"read", "write"})

    def read(self, limit: int = 25, config=None,
             upcoming_only: bool = True) -> tuple[list[Entry], list[str]]:
        # `upcoming_only` is accepted and cannot be honoured: the Google
        # connector asks for events from now onwards. Saying so here is
        # better than a silently short month view.
        from .connectors import google_calendar

        try:
            bookings = google_calendar.upcoming(limit=limit)
        except google_calendar.GoogleError as exc:
            return [], [f"Google Calendar: could not be read — {exc}"]
        return [Entry(
            summary=booking.summary,
            start=booking.start,
            end=booking.end,
            location=booking.location,
            all_day=booking.all_day,
            source="Google Calendar",
            ref=booking.event_id,
            link=booking.link,
            changeable=True,
        ) for booking in bookings], []

    # -- the write half, only meaningful because `capabilities` says so ----

    def add(self, summary: str, start: _dt.datetime,
            end: _dt.datetime | None = None, location: str = "",
            description: str = "", calendar_id: str = "primary",
            confirmed: bool = False) -> tuple[bool, str]:
        from .connectors import google_calendar

        return google_calendar.add(
            summary, start, end, location=location, description=description,
            calendar_id=calendar_id, confirmed=confirmed)

    def change(self, ref: str, calendar_id: str = "primary",
               confirmed: bool = False, **fields) -> tuple[bool, str]:
        from .connectors import google_calendar

        return google_calendar.change(
            ref, calendar_id=calendar_id, confirmed=confirmed, **fields)

    def cancel(self, ref: str, calendar_id: str = "primary",
               confirmed: bool = False) -> tuple[bool, str]:
        from .connectors import google_calendar

        return google_calendar.cancel(
            ref, calendar_id=calendar_id, confirmed=confirmed)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

_REGISTRY = seams.Registry("calendar")


def register(provider) -> None:
    _REGISTRY.register(provider)


def unregister(name: str) -> None:
    _REGISTRY.unregister(name)


def get(name: str):
    return _REGISTRY.get(name)


def registered_names() -> tuple[str, ...]:
    return _REGISTRY.names()


def reset_to_defaults() -> None:
    """The providers that always exist.

    Both are registered even with nothing connected, and each reports itself
    unavailable with a reason until it is. An unregistered provider produces
    "there is no calendar called google", which reads as a bug in the software
    rather than an account that has not been connected -- the same reason
    `channels` always registers Telegram.
    """
    _REGISTRY.clear()
    register(IcsFeeds())
    register(GoogleCalendar())


reset_to_defaults()


# ---------------------------------------------------------------------------
# What the commands actually call
# ---------------------------------------------------------------------------

def usable(config=None) -> list:
    """Every provider that can be used right now."""
    return [one for one in _REGISTRY.all() if one.available(config)[0]]


def readers(config=None) -> list:
    return [one for one in usable(config) if "read" in one.capabilities()]


def writers(config=None) -> list:
    return [one for one in usable(config) if "write" in one.capabilities()]


def writer(config=None):
    """The provider to add an event to, or None.

    Writable providers come back in registry order, which is name order. When
    there is a second one this becomes a real choice and the caller will need
    to say which -- until then, saying "the first" out loud is more honest
    than pretending the question does not exist.
    """
    found = writers(config)
    return found[0] if found else None


def why_no_writer(config=None) -> str:
    """The sentence to print when nothing can add an event.

    It names what would fix it rather than what failed, because "no writable
    calendar" tells a person nothing they can act on.
    """
    reasons = []
    for one in _REGISTRY.all():
        if "write" not in one.capabilities():
            continue
        ok, why = one.available(config)
        if not ok and why:
            reasons.append(why)
    if reasons:
        return ("None of your calendars can add events. "
                + "; ".join(reasons) + ".")
    return ("None of your calendars can add events. A subscription feed is "
            "read-only; connect Google to add and change things.")


def agenda(limit: int = 25, config=None) -> tuple[list[Entry], list[str]]:
    """Everything coming up, and anything that could not be read.

    Changeable entries lead. That ordering is not cosmetic: it is what stops
    a person reading a list top-down and asking to move something that lives
    in a published file nobody here can edit.
    """
    entries: list[Entry] = []
    problems: list[str] = []
    for provider in readers(config):
        found, trouble = provider.read(limit=limit, config=config)
        entries.extend(found)
        problems.extend(trouble)
    entries.sort(key=lambda one: (not one.changeable, _order(one.start)))
    return entries, problems


def _order(when: _dt.datetime | None) -> tuple[int, float]:
    """A sort key that survives one provider being timezone-aware.

    Google returns aware datetimes and an ICS feed can return naive ones.
    Comparing the two raises `TypeError`, which would mean a person who
    connected both calendars got a crash instead of an agenda. `timestamp()`
    reads an aware value by its offset and a naive one as local time, which
    is what both actually mean.
    """
    if when is None:
        return (1, 0.0)
    try:
        return (0, when.timestamp())
    except (OverflowError, OSError, ValueError):          # pragma: no cover
        return (1, 0.0)


def grouped(limit: int = 25,
            config=None) -> tuple[list[tuple[str, bool, list[Entry]]], list[str]]:
    """The agenda in labelled groups, changeable ones first.

    Groups rather than one merged list, because the label is the safety
    feature: a person needs to see which lines they can ask to move. Merging
    by time would read better and would be the change that reintroduces the
    problem this seam exists to fix.

    Each group is `(label, changeable, entries)`.
    """
    groups: list[tuple[str, bool, list[Entry]]] = []
    problems: list[str] = []
    for provider in readers(config):
        found, trouble = provider.read(limit=limit, config=config)
        problems.extend(trouble)
        by_source: dict[str, list[Entry]] = {}
        for entry in found:
            by_source.setdefault(entry.source or provider.name, []).append(entry)
        for label in sorted(by_source):
            entries = sorted(by_source[label], key=lambda one: _order(one.start))
            groups.append((label, entries[0].changeable, entries))
    groups.sort(key=lambda group: (not group[1], group[0]))
    return groups, problems


def everything(limit: int = 500, config=None) -> tuple[list[Entry], list[str]]:
    """Every entry each readable calendar will give up, earliest first.

    For the month view, which pages backwards. `agenda` is the other shape:
    grouped, labelled, and only what is still to come.
    """
    entries: list[Entry] = []
    problems: list[str] = []
    for provider in readers(config):
        found, trouble = provider.read(limit=limit, config=config,
                                       upcoming_only=False)
        entries.extend(found)
        problems.extend(trouble)
    entries.sort(key=lambda one: _order(one.start))
    return entries, problems
