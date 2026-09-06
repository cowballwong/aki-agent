"""Watching a long-running session, and deciding when it may be restarted.

WHY (reported 2026-08-20)
-----------------------
His students are taught to leave the machine and the session running around
the clock, so that the assistant is reachable from a phone at any hour. A
session left running does not stay healthy on its own: its context window
fills, and once it is full the assistant gets slower, more expensive and
eventually stops being able to hold the conversation at all.

`recycle.py` already knew how to restart one safely. Nothing knew *when*.

THE FOUR RULES, TAKEN FROM A SYSTEM THAT HAS RUN THIS FOR MONTHS
----------------------------------------------------------------
The maintainer sent two screenshots of his own working assistant's control room rather
than a specification, which is the better brief. Read off them:

1. **Three conditions, and all of them must be met.** The context has to be
   over the limit, the session has to have been idle a while, and the last
   recycle has to be far enough back. Any one of them alone is not a reason.

2. **Idle outranks context.** A session somebody is using is never cut, no
   matter how full it is. Size may *suggest* a recycle; only idleness may
   *authorise* one. Interrupting live work to tidy a number is destroying
   something real to fix something cosmetic.

3. **Anything shown but not decided on says so.** Session age appears on his
   screen dimmed and labelled *not a trigger*. A number on a dashboard that
   looks like a threshold and is not one will eventually be read as the reason
   something happened.

4. **The status sentence states what will and will not happen**, in those
   words: *"Auto-recycle is OFF, watching only. Nothing will recycle until you
   press the button."* Not a state name — a consequence.

ONE DELIBERATE DIFFERENCE
-------------------------
That system defaults auto-recycle to OFF. This one defaults it **ON**, and the
reason is the audience rather than a disagreement. He watches his own console
daily and can press a button; a student will not open a dashboard for weeks,
and an assistant that quietly fills up and stops working is worse for them
than one that restarts itself at three in the morning while nobody is typing.

Rule 2 is what makes that safe, and it is why rule 2 is not negotiable.

FAILING OPEN
------------
An unreadable settings file means auto is ON, not OFF. A deliberate OFF is a
written `false`; an absence is an accident, and an accident must not silently
disable the thing keeping the session alive. Same reasoning as the draft
checker's switch, and as the notification gate's unknown-channel default.
"""

from __future__ import annotations

import datetime as _dt
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import atomic, paths

# Where Claude Code keeps a session's transcript. The folder is named after
# the working directory with the separators flattened -- derived rather than
# configured, because a configured copy of a path somebody else owns goes
# stale silently.
TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects"

# The thresholds. Deliberately not a fifth of the way to the model's limit:
# the point is to recycle during a quiet spell well before anything is
# straining, not at the last possible moment.
CONTEXT_LIMIT = 180_000
IDLE_MINUTES = 12
MIN_GAP_HOURS = 3

# Shown, never decided on. See rule 3.
AGE_HOURS_NOTED = 12

# WHAT `auto_recycle: True` IS RESTING ON (noted 2026-09-05)
# ----------------------------------------------------------
# This default is the one place in the package where something destructive-
# looking happens with nobody watching, and it is ON here while the system it
# was copied from keeps it OFF (see the module note above: the audience is a
# student who will not open a dashboard for weeks, not somebody at a console).
#
# That difference is only safe because of rule 2 -- a session in use is never
# cut, however full it is. Rule 2 is not a nicety attached to this feature; it
# is the entire reason this line may read True. It is enforced in
# `should_recycle` and held down by
# `tests/test_guard.py::test_a_busy_session_is_never_cut_however_full_it_is`.
#
# So: if a later change makes idleness advisory, or lets size alone authorise
# a recycle, this default has to go back to False in the same change. Written
# here rather than only in the module note because this is the line somebody
# edits.
DEFAULTS = {
    "auto_recycle": True,
    "nightly_recycle": True,
    "recycle_hour": 4,
}

