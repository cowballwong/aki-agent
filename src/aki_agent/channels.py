"""Ways of reaching the user, and how to add another one.

WHY THIS IS AN ABSTRACTION AND NOT JUST A MESSAGING CLIENT
----------------------------------------------------------
The system this package derives from is wired to one messaging service. That
service is a perfectly good choice, and it is also the only choice, in about
a dozen places. Swapping it means editing all of them.

Here a channel is a small object with a name and a `deliver` method. Adding
one — a different messaging app, a desktop notification, an email, a text file
you tail in a terminal — means writing one class and registering it. Nothing
else in the package learns its name.

THE ONE THAT ALWAYS EXISTS
--------------------------
`file` is always registered, always available, and needs no configuration,
no account and no token. It writes messages to a text file in the user's own
folder.

That matters more than it looks: it means the notification system is testable
and demonstrable on a machine with no accounts set up, and a student who never
connects anything still sees the mechanism work. A feature that cannot be
demonstrated cannot be taught.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from . import atomic, paths, seams, secrets


@dataclass
class Message:
    """One thing the assistant wants to tell its user."""

    text: str
    urgent: bool = False
    # Free-form label for where it came from, e.g. "morning summary".
    origin: str = ""
    created_at: _dt.datetime = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.created_at is None:
            self.created_at = _dt.datetime.now()

    def safe_text(self) -> str:
        """The message with anything credential-shaped removed.

        Applied at the boundary rather than trusting every caller to remember.
        A notification is the single most likely place for a token to escape,
        because it is the one thing in the system designed to leave the
        machine.
        """
        return secrets.redact(self.text)


def as_telegram_html(text: str) -> str:
    """Turn what a language model writes into what Telegram will render.

    WHY THIS EXISTS (reported 2026-08-24)
    -----------------------------------
    His assistant's evening message arrived reading `**24 Aug —**`, asterisks
    and all:

    He was right twice. The stars were literal because messages were sent with
    no parse mode at all, so Telegram treated the markdown as punctuation --
    and a message full of stray asterisks reads as machine output whatever it
    says.

    HTML rather than MarkdownV2. MarkdownV2 requires escaping fourteen
    characters including `.` `-` `(` `!`, which every real sentence contains,
    and one missed escape means Telegram rejects the whole message. HTML needs
    three, and they are rare in prose.

    Escaping happens FIRST and the tags go in after, so nothing a model writes
    can close a tag or open one of its own.
    """
    import re

    escaped = (text.replace("&", "&amp;")
                   .replace("<", "&lt;")
                   .replace(">", "&gt;"))
    # Non-greedy, and never across a line break: emphasis does not run over a
    # paragraph, and without that limit one stray pair in a long message
    # swallows everything between it and the next one.
    return re.sub(r"\*\*(?!\s)([^\r\n]+?)\*\*", r"<b>\1</b>", escaped)


class Channel(Protocol):
    """What a channel has to provide. Deliberately tiny."""

    name: str

    def available(self) -> bool:
        """Can this channel actually deliver right now?"""

    def deliver(self, message: Message) -> tuple[bool, str]:
        """Send it. Returns (delivered, explanation)."""


class FileChannel:
    """Writes messages to a text file. Always available.

    The fallback that is never unavailable, so the notification gate can
    always be demonstrated and tested.

    THE PATH IS RESOLVED WHEN A MESSAGE IS SENT, NOT AT CONSTRUCTION
    ---------------------------------------------------------------
    The first version worked out its file path in `__init__`. Since this
    channel is registered when the module is imported, that meant the path was
    fixed before anything else had run -- so it pointed at wherever the user's
    folder was at import time, for the life of the process.

    A test caught it, but the real-world version is worse: a channel silently
    writing to a stale location is a notification the user never sees, and the
    system reports it as delivered.

    Anything derived from configuration should be read when it is used, not
    cached at start-up, unless there is a measured reason to cache it.
    """

    name = "file"

    def __init__(self, path: Path | None = None) -> None:
        # None means "ask when needed". An explicit path is honoured, which is
        # what lets a test point it somewhere specific.
        self._path = path

    @property
    def path(self) -> Path:
        return self._path or (paths.log_dir() / "messages.md")

    def available(self) -> bool:
        return True

    def deliver(self, message: Message) -> tuple[bool, str]:
        stamp = message.created_at.strftime("%Y-%m-%d %H:%M")
        marker = "**urgent** " if message.urgent else ""
        line = f"- {stamp} {marker}{message.safe_text()}"
        target = self.path
        try:
            atomic.append_line(target, line)
        except OSError as exc:
            return False, f"could not write to {target}: {exc}"
        return True, f"written to {target}"


class CallableChannel:
    """Wraps any function as a channel.

    This is the seam a messaging bridge plugs into. The bridge itself is not
    part of this package -- a student may want a different service entirely,
    and hard-wiring one is exactly the mistake being corrected.
    """

    def __init__(self, name: str, send: Callable[[str], None],
                 is_available: Callable[[], bool] | None = None) -> None:
        self.name = name
        self._send = send
        self._available = is_available or (lambda: True)

    def available(self) -> bool:
        try:
            return bool(self._available())
        except Exception:  # noqa: BLE001 -- a broken probe means unavailable
            return False

    def deliver(self, message: Message) -> tuple[bool, str]:
        try:
            self._send(message.safe_text())
        except Exception as exc:  # noqa: BLE001 -- transports fail in any way
            return False, f"{self.name} refused the message: {exc}"
        return True, f"delivered on {self.name}"


class TelegramChannel:
    """Actually sends a message to the user's phone.

    WHY THIS HAD TO EXIST, AND WHAT WAS WRONG WITHOUT IT
    ----------------------------------------------------
    The registry held only `file`. So `notify.send(..., channel_name=
    "telegram")` found no such channel and quietly held every message in the
    pending queue — forever, since nothing drains it to a channel that does
    not exist. Meanwhile the setup skill promised the user a notification gate
    with quiet hours "so the assistant will not spam you".

    Both halves were true in isolation and the combination was a lie: nothing
    was ever sent, so nothing was ever gated. Inbound worked (the messaging
    plugin's own bridge), outbound did not exist. That asymmetry is invisible
    from inside a conversation, because a reply typed by the assistant goes out
    through the plugin's own tool and never touches this package at all.

    STDLIB ONLY, ON PURPose
    -----------------------
    `urllib` rather than `requests`: the only hard dependency of this package
    is a YAML parser, and a notification path is not worth a second one.

    READS THE SAME FILES THE BRIDGE READS
    -------------------------------------
    Credentials are not duplicated into this package's own config. The token
    lives where the messaging plugin keeps it and where `telegram_setup`
    writes it; the recipient is the allow-list the same module maintains. One
    copy, so they cannot drift apart.
    """

    name = "telegram"
    TIMEOUT = 20

    def __init__(self, token: str = "", chat_id: str = "") -> None:
        # Explicit values are for tests. Normally both are read at delivery
        # time -- see FileChannel's note on why nothing is cached in __init__.
        self._token = token
        self._chat_id = chat_id

    def _credentials(self) -> tuple[str, str]:
        if self._token and self._chat_id:
            return self._token, self._chat_id
        from . import telegram_setup
        return telegram_setup.read_token(), telegram_setup.first_allowed()

    def available(self) -> bool:
        try:
            token, chat_id = self._credentials()
        except Exception:                                # noqa: BLE001
            return False
        return bool(token and chat_id)

    def deliver(self, message: Message) -> tuple[bool, str]:
        import json as _json
        import urllib.error
        import urllib.request

        token, chat_id = self._credentials()
        if not (token and chat_id):
            return False, ("no messaging account is connected yet -- run "
                           "/connect-telegram")

        plain = message.safe_text()

        # Sent as HTML so `**this**` arrives bold rather than as asterisks,
        # and retried WITHOUT formatting if Telegram objects to the markup.
        #
        # Delivery beats presentation. The failure mode of a markup bug is
        # Telegram refusing the whole message, which would turn a cosmetic
        # problem into a silent one -- exactly the trade this package keeps
        # getting wrong in the other direction.
        attempts = ((as_telegram_html(plain), "HTML"), (plain, ""))
        body = None
        refusal = ""

        for text, mode in attempts:
            fields = {"chat_id": chat_id, "text": text}
            if mode:
                fields["parse_mode"] = mode
            payload = _json.dumps(fields).encode("utf-8")
            request = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=payload, headers={"Content-Type": "application/json"})

            try:
                with urllib.request.urlopen(request,
                                            timeout=self.TIMEOUT) as reply:
                    body = _json.loads(reply.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                # The body carries the real reason (wrong chat id, bot
                # blocked, bad markup). The status code alone sends people
                # looking in the wrong place.
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", "replace")[:200]
                except Exception:                        # noqa: BLE001
                    pass
                refusal = f"the messaging service refused it: {detail or exc}"
                continue
            except (urllib.error.URLError, OSError, ValueError) as exc:
                # Not a formatting problem -- the network or the service.
                # Sending the same thing again unformatted would fail the same
                # way and only delay the answer.
                return False, f"could not reach the messaging service: {exc}"

        if body is None:
            return False, refusal or "the messaging service refused it"

        if not body.get("ok"):
            return False, f"the messaging service refused it: {body}"
        return True, "delivered to your phone"


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

_REGISTRY = seams.Registry("channel")


def best(config=None) -> str:
    """The channel a background job should send to.

    WHY THIS IS DERIVED AND NOT ASKED (reported 2026-08-20)
    -----------------------------------------------------
    Scheduled work used to default to `file`, which meant a task wrote its
    result into a file and stopped. The maintainer wants Telegram to be the main way
    the assistant is reached: he is on a phone, not at the machine, and
    something that only ever writes to disk is something he never sees.

    Not a new setting, because a setting is a question in the interview and
    then a thing that goes stale. If Telegram is connected it is the answer;
    if it is not, `file` still works and nothing had to be configured. The
    per-channel on/off switches people already have still win -- somebody who
    turned Telegram off meant it.
    """
    if config is not None:
        try:
            if not config.notifications.channel_enabled("telegram"):
                return "file"
        except AttributeError:                            # pragma: no cover
            pass

    telegram = get("telegram")
    if telegram is not None and telegram.available():
        return "telegram"
    return "file"


def register(channel: Channel) -> None:
    _REGISTRY.register(channel)


def unregister(name: str) -> None:
    _REGISTRY.unregister(name)


def get(name: str) -> Channel | None:
    return _REGISTRY.get(name)


def registered_names() -> tuple[str, ...]:
    return _REGISTRY.names()


def reset_to_defaults() -> None:
    """Clear the registry back to the channels that always exist.

    Telegram is registered even when no account is connected, and reports
    itself unavailable until one is. That is deliberate: an unregistered
    channel makes `notify.send` hold the message with "there is no channel
    called telegram" — which reads as a bug in the software rather than a
    missing account, and is exactly the message a user cannot act on.
    """
    _REGISTRY.clear()
    register(FileChannel())
    register(TelegramChannel())


reset_to_defaults()
