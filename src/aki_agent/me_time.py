"""Me time: away from the desk, but not out of touch.

reported 2026-08-23:



and, on when it stops.

WHAT THIS MODULE IS AND IS NOT
------------------------------
It is the switch, and the record of when it was thrown. It is deliberately
not the watching: that happens in a scheduled task, which is the only thing
on this machine that runs when nobody is looking. A module that both held
the state and did the work would need to be running to be asked whether it
is on -- which is the wrong way round.

So: this file answers "is me time on, and since when".

NOTHING ASKS IT YET (2026-08-23)
--------------------------------
This paragraph used to say "`tasks.py` asks it". It does not, and never has
-- `grep -rn me_time src/` reaches this module, four display lines in the
dashboard, and nothing else. There is no scheduled task that reads mail, and
`connectors.mail.recent()` has no production caller either, so the watching
half does not exist at any layer.

The switch is still real: it records that the user has stepped away, and
when. What has been corrected is the wording around it, which told the user
in writing that their email was being watched while they walked away
trusting it. A switch that overstates itself is worse than one that is
plainly unfinished, and the person most harmed is the one who believed it.

THE INVERSION THAT MATTERS
--------------------------
Every other quiet-hours rule in this package makes the assistant *less*
likely to interrupt. This one makes it more likely, on purpose, and only
while you have said so. That is why it is a button you press twice rather
than a schedule: a mode that turns itself on could interrupt you on a day
you never asked about.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

from . import atomic, paths


def state_file() -> Path:
    return paths.state_dir() / "me-time.json"


@dataclass
class MeTime:
    """Whether it is on, and what it has already told you about."""

    on: bool = False
    since: str = ""
    told_about: tuple[str, ...] = ()

    def running_for(self, now: _dt.datetime | None = None) -> str:
        """How long it has been on, in words. Empty when it is off."""
        if not self.on or not self.since:
            return ""
        try:
            started = _dt.datetime.fromisoformat(self.since)
        except ValueError:
            return ""
        minutes = int(((now or _dt.datetime.now()) - started).total_seconds()
                      // 60)
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{minutes} min"
        hours, rest = divmod(minutes, 60)
        return f"{hours}h {rest:02d}m"

    def sentence(self, config=None) -> str:
        """What is actually happening, in those words.

        Takes the config so it can say whether there is a mailbox to watch.
        Without one this is still a real switch — it records that you have
        stepped away — but saying "watching your inbox" to somebody who has
        never connected one would be the same overstatement this copy was
        corrected for once already.
        """
        if not self.on:
            return "Off. Nothing is watching your inbox for you."

        for_how_long = self.running_for()
        connected = bool(getattr(getattr(config, "connections", None),
                                 "mail", ()) or ())
        if not connected:
            return (f"On for {for_how_long}. Aki knows you have stepped away. "
                    "No mailbox is connected, so there is nothing to watch — "
                    "add one on Connections and this starts working.")

        told = len(self.told_about)
        so_far = (f" Raised {told} so far." if told else
                  " Nothing worth interrupting you for yet.")
        return (f"On for {for_how_long}. Watching your mail every ten minutes "
                f"and interrupting only for the words you marked urgent."
                + so_far)


def read() -> MeTime:
    stored = atomic.read_json(state_file(), default={}) or {}
    if not isinstance(stored, dict):
        return MeTime()
    return MeTime(
        on=bool(stored.get("on", False)),
        since=str(stored.get("since", "")),
        told_about=tuple(str(one) for one in stored.get("told_about") or ()),
    )


def _write(state: MeTime) -> MeTime:
    atomic.write_json(state_file(), {
        "on": state.on,
        "since": state.since,
        "told_about": list(state.told_about),
    })
    return state


def turn_on(now: _dt.datetime | None = None) -> MeTime:
    """Start watching. Forgets what it told you about last time.

    The forgetting is the point: yesterday's urgent email is not a reason to
    stay silent about today's.
    """
    return _write(MeTime(on=True,
                         since=(now or _dt.datetime.now()).isoformat(
                             timespec="seconds"),
                         told_about=()))


def turn_off() -> MeTime:
    """You are back at the desk."""
    return _write(MeTime(on=False, since="", told_about=()))


def toggle(now: _dt.datetime | None = None) -> MeTime:
    current = read()
    return turn_off() if current.on else turn_on(now)


def look_for_something_urgent(config, now: _dt.datetime | None = None
                              ) -> tuple[int, str]:
    """Read the connected mailboxes and pick out what should interrupt.

    Returns (how many are worth raising, what to say). `(0, "")` means say
    nothing, and that is the usual answer — a watcher that speaks most times
    it runs is one that gets switched off within a week.

    THE WATCHER THAT DID NOT EXIST (built 2026-08-23)
    --------------------------------------------------
    Everything around this was here: the switch, the state, the
    de-duplication, and copy telling the user their email was being watched
    while they walked away trusting it. Nothing read a mailbox — `me_time` was
    reached only by four display lines, and `connectors.mail.recent()` had no
    production caller at all.

    WHAT IT WILL NOT DO
    -------------------
    Nothing at all unless me time is on AND a mailbox is genuinely connected.
    Not "configured" — connected, with a password in the credential store. An
    account whose password is missing is reported, not guessed at, because a
    watcher that silently reads nothing is the failure this replaces.

    It never marks anything read: `mail.recent` opens the folder read-only.
    It never sends a reply. It raises, and a person decides.

    URGENCY IS THE USER'S WORD, NOT A GUESS
    ---------------------------------------
    Matched against `notifications.urgent_keywords`, which they typed
    themselves on the Notifications page. Inferring urgency from tone would be
    a model call per email and would be wrong in a way nobody could correct.
    With no keywords set, nothing is urgent and this stays quiet — which is
    the honest default, because the alternative is deciding on their behalf
    what is worth interrupting a break for.
    """
    from .connectors import mail as mail_module

    state = read()
    if not state.on:
        return 0, ""

    words = [word.casefold() for word in
             getattr(config.notifications, "urgent_keywords", ()) or ()
             if word.strip()]
    if not words:
        return 0, ""

    accounts = getattr(config.connections, "mail", ()) or ()
    if not accounts:
        return 0, ""

    found: list[str] = []
    troubles: list[str] = []

    for entry in accounts:
        try:
            account = mail_module.from_config(entry)
            messages = mail_module.recent(account, limit=25, unread_only=True)
        except Exception as exc:                         # noqa: BLE001
            # Said out loud rather than swallowed. "I watched and there was
            # nothing" and "I could not look" are different sentences, and
            # only one of them means you can relax.
            troubles.append(f"{getattr(entry, 'address', 'a mailbox')}: {exc}")
            continue

        for message in messages:
            haystack = f"{message.subject} {message.sender}".casefold()
            if not any(word in haystack for word in words):
                continue
            key = f"{getattr(entry, 'address', '')}:{message.uid}"
            if already_told(key):
                continue
            remember_told(key)
            found.append(message.safe_summary())

    if not found and not troubles:
        return 0, ""

    lines: list[str] = []
    if found:
        lines.append(f"While you are away, {len(found)} thing"
                     f"{'s' if len(found) != 1 else ''} came in that matched "
                     "what you said was urgent:")
        lines.append("")
        lines += [f"- {one}" for one in found]
    if troubles:
        if lines:
            lines.append("")
        lines.append("I could not check " + "; ".join(troubles)
                     + " — so this is not a clean 'nothing came in'.")

    return len(found), "\n".join(lines)


def already_told(key: str) -> bool:
    """Has this email already been raised during this me-time?

    Without this the watcher re-reports the same message every time it runs,
    which teaches somebody to ignore it -- and the one it teaches them to
    ignore is, by construction, the urgent one.
    """
    return key in read().told_about


def remember_told(key: str) -> MeTime:
    current = read()
    if not current.on or key in current.told_about:
        return current
    # Bounded: a long afternoon should not grow this file without limit.
    kept = (current.told_about + (key,))[-200:]
    return _write(MeTime(on=True, since=current.since, told_about=kept))
