"""Signing a Gmail mailbox in with Google instead of an app password.

WHY (reported 2026-08-29)
-----------------------

Calendar had OAuth because writing to a diary cannot be done any other way.
Mail could always be done with an app password, so it was — and the machinery
for signing in sat inside `google_calendar.py` where mail could not reach it.

What these tests hold down is not the happy path (which needs Google) but the
three things that decide whether this is safe and honest:

  * connecting a diary must not hand over a mailbox, and the other way round;
  * a mailbox only signs in with Google when the token is *that mailbox's*;
  * an app password still works, unchanged, for everybody who has one.
"""

from __future__ import annotations

import pytest

from aki_agent import secrets as secrets_module
from aki_agent.connectors import google_account, mail


@pytest.fixture(autouse=True)
def store(monkeypatch):
    """A credential store in memory, so no test reads the real machine."""
    kept: dict[str, str] = {}
    monkeypatch.setattr(secrets_module, "set_secret",
                        lambda key, value: kept.__setitem__(key, value) or "")
    monkeypatch.setattr(secrets_module, "get_secret", lambda key: kept.get(key))
    monkeypatch.setattr(secrets_module, "delete_secret",
                        lambda key: kept.pop(key, None) is not None)
    return kept


# ---------------------------------------------------------------------------
# The two grants are separate
# ---------------------------------------------------------------------------

def test_connecting_the_calendar_does_not_connect_the_mailbox(store):
    secrets_module.set_secret(google_account.CALENDAR.refresh_key, "token")
    assert google_account.connected(google_account.CALENDAR) is True
    assert google_account.connected(google_account.GMAIL) is False


def test_signing_out_of_one_leaves_the_other_alone(store):
    secrets_module.set_secret(google_account.CALENDAR.refresh_key, "one")
    secrets_module.set_secret(google_account.GMAIL.refresh_key, "two")

    google_account.disconnect(google_account.GMAIL)

    assert google_account.connected(google_account.GMAIL) is False
    assert google_account.connected(google_account.CALENDAR) is True


def test_the_two_ask_for_different_permissions():
    """The whole reason they are separate grants."""
    assert google_account.CALENDAR.scope != google_account.GMAIL.scope
    assert "calendar" in google_account.CALENDAR.scope
    assert "mail.google.com" in google_account.GMAIL.scope
    # The calendar's scope is the narrow one it has always been, not widened
    # on the way through this refactor.
    assert google_account.CALENDAR.scope.endswith("calendar.events")


def test_the_client_itself_is_shared():
    """One registration, several permissions -- that part is deliberate."""
    from aki_agent.connectors import google_calendar

    assert google_calendar.KEY_CLIENT_ID == google_account.KEY_CLIENT_ID
    assert google_calendar.KEY_REFRESH == google_account.CALENDAR.refresh_key


# ---------------------------------------------------------------------------
# Which mailbox a token belongs to
# ---------------------------------------------------------------------------

def _sign_gmail_in(address: str) -> None:
    secrets_module.set_secret(google_account.GMAIL.refresh_key, "token")
    secrets_module.set_secret(google_account.GMAIL.address_key, address)


def test_a_mailbox_uses_google_when_the_token_is_its_own(store):
    _sign_gmail_in("someone@gmail.com")
    assert mail.signs_in_with_google(
        mail.Account(address="someone@gmail.com")) is True


def test_a_token_from_a_different_account_is_not_used(store):
    """The failure this design exists to avoid.

    Gmail refuses a token belonging to another address with a bare
    authentication error naming neither, so guessing here would produce the
    least debuggable failure in the package.
    """
    _sign_gmail_in("someone@gmail.com")
    assert mail.signs_in_with_google(
        mail.Account(address="somebody-else@gmail.com")) is False


def test_the_address_is_matched_regardless_of_case(store):
    _sign_gmail_in("Someone@Gmail.com")
    assert mail.signs_in_with_google(
        mail.Account(address="someone@gmail.com")) is True


def test_a_token_with_no_address_is_not_used_for_anything(store):
    """Half a fact is not a fact.

    A refresh token with no address recorded could belong to any mailbox on
    the machine; using it for the first one would be a guess.
    """
    secrets_module.set_secret(google_account.GMAIL.refresh_key, "token")
    assert mail.signs_in_with_google(
        mail.Account(address="someone@gmail.com")) is False


def test_nothing_signed_in_means_the_app_password_path(store):
    assert mail.signs_in_with_google(
        mail.Account(address="someone@gmail.com")) is False


def test_a_credential_store_that_will_not_answer_means_no(monkeypatch):
    """Over SSH the store raises rather than replying.

    It must read as "no Google sign-in", never as an exception in the middle
    of fetching mail. This is the same trap that made `aki inspect` report
    two working calendar subscriptions as unconfigured.
    """
    def refuse(_key):
        raise OSError("the credential store is unreachable")

    monkeypatch.setattr(secrets_module, "get_secret", refuse)
    assert mail.signs_in_with_google(
        mail.Account(address="someone@gmail.com")) is False


