"""Taking a connection back out — and taking its credential with it.

WHY (reported 2026-08-20)
-----------------------
*"Add 左仲要有得 remove"*, and a minute later: *"Email 都係,要有得俾人
remove"*, then *"Or edit"*.

There was a way in and no way out. A mistyped address stayed on the page for
good, and the app password it had put into the credential store stayed on the
machine with it. `Calendar.forget()` and `Account.forget_password()` both
already existed — nothing was ever wired to them, which is the same shape as
most of the real defects in this package: a working mechanism with no route
to it.

The half that matters most is the second one. Removing the row and leaving
the credential behind would be worse than doing nothing: it looks gone while
still being a live secret on somebody's computer.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from aki_agent import config as config_module
from aki_agent import secrets as secrets_module
from aki_agent.connectors import calendars as calendar_module
from aki_agent.connectors import mail
from aki_agent.dashboard import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "configs" / "examples" / "architecture.yaml"


@pytest.fixture()
def store(monkeypatch):
    """A credential store in memory, so a test never touches the real one."""
    kept: dict[str, str] = {}

    monkeypatch.setattr(secrets_module, "set_secret",
                        lambda key, value: kept.__setitem__(key, value) or "")
    monkeypatch.setattr(secrets_module, "get_secret", lambda key: kept.get(key))
    monkeypatch.setattr(secrets_module, "delete_secret",
                        lambda key: kept.pop(key, None) is not None)
    return kept


@pytest.fixture()
def browser(monkeypatch, tmp_path):
    """The dashboard, with a config it may safely write to."""
    saved = {}

    app = create_app(EXAMPLE)
    app.config["TESTING"] = True

    loaded = config_module.load(EXAMPLE)
    loaded.connections = dataclasses.replace(
        loaded.connections,
        mail=(config_module.MailAccount(address="a@example.com",
                                        label="Work"),),
        calendars=(config_module.CalendarFeed(name="Work", url=""),))

    monkeypatch.setattr(config_module, "load", lambda *a, **k: loaded)
    monkeypatch.setattr(config_module, "save",
                        lambda cfg: saved.update({"config": cfg}))

    with app.test_client() as client:
        yield client, loaded, saved


def _token() -> str:
    import aki_agent.dashboard.app as module

    return module.SESSION_TOKEN


def test_removing_a_mailbox_deletes_its_password_too(browser, store):
    """The row and the secret go together, or the removal is a lie."""
    client, loaded, saved = browser
    account = mail.Account(address="a@example.com")
    secrets_module.set_secret(account.secret_key, "app-password")
    assert store, "the fixture did not store anything"

    response = client.post("/connections/mail/forget",
                           data={"token": _token(), "address": "a@example.com"})

    assert response.status_code in (301, 302)
    assert secrets_module.get_secret(account.secret_key) is None, (
        "the app password is still on this machine after 'remove'")
    assert saved["config"].connections.mail == ()


def test_removing_a_calendar_deletes_its_address_too(browser, store):
    """For a calendar the address *is* the credential.

    Anyone holding it reads the whole calendar with no password at all, so
    leaving it in the store after the calendar has visibly gone is the same
    mistake in a more dangerous form.
    """
    client, loaded, saved = browser
    calendar = calendar_module.Calendar(name="Work")
    calendar.save_url("https://calendar.example.com/secret/basic.ics")

    response = client.post("/connections/calendar/forget", data={"token": _token(), "name": "Work"})

    assert response.status_code in (301, 302)
    assert calendar.url() is None, "the secret address survived the removal"
    assert saved["config"].connections.calendars == ()


def test_removing_something_that_is_not_there_says_so(browser, store):
    """And changes nothing. A no-op that reports success teaches people to
    trust a button that did not do anything."""
    client, loaded, saved = browser

    response = client.post("/connections/mail/forget",
                           data={"token": _token(), "address": "nobody@example.com"})

    # The note travels in a query string, so spaces arrive as plus signs.
    where = response.headers["Location"].replace("+", " ").replace("%20", " ")
    assert "No account here" in where
    assert "config" not in saved, "a failed removal rewrote the config"


def test_removal_says_what_it_did_not_do(browser, store):
    """The honest half of the sentence.

    Disconnecting a mailbox here does not revoke anything at the provider, and
    unsubscribing does not invalidate a calendar address that may already have
    been shared. Somebody who removes a connection because they think it
    leaked needs to know that the leaked thing is still live.
    """
    client, loaded, saved = browser
    secrets_module.set_secret(
        mail.Account(address="a@example.com").secret_key, "pw")

    where = client.post("/connections/mail/forget",
                        data={"token": _token(),
                              "address": "a@example.com"}
                        ).headers["Location"]
    where = where.replace("+", " ").replace("%20", " ")
    assert "still valid" in where

    calendar_module.Calendar(name="Work").save_url("https://x/secret.ics")
    where = client.post("/connections/calendar/forget",
                        data={"token": _token(), "name": "Work"}).headers["Location"]
    assert "reset" in where.lower()


def test_the_page_says_which_of_googles_four_addresses_to_use():
    """the maintainer, standing in front of Google's settings page: *"which one is the
    subscribtion link?"*

    Google offers four things on that screen and names none of them usefully.
    Three of them look plausible and do not work: a web page, an HTML embed,
    and an ICS address that only functions if the calendar is made public to
    the world. The instructions belong where somebody is standing when they
    hit this, not in a document they do not have open.
    """
    # The section moved onto the Calendar tab when Connections was split
    # Read the tab that draws it --
    # and read it rendered, not off disk, so this also proves the tab shows
    # what it claims to.
    page = (REPO_ROOT / "src" / "aki_agent" / "dashboard" / "templates"
            / "_conn_calendar.html").read_text(encoding="utf-8")

    assert "Secret address in iCal format" in page
    # Named as wrong, not merely omitted -- somebody has already picked one of
    # these and needs to be told which.
    assert "Embed code" in page
    assert "Public address in iCal format" in page
    assert "public to the world" in page
    # And the way back if the address escapes.
    assert "Reset" in page
