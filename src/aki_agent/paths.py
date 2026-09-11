"""Where things live on disk, on both Windows and macOS.

WHY THIS FILE EXISTS
--------------------
The system this package is derived from had 22 absolute user paths written
directly into its dashboard alone -- things like "C:/Users/someone/...".
Every one of those is a reason the software only ever worked on one machine.

So there is exactly one rule here, and the whole package depends on it:

    No path is ever written down anywhere except in this file.

Everything else asks this file. If you find a hardcoded path elsewhere in the
package, that is a bug, not a shortcut.

A SECOND RULE, JUST AS IMPORTANT
--------------------------------
Everything installs into *user scope*. Never "Program Files", never
"/usr/local", never anything that would ask for an administrator password.
A student should never see a UAC prompt or be asked for `sudo`. If a design
seems to need elevation, the design is wrong.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# The folder name used under the user's home directory.
#
# NOTE: this is deliberately the ONLY place the product's short name appears in
# the Python source. When the product is finally named, change this one string
# (and the plugin manifests) rather than hunting through the codebase.
APP_DIR_NAME = ".aki-agent"


def home() -> Path:
    """The current user's home directory.

    Path.home() reads USERPROFILE on Windows and HOME on macOS/Linux, so this
    is already cross-platform. We wrap it anyway so that tests can monkeypatch
    a single function instead of patching pathlib globally.
    """
    return Path.home()


def default_root() -> Path:
    """Where a fresh install puts itself: the folder the session started in.

    WHY THE CURRENT FOLDER, AND NOT A QUESTION (reported 2026-08-19)
    -------------------------------------------------------------
    Setup used to ask where the assistant should live, and offer to let the
    person drag a folder in. Two of the first three real installs then failed
    in the same way: the answer and the folders on disk disagreed, and the
    dashboard came up empty with nothing reporting an error.

    The current folder is the one answer that cannot disagree with anything.
    `CLAUDE.md` and `.claude/` are only ever read from the folder the session
    starts in, so that folder is already the assistant's home whether or not
    anybody says so -- everything else was a second, unnecessary opinion about
    the same question.

    So: Claude Code is started in a folder, and `01_Config`, `02_Sandbox` and
    `03_Workspace` appear in it. The person picks the location by choosing
    where to open the terminal, which they have already done by the time they
    are asked anything.
    """
    return Path.cwd()


def app_dir() -> Path:
    """The per-user folder holding config, state and logs.

    Windows : C:\\Users\\<name>\\.aki-agent
    macOS   : /Users/<name>/.aki-agent

    MORE THAN ONE AGENT ON ONE MACHINE
    ----------------------------------
    Setting `AKI_AGENT_HOME` moves this folder, and with it the config, the
    memory, the specialists and the state. That is what makes two different
    agents on one machine possible -- one for an architect's work, one for a
    teacher's, each with its own memory and its own idea of who it works for.

    It is deliberately an environment variable rather than a flag: every
    entry point (launchers, scheduled tasks, the dashboard, the CLI) inherits
    it without any of them needing to know it exists. Unset, which is the
    normal case, nothing changes.

    Note what this does NOT do: it does not partition anything *inside* one
    agent. Two profiles are two separate installs that happen to share a
    machine. If they should see each other's work, they are one agent with two
    workspaces, not two agents.

    We deliberately do NOT use the platform-native locations (%APPDATA% on
    Windows, ~/Library/Application Support on macOS). Those are correct for
    commercial desktop software and wrong here, for one reason: this package
    is teaching material. A student needs to be able to find their own config
    file, look at it, and understand it. A dotted folder in the home directory
    is the same on both platforms, easy to describe out loud in a classroom
    ("go to your home folder"), and easy to back up or delete.

    That is a real trade-off, taken deliberately, in favour of legibility.
    """
    override = os.environ.get("AKI_AGENT_HOME", "").strip()
    if override:
        # expanduser so that `AKI_AGENT_HOME=~/agents/teaching` behaves the way
        # anyone typing it would expect, on either platform.
        return Path(override).expanduser()

    pointed = read_pointer()
    if pointed is not None:
        return pointed

    return home() / APP_DIR_NAME


# The file that says "the agent lives over there".
#
# WHY A POINTER AND NOT JUST THE FOLDER
# -------------------------------------
# Everything an agent owns now sits in one visible folder of the user's
# choosing -- `<their folder>/01_Config` beside `02_Workspace` -- so that the
# assistant is a thing they can see, back up and move, rather than a dotted
# folder they never find. But something has to know *where* that folder is
# before anything in it can be read, and asking the user to set an environment
# variable is exactly the technical step this package refuses to require.
#
# So: one line of text in the home directory, holding a path. The env var still
# wins when it is set, because two agents on one machine is a real case.
POINTER_NAME = ".aki-agent-home"


def pointer_file() -> Path:
    return home() / POINTER_NAME


def pointer_says() -> Path | None:
    """The path written in the pointer, whether or not it is there today.

    Separate from `read_pointer` because the two questions are different, and
    conflating them was dangerous.

    A pointer that names a folder which is not present *right now* is not the
    same thing as no pointer at all. It is what a synced drive looks like at
    login: Google Drive, OneDrive and iCloud all mount their folder some
    seconds — occasionally minutes — after the user signs in, and the
    login-triggered tasks fire immediately.

    In that window everything read "No configuration file yet", and `doctor`
    told the student to run setup. Setup over an existing configuration is the
    one thing `INSTALL.md` names as impossible to undo. The documentation was
    walking them into it, on a machine where nothing was actually wrong.
    """
    try:
        text = pointer_file().read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return Path(text).expanduser() if text else None


def read_pointer() -> Path | None:
    """Where the pointer says the agent's config folder is, if it is there.

    A pointer naming a folder that is not present is not obeyed: a user who
    deleted or moved their folder should land back on the default, not watch
    every command fail against a path that is not there.

    Callers about to tell somebody their agent is missing must ask
    `pointer_says()` as well — see the note there.
    """
    candidate = pointer_says()
    if candidate is None:
        return None
    return candidate if candidate.is_dir() else None


def write_pointer(config_dir: Path) -> Path:
    """Record where this machine's agent keeps its configuration."""
    target = pointer_file()
    target.write_text(str(Path(config_dir).resolve()) + "\n", encoding="utf-8")
    return target


