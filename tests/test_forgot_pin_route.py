"""The reset route itself, not just the counter behind it.

The counter had tests the moment it existed. The bug was never in a counter
-- it was that the route called none, so these go through the door the way an
attacker would: by POSTing to it.
"""
from __future__ import annotations

import pytest

from aki_agent.dashboard.app import SESSION_TOKEN


def _press_forgot(browser, host=None):
    """What a page pressing the button sends."""
    headers = {"Host": host} if host else {}
    return browser.post("/login/forgot", data={"token": SESSION_TOKEN},
                        headers=headers)


def test_the_first_press_resets(dashboard_client):
    answer = _press_forgot(dashboard_client)
    assert answer.status_code == 200
    page = answer.get_data(as_text=True)
    assert "already reset" not in page


def test_pressing_it_again_immediately_does_not_reset_again(dashboard_client):
    """Before 2026-09-06 every press through here invalidated the PIN the
    owner had just been given. A loop meant they never got in again."""
    _press_forgot(dashboard_client)
    second = _press_forgot(dashboard_client)

    page = second.get_data(as_text=True)
    assert "already reset" in page, page[:400]


def test_the_pin_does_not_change_on_the_refused_press(dashboard_client,
                                                      monkeypatch):
    """The message is not the protection -- not resetting is."""
    from aki_agent import dashboard_auth

    _press_forgot(dashboard_client)
    after_first = dashboard_auth._stored()

    _press_forgot(dashboard_client)
    assert dashboard_auth._stored() == after_first


def test_a_reset_cannot_be_asked_for_from_away(dashboard_client, monkeypatch):
    """A reset lands on the phone or the Desktop of somebody at the machine.

    Asked for from a tunnel it cannot help the person asking, and it can lock
    out the person who is there -- so it is the one thing remote access does
    not carry.
    """
    from aki_agent import exposure

    monkeypatch.setattr(exposure, "allows",
                        lambda host: "away.example" in (host or ""))
    answer = _press_forgot(dashboard_client, host="away.example")

    page = answer.get_data(as_text=True)
    assert "only be reset from the computer" in page, page[:400]


def test_a_press_with_no_token_is_refused(dashboard_client):
    """It takes no password, so the CSRF token is the only thing between it
    and any web page the user happens to have open."""
    answer = dashboard_client.post("/login/forgot", data={})
    assert answer.status_code == 403
