"""Photos, voice notes and files in the chat panel — and the rules they obey.

WHY THIS FILE EXISTS (reported 2026-08-20)
----------------------------------------
The panel was put on the real Telegram conversation, and then he sent a voice
message from his phone and it was not there. Not shown as a placeholder, not
shown as a gap: absent. One line of `history()` was responsible —

    if not text:
        continue                  # a photo or a sticker, not a turn

— which is the same shape as most of the real defects in this package: a
mechanism that works, with something quietly not wired to it.

His ask was the ordinary one: *"i need the same function as a normal telegram:
attach file, images (show thumbnail), record audio...playback in chatpanel"*.

These tests hold the parts of that which are easy to break and invisible when
broken.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from aki_agent import telegram_chat

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_HTML = (REPO_ROOT / "src" / "aki_agent" / "dashboard" / "templates"
             / "base.html")
APP_PY = REPO_ROOT / "src" / "aki_agent" / "dashboard" / "app.py"


# ---------------------------------------------------------------------------
# Stand-ins for what Telethon hands back
# ---------------------------------------------------------------------------

class _File:
    def __init__(self, mime="", name="", size=0, duration=0):
        self.mime_type = mime
        self.name = name
        self.size = size
        self.duration = duration


class _Message:
    """Only the attributes the code actually reads."""

    def __init__(self, ident=1, text="", out=False, media=None, file=None,
                 voice=None):
        self.id = ident
        self.message = text
        self.out = out
        self.media = media
        self.file = file
        self.voice = voice
        self.date = _dt.datetime(2026, 8, 20, 17, 30,
                                 tzinfo=_dt.timezone.utc)


class _Link:
    def __init__(self, messages):
        self._messages = messages

    def is_user_authorized(self):
        return True

    def get_messages(self, _bot, limit=None, ids=None):
        if ids is not None:
            for message in self._messages:
                if message.id == ids:
                    return message
            return None
        return list(reversed(self._messages))[:limit]

    def disconnect(self):
        pass


@pytest.fixture()
def conversation_of(monkeypatch):
    """Put a fixed conversation behind `history()` without a network."""
    def install(messages):
        monkeypatch.setattr(telegram_chat, "bot_username", lambda: "aki_bot")
        monkeypatch.setattr(telegram_chat, "_client",
                            lambda: _Link(list(messages)))
    return install


# ---------------------------------------------------------------------------
# The defect itself
# ---------------------------------------------------------------------------

def test_a_message_with_only_a_photo_is_still_a_turn(conversation_of):
    """The exact thing that went missing: an attachment and no words.

    This is the regression that matters. A photo sent with no caption is the
    normal way anybody sends a photo, and the first version of this code
    dropped every one of them.
    """
    conversation_of([
        _Message(ident=7, text="", media=object(),
                 file=_File(mime="image/jpeg", size=204800)),
    ])

    result = telegram_chat.history()

    assert result["ok"]
    assert len(result["turns"]) == 1, "a captionless photo vanished"
    assert result["turns"][0]["media"]["kind"] == "photo"
    assert result["turns"][0]["media"]["url"] == "/chat/media/7"


def test_a_voice_note_is_told_apart_from_an_audio_file(conversation_of):
    """Both play, but only one of them is a voice message.

    Telegram marks the difference and the panel draws it, so the distinction
    has to survive the trip through this module rather than being flattened
    into "some audio".
    """
    conversation_of([
        _Message(ident=1, media=object(), voice=object(),
                 file=_File(mime="audio/ogg", duration=6)),
        _Message(ident=2, media=object(),
                 file=_File(mime="audio/mpeg", name="song.mp3", size=5 << 20)),
    ])

    kinds = [turn["media"]["kind"] for turn in telegram_chat.history()["turns"]]
    assert kinds == ["voice", "audio"]


def test_an_unknown_attachment_is_offered_as_a_file_not_a_player(conversation_of):
    """The fallback carries more weight than the two pretty cases.

    A player that cannot play what it was given is worse than an honest link,
    because it looks like the file is broken rather than merely unusual.
    """
    conversation_of([
        _Message(ident=3, media=object(),
                 file=_File(mime="application/x-cbr", name="thing.cbr",
                            size=1536)),
    ])

    media = telegram_chat.history()["turns"][0]["media"]
    assert media["kind"] == "file"
    assert media["name"] == "thing.cbr"
    assert media["size"] == "1.5 KB", "a size nobody can read is not a size"


def test_a_message_with_neither_words_nor_attachment_is_skipped(conversation_of):
    """Service notices are not turns, and the panel should not show them."""
    conversation_of([_Message(ident=4, text="", media=None)])
    assert telegram_chat.history()["turns"] == []


def test_describing_media_never_downloads_it(conversation_of):
    """Two hundred messages must cost two hundred descriptions, not two
    hundred downloads.

    `history()` runs every few seconds for as long as somebody leaves the
    dashboard open. If describing a photo fetched it, a conversation with any
    pictures in it would saturate a connection on a timer.
    """
    def explode(*_args, **_kwargs):                       # pragma: no cover
        raise AssertionError("history downloaded an attachment")

    link = _Link([_Message(ident=5, media=object(),
                           file=_File(mime="image/png", size=10))])
    link.download_media = explode
    conversation_of([])
    import aki_agent.telegram_chat as module
    module._client = lambda: link                          # noqa: SLF001

    assert telegram_chat.history()["ok"]


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def test_only_ogg_is_sent_as_a_voice_note(tmp_path, monkeypatch):
    """Telegram accepts one container as a voice note and rejects the rest.

    A browser that can only record webm still gets its recording delivered --
    as ordinary audio, which plays. Marking a webm as a voice note would make
    the send fail outright, and a message that does not arrive is worse than
    one that arrives drawn differently.
    """
    sent = {}

    class _Sender(_Link):
        def send_file(self, _bot, path, caption=None, voice_note=False,
                      force_document=False):
            sent["path"] = path
            sent["voice_note"] = voice_note
            return _Message(ident=99)

    monkeypatch.setattr(telegram_chat, "bot_username", lambda: "aki_bot")
    monkeypatch.setattr(telegram_chat, "_client", lambda: _Sender([]))

    webm = tmp_path / "voice.webm"
    webm.write_bytes(b"x")
    telegram_chat.send_file(webm, voice=True)
    assert sent["voice_note"] is False, "webm cannot be a voice note"

    ogg = tmp_path / "voice.ogg"
    ogg.write_bytes(b"x")
    telegram_chat.send_file(ogg, voice=True)
    assert sent["voice_note"] is True


def test_sending_a_file_that_is_not_there_says_so_rather_than_raising(tmp_path):
    result = telegram_chat.send_file(tmp_path / "nothing.png")
    assert result["ok"] is False
    assert "not there" in result["error"]


# ---------------------------------------------------------------------------
# The rules the browser side has to keep
# ---------------------------------------------------------------------------

def test_never_set_up_is_certain_only_about_the_negative(monkeypatch):
    """False must mean 'cannot tell', never 'connected'."""
    monkeypatch.setattr(telegram_chat, "installed", lambda: False)
    assert telegram_chat.never_set_up() is True

    monkeypatch.setattr(telegram_chat, "installed", lambda: True)
    monkeypatch.setattr(telegram_chat, "credentials", lambda: (None, None))
    assert telegram_chat.never_set_up() is True


def test_credentials_without_a_session_is_still_never_set_up(monkeypatch,
                                                             tmp_path):
    """Saving the two values from my.telegram.org is not signing in.

    Stopping at the credentials would have called a half-finished pairing
    'connected' and hidden the one sentence telling them to finish it.
    """
    monkeypatch.setattr(telegram_chat, "installed", lambda: True)
    monkeypatch.setattr(telegram_chat, "credentials", lambda: (1234, "hash"))
    monkeypatch.setattr(telegram_chat, "session_file",
                        lambda: tmp_path / "absent.session")
    assert telegram_chat.never_set_up() is True

    (tmp_path / "present.session").write_text("", encoding="utf-8")
    monkeypatch.setattr(telegram_chat, "session_file",
                        lambda: tmp_path / "present.session")
    assert telegram_chat.never_set_up() is False