def adopt_app_dir(new_dir: Path) -> list[str]:
    """Move the agent's things into `new_dir`, then point at it.

    WHY THIS IS NOT JUST `write_pointer()`
    --------------------------------------
    Pointing at an empty folder is how an assistant loses its memory. The
    config, the specialists and everything remembered live in the old folder;
    redirect without moving them and every command still works, finds nothing,
    and reports a fresh install -- an amnesia with no error message anywhere,
    which is this package's whole catalogue of bugs in one move.

    So: copy across anything not already there, leave the originals alone (a
    move that half-fails must not lose the only copy), and only then write the
    pointer. Returns what was brought over, for the caller to report.
    """
    import shutil

    new_dir = Path(new_dir)
    new_dir.mkdir(parents=True, exist_ok=True)
    old_dir = app_dir()

    moved: list[str] = []
    if old_dir.exists() and old_dir.resolve() != new_dir.resolve():
        for entry in sorted(old_dir.iterdir()):
            destination = new_dir / entry.name
            if destination.exists():
                continue        # never overwrite what is already there
            try:
                if entry.is_dir():
                    shutil.copytree(entry, destination)
                else:
                    shutil.copy2(entry, destination)
            except OSError:
                # Reported by absence in the return value rather than raised:
                # one unreadable file must not abort the whole move.
                continue
            moved.append(entry.name)

    write_pointer(new_dir)
    for directory in (new_dir, new_dir / "state", new_dir / "logs",
                      new_dir / "memory"):
        directory.mkdir(parents=True, exist_ok=True)
    return moved


def config_file() -> Path:
    """The user's configuration file, written by the setup interview."""
    return app_dir() / "config.yaml"


def state_dir() -> Path:
    """Working state the agent writes as it runs (handoffs, checkpoints)."""
    return app_dir() / "state"


def log_dir() -> Path:
    """Append-only logs (traces, activity)."""
    return app_dir() / "logs"


def memory_dir() -> Path:
    """Durable facts the agent has learned about its user."""
    return app_dir() / "memory"


def ensure_app_dirs() -> None:
    """Create the per-user folders if they do not exist yet.

    Safe to call repeatedly. Called by the installer and by `doctor`.
    """
    for directory in (app_dir(), state_dir(), log_dir(), memory_dir()):
        directory.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# Platform questions
#
# These exist so that the rest of the package never writes
# `sys.platform == "win32"` inline. Platform checks scattered through a
# codebase are how software quietly becomes single-platform.
# --------------------------------------------------------------------------

# Where the tools a scheduled job runs actually live.
#
# WHY THIS LIST EXISTS, AND WHY IT IS ONLY ONE (2026-09-11)
# ---------------------------------------------------------
# launchd hands its children `/usr/bin:/bin:/usr/sbin:/sbin` and nothing
# else. Almost nothing this package depends on is in those four:
#
#   ~/.local/bin      `claude`, from Claude Code's own installer
#   /opt/homebrew/bin Homebrew on Apple silicon
#   /usr/local/bin    Homebrew on Intel, and npm -g
#   ~/.bun/bin        `bun`, which the Claude Code channel plugins run on
#
# 0.48.5 fixed the first of those and shipped the fix as TWO lists -- one
# written into the launchd plist, one inside `runner.find_claude()`. Within
# the hour a scheduled run failed again because the Telegram plugin could not
# start: `bun` was in neither list. Two lists of the same thing drift, and
# the second one is always the one somebody forgets.
#
# So: one list, read by both. Adding a directory is one edit, in one place.
EXTRA_BIN_DIRS = (
    "~/.local/bin",
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "~/.bun/bin",
    "~/.npm-global/bin",
    "~/.volta/bin",
    "~/.deno/bin",
)

