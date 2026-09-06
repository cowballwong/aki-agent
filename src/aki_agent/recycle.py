"""Actually performing a recycle — the part that was missing.

WHY THIS FILE EXISTS
--------------------
`session.py` holds the rules: when it is safe to restart, what order to do it
in, and how to verify it afterwards against something that cannot be faked.
Every one of those rules was learned by something breaking.

And nothing called any of them.

That is the same failure this package quotes at itself — *a tool is not
automation* — and it is the third time it appeared while building this
package. The rules existed, were correct, were tested, and had no effect on
anything, because no code path ever reached them.

So this is the part that reaches them. It is deliberately small: all the
judgement lives in `session.py`, and this file only sequences it.

WHAT A RECYCLE IS FOR
---------------------
A long-running assistant accumulates context until it is spending most of its
budget re-reading its own history. Restarting it clears that, and the handoff
file is what stops the restart losing the thread.

The order matters, and it is not negotiable:

    write the state  ->  release the connection  ->  stop  ->  start  ->  VERIFY

Verification last, and never skipped. This system's ancestor once recorded a
recycle as successful when its check had matched the wrong process.
"""

from __future__ import annotations

import datetime as _dt
import time
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

from . import memory, paths, session


@dataclass
class RecycleReport:
    """What happened, step by step, including the steps that did not run."""

    attempted: bool = False
    completed: bool = False
    reason: str = ""
    stopped: int = 0
    identified_the_old_session: bool = False
    forced: bool = False
    channel_confirmed: bool | None = None
    steps: list[str] = dataclass_field(default_factory=list)
    verification: session.Verification | None = None

    def summary(self) -> str:
        """What to tell the user. The failure wording is the important half."""
        if not self.attempted:
            return f"Not restarted: {self.reason}"
        if self.completed and not self.stopped:
            # Observed 2026-09-03: this said "Restarted and confirmed" while
            # the previous session was untouched. Verification only ever
            # checked that a NEW process exists -- never that the old one is
            # gone -- so the sentence was true about the half it measured and
            # wrong about the half that matters.
            return ("Started a new session and confirmed it is running. "
                    "Nothing was stopped: no previous session could be "
                    "found. If one is still open it is still running, and "
                    "you now have two. " + self.reason)
        if self.completed:
            forced = "Forced. " if self.forced else ""
            return (f"{forced}Restarted and confirmed. "
                    f"Stopped {self.stopped}. {self.reason}")
        return (f"RESTART NOT CONFIRMED — {self.reason}\n"
                "I am not recording this as a successful restart. "
                "Check it before relying on it.")


def should_recycle(idle_seconds_required: float = 900,
                   now: _dt.datetime | None = None) -> session.RestartAdvice:
    """Ask, before doing anything: is this even a good idea right now?

    Idle time decides. Size may suggest a recycle; only idleness may authorise
    one. Interrupting work in progress to satisfy a threshold destroys real
    work to tidy a number.
    """
    state = memory.read_working_state()
    last_activity = state.generated_at if state else None
    return session.is_safe_to_restart(last_activity,
                                      minimum_idle_seconds=idle_seconds_required,
                                      now=now)