# ---------------------------------------------------------------------------
# The login string itself
# ---------------------------------------------------------------------------

def test_the_login_string_is_the_xoauth2_one_google_documents(store,
                                                              monkeypatch):
    _sign_gmail_in("someone@gmail.com")
    monkeypatch.setattr(google_account, "access_token", lambda _s: "ya29.abc")

    line = mail._google_login_string(mail.Account(address="someone@gmail.com"))

    assert line == "user=someone@gmail.com\x01auth=Bearer ya29.abc\x01\x01"


def test_the_address_is_read_out_of_googles_id_token():
    """How the mailbox becomes known without a second API call."""
    import base64
    import json

    def part(payload: dict) -> str:
        raw = json.dumps(payload).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    token = f"header.{part({'email': 'someone@gmail.com'})}.signature"
    assert google_account._address_in(token) == "someone@gmail.com"


@pytest.mark.parametrize("rubbish", ["", "not-a-token", "a.b", None,
                                     "a.!!!!.c"])
def test_an_unreadable_id_token_yields_no_address(rubbish):
    """It is used for one thing, so it fails to nothing rather than throwing."""
    assert google_account._address_in(rubbish) == ""


def test_an_unknown_service_is_refused_rather_than_defaulted():
    """A typo must not quietly ask Google for the calendar instead."""
    with pytest.raises(google_account.GoogleError):
        google_account.service("drive-someday")


# ---------------------------------------------------------------------------
# What the IMAP session actually does
# ---------------------------------------------------------------------------

class _FakeImap:
    """Enough of imaplib to record which way it was asked to sign in."""

    def __init__(self, *args, **kwargs):
        self.logged_in_with = None
        self.authenticated_with = None
        _FakeImap.made = self

    def login(self, username, password):
        self.logged_in_with = (username, password)

    def authenticate(self, mechanism, responder):
        self.authenticated_with = (mechanism, responder(None))


@pytest.fixture()
def fake_imap(monkeypatch):
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL",
                        lambda *a, **k: _FakeImap(*a, **k))
    return _FakeImap


def test_a_google_signed_mailbox_authenticates_with_a_token(store, fake_imap,
                                                            monkeypatch):
    _sign_gmail_in("someone@gmail.com")
    monkeypatch.setattr(google_account, "access_token", lambda _s: "ya29.abc")

    account = mail.Account(address="someone@gmail.com", provider_key="gmail")
    connection = mail._connect(account)

    mechanism, response = connection.authenticated_with
    assert mechanism == "XOAUTH2"
    assert response == b"user=someone@gmail.com\x01auth=Bearer ya29.abc\x01\x01"
    assert connection.logged_in_with is None, "it also sent a password"


def test_an_app_password_mailbox_is_untouched_by_any_of_this(store, fake_imap):
    """The path almost everybody is on, and it must not have moved."""
    account = mail.Account(address="someone@example.com",
                           imap_host="imap.example.com")
    secrets_module.set_secret(account.secret_key, "app-password")

    connection = mail._connect(account)

    assert connection.logged_in_with == ("someone@example.com", "app-password")
    assert connection.authenticated_with is None


def test_a_google_mailbox_needs_no_app_password_to_connect(store, fake_imap,
                                                           monkeypatch):
    """Before this, no password meant a refusal before any connection."""
    _sign_gmail_in("someone@gmail.com")
    monkeypatch.setattr(google_account, "access_token", lambda _s: "ya29.abc")
    account = mail.Account(address="someone@gmail.com", provider_key="gmail")

    assert account.password() is None
    mail._connect(account)          # must not raise MailError


# ---------------------------------------------------------------------------
# What `aki inspect` says about all this
# ---------------------------------------------------------------------------

def test_inspect_lists_every_google_permission_separately(store):
    """`inspect` answers "what else can it reach", so it has to say which.

    "Connected to Google" would be the wrong answer now that there are three
    grants: somebody checking months later needs to see that mail is on and
    files are not.
    """
    from aki_agent import inspect_report

    secrets_module.set_secret(google_account.GMAIL.refresh_key, "token")

    rows = {one["service"]: one for one in inspect_report._google()}

    assert set(rows) == {"calendar", "gmail", "drive"}
    assert rows["gmail"]["connected"] is True
    assert rows["calendar"]["connected"] is False
    assert rows["drive"]["connected"] is False


def test_inspect_never_prints_the_mailbox_address(store):
    """Everything this report prints lands in a session transcript."""
    from aki_agent import inspect_report

    _sign_gmail_in("someone@gmail.com")
    printed = inspect_report.render({"google": inspect_report._google()})

    assert "someone@gmail.com" not in printed
    assert "Gmail" in printed


def test_a_store_that_will_not_answer_is_unknown_not_off(monkeypatch):
    """Reporting "not connected" for an unreadable store is the SSH trap."""
    from aki_agent import inspect_report

    def refuse(_key):
        raise OSError("the credential store is unreachable")

    monkeypatch.setattr(secrets_module, "get_secret", refuse)
    rows = {one["service"]: one for one in inspect_report._google()}
    assert rows["gmail"]["connected"] is None
