"""The user's own standing instructions, in a place the assistant reads.

WHY THIS IS NOT THE SAFETY GATE (reported 2026-08-20)
---------------------------------------------------
He looked at the Safety page, asked whether it was house rules, and — told it
was not — asked for house rules as well. Both belong, and keeping them apart
is the point:

  **`safety_gate.py`** is a short list of commands refused by *code*, in any
  mode, whatever anybody says. It cannot be edited from a web page, because a
  floor that can be lifted from a web page is not a floor.

  **This** is what the user wants their assistant to do. It is followed, not
  enforced. It is theirs to write, change and delete.

Mixing the two would be the worse mistake of the two available: a page that
shows "never send an email without asking" beside "rm -rf is refused" teaches
somebody that both are guaranteed, and one of them is not.

A RULE THAT ONLY LIVES IN A DASHBOARD IS DECORATION
---------------------------------------------------
The failure this package keeps finding in itself is a working mechanism with
nothing wired to it. Twice on the day this was written: an instruction in a
file nothing read, and a question with no card so the phone showed nothing.

So the rules are written to `house-rules.md` in the assistant's own folder,
the workspace `CLAUDE.md` carries a permanent line telling every session to
read it, and the agent brief says to follow it. The dashboard owns that whole
file and never edits the user's own prose — a marked block inside somebody
else's document is a thing that eventually eats a paragraph.

SOME OF THEM ARE ALSO ENFORCED, AND THAT IS WORTH SAYING
--------------------------------------------------------
The maintainer's own example — *no email goes out before approval* — happens to be
true in code as well: `connectors/mail.send` refuses without an explicit yes,
every message, every time. Most house rules have no such backing.

`backed_by_code` says which is which, and the page shows it, because "the
assistant has been told" and "the software will not let it" are different
promises and a person deciding how much to trust an unattended agent needs to
know which one they have.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

from . import atomic, paths

FILE_NAME = "house-rules.md"

# Where the assistant is told to look. One line, permanent, in the workspace
# CLAUDE.md -- see `scaffold`.
POINTER = "read your house rules"


@dataclass(frozen=True)
class Backing:
    """A rule that is also true in code, and where."""

    matches: tuple[str, ...]
    where: str
    detail: str


# Rules that the software genuinely enforces, recognised by what the user
# wrote rather than by an id -- somebody typing their own words should still
# be told their rule has teeth.
#
# Deliberately short. Claiming enforcement that does not exist is worse than
# claiming none: it is the difference between an assistant being careful and
# an assistant being unable, and somebody leaving one running unattended is
# making that exact judgement.
# THE BADGE USED TO OVER-CLAIM (2026-08-23)
# -----------------------------------------
# The match is a substring test over the whole rule, so a rule that merely
# mentions one of these words gets the badge. That is the right behaviour --
# somebody typing their own words should still be told when the software is
# behind them -- but it only works if what the badge SAYS is narrow enough to
# be true of every rule that can match it.
#
# It was not. "Never delete anything in my project folders" earned a badge
# reading "the unrecoverable commands are refused outright", which describes
# whole-drive `rm -rf` and says nothing about a project folder. "Never post my
# email address anywhere" earned one about outgoing mail. And the credentials
# claim named `secrets.redact` while `memory.py` did not import it, so
# `/remember-this` wrote raw text -- that gap is closed now, and the wording
# below is narrowed to what the code actually does in each case.
BACKED = (
    Backing(("email", "e-mail", "mail"), "connectors/mail.send",
            "sending is off unless you turn it on for that mailbox, and each "
            "message asks separately. What is in a message is still yours to "
            "judge"),
    Backing(("delete", "rm -rf", "format", "drop database"),
            "safety_gate", "commands that would take a whole drive, disk or "
            "database are refused outright, in any mode. Ordinary deleting "
            "still goes through the permission prompt"),
    Backing(("password", "secret", "key", "credential", "token"),
            "secrets.redact", "anything that looks like a credential is "
            "stripped from what is logged, remembered or sent — including the "
            "daily narrative and saved facts"),
)


def backed_by_code(rule: str) -> Backing | None:
    """Whether this rule is also enforced, and by what."""
    lowered = rule.casefold()
    for backing in BACKED:
        if any(word in lowered for word in backing.matches):
            return backing
    return None


def rules_file() -> Path:
    return paths.app_dir() / FILE_NAME


def ensure() -> Path:
    """Make sure the file exists, empty if need be.

    WHY (2026-08-20, found by a user's own assistant)
    ------------------------------------------------
    The workspace notes were taught to say *read your house rules at the start
    of every session*, and nothing created the file. The first thing the
    assistant did on the next run was report that it had been told to read
    something that was not there.

    An instruction pointing at a missing file is worse than no instruction:
    it makes the assistant open a session by describing a fault, and it makes
    the user wonder what else is broken. An empty file that says "none set" is
    an answer.
    """
    if not rules_file().exists():
        write([])
    return rules_file()


def read() -> list[str]:
    """The rules, in order. Missing file means none, which is a normal state."""
    try:
        text = rules_file().read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    found = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            rule = stripped[2:].strip()
            if rule:
                found.append(rule)
    return found


def write(rules: list[str]) -> Path:
    """Replace the list.

    The file is written whole, and it is the dashboard's file — the user's own
    writing lives in `CLAUDE.md`, which this never touches. Rewriting a marked
    block inside somebody else's document is a thing that eventually eats a
    paragraph of theirs.
    """
    cleaned = [one.strip() for one in rules if one and one.strip()]

    lines = [
        "# House rules",
        "",
        "Standing instructions from the person this assistant works for.",
        "**Follow them.** They are not suggestions, and they outrank your own",
        "judgement about what would be more helpful.",
        "",
        "They are not the same as the safety gate: that refuses a short list",
        "of unrecoverable commands in code, whatever anybody says. These are",
        "theirs, and they change. Read this file at the start of every",
        "session — it may have changed since the last one.",
        "",
        f"_Last changed {_dt.datetime.now():%Y-%m-%d %H:%M}. Edited on the "
        "dashboard's House rules page, or just ask._",
        "",
    ]
    if cleaned:
        lines += [f"- {one}" for one in cleaned]
    else:
        lines.append("_None set. The user has not asked for anything "
                     "specific; use your ordinary judgement._")
    lines.append("")

    return atomic.write_text(rules_file(), "\n".join(lines))


def add(rule: str) -> tuple[bool, str]:
    rule = (rule or "").strip()
    if not rule:
        return False, "Nothing to add."
    if len(rule) > 400:
        return False, ("That is long enough to be a paragraph rather than a "
                       "rule. A rule somebody cannot hold in their head is "
                       "one nobody checks against.")

    existing = read()
    if any(rule.casefold() == one.casefold() for one in existing):
        return False, "That one is already there."

    write(existing + [rule])
    return True, "Added."


def remove(rule: str) -> tuple[bool, str]:
    existing = read()
    remaining = [one for one in existing if one != rule]
    if len(remaining) == len(existing):
        return False, "That rule is not in the list."
    write(remaining)
    return True, "Removed."


# Offered on an empty page, never written without being chosen. Suggestions
# are not defaults: a rule somebody did not choose is one they will not
# remember agreeing to, and the first time it gets in their way they will
# distrust the whole list rather than that one line.
SUGGESTIONS = (
    "No email goes out until I have seen it and said yes.",
    "Never message anyone but me without asking first.",
    "Tell me what you are about to spend money on before you spend it.",
    "Ask before touching anything outside my workspace folder.",
    "If you are not sure, stop and ask rather than guessing.",
    "Say when you could not verify something, instead of assuming it worked.",
)