# The guard ticks on a timer, so "at 4am" has to be a window rather than an
# instant: an equality test on the hour fires several times and a test on the
# minute usually misses. The gap rule does the real de-duplication.
NIGHTLY_WINDOW_MINUTES = 25

# How far back a transcript can have been touched and still be a candidate for
# "the session running now".
#
# Generous on purpose. Narrowing it does not make the answer more accurate --
# it makes a long-idle session invisible, and a long-idle session is the exact
# thing this guard exists to find. What excludes a dead transcript is being
# older, not being untouched for a while. See `live_transcript`.
RECENT_TRANSCRIPT_HOURS = 36


def settings_file() -> Path:
    return paths.state_dir() / "recycle.json"


def settings() -> dict:
    """The three switches, defaulting to on. See "failing open" above."""
    found = dict(DEFAULTS)
    stored = atomic.read_json(settings_file(), default=None)
    if isinstance(stored, dict):
        for key, fallback in DEFAULTS.items():
            if key not in stored:
                continue
            if isinstance(fallback, bool):
                found[key] = bool(stored[key])
            else:
                try:
                    found[key] = int(stored[key])
                except (TypeError, ValueError):
                    pass
    found["recycle_hour"] = max(0, min(23, int(found["recycle_hour"])))
    return found


def save_settings(**changes) -> dict:
    current = settings()
    current.update({key: value for key, value in changes.items()
                    if key in DEFAULTS})
    current["recycle_hour"] = max(0, min(23, int(current["recycle_hour"])))
    atomic.write_json(settings_file(), current)
    return current


# ---------------------------------------------------------------------------
# Reading the live session
# ---------------------------------------------------------------------------

def session_folder() -> Path:
    """The directory the assistant's session actually starts in.

    The launcher does `cd` to the configured root before starting Claude Code
    (`launcher.py`, `workspace=loaded.layout.root`), and Claude Code names the
    transcript folder after its working directory. So the answer has to come
    from the same place the launcher reads it, not from a guess about where
    the config folder sits -- those differ, and a guard pointed at the wrong
    transcript folder reports a context of zero for ever and never says why.
    """
    try:
        from . import config as config_module

        root = config_module.load().layout.root
        if root is not None:
            return root
    except Exception:                     # noqa: BLE001 -- not configured yet
        pass
    return paths.app_dir().parent


def transcript_dir(workspace: Path | None = None) -> Path:
    """Claude Code's folder for a given working directory.

    It flattens the path into a single name -- `C:\\Users\\me\\Assistant`
    becomes `C--Users-me-Assistant`. Derived here rather than stored, because
    a stored copy of somebody else's naming convention is a thing that breaks
    without saying anything.
    """
    if workspace is None:
        workspace = session_folder()
    flattened = str(Path(workspace).resolve())
    for char in (":", "\\", "/", " ", "_", "."):
        flattened = flattened.replace(char, "-")
    return TRANSCRIPT_ROOT / flattened


