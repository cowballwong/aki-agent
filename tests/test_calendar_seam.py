"""The calendar seam, and the promise it was built to keep.

The promise, in the maintainer's terms (2026-08-26): adding a calendar later — iCloud
over CalDAV is the one actually waiting — should be **one new class and one
name in the defaults**. No command edited, nothing in `cli.py` touched.

So the centrepiece here is `NewCalendar`: a provider written the way a future
one would be, registered the way a future one would be, and then checked
through the ordinary commands. If a command ever has to learn a provider's
name again, `test_a_calendar_added_later_is_used_with_no_command_changed`
fails, and it fails for the right reason.

The other half is the distinction that made a seam necessary at all. A
subscription feed can be read and cannot be written to. Before this,
`calendar-add` imported Google directly, so on a machine with an ICS feed and
no Google account it announced what it *would* add and then reached for a
service that was not there.
"""

from __future__ import annotations

import datetime as _dt
from types import SimpleNamespace

import pytest

from aki_agent import calendar_seam, paths, seams


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


@pytest.fixture(autouse=True)
def clean_registry():
    """Every test starts from the shipped providers and leaves them behind.

    The registry is module-level, so a test that registers a fake and does not
    put it back is a test that silently changes the next one.
    """
    calendar_seam.reset_to_defaults()
    yield
    calendar_seam.reset_to_defaults()


# ---------------------------------------------------------------------------
# Providers a future contributor would write
# ---------------------------------------------------------------------------

class NewCalendar:
    """What an iCloud CalDAV provider would look like. Reads and writes."""

    name = "newcal"

    def __init__(self) -> None:
        self.added: list[tuple] = []
        self.changed: list[tuple] = []
        self.cancelled: list[str] = []

    def available(self, config=None):
        return True, ""

    def capabilities(self):
        return frozenset({"read", "write"})

    def read(self, limit=25, config=None, upcoming_only=True):
        return [calendar_seam.Entry(
            summary="Site visit",
            start=_dt.datetime(2026, 9, 1, 10, 0),
            source="iCloud",
            ref="cal-1",
            changeable=True,
        )], []

    def add(self, summary, start, end=None, location="", description="",
            calendar_id="primary", confirmed=False):
        self.added.append((summary, start, confirmed))
        return True, f"Added to iCloud: {summary}"

    def change(self, ref, calendar_id="primary", confirmed=False, **fields):
        self.changed.append((ref, fields))
        return True, f"Moved {ref}"

    def cancel(self, ref, calendar_id="primary", confirmed=False):
        self.cancelled.append(ref)
        return True, f"Cancelled {ref}"


class ReadOnlyFeed:
    """A subscription. There is nothing to write to."""

    name = "feed"

    def available(self, config=None):
        return True, ""

    def capabilities(self):
        return frozenset({"read"})

    def read(self, limit=25, config=None, upcoming_only=True):
        return [calendar_seam.Entry(
            summary="Term starts",
            start=_dt.datetime(2026, 8, 30, 9, 0),
            source="School",
        )], []


def _only(provider):
    calendar_seam._REGISTRY.clear()
    calendar_seam.register(provider)
    return provider


# ---------------------------------------------------------------------------
# The registry itself
# ---------------------------------------------------------------------------

def test_the_registry_holds_anything_with_a_name():
    """It asks for `name` and nothing else, which is what lets one registry
    serve seams whose providers promise genuinely different things."""
    shelf = seams.Registry("thing", listed=False)
    thing = SimpleNamespace(name="one")
    shelf.register(thing)

    assert shelf.get("one") is thing
    assert shelf.names() == ("one",)
    assert "one" in shelf
    assert len(shelf) == 1

    shelf.unregister("one")
    assert shelf.get("one") is None
    assert shelf.names() == ()


def test_registering_the_same_name_replaces_rather_than_refuses():
    """The behaviour `channels` already had. Tests register a fake over the
    real thing constantly; making that an error would break every one."""
    shelf = seams.Registry("thing", listed=False)
    first, second = SimpleNamespace(name="x"), SimpleNamespace(name="x")
    shelf.register(first)
    shelf.register(second)

    assert shelf.get("x") is second
    assert len(shelf) == 1


def test_a_throwaway_registry_does_not_become_a_seam_of_this_install():
    """A `Registry` claims its seam name globally, which is what lets `apply`
    and `inspect` reach every seam without importing each one by hand.

    It also means a registry made for one test used to become a permanent
    seam that `inspect` then reported on a real machine — which is how this
    was found. `listed=False` is the opt-out, and this holds it down.
    """
    seams.Registry("not-a-real-seam", listed=False)

    assert "not-a-real-seam" not in seams.known()
    assert seams.seam("not-a-real-seam") is None


def test_both_shipped_calendars_are_registered_even_with_nothing_connected():
    """An unregistered provider produces "there is no calendar called google",
    which reads as a bug rather than an account nobody has connected."""
    assert calendar_seam.registered_names() == ("google", "ics")


