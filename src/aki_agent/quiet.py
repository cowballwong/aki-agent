"""Quiet time: named windows, and which task obeys which.

WHY MODES AND NOT ONE PAIR OF TIMES
-----------------------------------
There used to be a single quiet window that applied to everything. That is
one answer to a question people ask several times: a morning summary and a
folder-watcher do not deserve the same silence, and a weekend is not a
weekday.

reported 2026-08-21:



So a mode is a window plus the days it applies on, it has a name, and each
scheduled task points at one. Nothing new is invented for the old behaviour:
the single quiet window survives as the shipped `daily` mode, so an existing
install keeps the silence it already had.

WHAT QUIET DOES AND DOES NOT DO
-------------------------------
It stops the message, never the work. A task inside its quiet window still
runs, still writes to the day's log, and its output is held and delivered
afterwards -- see `notify.py`, which is the module that enforces this and
where the rule is written down at length. Nothing here drops anything.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

from . import paths

WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

# What "no mode at all" means. Not silence -- a task nobody has decided about
# should reach you, because the alternative is a message that never arrives
# and never explains why.
ALWAYS = "always"


@dataclass
class Mode:
    """One named quiet window.

    `days` lists the days it applies on, and nothing else -- an empty list
    applies on no day. `start` after `end` wraps midnight, which is the
    common case and the reason the comparison below is written the way it
    is.
    """

    key: str
    name: str
    start: str = "22:00"
    end: str = "07:00"
    days: tuple[str, ...] = ()
    built_in: bool = False

    def when(self) -> str:
        """This mode in words, for the page and for `doctor`."""
        if not self.days:
            return "never — no day is ticked"
        days = ("every day" if len(self.days) == len(WEEKDAYS)
                else ", ".join(self.days))
        if not self.start or not self.end:
            return f"never quiet, {days}"
        return f"{self.start} to {self.end}, {days}"

    def problems(self) -> list[str]:
        found: list[str] = []
        if not self.name.strip():
            found.append("A mode needs a name.")
        for label, value in (("start", self.start), ("end", self.end)):
            if value and _minutes(value) is None:
                found.append(f"{value!r} is not a time of day ({label}).")
        unknown = [day for day in self.days if day not in WEEKDAYS]
        if unknown:
            found.append(f"{', '.join(unknown)} is not a day of the week.")
        if not self.days:
            found.append(
                "No day is ticked, so this mode never applies. Tick the days "
                "you want it on.")
        return found

    def holds(self, at: _dt.datetime) -> bool:
        """Would a message be held if it arrived now?"""
        if not self.start or not self.end:
            return False

        start = _minutes(self.start)
        end = _minutes(self.end)
        if start is None or end is None:
            return False

        now = at.hour * 60 + at.minute
        today = WEEKDAYS[at.weekday()]

        if start == end:
            # A zero-length window would silently mean "never quiet", which
            # is not what somebody typing the same time twice is asking for.
            # All day is the honest reading.
            return today in self.days

        if start < end:                       # 09:00 -> 17:00, same day
            inside = start <= now < end
            day = today
        else:                                 # 22:00 -> 07:00, over midnight
            inside = now >= start or now < end
            # Before the end time, the window belongs to the day it began on
            # -- 01:00 on Saturday is Friday's night.
            day = today if now >= start else WEEKDAYS[(at.weekday() - 1) % 7]

        if not inside:
            return False
        return day in self.days

    def to_dict(self) -> dict:
        return {"key": self.key, "name": self.name, "start": self.start,
                "end": self.end, "days": list(self.days)}

    @classmethod
    def from_dict(cls, data: dict) -> "Mode":
        # ABSENT and EMPTY are different answers (2026-08-23).
        #
        # This read `data.get("days") or () or WEEKDAYS`, so a stored empty
        # list came back as all seven days. Which meant unticking every day
        # and saving produced a mode that applied *always* — and on the
        # shipped Weekend mode, whose window is 00:00–00:00 and therefore
        # all-day, that turned it into permanent silence.
        #
        # Worse, the form said so and was ignored: `problems()` returns "No
        # day is ticked, so this mode never applies", the page showed that
        # sentence, and then the card re-rendered with all seven ticked. A
        # switch that confirms and does the opposite is the exact shape the maintainer
        # has been caught by before.
        #
        # A file written before days existed has no "days" key at all, and
        # for those "every day" is the right reading. A file that carries the
        # key and an empty list was saved that way on purpose.
        stored = data.get("days")
        days = WEEKDAYS if stored is None else tuple(stored)
        return cls(
            key=str(data.get("key", "")),
            name=str(data.get("name", "")),
            start=str(data.get("start", "")),
            end=str(data.get("end", "")),
            days=days,
        )


def _minutes(value: str) -> int | None:
    """"22:30" -> 1350. None for anything that is not a time."""
    try:
        hour, _, minute = str(value).partition(":")
        hour, minute = int(hour), int(minute)
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


# ---------------------------------------------------------------------------
# The two that ship
# ---------------------------------------------------------------------------
# Two, not five. A person can hold two in their head and will recognise both
# without reading anything; the rest they name themselves, which is the point
# of the custom ones.
DEFAULT_MODES: tuple[Mode, ...] = (
    Mode(key="daily", name="Daily", start="22:00", end="07:00",
         days=WEEKDAYS, built_in=True),
    Mode(key="weekend", name="Weekend", start="00:00", end="00:00",
         days=("SAT", "SUN"), built_in=True),
)


def modes_file() -> Path:
    return paths.state_dir() / "quiet-modes.json"


def assignments_file() -> Path:
    return paths.state_dir() / "quiet-assignments.json"


def read_modes() -> list[Mode]:
    """The two shipped modes, then the user's own.

    An entry in the file whose key matches a shipped mode is an *override* of
    its window and days -- not a replacement of the mode. The name stays as
    shipped, because tasks point at the key and a person points at the word:
    renaming "Daily" would leave every assignment reading as something it is
    not.
    """
    from . import atomic

    stored = atomic.read_json(modes_file(), default=[]) or []
    shipped = {one.key: one for one in DEFAULT_MODES}
    overrides: dict[str, Mode] = {}
    mine: list[Mode] = []

    for entry in stored:
        try:
            one = Mode.from_dict(entry)
        except (TypeError, ValueError):
            continue          # one bad entry must not lose the rest
        if not one.key:
            continue
        if one.key in shipped:
            overrides[one.key] = one
        else:
            mine.append(one)

    out: list[Mode] = []
    for one in DEFAULT_MODES:
        changed = overrides.get(one.key)
        if changed is None:
            out.append(one)
        else:
            out.append(Mode(key=one.key, name=one.name,
                            start=changed.start, end=changed.end,
                            days=changed.days, built_in=True))
    return out + mine


def save_built_in(mode: Mode) -> tuple[Mode, list[str]]:
    """Change a shipped mode's window and days, keeping its name.

    Stored as an override rather than by editing `DEFAULT_MODES`, which is a
    constant in this file: a package update would otherwise silently put
    somebody's quiet hours back to 22:00.
    """
    from . import atomic

    if mode.key not in {one.key for one in DEFAULT_MODES}:
        return save_mode(mode)

    problems = mode.problems()
    stored = atomic.read_json(modes_file(), default=[]) or []
    kept = [entry for entry in stored
            if str(entry.get("key", "")) != mode.key]
    kept.append(mode.to_dict())
    atomic.write_json(modes_file(), kept)
    return mode, problems


def get_mode(key: str) -> Mode | None:
    for one in read_modes():
        if one.key == key:
            return one
    return None


def save_mode(mode: Mode) -> tuple[Mode, list[str]]:
    """Add or replace one of the user's modes.

    Saved even with problems, and the problems reported -- a half-finished
    mode somebody can come back to beats one that disappears on submit.
    """
    import re

    from . import atomic

    if not mode.key:
        slug = re.sub(r"[^a-z0-9]+", "-", mode.name.lower()).strip("-")
        mode.key = (slug or "mode")[:40]

    # A user mode must never take a shipped mode's key, or `get_mode` would
    # answer with the shipped one and the user's edits would vanish into a
    # file nothing reads.
    reserved = {one.key for one in DEFAULT_MODES}
    if mode.key in reserved:
        mode.key = f"{mode.key}-mine"

    # Read the file, not `read_modes()`: the file also holds the overrides
    # for the shipped modes, and rewriting it from the merged list would drop
    # them the first time somebody added a mode of their own.
    stored = atomic.read_json(modes_file(), default=[]) or []
    kept = [entry for entry in stored
            if str(entry.get("key", "")) != mode.key]
    kept.append(mode.to_dict())
    atomic.write_json(modes_file(), kept)
    return mode, mode.problems()


def delete_mode(key: str) -> bool:
    """Remove one of the user's modes, and unassign every task using it."""
    from . import atomic

    if key in {one.key for one in DEFAULT_MODES}:
        return False          # a shipped mode is not the user's to delete

    stored = atomic.read_json(modes_file(), default=[]) or []
    remaining = [entry for entry in stored
                 if str(entry.get("key", "")) != key]
    if len(remaining) == len(stored):
        return False

    atomic.write_json(modes_file(), remaining)

    # Otherwise a task keeps pointing at a mode that no longer exists, and
    # `holds_for` quietly falls back to ALWAYS -- a task that was silent
    # yesterday starts talking, and nothing on screen says why.
    kept = {task: mode for task, mode in read_assignments().items()
            if mode != key}
    atomic.write_json(assignments_file(), kept)
    return True


