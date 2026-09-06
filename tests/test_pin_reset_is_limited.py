"""The one door in the dashboard that takes no password.

`/login/forgot` cannot ask for the PIN -- it is what you press when the PIN
is the thing you have lost. That made it, until 2026-09-06, the only
unauthenticated write in the whole dashboard, and it had no limit of any kind.

Nothing here is about guessing. The attack is repetition: every press throws
away the PIN the owner was just sent, so a loop means they can never log in
again, however many times they read the new one off their phone.
"""
from __future__ import annotations

import time

import pytest

from aki_agent import dashboard_auth


@pytest.fixture(autouse=True)
def _own_folder(tmp_path, monkeypatch):
    """Counters in a folder this test owns, never the real one."""
    from aki_agent import paths
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    yield


def test_a_reset_is_allowed_when_none_has_happened():
    may, wait = dashboard_auth.reset_allowed()
    assert may and wait == 0


def test_a_second_reset_straight_away_is_refused():
    dashboard_auth.record_reset()
    may, wait = dashboard_auth.reset_allowed()
    assert not may
    assert 0 < wait <= dashboard_auth.RESET_EVERY_SECONDS


def test_the_door_opens_again_after_the_wait():
    dashboard_auth.record_reset(
        now=time.time() - dashboard_auth.RESET_EVERY_SECONDS - 1)
    may, _ = dashboard_auth.reset_allowed()
    assert may


def test_a_hundred_presses_still_only_reset_once():
    """The shape of the actual attack, written as the actual attack."""
    allowed = 0
    for _ in range(100):
        may, _ = dashboard_auth.reset_allowed()
        if may:
            allowed += 1
            dashboard_auth.record_reset()
    assert allowed == 1


def test_a_reset_forgives_the_failed_logins_before_it():
    """Otherwise a legitimate reset hands somebody a new PIN and a door that
    is still bolted from the last twenty wrong guesses."""
    for _ in range(dashboard_auth.FREE_TRIES + 20):
        dashboard_auth.record_failure()
    assert dashboard_auth.locked_out()[0]

    dashboard_auth.clear_failures()
    assert not dashboard_auth.locked_out()[0]


def test_a_count_that_cannot_be_written_raises_rather_than_passing(tmp_path,
                                                                   monkeypatch):
    """`record_reset` must not fail quietly.

    The login throttle deliberately reports a failed write and lets the
    caller decide, because at a keyboard the worst case is one person typing.
    A reset has no such consolation: if the count cannot be kept there is no
    limit at all, and the route refuses instead.
    """
    from aki_agent import atomic

    def cannot_write(*args, **kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(atomic, "write_text", cannot_write)
    with pytest.raises(Exception):
        dashboard_auth.record_reset()
