"""Session lifecycle — starting, checking, and safely restarting the agent.

This is the part of the package that was learned entirely by things going
wrong. Every rule below is here because ignoring it produced a real failure,
and the comments explaining why are the most valuable thing in the file.

THE SIX RULES
-------------

**1. Kill order matters.** If the agent holds a messaging connection, release
   the connection *before* terminating the process. Only one process may poll
   a given bot token; a second one is rejected. Terminate first and the new
   process starts before the old connection has been dropped, gets refused,
   and you have an agent that is running and unreachable — the worst state,
   because everything looks fine.

**2. Identify processes by which launcher started them, not by name.** Every
   agent on a machine is `python.exe` or `node`. Matching on the name will
   happily kill somebody else's. Match on the lineage: whose child is it?

**3. The newest transcript is not necessarily the live session.** A restart
   can leave a dead transcript with a *newer* timestamp than the live one.
   Filter for liveness explicitly. A decision made by reading the wrong
   transcript is worse than making no decision.

**4. Idle time outranks size.** Never interrupt work in progress to satisfy a
   threshold. A big session that is mid-task must not be recycled; a small one
   idle for an hour safely can be.

**5. Verify a restart against something that cannot be faked.** Not "is a
   process running" — that has previously been true while the *intended*
   process failed to start and a different one was found. Check that the start
   time is later than the restart instruction, and that it descends from the
   launcher you used.

**6. If verification fails, say so loudly.** Never report success on an
   unverified step. This system's ancestor once recorded a recycle as
   successful when the check had matched the wrong process.

A NOTE ON psutil
----------------
Process inspection needs `psutil`. It is an optional dependency, and when it
is absent this module says so plainly rather than falling back to something
weaker. A degraded check that reports success is precisely rule 6's failure.
"""

from __future__ import annotations

import datetime as _dt
import os
import time
from dataclasses import dataclass
from pathlib import Path

from . import atomic, paths


def marker_path() -> Path:
    """Where we record what we launched, so we can recognise it later."""
    return paths.state_dir() / "session.json"


class ProcessInspectionUnavailable(Exception):
    """Raised when we cannot inspect processes and must not pretend we can."""


def _psutil():
    try:
        import psutil
    except ImportError as exc:
        raise ProcessInspectionUnavailable(
            "Checking on the assistant's process needs the `psutil` package, "
            "which is not installed. Until it is, I cannot tell you whether "
            "a restart worked -- and I am not going to guess."
        ) from exc
    return psutil


# ---------------------------------------------------------------------------
# Recording what we started
# ---------------------------------------------------------------------------

@dataclass
class SessionMarker:
    """Proof of what we launched, written at launch time."""

    pid: int
    launcher: str            # the command we used -- rule 2's identity
    started_at: float        # epoch seconds
    label: str = ""

    def to_dict(self) -> dict:
        return {
            "pid": self.pid,
            "launcher": self.launcher,
            "started_at": self.started_at,
            "label": self.label,
        }


def record_launch(pid: int, launcher: str, label: str = "") -> SessionMarker:
    """Write down what we just started.

    Called immediately after launching. The marker is what makes rule 5
    possible later: without a record of *when we asked*, "is it running?"
    cannot be distinguished from "did our restart work?".
    """
    marker = SessionMarker(pid=pid, launcher=launcher,
                           started_at=time.time(), label=label)
    atomic.write_json(marker_path(), marker.to_dict())
    return marker


