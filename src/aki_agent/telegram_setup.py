"""Connecting the assistant to Telegram, so it can reach the user's phone.

WHY TELEGRAM AND WHY IT IS OPTIONAL
-----------------------------------
An assistant that can only speak when you are sitting at the computer is a
program you open. An assistant that can reach your phone is something you
have. That is a large difference for very little machinery.

It is still optional. Everything works without it; the `file` channel exists
precisely so the notification system can be demonstrated with no account at
all.

WHAT THIS MODULE DOES AND DOES NOT DO
-------------------------------------
It does the mechanical parts: check whether the plugin is installed, write the
two configuration files, and verify afterwards.

It does NOT create the bot. A person has to talk to @BotFather themselves,
because only they can own their bot. The step-by-step for that lives in
`skills/connect-telegram/SKILL.md`, written for a non-developer.

A CORRECTION, AND THEN A CORRECTION OF THE CORRECTION
-----------------------------------------------------
This file used to state that `--channels plugin:telegram@claude-plugins-official`
**does not exist**, "verified against version 2.1.233, where the word 'channel'
does not appear in `--help` at all".

The `--help` observation was true. The conclusion drawn from it was wrong, and
it shipped.

`--channels` is a HIDDEN flag. It is absent from `--help` and present in the
binary, which now reads:

    --channels <servers...>
        MCP servers whose channel notifications (inbound push) should register
        this session. Space-separated server names.

Found by searching the installed executable for the string, after a user
reported that his generated launcher opened an ordinary session with no
Telegram -- while a hand-written launcher on another machine, passing exactly
this flag, had been working for months. The working system was the evidence;
`--help` was not.

WHAT THE FLAG ACTUALLY DOES, AND WHY THE ABSENCE WAS INVISIBLE
--------------------------------------------------------------
Installing the plugin gives the session the OUTBOUND half: it can send. What
the flag adds is the INBOUND half -- registering this session to receive pushed
messages. So without it everything looks fine. The assistant starts, the plugin
loads, replies sent from the session arrive on the phone. Only messages sent TO
the assistant go nowhere, and nothing anywhere reports that.

That is the exact failure shape this package keeps finding in itself, and this
time it was introduced BY a correction: a flag was removed because a check said
it was not real. The lesson is not "check `--help`" -- it is that **a negative
result from one source is not proof of absence when a working system disagrees
with it.**
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from . import atomic, paths

PLUGIN_ID = "telegram@claude-plugins-official"
MARKETPLACE = "claude-plugins-official"

# What `--channels` has to be given to make this session receive pushed
# messages. Named here once so the launcher cannot spell it differently from
# the plugin it is supposed to match -- a typo produces a session that starts
# normally and never receives anything.
CHANNEL_SERVER = f"plugin:{PLUGIN_ID}"


def claude_dir() -> Path:
    """Claude Code's own configuration folder."""
    return paths.home() / ".claude"


def channel_name(assistant_name: str = "") -> str:
    """The folder name this assistant's Telegram state lives under.

    NEVER the bare "telegram". That folder is the default one, and on a
    machine that already runs another Claude Code assistant it is already
    occupied -- by its token, its allow-list and its bot.pid. Writing there
    during setup does not fail, does not warn, and replaces a working
    assistant's credentials with this one's. Reading from there is worse in
    a quieter way: this assistant then sends its messages, including a reset
    PIN, out through somebody else's bot.

    Both of those were observed on a real machine on 2026-09-03, by an owner
    who happened to be watching the setup output closely enough to stop it.

    The launcher already knew this -- it exports TELEGRAM_STATE_DIR so the
    plugin keeps its state apart. Only this module did not, so the two halves
    disagreed about where the state was.
    """
    if assistant_name.strip():
        # Passed in by the launcher writer, which runs during setup -- before
        # there is a config on disk to read the name back out of.
        return f"telegram-{_slug(assistant_name)}"

    named = (os.environ.get("AKI_CHANNEL_NAME") or "").strip()
    if named:
        return named

    try:
        from . import config as config_module

        assistant = config_module.load().assistant.name
    except Exception:                                    # noqa: BLE001
        # Setup runs before there is a config to read, and the doctor runs
        # when the config may be broken. Neither is a reason to fall back to
        # the shared folder -- a name nobody chose is still this assistant's
        # own folder, which is the property that matters.
        assistant = ""

    return f"telegram-{_slug(assistant)}"


def _slug(text: str) -> str:
    import re

    cleaned = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return cleaned or "assistant"


def channel_dir() -> Path:
    """Where the token and the allow-list live.

    TELEGRAM_STATE_DIR wins when it is set, because that is the exact value
    the running plugin is using -- the launcher exports it. Agreeing with the
    process that is actually holding the connection beats re-deriving a name
    and hoping the two derivations match.
    """
    told = (os.environ.get("TELEGRAM_STATE_DIR") or "").strip()
    if told:
        return Path(told)
    return claude_dir() / "channels" / channel_name()


