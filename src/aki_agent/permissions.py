"""The tools this assistant may use without stopping to ask.

WHY THIS EXISTS
---------------
A user asked their assistant, from their phone, to look something up on the
web. It replied that the web tools had no permission in this session, and it was
right: nothing in this package had ever written a permission of any kind.
`situation.py` reads Claude Code's settings to detect hooks; no line anywhere
wrote one back.

That is survivable at a keyboard, where an approval prompt appears and the
person presses a key. From a phone it is not a prompt at all. The session is
waiting on an answer nobody can see, and the only thing the user is told is
that their assistant cannot do the thing they asked for.

WHY THE WORKSPACE FILE AND NOT `~/.claude/settings.json`
--------------------------------------------------------
Because the home file applies to **every** Claude Code session on the machine,
including other people's assistants and the user's own unrelated work.

This package has made that exact mistake once already: its hooks were
installed globally and fired inside a different assistant's sessions, where
they did real damage before anyone worked out why. A permission is a smaller
blast radius than a hook and the principle is identical — an assistant
configures itself, never the machine.

The launcher `cd`s into the workspace before starting Claude Code, so
`<workspace>/.claude/settings.json` is read for exactly the sessions this
assistant runs in and no others. Scheduled work is unaffected either way: it
runs headless with an explicit `--allowedTools` list built in `runner.py`,
which this does not touch and must not.

WHY ONLY THE TWO WEB TOOLS
--------------------------
They are read-only, they are what was actually reported broken, and they can
be named exactly.

The obvious next candidate is a `Bash(...)` rule for this package's own
commands, and it is deliberately not here. A Bash rule has to match the
command as it is actually written, and the assistant writes it two ways: the
skills use `${CLAUDE_PLUGIN_ROOT}/bin/_bootstrap.py`, while everything
generated from Python uses the expanded install path. A rule that matches
neither reliably would sit in the file looking like a granted permission while
changing nothing, and a permission that lies is worse than one that is absent:
the next person to debug this would cross it off the list.

So the rule for adding to this list is the rule the package uses everywhere
else — grant what can be named exactly, and leave what cannot to the prompt.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import atomic

# Read-only, outward-reading, and the pair the user actually hit.
WEB_TOOLS = ("WebSearch", "WebFetch")

GRANTED = WEB_TOOLS


def settings_file(workspace: Path) -> Path:
    """Claude Code's project settings for the workspace this assistant runs in."""
    return Path(workspace) / ".claude" / "settings.json"


def _allow_list(data: object) -> list:
    """The `permissions.allow` list, whatever shape the file is in.

    Returns a list even when the file is empty, unreadable-as-expected, or has
    `permissions` set to something that is not an object. The caller decides
    what to do about it; this never raises for a merely surprising file.
    """
    if not isinstance(data, dict):
        return []
    block = data.get("permissions")
    if not isinstance(block, dict):
        return []
    allowed = block.get("allow")
    return list(allowed) if isinstance(allowed, list) else []


def missing(workspace: Path) -> list[str]:
    """Which of the granted tools are not in the workspace settings yet."""
    try:
        data = json.loads(settings_file(workspace).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    have = set(_allow_list(data))
    return [tool for tool in GRANTED if tool not in have]


def ensure(workspace: Path) -> tuple[bool, str]:
    """Add the granted tools to the workspace settings, keeping everything else.

    Additive by construction: the file is read, entries are appended to
    `permissions.allow` if they are absent, and every other key is written back
    untouched. Nothing here removes a permission — a user who has taken one
    away has decided something, and an upgrade that silently reinstated it
    would be the same bug as a launcher that rewrites its own removal.

    A file that will not parse is left alone and reported. Overwriting it would
    destroy settings this package did not write.
    """
    path = settings_file(Path(workspace))
    data: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as problem:
            return False, (f"{path} could not be read ({problem}), so it was "
                           "left alone. Fix or delete it and run repair again.")
        if not isinstance(loaded, dict):
            return False, (f"{path} is not a settings object, so it was left "
                           "alone.")
        data = loaded

    allowed = _allow_list(data)
    added = [tool for tool in GRANTED if tool not in allowed]
    if not added:
        return True, "the web tools were already allowed"

    block = data.get("permissions")
    data["permissions"] = block if isinstance(block, dict) else {}
    data["permissions"]["allow"] = allowed + added

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_json(path, data)
    except OSError as problem:
        return False, f"could not write {path}: {problem}"
    return True, f"allowed {', '.join(added)} in {path}"
