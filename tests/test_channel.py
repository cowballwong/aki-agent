"""The local channel: one chat store, and the server that wakes a session.

This is the piece that lets Telegram go. Two things have to hold or the whole
2d design is unsound: a message must reach the session it is addressed to and
no other, and it must not be delivered twice or lost when the agent restarts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aki_agent import channel_server, chat, paths


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    monkeypatch.delenv(chat.SESSION_ENV, raising=False)
    paths.ensure_app_dirs()
    yield


def _frames(monkeypatch) -> list[dict]:
    """Capture what the server would put on stdout."""
    sent: list[dict] = []
    monkeypatch.setattr(channel_server, "_send", sent.append)
    return sent


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def test_both_directions_land_in_one_file():
    """The August bug was two stores kept in step by convention. One store."""
    chat.say("user", "are you there")
    chat.say("assistant", "yes")

    lines = chat.read()

    assert [one.role for one in lines] == ["user", "assistant"]
    assert [one.text for one in lines] == ["are you there", "yes"]
    assert chat.chat_file().exists()


def test_a_secret_pasted_into_the_conversation_is_redacted():
    """A chat log is exactly where somebody pastes a key without thinking."""
    chat.say("user", "my token is sk-ant-api03-" + "A" * 40)

    assert "sk-ant-api03-" + "A" * 40 not in chat.read()[0].text


def test_an_empty_message_is_not_recorded():
    assert chat.say("user", "   ") is None
    assert chat.read() == []


def test_a_role_that_is_not_a_side_of_the_conversation_is_refused():
    with pytest.raises(ValueError):
        chat.say("system", "quietly steering things")


# ---------------------------------------------------------------------------
# Addressing — the reason a queue can have several readers and a bot cannot
# ---------------------------------------------------------------------------

def test_a_clone_is_handed_only_its_own_messages():
    chat.say("user", "main, do this", session="main")
    chat.say("user", "david-2, do that", session="david-2")

    for_main, _ = chat.unread("main")
    for_clone, _ = chat.unread("david-2")

    assert [one.text for one in for_main] == ["main, do this"]
    assert [one.text for one in for_clone] == ["david-2, do that"]


def test_a_session_is_not_handed_its_own_replies():
    """Only what the person typed wakes an agent. Otherwise it answers itself."""
    chat.say("user", "hello", session="main")
    chat.say("assistant", "hello back", session="main")

    fresh, _ = chat.unread("main")

    assert [one.text for one in fresh] == ["hello"]


# ---------------------------------------------------------------------------
# The watermark — delivered once, and never dropped across a restart
# ---------------------------------------------------------------------------

def test_a_message_is_not_delivered_twice():
    chat.say("user", "only once please", session="main")

    first, offset = chat.unread("main")
    chat.mark_read("main", offset)
    second, _ = chat.unread("main")

    assert len(first) == 1
    assert second == []


def test_a_message_typed_while_the_agent_was_down_still_arrives():
    """The reason the offset is on disk rather than in memory."""
    chat.say("user", "first", session="main")
    _, offset = chat.unread("main")
    chat.mark_read("main", offset)

    chat.say("user", "typed while it was restarting", session="main")

    fresh, _ = chat.unread("main")

    assert [one.text for one in fresh] == ["typed while it was restarting"]


def test_a_new_clone_does_not_wake_up_to_this_mornings_conversation():
    chat.say("user", "a long conversation", session="david-2")

    chat.start_at_end("david-2")
    fresh, _ = chat.unread("david-2")

    assert fresh == []


def test_start_at_end_does_not_move_a_session_that_already_has_a_place():
    chat.say("user", "unread and waiting", session="main")
    chat.start_at_end("main")
    chat.start_at_end("main")           # a restart, not a new session

    fresh, _ = chat.unread("main")

    assert [one.text for one in fresh] == []

    chat.say("user", "arrived after the restart", session="main")
    fresh, _ = chat.unread("main")

    assert [one.text for one in fresh] == ["arrived after the restart"]


def test_a_trimmed_log_does_not_replay_the_whole_conversation():
    """An offset into a file that has been rewritten means nothing."""
    chat.say("user", "old", session="main")
    _, offset = chat.unread("main")
    chat.mark_read("main", offset + 10_000)     # as if the log had shrunk

    fresh, new_offset = chat.unread("main")

    assert fresh == []
    assert new_offset <= chat.chat_file().stat().st_size


# ---------------------------------------------------------------------------
# The protocol
# ---------------------------------------------------------------------------

def test_initialize_echoes_the_version_it_was_asked_for(monkeypatch):
    """Guessing a version number is how a server dies at somebody's upgrade."""
    sent = _frames(monkeypatch)

    channel_server._handle({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2099-01-01"},
    }, "main")

    assert sent[0]["result"]["protocolVersion"] == "2099-01-01"
    assert "tools" in sent[0]["result"]["capabilities"]


