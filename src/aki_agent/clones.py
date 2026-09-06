"""Shadow clones: several agents, one memory, one conversation.

WHAT ANZON ASKED FOR, IN HIS WORDS
----------------------------------
2026-09-01, with a
[+] / [−] beside the chat panel -- ordinarily you speak to the main body, and
you add a clone when you want a second thing running.

**The metaphor is more precise than it looks, and it is the design.** A shadow
clone does not stream its experience to the others while it works. It works
alone, and at the moment it is dispelled everything it learned returns to the
original, which carries it into every clone made afterwards. So this is not
many writers on one memory. It is *independent work, merged at the end, by one
owner* -- which is the single-writer rule wearing a better name.

WHY THIS IS POSSIBLE NOW AND WAS NOT BEFORE
-------------------------------------------
One bot token may be polled by exactly one process, so while Telegram was the
way in, one agent was the ceiling however the interface was arranged. The local
channel removed it: a queue on disk can have as many named readers as you like,
and `chat.py` puts the session's name on every line so no broker is needed.

WHAT A CLONE ACTUALLY IS
------------------------
Three things, and deliberately not a fourth:

* a **name**, because names are the addresses -- the chat queue routes by them
  and one session messages another by them;
* a **working directory**, which is the project it is for, and which is what
  makes most write conflicts impossible rather than arbitrated;
* **whether it may write shared state**, defaulting to no. A clone that can
  only read the shared memory and propose additions cannot corrupt it.

Not a fourth: it has no separate memory, no separate config, and no separate
identity. `AKI_AGENT_HOME` exists for agents that should forget each other, and
reaching for it here would produce three strangers rather than one person
working on three things.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import string
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import atomic, chat, mcp, paths, runner

# The main body. Reserved: a clone called "main" would receive the main
# agent's messages, which is a collision with no error message.
MAIN = chat.MAIN

# Somebody has to stop somewhere. This is not a technical ceiling -- it is the
# point past which a person is no longer supervising anything, they are just
# starting processes.
MAX_CLONES = 8

REGISTRY_NAME = "clones.json"

# The name the session listens to, defined once in `launcher` and shared
# so the flag, the main agent's entry and a clone's entry cannot drift apart.
from .launcher import CHANNEL_NAME as CHANNEL_SERVER  # noqa: E402


class CloneError(Exception):
    """Something a person can read and act on."""


def registry_file() -> Path:
    return paths.state_dir() / REGISTRY_NAME


@dataclass
class Clone:
    name: str
    folder: str
    created: str
    pid: int = 0

    # `may_write_shared` was here until 2026-09-06. It was a permission: a
    # field on this row, written to the registry, accepted by `create`, and
    # read from a form on the Clones page -- and NOTHING anywhere read it to
    # decide what a clone may do. It granted nothing and forbade nothing.
    #
    # Removed rather than wired up. Giving a clone a write boundary is a
    # feature that has to be designed and then enforced somewhere; a flag
    # that merely records an intention is worse than no flag, because the
    # next interface to show it would tell somebody their clone is
    # restricted, on the authority of a value nothing consults.

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "folder": self.folder,
            "created": self.created,
            "pid": int(self.pid or 0),
        }

    @property
    def alive(self) -> bool:
        return _is_running(self.pid)


def _is_running(pid: int) -> bool:
    """Is that process still there?

    Deliberately tolerant. A clone whose process cannot be inspected is
    reported as not running rather than raising, because this is drawn on a
    page that repaints on a timer and a page must not fail over a status light.
    """
    pid = int(pid or 0)
    if pid <= 0:
        return False
    try:
        import psutil                                     # noqa: PLC0415
    except ImportError:
        return True         # cannot tell; do not claim it is dead
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != "zombie"
    except Exception:                                     # noqa: BLE001
        return False


def _read() -> list[Clone]:
    data = atomic.read_json(registry_file(), default={}) or {}
    found = []
    for row in data.get("clones") or []:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        found.append(Clone(
            name=str(row.get("name")),
            folder=str(row.get("folder") or ""),
            created=str(row.get("created") or ""),
            pid=int(row.get("pid") or 0),
        ))
    return found


def _write(rows: list[Clone]) -> None:
    """Caller holds the lock. See `atomic.lock` in every mutating function."""
    atomic.write_json(registry_file(),
                      {"clones": [one.as_dict() for one in rows]})


def listing() -> list[Clone]:
    """Every clone, whether or not its process is still up."""
    return _read()


def get(name: str) -> Clone | None:
    for one in _read():
        if one.name == name:
            return one
    return None


def check_name(name: str) -> str:
    """A name is an address, so it has to be one somebody can type.

    Rejecting rather than sanitising: a name quietly turned into something
    else is a message delivered to a session the person did not mean.
    """
    cleaned = (name or "").strip().lower()
    if not cleaned:
        raise CloneError("A clone needs a name — that is how you address it.")
    if cleaned == MAIN:
        raise CloneError(
            f"{MAIN!r} is the main body. Pick another name, or you will be "
            "talking to two things at once without being able to tell.")
    if len(cleaned) > 32:
        raise CloneError("That name is too long — 32 characters at most.")
    allowed = set(string.ascii_lowercase + string.digits + "-_")
    if any(ch not in allowed for ch in cleaned):
        raise CloneError(
            "Letters, numbers, dashes and underscores only. The name is used "
            "in a filename and in a URL, so it has to be plain.")
    return cleaned


# ---------------------------------------------------------------------------
# Making one
# ---------------------------------------------------------------------------

def _channel_command() -> tuple[str, tuple[str, ...]]:
    """How to start the channel server, from wherever this is installed."""
    return sys.executable, ("-m", "aki_agent.channel_server")


def suggest_name() -> str:
    """The next free name, built from the assistant's own.

    He is right, and the prompt was asking him to invent something the system
    already knows: a clone of David is David, doing a second thing. So it is
    `david-2`, `david-3`, and the person is asked only for the part that
    genuinely varies -- which project it works in.

    Falls back to `clone` when there is no config to read, because a naming
    helper must never be the reason a clone cannot be made.
    """
    base = "clone"
    try:
        from . import config as config_module

        name = (config_module.load().assistant.name or "").strip().lower()
        cleaned = "".join(ch if (ch.isalnum() or ch in "-_") else "-"
                          for ch in name).strip("-")
        if cleaned:
            base = cleaned[:24]
    except Exception:                                     # noqa: BLE001
        pass

    taken = {one.name for one in _read()} | {MAIN}
    # Starts at 2: the main body is the first of them, so the first clone is
    # the second hand rather than a second person.
    for number in range(2, MAX_CLONES + 3):
        candidate = f"{base}-{number}"
        if candidate not in taken:
            return candidate
    return f"{base}-{len(taken) + 1}"


def configure(name: str, folder: Path) -> None:
    """Give the clone its own `.mcp.json`, naming it.

    The name goes in the server's environment rather than in an argument
    because everything the clone runs inherits the environment -- the server,
    anything it shells out to, and any tool that later wants to know which
    agent it is part of.
    """
    command, args = _channel_command()
    ok, message = mcp.add(CHANNEL_SERVER, command, args, root=folder,
                          env={chat.SESSION_ENV: name})
    if not ok and "already there" not in message:
        raise CloneError(message)


def configure_main() -> None:
    """Register the channel for the MAIN agent, in the assistant's own folder.

    THIS WAS MISSING AND IT WAS THE WHOLE POINT (2026-09-01)
    -------------------------------------------------------
    `configure()` gave every clone its own `.mcp.json`, and nothing ever gave
    one to the main body. So the dashboard wrote into the conversation, the
    channel server was never started for `main`, and the only thing still
    listening was Telegram -- which is exactly what the maintainer saw when his
    assistant kept messaging him there.

    Called from the same step that re-points the launcher, so an upgrade
    installs the listener and the flag that names it together. Doing one
    without the other produces a session that is either listening to nothing
    or told to listen to something that is not there.

    THE PROJECT ENTRY IS NOW A DUPLICATE, AND IS REMOVED (2026-09-04)
    ----------------------------------------------------------------
    The main agent's channel moved into the plugin, where it is
    `plugin:aki-agent@aki-agent` and can be approved once in managed
    settings. A project-scope copy of the same server would be started
    alongside it, tail the same log, and deliver every line twice -- so the
    old entry is taken out rather than left to rot.

    Clones keep theirs. They are named servers in their own folders and are
    reached by the main agent, not by a channel.
    """
    where = mcp.project_file().parent
    mcp.remove(CHANNEL_SERVER, root=where)
    chat.start_at_end(MAIN)


def create(name: str, folder: Path | str, *,
           start: bool = True,
           spawn: Callable[..., int] | None = None) -> Clone:
    """Register a clone, configure its channel, and start it.

    `spawn` is injectable so the registry and the configuration can be tested
    without starting a real session -- starting one is the part that cannot be
    undone by a test.
    """
    name = check_name(name)
    where = Path(folder).expanduser()

    if not where.is_dir():
        raise CloneError(
            f"{where} is not a folder that exists. A clone works somewhere; "
            "make the project folder first.")

    with atomic.lock(registry_file()):
        rows = _read()
        if any(one.name == name for one in rows):
            raise CloneError(
                f"There is already a clone called {name!r}. Remove it first, "
                "or pick another name.")
        if len(rows) >= MAX_CLONES:
            raise CloneError(
                f"That would be {len(rows) + 1} clones. The limit is "
                f"{MAX_CLONES} — past that nobody is supervising anything.")

        configure(name, where)

        # A brand new clone starts at the end of the conversation rather than
        # waking up to this morning's.
        chat.start_at_end(name)

        made = Clone(name=name, folder=str(where),
                     created=_dt.datetime.now().isoformat(timespec="seconds"))

        if start:
            made.pid = (spawn or launch)(name, where)

        rows.append(made)
        _write(rows)

    return made


def clone_arguments() -> list[str]:
    """What a clone's session is started with.

    NO CHANNEL FLAG, since 2026-09-01 evening. The only route available to a
    channel somebody wrote themselves stops on an interactive prompt at every
    start, so a clone launched with it would sit waiting for a keypress
    forever -- which is exactly what happened all evening and looked like the
    clone dying instantly.

    A clone does not need one. It is reached by the MAIN agent over
    cross-session messaging, which needs no flag and no approval, and it
    reports back the same way. That is the merge the maintainer chose in 3a: the main
    body decides, the clones return what they learned.

    What is taken from the main launcher rather than invented is the rest --
    a clone is supposed to BE the same assistant, and starting it as a plain
    Claude Code session would put a stranger in one of his project folders.
    """
    from . import launcher

    arguments: list[str] = []

    try:
        text = launcher.launcher_path().read_text(encoding="utf-8")
    except OSError:
        return arguments

    chosen = launcher.choices_in(text)
    if chosen.get("auto_mode"):
        arguments += ["--permission-mode", "auto"]
    if chosen.get("assistant_agent"):
        arguments += ["--agent", chosen["assistant_agent"]]
    return arguments


def launch(name: str, folder: Path) -> int:
    """Start a Claude Code session for this clone. Returns its process id.

    Its own window, because a clone is a session somebody may want to look at,
    and a hidden process that is doing work on your projects is the wrong
    default however convenient it is.
    """
    executable = runner.find_claude()
    environment = dict(os.environ)
    environment[chat.SESSION_ENV] = name

    # THE MACOS HALF DID NOT EXIST ()
    #
    # The docstring above promises a window, and on Windows
    # CREATE_NEW_CONSOLE delivers one. There was no equivalent here, so on a
    # Mac every clone was the exact thing that paragraph calls the wrong
    # default: a hidden process working on somebody's projects.
    if not paths.is_windows():
        return _launch_in_terminal(executable, folder, environment)

    extra: dict[str, Any] = {}
    creation = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    if creation:
        extra["creationflags"] = creation

    process = subprocess.Popen(          # noqa: S603
        [executable, *clone_arguments()], cwd=str(folder),
        env=environment, **extra)
    return int(process.pid)


def _launch_in_terminal(executable: str, folder: Path,
                        environment: dict) -> int:
    """Open a clone in a Terminal window, and return the pid of the session.

    `osascript` rather than `open`, because a clone is a command with
    arguments and an environment variable, not a file that can be double
    clicked -- and because Terminal hands back the process id of the shell it
    started, so the pid recorded is the session's own rather than a launcher's
    that has already exited.

    NOT TESTED ON A REAL MAC: neither the maintainer nor I have one to hand. The shape
    is the same as the Windows branch and it is covered by tests that fake the
    platform, but a first run on a Mac may still need adjusting -- said here
    rather than discovered by somebody trusting it.
    """
    import shlex

    session_name = environment.get(chat.SESSION_ENV, "")
    parts = [f"{chat.SESSION_ENV}={shlex.quote(session_name)}",
             shlex.quote(executable), *clone_arguments()]
    line = f"cd {shlex.quote(str(folder))} && " + " ".join(parts)
    script = (f'tell application "Terminal" to do script {json.dumps(line)}\n'
              'tell application "Terminal" to activate')

    done = subprocess.run(                # noqa: S603
        ["osascript", "-e", script],      # noqa: S607
        capture_output=True, text=True, timeout=30, check=True)

    # Terminal answers with `tab 1 of window id NNN`, which is not a pid, so
    # its reply is only proof that the window opened. The session itself is
    # the newest process running this executable in that folder.
    del done
    return _newest_session_pid(executable, folder)


def _newest_session_pid(executable: str, folder: Path) -> int:
    """The most recently started process running `executable` in `folder`.

    Zero when nothing can be seen -- the caller records that as "started, pid
    unknown" rather than pretending to a number it does not have.
    """
    import time as _time

    from . import session as session_module

    deadline = _time.time() + 20
    while _time.time() < deadline:
        try:
            psutil = session_module._psutil()
        except Exception:                                # noqa: BLE001
            return 0
        best, newest = 0, 0.0
        for process in psutil.process_iter(["pid", "cmdline", "cwd",
                                            "create_time"]):
            try:
                cmdline = " ".join(process.info.get("cmdline") or [])
                if executable not in cmdline:
                    continue
                if str(folder) not in (process.info.get("cwd") or str(folder)):
                    continue
                started = process.info.get("create_time") or 0.0
                if started > newest:
                    best, newest = process.info["pid"], started
            except Exception:                            # noqa: BLE001
                continue
        if best:
            return int(best)
        _time.sleep(0.5)
    return 0


# ---------------------------------------------------------------------------
# Dispelling one
# ---------------------------------------------------------------------------

def dispel(name: str, *, stop: Callable[[int], None] | None = None) -> str:
    """Remove a clone. What it learned has already been merged, or it has not.

    This does NOT try to extract anything from the session as it goes. The
    merge is the clone posting its result into the conversation while it is
    still working -- by the time it is dispelled, whatever it had to say has
    either been said or was never going to be. A "collect on the way out" step
    would be a second, silent path into shared memory, and there is exactly one
    on purpose.
    """
    name = (name or "").strip().lower()

    with atomic.lock(registry_file()):
        rows = _read()
        found = next((one for one in rows if one.name == name), None)
        if found is None:
            raise CloneError(f"There is no clone called {name!r}.")

        if found.pid:
            (stop or _stop)(found.pid)

        mcp.remove(CHANNEL_SERVER, root=Path(found.folder))
        _write([one for one in rows if one.name != name])

    return f"{name} dispelled."


def _stop(pid: int) -> None:
    """End the session, tolerantly. A clone already gone is not an error."""
    try:
        import psutil                                     # noqa: PLC0415

        process = psutil.Process(int(pid))
        process.terminate()
        process.wait(timeout=5)
    except Exception:                                     # noqa: BLE001
        return


def forget_dead() -> int:
    """Drop clones whose process is gone. Returns how many were dropped.

    A window somebody closed by hand should not leave a row on the page
    claiming to be an agent.
    """
    with atomic.lock(registry_file()):
        rows = _read()
        alive = [one for one in rows if not one.pid or _is_running(one.pid)]
        if len(alive) != len(rows):
            _write(alive)
        return len(rows) - len(alive)
