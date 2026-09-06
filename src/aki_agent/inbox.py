"""The assistant's side of the conversation mirror.

WHY THIS FILE EXISTS
--------------------
`conversation.py` can record a turn and can hand over anything queued from the
dashboard. Nothing called either.

So the mirror was half a mirror: messages the assistant *sent* appeared,
because those pass through the notification gate. Messages the user sent from
their phone never appeared, and messages typed into the dashboard queued
forever under a label saying "waiting to be picked up" — with nothing that
could ever pick them up.

That is the fifth time in this build the same shape appeared: a correct
mechanism with nothing wired to it. It is worth counting, because the lesson
is not "be more careful" — it is that a function passing its own unit test
tells you nothing about whether anything reaches it.

WHAT THIS IS
------------
A tiny command-line surface the assistant itself calls, because the assistant
is a language model reading instructions, not code that can import a module.

    python "<engine>/bin/_bootstrap.py" aki_agent.inbox pending
        prints anything the user typed into the dashboard, and clears it.
        Claimed exactly once -- see the note in conversation.take_pending.

    python "<engine>/bin/_bootstrap.py" aki_agent.inbox said "what they said"
        records something the user said, wherever they said it.

    python "<engine>/bin/_bootstrap.py" aki_agent.inbox replied "what I said"
        records a reply that did NOT go through the notification gate --
        an answer typed straight back in a session, for instance.

The assistant's own instructions (`agents/assistant.md`) tell it to use these.
That is the wiring, and it is as much a part of the feature as the code.
"""

from __future__ import annotations

import sys

from . import conversation


def collect_pending() -> str:
    """Take everything queued from the dashboard and present it to read.

    Returns text rather than printing, so it is testable without capturing
    stdout.
    """
    waiting = conversation.take_pending()
    if not waiting:
        return "Nothing waiting."

    lines = [f"{len(waiting)} message(s) typed into the dashboard:", ""]
    for entry in waiting:
        when = str(entry.get("at", ""))[11:16]
        lines.append(f"  [{when}] {entry.get('text', '')}")
    lines += [
        "",
        "These are from your user. Treat them as things they said to you.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    command = argv[1] if len(argv) > 1 else "pending"
    channel, words = _split_channel(argv[2:])
    rest = " ".join(words).strip()

    if command == "pending":
        print(collect_pending())
        return 0

    if command == "said":
        if not rest:
            print("Nothing to record.")
            return 2
        # Written to the CHAT STORE, which mirrors into the conversation log
        # itself. Writing only the side log is what left the dashboard panel
        # showing a Telegram conversation with the replies missing, or the
        # messages missing, depending on which file it happened to render
        # (2026-09-04). `deliver=False` because the session is the thing
        # running this command -- it already has the message.
        from . import chat

        chat.say("user", rest, meta={"channel": channel}, deliver=False)
        print("Recorded.")
        return 0

    if command == "replied":
        if not rest:
            print("Nothing to record.")
            return 2
        # `chat.say` mirrors into the conversation log and skips a duplicate
        # itself, so the guard that used to live here would now be a second
        # opinion about the same question.
        from . import chat

        chat.say("assistant", rest, meta={"channel": channel})
        print("Recorded.")
        return 0

    if command == "show":
        for turn in conversation.read(limit=40):
            who = "you" if turn.role == "assistant" else "them"
            print(f"[{turn.at[:16].replace('T', ' ')}] {who}: {turn.text}")
        return 0

    print(__doc__.split("WHAT THIS IS")[-1].strip())
    return 2


def _split_channel(words: list[str]) -> tuple[str, list[str]]:
    """Pull `--channel X` out of the words, and return the rest as the message.

    A test caught the first version recording the message as
    "chase them again --channel telegram" -- the flag was read AND left in the
    text. The flag has to be removed as well as read, and doing both in one
    function is what makes that impossible to forget.
    """
    channel = "chat"
    remaining: list[str] = []
    index = 0

    while index < len(words):
        if words[index] == "--channel" and index + 1 < len(words):
            channel = words[index + 1]
            index += 2
            continue
        remaining.append(words[index])
        index += 1

    return channel, remaining


if __name__ == "__main__":
    raise SystemExit(main())