def test_initialize_declares_the_channel_capability(monkeypatch):
    """The one line that decides whether anything is delivered at all.

    Claude Code reads this declaration at `initialize` and nothing else. For
    three days without it every push was dropped in silence, the only trace
    being one line in a log file nobody reads:

        Channel notifications skipped: server did not declare
        claude/channel capability

    So this is asserted rather than assumed. A channel that cannot push is
    not a channel, and the failure is invisible from the panel.
    """
    sent = _frames(monkeypatch)

    channel_server._handle({
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {},
    }, "main")

    experimental = sent[0]["result"]["capabilities"]["experimental"]
    assert "claude/channel" in experimental


def test_it_does_not_claim_to_authenticate_the_replier(monkeypatch):
    """`claude/channel/permission` asserts the server knows who replied.

    This one knows a file on the machine wrote a line. That is a different
    claim, and declaring the stronger one would be untrue.
    """
    sent = _frames(monkeypatch)

    channel_server._handle({
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {},
    }, "main")

    experimental = sent[0]["result"]["capabilities"]["experimental"]
    assert "claude/channel/permission" not in experimental


def test_a_notification_is_never_answered(monkeypatch):
    """A response to something with no id is a protocol error."""
    sent = _frames(monkeypatch)

    channel_server._handle(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}, "main")

    assert sent == []


def test_the_reply_tool_is_offered(monkeypatch):
    sent = _frames(monkeypatch)

    channel_server._handle(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, "main")

    names = [tool["name"] for tool in sent[0]["result"]["tools"]]
    assert names == ["reply"]


def test_replying_puts_the_message_in_the_same_store(monkeypatch):
    """Not a second store the panel has to be told about."""
    sent = _frames(monkeypatch)

    channel_server._handle({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "reply", "arguments": {"text": "on my way"}},
    }, "main")

    assert sent[0]["result"]["isError"] is False
    assert [one.text for one in chat.read()] == ["on my way"]
    assert chat.read()[0].role == "assistant"


def test_an_unknown_tool_is_an_error_not_a_crash(monkeypatch):
    sent = _frames(monkeypatch)

    channel_server._handle({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "delete_everything", "arguments": {}},
    }, "main")

    assert "error" in sent[0]


