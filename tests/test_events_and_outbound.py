"""Phase 1 of "alive at install": the event bus and a real outbound channel.

These two are grouped because they are the same failure seen from two sides.
Before them, an assistant could neither *say* anything to its user when they
were away, nor answer the question "what have you been doing?" — while every
mechanism for both was written, tested and present.

Nothing here touches the network. The delivery test replaces the transport, so
what is proved is that the channel builds the right request and honours the
answer — not that Telegram is up.
"""

from __future__ import annotations

import json

import pytest

from aki_agent import channels, conversation, events, memory, notify, paths


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    channels.reset_to_defaults()
    yield


# ---------------------------------------------------------------------------
# The bus


def test_an_event_survives_a_write_and_reads_back():
    events.record("task", "Morning summary ran", source="schedule",
                  detail={"seconds": 12})
    [entry] = events.read()

    assert entry.kind == "task"
    assert entry.text == "Morning summary ran"
    assert entry.source == "schedule"
    assert entry.detail["seconds"] == 12


def test_writing_an_event_never_raises_whatever_happens(monkeypatch):
    """Rule 1. The diary must never be the reason something else fails."""
    def explode(*args, **kwargs):
        raise OSError("the disk is full")

    monkeypatch.setattr(events.atomic, "append_line", explode)
    events.record("note", "this must not raise")          # no assertion needed


def test_a_secret_pasted_into_an_event_is_masked():
    """Built at runtime rather than written out: a literal that looks like a
    credential fails the repo-wide scan, which is exactly what it is for."""
    looks_like_a_key = "Bearer " + ("k9" * 12) + "Qz"

    events.record("note", f"the header was {looks_like_a_key}")
    [entry] = events.read()
    assert "k9k9k9" not in entry.text


def test_a_corrupt_line_is_skipped_not_fatal():
    events.record("note", "good one")
    with events.event_file().open("a", encoding="utf-8") as handle:
        handle.write("{ this is not json\n")
    events.record("note", "another good one")

    texts = [entry.text for entry in events.read()]
    assert texts == ["another good one", "good one"]


def test_the_cursor_returns_only_what_is_new():
    events.record("note", "first")
    cursor = events.line_count()
    events.record("note", "second")

    fresh = events.read(since_line=cursor)
    assert [entry.text for entry in fresh] == ["second"]


def test_summary_says_nothing_yet_in_words():
    """An empty panel reads as broken; a sentence reads as calm."""
    assert "Nothing recorded yet" in events.summary()


# ---------------------------------------------------------------------------
# The outbound channel


def test_telegram_is_registered_even_before_an_account_exists():
    """Unregistered produced "there is no channel called telegram", which
    reads as a bug in the software rather than a missing account."""
    assert "telegram" in channels.registered_names()
    assert channels.get("telegram").available() is False


def test_it_sends_the_right_request_and_reports_success(monkeypatch):
    sent = {}

    class FakeResponse:
        def read(self):
            return json.dumps({"ok": True}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=0):
        sent["url"] = request.full_url
        sent["body"] = json.loads(request.data.decode())
        return FakeResponse()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    channel = channels.TelegramChannel(token="T0KEN", chat_id="42")
    delivered, why = channel.deliver(channels.Message(text="the roof leaks"))

    assert delivered, why
    assert sent["body"] == {"chat_id": "42", "text": "the roof leaks",
                            "parse_mode": "HTML"}
    assert "sendMessage" in sent["url"]


def test_a_refusal_is_reported_with_the_reason_not_just_a_code(monkeypatch):
    """A status code alone sends people looking in the wrong place."""
    import urllib.error
    import urllib.request

    def refuse(request, timeout=0):
        raise urllib.error.HTTPError(
            request.full_url, 403, "Forbidden", {},
            __import__("io").BytesIO(b'{"description":"bot was blocked"}'))

    monkeypatch.setattr(urllib.request, "urlopen", refuse)

    delivered, why = channels.TelegramChannel(
        token="T", chat_id="1").deliver(channels.Message(text="hello"))

    assert not delivered
    assert "blocked" in why


def test_an_unconnected_account_explains_what_to_do():
    delivered, why = channels.TelegramChannel().deliver(
        channels.Message(text="hello"))
    assert not delivered
    assert "/connect-telegram" in why


def test_a_delivered_message_lands_on_the_bus(monkeypatch):
    """So "what have you been doing" includes what it told you."""
    class Fake:
        name = "telegram"

        def available(self):
            return True

        def deliver(self, message):
            return True, "sent"

    channels.register(Fake())
    config = __import__("aki_agent.config", fromlist=["Config"]).Config()
    notify.send("the meeting moved to Thursday", config, "telegram")

    said = [entry for entry in events.read() if entry.kind == "said"]
    assert said and "Thursday" in said[0].text


def test_something_typed_in_the_dashboard_lands_on_the_bus():
    conversation.queue("can you look at the drainage drawing")
    heard = [entry for entry in events.read() if entry.kind == "heard"]
    assert heard and "drainage" in heard[0].text


# ---------------------------------------------------------------------------
# How a message LOOKS when it lands
#
# It arrived reading `**24 Aug —**`
# because nothing told Telegram the text was formatted.
# ---------------------------------------------------------------------------


def test_emphasis_arrives_as_bold_not_as_asterisks(monkeypatch):
    sent = {}

    class FakeResponse:
        def read(self):
            return json.dumps({"ok": True}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=0):
        sent["body"] = json.loads(request.data.decode())
        return FakeResponse()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    channel = channels.TelegramChannel(token="T0KEN", chat_id="42")
    channel.deliver(channels.Message(text="**24 Aug** — two tasks failed"))

    assert "<b>24 Aug</b>" in sent["body"]["text"]
    assert "**" not in sent["body"]["text"]


def test_a_markup_problem_never_costs_the_message(monkeypatch):
    """Delivery beats presentation.

    The failure mode of a markup bug is Telegram refusing the whole message —
    which turns a cosmetic problem into a silent one. So a refusal is retried
    with no formatting at all.
    """
    import urllib.error
    import urllib.request

    tries = []

    class FakeResponse:
        def read(self):
            return json.dumps({"ok": True}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fussy_urlopen(request, timeout=0):
        body = json.loads(request.data.decode())
        tries.append(body)
        if body.get("parse_mode"):
            raise urllib.error.HTTPError(
                request.full_url, 400, "Bad Request", {}, None)
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fussy_urlopen)

    channel = channels.TelegramChannel(token="T0KEN", chat_id="42")
    delivered, why = channel.deliver(channels.Message(text="**bold** and 5<6"))

    assert delivered, why
    assert len(tries) == 2, "it must try again without formatting"
    assert "parse_mode" not in tries[1]
    assert tries[1]["text"] == "**bold** and 5<6", (
        "the fallback sends what the person wrote, unescaped")


def test_a_network_failure_is_not_retried_as_a_markup_problem(monkeypatch):
    """Sending the same thing again unformatted fails the same way."""
    import urllib.error
    import urllib.request

    tries = []

    def unreachable(request, timeout=0):
        tries.append(1)
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(urllib.request, "urlopen", unreachable)

    channel = channels.TelegramChannel(token="T0KEN", chat_id="42")
    delivered, why = channel.deliver(channels.Message(text="anything"))

    assert delivered is False
    assert len(tries) == 1, "a dead network is not a formatting problem"
    assert "could not reach" in why
