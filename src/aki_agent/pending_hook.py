"""Putting a dashboard message into the live session, the moment there is one.

WHY (reported 2026-08-20)
-----------------------
He typed into the dashboard's chat panel, saw nothing arrive in his session,
got a reply some time later, and reasonably suspected a fault. There was none:
dashboard messages queue on purpose rather than interrupting, and a scheduled
task collected them — every thirty minutes at the time.

Then he named the thing that actually mattered, from memory of building his
own system: **. His own assistant's dashboard has no such lag, and the reason is
that it does not poll. A hook feeds whatever is waiting straight into the
running session on his next prompt.

So does this one now.

WHAT A HOOK CAN DO THAT A TIMER CANNOT
--------------------------------------
A timer, however short, is still a wait: the person types, and then nothing
happens for a while. Five minutes is better than thirty and is still long
enough to look broken. A hook has no interval at all — the next thing they
say carries everything that was queued, so the two halves of the conversation
arrive together.

The scheduled task stays. It is what covers the hours when nobody is typing
into the session at all, and belt-and-braces is right here: the failure it
guards against is a message somebody typed and watched be ignored, which
costs more trust than a duplicate ever will.

THE RULES A PROMPT HOOK MUST FOLLOW
-----------------------------------
This runs before **every single thing the user says**. That constrains it more
than anything else in the package:

1. **Never fail.** An exception here is an exception on every prompt, and the
   symptom is an assistant that has stopped working for no visible reason.
   Everything is wrapped; the exit code is always 0.
2. **Never be slow.** One small JSON read. No model call, no network, no
   scanning the workspace.
3. **Say nothing when there is nothing.** Printing "no messages waiting"
   before every prompt would put a line of noise into every turn for ever --
   and it is the same "absence of news is not news" rule the tasks and the
   persona already follow.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def mine(payload: dict) -> bool:
    """Whether the session that just got a prompt is this assistant's own.

    WHY (reported 2026-09-04)
    -----------------------
    He typed two messages into the dashboard, nothing reached the assistant,
    and the queue was empty afterwards -- which reads as the queue losing
    them. It had not. A *different* Claude Code session on the same machine
    drained it: he runs another assistant out of a folder on his Google
    Drive, and this package's hooks are installed for the user, not for a
    folder, so they fire on every prompt in every session there is.

    `take_pending` empties the queue exactly once. The first session to ask
    therefore takes a message addressed to a different assistant, answers it
    somewhere he is not looking, and the one he was waiting on never learns
    it was said.

    So the queue belongs to whoever is working inside this install. Anything
    else asking gets nothing, and -- this is the point -- the messages stay
    on the list for the session they were meant for.

    Conservative on purpose: if the payload carries no `cwd`, or the config
    cannot be read, the answer is no. A message that waits is recoverable; a
    message handed to the wrong assistant is not.
    """
    where = str(payload.get("cwd") or "").strip()
    if not where:
        return False
    try:
        from . import config as config_module

        root = config_module.load().layout.root
        if root is None:
            return False
        root = Path(root).resolve()
        here = Path(where).resolve()
    except Exception:                                     # noqa: BLE001
        return False
    return here == root or root in here.parents


def collected() -> str:
    """Whatever the dashboard is holding, framed for the session to act on.

    Empty string when there is nothing, which the caller prints as nothing at
    all.
    """
    from . import conversation

    waiting = conversation.take_pending()
    if not waiting:
        return ""

    lines = [
        "<dashboard-messages>",
        f"{len(waiting)} message(s) your user typed into the dashboard while "
        "you were not looking. They are speaking to you: treat each one as "
        "though they had just said it here, and answer it.",
        "",
    ]
    for entry in waiting:
        when = str(entry.get("at", ""))[11:16]
        text = str(entry.get("text", "")).strip()
        if text:
            lines.append(f"[{when}] {text}")
    lines.append("</dashboard-messages>")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the UserPromptSubmit hook.

    Anything printed to stdout is added to the session's context, so the
    messages arrive as part of the turn the user has just started.

    Returns 0 unconditionally. A prompt hook that can fail is a prompt hook
    that can stop somebody's assistant answering, and no message queued in a
    dashboard is worth that.
    """
    try:
        # The payload on stdin says which session is asking. It is read
        # first in any case, so the pipe is drained and the caller never
        # blocks on a full buffer -- and now it is also read for `cwd`, which
        # is what keeps another assistant's session from taking this one's
        # messages. See `mine`.
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except Exception:                                 # noqa: BLE001
            payload = {}

        if not isinstance(payload, dict) or not mine(payload):
            return 0

        text = collected()
        if text:
            print(text)
    except Exception:                                     # noqa: BLE001
        # Deliberately silent. A hook that prints a traceback puts it into the
        # conversation, where it is both alarming and useless.
        return 0
    return 0


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