def live_transcript(workspace: Path | None = None) -> Path | None:
    """The transcript that is actually in use, or None if we cannot tell.

    RULE 3, WHICH THIS FILE WAS BREAKING (fixed 2026-08-23)
    --------------------------------------------------------
    `session.py` states it: *"the newest transcript is not necessarily the
    live session. A restart can leave a dead transcript with a newer timestamp
    than the live one. A decision made by reading the wrong transcript is
    worse than making no decision."*

    `session.pick_live_transcript` was written for exactly this and had zero
    callers. What was here instead was `sorted(glob, key=mtime)[-1]` — the
    implementation that rule names as the wrong one — and it fed the automatic
    recycle that runs every twenty minutes.

    The failure it produces is the bad kind. A dead transcript left by the
    previous restart reads as a small, idle session, so the guard concludes
    the live session is fine and never restarts it; or the reverse, and it
    restarts a session somebody is working in. Neither errors.

    WHY NOT `session.pick_live_transcript` DIRECTLY
    -----------------------------------------------
    Because its notion of live is "modified in the last fifteen minutes",
    which is right for the question it was written for and wrong for this one.
    This guard exists to notice a session that has been **idle for a long
    time**. Filtering to recently-touched files means a session idle for forty
    minutes has no live transcript, `idle_minutes` answers 0.0, and 0.0 reads
    as "somebody is typing" — so the guard would refuse to recycle precisely
    the sessions it was built to recycle. Rule 3 traded for Rule 4.

    What actually distinguishes the dead transcript from the live one is not
    recency of modification, it is which session is the current one: a restart
    creates a NEW file, and the old one may then receive a final line and end
    up with a newer mtime. So among the files that are plausibly this
    machine's recent work, the live one is the most recently **created**.

    That is the exact failure Rule 3 describes, addressed by the property that
    separates the two rather than by the one that happens to correlate.
    """
    folder = transcript_dir(workspace)
    try:
        candidates = [one for one in folder.glob("*.jsonl") if one.is_file()]
    except OSError:
        return None
    if not candidates:
        return None

    cutoff = time.time() - RECENT_TRANSCRIPT_HOURS * 3600
    recent = []
    for path in candidates:
        try:
            stat = path.stat()
        except OSError:                                   # pragma: no cover
            continue
        if stat.st_mtime >= cutoff:
            recent.append((stat.st_ctime, stat.st_mtime, path))

    if not recent:
        return None
    # Newest created; mtime breaks a tie, which happens when two files are
    # created inside the same filesystem timestamp granularity.
    return max(recent)[2]


def newest_transcript(workspace: Path | None = None) -> Path | None:
    """Kept for callers that genuinely want the newest file on disk.

    Not for deciding anything about the live session — use `live_transcript`.
    The distinction is Rule 3 and it is the whole reason both exist.
    """
    folder = transcript_dir(workspace)
    try:
        files = sorted(folder.glob("*.jsonl"),
                       key=lambda one: one.stat().st_mtime)
    except OSError:
        return None
    return files[-1] if files else None