def test_an_unknown_method_is_an_error_not_a_crash(monkeypatch):
    sent = _frames(monkeypatch)

    channel_server._handle(
        {"jsonrpc": "2.0", "id": 5, "method": "resources/list"}, "main")

    assert sent[0]["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# Delivery — the frame that actually wakes the session
# ---------------------------------------------------------------------------

def test_delivery_uses_the_channel_notification(monkeypatch):
    """The one mechanism that makes dropping Telegram possible at all."""
    sent = _frames(monkeypatch)
    line = chat.say("user", "the message", session="david-2")

    channel_server._deliver(line)

    assert sent[0]["method"] == "notifications/claude/channel"
    assert sent[0]["params"]["content"] == "the message"
    assert sent[0]["params"]["meta"]["session"] == "david-2"
    assert "id" not in sent[0]          # a notification, not a request


def test_a_frame_is_one_line_of_json(monkeypatch, capsys):
    """Stdout is the protocol. A frame split across lines stops the channel."""
    channel_server._send({"jsonrpc": "2.0", "id": 9,
                          "result": {"note": "多行會爆"}})

    out = capsys.readouterr().out

    assert out.count("\n") == 1
    assert json.loads(out)["result"]["note"] == "多行會爆"


def test_the_session_name_comes_from_the_environment(monkeypatch):
    """How a clone learns which lines are its own."""
    assert chat.this_session() == "main"

    monkeypatch.setenv(chat.SESSION_ENV, "david-2")

    assert chat.this_session() == "david-2"


# ---------------------------------------------------------------------------
# Attachments
#
# A chat that carries only
# text is not a replacement for the one being removed.
# ---------------------------------------------------------------------------

def _a_file(tmp_path, name: str, data: bytes = b"pretend this is a photo"):
    made = tmp_path / name
    made.write_bytes(data)
    return made


def test_a_photo_is_kept_and_described_for_the_panel(tmp_path):
    line = chat.attach("user", _a_file(tmp_path, "site.jpg"),
                       text="the north elevation")

    assert line.media["kind"] == "photo"
    assert line.media["mime"] == "image/jpeg"
    assert line.media["url"].startswith("/chat/media/")
    assert line.text == "the north elevation"
    assert chat.media_file(line.media["id"]).exists()


def test_the_file_is_copied_not_referenced(tmp_path):
    """Whatever produced it may be cleaned up a second later."""
    source = _a_file(tmp_path, "report.pdf")
    line = chat.attach("assistant", source)
    source.unlink()

    kept = chat.media_file(line.media["id"])

    assert kept is not None and kept.exists()


def test_the_browsers_filename_never_reaches_the_filesystem(tmp_path):
    """An upload names itself, and the name is attacker-chosen."""
    line = chat.attach("user", _a_file(tmp_path, "ok.png"),
                       filename="../../../../windows/system32/evil.png")

    kept = chat.media_file(line.media["id"])

    assert kept is not None
    assert kept.parent == chat.media_dir()
    # The offered name survives as a label, which is display and not a path.
    assert "evil.png" in line.media["name"]


def test_an_attachment_id_from_a_url_cannot_climb_out():
    for attempt in ("../../secrets", "..", "a/b", r"C:\Windows\win.ini",
                    "nothex!", "", "  "):
        assert chat.media_file(attempt) is None


def test_a_recording_is_marked_as_one(tmp_path):
    """A voice note is drawn as a player, not as an attachment to download."""
    line = chat.attach("user", _a_file(tmp_path, "note.ogg"), voice=True)

    assert line.media["kind"] == "voice"


def test_something_too_large_is_refused_in_words_a_person_can_act_on(
        tmp_path, monkeypatch):
    monkeypatch.setattr(chat, "MAX_ATTACHMENT_BYTES", 10)

    with pytest.raises(ValueError) as raised:
        chat.attach("user", _a_file(tmp_path, "big.bin", b"x" * 64))

    assert "limit" in str(raised.value)


def test_the_session_is_told_where_the_file_actually_is(tmp_path):
    """The path goes in meta, never in the text -- the text is forgeable."""
    line = chat.attach("user", _a_file(tmp_path, "plan.png"),
                       text="have a look", session="main")

    meta = channel_server._attachment_meta(line)

    assert meta["attachment_kind"] == "photo"
    assert meta["image_path"] == str(chat.media_file(line.media["id"]))
    assert Path(meta["attachment_path"]).exists()


def test_a_plain_message_carries_no_attachment_meta():
    line = chat.say("user", "just words")

    assert channel_server._attachment_meta(line) == {}


def test_replying_with_a_file_puts_it_in_the_conversation(tmp_path,
                                                          monkeypatch):
    sent = _frames(monkeypatch)
    drawing = _a_file(tmp_path, "elevation.png")

    channel_server._handle({
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": "reply", "arguments": {
            "text": "here it is", "files": [str(drawing)]}},
    }, "main")

    assert sent[0]["result"]["isError"] is False
    line = chat.read()[-1]
    assert line.role == "assistant"
    assert line.text == "here it is"
    assert line.media["kind"] == "photo"


def test_a_reply_whose_attachment_is_missing_still_delivers_the_words(
        monkeypatch):
    """The sentence matters more than the file that was meant to go with it."""
    sent = _frames(monkeypatch)

    channel_server._handle({
        "jsonrpc": "2.0", "id": 8, "method": "tools/call",
        "params": {"name": "reply", "arguments": {
            "text": "the chart is attached", "files": ["/no/such/chart.png"]}},
    }, "main")

    assert [one.text for one in chat.read()] == ["the chart is attached"]
    assert "could not attach" in sent[0]["result"]["content"][0]["text"]


