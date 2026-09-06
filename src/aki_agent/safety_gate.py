"""A hard stop in front of the commands that cannot be undone.

WHY A SEPARATE GATE, WHEN THE ASSISTANT ALREADY ASKS PERMISSION
---------------------------------------------------------------
Permission prompts are a *conversation*, and this package's own launcher can
turn them down to "auto" — which most people choose, because being asked about
every file read is how a useful assistant becomes an ignored one. Auto mode is
the right default for ordinary work and it is precisely why a small number of
commands need a floor underneath it.

So this is not "ask the user" again. It is a short, high-precision list of
operations whose *worst case is unrecoverable*, refused regardless of who
asked, what mode is on, or how convincing the reason looked.

THE LIST IS SHORT ON PURPOSE
----------------------------
A long denylist is a false sense of safety: it grows until nobody remembers
what is in it, and it blocks ordinary work often enough that people learn to
disable it. Everything here destroys data with no undo, or rewrites shared
history. Anything merely *risky* is left to the ordinary permission flow.

FAIL OPEN, AND SAY SO
---------------------
If this module itself breaks, it allows the command and records the failure.
A safety check that blocks all work when it has a bug is a safety check that
gets removed within the week — and then nothing is checked at all. That is a
deliberate trade, and the recorded failure is what makes it honest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Each entry: a pattern, and the plain sentence a person gets back.
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*-?[a-zA-Z]*[rf][a-zA-Z]*\s+"
                r"(/|~|\$HOME|[A-Za-z]:\\?)\s*$"),
     "that deletes everything from the top of a drive or home folder"),
    (re.compile(r"\b(mkfs|format)\b.*\b([a-z]/dev/|[A-Za-z]:)"),
     "that formats a disk"),
    (re.compile(r"\bdd\b.*\bof=/dev/(sd|nvme|disk)"),
     "that writes directly over a disk"),
    (re.compile(r"(?i)\bDROP\s+(DATABASE|TABLE)\b"),
     "that destroys a database"),
    (re.compile(r"(?i)^\s*DELETE\s+FROM\s+\w+\s*(;|$)"),
     "that deletes every row in a table -- there is no WHERE clause"),
    # The lookahead has to sit BEFORE the match, not after it: `--force\b`
    # matches inside `--force-with-lease` (the boundary falls on the hyphen),
    # and a lookahead placed afterwards then sees only "-with-lease" and
    # passes. So the safe form was blocked and the dangerous one was not
    # distinguishable -- which would have taught users to switch the gate off.
    (re.compile(r"\bgit\s+push\b(?!.*--force-with-lease).*\s(--force|-f)\b"),
     "that force-pushes, which can overwrite work that is not yours"),
    (re.compile(r"\bgit\s+reset\s+--hard\b.*\borigin/(main|master)\b"),
     "that throws away every local change without a copy"),
    (re.compile(r"(?i)\bRemove-Item\b.*-Recurse.*-Force.*"
                r"([A-Za-z]:\\?\s*$|\\Users\s*$|\$env:USERPROFILE\s*$)"),
     "that recursively deletes a drive or the whole user folder"),
    (re.compile(r"\bchmod\s+-R\s+777\s+/\s*$"),
     "that makes the entire filesystem writable by anyone"),
)


@dataclass
class Verdict:
    allowed: bool
    reason: str = ""

    def as_hook_result(self) -> tuple[int, str]:
        """(exit code, message). 2 is what a blocking hook returns."""
        return (0, "") if self.allowed else (2, self.reason)


def check(command: str) -> Verdict:
    """Judge one shell command. Never raises -- see the fail-open note."""
    try:
        text = " ".join(str(command or "").split())
        if not text:
            return Verdict(True)

        for pattern, why in _RULES:
            if pattern.search(text):
                verdict = Verdict(False, (
                    f"Blocked: {why}. If this really is what you want, run it "
                    "yourself in a terminal — an assistant should not be the "
                    "thing that does it."))
                _remember(text, why)
                return verdict
        return Verdict(True)
    except Exception as exc:                             # noqa: BLE001
        from . import events

        events.record("problem", f"the safety check could not run: {exc}",
                      source="safety")
        return Verdict(True)


def describe() -> str:
    """What it refuses, for the user to read once and trust afterwards."""
    lines = ["These are refused outright, in any mode, with no prompt:", ""]
    for _pattern, why in _RULES:
        lines.append(f"  - anything {why}")
    lines += ["",
              "Everything else follows the ordinary permission rules. This "
              "list is deliberately short: a long one gets switched off."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Entry point for use as a pre-execution hook.

    Reads the command on stdin (or as arguments), prints a reason and exits 2
    to block, or exits 0 silently to allow.
    """
    import sys

    argv = argv if argv is not None else sys.argv[1:]
    if argv:
        command = " ".join(argv)
    else:
        try:
            payload = sys.stdin.read()
        except Exception as exc:                         # noqa: BLE001
            # THE ONE PATH THAT USED TO ALLOW WITHOUT A TRACE (2026-09-05)
            # -----------------------------------------------------------
            # Everywhere else this module fails open it says so: a broken
            # check records a "problem" event, which is what makes the
            # fail-open trade honest rather than merely convenient. This
            # branch did not, so a gate that could no longer read its input
            # was indistinguishable from a gate with nothing to refuse --
            # and the difference between "it has never fired" and "it has
            # been deaf for three weeks" is the whole value of the record.
            #
            # Still returns 0. Refusing every command because the gate
            # cannot read is the failure mode this module exists to avoid.
            try:
                from . import events

                events.record("problem",
                              f"the safety check could not read the command "
                              f"it was given, so it allowed it: {exc}",
                              source="safety")
            except Exception:                            # noqa: BLE001
                pass
            return 0
        command = payload
        # A hook may be handed the whole tool-call as JSON.
        if payload.strip().startswith("{"):
            import json
            try:
                data = json.loads(payload)
                command = str((data.get("tool_input") or {}).get("command",
                                                                 payload))
            except ValueError:
                command = payload

    verdict = check(command)
    code, message = verdict.as_hook_result()
    if message:
        print(message, file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

# ---------------------------------------------------------------------------
# Keeping a record
# ---------------------------------------------------------------------------

LOG_NAME = "safety-gate.jsonl"
KEEP = 200


def log_file() -> Path:
    from . import paths

    return paths.app_dir() / "state" / LOG_NAME


def _remember(command: str, why: str) -> None:
    """Write down what was refused.

    ADDED 2026-08-19, AND THE GAP IS THE POINT
    ------------------------------------------
    This gate has been stopping irreversible commands since it was written and
    keeping no record of it. So it protected the user in a way the user could
    never see: no page, no count, no way to tell "it has never fired" from "it
    fired last Tuesday and saved your documents".

    Never raises. A gate that fails because its diary is full would be worse
    than one that keeps no diary at all.
    """
    import datetime as _dt
    import json

    try:
        from . import paths

        paths.ensure_app_dirs()
        path = log_file()
        entry = {
            "at": _dt.datetime.now().isoformat(timespec="seconds"),
            # Truncated: a blocked command can carry a pasted secret, and this
            # file is read by a web page.
            "command": command[:300],
            "why": why,
        }
        lines = []
        if path.exists():
            lines = path.read_text(encoding="utf-8",
                                   errors="replace").splitlines()
        lines.append(json.dumps(entry, ensure_ascii=False))
        path.write_text("\n".join(lines[-KEEP:]) + "\n", encoding="utf-8")
    except Exception:                                    # noqa: BLE001
        return


def recent(limit: int = 50) -> list[dict]:
    """What the gate has refused, newest first."""
    import json

    try:
        lines = log_file().read_text(encoding="utf-8",
                                     errors="replace").splitlines()
    except OSError:
        return []

    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
        if len(out) >= limit:
            break
    return out
