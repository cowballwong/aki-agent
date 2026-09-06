"""Removing a workspace or a project, without ever destroying somebody's work.

The maintainer asked for a minus button next to the plus button, with a double
confirmation. The plus button is easy. The minus button is the one that needs
thinking about, because the thing behind it is a folder full of the user's own
documents -- the exact thing the rest of this package refuses to touch.

WHAT "REMOVE" MEANS HERE, AND WHY IT IS NOT `rmtree`
---------------------------------------------------
It **moves the folder into the sandbox**, under `_removed/`, with the date on
the end. Nothing is deleted.

The reason is not caution for its own sake. A dashboard button is one mistaken
click, on a laptop, with no undo, against a folder that may hold the only copy
of something. Windows Explorer's own delete goes to a Recycle Bin for exactly
this reason, and doing worse than Explorer inside a personal assistant is not
a defensible trade. The sandbox is already the one place in the design where
"nothing in here is safe to keep" is stated to the user, so it is where a
retired folder belongs until they empty it themselves.

The double confirmation the maintainer asked for is therefore the second of two very
different guards, not the only one:

  1. the person has to type the name back, so a click cannot do it alone;
  2. and even then, the work is moved rather than destroyed.
"""

from __future__ import annotations

import datetime as _dt
import shutil
from dataclasses import dataclass
from pathlib import Path

RETIRED_DIR_NAME = "_removed"


@dataclass
class Retirement:
    """What removing one folder would do."""

    source: Path
    destination: Path
    label: str
    files: int = 0
    problem: str = ""

    @property
    def ok(self) -> bool:
        return not self.problem

    def describe(self) -> str:
        if self.problem:
            return self.problem
        return (f"{self.label} would move to {self.destination}, with its "
                f"{self.files} file(s). Nothing is deleted -- you can drag it "
                "back, or delete it yourself once you are sure.")


def _count(path: Path) -> int:
    try:
        return sum(1 for entry in path.rglob("*") if entry.is_file())
    except OSError:                                       # pragma: no cover
        return 0


def plan(source: Path, sandbox: Path, label: str,
         stamp: str | None = None) -> Retirement:
    """Where this folder would go. Writes nothing.

    `stamp` is injectable so the destination is predictable in a test; the
    default is the wall clock, which is what makes two removals of the same
    name not collide.
    """
    source = Path(source)
    when = stamp or _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = Path(sandbox) / RETIRED_DIR_NAME / f"{source.name}-{when}"

    if not source.exists():
        return Retirement(source, destination, label,
                          problem=f"{label} is not there any more.")
    if not source.is_dir():
        return Retirement(source, destination, label,
                          problem=f"{label} is not a folder.")

    # A removal that lands inside the folder being removed would recurse.
    try:
        if source.resolve() in destination.resolve().parents:
            return Retirement(
                source, destination, label,
                problem=("that folder contains the place removed things go, "
                         "so moving it there would eat itself."))
    except OSError:                                       # pragma: no cover
        pass

    return Retirement(source, destination, label, files=_count(source))


def perform(the_plan: Retirement, confirmed_name: str) -> tuple[bool, str]:
    """Move it. Requires the person to have typed the name back.

    The typed name is checked here rather than in the web layer on purpose:
    the guard belongs with the thing it guards, so a second caller cannot
    forget it. Compared case-insensitively and stripped, because insisting on
    exactness in punctuation only teaches people to copy-paste past the
    warning.
    """
    if not the_plan.ok:
        return False, the_plan.problem

    typed = (confirmed_name or "").strip().casefold()
    if typed != the_plan.source.name.strip().casefold():
        return False, (f'To remove it, type its name exactly: '
                       f'{the_plan.source.name}')

    try:
        the_plan.destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(the_plan.source), str(the_plan.destination))
    except OSError as exc:
        # The likeliest cause on Windows by a wide margin, and worth naming:
        # something has the folder open.
        return False, (f"could not move it ({exc}). On Windows this is almost "
                       "always a file open in another program -- close it and "
                       "try again.")

    return True, (f"{the_plan.label} moved to {the_plan.destination}. "
                  "Nothing was deleted.")
