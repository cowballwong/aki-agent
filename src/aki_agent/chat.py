"""The one chat store, which both the panel and the session read.

WHY THIS FILE EXISTS AT ALL
---------------------------

Until now the dashboard's chat box was Telegram wearing a dashboard coat: it
signed in as the user with Telethon and sent the message to their own bot, so
the session received an ordinary Telegram message. That worked, and it cost a
developer registration and a stored user session file -- a credential worth
more than the bot token, because it signs in as the person.

It also capped the whole system at one agent. **One bot token may be polled by
exactly one process.** Every scheduled job already works around that. No
arrangement of clones can get past it while Telegram is the way in.

THE MISTAKE THIS MUST NOT REPEAT
--------------------------------
Before August the dashboard kept its own copy: a message typed there went into
a queue and the assistant was expected to copy it across. Two stores kept in
step by convention, and the symptoms were the predictable ones -- the panel
lagged, the session showed nothing arriving, the two views disagreed.

So the rule here is not "our queue instead of theirs". It is **one store, and
both directions are written by the same code**. A message from the person and
a reply from the assistant land in this same file, appended by this module,
and the panel renders what it finds. Nothing copies anything.

WHY APPEND-ONLY
---------------
Several sessions will write this at once -- that is the entire point of the
clone design. An append is one turn and cannot lose a neighbour's line;
read-modify-write on a shared file is how the working state used to eat notes.
`atomic.append_line` takes the file's lock, so even the appends are ordered.

ADDRESSING
----------
Every line carries a `session`. The main agent is `main`; a clone is whatever
it was named when it was created. A line from the person carries the name of
the session it is *for*, so a queue with several readers needs no broker: each
session reads the file and answers only to its own name.
"""

from __future__ import annotations

import datetime as _dt
import json
import mimetypes
import os
import shutil
import uuid
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any

from . import atomic, paths, secrets

# The main agent, when nothing says otherwise. A clone overrides this through
# AKI_SESSION_NAME in its own .mcp.json, which is also how its channel server
# learns which lines are addressed to it.
MAIN = "main"

SESSION_ENV = "AKI_SESSION_NAME"

# The log is allowed to be large -- it is the conversation, and losing the
# middle of it to save a few megabytes is the wrong trade. These match the
# event log's shape so there is one story about log growth, not two.
KEEP_LINES = 4000
MAX_LOG_BYTES = 8 * 1024 * 1024


def chat_file() -> Path:
    return paths.log_dir() / "chat.jsonl"


def this_session() -> str:
    """Which session this process belongs to."""
    name = (os.environ.get(SESSION_ENV) or "").strip()
    return name or MAIN


@dataclass
class Line:
    at: _dt.datetime
    role: str                       # "user" | "assistant"
    text: str
    session: str = MAIN
    media: dict[str, Any] | None = None
    meta: dict[str, Any] = dataclass_field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(timespec="seconds"),
            "role": self.role,
            "text": self.text,
            "session": self.session,
            **({"media": self.media} if self.media else {}),
            **({"meta": self.meta} if self.meta else {}),
        }


def _parse(raw: str) -> Line | None:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        at = _dt.datetime.fromisoformat(str(data.get("at", "")))
    except ValueError:
        at = _dt.datetime.now()
    role = str(data.get("role") or "")
    if role not in ("user", "assistant"):
        return None
    meta = data.get("meta")
    media = data.get("media")
    return Line(
        at=at,
        role=role,
        text=str(data.get("text") or ""),
        session=str(data.get("session") or MAIN),
        media=media if isinstance(media, dict) else None,
        meta=meta if isinstance(meta, dict) else {},
    )


def say(role: str, text: str, *, session: str | None = None,
        meta: dict[str, Any] | None = None,
        deliver: bool = True) -> Line | None:
    """Append one message. Returns the line written, or None if there was none.

    Redacted on the way in, like everything else that is written down: this
    file is the conversation, and a conversation is exactly where somebody
    pastes a key without thinking about it.

    `deliver=False` records a message the session has ALREADY received by some
    other route -- one that arrived over Telegram, say. It belongs in the
    conversation, because the panel showing only half a conversation is what
     meant. It must not be handed
    to the session again: this file is also the queue, so a plain record would
    be read back as a fresh instruction and answered a second time.
    """
    clean = secrets.redact(str(text or "")).strip()
    if not clean:
        return None
    if role not in ("user", "assistant"):
        raise ValueError(f"role must be 'user' or 'assistant', got {role!r}")

    stamped = dict(meta or {})
    if not deliver:
        stamped["deliver"] = "no"

    line = Line(at=_dt.datetime.now(), role=role, text=clean,
                session=(session or this_session()), meta=stamped)

    paths.ensure_app_dirs()
    atomic.append_line(chat_file(),
                       json.dumps(line.as_dict(), ensure_ascii=False))
    atomic.trim_log(chat_file(), KEEP_LINES, MAX_LOG_BYTES)

    # Mirror into the conversation log, which is what the dashboard panel and
    # `aki inbox show` render. Without this the assistant's replies exist and
    # are simply invisible: the owner types, it answers, and the panel shows
    # only his own half. Never allowed to be the reason a reply fails to be
    # recorded here -- this file is the one the session reads back.
    try:
        from . import conversation

        channel = str(stamped.get("channel") or "dashboard")
        if not conversation.already_recorded(role, clean):
            conversation.append(role, clean, channel=channel)
    except Exception:                                    # noqa: BLE001
        pass

    return line


