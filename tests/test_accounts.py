"""The account seam, and the promise it is built to keep.

The promise, in. Four connectors had four unrelated ways of obtaining a credential,
and adding Google Drive would have meant writing the OAuth refresh dance a
second time because there was nowhere else to put it.

So the centrepiece here is `Bitbucket` — a provider written the way a future
one would be, registered the way a future one would be, and then seen through
the ordinary `inspect` report. If a report ever has to learn a provider's name
again, `test_a_provider_added_later_appears_with_nothing_else_edited` fails,
and it fails for the right reason.

The other half is the thing that made this a seam rather than a helper: the
report has to survive a broken machine. `inspect` exists to tell somebody what
is wrong with their install, so a provider that raises must not be able to
empty it.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from aki_agent import accounts, inspect_report, paths, seams


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


@pytest.fixture(autouse=True)
def clean_registry():
    """Every test starts from the shipped providers and leaves them behind."""
    accounts.reset_to_defaults()
    yield
    accounts.reset_to_defaults()


def a_config(mail=(), calendars=()):
    """The shape `config.connections` presents, and nothing more."""
    return SimpleNamespace(
        connections=SimpleNamespace(mail=tuple(mail), calendars=tuple(calendars)),
        source_path="",
    )


# ---------------------------------------------------------------------------
# It is a seam, registered like the other two
# ---------------------------------------------------------------------------

def test_account_is_a_seam_the_registry_knows_about():
    seams.import_seam_modules()
    assert "account" in seams.known()
    assert seams.seam("account") is not None


def test_the_shipped_providers_are_registered():
    assert set(accounts.registered_names()) == {
        "google", "app-password", "ics", "folder"}


# ---------------------------------------------------------------------------
# What it reports
# ---------------------------------------------------------------------------

def test_with_no_configuration_it_still_answers():
    """A machine where setup never ran is the case `inspect` is *for*."""
    found = accounts.every(None)
    assert found, "the report must not be empty just because nothing is set up"
    assert all(isinstance(c, accounts.Connection) for c in found)


def test_a_configured_mailbox_reads_as_connected():
    config = a_config(mail=[SimpleNamespace(address="a@example.com",
                                            may_send=True)])
    mail = [c for c in accounts.every(config) if c.service.startswith("mail:")]
    assert len(mail) == 1
    assert mail[0].connected is True
    assert mail[0].kind == "app_password"
    assert "send" in mail[0].detail


def test_a_mailbox_that_cannot_send_says_so():
    config = a_config(mail=[SimpleNamespace(address="a@example.com",
                                            may_send=False)])
    mail = [c for c in accounts.every(config) if c.service.startswith("mail:")]
    assert mail[0].detail == "read only"


def test_no_mailbox_gives_a_next_step_rather_than_silence():
    """An empty list teaches nobody what to do about it."""
    mail = [c for c in accounts.every(a_config()) if c.service == "mail"]
    assert len(mail) == 1
    assert mail[0].connected is False
    assert "connect-mail" in mail[0].next_step


def test_ics_feeds_are_listed_by_name():
    config = a_config(calendars=[SimpleNamespace(name="Work",
                                                 url="https://x/y.ics")])
    feeds = [c for c in accounts.every(config)
             if c.service.startswith("calendar feed:")]
    assert len(feeds) == 1
    assert "Work" in feeds[0].service
    assert feeds[0].connected is True
    assert feeds[0].kind == "location"


def test_google_gaps_are_listed_rather_than_hidden():
    """Drive and Gmail are not implemented, and the report says so.

    A short list that looks complete is worse than an honest gap: it answers
    "can it reach my Drive?" with silence, which reads as yes.
    """
    services = {c.service: c for c in accounts.every(None)}
    assert services["google drive"].connected is False
    assert "not implemented" in services["google drive"].detail
    assert services["gmail (sending)"].connected is False


# ---------------------------------------------------------------------------
# The promise: one class and one name
# ---------------------------------------------------------------------------

@dataclass
class Bitbucket:
    """A provider written the way a future one would be. Nothing else knows it."""

    name: str = "bitbucket"
    kind: str = "oauth"

    def connections(self, config=None):
        return (accounts.Connection(
            service="bitbucket",
            provider=self.name,
            kind=self.kind,
            connected=True,
            detail="repositories",
        ),)


def test_a_provider_added_later_appears_with_nothing_else_edited():
    accounts.register(Bitbucket())
    services = [c.service for c in accounts.every(None)]
    assert "bitbucket" in services


def test_a_provider_added_later_reaches_the_inspect_report():
    accounts.register(Bitbucket())
    report = inspect_report.gather(None)
    listed = [e["service"] for e in report.get("accounts", [])]
    assert "bitbucket" in listed
    assert "bitbucket" in inspect_report.render(report)


# ---------------------------------------------------------------------------
# It has to survive a broken machine
# ---------------------------------------------------------------------------

@dataclass
class Exploding:
    name: str = "exploding"
    kind: str = "oauth"

    def connections(self, config=None):
        raise RuntimeError("this provider is broken")


def test_one_broken_provider_does_not_empty_the_report():
    accounts.register(Exploding())
    found = accounts.every(None)
    assert found, "a broken provider must not take the whole report down"
    assert all(c.provider != "exploding" for c in found)


def test_inspect_still_renders_with_a_broken_provider():
    accounts.register(Exploding())
    text = inspect_report.render(inspect_report.gather(None))
    assert "Accounts" in text


# ---------------------------------------------------------------------------
# The line a person reads
# ---------------------------------------------------------------------------

def test_a_connected_line_says_connected():
    line = accounts.Connection(service="mail: a@b", provider="app-password",
                               kind="app_password", connected=True,
                               detail="read and send").line()
    assert "connected" in line and "not connected" not in line
    assert "read and send" in line


def test_an_unconnected_line_carries_the_next_step():
    line = accounts.Connection(service="mail", provider="app-password",
                               kind="app_password", connected=False,
                               next_step="run `connect-mail`").line()
    assert "not connected" in line
    assert "connect-mail" in line
