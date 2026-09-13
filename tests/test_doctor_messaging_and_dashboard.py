"""The two checks that used to be found out at the launcher.

A user's report, 2026-09-12, on what actually goes wrong most often when this
package installs: the messaging credentials, and the dashboard -- both
discovered when the launcher was opened, days later, rather than when it was
installed.
"""
from __future__ import annotations

import ssl
import urllib.error
import urllib.request

import pytest

from aki_agent import doctor, telegram_setup


@pytest.fixture
def _no_real_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("this test must not touch the network")
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


def _answer(monkeypatch, body):
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return body
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Reply())


def test_no_account_connected_is_a_note_not_a_failure(monkeypatch,
                                                      _no_real_network):
    """Somebody who never wanted Telegram has not broken anything."""
    monkeypatch.setattr(telegram_setup, "read_token", lambda: "")
    monkeypatch.setattr(telegram_setup, "first_allowed", lambda: "")
    check = doctor.check_messaging()
    assert not check.ok and check.warning_only
    assert "connect-telegram" in check.fix


def test_a_revoked_token_is_named_as_such(monkeypatch):
    """401 has one meaning. Say it, not the status code."""
    def refused(*a, **k):
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)
    monkeypatch.setattr(telegram_setup, "read_token", lambda: "t")
    monkeypatch.setattr(telegram_setup, "first_allowed", lambda: "1")
    monkeypatch.setattr(urllib.request, "urlopen", refused)
    check = doctor.check_messaging()
    assert not check.ok and not check.warning_only
    assert "not valid" in check.detail


def test_a_real_token_with_nobody_allowed_fails(monkeypatch):
    """`getMe` passing is not the same as anything being deliverable."""
    _answer(monkeypatch, b'{"ok":true,"result":{"username":"somebot"}}')
    monkeypatch.setattr(telegram_setup, "read_token", lambda: "t")
    monkeypatch.setattr(telegram_setup, "first_allowed", lambda: "")
    check = doctor.check_messaging()
    assert not check.ok and not check.warning_only
    assert "somebot" in check.detail


def test_a_working_account_names_the_bot(monkeypatch):
    _answer(monkeypatch, b'{"ok":true,"result":{"username":"somebot"}}')
    monkeypatch.setattr(telegram_setup, "read_token", lambda: "t")
    monkeypatch.setattr(telegram_setup, "first_allowed", lambda: "4242")
    check = doctor.check_messaging()
    assert check.ok
    assert "somebot" in check.detail and "4242" in check.detail


def test_a_certificate_failure_is_not_reported_as_being_offline(monkeypatch):
    """Found on a test Mac, 2026-09-12.

    The first version said "if this machine is offline, ignore it" for
    anything that was not an HTTP error, and then said exactly that over a
    CERTIFICATE_VERIFY_FAILED on a machine that was online. The advice was
    wrong and pointed away from the fault, which is the one thing a line in
    `doctor` must never do.
    """
    def intercepted(*a, **k):
        raise urllib.error.URLError(ssl.SSLCertVerificationError(
            1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
               "self-signed certificate in certificate chain"))
    monkeypatch.setattr(telegram_setup, "read_token", lambda: "t")
    monkeypatch.setattr(telegram_setup, "first_allowed", lambda: "1")
    monkeypatch.setattr(urllib.request, "urlopen", intercepted)

    check = doctor.check_messaging()
    assert not check.ok and check.warning_only
    assert "certificate" in check.detail
    assert "offline" not in check.fix.lower()


def test_the_dashboard_check_asks_for_a_page():
    """Not "is there a file", not "is the bit set" -- does a page come back."""
    check = doctor.check_dashboard_serves()
    assert check.ok, f"{check.detail} / {check.fix}"
    assert "serves its first page" in check.detail


def test_a_dashboard_that_will_not_start_says_so_and_not_something_else(
        monkeypatch):
    """The two failures are different sentences and must stay different."""
    from aki_agent.dashboard import app as app_module

    monkeypatch.setattr(app_module, "create_app",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("config exploded")))
    check = doctor.check_dashboard_serves()
    assert not check.ok
    assert "will not start" in check.detail
    assert "first page" not in check.detail
