"""One conversation, visible from everywhere.

WHAT THIS SOLVES
----------------
The assistant can be reached from more than one place: typed at in a terminal,
messaged on a phone, or written to from the dashboard. Without something like
this, each of those is a separate island — the dashboard has no idea what was
said on the phone an hour ago, and neither do you when you sit back down.

So there is one append-only conversation log, and every route writes to it.
The dashboard's chat view is a **mirror** of that log, not a second inbox.

HOW THE MIRROR ACTUALLY WORKS, AND WHAT IT CANNOT DO
----------------------------------------------------
It works because both sides write here, not because anything scrapes Telegram.

That distinction matters, because the alternative is impossible: Telegram's
Bot API exposes no message history, and the plugin does not keep message text.
Any design that claimed to "pull your Telegram conversation into the
dashboard" would be a design that could not be built.

What that means in practice:

  * Messages the assistant SENDS appear here always — every outbound message
    goes through the notification gate, which writes here.
  * Messages you send ON TELEGRAM appear here only if the assistant records
    them, which its instructions tell it to do. Its instructions are followed
    reliably but not mechanically, so a message can be missed.
  * Messages you type INTO THE DASHBOARD appear here immediately, and wait to
    be picked up.

That third one is the part worth being clear about: typing into the dashboard
does not interrupt the assistant. It queues. If nothing is running, nothing
happens until something is. The dashboard says so rather than showing a
hopeful spinner.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, asdict
from pathlib import Path

from . import atomic, events, paths, secrets

ROLES = ("user", "assistant", "system")

# Keep the visible history bounded. A chat view that loads ten thousand
# messages is a chat view nobody opens twice.
DEFAULT_LIMIT = 200

# How much of the conversation to keep on disk, and when to start trimming.
#
# Larger than the event log's window because this is the assistant's own
# memory of what was said, and losing the middle of a conversation is a
# different kind of loss from losing an old status line. Still bounded: with
# no trim at all this file grew for the life of the install and was read whole
# to show the last twenty lines.
KEEP_TURNS = 20_000
MAX_LOG_BYTES = 8 * 1024 * 1024


def log_file() -> Path:
    return paths.log_dir() / "conversation.jsonl"


def pending_file() -> Path:
    return paths.state_dir() / "pending-messages.json"


@dataclass
class Turn:
    """One thing said, by somebody, somewhere."""

    role: str
    text: str
    channel: str = "dashboard"
    at: str = ""
    # Set on assistant turns that were held rather than delivered.
    held: bool = False

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}, not {self.role!r}")
        if not self.at:
            self.at = _dt.datetime.now().isoformat(timespec="seconds")

    @property
    def when(self) -> str:
        return self.at[11:16]

    @property
    def day(self) -> str:
        return self.at[:10]


def append(role: str, text: str, channel: str = "dashboard",
           held: bool = False) -> Turn:
    """Record one turn.

    Redacted on the way in. A conversation log is read by the dashboard, may
    be scrolled through in a classroom, and is the sort of file somebody
    copies when asking for help.
    """
    turn = Turn(role=role, text=secrets.redact(text.strip()),
                channel=channel, held=held)
    atomic.append_line(log_file(),
                       json.dumps(asdict(turn), ensure_ascii=False))
    # Bounded here rather than by anything having to remember to tidy up. The
    # usual cost is one `stat`; see KEEP_TURNS for what is kept and why.
    atomic.trim_log(log_file(), KEEP_TURNS, MAX_LOG_BYTES)
    return turn


def already_recorded(role: str, text: str,
                     within_seconds: float = 300) -> bool:
    """Is this same turn already the tail of the log?

    There are two ways an assistant reply reaches this file -- the mirror in
    `chat.say`, and `aki inbox replied` run by the assistant itself -- and an
    assistant that does both would otherwise say everything twice. Compared
    on the redacted text, because that is what was stored.

    Deliberately only the recent tail: a person who says "ok" twice in an
    afternoon means it twice, and collapsing that would be a worse fault than
    the duplicate this prevents.
    """
    wanted = secrets.redact(str(text or "")).strip()
    if not wanted:
        return True

    cutoff = _dt.datetime.now() - _dt.timedelta(seconds=within_seconds)
    for turn in read(limit=12):
        if turn.role != role or turn.text != wanted:
            continue
        try:
            when = _dt.datetime.fromisoformat(turn.at)
        except (TypeError, ValueError):
            return True
        if when >= cutoff:
            return True
    return False


def read(limit: int = DEFAULT_LIMIT) -> list[Turn]:
    """The most recent turns, oldest first."""
    path = log_file()
    if not path.exists():
        return []

    # Read from the end. Showing the last twenty turns used to mean loading
    # every turn there had ever been, on a panel that is on every page.
    lines = atomic.tail_lines(path, limit)

    turns: list[Turn] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            turns.append(Turn(**json.loads(line)))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue        # one bad line must not empty the history
    return turns


def grouped_by_day(limit: int = DEFAULT_LIMIT) -> list[tuple[str, list[Turn]]]:
    """Turns grouped under a date heading, for rendering."""
    days: dict[str, list[Turn]] = {}
    for turn in read(limit):
        days.setdefault(turn.day, []).append(turn)
    return sorted(days.items())


# ---------------------------------------------------------------------------
# Messages typed into the dashboard, waiting to be picked up
# ---------------------------------------------------------------------------

def queue(text: str) -> Turn:
    """Add something the user typed in the dashboard.

    It goes into the conversation immediately, so they can see it was
    received, AND into a pending list, so the assistant can find it.

    Two places on purpose: the conversation is a record and must never be
    consumed, while the pending list is a queue and must be emptied exactly
    once.
    """
    turn = append("user", text, channel="dashboard")

    waiting = read_pending()
    waiting.append({"text": turn.text, "at": turn.at})
    atomic.write_json(pending_file(), waiting)

    events.record("heard", turn.text, source="dashboard")
    return turn


def queue_pending(text: str, at: str | None = None) -> None:
    """Put something on the pending list WITHOUT recording it again.

    `queue` above both records and queues, which is right when it is the only
    writer. It is not any more: the dashboard writes what a person typed into
    the chat store, and the store mirrors it into this log itself. What is
    still needed is the queue -- the pending list is how a dashboard message
    actually reaches the session, through the prompt hook.

    Why the hook and not the channel (2026-09-04): Claude Code accepts inbound
    only from an APPROVED plugin channel, so this package's own channel server
    can hand a message over and be ignored -- delivered, marked read, never
    seen. The queue is slower (it arrives on the session's next turn) and it
    is the one that works.
    """
    clean = secrets.redact(str(text or "")).strip()
    if not clean:
        return
    waiting = read_pending()
    waiting.append({"text": clean, "at": at or _dt.datetime.now().isoformat(
        timespec="seconds")})
    atomic.write_json(pending_file(), waiting)
    events.record("heard", clean, source="dashboard")


def read_pending() -> list[dict]:
    # `read_json_for_update`, not `read_json`: every caller of this reads the
    # queue, changes it, and writes it back. A plain read cannot tell "the
    # file is not there" from "the file is there and would not open", and
    # answering the second with an empty list is how the whole queue used to
    # be erased by the next write.
    return atomic.read_json_for_update(pending_file(), default=[]) or []


def pending_count() -> int:
    return len(read_pending())


def take_pending() -> list[dict]:
    """Claim everything waiting, and clear the queue.

    Claimed atomically: the queue is cleared only after the caller has the
    messages in hand. If this process dies between the two, the messages are
    delivered twice rather than lost — which is the right way round for
    something a person typed.
    """
    waiting = read_pending()
    if waiting:
        atomic.write_json(pending_file(), [])
    return waiting


# ---------------------------------------------------------------------------
# Used by the notification gate
# ---------------------------------------------------------------------------

def record_outbound(text: str, channel: str, delivered: bool) -> Turn:
    """Called whenever the assistant sends something, anywhere.

    This is what makes the dashboard a mirror rather than a separate inbox —
    a message sent to a phone shows up in the dashboard because it passed
    through here on the way out.
    """
    return append("assistant", text, channel=channel, held=not delivered)
