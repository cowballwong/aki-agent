"""A written record of every upgrade, kept whether it worked or not.

WHY (reported 2026-08-20)
-----------------------
A 0.5.0 -> 0.8.0 upgrade failed three times on Windows and left the product
unrunnable twice. What made it fixable was that somebody sat down and wrote a
narrative afterwards: what was run, what came back, what state the tree was in
between attempts. That document is the only reason the root cause was found in
an afternoon rather than being rediscovered by the next person.

Nothing in the software produced any of it. The upgrade printed one wrong
sentence -- "could not copy the engine", for an exception thrown by the delete
-- and kept no record at all. So the maintainer asked for the obvious thing: keep the
log every time, in `_upgrade`.

WHAT THIS IS NOT
----------------
Not telemetry. It is written to the user's own folder, it never leaves the
machine, and it is a file they can read, quote in a message, or delete.

THE PART THAT MATTERS MOST
--------------------------
**The failure path writes a log too, and writes it before returning.** A
recorder that only fires on success documents the runs nobody needed
documented. The whole reason this exists is the run that went wrong -- and
during that run the product may be halfway through replacing itself, so the
log is flushed at every step rather than assembled at the end and lost with
the process.
"""

from __future__ import annotations

import datetime as _dt
import platform
from pathlib import Path

from . import paths

FOLDER_NAME = "_upgrade"

# Keep the last twenty. Enough to see a pattern across releases; not so many
# that the folder becomes something nobody opens.
KEEP = 20


def folder() -> Path:
    return paths.app_dir() / FOLDER_NAME


class Recorder:
    """Collects the narrative of one upgrade and keeps the file current.

    Every `step()` rewrites the file. That is deliberately wasteful: these are
    a few kilobytes, and the alternative -- holding the story in memory until
    the end -- loses exactly the run worth keeping, because a failing upgrade
    is one of the few operations that can stop its own process from getting to
    the end.
    """

    def __init__(self, from_version: str, to_version: str,
                 source: Path | None = None, target: Path | None = None):
        self.started = _dt.datetime.now()
        self.from_version = from_version or "unknown"
        self.to_version = to_version or "unknown"
        self.source = source
        self.target = target
        self.lines: list[str] = []
        self.outcome = "did not finish"
        self.path = self._name()
        self.step("started", f"{self.from_version} -> {self.to_version}")

    # -- recording ---------------------------------------------------------

    def step(self, what: str, detail: str = "", ok: bool | None = None) -> None:
        mark = "" if ok is None else ("ok - " if ok else "FAILED - ")
        stamp = _dt.datetime.now().strftime("%H:%M:%S")
        self.lines.append(f"{stamp}  {mark}{what}"
                          + (f"\n           {detail}" if detail else ""))
        self._flush()

    def note(self, text: str) -> None:
        self.lines.append(f"           {text}")
        self._flush()

    def finish(self, outcome: str) -> Path:
        self.outcome = outcome
        self._flush()
        self._prune()
        return self.path

    # -- the file ----------------------------------------------------------

    def _name(self) -> Path:
        base = folder() / f"upgrade-{self.started:%Y-%m-%d}"
        candidate = base.with_name(base.name + ".md")
        count = 2
        while candidate.exists():
            candidate = base.with_name(f"{base.name}-{count}.md")
            count += 1
        return candidate

    def _flush(self) -> None:
        try:
            folder().mkdir(parents=True, exist_ok=True)
            self.path.write_text(self._render(), encoding="utf-8")
        except OSError:
            # A log that cannot be written must never stop an upgrade. The
            # upgrade is the thing the user asked for; this is a courtesy.
            pass

    def _render(self) -> str:
        head = [
            f"# Upgrade log - {self.from_version} -> {self.to_version}",
            "",
            f"**When:** {self.started:%Y-%m-%d %H:%M}",
            f"**Outcome:** {self.outcome}",
            f"**Machine:** {platform.platform()}, "
            f"Python {platform.python_version()}",
        ]
        if self.source:
            head.append(f"**From:** `{self.source}`")
        if self.target:
            head.append(f"**To:** `{self.target}`")
        head += ["", "---", "", "## What happened", "", "```"]
        return "\n".join(head + self.lines + ["```", "",
                                             self._footer(), ""])

    def _footer(self) -> str:
        if self.outcome == "done":
            return ("If something is wrong after this, the previous engine is "
                    "kept alongside the new one and\n`aki_agent.cli rollback` "
                    "puts it back.")
        return ("An upgrade that did not finish leaves the engine you had in "
                "place -- it is staged and swapped,\nnever deleted first. "
                "Re-running it is safe. If the engine is somehow broken, "
                "`aki_agent.cli rollback`\nreturns the previous one.")

    def _prune(self) -> None:
        try:
            kept = sorted(folder().glob("upgrade-*.md"),
                          key=lambda one: one.stat().st_mtime, reverse=True)
            for old in kept[KEEP:]:
                old.unlink()
        except OSError:
            pass


def latest() -> Path | None:
    """The most recent log, for `doctor` and for anyone asking what happened."""
    try:
        found = sorted(folder().glob("upgrade-*.md"),
                       key=lambda one: one.stat().st_mtime, reverse=True)
    except OSError:
        return None
    return found[0] if found else None