def read(limit: int = 200, session: str | None = None) -> list[Line]:
    """The last `limit` messages, oldest first.

    `session` filters to one agent's thread; None returns everything, which is
    what the panel wants when it shows the main conversation with a clone's
    results folded into it.
    """
    path = chat_file()
    if not path.exists():
        return []

    try:
        raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    lines = [parsed for parsed in (_parse(one) for one in raw) if parsed]
    if session:
        lines = [one for one in lines if one.session == session]
    return lines[-limit:] if limit else lines


# ---------------------------------------------------------------------------
# Tailing, for the channel server
#
# By byte offset rather than by line count, and the offset is kept on disk so
# that a message typed while the agent was restarting is delivered when it
# comes back rather than silently skipped. `conversations.py` reads Claude
# Code's own transcripts the same way -- one idea about tailing, not two.
# ---------------------------------------------------------------------------

def watermark_file(session: str) -> Path:
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "-"
                   for ch in session) or MAIN
    return paths.state_dir() / f"chat-seen-{safe}.json"


def unread(session: str) -> tuple[list[Line], int]:
    """Lines addressed to `session` that it has not been handed yet.

    Returns the lines and the new offset. The offset is NOT saved here: the
    caller saves it after the delivery has actually happened, so a crash
    between reading and delivering repeats a message rather than losing it.
    Repeating is recoverable; losing is not.
    """
    path = chat_file()
    if not path.exists():
        return [], 0

    mark = atomic.read_json(watermark_file(session), default={}) or {}
    offset = int(mark.get("offset", 0) or 0)

    try:
        size = path.stat().st_size
    except OSError:
        return [], offset

    # The log was trimmed (or replaced) under us -- an offset into the old
    # file means nothing now, so start from the end rather than replaying a
    # conversation the person has already had.
    if offset > size:
        return [], size

    try:
        with path.open("r", encoding="utf-8", errors="replace",
                       newline="") as handle:
            handle.seek(offset)
            fresh = handle.read()
            new_offset = offset + len(fresh.encode("utf-8"))
    except OSError:
        return [], offset

    found: list[Line] = []
    for raw in fresh.splitlines():
        parsed = _parse(raw)
        if (parsed and parsed.role == "user" and parsed.session == session
                # A line the session has already been given by another route
                # is history here, not a new instruction. Without this test a
                # message that arrived over Telegram would be recorded, read
                # straight back out of this file, and answered twice.
                and parsed.meta.get("deliver") != "no"):
            found.append(parsed)

    return found, new_offset


def mark_read(session: str, offset: int) -> None:
    """Record how far this session got. Call AFTER delivering, never before."""
    try:
        paths.ensure_app_dirs()
        atomic.write_json(watermark_file(session), {"offset": int(offset)})
    except OSError:
        return


def start_at_end(session: str) -> None:
    """Point a brand new session at the end of the log.

    A clone created this afternoon should not wake up to this morning's
    conversation. Only called when no watermark exists yet.
    """
    if watermark_file(session).exists():
        return
    try:
        size = chat_file().stat().st_size
    except OSError:
        size = 0
    mark_read(session, size)


# ---------------------------------------------------------------------------
# Attachments
#
# A chat that can only carry text is not a replacement for the one it is
# replacing. Photos,
# files, recordings, and previews of them.
#
# The descriptor below is deliberately the SAME SHAPE the panel already draws
# with, because the panel's drawing code is good and the thing being replaced
# is the transport underneath it, not the interface on top.
# ---------------------------------------------------------------------------

MEDIA_DIR_NAME = "chat-media"

KIND_BY_MIME = (
    ("image/", "photo"),
    ("video/", "video"),
    ("audio/", "audio"),
)

# Big enough for a phone photograph or a short screen recording, small enough
# that a mistake does not fill somebody's disk before they notice.
MAX_ATTACHMENT_BYTES = 64 * 1024 * 1024


