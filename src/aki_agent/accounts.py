"""One place that knows how every connection was made.

WHY THIS EXISTS
---------------
Storing a credential was already uniform: everything goes to `secrets.py` and
the operating system's credential store. *Obtaining* one was not. On
2026-08-28 there were four connectors and four unrelated ways in:

    mail.py               an app password, pasted by the user
    google_calendar.py    OAuth, hand-rolled over four REST calls
    calendars.py          an ICS link, pasted by the user
    files.py              a folder that was already synced

He is right, and the cost is not only the user's. Adding Google Drive today
would mean re-implementing the OAuth refresh dance that `google_calendar.py`
already contains, because there is nowhere else to put it.

WHAT THIS MODULE DOES, AND WHAT IT DELIBERATELY DOES NOT
--------------------------------------------------------
It is a **seam and a report**, not a rewrite. Every provider here describes
connections that already work; none of them replaces the code that makes them.
That is on purpose:

  * The connectors are covered by a passing suite. A seam that quietly changed
    how mail authenticates would be an architectural change wearing a
    refactor's clothes, and the tests that pass afterwards would be proving
    less than they look.
  * The value arrives before the migration does. `aki inspect` can list every
    connection and its state in one place the moment this exists, which is the
    thing a person actually asks for — *what am I connected to?*
  * Migration then has somewhere to arrive. When `mail.py` is ready to stop
    owning its own credential prompt, the provider it hands the job to is
    already registered and already tested.

So: read-only first, authoritative later. The direction is one-way — new
connectors should be written against this from the start rather than growing
their own flow and being migrated afterwards.

WHY "ACCOUNT" AND NOT "MAIL" OR "FILES" AS THE THIRD SEAM
---------------------------------------------------------
`calendar` and `channel` were the first two. Mail and files were the obvious
third and fourth — but both of them need an authentication story before they
need a provider story, so authentication is the layer underneath them and
should exist first. See `docs/CONNECTING.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from . import seams


@dataclass(frozen=True)
class Connection:
    """One thing the assistant is, or could be, connected to.

    `connected` is the only field a caller should branch on. `detail` is for a
    person to read and is never parsed.
    """

    service: str
    provider: str
    kind: str
    connected: bool
    detail: str = ""
    # What the user would have to do, in plain words, if it is not connected.
    next_step: str = ""
    # The `guides` topic that explains how to set this up. A connection with
    # no guide is a connection somebody will be stuck on, so providers should
    # always set one -- see test_every_connection_offers_a_guide.
    guide: str = ""

    def line(self) -> str:
        """One line, for `inspect` and for `doctor`."""
        mark = "connected" if self.connected else "not connected"
        bits = [f"{self.service} ({self.kind}) — {mark}"]
        if self.detail:
            bits.append(self.detail)
        if not self.connected and self.next_step:
            bits.append(self.next_step)
        return " · ".join(bits)


class AccountProvider(Protocol):
    """What a provider has to offer. Deliberately tiny, like `Channel`."""

    name: str
    kind: str

    def connections(self, config=None) -> tuple[Connection, ...]:
        """Every connection this provider knows about, connected or not."""


# ---------------------------------------------------------------------------
# The providers that ship
# ---------------------------------------------------------------------------


@dataclass
class GoogleOAuth:
    """Google, reached by OAuth.

    Today this covers the calendar only, because the calendar is the only
    Google service implemented. Drive and Gmail are listed as *not connected*
    rather than omitted, because a person asking "what can this reach?" is
    better served by an honest gap than by a short list that looks complete.

    The scope tiers behind those two gaps are in `docs/CONNECTING.md`. The
    short version: Drive via `drive.file` and sending mail via `gmail.send`
    are reachable without a paid annual security assessment; *reading* Gmail
    is not, and should stay on IMAP.
    """

    name: str = "google"
    kind: str = "oauth"

    def connections(self, config=None) -> tuple[Connection, ...]:
        try:
            from .connectors import google_calendar
            live = bool(google_calendar.connected())
        except Exception:                                  # pragma: no cover
            # A provider must never be the reason `inspect` fails. The whole
            # point of the report is that it still answers on a broken machine.
            live = False
        calendar = Connection(
            service="google calendar",
            provider=self.name,
            kind=self.kind,
            connected=live,
            detail="read and write" if live else "",
            next_step="run `connect-calendar`",
            guide="google-oauth",
        )
        drive = Connection(
            service="google drive",
            provider=self.name,
            kind=self.kind,
            connected=False,
            detail="not implemented yet",
            next_step="see docs/CONNECTING.md — drive.file needs no verification",
            guide="google-oauth",
        )
        gmail_send = Connection(
            service="gmail (sending)",
            provider=self.name,
            kind=self.kind,
            connected=False,
            detail="not implemented yet; sending currently goes over SMTP",
            next_step="see docs/CONNECTING.md — gmail.send is a sensitive scope",
            guide="google-oauth",
        )
        return (calendar, drive, gmail_send)


@dataclass
class AppPasswords:
    """Mailboxes reached with an app password over IMAP and SMTP.

    Reads the accounts out of the configuration rather than the credential
    store. Asking the credential store would mean asking for a secret in order
    to answer a question about whether a secret exists, which is a good way to
    end up logging one.
    """

    name: str = "app-password"
    kind: str = "app_password"

    def connections(self, config=None) -> tuple[Connection, ...]:
        entries = _connections_of(config, "mail")
        if not entries:
            return (Connection(
                service="mail",
                provider=self.name,
                kind=self.kind,
                connected=False,
                next_step="run `connect-mail`",
                guide="mail-app-password",
            ),)
        out = []
        for entry in entries:
            # THE DOMAIN, NEVER THE WHOLE ADDRESS
            # -----------------------------------
            # `inspect` output is the thing people paste into a chat when they
            # ask for help, so it is the most likely place for a personal
            # address to escape. `_connections` in inspect_report.py already
            # reduced mail to the domain for exactly this reason, and
            # `test_inspect_never_prints_a_whole_mail_address` caught the first
            # version of this provider printing the lot. Two mailboxes at the
            # same provider will read alike; that is the cheaper mistake.
            address = getattr(entry, "address", "") or ""
            domain = address.split("@")[-1] if "@" in address else (
                address or "(no address)")
            may_send = bool(getattr(entry, "may_send", False))
            out.append(Connection(
                service=f"mail: {domain}",
                provider=self.name,
                kind=self.kind,
                connected=True,
                detail="read and send" if may_send else "read only",
                guide="mail-app-password",
            ))
        return tuple(out)


@dataclass
class IcsFeeds:
    """Calendars subscribed to by link.

    Kept as its own provider rather than folded into `GoogleOAuth` because it
    is genuinely a different thing: no account, no token, no permission to
    revoke — just a URL that returns a file. It is also the only route that
    works for a service with no usable OAuth at all, which is why it must not
    be treated as a lesser fallback.
    """

    name: str = "ics"
    kind: str = "location"

    def connections(self, config=None) -> tuple[Connection, ...]:
        feeds = _connections_of(config, "calendars")
        if not feeds:
            return (Connection(
                service="calendar feed",
                provider=self.name,
                kind=self.kind,
                connected=False,
                next_step="add an ICS link",
                guide="calendar-ics",
            ),)
        return tuple(
            Connection(
                service=f"calendar feed: {getattr(f, 'name', '') or '(unnamed)'}",
                provider=self.name,
                kind=self.kind,
                connected=bool(getattr(f, "url", "")),
                detail="read only",
                guide="calendar-ics",
            )
            for f in feeds
        )


@dataclass
class SyncedFolders:
    """Cloud storage, reached as the folder the machine already has.

    There is no credential here at all, which is the point. It is listed
    alongside the others so that "what am I connected to?" has one answer
    rather than one answer plus a footnote.
    """

    name: str = "folder"
    kind: str = "location"

    def connections(self, config=None) -> tuple[Connection, ...]:
        try:
            from .connectors import files
            stores = files.detect()
        except Exception:                                  # pragma: no cover
            stores = []
        if not stores:
            return (Connection(
                service="cloud files",
                provider=self.name,
                kind=self.kind,
                connected=False,
                detail="no synced folder found on this machine",
                next_step="install the provider's desktop app, or point at a folder",
                guide="cloud-files",
            ),)
        return tuple(
            Connection(
                service=f"files: {getattr(s, 'name', '') or '(unnamed)'}",
                provider=self.name,
                kind=self.kind,
                connected=True,
                detail=str(getattr(s, "path", "")),
                guide="cloud-files",
            )
            for s in stores
        )


def _connections_of(config, attribute: str):
    """`config.connections.<attribute>`, or an empty tuple.

    Defensive because this module is called by `inspect` and by `doctor`, and
    both are expected to work on a half-installed machine where the config may
    be missing, partial, or an object of a shape nobody promised.
    """
    if config is None:
        return ()
    try:
        return tuple(getattr(config.connections, attribute) or ())
    except AttributeError:
        return ()


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

_REGISTRY = seams.Registry("account")


def register(provider: AccountProvider) -> None:
    _REGISTRY.register(provider)


def unregister(name: str) -> None:
    _REGISTRY.unregister(name)


def get(name: str) -> AccountProvider | None:
    return _REGISTRY.get(name)


def registered_names() -> tuple[str, ...]:
    return _REGISTRY.names()


def every(config=None) -> tuple[Connection, ...]:
    """Every connection, from every registered provider, in one list.

    The order is provider registration order, not alphabetical: the providers
    are registered cheapest-to-explain first, and a person reading the list
    wants the account-shaped things before the folder-shaped ones.

    A provider that raises is skipped rather than allowed to empty the report.
    `inspect` exists to tell somebody what is wrong with their machine, so it
    is the last thing that should fall over on a broken one.
    """
    out: list[Connection] = []
    for provider in _REGISTRY.all():
        try:
            out.extend(provider.connections(config))
        except Exception:                                  # pragma: no cover
            continue
    return tuple(out)


def reset_to_defaults() -> None:
    """Clear the registry back to the providers that always exist."""
    _REGISTRY.clear()
    register(GoogleOAuth())
    register(AppPasswords())
    register(IcsFeeds())
    register(SyncedFolders())


reset_to_defaults()