def _context_from_lines(lines: list[str]) -> int:
    """The size of the window, from the most recent usage block.

    Walks backwards: the last `usage` recorded is the current size. The three
    fields are summed because the window is what the model is *given*, and a
    cached read occupies it exactly as much as a fresh one -- reading only
    `input_tokens` reports a fraction of the truth and reports it confidently.
    """
    for line in reversed(lines):
        if '"usage"' not in line:
            continue
        try:
            usage = (json.loads(line).get("message") or {}).get("usage")
        except (json.JSONDecodeError, AttributeError):
            continue                      # a half-written line at the tail
        if usage:
            return (usage.get("input_tokens", 0)
                    + usage.get("cache_read_input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0))
    return 0


def context_size(workspace: Path | None = None) -> int:
    """How full the live session's window is, or 0 if it cannot be read."""
    transcript = live_transcript(workspace)
    if transcript is None:
        return 0
    try:
        lines = transcript.read_text(
            encoding="utf-8", errors="replace").splitlines()[-500:]
    except OSError:
        return 0
    return _context_from_lines(lines)


def idle_minutes(workspace: Path | None = None) -> float:
    """How long since the session last wrote anything."""
    transcript = live_transcript(workspace)
    if transcript is None:
        return 0.0
    try:
        return (time.time() - transcript.stat().st_mtime) / 60
    except OSError:                                       # pragma: no cover
        return 0.0


def engine_installed_at() -> float:
    """When the engine now on disk was put there, as a timestamp.

    Uses the marker the copy writes, falling back to the folder's own time.
    """
    from . import engine

    for candidate in (engine.engine_dir() / engine.MANIFEST_FILE,
                      engine.engine_dir()):
        try:
            return candidate.stat().st_mtime
        except OSError:
            continue
    return 0.0


def session_started_at(workspace: Path | None = None) -> float:
    """When the live session began, from its transcript's creation time."""
    transcript = live_transcript(workspace)
    if transcript is None:
        return 0.0
    try:
        return transcript.stat().st_ctime
    except OSError:                                       # pragma: no cover
        return 0.0


def session_predates_engine(workspace: Path | None = None) -> bool:
    """Is the running session older than the code it is meant to be running?

    WHY THIS IS A SEPARATE QUESTION FROM "IS IT TOO BIG" (reported 2026-08-20)
    ------------------------------------------------------------------------
    He upgraded roughly ten times in one day and none of it changed how his
    assistant behaved. His session had been running since the 17th: every
    brief, skill and hook shipped that day was on disk and none of it had
    been loaded. Claude Code reads those once, at start-up.

    Nothing noticed. The guard watches the *size* of a session, and by that
    measure a three-day-old session sitting at 52,930 tokens is in perfect
    health -- which it was, and which was beside the point. Session age is
    deliberately not a trigger here (interrupting live work to satisfy a
    number is the thing rule 2 forbids), so age alone would never have raised
    it either.

    "Older than the engine" is a different fact from both, and unlike them it
    has an unambiguous consequence: **the assistant is running yesterday's
    behaviour and will keep doing so until it is restarted.** That is worth
    saying out loud, once, wherever somebody is looking.
    """
    started = session_started_at(workspace)
    installed = engine_installed_at()
    if not started or not installed:
        return False
    return started < installed


def last_recycle_file() -> Path:
    return paths.state_dir() / "last-recycle.json"


def hours_since_recycle() -> float:
    stored = atomic.read_json(last_recycle_file(), default=None)
    if not isinstance(stored, dict) or "at" not in stored:
        return 1e6                        # never recycled: no reason to wait
    try:
        when = _dt.datetime.fromisoformat(str(stored["at"]))
    except ValueError:                                    # pragma: no cover
        return 1e6
    return (_dt.datetime.now() - when).total_seconds() / 3600


def record_recycle(now: _dt.datetime | None = None) -> Path:
    return atomic.write_json(last_recycle_file(), {
        "at": (now or _dt.datetime.now()).isoformat(timespec="seconds")})


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------

@dataclass
class Condition:
    name: str
    detail: str
    value: float
    threshold: float
    met: bool
    decides: bool = True
    # What to print instead of the number, when the number is a sentinel
    # rather than a measurement. "9,999.0 / 3" on a dashboard reads as a bug;
    # "never restarted" reads as the fact it stands for.
    instead: str = ""

    def reading(self) -> str:
        if self.instead:
            return self.instead
        if self.threshold >= 1000:
            return f"{self.value:,.0f} / {self.threshold:,.0f}"
        return f"{self.value:,.1f} / {self.threshold:,.0f}"

    def line(self) -> str:
        mark = "[x]" if self.met else "[ ]"
        if not self.decides:
            mark = " . "
        return f"{mark} {self.name} ({self.detail}) {self.reading()}"


@dataclass
class Assessment:
    conditions: list[Condition] = field(default_factory=list)
    auto: bool = True
    nightly_due: bool = False

    @property
    def deciding(self) -> list[Condition]:
        return [one for one in self.conditions if one.decides]

    @property
    def all_met(self) -> bool:
        return all(one.met for one in self.deciding)

    @property
    def would_recycle(self) -> bool:
        """What will actually happen on this tick, switches included.

        THE TWO ROUTES ARE NOT THE SAME QUESTION (fixed 2026-08-23)
        ------------------------------------------------------------
        This read `all_met and (auto or nightly_due)`, so the nightly restart
        needed the same three conditions as the automatic one: context over
        the limit, idle long enough, and a long enough gap. Which meant
        "Nightly at 04:00" could never restart a session that was merely
        stale — a session at 40,000 tokens that had been open for three days
        met none of them, and that is exactly the session a nightly restart
        exists for.

        The label promised a time and delivered a condition. So:

        * **auto** is a health check. It fires when the session is genuinely
          in trouble, whenever that is, and keeps all three conditions.
        * **nightly** is a rhythm. It fires in tonight's window because it is
          tonight, and keeps only the conditions about safety — is anybody
          mid-sentence, and did we already restart recently. `nightly_due`
          already carries the gap check.

        Being idle stays required on both. Restarting a session somebody is
        typing into is not a rhythm, it is an interruption.
        """
        if self.auto and self.all_met:
            return True

        if self.nightly_due:
            idle = next((one for one in self.conditions
                         if one.name == "Idle"), None)
            return idle is None or idle.met

        return False

    def sentence(self) -> str:
        """What will and will not happen, in those words. See rule 4."""
        context = next((one for one in self.conditions
                        if one.name == "Context"), None)
        size = f"Context {context.value:,.0f}. " if context else ""

        if not self.auto and not self.nightly_due:
            return (f"Auto-recycle is OFF, watching only. {size}"
                    "Nothing will restart on its own -- only the button.")

        # Said in the order it is decided, so the sentence and the behaviour
        # cannot drift. The nightly route has its own answer because it has
        # its own conditions -- see `would_recycle`.
        if self.nightly_due and self.would_recycle:
            return (f"{size}It is tonight's restart window and nobody is "
                    "mid-sentence; the session will be restarted on the next "
                    "check.")
        if self.nightly_due:
            return (f"{size}It is tonight's restart window, but the session "
                    "is still being used. Waiting for it to go idle.")

        if self.all_met:
            return (f"{size}All three conditions are met; the session will be "
                    "restarted on the next check.")

        waiting = [one.name.lower() for one in self.deciding if not one.met]
        return (f"Auto-recycle is on. {size}Waiting on: "
                + ", ".join(waiting) + ".")


def nightly_due(config: dict, gap_hours: float,
                now: _dt.datetime | None = None) -> bool:
    """Is this tick inside tonight's window?"""
    if not config.get("nightly_recycle"):
        return False
    now = now or _dt.datetime.now()
    start = now.replace(hour=int(config["recycle_hour"]), minute=0,
                        second=0, microsecond=0)
    minutes = (now - start).total_seconds() / 60
    return 0 <= minutes < NIGHTLY_WINDOW_MINUTES and gap_hours >= MIN_GAP_HOURS


def assess(workspace: Path | None = None,
           now: _dt.datetime | None = None) -> Assessment:
    """Everything the guard knows, in the order it is shown."""
    config = settings()
    size = context_size(workspace)
    idle = idle_minutes(workspace)
    gap = hours_since_recycle()

    transcript = live_transcript(workspace)
    age_hours = 0.0
    if transcript is not None:
        try:
            age_hours = (time.time() - transcript.stat().st_ctime) / 3600
        except OSError:                                   # pragma: no cover
            age_hours = 0.0

    return Assessment(
        conditions=[
            Condition("Context", f"over {CONTEXT_LIMIT:,}", size,
                      CONTEXT_LIMIT, size >= CONTEXT_LIMIT),
            Condition("Idle", f"needs {IDLE_MINUTES} min+", idle,
                      IDLE_MINUTES, idle >= IDLE_MINUTES),
            Condition("Since last restart", f"needs {MIN_GAP_HOURS} h+",
                      min(gap, 9999), MIN_GAP_HOURS, gap >= MIN_GAP_HOURS,
                      instead="never restarted" if gap > 9000 else ""),
            # Shown, never decided on. Rule 3.
            Condition("Session age", f"{AGE_HOURS_NOTED} h - not a trigger",
                      age_hours, AGE_HOURS_NOTED, age_hours >= AGE_HOURS_NOTED,
                      decides=False),
        ],
        auto=bool(config["auto_recycle"]),
        nightly_due=nightly_due(config, gap, now=now),
    )


FOOTER = ("All three deciding conditions must be met. Idle outranks context "
          "-- a session in use is never cut. The dimmed row is for awareness "
          "and is not part of the decision.")