def token_file() -> Path:
    return channel_dir() / ".env"


def access_file() -> Path:
    return channel_dir() / "access.json"


def installed_plugins_file() -> Path:
    return claude_dir() / "plugins" / "installed_plugins.json"


# ---------------------------------------------------------------------------
# What is already in place?
# ---------------------------------------------------------------------------

@dataclass
class TelegramStatus:
    plugin_installed: bool = False
    plugin_version: str = ""
    token_present: bool = False
    allowlist_present: bool = False
    allowed_count: int = 0

    @property
    def ready(self) -> bool:
        return (self.plugin_installed and self.token_present
                and self.allowlist_present)

    def next_step(self) -> str:
        """The single next thing to do, in plain words."""
        if not self.plugin_installed:
            return ("The Telegram plugin is not installed yet. In Claude "
                    f"Code, type:  /plugin install {PLUGIN_ID}")
        if not self.token_present:
            return ("No bot token saved yet. Talk to @BotFather on Telegram "
                    "to create a bot -- the /connect-telegram skill walks you "
                    "through it.")
        if not self.allowlist_present:
            return ("The bot exists but nobody is allowed to talk to it yet. "
                    "You need your own Telegram user id, from @userinfobot.")
        return "Telegram is set up."


def status() -> TelegramStatus:
    """Look at what is on disk. Never reads the token itself."""
    result = TelegramStatus()

    registry = atomic.read_json(installed_plugins_file(), default={})
    plugins = (registry or {}).get("plugins", {})
    entries = plugins.get(PLUGIN_ID) or []
    if entries:
        result.plugin_installed = True
        result.plugin_version = str(entries[0].get("version", ""))

    # Presence only. The token is never read, logged or displayed -- knowing
    # that a secret exists is a different act from handling it, and only the
    # first one is needed here.
    token_path = token_file()
    if token_path.exists():
        try:
            result.token_present = "TELEGRAM_BOT_TOKEN=" in token_path.read_text(
                encoding="utf-8")
        except OSError:
            result.token_present = False

    access = atomic.read_json(access_file(), default=None)
    if isinstance(access, dict):
        allowed = access.get("allowFrom") or []
        result.allowlist_present = bool(allowed)
        result.allowed_count = len(allowed)

    return result


# ---------------------------------------------------------------------------
# Writing the configuration
# ---------------------------------------------------------------------------

def save_token(token: str, confirmed: bool) -> tuple[bool, str]:
    """Write the bot token where the plugin expects it.

    The token is written to Claude Code's own channel folder, which is where
    the plugin reads it from. It is deliberately NOT put in this package's
    config file, not in the OS credential store, and not anywhere else --
    duplicating a secret is how one copy gets forgotten and leaks.
    """
    if not confirmed:
        return False, "Not saved: nobody confirmed it."

    token = token.strip()
    if not _looks_like_a_bot_token(token):
        return False, (
            "That does not look like a bot token. BotFather gives you "
            "something shaped like 1234567890:AA... -- a number, a colon, "
            "then a long string. Paste the whole thing."
        )

    channel_dir().mkdir(parents=True, exist_ok=True)
    atomic.write_text(token_file(), f"TELEGRAM_BOT_TOKEN={token}\n")

    # Never echo it back, not even partially.
    return True, f"Saved. The token is in {token_file()} and nowhere else."


def _looks_like_a_bot_token(token: str) -> bool:
    """A shape check, not a validity check.

    Catches the common paste mistakes -- the bot's @name instead of its token,
    a truncated copy, the whole BotFather message -- without pretending we can
    tell whether Telegram will accept it. Only Telegram can say that.
    """
    if ":" not in token or " " in token or "\n" in token:
        return False
    bot_id, _, secret = token.partition(":")
    return bot_id.isdigit() and len(bot_id) >= 6 and len(secret) >= 20


def allow_user(user_id: str, confirmed: bool) -> tuple[bool, str]:
    """Let one Telegram user talk to this assistant.

    Uses an explicit allowlist rather than the plugin's pairing flow. Two
    reasons, and the second matters more:

      * it needs no back-and-forth on the phone
      * an unknown DM is dropped silently, instead of getting a pairing-code
        reply -- so a stranger who finds the bot learns nothing

    An assistant that answers strangers is not a smaller problem than one that
    is hard to set up.
    """
    if not confirmed:
        return False, "Not saved: nobody confirmed it."

    user_id = user_id.strip()
    if not user_id.isdigit():
        return False, (
            "A Telegram user id is a plain number. Message @userinfobot on "
            "Telegram and it replies with yours straight away."
        )

    existing = atomic.read_json(access_file(), default={}) or {}
    if not isinstance(existing, dict):
        existing = {}

    allowed = list(existing.get("allowFrom") or [])
    if user_id not in allowed:
        allowed.append(user_id)

    existing["dmPolicy"] = "allowlist"
    existing["allowFrom"] = allowed

    channel_dir().mkdir(parents=True, exist_ok=True)
    atomic.write_json(access_file(), existing)

    return True, (f"Done. {len(allowed)} person(s) may talk to this "
                  "assistant. Anyone else is ignored silently.")


