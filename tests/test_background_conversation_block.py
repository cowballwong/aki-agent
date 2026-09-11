"""Telling the session what it cannot remember, instead of hoping it asks.

The question that prompted it: when a cron job sends a message,
can the user answer it, and will the session know what they are
talking about?

The honest answer at the time was: it works, but by self-discipline. Every
outbound message including scheduled work was already written into the one
conversation log, and `agents/assistant.md` already told the assistant to go
and read it when a message looked like a fragment. Two things were missing,
and neither could be fixed by writing a firmer instruction:

- nothing put it in front of the session, so the mechanism rested on the model
  choosing to look;
- a log cannot tell two open questions apart, because it does not record which
  answers are still outstanding. `approvals` does, and nothing read it here.

Built on `approvals` rather than a store of its own. A second queue of "things
waiting for the user" would be two answers to one question, which is the shape
this codebase keeps paying for.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from aki_agent import approvals, chat, pending_hook


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True)
    return tmp_path / "home"


# ---------------------------------------------------------------------------
# Nothing to say
# ---------------------------------------------------------------------------

def test_it_says_nothing_when_there_is_nothing(home):
    """This runs before every single thing the user says. A line of noise
    here is a line of noise in every turn for ever."""
    assert pending_hook.background_block() == ""


# ---------------------------------------------------------------------------
# Open decisions
# ---------------------------------------------------------------------------

def test_an_open_question_is_put_in_front_of_the_session(home):
    item = approvals.ask(
        "Which flight should I book?", kind="question",
        options=[approvals.Option(key="1", label="the 07:20"),
                 approvals.Option(key="2", label="the 11:45")],
        context="task:flights")

    block = pending_hook.background_block()

    assert item.id in block
    assert "Which flight should I book?" in block
    assert "1=the 07:20" in block


def test_the_way_to_close_it_is_named(home):
    """A block that says "this is open" and not "here is how to close it"
    produces answers that are given to the user and never recorded, which
    leaves the question open for ever and the block growing."""
    approvals.ask("Send it?", kind="question", context="task:x")

    assert "aki_agent.cli answer" in pending_hook.background_block()


def test_an_answered_question_disappears(home):
    item = approvals.ask("Send it?", kind="question", context="task:x")
    assert item.id in pending_hook.background_block()

    approvals.answer(item.id, item.options[0].key)

    assert item.id not in pending_hook.background_block()


def test_waiting_on_somebody_else_is_not_shown(home):
    """`kind="waiting"` is what the user is owed by other people. It is not a
    question addressed to them, so a reply of theirs never answers one, and
    putting it here would be three lines of noise per turn."""
    item = approvals.ask("Chasing the surveyor", kind="waiting",
                         waiting_on="the surveyor")

    assert item.id not in pending_hook.background_block()


# ---------------------------------------------------------------------------
# What was already sent
# ---------------------------------------------------------------------------

def test_recent_scheduled_messages_are_shown_as_a_log(home):
    chat.say("assistant", "Your morning summary: three things today.",
             meta={"origin": "task:morning-summary"})

    block = pending_hook.background_block()

    assert "morning summary" in block
    assert "never send one of them again" in block


def test_a_multi_line_result_is_flattened(home):
    """Scheduled results are often formatted digests. Their newlines pasted
    straight in break the list apart, and the reader can no longer tell where
    one message ends and the next begins."""
    chat.say("assistant", "**Friday**\n\nline two\nline three",
             meta={"origin": "task:day-log"})

    body = pending_hook.background_block()
    inside = [one for one in body.splitlines() if "Friday" in one]

    assert len(inside) == 1
    assert "line three" in inside[0]


def test_an_ordinary_reply_is_not_mistaken_for_scheduled_work(home):
    """Only `origin` beginning `task:` is background. Everything else in the
    log is the conversation the session is already having, and repeating it
    back would be telling somebody what they just said."""
    chat.say("assistant", "Sure, done.", meta={"origin": ""})

    assert pending_hook.background_block() == ""


# ---------------------------------------------------------------------------
# It has to survive everything
# ---------------------------------------------------------------------------

def test_a_broken_store_does_not_break_the_prompt(home, monkeypatch):
    """An exception here is an exception on every prompt, and the symptom is
    an assistant that stopped working for no visible reason."""
    def explode(*a, **k):
        raise RuntimeError("queue is unreadable")

    monkeypatch.setattr(approvals, "open_items", explode)
    monkeypatch.setattr(chat, "read", explode)

    assert pending_hook.background_block() == ""
