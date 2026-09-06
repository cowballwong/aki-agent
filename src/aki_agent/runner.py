"""Running the assistant without a person sitting there.

WHAT THIS IS FOR
----------------
Scheduled work: a morning summary, a weekly tidy-up, a check on something.
The assistant is invoked non-interactively, does the job, and either writes
the result somewhere or sends it through the notification gate.

**No API key is involved.** This runs the user's own Claude Code, signed in
as them. That was verified by measurement rather than assumed: on a machine
with no `ANTHROPIC_API_KEY` anywhere in the environment or in any secrets
file, scheduled headless runs execute and exit cleanly. Subscription sign-in
covers headless invocation. Do not reintroduce a key requirement.

TWO PLATFORM TRAPS, BOTH FIXED HERE
-----------------------------------

**1. Windows has a command-line length limit** and a real prompt will exceed
it. The failure is not a clean error either — it is a truncated prompt, or a
mysterious refusal to start. So the prompt goes in through **standard input**,
never as an argument. This costs nothing and removes an entire class of
bug that only appears once prompts get long enough to be useful.

**2. A Windows console's default encoding cannot render non-Latin text**, and
the exception that raises kills whatever shelled out. The child process is
given an explicit UTF-8 environment. A user whose assistant speaks Chinese,
Greek or Arabic should not discover this the hard way at 07:00 on a schedule.
"""

from __future__ import annotations

import datetime as _dt
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import memory, paths, secrets

# A scheduled job that hangs is worse than one that fails: it holds a slot,
# produces nothing, and gives no signal. Everything here is bounded.
DEFAULT_TIMEOUT_SECONDS = 900


class ClaudeNotFound(Exception):
    """Raised when the `claude` command is not on this machine."""


@dataclass
class RunResult:
    ok: bool
    output: str
    error: str = ""
    seconds: float = 0.0
    timed_out: bool = False

    def reason(self) -> str:
        """Why it failed, wherever the failure happened to be written.

        `claude` prints some of its own fatal errors to STDOUT and exits
        non-zero with an empty stderr. Reading only stderr therefore produced
        the least useful message an agent can send: "failed after 7s:" -- it
        knew something had gone wrong, knew how long it took, was holding the
        answer, and did not say it.

        The maintainer got exactly that on 2026-08-24 for two morning tasks, asked why,
        and the answer was sitting in stdout: "OAuth session expired and could
        not be refreshed". One line, and it would have told him what to do.

        Only used when the run FAILED. On a healthy run stdout is the work,
        not an explanation, and it belongs where the work goes.
        """
        for candidate in (self.error, self.output):
            first = (candidate or "").strip()
            if first:
                # The first line, not the whole thing: a failure notice goes
                # to a phone, and a page of output there is the same as none.
                return first.splitlines()[0][:200]
        return "no reason given -- see the task's own log"

    def summary(self) -> str:
        """One line for a log or a notification."""
        if self.timed_out:
            return f"timed out after {self.seconds:.0f}s"
        if self.ok:
            return f"finished in {self.seconds:.0f}s"
        return f"failed after {self.seconds:.0f}s: {self.reason()}"


# What a scheduled task is allowed to do.
#
# WHY THIS HAD TO BE SAID OUT LOUD (reported 2026-08-21)
# ----------------------------------------------------
# His 08:00 task reported:
#
# Headless `claude -p` asks for permission like any other session, and there is
# nobody there to answer — so the request is refused and the run carries on
# without it. The package spends a whole section of the assistant's brief
# telling it to read the house rules before anything else, and then scheduled
# it in a mode where it cannot. A mechanism with nothing wired to it, again.
#
# `Bash(python *)` USED TO BE ON THIS LIST. It was not a narrowing (2026-08-23)
# ----------------------------------------------------------------------------
# The comment here read: "Narrowed to python rather than bare Bash: a headless
# agent with an open shell is a different proposition from one that can run
# this package's commands."
#
# That reasoning is the bug. `python -c "..."` is a general-purpose shell, so
# `Bash(python *)` pre-approves anything at all -- it is `Bash(*)` with three
# more characters of typing. And the one backstop, the PreToolUse safety gate,
# holds nine patterns for `rm -rf /`, `mkfs`, `dd of=/dev/` and the like; not
# one of them can match a `python` invocation.
#
# What that adds up to, on a student's machine: the default workspace root is
# their Google Drive or OneDrive folder, and the 08:00 summary reads the whole
# of it with nobody at the keyboard. Anyone who can put a file in that folder
# -- share it, or email a document the student saves -- could put a sentence
# in it and have this run whatever they liked. The only thing between those
# two facts was a line of prose in the prompt asking the model to treat file
# contents as information rather than instruction. That sentence is real and
# it is correctly placed, but it is a probabilistic mitigation guarding a
# deterministic capability.
#
# So the shell permission is now the exact command a task is actually told it
# may run, and nothing else. `tasks._prompt_for` offers precisely one:
# `aki_agent.inbox pending`. If a future task needs another, add it here on
# purpose -- the failure mode of being too strict is a task that says it could
# not check something, which is visible and harmless.
def scheduled_tools() -> tuple[str, ...]:
    """What a headless run is allowed to do.

    Built at call time rather than as a constant, because the bootstrap path
    is per-install and has to be spelled out exactly for the allowlist to
    match it.
    """
    from . import engine

    allowed = ["Read", "Grep", "Glob"]
    try:
        allowed.append(f"Bash({engine.how_to_run('aki_agent.inbox', 'pending')})")
    except Exception:                                     # pragma: no cover
        # No engine path yet -- a first run before scaffolding. Read-only is
        # the right answer then, not a wider grant.
        pass
    return ("--allowedTools", *allowed)