# The four launchd guarantees, kept last so nothing above is shadowed by a
# system copy of the same name.
SYSTEM_BIN_DIRS = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")


def extra_bin_dirs() -> tuple[Path, ...]:
    """`EXTRA_BIN_DIRS` with `~` resolved against this user's home."""
    return tuple(Path(one.replace("~", str(home()), 1)) if one.startswith("~")
                 else Path(one) for one in EXTRA_BIN_DIRS)


def job_path() -> str:
    """The PATH to hand a scheduled job.

    Written out in full rather than with a `~`: launchd does not expand a
    tilde inside a plist value, so a tilde there names a directory that does
    not exist.
    """
    # `as_posix`, not `str`. This value is read by launchd, which is POSIX
    # by definition -- and the tests for it run on Windows, where `str(Path)`
    # produces backslashes and a separator that is already the PATH
    # delimiter. Building the string the target platform uses, rather than
    # the one the developer happens to be on, is the whole point.
    return ":".join([one.as_posix() for one in extra_bin_dirs()]
                    + list(SYSTEM_BIN_DIRS))


def is_windows() -> bool:
    return sys.platform.startswith("win")


def is_macos() -> bool:
    return sys.platform == "darwin"


def platform_label() -> str:
    """A human-readable platform name, for messages shown to the user."""
    if is_windows():
        return "Windows"
    if is_macos():
        return "macOS"
    return "Linux"


# --------------------------------------------------------------------------
# Cloud-synced drives
#
# INHERITED TRAP: do not assume a cloud-synced drive (Google Drive, OneDrive,
# iCloud, Dropbox) is mounted when the machine starts. The source system had
# scheduled work fire at boot, before the drive was ready, and fail silently
# in a way that looked like "nothing to do" rather than "cannot see anything".
#
# So: poll, with a timeout, and a clear message. Never an infinite wait --
# a student who leaves the laptop offline should be told what is wrong, not
# left with a hung window.
# --------------------------------------------------------------------------

def wait_for_path(target: Path, timeout_seconds: int = 60,
                  poll_seconds: float = 2.0) -> bool:
    """Wait for `target` to appear. Return True if it did, False on timeout.

    The caller is expected to explain the failure to the user. This function
    deliberately does not raise: "your workspace folder is not available yet"
    is a normal condition on a laptop that just woke up, not an exception.
    """
    import time

    deadline = time.monotonic() + timeout_seconds
    while True:
        if target.exists():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_seconds)


def describe_environment() -> dict:
    """A small dictionary used by `doctor` and by bug reports.

    Deliberately contains no user name, no absolute home path and no machine
    name -- a student may paste this into a class chat or send it to the maintainer for
    help, and it should not carry personal detail with it.
    """
    return {
        "platform": platform_label(),
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "python_is_64bit": sys.maxsize > 2**32,
        "app_dir_exists": app_dir().exists(),
        "config_exists": config_file().exists(),
        # os.name is 'nt' or 'posix' -- useful when a report looks odd.
        "os_name": os.name,
    }


# The folders macOS guards with TCC (Transparency, Consent and Control).
#
# A process started by launchd has no Full Disk Access, so reading anything
# inside these fails -- a shell script in one is not even executable, which
# surfaces as exit 126 and the word "Operation not permitted" if anybody is
# watching, and as nothing at all if nobody is.
PROTECTED_ON_MACOS = ("Documents", "Desktop", "Downloads")


def inside_a_protected_folder(target: "Path | str") -> str:
    """The protected folder `target` sits in, or "" -- macOS only.

    WHY THIS IS NOT A DETAIL (2026-09-11)
    --------------------------------------
    A scheduled task on macOS runs under launchd, and launchd's children get
    no Full Disk Access. Put somebody's workspace in `~/Documents` -- which
    `suggest_root` did, and which is where anybody would put it -- and every
    scheduled task is created successfully, reports success, and then fails
    at every single firing for as long as it exists.

    That is the exact failure this package keeps writing notes about: not a
    mechanism that is wrong, but one that reports success and does nothing.
    It was found when a one-off job fired on time and died with exit 126
    because `/bin/bash` was not allowed to read a script in `Documents`.
    """
    if not is_macos():
        return ""
    try:
        resolved = Path(target).expanduser().resolve()
        base = home().resolve()
    except OSError:                                       # pragma: no cover
        return ""
    for name in PROTECTED_ON_MACOS:
        guarded = base / name
        if resolved == guarded or guarded in resolved.parents:
            return name
    return ""