def read_token() -> str:
    """The bot token, or "" — for the outbound channel, never for display.

    Read from the messaging plugin's own file rather than copied into this
    package's config, so there is exactly one place a token lives and the two
    cannot drift apart. Callers must never print or log the result.
    """
    path = token_file()
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "TELEGRAM_BOT_TOKEN":
            return value.strip().strip('"').strip("'")
    return ""


def first_allowed() -> str:
    """The user's own chat id, taken from the allow-list they set up.

    A personal assistant has one user, so the first allowed id is the right
    recipient. If that ever stops being true, this is the single place that
    decides — which is why the outbound channel asks here rather than keeping
    its own copy.
    """
    data = _read_access()
    allowed = data.get("allowFrom") or []
    for entry in allowed:
        if str(entry).strip():
            return str(entry).strip()
    return ""


def token_fingerprint() -> str:
    """Enough of the token to tell *which* one is saved. Never the token.

    WHY NOT JUST SHOW IT (reported 2026-08-20)
    ----------------------------------------
    He opened Connections, saw "Bot token: saved" and no value, and reported
    it as a bug. It is not one -- but "saved" on its own is a poor answer,
    because the real question behind it is *which* token, and that question
    deserves one.

    A bot token is a password. Anyone holding it can send and read messages as
    that bot. Printing it into a web page puts it into the browser cache, into
    every screenshot of that page, and onto the screen during any screen
    share -- and this is a package whose users are learners being taught over
    a screen share. There is no way to un-leak one; the only fix is a new bot.

    So: the bot number, which identifies the bot and is not secret, and the
    last four characters, which distinguish two tokens without being enough to
    use one.
    """
    token = read_token()
    if not token:
        return ""
    bot_number, _, rest = token.partition(":")
    if not rest:
        return "..." + token[-4:]
    return f"{bot_number}:...{rest[-4:]}"


def allowed_ids() -> list[str]:
    """Who may talk to this assistant.

    Shown in full, unlike the token, because a chat id is not a credential --
    it names a conversation and grants nothing. Hiding it behind a count was
    the actual defect: somebody who allowed the wrong id could see that there
    was one and had no way to find out which, or to take it back.
    """
    data = _read_access()
    return [str(entry).strip() for entry in (data.get("allowFrom") or [])
            if str(entry).strip()]


def remove_allowed(user_id: str) -> tuple[bool, str]:
    """Take somebody off the list.

    Being able to add without being able to remove is not an access list, it
    is a ratchet.
    """
    wanted = str(user_id).strip()
    if not wanted:
        return False, "No id given."

    data = _read_access()
    before = [str(entry).strip() for entry in (data.get("allowFrom") or [])]
    after = [entry for entry in before if entry != wanted]
    if len(after) == len(before):
        return False, f"{wanted} was not on the list."

    data["allowFrom"] = after
    try:
        # Atomically. A torn `access.json` is not a cosmetic problem: the
        # plugin reads it to decide who may talk to the assistant, and an
        # unparseable file means nobody can -- silently, with the assistant
        # apparently running normally.
        atomic.write_json(access_file(), data)
    except OSError as exc:
        return False, f"could not write the access list: {exc}"

    if not after:
        return True, (f"Removed {wanted}. Nobody is allowed now, so the "
                      "assistant cannot be reached on Telegram until you add "
                      "someone.")
    return True, f"Removed {wanted}."


def _read_access() -> dict:
    path = access_file()
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def install_plugin_command() -> str:
    """The command the user types. We do not run it for them.

    Plugin installation is a Claude Code action, not something a Python script
    should reach in and do. Telling the person exactly what to type keeps it
    honest and keeps them in control of what gets installed.
    """
    return f"/plugin install {PLUGIN_ID}"


def describe_setup() -> str:
    """The whole picture, for the setup interview to read out."""
    current = status()
    lines = ["Telegram lets the assistant reach your phone.", ""]

    lines.append(f"  Plugin installed:  "
                 f"{'yes (' + current.plugin_version + ')' if current.plugin_installed else 'no'}")
    lines.append(f"  Bot token saved:   "
                 f"{'yes' if current.token_present else 'no'}")
    lines.append(f"  People allowed:    {current.allowed_count}")
    lines.append("")
    lines.append(f"Next: {current.next_step()}")

    return "\n".join(lines)
