"""The dashboard's chat box, signed in as the user, on the real conversation.

WHY THIS REPLACES A MIRROR (reported 2026-08-20)
----------------------------------------------
The dashboard used to keep its own copy: a message typed there went into a
queue, and the assistant was expected to copy it into a separate log. Two
stores, kept in step by convention. The symptoms were exactly what you would
predict and exactly what he reported — the panel lagged, his session showed
nothing arriving, and the two views disagreed.

He was certain his own assistant's dashboard did not work that way, and
remembered pairing it with *his Telegram account, not the bot*. He was right.
Reading that implementation settled it: it signs in as him with Telethon and
**sends the message as him**, to his own bot. The session receives an ordinary
Telegram message; the reply goes back through Telegram; the dashboard reads
the real history.

There is one conversation. The dashboard is a link of it, not a copy of it.

THE COST, WHICH HE ACCEPTED DELIBERATELY
----------------------------------------
This needs an `api_id` and `api_hash` from my.telegram.org — a developer
registration — and it signs in with the person's own Telegram account rather
than their bot. Both cut against this package's "no API key, nothing to
register" promise, and both were put to him plainly. His answer was to build
it and not to make it optional: *"要唔要 Aki 跟? yes / 做成可選?? NO!"*

So it is the way the dashboard chat works, and the setup asks for the two
values like anything else.

WHAT IS A SECRET HERE, AND WHAT IS NOT
--------------------------------------
The **session file** is the credential that matters. Anyone holding it is
signed in as the user — it is worth more than the bot token, because it is
their account rather than a bot. It lives in the assistant's own state folder,
it is never copied anywhere, and `uninstall` removes it.

The phone number and the login code are transient and are never written down.
The 2FA password is passed straight to Telegram and never stored, not even in
memory beyond the call.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
from pathlib import Path
from typing import Any

from . import paths, secrets

# Where Telethon keeps the signed-in session. `.session` is appended by it.
SESSION_NAME = "telegram-user"

# Read once and cached: the bot's @name, which the token already knows.
# Asking somebody for a value the software can look up is a question that
# exists only because nobody wrote the lookup.
_BOT_USERNAME: str | None = None

HISTORY_LIMIT = 200

# Transient only. The phone and the code hash live for one sign-in and are
# never written to disk; the password is never held at all.
_AUTH: dict[str, Any] = {"phone": None, "hash": None}


def session_path() -> Path:
    return paths.state_dir() / SESSION_NAME


def session_file() -> Path:
    return Path(str(session_path()) + ".session")


# ---------------------------------------------------------------------------
# The two values from my.telegram.org
# ---------------------------------------------------------------------------

def save_credentials(api_id: str, api_hash: str) -> tuple[bool, str]:
    """Keep the pair in the operating system's credential store.

    Not in the config file: that gets backed up, copied between machines and
    pasted into support conversations, and these two identify the application
    that may sign somebody in.
    """
    api_id = (api_id or "").strip()
    api_hash = (api_hash or "").strip()

    if not api_id.isdigit():
        return False, ("The API ID is the short number from my.telegram.org, "
                       "digits only.")
    if len(api_hash) < 16:
        return False, ("The API hash is the long string beside it — that does "
                       "not look like one.")

    secrets.set_secret("telegram_api_id", api_id)
    secrets.set_secret("telegram_api_hash", api_hash)
    return True, "Saved."


def credentials() -> tuple[int | None, str | None]:
    api_id = secrets.get_secret("telegram_api_id")
    api_hash = secrets.get_secret("telegram_api_hash")
    if not api_id or not api_hash:
        return None, None
    try:
        return int(api_id), api_hash
    except ValueError:
        return None, None


def bot_username() -> str:
    """The @name of their own bot, looked up from the token they already gave.

    Cached for the life of the process. A failed lookup returns "" and every
    caller treats that as "not set up yet" rather than guessing a name.
    """
    global _BOT_USERNAME
    if _BOT_USERNAME is not None:
        return _BOT_USERNAME

    from . import telegram_setup

    token = telegram_setup.read_token()
    if not token:
        _BOT_USERNAME = ""
        return ""

    try:
        import json
        import urllib.request

        with urllib.request.urlopen(
                f"https://api.telegram.org/bot{token}/getMe", timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        _BOT_USERNAME = str((data.get("result") or {}).get("username", ""))
    except Exception:                                     # noqa: BLE001
        _BOT_USERNAME = ""
    return _BOT_USERNAME


# ---------------------------------------------------------------------------
# Media
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS (reported 2026-08-20)
# -----------------------------------
# The first version of `history()` had one line in it -- `if not text:
# continue` -- and that line quietly threw away every photo, voice note and
# file in the conversation. On the panel they did not appear as anything: not
# as a placeholder, not as a gap. A voice message sent from his phone was
# simply not there.
#
# What he asked for is the ordinary thing: *"i need the same function as a
# normal telegram: attach file, images (show thumbnail), record audio...
# playback in chatpanel"*. A chat panel that can only carry plain text is a
# transcript of a conversation, not the conversation.

# Downloaded media, kept so a panel that repaints every few seconds does not
# fetch the same photo again every time. Named by message id, which is stable.
MEDIA_DIR_NAME = "chat-media"

# What the browser needs in order to show or play a thing, decided by what
# Telegram says it is. Anything unlisted is offered as a file to download,
# which is the honest fallback: a player that cannot play is worse than a link.
KIND_BY_MIME = (
    ("image/", "photo"),
    ("video/", "video"),
    ("audio/", "audio"),
)


def media_dir() -> Path:
    folder = paths.state_dir() / MEDIA_DIR_NAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _human_size(count: float) -> str:
    """A size somebody can read, rather than a number of bytes."""
    if count <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            if unit == "B":
                return f"{count:.0f} B"
            return f"{count:.1f} {unit}"
        count /= 1024.0
    return ""


def _describe_media(message) -> dict[str, Any] | None:
    """What is attached to this message, in the terms the panel draws with.

    Returns None for a message that is only text. Never downloads anything:
    this runs for every message in the history, and fetching two hundred files
    in order to draw a list is how a chat panel becomes unusable. The bytes
    are collected by `media_file()`, when the browser actually asks for them.
    """
    if not getattr(message, "media", None):
        return None

    handle = getattr(message, "file", None)
    mime = str(getattr(handle, "mime_type", "") or "")

    kind = "file"
    for prefix, name in KIND_BY_MIME:
        if mime.startswith(prefix):
            kind = name
            break

    # A voice note is an audio file Telegram has marked as one, and it is
    # worth keeping apart: it is drawn as a player rather than an attachment.
    if getattr(message, "voice", None) is not None:
        kind = "voice"

    size = float(getattr(handle, "size", 0) or 0)
    name = str(getattr(handle, "name", "") or "")
    duration = int(getattr(handle, "duration", 0) or 0)

    if not name:
        name = {"photo": "photo", "voice": "voice message",
                "audio": "audio", "video": "video"}.get(kind, "file")

    return {
        "kind": kind,
        "id": int(message.id),
        "name": name,
        "mime": mime,
        "size": _human_size(size),
        "duration": duration,
        "url": f"/chat/media/{int(message.id)}",
    }


def media_file(message_id: int) -> Path | None:
    """The bytes of one attachment, on disk, fetched once and kept.

    Returns None when there is nothing to fetch, which the route answers as a
    404 rather than as an error: asking for an attachment that is no longer
    there is a normal thing to do after a conversation has been cleared.
    """
    folder = media_dir()
    for existing in sorted(folder.glob(f"{int(message_id)}.*")):
        return existing

    bot = bot_username()
    if not bot:
        return None

    link = None
    try:
        link = _client()
        if not link.is_user_authorized():
            return None
        found = link.get_messages(bot, ids=int(message_id))
        if not found or not getattr(found, "media", None):
            return None
        # Telethon appends the extension the file actually deserves.
        saved = link.download_media(found,
                                    file=str(folder / str(int(message_id))))
        return Path(saved) if saved else None
    except Exception:                                     # noqa: BLE001
        return None
    finally:
        _shut(link)


def send_file(path, caption: str = "", voice: bool = False) -> dict[str, Any]:
    """Send one file to their bot, as them.

    `voice` marks a recording as a voice note rather than an attachment, which
    is what makes it play in place in every Telegram client. Telegram accepts
    only ogg/opus as a voice note, so anything else is sent as ordinary audio
    -- it still plays, it just is not drawn as a waveform.
    """
    source = Path(path)
    if not source.exists():
        return {"ok": False, "error": "That file is not there."}

    bot = bot_username()
    if not bot:
        return {"ok": False,
                "error": "No bot to send to — set the bot token up first."}

    link = None
    try:
        link = _client()
        if not link.is_user_authorized():
            return {"ok": False, "error": "Not signed in."}
        message = link.send_file(
            bot, str(source), caption=(caption or "").strip() or None,
            voice_note=bool(voice) and source.suffix.lower() == ".ogg",
            force_document=False)
        return {"ok": True, "id": int(getattr(message, "id", 0) or 0)}
    except Exception as exc:                              # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _shut(link)


# ---------------------------------------------------------------------------
# The link
# ---------------------------------------------------------------------------

def _client():
    """A fresh connection, on a fresh event loop, for this one call.

    NOT a long-lived connection shared across requests, and the reason is specific:
    Telethon's synchronous wrappers refuse to run after the asyncio loop they
    connected on has changed, and a web server answers requests on whichever
    thread is free. A connection kept between requests works in testing, where the
    requests are serial, and fails in use.

    This is lifted from the working implementation rather than rediscovered.
    """
    from telethon.sync import TelegramClient

    api_id, api_hash = credentials()
    if api_id is None or api_hash is None:
        raise RuntimeError("no Telegram API credentials saved")

    asyncio.set_event_loop(asyncio.new_event_loop())
    link = TelegramClient(str(session_path()), api_id, api_hash)
    link.connect()
    return link


def _shut(link) -> None:
    if link is None:
        return
    try:
        link.disconnect()
    except Exception:                                     # noqa: BLE001
        pass


def installed() -> bool:
    """Is the library even here? Its absence is a normal state, not a fault."""
    try:
        import telethon                                   # noqa: F401
    except ImportError:
        return False
    return True


def never_set_up() -> bool:
    """A definite no, bought without opening a connection.

    `status()` is the honest answer, and it costs a Telegram client -- far too
    much for the chat panel, which is on every page of the dashboard. This
    answers the narrower question the panel actually needs: is there anything
    here at all to connect through? Library missing, no credentials, or no
    session file means the answer is certainly no.

    It never claims the opposite. All three present means only "cannot be
    ruled out from disk", so a caller must treat False as "do not know", not
    as "connected" -- otherwise the panel starts asserting a connection it has
    not checked.
    """
    if not installed():
        return True
    api_id, api_hash = credentials()
    if api_id is None or api_hash is None:
        return True
    return not session_file().exists()


def status() -> dict[str, Any]:
    """Everything the page needs to decide what to show, in one read."""
    api_id, api_hash = credentials()
    ready = {
        "library": installed(),
        "credentials": api_id is not None and api_hash is not None,
        "signed_in": False,
        "bot": "",
        "session": str(session_file()),
        # Empty means "the answer above is the answer". Anything else means
        # the check itself failed and `signed_in` is not to be trusted.
        "problem": "",
    }
    if not (ready["library"] and ready["credentials"]):
        return ready

    # "Could not tell" is a third answer, and collapsing it into "no" was the
    # mistake that cost an hour here: a swallowed exception showed as a calm
    # `Signed in: no`, which somebody who HAS just signed in reads as a fault
    # in their sign-in rather than a fault in the check.
    link = None
    try:
        link = _client()
        ready["signed_in"] = bool(link.is_user_authorized())
    except Exception as exc:                              # noqa: BLE001
        ready["signed_in"] = False
        ready["problem"] = f"{type(exc).__name__}: {exc}"
    finally:
        _shut(link)

    if ready["signed_in"]:
        ready["bot"] = bot_username()
    return ready


def next_step(ready: dict[str, Any] | None = None) -> str:
    """One sentence saying what is missing, or that nothing is."""
    ready = ready or status()
    if not ready["library"]:
        return ("The Telegram library is not installed. Run `doctor` — it "
                "will offer to put it in.")
    if not ready["credentials"]:
        return ("No API ID and hash yet. Get them from my.telegram.org — it "
                "takes a minute and they never change.")
    if ready.get("problem"):
        return ("Could not check whether you are signed in — "
                + ready["problem"] + ". That is a fault in the check, not "
                "necessarily in your sign-in.")
    if not ready["signed_in"]:
        return ("Not signed in yet. Enter your phone number below and "
                "Telegram will send you a code.")
    if not ready["bot"]:
        return ("Signed in, but your bot could not be identified — check the "
                "bot token on this page.")
    return f"Signed in. Your chat box talks to @{ready['bot']} as you."


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------

def send_code(phone: str) -> dict[str, Any]:
    """Ask Telegram to text them a login code."""
    phone = (phone or "").strip().replace(" ", "")
    if not phone:
        return {"ok": False, "error": "A phone number is needed."}
    if not phone.startswith("+"):
        return {"ok": False,
                "error": ("It has to start with your country code and a plus "
                          "— +44…, +852…")}

    link = None
    try:
        link = _client()
        if link.is_user_authorized():
            return {"ok": True, "already": True}
        result = link.send_code_request(phone)
        _AUTH["phone"] = phone
        _AUTH["hash"] = result.phone_code_hash
        return {"ok": True, "sent": True}
    except Exception as exc:                              # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _shut(link)


def sign_in(code: str, password: str = "") -> dict[str, Any]:
    """Finish signing in. Returns `needs_password` when 2FA is on."""
    # The cheap checks first, and the import after them.
    #
    # Written the other way round to begin with, so a machine without the
    # library answered "no module named telethon" to a question that could be
    # settled without it -- an error about the wrong thing entirely, at the
    # exact moment somebody is trying to set the library up.
    code = (code or "").strip()
    if not code:
        return {"ok": False, "error": "The code from Telegram is needed."}
    if not (_AUTH.get("phone") and _AUTH.get("hash")):
        return {"ok": False,
                "error": "Ask for a code first — that step has expired."}

    from telethon.errors import SessionPasswordNeededError

    link = None
    try:
        link = _client()
        try:
            me = link.sign_in(phone=_AUTH["phone"], code=code,
                                phone_code_hash=_AUTH["hash"])
        except SessionPasswordNeededError:
            if not password:
                return {"ok": False, "needs_password": True}
            me = link.sign_in(password=password)

        _AUTH["phone"] = None
        _AUTH["hash"] = None
        return {"ok": True, "name": getattr(me, "first_name", "") or "you"}
    except Exception as exc:                              # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _shut(link)


def sign_out() -> tuple[bool, str]:
    """Forget the session.

    Logs out at Telegram's end as well as deleting the file, because a deleted
    file that is still an authorised session somewhere is not signed out.
    """
    link = None
    try:
        link = _client()
        if link.is_user_authorized():
            link.log_out()
    except Exception:                                     # noqa: BLE001
        pass
    finally:
        _shut(link)

    try:
        session_file().unlink(missing_ok=True)
    except OSError as exc:                                # pragma: no cover
        return False, f"could not remove the session file: {exc}"
    return True, "Signed out, and the session on this machine is gone."


# ---------------------------------------------------------------------------
# The conversation itself
# ---------------------------------------------------------------------------

def send(text: str) -> dict[str, Any]:
    """Send a message to their bot, as them."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "Nothing to send."}

    bot = bot_username()
    if not bot:
        return {"ok": False,
                "error": "No bot to send to — set the bot token up first."}

    link = None
    try:
        link = _client()
        if not link.is_user_authorized():
            return {"ok": False, "error": "Not signed in."}
        message = link.send_message(bot, text)
        return {"ok": True, "id": message.id}
    except Exception as exc:                              # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _shut(link)


def history(limit: int = HISTORY_LIMIT) -> dict[str, Any]:
    """The real conversation with their bot, newest last."""
    bot = bot_username()
    if not bot:
        return {"ok": False, "turns": [], "error": "No bot configured."}

    link = None
    try:
        link = _client()
        if not link.is_user_authorized():
            return {"ok": False, "turns": [], "error": "Not signed in."}

        turns = []
        for message in reversed(link.get_messages(bot, limit=limit)):
            text = (message.message or "").strip()
            media = _describe_media(message)
            # Text or an attachment: either one makes a turn. Only a message
            # with neither is skipped. The first version required text, so
            # every photo and voice note was silently absent from the panel.
            if not text and media is None:
                continue
            when = message.date or _dt.datetime.now(_dt.timezone.utc)
            turns.append({
                # `out` is Telethon's word for "I sent this".
                "role": "user" if message.out else "assistant",
                "text": text,
                "when": when.astimezone().strftime("%H:%M"),
                "channel": "telegram",
                "held": False,
                "media": media,
            })
        return {"ok": True, "turns": turns}
    except Exception as exc:                              # noqa: BLE001
        return {"ok": False, "turns": [],
                "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _shut(link)
