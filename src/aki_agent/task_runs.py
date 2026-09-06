"""What happened the last time each scheduled task ran.

WHY THIS EXISTS
---------------
The honest answer to "does the user find out that a task has been failing for
a week?" was **no**. Six tasks fire unattended. `run-task.bat` runs them with
the console window hidden, so anything a task printed — including a
traceback — went to a window nobody would ever see. Nothing was written down,
so there was no later moment at which the failure could be noticed either.

A task that quietly stops working is worse than one that never existed. The
user keeps believing the thing is being done.

WHAT IS RECORDED, AND WHAT IS NOT
---------------------------------
One row per task: when it last succeeded, when it last failed, what it said,
and how many failures have run together since the last success. That is
enough for the two questions worth asking — *is this working?* and *how long
has it not been?* — and small enough that the file stays a fixed size however
long the assistant runs.

Deliberately NOT a log. `events.jsonl` is the log. This is a scoreboard with
one line per task, rewritten in place, so it can be read at a glance by
`doctor` and by the Schedule page without parsing a history.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

from . import atomic, paths


def runs_file() -> Path:
    return paths.state_dir() / "task-runs.json"


@dataclass
class Run:
    """The standing of one task."""

    key: str
    last_ok_at: str = ""
    last_failed_at: str = ""
    last_message: str = ""
    failures_in_a_row: int = 0

    @property
    def failing(self) -> bool:
        return self.failures_in_a_row > 0

    def since(self, now: _dt.datetime | None = None) -> _dt.timedelta | None:
        """How long it has been failing. None if it is not, or if unknown."""
        if not self.failing or not self.last_ok_at:
            return None
        try:
            started = _dt.datetime.fromisoformat(self.last_ok_at)
        except ValueError:
            return None
        return (now or _dt.datetime.now()) - started

    def sentence(self, now: _dt.datetime | None = None) -> str:
        """What to tell somebody, in the words they would use.

        Never "0 days" and never a bare timestamp: the question behind this is
        always "should I do something about it", and a duration answers that
        where a date does not.
        """
        if not self.last_ok_at and not self.last_failed_at:
            return "has not run yet"
        if not self.failing:
            return f"last ran cleanly at {self.last_ok_at[11:16]}"

        gone = self.since(now)
        if gone is None:
            return (f"failing — {self.failures_in_a_row} run(s) in a row, and "
                    "it has never succeeded")

        days = gone.days
        if days >= 1:
            length = f"{days} day{'s' if days != 1 else ''}"
        else:
            hours = max(1, int(gone.total_seconds() // 3600))
            length = f"{hours} hour{'s' if hours != 1 else ''}"
        return (f"failing for {length} — {self.failures_in_a_row} run(s) "
                "since it last worked")


def _read() -> dict[str, dict]:
    # For update: this is read, changed and written back on every task run.
    return atomic.read_json_for_update(runs_file(), default={}) or {}


def all_runs() -> dict[str, Run]:
    out: dict[str, Run] = {}
    for key, row in _read().items():
        if not isinstance(row, dict):
            continue
        out[str(key)] = Run(
            key=str(key),
            last_ok_at=str(row.get("last_ok_at", "")),
            last_failed_at=str(row.get("last_failed_at", "")),
            last_message=str(row.get("last_message", "")),
            failures_in_a_row=int(row.get("failures_in_a_row", 0) or 0),
        )
    return out


def for_task(key: str) -> Run:
    return all_runs().get(key, Run(key=key))


def failing() -> list[Run]:
    """Every task that did not work last time, worst first."""
    return sorted((one for one in all_runs().values() if one.failing),
                  key=lambda one: one.failures_in_a_row, reverse=True)


def record(key: str, ok: bool, message: str = "",
           now: _dt.datetime | None = None) -> Run:
    """Write down how a run went. Called once per run, whatever happened."""
    stamp = (now or _dt.datetime.now()).isoformat(timespec="seconds")

    with atomic.lock(runs_file()):
        rows = _read()
        row = rows.get(key) if isinstance(rows.get(key), dict) else {}

        if ok:
            row["last_ok_at"] = stamp
            row["failures_in_a_row"] = 0
        else:
            row["last_failed_at"] = stamp
            row["failures_in_a_row"] = int(row.get("failures_in_a_row", 0) or 0) + 1
        # Kept for both outcomes. "It works now, and here is what it said the
        # last time it did not" is more use than a message that vanishes the
        # moment the task recovers.
        row["last_message"] = (message or "").strip()[:400]

        rows[key] = row
        atomic.write_json(runs_file(), rows)

    return for_task(key)


def forget(key: str) -> None:
    """Drop a task's row, for when the task itself is deleted."""
    with atomic.lock(runs_file()):
        rows = _read()
        if key in rows:
            del rows[key]
            atomic.write_json(runs_file(), rows)