def media_dir() -> Path:
    folder = paths.state_dir() / MEDIA_DIR_NAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _human_size(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _kind_for(mime: str, voice: bool = False) -> str:
    if voice:
        return "voice"
    for prefix, name in KIND_BY_MIME:
        if mime.startswith(prefix):
            return name
    return "file"


def _safe_media_id(media_id: str) -> str:
    """Only ever a hex id we minted ourselves.

    The id reaches this module from a URL, so it is treated as hostile: hex
    and nothing else, which cannot climb out of the folder however it is
    written. Rejecting is safer than sanitising -- a sanitiser that turns a
    traversal into a valid-looking name is worse than a refusal.
    """
    cleaned = str(media_id or "").strip().lower()
    if not cleaned or len(cleaned) > 64 or any(
            ch not in "0123456789abcdef" for ch in cleaned):
        raise ValueError("not an attachment id")
    return cleaned


def media_file(media_id: str) -> Path | None:
    """The bytes of one attachment, or None when it is no longer there."""
    try:
        wanted = _safe_media_id(media_id)
    except ValueError:
        return None
    for existing in sorted(media_dir().glob(f"{wanted}.*")):
        if existing.is_file():
            return existing
    found = media_dir() / wanted
    return found if found.is_file() else None


def keep(source: Path, *, filename: str = "", voice: bool = False) -> dict:
    """Take a copy of a file into the store and describe it.

    A copy rather than a reference: the browser's upload is a temporary file
    and a scheduled job's output may be anywhere, and a conversation that
    points at paths which vanish is a conversation full of broken images.

    Only the extension of the offered name is kept. The name itself never
    reaches the filesystem -- it is attacker-chosen on an upload -- but it is
    recorded in the descriptor so the panel can show what the thing was called.
    """
    source = Path(source)
    size = source.stat().st_size
    if size > MAX_ATTACHMENT_BYTES:
        raise ValueError(
            f"that file is {_human_size(size)}; the limit is "
            f"{_human_size(MAX_ATTACHMENT_BYTES)}")

    offered = (filename or source.name or "").strip()
    suffix = "".join(ch for ch in Path(offered or source.name).suffix
                     if ch.isalnum() or ch == ".")[:16]

    media_id = uuid.uuid4().hex
    target = media_dir() / f"{media_id}{suffix}"
    shutil.copyfile(source, target)

    mime = mimetypes.guess_type(offered or source.name)[0] or ""
    kind = _kind_for(mime, voice=voice)
    name = offered or {"photo": "photo", "voice": "voice message",
                       "audio": "audio", "video": "video"}.get(kind, "file")

    return {
        "kind": kind,
        "id": media_id,
        "name": name,
        "mime": mime,
        "size": _human_size(size),
        "duration": 0,
        "url": f"/chat/media/{media_id}",
    }


def attach(role: str, source: Path, *, text: str = "", voice: bool = False,
           filename: str = "", session: str | None = None) -> Line | None:
    """Send a file, with or without something written alongside it."""
    media = keep(Path(source), filename=filename, voice=voice)
    line = Line(at=_dt.datetime.now(), role=role,
                text=secrets.redact(str(text or "")).strip(),
                session=(session or this_session()), media=media)

    paths.ensure_app_dirs()
    atomic.append_line(chat_file(),
                       json.dumps(line.as_dict(), ensure_ascii=False))
    atomic.trim_log(chat_file(), KEEP_LINES, MAX_LOG_BYTES)
    return line


# ---------------------------------------------------------------------------
# What the panel asks for
# ---------------------------------------------------------------------------

HISTORY_LIMIT = 200


def history(limit: int = HISTORY_LIMIT, session: str | None = None) -> dict:
    """The conversation as plain values, newest last.

    The same shape the panel was already being fed, so that swapping the
    transport underneath it is a change of one import rather than a rewrite of
    the interface. `ok` is always true: this store is a file on this machine,
    so there is no signed-in state that can quietly be false -- which was the
    failure the connection light was added to catch.
    """
    turns = []
    for line in read(limit=limit, session=session):
        if not line.text and not line.media:
            continue
        turns.append({
            "role": line.role,
            "text": line.text,
            "when": line.at.strftime("%H:%M"),
            "channel": str(line.meta.get("channel") or "aki"),
            # Something the assistant tried to say and is still holding --
            # quiet hours, usually. The panel shows it as waiting rather than
            # sent, which is the whole information the quiet-hours rule exists
            # to preserve, so it has to survive the trip through meta.
            "held": line.meta.get("delivered") == "no",
            "media": line.media or None,
            "session": line.session,
            "origin": str(line.meta.get("origin") or ""),
        })
    return {"ok": True, "turns": turns}


def never_set_up() -> bool:
    """Nothing has ever been said here.

    There is nothing to set up any more -- that is the point of this module --
    so "not set up" now means only "empty", and the panel says so.
    """
    return not chat_file().exists()
