"""Web push: the tap on the shoulder that Telegram used to do.

Without this the switch trades an agent that reaches you for one that waits
for you, so the tests that matter are the ones about a notification actually
leaving, and about the whole thing degrading honestly when the optional piece
is not installed.
"""

from __future__ import annotations

import json

import pytest

from aki_agent import notify, paths, push
from aki_agent.config import Config, Notifications


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


def _a_subscription(endpoint: str = "https://push.example/abc") -> dict:
    return {"endpoint": endpoint,
            "keys": {"p256dh": "a-public-key", "auth": "a-secret"}}


# ---------------------------------------------------------------------------
# The keypair — generated here, never obtained from anybody
# ---------------------------------------------------------------------------

def test_the_keypair_is_generated_on_this_machine():
    """Nothing to register is the promise the package is built on."""
    made = push.keys()

    assert made["private"] and made["public"]
    assert push.key_file().exists()


def test_the_keypair_is_generated_once_and_then_kept():
    """A new key on every call would invalidate every subscription."""
    first = push.public_key()
    second = push.public_key()

    assert first == second


def test_only_the_public_half_is_handed_out():
    assert push.public_key() == push.keys()["public"]
    assert push.public_key() != push.keys()["private"]


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------

def test_a_browser_can_ask_to_be_told():
    push.subscribe(_a_subscription(), label="the phone")

    rows = push.listing()

    assert [one.endpoint for one in rows] == ["https://push.example/abc"]
    assert rows[0].label == "the phone"


def test_subscribing_twice_from_one_browser_is_one_device():
    push.subscribe(_a_subscription())
    push.subscribe(_a_subscription())

    assert len(push.listing()) == 1


def test_two_devices_are_two_devices():
    push.subscribe(_a_subscription("https://push.example/phone"))
    push.subscribe(_a_subscription("https://push.example/laptop"))

    assert len(push.listing()) == 2


def test_a_subscription_missing_its_keys_is_refused():
    with pytest.raises(ValueError):
        push.subscribe({"endpoint": "https://push.example/x", "keys": {}})


def test_a_push_endpoint_must_be_https():
    """Anything else is a mistake or somebody pointing this at a listener."""
    with pytest.raises(ValueError) as raised:
        push.subscribe({"endpoint": "http://push.example/x",
                        "keys": {"p256dh": "k", "auth": "a"}})

    assert "https" in str(raised.value)


def test_a_device_can_be_forgotten():
    push.subscribe(_a_subscription())

    assert push.unsubscribe("https://push.example/abc") is True
    assert push.listing() == []
    assert push.unsubscribe("https://push.example/abc") is False


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def test_sending_with_nobody_subscribed_is_not_an_error():
    assert push.send("Aki", "hello") == {"sent": 0, "dropped": 0,
                                         "devices": 0}


def test_a_notification_reaches_every_device(monkeypatch):
    calls = []
    monkeypatch.setattr(push, "_library",
                        lambda: (lambda **kw: calls.append(kw), Exception))
    push.subscribe(_a_subscription("https://push.example/phone"))
    push.subscribe(_a_subscription("https://push.example/laptop"))

    result = push.send("Aki", "the report is ready", url="/chat")

    assert result["sent"] == 2
    payload = json.loads(calls[0]["data"])
    assert payload["title"] == "Aki"
    assert payload["body"] == "the report is ready"
    assert payload["url"] == "/chat"


def test_a_notification_carries_a_tap_not_the_conversation(monkeypatch):
    """The whole message on a lock screen is the conversation on a lock screen."""
    calls = []
    monkeypatch.setattr(push, "_library",
                        lambda: (lambda **kw: calls.append(kw), Exception))
    push.subscribe(_a_subscription())

    push.send("Aki", "x" * 900)

    assert len(json.loads(calls[0]["data"])["body"]) == push.MAX_BODY


def test_a_device_the_service_says_is_gone_is_forgotten(monkeypatch):
    """A list that only grows eventually sends everything eight times."""
    class Gone(Exception):
        response = type("R", (), {"status_code": 410})()

    def refuses(**kwargs):
        raise Gone()

    monkeypatch.setattr(push, "_library", lambda: (refuses, Gone))
    push.subscribe(_a_subscription())

    result = push.send("Aki", "anybody there")

    assert result["dropped"] == 1
    assert push.listing() == []