# ---------------------------------------------------------------------------
# The promise
# ---------------------------------------------------------------------------

def test_a_calendar_added_later_is_used_with_no_command_changed(capsys):
    """The acceptance test for the whole phase.

    `NewCalendar` is registered and nothing else is told about it. If this
    passes, adding iCloud is a class and a name.
    """
    from aki_agent import cli

    later = _only(NewCalendar())

    args = SimpleNamespace(title="Survey", start="2026-09-12 14:30", end=None,
                           location="", description="", calendar="primary",
                           yes=True)
    assert cli.cmd_calendar_add(args) == 0

    assert later.added and later.added[0][0] == "Survey"
    assert "Added to iCloud: Survey" in capsys.readouterr().out


def test_the_dry_run_names_the_calendar_it_would_use(capsys):
    """A person about to book something should see where it is going."""
    from aki_agent import cli

    _only(NewCalendar())
    args = SimpleNamespace(title="Survey", start="2026-09-12 14:30", end=None,
                           location="", description="", calendar="primary",
                           yes=False)
    assert cli.cmd_calendar_add(args) == 0

    printed = capsys.readouterr().out
    assert "Would add to newcal: Survey" in printed
    assert "Nothing was added" in printed


def test_change_and_cancel_also_find_the_new_calendar(capsys):
    from aki_agent import cli

    later = _only(NewCalendar())

    changed = SimpleNamespace(event_id="cal-1", calendar="primary",
                              title="Moved", start=None, end=None,
                              location=None, yes=True)
    assert cli.cmd_calendar_change(changed) == 0
    assert later.changed and later.changed[0][0] == "cal-1"

    cancelled = SimpleNamespace(event_id="cal-1", calendar="primary", yes=True)
    assert cli.cmd_calendar_cancel(cancelled) == 0
    assert later.cancelled == ["cal-1"]


# ---------------------------------------------------------------------------
# The distinction that made this necessary
# ---------------------------------------------------------------------------

def test_a_read_only_calendar_is_never_offered_for_writing():
    _only(ReadOnlyFeed())

    assert [one.name for one in calendar_seam.readers()] == ["feed"]
    assert calendar_seam.writers() == []
    assert calendar_seam.writer() is None


def test_adding_with_nothing_writable_refuses_before_it_pretends(capsys):
    """The bug this seam was built for.

    The old command printed "Would add: ..." and only then reached for a
    service that was not connected. The refusal has to come first, and it has
    to name what would fix it.
    """
    from aki_agent import cli

    _only(ReadOnlyFeed())
    args = SimpleNamespace(title="Survey", start="2026-09-12 14:30", end=None,
                           location="", description="", calendar="primary",
                           yes=False)
    assert cli.cmd_calendar_add(args) == 1

    printed = capsys.readouterr().out
    assert "Would add" not in printed
    assert "None of your calendars can add events" in printed
    assert "connect Google" in printed


def test_the_refusal_repeats_the_provider_s_own_reason():
    """`why_no_writer` names what would fix it, not what failed."""
    calendar_seam.reset_to_defaults()
    said = calendar_seam.why_no_writer()

    assert "Google is not connected" in said
    assert "Connections page" in said


# ---------------------------------------------------------------------------
# Subscribed is not the same as usable
# ---------------------------------------------------------------------------

def _with_feeds(*names):
    return SimpleNamespace(connections=SimpleNamespace(
        calendars=tuple(SimpleNamespace(name=name, url="") for name in names)))


def test_no_subscriptions_says_how_to_add_one():
    usable, why = calendar_seam.IcsFeeds().available(_with_feeds())

    assert usable is False
    assert "connect-calendar" in why


def test_a_credential_store_that_cannot_be_read_says_so_rather_than_blaming_setup(
        monkeypatch):
    """Found on the Surface, 2026-08-26, and the first fix got it wrong.

    `secrets.get_secret` returns None both when nothing was stored and when
    Windows Credential Manager cannot be reached — which is every session
    without an interactive logon, an SSH connection included. Calling an empty
    answer "no address saved" tells somebody to set up calendars that are
    already set up.

    `secrets.store_unavailable()` exists for exactly this distinction, so it
    is asked first.
    """
    from aki_agent import secrets

    monkeypatch.setattr(secrets, "store_unavailable",
                        lambda: "WinError 1312: no interactive logon.")

    usable, why = calendar_seam.IcsFeeds().available(_with_feeds("Work",
                                                                "Personal"))

    assert usable is False
    assert "cannot be read" in why
    assert "1312" in why
    assert "no address is saved" not in why