def perform(launcher_command: list[str], *,
            holds_connection: bool,
            confirmed: bool,
            idle_seconds_required: float = 900,
            settle_seconds: float = 5.0,
            force: bool = False,
            note: str = "") -> RecycleReport:
    """Do the recycle, in the one correct order, and verify it.

    `confirmed` is required: restarting somebody's assistant while they are
    using it is not something to do on a hunch.
    """
    report = RecycleReport()

    if not confirmed:
        report.reason = "nobody confirmed it"
        return report

    advice = should_recycle(idle_seconds_required)
    if not advice.safe and not force:
        report.reason = advice.reason
        return report

    report.attempted = True
    report.forced = force and not advice.safe
    if report.forced:
        # Said out loud in the report, because "I restarted it anyway" is
        # exactly the sentence somebody needs to see afterwards when the
        # session turns out to have been in the middle of something.
        report.steps.append(f"forced past the idle check ({advice.reason})")

    # Stamped before the restart rather than after it. A recycle that gets
    # part-way and does not come back must still count as "one just happened"
    # -- otherwise the guard sees no recent recycle, the conditions are still
    # met, and it tries again immediately, on a machine that has just shown it
    # cannot complete one.
    from . import guard

    guard.record_recycle()

    # Read before anything is started: it names the launcher the session that
    # is running now was started with, and starting a replacement overwrites
    # it.
    marker = session.read_marker()

    # --- 1. write the state, before anything can be lost -------------------
    state = memory.read_working_state() or memory.WorkingState(
        generated_at=_dt.datetime.now())
    if note:
        memory.append_human_note(note)
    memory.write_working_state(state)
    report.steps.append("wrote the working state")

    # And kept, under its own name. The line above overwrites the one live
    # handoff file, which is right -- a starting session needs the current
    # one at a known path. It also means that without this the account of
    # every previous handoff was destroyed by the next one.
    #
    # Read back rather than archiving `state`: `append_human_note` above
    # writes straight to the file, so the object in hand does not carry the
    # note, and the note is the half worth keeping.
    try:
        memory.record_handoff(
            memory.read_working_state() or state,
            kind=memory.HANDOFF_SYSTEM,
            why="session recycled")
        report.steps.append("kept it in the handoff log")
    except OSError as exc:                                # noqa: BLE001
        # Never fatal. The archive is a record of the recycle; failing to
        # write it must not stop the recycle it is a record of.
        report.steps.append(f"could not keep the handoff ({exc})")

    # --- 2. start the replacement FIRST -----------------------------------
    #
    # Changed on the owner's instruction, 2026-09-03: "Recycle 要開新
    # session, 通咗 telegram 再 kill 舊 session". Starting first means there
    # is never a moment with no assistant, and a replacement that fails to
    # start leaves the working one untouched instead of leaving nothing.
    held_before = _channel_holder() if holds_connection else None

    instructed_at = time.time()
    new_pid = _start(launcher_command)
    if new_pid is None:
        report.reason = ("the new session would not start -- the old one has "
                         "been left running")
        report.steps.append("FAILED to start the replacement; stopped nothing")
        return report

    session.record_launch(new_pid, launcher=" ".join(launcher_command),
                          label="recycle")
    report.steps.append(f"started a replacement (pid {new_pid})")

    # Give it a moment to exist properly before asking about it.
    time.sleep(settle_seconds)

    # --- 3. wait for it to be reachable -----------------------------------
    if holds_connection:
        connected, why = _wait_for_channel(held_before)
        report.channel_confirmed = connected
        report.steps.append(why)
        if not connected:
            # Stop the old one anyway. Two live sessions is the fault that
            # started all of this, and leaving both running to avoid an
            # unconfirmed connection trades a known bad state for a worse
            # one. It is said out loud instead.
            report.steps.append(
                "stopping the old session regardless, rather than leaving two")

    # --- 4. stop the old one, identified by ITS LAUNCHER ------------------
    #
    # Never by process name. Every agent on a machine is `python` or `node`,
    # and a sweep matching on name will kill somebody else's.
    #
    # The marker is written by a previous recycle -- and by nothing else. A
    # session the owner started by double-clicking the launcher has no marker,
    # so this used to find nobody to stop, start a second session, and report
    # success. Fall back to the launcher we were asked to run: that is the
    # same string the old session's command line carries, which is exactly
    # what `find_orphans` matches on.
    #
    # `plan` is read here because the order it describes is the order this
    # follows: the connection is handed over before the process goes.
    plan = session.shutdown_order(holds_connection)
    if plan:
        report.steps.append(f"shutdown order: {len(plan)} step(s)")

    launcher_to_match = (marker.launcher if marker and marker.launcher
                         else (launcher_command[0] if launcher_command else ""))

    stopped: list[int] = []
    if launcher_to_match:
        # Before the first kill, not after: the launcher reaches its own tail
        # about a second later, and the note has to be there when it looks.
        say_this_was_deliberate()
        try:
            for pid in session.find_orphans(launcher_to_match,
                                            exclude_pid=new_pid):
                if pid == new_pid:
                    continue
                stopped.extend(_terminate(pid))
        except session.ProcessInspectionUnavailable as exc:
            report.reason = str(exc)
            return report
        report.identified_the_old_session = True

    report.stopped = len(stopped)
    report.steps.append(f"stopped {len(stopped)} process(es)")

    # --- 5. verify against something that cannot be faked ------------------
    try:
        verification = session.verify_restart(
            instructed_at,
            expected_launcher=launcher_command[0] if launcher_command else "",
            pid=new_pid)
    except session.ProcessInspectionUnavailable as exc:
        report.reason = str(exc)
        report.steps.append("could NOT verify")
        return report

    report.verification = verification
    report.completed = verification.verified
    report.reason = verification.reason
    report.steps.append("verified" if verification.verified
                        else "verification FAILED")

    memory.log_event(f"recycle: {report.summary().splitlines()[0]}")
    return report