def read_marker() -> SessionMarker | None:
    data = atomic.read_json(marker_path())
    if not data:
        return None
    try:
        return SessionMarker(
            pid=int(data["pid"]),
            launcher=str(data.get("launcher", "")),
            started_at=float(data.get("started_at", 0)),
            label=str(data.get("label", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Rule 5 — verification that cannot be faked
# ---------------------------------------------------------------------------

@dataclass
class Verification:
    """The result of checking whether a restart actually worked."""

    verified: bool
    reason: str
    pid: int | None = None
    started_at: _dt.datetime | None = None

    def report(self) -> str:
        """What to tell the user. Rule 6 lives here.

        Note the phrasing of the failure case. "I could not confirm" is a
        different claim from "it failed", and both are different from the
        thing that must never be said, which is "done".
        """
        if self.verified:
            when = self.started_at.strftime("%H:%M:%S") if self.started_at \
                else "unknown time"
            return f"Confirmed: the assistant restarted at {when} (pid {self.pid})."
        return (f"NOT CONFIRMED: {self.reason}\n"
                "I am not treating this as a successful restart. Check it "
                "yourself before relying on it.")


def verify_restart(instructed_at: float,
                   expected_launcher: str = "",
                   pid: int | None = None) -> Verification:
    """Did the thing we asked for actually happen?

    Two independent checks, both of which must pass:

      * the process started AFTER we gave the instruction
      * it descends from the launcher we used

    Either alone is forgeable by coincidence. A process that was already
    running satisfies "a process exists". A process started by someone else
    satisfies "something started recently". Together they are strong enough
    to act on.
    """
    psutil = _psutil()

    marker = read_marker()
    candidate_pid = pid or (marker.pid if marker else None)
    launcher = expected_launcher or (marker.launcher if marker else "")

    if candidate_pid is None:
        return Verification(False, "there is no record of what was launched")

    try:
        process = psutil.Process(candidate_pid)
    except psutil.NoSuchProcess:
        return Verification(False, f"process {candidate_pid} is not running")
    except psutil.AccessDenied:
        return Verification(
            False,
            f"process {candidate_pid} exists but cannot be inspected on this "
            "machine")

    started = process.create_time()
    if started < instructed_at:
        # This is the exact failure mode rule 5 exists for: something is
        # running, so a naive check says "yes", but it is the OLD process --
        # our restart never happened.
        return Verification(
            False,
            f"process {candidate_pid} started before the restart was "
            "requested, so this is the previous process, not a new one",
            pid=candidate_pid,
            started_at=_dt.datetime.fromtimestamp(started),
        )

    if launcher and not _descends_from(process, launcher, psutil):
        return Verification(
            False,
            f"process {candidate_pid} started recently but did not come from "
            f"'{launcher}' -- it may belong to something else",
            pid=candidate_pid,
            started_at=_dt.datetime.fromtimestamp(started),
        )

    return Verification(True, "started after the instruction, from the "
                              "expected launcher",
                        pid=candidate_pid,
                        started_at=_dt.datetime.fromtimestamp(started))


def _descends_from(process, launcher: str, psutil) -> bool:
    """Walk up the parent chain looking for the launcher.

    RULE 2. Matching on process *name* would match every other Python or Node
    program on the machine, including another person's assistant. Lineage is
    the only identity that distinguishes "mine" from "one exactly like mine".
    """
    needle = launcher.casefold()
    current = process
    # A depth limit rather than `while True`: a corrupted parent chain must
    # not become an infinite loop inside a health check.
    for _ in range(12):
        try:
            command = " ".join(current.cmdline()).casefold()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            command = ""
        if needle in command or needle in current.name().casefold():
            return True
        try:
            parent = current.parent()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            return False
        if parent is None:
            return False
        current = parent
    return False


# ---------------------------------------------------------------------------
# Rule 4 — is it safe to restart right now?
# ---------------------------------------------------------------------------

@dataclass
class RestartAdvice:
    safe: bool
    reason: str
    idle_seconds: float = 0.0


def is_safe_to_restart(last_activity: _dt.datetime | None,
                       minimum_idle_seconds: float = 600,
                       now: _dt.datetime | None = None) -> RestartAdvice:
    """Idle time decides. Size never overrides it.

    RULE 4. It is tempting to recycle a session because it has grown large.
    Do not. A large session that is mid-task is doing exactly what it is for,
    and interrupting it to satisfy a threshold destroys work to tidy a number.

    Size may *suggest* a recycle. Only idleness may authorise one.
    """
    now = now or _dt.datetime.now()

    if last_activity is None:
        return RestartAdvice(
            False,
            "I cannot tell when it was last active, so I will not interrupt "
            "it")

    idle = (now - last_activity).total_seconds()
    if idle < minimum_idle_seconds:
        return RestartAdvice(
            False,
            f"it was active {round(idle)} seconds ago -- work may be in "
            "progress",
            idle_seconds=idle)

    return RestartAdvice(True, f"idle for {round(idle / 60)} minutes",
                         idle_seconds=idle)


# ---------------------------------------------------------------------------
# Rule 1 — the shutdown order
# ---------------------------------------------------------------------------

def shutdown_order(holds_connection: bool) -> list[str]:
    """The order of operations for a safe restart, as explicit steps.

    Returned as data rather than performed, because the actual actions depend
    on what the user has connected -- but the ORDER is not negotiable and
    belongs in one place where it can be read, taught and tested.

    RULE 1. Release the connection first. Only one process may hold a given
    messaging token; if the new process starts while the old one still holds
    it, the new one is refused and you get an assistant that is running and
    silently unreachable.
    """
    steps: list[str] = []

    if holds_connection:
        steps.append("release the messaging connection")
        steps.append("wait a few seconds for the service to notice")

    steps.append("write the working state to disk")
    steps.append("terminate the process")
    steps.append("wait for it to actually exit")
    steps.append("start the new process from the known launcher")
    steps.append("verify the new process against the restart time and lineage")
    steps.append("report ONLY what was verified")

    return steps


# ---------------------------------------------------------------------------
# Rule 3 — which transcript is live?
# ---------------------------------------------------------------------------

def pick_live_transcript(candidates: list[Path],
                         max_age_seconds: float = 900,
                         now: float | None = None) -> Path | None:
    """Choose the transcript that is actually live, not merely the newest.

    RULE 3. A recycle leaves behind a dead transcript that can be newer than
    the live one. Sorting by modification time and taking the first is the
    obvious implementation and it is wrong.

    Here "live" means modified recently enough to still be in use. If nothing
    qualifies, return None -- which the caller must treat as "I do not know",
    never as "the newest one, probably".
    """
    now = now if now is not None else time.time()

    live = [
        path for path in candidates
        if path.exists() and (now - path.stat().st_mtime) <= max_age_seconds
    ]
    if not live:
        return None

    return max(live, key=lambda path: path.stat().st_mtime)


# ---------------------------------------------------------------------------
# Rule 2 — finding our own orphans
# ---------------------------------------------------------------------------

def find_orphans(launcher: str, exclude_pid: int | None = None) -> list[int]:
    """Processes started by our launcher that are no longer wanted.

    RULE 2 again, in its most dangerous form. A sweep that matches on process
    name will kill a sibling agent belonging to a different user on a shared
    machine. Match on the launcher in the command line, and nothing else.
    """
    psutil = _psutil()

    exclude_pid = exclude_pid if exclude_pid is not None else os.getpid()
    needle = launcher.casefold()
    found: list[int] = []

    for process in psutil.process_iter(["pid", "cmdline"]):
        try:
            pid = process.info["pid"]
            if pid == exclude_pid:
                continue
            cmdline = process.info.get("cmdline") or []
            if needle in " ".join(cmdline).casefold():
                found.append(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return found