def test_subscriptions_with_no_saved_address_are_named(monkeypatch):
    from aki_agent import secrets
    from aki_agent.connectors import calendars as ics

    monkeypatch.setattr(secrets, "store_unavailable", lambda: "")
    monkeypatch.setattr(ics.Calendar, "url", lambda self: None)

    usable, why = calendar_seam.IcsFeeds().available(_with_feeds("Work"))

    assert usable is False
    assert "no address is saved" in why
    assert "Work" in why


def test_one_readable_subscription_is_enough_to_be_usable(monkeypatch):
    """One broken feed among several must not report the whole seam as
    unusable — `read` already names the one that failed."""
    from aki_agent import secrets
    from aki_agent.connectors import calendars as ics

    monkeypatch.setattr(secrets, "store_unavailable", lambda: "")
    monkeypatch.setattr(ics.Calendar, "url",
                        lambda self: "https://x/y.ics"
                        if self.name == "Work" else None)

    usable, why = calendar_seam.IcsFeeds().available(_with_feeds("Work",
                                                                "Broken"))

    assert usable is True
    assert why == ""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def test_the_agenda_puts_changeable_calendars_first_and_labels_them():
    """The ordering is the safety feature, not a preference: a person reading
    top-down must not be invited to move something nobody here can move."""
    calendar_seam._REGISTRY.clear()
    calendar_seam.register(ReadOnlyFeed())
    calendar_seam.register(NewCalendar())

    groups, problems = calendar_seam.grouped()

    assert problems == []
    assert [(label, changeable) for label, changeable, _ in groups] == [
        ("iCloud", True), ("School", False)]


def test_the_agenda_prints_the_label_and_the_handle(capsys, monkeypatch):
    from aki_agent import cli

    # `agenda` loads the configuration because the ICS provider needs the feed
    # list. Stubbed rather than written to disk: what is being checked here is
    # the wiring between the command and the seam, and a setup interview in
    # the middle of that would be testing the interview.
    monkeypatch.setattr(cli, "_load_config", lambda: (
        SimpleNamespace(connections=SimpleNamespace(calendars=())), ""))

    calendar_seam._REGISTRY.clear()
    calendar_seam.register(ReadOnlyFeed())
    calendar_seam.register(NewCalendar())

    assert cli.cmd_agenda(SimpleNamespace(limit=10)) == 0

    printed = capsys.readouterr().out
    assert "iCloud (can be changed):" in printed
    assert "[cal-1]" in printed
    # The read-only one is listed, and carries no invitation to change it.
    assert "School:" in printed
    assert "School (can be changed)" not in printed


def test_one_unreadable_calendar_does_not_hide_the_others():
    """A provider reports trouble instead of raising, so a broken feed costs
    its own lines and nothing else."""

    class Broken:
        name = "broken"

        def available(self, config=None):
            return True, ""

        def capabilities(self):
            return frozenset({"read"})

        def read(self, limit=25, config=None, upcoming_only=True):
            return [], ["Broken: could not be read — the address moved"]

    calendar_seam._REGISTRY.clear()
    calendar_seam.register(Broken())
    calendar_seam.register(ReadOnlyFeed())

    groups, problems = calendar_seam.grouped()

    assert [label for label, _, _ in groups] == ["School"]
    assert problems == ["Broken: could not be read — the address moved"]


def test_a_timezone_aware_calendar_beside_a_naive_one_does_not_crash():
    """Google returns aware datetimes; an ICS feed can return naive ones.
    Sorting the two together raises `TypeError`, which would have meant a
    person who connected both got a stack trace instead of an agenda.
    """

    class Aware:
        name = "aware"

        def available(self, config=None):
            return True, ""

        def capabilities(self):
            return frozenset({"read"})

        def read(self, limit=25, config=None, upcoming_only=True):
            return [calendar_seam.Entry(
                summary="From Google",
                start=_dt.datetime(2026, 9, 1, 9, 0,
                                   tzinfo=_dt.timezone.utc),
                source="Google Calendar",
                changeable=True,
            )], []

    calendar_seam._REGISTRY.clear()
    calendar_seam.register(Aware())
    calendar_seam.register(ReadOnlyFeed())

    entries, problems = calendar_seam.everything()

    assert problems == []
    assert [one.summary for one in entries] == ["Term starts", "From Google"]


def test_an_entry_describes_itself_with_secrets_removed():
    """A meeting invitation is a place other people write text this assistant
    reads. Dial-in details and one-time codes land in calendar entries."""
    entry = calendar_seam.Entry(
        summary="Standup",
        start=_dt.datetime(2026, 9, 1, 9, 30),
        location="Room 2",
    )

    said = entry.describe()
    assert "Standup" in said
    assert "09:30" in said
    assert "(Room 2)" in said


def test_an_all_day_entry_says_so_rather_than_showing_midnight():
    entry = calendar_seam.Entry(
        summary="Bank holiday",
        start=_dt.datetime(2026, 8, 31, 0, 0),
        all_day=True,
    )

    assert "all day" in entry.when()
    assert "00:00" not in entry.when()
