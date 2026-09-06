"""Aki's own channel: the dashboard reaches the session directly.

WHAT THIS REPLACES, AND THE THING THAT MADE IT POSSIBLE
------------------------------------------------------
The fear about dropping Telegram is that it is the only thing able to reach
into a running Claude Code session. It is not. The official channel plugin
delivers an inbound message with a single MCP notification:

    notifications/claude/channel   { content, meta: { ... } }

Nothing in that is Telegram. The `meta` fields become the attributes on the
<channel> tag the session sees; Telegram merely fills them in. Any MCP server
can send it, so the transport can be a file on this machine.

That is the whole trick, and it is why this file is short. The reference
implementation is around forty kilobytes, and the bulk of it is pairing,
allowlists and access control -- necessary for a bot that strangers can find,
and pointless for a queue on loopback behind the dashboard's PIN.

WHY IT IS HAND-WRITTEN AND NOT AN SDK
-------------------------------------
The package's runtime dependency is PyYAML. One. Adding an MCP SDK to deliver
four message types would be the largest dependency in the project, installed
on a student's machine, to save perhaps eighty lines. The protocol below is
newline-delimited JSON-RPC over stdio and is stdlib throughout.

The one protocol subtlety worth stating: **the version is echoed, not
asserted.** Whatever `initialize` asks for is what comes back, because guessing
a version number is how a server stops working after somebody else's upgrade.

STDOUT IS THE PROTOCOL
----------------------
Nothing may print. A stray line on stdout is a parse error at the other end
and the channel simply stops, with no message saying why. Every diagnostic in
this file goes to stderr, and the writer is behind a lock because the reply
thread and the delivery thread both write frames.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import chat, paths

# How often the log is checked for something new. Fast enough that typing in
# the panel feels immediate; slow enough to be free. It is a `stat` in the
# usual case, not a read.
POLL_SECONDS = 0.4

SERVER_NAME = "aki-channel"
SERVER_VERSION = "1.0.0"

_write_lock = threading.Lock()


def _send(payload: dict[str, Any]) -> None:
    """One JSON-RPC frame to stdout, whole, from one thread at a time."""
    text = json.dumps(payload, ensure_ascii=False)
    with _write_lock:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()


def _log(message: str) -> None:
    sys.stderr.write(f"aki-channel: {message}\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Delivering what the person typed
# ---------------------------------------------------------------------------

def _attachment_meta(line: chat.Line) -> dict[str, str]:
    """Tell the session where the file actually is.

    A path in `meta` and never in `content`: anything inside the message text
    is written by whoever sent it, so an "[image attached -- read: ...]" line
    in the body is a sentence anybody can type. The meta is ours.

    `image_path` is the key the harness already understands for a picture, so
    an image arriving here reads the same way it does on any other channel.
    """
    if not line.media:
        return {}

    found = chat.media_file(str(line.media.get("id") or ""))
    if found is None:
        return {}

    kind = str(line.media.get("kind") or "file")
    meta = {
        "attachment_path": str(found),
        "attachment_kind": kind,
        "attachment_name": str(line.media.get("name") or found.name),
    }
    if kind == "photo":
        meta["image_path"] = str(found)
    return meta


def _deliver(line: chat.Line) -> None:
    _send({
        "jsonrpc": "2.0",
        "method": "notifications/claude/channel",
        "params": {
            "content": line.text,
            "meta": {
                "session": line.session,
                "ts": line.at.isoformat(timespec="seconds"),
                **_attachment_meta(line),
                **{key: str(value) for key, value in line.meta.items()},
            },
        },
    })


def _watch(session: str, stop: threading.Event) -> None:
    """Tail the chat log and hand this session its own messages.

    The watermark is saved only after the frame has gone out. A crash between
    reading and sending therefore repeats a message rather than dropping it,
    which is the right way round: a person can ignore a duplicate and cannot
    recover a message that was never delivered.
    """
    while not stop.is_set():
        try:
            fresh, offset = chat.unread(session)
            for line in fresh:
                _deliver(line)
            if fresh or offset:
                chat.mark_read(session, offset)
        except Exception as error:                       # noqa: BLE001
            # The channel must not die because one line was malformed.
            _log(f"watch: {error}")
        stop.wait(POLL_SECONDS)


# ---------------------------------------------------------------------------
# The protocol
# ---------------------------------------------------------------------------

# Handed to the session at `initialize` and shown to the assistant as part of
# its own instructions. WITHOUT THIS THE WHOLE CHANNEL LOOKS BROKEN, and it
# looks broken in the most confusing possible way: the message arrives, the
# assistant reads it, thinks about it, answers into a terminal nobody is
# looking at, and the panel stays silent. Every layer reports success.
#
# Found on the test laptop on 2026-09-01 after five other walls, by writing a
# line into the store over SSH and watching it be delivered -- `undelivered: 0`
# -- with no reply ever coming back. The official Telegram channel supplies
# exactly this and it is why that one works.
INSTRUCTIONS = """
The person is reading the Aki chat panel in their dashboard, NOT this
terminal. Text you print here never reaches them.

To say anything to them, call the `reply` tool. That is the only way.

