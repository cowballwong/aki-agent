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


def background_block() -> str:
    """What the session could not possibly know, put in front of it anyway.

    Two things, answering two different failures.

    OPEN DECISIONS, because a one-word reply has to land somewhere
    --------------------------------------------------------------
    Scheduled work raises questions from its own run and then stops existing.
    When the answer comes back -- "yes", "the second one", "do it" -- the
    session reading it never asked anything.

    `agents/assistant.md` already tells the assistant to go and read the log
    when a message looks like a fragment, and that stays. But an instruction
    is followed by a model that remembers to, and a hook is followed by all of
    them; and reading a log cannot tell two open questions apart, because a
    log does not record which answers are still outstanding. `approvals` does.

    WHAT WAS RECENTLY SENT, because no memory of it looks like it never happened
    ---------------------------------------------------------------------------
    The last few things the assistant's own scheduled work sent out. Labelled
    as a log and not as a list of jobs, because a session handed a list of
    things it has apparently not done will helpfully do them again.

    Costs one small JSON read and a tail of the chat log. Says nothing when
    there is nothing, like every other line in this file.
    """
    lines: list[str] = []

    try:
        from . import approvals

        waiting = [item for item in approvals.open_items()
                   if item.kind in ("question", "draft")]
    except Exception:                                     # noqa: BLE001
        waiting = []

    if waiting:
        lines.append(
            "These are still waiting for your user's answer. If what they "
            "just said answers one of them, THAT is what it means -- do not "
            "read it as following on from your own last message:")
        for item in waiting[:3]:
            one = f"  - [{item.id}] {item.title}"
            if item.options:
                one += ("  (" + " | ".join(f"{o.key}={o.label}"
                                           for o in item.options[:4]) + ")")
            lines.append(one)
        lines += [
            "",
            "Record the answer against the item, so it stops being open:",
            "  aki_agent.cli answer <id> <option key>",
            "  aki_agent.cli answer <id> --text \"what they actually said\"",
            "",
        ]

    try:
        from . import chat

        sent = [line for line in chat.read(limit=40)
                if line.role == "assistant"
                and str((line.meta or {}).get("origin", "")).startswith("task:")]
    except Exception:                                     # noqa: BLE001
        sent = []

    if sent:
        lines.append("Your scheduled work has ALREADY sent these. A log, not "
                     "a to-do list -- never send one of them again:")
        for line in sent[-3:]:
            # Flattened to one line each. A scheduled result is
            # often a formatted digest, and pasting its newlines
            # into this block breaks the list apart -- the reader
            # can no longer tell where one message ends.
            said = " ".join(line.text.split())[:160]
            lines.append(f"  - [{line.at.strftime('%H:%M')}] {said}")

    if not lines:
        return ""
    return ("<background-conversation>" + "\n"
            + "\n".join(lines) + "\n"
            + "</background-conversation>")


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

        blocks = [collected(), background_block()]
        text = "\n".join(one for one in blocks if one)
        if text:
            print(text)
    except Exception:                                     # noqa: BLE001
        # Deliberately silent. A hook that prints a traceback puts it into the
        # conversation, where it is both alarming and useless.
        return 0
    return 0


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
