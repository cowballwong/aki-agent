"""The mirror, checked at the wiring rather than the mechanism.

`conversation.py` passed its own tests from the moment it was written. It was
still half a mirror: outbound messages appeared because they pass through the
notification gate, and nothing on earth put an inbound message into it or took
a queued one out.

That was the fifth defect of the same shape in this build. So these tests do
not check that the functions work — they check that something reaches them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import conversation, inbox, paths, schedule

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


# ---------------------------------------------------------------------------
# Something must be able to take the queue
# ---------------------------------------------------------------------------

def test_queued_messages_can_actually_be_collected():
    conversation.queue("look at the budget")
    conversation.queue("and book the exam")

    text = inbox.collect_pending()

    assert "look at the budget" in text
    assert "and book the exam" in text
    assert conversation.pending_count() == 0


def test_collecting_an_empty_queue_says_so():
    assert inbox.collect_pending() == "Nothing waiting."


def test_the_collected_messages_are_framed_as_the_user_speaking():
    """An agent reading this must not mistake it for a document."""
    conversation.queue("do the thing")
    text = inbox.collect_pending()
    assert "from your user" in text


# ---------------------------------------------------------------------------
# Something must be able to put an inbound message in
# ---------------------------------------------------------------------------

def test_an_inbound_message_can_be_recorded_with_its_channel():
    inbox.main(["inbox", "said", "chase them again", "--channel", "telegram"])

    turns = conversation.read()
    assert turns[-1].role == "user"
    assert turns[-1].text == "chase them again"
    assert turns[-1].channel == "telegram"


def test_a_reply_typed_in_a_session_can_be_recorded():
    inbox.main(["inbox", "replied", "chased", "--channel", "telegram"])

    turns = conversation.read()
    assert turns[-1].role == "assistant"
    assert turns[-1].channel == "telegram"


def test_recording_nothing_is_refused_rather_than_writing_a_blank_turn():
    assert inbox.main(["inbox", "said"]) == 2
    assert conversation.read() == []


# ---------------------------------------------------------------------------
# The instructions ARE the wiring, so they are tested too
# ---------------------------------------------------------------------------

def test_the_assistant_is_told_to_collect_the_queue():
    """Without this line, messages typed in the dashboard queue forever.

    The persona file is not documentation here — it is the only thing that
    connects a working mechanism to a running assistant. Deleting the line
    would silently break the feature, so the line is tested.
    """
    persona = (REPO_ROOT / "agents" / "assistant.md").read_text(
        encoding="utf-8")

    assert "aki_agent.inbox pending" in persona
    assert "start of every session" in persona


def test_the_assistant_is_told_to_record_inbound_messages():
    persona = (REPO_ROOT / "agents" / "assistant.md").read_text(
        encoding="utf-8")

    assert "aki_agent.inbox said" in persona
    assert "Do this without being asked" in persona


def test_a_scheduled_task_collects_the_queue_as_a_backstop():
    """Instructions are followed reliably, not mechanically.

    So there is also a scheduled task. Belt and braces is right here: the
    failure mode without it is a message the user typed and watched be
    ignored, which destroys trust in the whole chat view.
    """
    task = schedule.get_task("collect-messages")

    assert task is not None
    assert [one.kind for one in task.triggers] == ["interval"]


def test_the_collect_task_runs_a_command_that_actually_works():
    """The stored prompt is a sentinel; what matters is what it becomes.

    THE BUG THIS EXISTS FOR (2026-08-20)
    ------------------------------------
    The prompt used to be the literal `python -m aki_agent.inbox pending`, and
    the old version of this test asserted exactly that string was present --
    so it passed, for months, while the command failed on every real install.
    The package lives in the assistant's virtual environment and a bare
    `python` started in the user's workspace is not that interpreter.

    A failed command inside a prompt raises nothing: the model narrates it and
    the task reports success. So the dashboard's messages queued forever, and
    the symptom that eventually reached the user was "I typed in the chat
    panel and nothing happened".

    Asserting on the literal text was the mistake. This asserts on the
    resolved command, which is the thing that has to be right.
    """
    from aki_agent import engine, tasks

    resolved = tasks.resolve_prompt(schedule.get_task("collect-messages"))

    assert "aki_agent.inbox" in resolved
    assert "pending" in resolved
    assert "_bootstrap.py" in resolved,         "it must go through the bootstrap, not `python -m`"
    assert "python -m aki_agent" not in resolved
    assert str(engine.bootstrap()) in resolved


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------

def test_the_whole_round_trip(monkeypatch):
    """Type in the dashboard -> assistant collects -> assistant replies ->
    the reply is visible in the dashboard."""
    from aki_agent import notify
    from aki_agent.config import Config, Notifications

    config = Config()
    config.notifications = Notifications(enabled=True)

    # Rewritten 2026-09-01: the round trip no longer goes through a queue the
    # assistant has to be told to collect. The dashboard writes into the
    # conversation, the channel server hands the line to the session it is
    # addressed to, and the answer comes back to the same file.
    from aki_agent import chat

    # 1. the user types into the dashboard
    chat.say("user", "what is outstanding?", session=chat.MAIN)

    # 2. the session is handed it -- addressed to it, and only once
    fresh, offset = chat.unread(chat.MAIN)
    assert [line.text for line in fresh] == ["what is outstanding?"]
    chat.mark_read(chat.MAIN, offset)
    assert chat.unread(chat.MAIN)[0] == []

    # 3. the assistant answers through the notification system
    notify.send("Two things: the report and the fees.", config, "file")

    # 4. both sides are in one conversation, in order, in one file
    turns = chat.read()
    assert [turn.role for turn in turns] == ["user", "assistant"]
    assert "outstanding" in turns[0].text
    assert "Two things" in turns[1].text


# ---------------------------------------------------------------------------
# The canary for the whole class, not just the instance that was noticed
# ---------------------------------------------------------------------------

def _executable_strings(source: Path) -> list[tuple[int, str]]:
    """String literals a file will actually emit, docstrings excluded.

    Parsed, not grepped, for the same reason the vocabulary canary in
    `test_two_configs.py` is parsed: prose explaining a mistake must be able
    to name the mistake, and a regular expression cannot tell the difference
    between an explanation and an instruction.
    """
    import ast

    tree = ast.parse(source.read_text(encoding="utf-8"))

    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and body:
            first = body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstrings.add(id(first.value))

    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings):
            found.append((getattr(node, "lineno", 0), node.value))
    return found


def test_no_shipped_instruction_tells_anyone_to_run_python_dash_m():
    """`python -m aki_agent.…` does not work on an install and must not be
    printed, written or prompted anywhere.

    The package lives in the assistant's own virtual environment. A bare
    `python`, started in the user's workspace or typed into their shell, is a
    different interpreter and reports *No module named 'aki_agent'*.

    Three shipped places said it — the agent's brief, the CLAUDE.md written
    into the user's workspace, and the scheduled task whose entire job is
    collecting messages typed into the dashboard. The last of those did
    nothing every half hour for months and reported success each time, because
    a command that fails inside a prompt is narrated, not raised. The symptom
    that finally surfaced was a user typing into the chat panel and watching
    nothing happen.

    Fixing the three that were noticed is not the fix. This is: the pattern
    cannot come back anywhere a person or a model is expected to act on it.
    `specialists._safe_key` taught this codebase the same lesson once already
    — a fix applied to an instance is not applied to the class.
    """
    root = Path(__file__).resolve().parents[1]
    bad = "python -m aki_agent"
    offences: list[str] = []

    for path in (root / "src").rglob("*.py"):
        for number, text in _executable_strings(path):
            if bad in text:
                offences.append(f"{path.relative_to(root)}:{number}")

    # Markdown a model follows. Everything in it is an instruction; there is
    # no docstring to be exempt.
    for path in (list((root / "agents").rglob("*.md"))
                 + list((root / "skills").rglob("SKILL.md"))):
        for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            if bad in line:
                offences.append(f"{path.relative_to(root)}:{number}")

    assert not offences, (
        "these would have someone run a command that fails on a real install. "
        "Use `engine.how_to_run(...)`, or `${CLAUDE_PLUGIN_ROOT}/bin/"
        "_bootstrap.py` in a plugin file: " + ", ".join(offences))


# ---------------------------------------------------------------------------
# Telegram as the main way in (reported 2026-08-20)
# ---------------------------------------------------------------------------

def test_scheduled_results_go_where_the_user_reads_not_to_a_file():
    """They defaulted to the `file` channel, so a task did its work and then
    told a file about it. The maintainer is on a phone; a result he never sees is a
    result that did not happen."""
    from aki_agent import channels

    class Connected:
        name = "telegram"

        def available(self):
            return True

        def deliver(self, message):        # pragma: no cover
            return True, "sent"

    channels.reset_to_defaults()
    channels.register(Connected())
    try:
        assert channels.best() == "telegram"
    finally:
        channels.reset_to_defaults()


def test_it_falls_back_to_the_file_channel_when_telegram_is_not_connected():
    """Most installs never connect anything, and that is a normal state — not
    a reason for a scheduled result to vanish."""
    from aki_agent import channels

    channels.reset_to_defaults()
    assert channels.best() == "file"


def test_somebody_who_switched_telegram_off_meant_it():
    from aki_agent import channels
    from aki_agent.config import Config, Notifications

    class Connected:
        name = "telegram"

        def available(self):
            return True

        def deliver(self, message):        # pragma: no cover
            return True, "sent"

    channels.reset_to_defaults()
    channels.register(Connected())
    config = Config(notifications=Notifications(channels={"telegram": False}))
    try:
        assert channels.best(config) == "file"
    finally:
        channels.reset_to_defaults()


def test_the_assistant_is_told_to_read_the_thread_before_a_one_word_reply():
    """A scheduled task sends its result from its own run, hours earlier. A
    reply of "yes" is very often about something this session never sent."""
    persona = (Path(__file__).resolve().parents[1]
               / "agents" / "assistant.md").read_text(encoding="utf-8")

    assert "aki_agent.inbox show" in persona
    assert "Read first, then answer" in persona


def test_the_assistant_is_told_not_to_recite_what_it_read():
    """the maintainer typed "hi" and got the state of the handoff, that no house rules
    were set, and that nothing was waiting.

    Reading those is right; reporting them back is not. Every one of those
    lines is the *absence* of news, which is the same defect that made a
    scheduled task message his phone to say it had nothing to say — the same
    rule, one layer up.
    """
    persona = (Path(__file__).resolve().parents[1]
               / "agents" / "assistant.md").read_text(encoding="utf-8")

    assert "Read them silently" in persona
    assert "Match the size of your reply" in persona
    assert "absence of news is not news" in persona
    # And the exception, so it does not become uselessly silent.
    assert "Being asked is different from being greeted" in persona