When a message arrives as <channel source="aki-channel">, answer it with
`reply` even if the answer is short. Silence is indistinguishable from the
channel being broken, and they have no way to tell the difference.

Attach files by absolute path with `reply`'s `files` argument -- images, video
and audio preview in the panel; anything else is offered as a download.

The `session` in the message's meta names which agent it was addressed to.
""".strip()

REPLY_TOOL = {
    "name": "reply",
    "description": (
        "Reply to the person in the Aki chat panel. This is the ONLY way to "
        "reach them: text you print is not shown to them. Plain text; the "
        "panel renders it. Attach files by absolute path — images, video and "
        "audio are previewed in the panel, anything else is offered as a "
        "download."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "What to say. Plain text.",
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Absolute paths to attach. The file is copied into the "
                    "conversation, so it survives whatever produced it being "
                    "cleaned up."
                ),
            },
        },
        "required": ["text"],
    },
}


def _result(request_id: Any, result: dict[str, Any]) -> None:
    _send({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id: Any, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": request_id,
           "error": {"code": code, "message": message}})


def _handle(message: dict[str, Any], session: str) -> None:
    method = message.get("method")
    request_id = message.get("id")

    # A notification has no id and takes no response. Answering one is a
    # protocol error, so the check comes before anything else.
    if request_id is None:
        return

    if method == "initialize":
        asked = (message.get("params") or {}).get("protocolVersion")
        _result(request_id, {
            "protocolVersion": asked or "2025-06-18",
            # `experimental` is not optional decoration, and leaving it out
            # is why this channel delivered nothing for three days.
            #
            # Claude Code decides at `initialize` whether a server is allowed
            # to push, and it decides on this declaration alone. Without it
            # every `notifications/claude/channel` frame is dropped in
            # silence; the only trace is one line in the MCP log --
            #
            #   Channel notifications skipped: server did not declare
            #   claude/channel capability
            #
            # -- which nothing surfaces to the person typing into the panel.
            # The official Telegram plugin declares exactly this, and that is
            # the whole difference between the two (reported 2026-09-04:
            # ).
            #
            # `claude/channel/permission` is deliberately NOT declared.
            # Declaring it asserts the server authenticates whoever replies;
            # this one authenticates a file on the machine, which is not the
            # same claim.
            "capabilities": {
                "tools": {},
                "experimental": {"claude/channel": {}},
            },
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": INSTRUCTIONS,
        })
        return

    if method == "ping":
        _result(request_id, {})
        return

    if method == "tools/list":
        _result(request_id, {"tools": [REPLY_TOOL]})
        return

    if method == "tools/call":
        params = message.get("params") or {}
        if params.get("name") != "reply":
            _error(request_id, -32602, f"no such tool: {params.get('name')!r}")
            return

        arguments = params.get("arguments") or {}
        text = str(arguments.get("text") or "")
        files = arguments.get("files") or []
        if isinstance(files, str):                       # one path, unwrapped
            files = [files]

        sent = 0
        trouble: list[str] = []

        # The text rides with the first attachment as its caption, the way it
        # does in any chat: a photo and the sentence about the photo are one
        # message, not two that happen to be adjacent.
        for index, raw_path in enumerate(files):
            candidate = Path(str(raw_path))
            try:
                if not candidate.is_file():
                    raise FileNotFoundError(str(candidate))
                chat.attach("assistant", candidate,
                            text=text if index == 0 else "",
                            session=session)
                sent += 1
            except Exception as error:                   # noqa: BLE001
                trouble.append(f"{candidate.name}: {error}")

        if not files and chat.say("assistant", text, session=session):
            sent = 1
        elif files and text and sent == 0:
            # Every attachment failed. The words still deserve to arrive.
            if chat.say("assistant", text, session=session):
                sent = 1

        note = "sent" if sent else "nothing to send"
        if trouble:
            note += " — could not attach " + "; ".join(trouble)

        _result(request_id, {
            "content": [{"type": "text", "text": note}],
            "isError": bool(trouble) and sent == 0,
        })
        return

    _error(request_id, -32601, f"method not found: {method!r}")


def serve() -> int:
    """Run until stdin closes. Returns a process exit code."""
    session = chat.this_session()
    paths.ensure_app_dirs()

    # A clone made this afternoon should not wake to this morning's
    # conversation; an existing session keeps the place it had.
    chat.start_at_end(session)

    stop = threading.Event()
    watcher = threading.Thread(target=_watch, args=(session, stop),
                               name="aki-channel-watch", daemon=True)
    watcher.start()
    _log(f"listening as {session!r}")

    try:
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except ValueError:
                _log("ignored a line that was not JSON")
                continue
            if isinstance(message, dict):
                try:
                    _handle(message, session)
                except Exception as error:               # noqa: BLE001
                    _log(f"handler: {error}")
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        watcher.join(timeout=2.0)

    return 0


def main() -> int:
    # Windows consoles default to a legacy code page; a Chinese reply would
    # raise UnicodeEncodeError on the way out and take the channel with it.
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8")         # type: ignore[union-attr]
        except Exception:                                # noqa: BLE001
            pass
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