def _channel_holder() -> int | None:
    """Which process is currently holding the messaging connection.

    Read from the plugin's own bot.pid rather than from anything this package
    writes, because the question is whether THE BRIDGE is up -- and only the
    bridge knows that.
    """
    try:
        from . import telegram_setup

        raw = (telegram_setup.channel_dir() / "bot.pid").read_text(
            encoding="utf-8").strip()
        return int(raw)
    except Exception:                                    # noqa: BLE001
        return None


def _wait_for_channel(previous_holder: int | None,
                      timeout_seconds: float = 45.0) -> tuple[bool, str]:
    """Wait until the NEW session is the one holding the connection.

    "A different live pid than the one that held it before" is the only
    evidence available here that is not a guess. A file that merely exists
    proves nothing -- it is written by whoever last started, including the
    process we are about to stop.
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        holder = _channel_holder()
        if holder is not None and holder != previous_holder:
            try:
                if session._psutil().pid_exists(holder):
                    return True, f"the messaging connection came up (pid {holder})"
            except Exception:                            # noqa: BLE001
                return True, f"the messaging connection came up (pid {holder})"
        time.sleep(1.0)

    return False, ("the new session did not take over the messaging "
                   f"connection within {timeout_seconds:g}s")


def _is_the_dashboard(process) -> bool:
    """Is this the dashboard rather than the session?

    The launcher starts both, so both are children -- but only one of them is
    a page somebody may be looking at right now, listening on a fixed port
    that the replacement will need and cannot wait for.
    """
    try:
        command = " ".join(process.cmdline() or []).casefold()
    except Exception:                                    # noqa: BLE001
        return False
    return "dashboard" in command


def deliberate_stop_file() -> Path:
    """The note that tells a dying launcher it was replaced, not broken."""
    return paths.state_dir() / "being-recycled"


def say_this_was_deliberate() -> None:
    """Leave that note, so the launcher exits quietly instead of explaining.

    WHY (reported 2026-09-04)
    -----------------------
     -- and he
    was watching two of this package's own timers fight each other:

      * the launcher, on ANY non-zero exit, prints what went wrong and waits
        thirty seconds so somebody has time to read it;
      * `_terminate`, having killed the session, gives the launcher eight
        seconds to finish by itself and then kills it.

    A recycled session always exits non-zero -- it was stopped on purpose --
    so the launcher always took the failure path, was always still sitting in
    that thirty-second pause at the eight-second mark, and was always killed.
    A killed process is exactly what makes Windows Terminal keep the pane, so
    every recycle left a corpse: `[process exited with code 15]`.

    The fix is not a longer wait on either side. It is that a recycle is not a
    failure and should never have been explained as one.

    A stale note can only outlive one recycle -- the launcher deletes it on
    the way past -- and the worst it could do is let one genuine crash exit
    quietly. That is a smaller harm than a window per restart, which is what
    it replaces.
    """
    try:
        paths.ensure_app_dirs()
        deliberate_stop_file().write_text("stopped on purpose\n",
                                          encoding="utf-8")
    except Exception:                                    # noqa: BLE001
        pass  # A tidy window is never worth failing a restart for.


def forget_the_deliberate_stop() -> None:
    """Take the note back when the stop did not happen after all."""
    try:
        deliberate_stop_file().unlink()
    except Exception:                                    # noqa: BLE001
        pass


def _terminate(pid: int) -> list[int]:
    """Stop the process and everything it started. Returns what was stopped.

    The launcher is a wrapper. `cmd /c start-assistant.bat` is what carries
    the launcher path in its command line, so it is what identifies the old
    session -- but the session is claude.exe, its child, and killing the
    wrapper alone leaves that child running with no parent and no window.
    The owner met the result on 2026-09-03 and called it a hidden session.
    """
    import os
    import signal

    try:
        psutil = session._psutil()
    except Exception:                                    # noqa: BLE001
        psutil = None

    if psutil is None:
        try:
            os.kill(pid, signal.SIGTERM)
            return [pid]
        except (OSError, ProcessLookupError):
            return []

    try:
        parent = psutil.Process(pid)
    except Exception:                                    # noqa: BLE001
        return []

    children = []
    try:
        children = list(parent.children(recursive=True))
    except Exception:                                    # noqa: BLE001
        children = []
    children = [member for member in children if not _is_the_dashboard(member)]

    # The children go first, and the launcher is then LEFT ALONE for a moment
    # to finish by itself.
    #
    # Why the order matters: a terminal closes a pane when its process exits
    # cleanly and keeps the dead pane on screen when the process is killed
    # (measured on the owner's machine 2026-09-04 -- a killed `cmd` left its
    # Windows Terminal pane open, an identical one allowed to finish closed
    # it). Killing the wrapper alongside its children is what left the corpse
    # window the owner reported: the session really had been replaced, but the
    # old terminal sat there looking alive.
    #
    # With claude gone the launcher falls through to its own `exit /b 0`, so
    # it exits 0, and the pane closes on its own.
    for victim in children:
        try:
            victim.terminate()
        except Exception:                                # noqa: BLE001
            continue

    try:
        _, still_alive = psutil.wait_procs(children, timeout=5)
    except Exception:                                    # noqa: BLE001
        still_alive = []

    for stubborn in still_alive:
        # A session that ignores SIGTERM is the one most likely to go on
        # holding the bot token, which is the whole failure being avoided.
        try:
            stubborn.kill()
        except Exception:                                # noqa: BLE001
            continue

    try:
        _, lingering = psutil.wait_procs([parent], timeout=8)
    except Exception:                                    # noqa: BLE001
        lingering = [parent]

    # It did not leave on its own -- an older launcher with no tidy exit, a
    # `pause`, a shell waiting on something. Stopping the session still
    # outranks a tidy window, so take it, and accept the corpse pane.
    for holdout in lingering:
        try:
            holdout.terminate()
        except Exception:                                # noqa: BLE001
            continue
    try:
        _, refused = psutil.wait_procs(lingering, timeout=3)
    except Exception:                                    # noqa: BLE001
        refused = []
    for stubborn in refused:
        try:
            stubborn.kill()
        except Exception:                                # noqa: BLE001
            continue

    stopped = []
    for victim in children + [parent]:
        try:
            stopped.append(victim.pid)
        except Exception:                                # noqa: BLE001
            continue
    return stopped


def _start(command: list[str]) -> int | None:
    """Start the replacement in a window the owner can see.

    Observed 2026-09-03: the dashboard runs with no window of its own, the
    replacement inherited that, and the result was a session answering
    messages from somewhere nobody could look at. An assistant you cannot see
    is not a restarted assistant; it is a second, hidden one.

    On Windows the launcher already has the two switches needed. AKI_NO_WT
    tells it not to hand itself to Windows Terminal -- which would put the
    real session in a process we did not spawn and cannot then verify -- and
    CREATE_NEW_CONSOLE gives it a console of its own regardless of what the
    parent had. WT_SESSION is cleared because its mere presence is what the
    launcher reads as "you are already in a terminal".
    """
    import os
    import subprocess

    if not command:
        return None

    if not paths.is_windows():
        return _start_on_macos(command)

    environment = dict(os.environ)
    environment["AKI_NO_WT"] = "1"
    environment.pop("WT_SESSION", None)

    try:
        process = subprocess.Popen(          # noqa: S603
            command,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        return process.pid
    except (OSError, ValueError):
        return None


def _start_on_macos(command: list[str]) -> int | None:
    """The same thing on a Mac, where the window has to be asked for.

    WHY THIS IS NOT JUST `Popen` ()
    ----------------------------------------------------------------------
    Running a `.command` directly gives a process with no terminal attached.
    On Windows that was solved with CREATE_NEW_CONSOLE; the macOS half was
    never written, so a recycle there would have produced exactly the fault
    that made this function exist in the first place -- an assistant answering
    from somewhere nobody can look at.

    `open` hands the file to Terminal.app, which gives it a real window.

    AND THEN THE PID IS THE WRONG PID, WHICH WOULD BE WORSE THAN NO WINDOW.
    `open` exits immediately, so its pid is not the session's. The caller uses
    the returned pid to EXCLUDE the replacement from the sweep that stops the
    old session -- so returning `open`'s pid would have the recycle kill the
    session it had just started, every time, on every Mac.

    So the pid is found rather than assumed: note which processes already
    match this launcher, ask Terminal to open it, and wait for one that was
    not there before. Nothing appearing returns None, which the caller reports
    as "the new session would not start -- the old one has been left running".
    Failing that way round is the whole point.

    NOT TESTED ON A REAL MAC. The maintainer has no Mac to hand and neither do I; this
    is reasoned from the same evidence as the Windows half and covered by
    tests that fake the platform. Said plainly here so the next person on a
    Mac knows which parts have and have not met one.
    """
    import subprocess
    import time as _time

    launcher = command[0]
    try:
        before = set(session.find_orphans(launcher, exclude_pid=-1))
    except Exception:                                    # noqa: BLE001
        before = set()

    try:
        subprocess.run(["open", "-a", "Terminal", launcher],  # noqa: S603, S607
                       check=True, capture_output=True, timeout=30)
    except Exception:                                    # noqa: BLE001
        return None

    # Terminal has to launch, and the shell inside it has to get as far as
    # naming the launcher on its own command line. Twenty seconds is the same
    # patience the Windows side gives a cold start.
    deadline = _time.time() + 20
    while _time.time() < deadline:
        try:
            now = set(session.find_orphans(launcher, exclude_pid=-1))
        except Exception:                                # noqa: BLE001
            now = set()
        fresh = sorted(now - before)
        if fresh:
            return fresh[0]
        _time.sleep(0.5)
    return None


# ---------------------------------------------------------------------------
# The scheduled entry point
# ---------------------------------------------------------------------------

def checkpoint() -> None:
    """Write the working state. Called on a schedule.

    THIS IS THE OTHER HALF OF THE SAME MISSING PIECE. The handoff file existed
    and nothing ever wrote it, so after a crash there was nothing to come back
    to. A handoff written only when someone remembers is a handoff that is
    absent exactly when it is needed.

    Cheap enough to run every twenty minutes, which is roughly how much work
    it is acceptable to lose.
    """
    from . import config as config_module
    from . import workspace as workspace_module

    existing = memory.read_working_state()

    open_items: list[str] = []
    waiting: list[str] = []
    touched: list[str] = []

    try:
        loaded = config_module.load()
        space = workspace_module.scan(loaded)

        for item in space.items:
            actions = item.sections.get("actions", "")
            for line in actions.splitlines():
                stripped = line.strip()
                if stripped.startswith("- [ ]"):
                    open_items.append(f"{item.title}: {stripped[5:].strip()}")

            for line in item.sections.get("waiting", "").splitlines():
                stripped = line.strip()
                if stripped.startswith("- "):
                    waiting.append(f"{item.title}: {stripped[2:].strip()}")

            if item.last_modified:
                touched.append(
                    f"{item.title} ({item.last_modified:%d %b %H:%M})")

    except Exception as exc:  # noqa: BLE001
        # A checkpoint that throws takes down whatever scheduled it. Record
        # the problem in the state itself, which is exactly where somebody
        # recovering from a crash will look.
        open_items.append(f"(checkpoint could not read the workspace: {exc})")

    memory.write_working_state(memory.WorkingState(
        generated_at=_dt.datetime.now(),
        open_items=open_items[:30],
        waiting_on=waiting[:30],
        recent_files=sorted(touched, reverse=True)[:15],
        human_notes=existing.human_notes if existing else "",
    ))