def test_the_caption_belongs_to_the_first_file_only(tmp_path, monkeypatch):
    """A photo and the sentence about it are one message, not two."""
    _frames(monkeypatch)

    channel_server._handle({
        "jsonrpc": "2.0", "id": 9, "method": "tools/call",
        "params": {"name": "reply", "arguments": {
            "text": "both elevations",
            "files": [str(_a_file(tmp_path, "north.png")),
                      str(_a_file(tmp_path, "south.png"))]}},
    }, "main")

    lines = chat.read()

    assert [one.text for one in lines] == ["both elevations", ""]
    assert all(one.media for one in lines)


def test_history_gives_the_panel_the_shape_it_already_draws(tmp_path):
    chat.say("user", "morning")
    chat.attach("assistant", _a_file(tmp_path, "site.jpg"), text="the site")

    turns = chat.history()["turns"]

    assert [turn["role"] for turn in turns] == ["user", "assistant"]
    assert turns[0]["media"] is None
    assert turns[1]["media"]["kind"] == "photo"
    for turn in turns:
        assert set(turn) >= {"role", "text", "when", "channel", "held",
                             "media", "session"}


def test_an_empty_conversation_says_so():
    assert chat.never_set_up() is True
    chat.say("user", "hello")
    assert chat.never_set_up() is False


# ---------------------------------------------------------------------------
# Scheduled work in the conversation
#
# Until this, a scheduled job was a stranger: it ran, spoke on its own channel,
# and the live agent learned about its own background work from a hook.
# ---------------------------------------------------------------------------

def test_a_scheduled_job_reports_into_the_main_conversation():
    from aki_agent import runner

    runner._post_to_the_conversation(
        "morning summary",
        runner.RunResult(ok=True, output="done", seconds=4.0))

    line = chat.read()[-1]

    assert line.session == chat.MAIN
    assert "morning summary" in line.text
    assert line.meta["origin"] == "task"
    assert line.meta["ok"] == "yes"


def test_a_failed_job_says_so_rather_than_going_quiet():
    """A job that fails silently is how somebody finds out in March."""
    from aki_agent import runner

    runner._post_to_the_conversation(
        "weekly tidy",
        runner.RunResult(ok=False, output="", error="OAuth session expired",
                         seconds=2.0))

    line = chat.read()[-1]

    assert "FAILED" in line.text
    assert "OAuth session expired" in line.text
    assert line.meta["ok"] == "no"


def test_the_job_result_is_marked_so_the_panel_can_fold_it():
    """Ten job results a day in one window is a log unless they read apart."""
    from aki_agent import runner

    chat.say("user", "morning")
    runner._post_to_the_conversation(
        "trend scan", runner.RunResult(ok=True, output="", seconds=1.0))

    turns = chat.history()["turns"]

    assert turns[0]["origin"] == ""
    assert turns[1]["origin"] == "task"


def test_a_job_is_never_reported_failed_because_the_note_could_not_be_written(
        monkeypatch):
    """The work happened. Losing the note about it must not undo that."""
    from aki_agent import runner

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(chat, "say", broken)

    runner._post_to_the_conversation(
        "morning summary",
        runner.RunResult(ok=True, output="done", seconds=1.0))


# ---------------------------------------------------------------------------
# The instructions
#
# Without them the channel looks broken in the most confusing way available:
# the message arrives, the assistant reads it, answers into a terminal nobody
# is looking at, and the panel stays silent while every layer reports success.
# Found on the Surface on 2026-09-01 -- delivered, `undelivered: 0`, no reply
# ever coming back. The official Telegram channel supplies exactly this.
# ---------------------------------------------------------------------------

def test_the_session_is_told_that_printing_does_not_reach_anybody(monkeypatch):
    sent = _frames(monkeypatch)

    channel_server._handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        "main")

    instructions = sent[0]["result"]["instructions"]

    assert "reply" in instructions
    assert "NOT this" in instructions or "not this" in instructions.lower()


def test_the_instructions_name_the_only_way_out():
    """If the tool is ever renamed, this is what stops the text going stale."""
    assert REPLY_NAME in channel_server.INSTRUCTIONS
    assert channel_server.REPLY_TOOL["name"] == REPLY_NAME


REPLY_NAME = "reply"