# ---------------------------------------------------------------------------
# Which task obeys which
# ---------------------------------------------------------------------------
def read_assignments() -> dict[str, str]:
    """`{task key: mode key}`. A task absent from this is `ALWAYS`.

    A separate file from the modes, and from the tasks, for the same reason
    `task-announce.json` is separate: the shipped tasks are constants in
    `schedule.py`, so anything the user decides about them has to live
    somewhere the package does not overwrite.
    """
    from . import atomic

    stored = atomic.read_json(assignments_file(), default={}) or {}
    if not isinstance(stored, dict):
        return {}
    return {str(k): str(v) for k, v in stored.items()}


def assign(task_key: str, mode_key: str) -> None:
    """Record which quiet mode a task answers to.

    ALWAYS IS STORED, NOT ERASED (2026-08-23)
    ------------------------------------------
    This used to `pop` the entry when the answer was ALWAYS, on the reasoning
    that it is the default and a default need not be written down. That made
    two different intentions identical on disk:

    * nobody has decided about this task
    * somebody chose "always tell me", on purpose

    `notify._mode_for` states that the second one means "never held, not even
    by the global quiet window" — an intention the store could not express, so
    the sentence was true of nothing.

    It matters now because the two answers have different consequences: an
    unassigned task falls through to the global quiet hours, which is what
    makes that setting work at all (it was inert until this was separated).
    Erasing the entry would silently turn a deliberate "always" into
    "whatever the global window says".

    An empty `mode_key` still clears the entry. That is the third answer —
    "I take it back" — and it is distinct from both of the others.
    """
    from . import atomic

    current = read_assignments()
    if mode_key:
        current[task_key] = mode_key
    else:
        current.pop(task_key, None)
    atomic.write_json(assignments_file(), current)


def mode_for(task_key: str) -> str:
    """Which mode a task answers to, defaulting to "always tell me".

    Callers that need to know whether anybody has *decided* must ask
    `read_assignments()` for membership instead — see `notify._mode_for`.
    """
    return read_assignments().get(task_key, ALWAYS)


def holds_for(task_key: str, at: _dt.datetime | None = None) -> bool:
    """Should this task's message be held right now?"""
    key = mode_for(task_key)
    if key == ALWAYS:
        return False
    mode = get_mode(key)
    if mode is None:
        # The mode was deleted from under it. Say what you do not know by
        # letting the message through -- silence you cannot explain is worse
        # than a message you did not need.
        return False
    return mode.holds(at or _dt.datetime.now())