def test_a_network_blip_does_not_forget_somebodys_phone(monkeypatch):
    class Blip(Exception):
        response = None

    def fails(**kwargs):
        raise OSError("connection reset")

    monkeypatch.setattr(push, "_library", lambda: (fails, Blip))
    push.subscribe(_a_subscription())

    result = push.send("Aki", "anybody there")

    assert result["sent"] == 0
    assert result["dropped"] == 0
    assert len(push.listing()) == 1


# ---------------------------------------------------------------------------
# Degrading honestly
# ---------------------------------------------------------------------------

def test_without_the_optional_piece_it_says_what_to_install(monkeypatch):
    def missing():
        raise push.PushUnavailable(
            "Notifications on your phone need one extra piece. Install it "
            "with:  pip install aki-agent[push]")

    monkeypatch.setattr(push, "_library", missing)

    assert push.available() is False
    with pytest.raises(push.PushUnavailable) as raised:
        push.send("Aki", "hello")

    assert "pip install aki-agent[push]" in str(raised.value)


def test_a_failed_push_never_undoes_a_delivered_message(monkeypatch):
    """The panel holds the message. The push is only the tap."""
    def explodes(*args, **kwargs):
        raise RuntimeError("the push service is down")

    monkeypatch.setattr(push, "send", explodes)

    config = Config()
    config.notifications = Notifications(enabled=True)
    decision = notify.send("this still counts as delivered", config, "file")

    assert decision.deliver is True


def test_delivering_a_message_taps_the_shoulder(monkeypatch):
    taps = []
    monkeypatch.setattr(push, "notify_quietly",
                        lambda title, body, url="/": taps.append(body))

    config = Config()
    config.notifications = Notifications(enabled=True)
    notify.send("the report is ready", config, "file")

    assert taps and "report is ready" in taps[0]


def test_a_held_message_does_not_tap_the_shoulder(monkeypatch):
    """Quiet hours means quiet. A push would be the thing it exists to stop."""
    taps = []
    monkeypatch.setattr(push, "notify_quietly",
                        lambda title, body, url="/": taps.append(body))

    config = Config()
    config.notifications = Notifications(enabled=False)
    notify.send("this one is waiting", config, "file")

    assert taps == []


# ---------------------------------------------------------------------------
# The lock, and the two files that must be outside it
#
# Found on the real machine on 2026-09-01, not reasoned about: both answered
# 200 with the login PAGE, so the browser was handed HTML where it expected
# JavaScript and the service worker never registered. No error anywhere.
# ---------------------------------------------------------------------------

def test_the_service_worker_is_served_as_javascript_not_as_the_login_page(
        tmp_path, monkeypatch):
    from aki_agent.dashboard import create_app

    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as browser:            # no PIN entered
        answer = browser.get("/sw.js")

    assert answer.status_code == 200
    assert "javascript" in answer.headers["Content-Type"]
    assert b"<!doctype html>" not in answer.data.lower()
    assert b"showNotification" in answer.data


def test_the_manifest_is_reachable_before_anybody_has_logged_in():
    from aki_agent.dashboard import create_app

    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as browser:
        answer = browser.get("/manifest.webmanifest")

    assert answer.status_code == 200
    assert "manifest" in answer.headers["Content-Type"]
    assert b"<!doctype html>" not in answer.data.lower()


def test_the_exemption_is_two_files_and_not_a_habit():
    """A canary on the list itself, in the style of the other canaries here.

    Runtime is the wrong place to assert this: on a fresh install with no PIN
    set there is nothing to be let past, so every path answers and the test
    would pass while proving nothing. What actually matters is that the next
    person adding a route does not quietly add a seventh line to the list, so
    the list is what is checked.

    If you are here because this failed: adding to OPEN_TO_EVERYONE means the
    thing you added is readable by anyone who can reach this machine. That is
    right for a manifest and a service worker. It is wrong for anything that
    reads his files.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1]
              / "src" / "aki_agent" / "dashboard" / "app.py"
              ).read_text(encoding="utf-8")

    line = next(one for one in source.splitlines()
                if one.strip().startswith("OPEN_TO_EVERYONE ="))
    tail = source.split("OPEN_TO_EVERYONE =", 1)[1].split(")", 1)[0]

    import re

    quoted = re.findall(r'"([^"]+)"', tail)

    assert sorted(quoted) == sorted([
        "/login", "/login/forgot", "/first-pin", "/static/",
        "/sw.js", "/manifest.webmanifest"]), line