def find_claude() -> str:
    executable = shutil.which("claude")
    if not executable:
        raise ClaudeNotFound(
            "The `claude` command was not found, so scheduled work cannot "
            "run. Install Claude Code from https://claude.com/claude-code "
            "and sign in."
        )
    return executable


def run(prompt: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS,
        working_directory: Path | None = None,
        extra_args: tuple[str, ...] = ()) -> RunResult:
    """Run one headless task and return what it produced.

    The prompt is delivered on stdin -- see trap 1 at the top of this file.
    """
    executable = find_claude()

    # Whatever brain this install was set up against, use the same one here.
    #
    # A scheduled task runs from Task Scheduler, not from the terminal the
    # student configured Ollama in, so `ANTHROPIC_BASE_URL` and the model are
    # both absent unless something puts them back. Without this, somebody
    # running a local model gets an assistant that answers them all day and
    # then fails every night against a service they are not signed in to.
    #
    # Empty for an ordinary install, so nothing changes for anybody who
    # changed nothing.
    from . import backend as backend_module

    brain = backend_module.stored()

    command = [executable, "-p", *scheduled_tools(),
               *brain.arguments(), *extra_args]

    environment = dict(os.environ)
    environment.update(brain.environment())
    # Trap 2. Force UTF-8 in the child regardless of the console's code page.
    environment["PYTHONIOENCODING"] = "utf-8"
    environment.setdefault("PYTHONUTF8", "1")

    started = _dt.datetime.now()

    # Both callers of this are headless -- a scheduled task and a
    # specialist -- so a console window is never wanted here. It was
    # what the maintainer saw flashing over his work every twenty minutes
    # (2026-08-19): the scheduler starts the runner hidden now, and
    # this stops the child claiming a fresh window of its own.
    hidden = ({'creationflags': subprocess.CREATE_NO_WINDOW}
              if hasattr(subprocess, 'CREATE_NO_WINDOW') else {})

    try:
        completed = subprocess.run(
            command,
            **hidden,
            input=prompt,                 # <- stdin, never an argument
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(working_directory) if working_directory else None,
            env=environment,
            check=False,
        )
    except subprocess.TimeoutExpired:
        elapsed = (_dt.datetime.now() - started).total_seconds()
        return RunResult(False, "", "the task took too long and was stopped",
                         elapsed, timed_out=True)
    except OSError as exc:
        elapsed = (_dt.datetime.now() - started).total_seconds()
        return RunResult(False, "", f"could not start: {exc}", elapsed)

    elapsed = (_dt.datetime.now() - started).total_seconds()

    # Redact on the way out. Scheduled output is written to files and sent to
    # phones, which are the two places a leaked token travels furthest.
    output = secrets.redact(completed.stdout or "")
    error = secrets.redact(completed.stderr or "")

    return RunResult(completed.returncode == 0, output.strip(),
                     error.strip(), elapsed)


def run_and_record(task_name: str, prompt: str, **kwargs) -> RunResult:
    """Run a scheduled task and write it into the daily narrative.

    Records both outcomes. A scheduled job that fails silently is how a person
    discovers three weeks later that their morning summary stopped in March.
    """
    result = run(prompt, **kwargs)

    if result.ok:
        memory.log_event(f"{task_name}: {result.summary()}")
    else:
        memory.log_event(f"{task_name}: FAILED — {result.summary()}")

    _post_to_the_conversation(task_name, result)
    return result


def _post_to_the_conversation(task_name: str, result: RunResult) -> None:
    """Put the job's result where the person is actually looking.

    reported 2026-09-01: scheduled work belongs in the main agent's window.

    **What goes in is the finding, not the digging.** A scheduled run is
    already a clone in everything but name -- its own process, its own
    context, dispelled when it is done -- and that isolation is the reason
    this is safe. If the job's work happened *inside* the main conversation,
    every file it opened would sit in that context for the rest of the day and
    be re-read on every later turn. So what crosses over is one line.

    Never raises, for the same reason the notification mirror does not: a job
    that did its work must not be reported as failed because the note about it
    could not be written.
    """
    try:
        from . import chat

        note = (f"{task_name} — {result.summary()}" if result.ok
                else f"{task_name} — FAILED: {result.summary()}")
        chat.say("assistant", note, session=chat.MAIN, meta={
            "origin": "task",
            "task": task_name,
            "ok": "yes" if result.ok else "no",
        })
    except Exception:                                     # noqa: BLE001
        return


def write_output(task_name: str, text: str,
                 day: _dt.date | None = None) -> Path:
    """Save a task's output where the dashboard can find it."""
    day = day or _dt.date.today()
    directory = paths.log_dir() / "runs" / day.isoformat()
    directory.mkdir(parents=True, exist_ok=True)

    from . import atomic
    stamp = _dt.datetime.now().strftime("%H%M%S")
    safe_name = "".join(character if character.isalnum() else "-"
                        for character in task_name).strip("-").lower()
    return atomic.write_text(directory / f"{stamp}-{safe_name}.md",
                             secrets.redact(text))
