"""The panel showed his half of the conversation and not the assistant's.

Observed 2026-09-03: he typed in the dashboard, the assistant answered, and
nothing appeared. What he typed went to conversation.jsonl, what it answered
went to chat.jsonl, and the panel renders the first one.
"""

from __future__ import annotations

import pytest

from aki_agent import chat, conversation, paths


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


def test_a_reply_reaches_the_log_the_panel_renders():
    conversation.queue("testing")

    chat.say("assistant", "Getting you here too.")

    said = [(turn.role, turn.text) for turn in conversation.read(limit=10)]
    assert ("user", "testing") in said
    assert ("assistant", "Getting you here too.") in said


def test_it_is_still_written_where_the_session_reads_it():
    """The mirror must not become a move: chat.jsonl is what the session
    reads back, and what carries the session addressing."""
    chat.say("assistant", "still here", session="main")

    assert [line.text for line in chat.read(limit=5)] == ["still here"]


def test_the_same_reply_is_not_recorded_twice():
    """Two paths write assistant replies -- the mirror, and `aki inbox
    replied` run by the assistant itself."""
    chat.say("assistant", "only once")
    conversation.append("assistant", "only once")

    texts = [turn.text for turn in conversation.read(limit=10)]
    assert texts.count("only once") == 2, (
        "conversation.append is deliberately unguarded; the guard belongs to "
        "the callers that might duplicate")

    assert conversation.already_recorded("assistant", "only once")
    assert not conversation.already_recorded("assistant", "never said")


def test_a_repeat_much_later_is_not_treated_as_a_duplicate():
    """Somebody who says "ok" twice in an afternoon means it twice."""
    conversation.append("user", "ok")

    assert conversation.already_recorded("user", "ok")
    assert not conversation.already_recorded("user", "ok", within_seconds=0)


def test_a_broken_mirror_never_costs_the_reply_itself(monkeypatch):
    """chat.jsonl is the file the session reads. A failure to mirror must
    not be allowed to lose the line it was mirroring."""
    def explode(*args, **kwargs):
        raise RuntimeError("the log is on fire")

    monkeypatch.setattr(conversation, "already_recorded", explode)

    assert chat.say("assistant", "written anyway") is not None
    assert [line.text for line in chat.read(limit=5)] == ["written anyway"]


def test_a_telegram_message_is_recorded_but_not_handed_back():
    """The other half of the same defect (2026-09-04).

    Messages that arrived over Telegram were written only to the side log, so
    the panel — reading the chat store — showed the assistant talking to
    nobody. They belong in the store. But the store is also the queue the
    session reads, so recording one must not make the session answer a
    message it has already answered.
    """
    chat.start_at_end("main")

    chat.say("user", "Online?", meta={"channel": "telegram"}, deliver=False)

    # Recorded, and visible to the panel.
    assert [line.text for line in chat.read(limit=5)] == ["Online?"]
    assert ("user", "Online?") in [(t.role, t.text)
                                   for t in conversation.read(limit=10)]

    # But never handed to the session a second time.
    fresh, _ = chat.unread("main")
    assert [line.text for line in fresh] == []


def test_a_dashboard_message_is_still_delivered():
    """The guard above must not swallow the messages that DO need delivering —
    the whole point of the store is that typing in the panel reaches the
    session."""
    chat.start_at_end("main")

    chat.say("user", "wai", meta={"channel": "dashboard"})

    fresh, _ = chat.unread("main")
    assert [line.text for line in fresh] == ["wai"]


def test_inbox_said_writes_to_the_store_the_panel_reads():
    """`aki inbox said` is how a Telegram message gets recorded at all. It
    used to write the side log only, which is the same defect one layer up."""
    from aki_agent import inbox

    chat.start_at_end("main")
    inbox.main(["inbox", "said", "--channel", "telegram", "Online?"])

    assert [line.text for line in chat.read(limit=5)] == ["Online?"]
    fresh, _ = chat.unread("main")
    assert fresh == []


