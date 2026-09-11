"""Shared launcher logic. Standard library only -- it runs before anything
is installed.

WHAT THIS DOES
--------------
1. Finds a Python it can use.
2. Creates a private virtual environment for this package, if there isn't one.
3. Installs the package's dependencies into it, if they are missing.
4. Hands over to the module the user actually asked for.

WHERE THE VIRTUAL ENVIRONMENT GOES, AND WHY IT MATTERS
------------------------------------------------------
Into the user's own folder (`~/.aki-agent/venv`), NEVER into the package
folder.

The reason is practical and bites hard: people keep folders like this inside
Google Drive, OneDrive, Dropbox or iCloud. A virtual environment is thousands
of tiny files. A syncing client will either grind for hours, corrupt it
halfway through, or both -- and the failure looks like "the software is
broken" rather than "your sync client ate it".

So: the code may live on a synced drive. The environment never does.

WHY THE LAUNCHERS ARE THIN
--------------------------
The .bat and .command files next to this one do almost nothing: check that
Python exists, say something helpful if it does not, then run this file. All
the real logic is here, in one place, in a language that is the same on both
platforms. Two copies of the same logic in two shell dialects is how
cross-platform support quietly rots.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

MINIMUM_PYTHON = (3, 10)

# Kept in step with paths.APP_DIR_NAME. Duplicated on purpose: this file must
# run before the package is importable, so it cannot import that constant.
# If you rename one, rename both -- there is a test that checks they agree.
APP_DIR_NAME = ".aki-agent"

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def app_dir() -> Path:
    return Path.home() / APP_DIR_NAME


def venv_dir() -> Path:
    return app_dir() / "venv"


def venv_python() -> Path:
    if sys.platform.startswith("win"):
        return venv_dir() / "Scripts" / "python.exe"
    return venv_dir() / "bin" / "python"


def say(message: str = "") -> None:
    """Print, immediately, tolerating a console that cannot render it.

    INHERITED TRAP: a Windows console's default code page cannot print
    non-Latin text, and the resulting exception kills the process that shelled
    out to this script. A launcher that crashes while explaining an error is
    worse than useless.

    FLUSHING IS NOT OPTIONAL, and this was a real bug in the first version.
    Python buffers stdout when it is not a terminal, so the parent's messages
    were all held until exit -- while the child process it launched wrote
    straight to the console. The user saw the health report FIRST and
    "Setting up for the first time..." afterwards.

    Nothing was broken, and it looked completely broken. Anything printed
    before handing over to a subprocess has to be flushed, or the order the
    user reads is not the order things happened.
    """
    # stderr, not stdout.
    #
    # WHY (2026-08-20): this file is also the entry point for the
    # UserPromptSubmit hook, and a prompt hook's **stdout is added to the
    # session's context**. On a machine where the environment has not been
    # built yet, the first prompt would therefore carry "Setting up for the
    # first time... Installing the pieces it needs..." into the conversation,
    # as though the assistant had said it.
    #
    # Found by running the hook through this file for real rather than calling
    # the module directly -- the tests all called the module, and none of them
    # could see this.
    #
    # Progress is not data. It belongs where a person reads it and a pipe does
    # not: stderr shows in a console exactly as before.
    try:
        print(message, flush=True, file=sys.stderr)
    except UnicodeEncodeError:
        print(message.encode("ascii", "replace").decode("ascii"),
              flush=True, file=sys.stderr)


# Set on the child when this file re-runs itself under a newer interpreter,
# so the child never tries to do it again. Without it, a machine where every
# candidate reports a version this file disagrees with would fork for ever.
RELAUNCH_FLAG = "AKI_BOOTSTRAP_RELAUNCHED"


def python_candidates():
    """Interpreters to try, best first, when the current one is too old.

    WHY EXPLICIT PATHS AND NOT JUST NAMES
    --------------------------------------
    macOS ships Apple's own `python3`, and it is 3.9.6. It is first on PATH,
    it is what every `.command` here resolved, and this file refused it --
    correctly, and uselessly, because the message said "install a current
    Python" to somebody who may already have one. That is the whole macOS
    install failing at step one on a stock machine.

    Names alone do not fix it. A `.command` double-clicked from Finder starts
    with a minimal PATH: Homebrew's `/opt/homebrew/bin` is often not on it,
    and the python.org installer's PATH line lands in a shell profile that a
    non-interactive bash never reads. So the two places an installed Python
    actually lives are named outright rather than hoped for.

    Windows gets `py -3` for the same class of reason: the python.org
    installer always installs the launcher, including when the user missed
    the "Add Python to PATH" tick box, which is the box people miss.
    """
    wanted = []
    if sys.platform.startswith("win"):
        wanted.append(["py", "-3"])
    # Newest first. A machine with several installed should use the best one.
    versions = ["3.14", "3.13", "3.12", "3.11", "3.10"]
    for version in versions:
        wanted.append(["python" + version])
    if not sys.platform.startswith("win"):
        for folder in ("/opt/homebrew/bin", "/usr/local/bin",
                       "/opt/local/bin"):
            for version in versions:
                wanted.append([folder + "/python" + version])
        for version in versions:
            wanted.append(["/Library/Frameworks/Python.framework/Versions/"
                           + version + "/bin/python3"])
    return wanted


def is_new_enough(command) -> bool:
    """Run it and ask. Never trust a name or a path to say what version it is.

    The Windows Store stub on PATH is the standing reminder: it answers to
    `python`, it is zero bytes, and running it opens a shop.
    """
    test = ("import sys; raise SystemExit(0 if sys.version_info >= "
            + str(tuple(MINIMUM_PYTHON)) + " else 1)")
    try:
        done = subprocess.run(command + ["-c", test],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL,
                              timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def relaunch_under_newer_python(argv: list) -> "int | None":
    """Hand this same command to a newer Python. The exit code, or None.

    None means "carry on here": either this interpreter is already fine, or
    nothing better could be found and the caller should print the advice.

    A subprocess rather than `os.execv` on purpose -- `execv` on Windows
    replaces the process in a way that detaches it from the console it was
    started in, and a launcher whose window returns instantly while work
    carries on invisibly is worse than the problem being fixed.
    """
    if sys.version_info >= MINIMUM_PYTHON:
        return None
    if os.environ.get(RELAUNCH_FLAG):
        return None

    here = str(Path(__file__).resolve())
    child = dict(os.environ)
    child[RELAUNCH_FLAG] = "1"

    for command in python_candidates():
        if not is_new_enough(command):
            continue
        say()
        say("  The Python that started this is "
            + ".".join(str(part) for part in sys.version_info[:3])
            + ", which is too old. Using " + " ".join(command) + " instead.")
        try:
            done = subprocess.run(command + [here] + list(argv[1:]),
                                  env=child, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        return done.returncode
    return None


def check_python_version() -> bool:
    if sys.version_info >= MINIMUM_PYTHON:
        return True
    wanted = ".".join(str(part) for part in MINIMUM_PYTHON)
    have = ".".join(str(part) for part in sys.version_info[:3])
    say()
    say(f"  This needs Python {wanted} or newer, but found Python {have}.")
    say()
    say("  Install a current Python from:")
    say("      https://www.python.org/downloads/")
    say()
    if sys.platform.startswith("win"):
        say("  During the install, tick 'Add Python to PATH'.")
        say()
    return False


def ensure_venv() -> bool:
    """Create the virtual environment if it is not there. True if usable."""
    python = venv_python()
    if python.exists():
        return True

    say()
    say("  Setting up for the first time. This takes a minute.")
    say(f"  Creating a private environment in: {venv_dir()}")
    say()

    app_dir().mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir())],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0 or not python.exists():
        say("  Could not create the environment.")
        say()
        # Show the real error, but only once and clearly labelled. A user
        # forwarding this to someone for help needs the detail; they should
        # not have to scroll past it every time it works.
        detail = (result.stderr or result.stdout).strip()
        if detail:
            say("  The exact message was:")
            for line in detail.splitlines()[-6:]:
                say(f"      {line}")
            say()
        return False

    return True


def ensure_dependencies(extras: str = "full") -> bool:
    """Install the package and its dependencies into the environment.

    Installed in editable mode so that the student can open the source, change
    something, and see the change -- this package is teaching material and
    being able to poke it is the point.
    """
    python = venv_python()

    # Cheap check first: if the package imports, assume the install is good.
    # A full pip run on every launch would add seconds to every start.
    probe = subprocess.run(
        [str(python), "-c", "import aki_agent, yaml"],
        capture_output=True, text=True, check=False,
    )
    if probe.returncode == 0:
        return True

    say("  Installing the pieces it needs...")
    say()
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet",
         "-e", f"{PACKAGE_ROOT}[{extras}]"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        say("  The install did not finish.")
        say()
        detail = (result.stderr or result.stdout).strip()
        if detail:
            say("  The exact message was:")
            for line in detail.splitlines()[-10:]:
                say(f"      {line}")
        say()
        say("  If that mentions a network or proxy problem, you are probably")
        say("  behind a work firewall -- try again on a home connection.")
        say()
        return False

    return True


def run_module(module: str, arguments: list[str]) -> int:
    """Hand over to the real program inside the environment."""
    python = venv_python()
    environment = dict(os.environ)
    # Make sure Python can find the package even if the editable install
    # placed it somewhere unexpected.
    environment["PYTHONPATH"] = str(PACKAGE_ROOT / "src") + os.pathsep + \
        environment.get("PYTHONPATH", "")
    # Force UTF-8 inside the child, for the same console-encoding reason
    # described in `say()`.
    environment["PYTHONIOENCODING"] = "utf-8"

    completed = subprocess.run(
        [str(python), "-m", module, *arguments],
        env=environment, check=False,
    )
    return completed.returncode


SHIM_NAME = "aki.py"

SHIM = '''"""Run the assistant without needing to know where it is installed.

Written by `bin/_bootstrap.py`. Do not edit -- it is replaced every time the
plugin runs, which is how it stays correct across updates and reinstalls.

WHY THIS FILE EXISTS
--------------------
The skills used to say:

    python "${CLAUDE_PLUGIN_ROOT}/bin/_bootstrap.py" aki_agent.doctor

`CLAUDE_PLUGIN_ROOT` is substituted in plugin hooks and slash-command
frontmatter. It is NOT set in the environment of an ordinary Bash call, which
is how skills actually run -- so the variable expanded to nothing and the
student's first screen was:

    python: can't open file '/bin/_bootstrap.py'

A model usually recovers by guessing the path, and a wrong guess runs a stale
copy of the package from an old install. The failure was in 17 places in the
setup skill alone and 60+ across all of them.

This file's own path never changes, so nothing has to be guessed.
"""
import runpy
import sys

BOOTSTRAP = __BOOTSTRAP__

sys.argv = [BOOTSTRAP] + sys.argv[1:]
runpy.run_path(BOOTSTRAP, run_name="__main__")
'''


def remember_where_i_am() -> None:
    """Write down where the plugin is, and leave a launcher beside it.

    Called on every run. The hooks in `plugin.json` invoke this file on every
    Bash call and every user prompt, and `${CLAUDE_PLUGIN_ROOT}` *is*
    substituted there -- so by the time anybody runs a command by hand, both
    files are already correct, including straight after an update that moved
    the plugin to a new version folder.

    Never raises. This is bookkeeping at the top of a launcher; a read-only
    home directory must not stop the thing the user actually asked for.
    """
    try:
        directory = app_dir()
        directory.mkdir(parents=True, exist_ok=True)

        pointer = directory / "plugin-root"
        wanted = str(PACKAGE_ROOT)
        if not pointer.exists() or pointer.read_text(
                encoding="utf-8").strip() != wanted:
            pointer.write_text(wanted + "\n", encoding="utf-8")

        shim = directory / SHIM_NAME
        # `replace`, not `format`: the template above documents a
        # `${CLAUDE_PLUGIN_ROOT}`, and `format` reads those braces as fields
        # of its own and raises on the first one. Which it did -- silently,
        # because this whole function swallows exceptions, so the pointer was
        # written and the launcher beside it was not.
        body = SHIM.replace("__BOOTSTRAP__", repr(str(Path(__file__).resolve())))
        if not shim.exists() or shim.read_text(encoding="utf-8") != body:
            shim.write_text(body, encoding="utf-8")
    except Exception:                                    # noqa: BLE001
        pass


# Modules that run as Claude Code hooks, and must never build anything.
#
# WHY (2026-08-23)
# ----------------
# `plugin.json` runs `aki_agent.safety_gate` before every Bash call and
# `aki_agent.pending_hook` on every user prompt. Both went through the full
# path below, which on a machine that has not been set up means creating a
# virtual environment and running a cold `pip install .[full]` -- Flask,
# keyring, psutil and Telethon.
#
# Claude Code's hook timeout is 60 seconds. A cold Telethon install on Windows
# is comfortably past that. So the student's first Bash command hung for a
# minute and was killed, and then it happened again on the next one, and on
# every prompt, because nothing about the failure was remembered.
#
# Neither of these needs any of it. The safety gate is standard-library by
# design and documents itself as failing open; the prompt hook reads a JSON
# file. So when the environment is not ready they do nothing at all, quietly,
# and the real install happens where there is no timer on it: the setup skill,
# the launchers, and `doctor`.
HOOKS = ("aki_agent.safety_gate", "aki_agent.pending_hook")


def main(argv: list[str]) -> int:
    module = argv[1] if len(argv) > 1 else "aki_agent.doctor"
    arguments = argv[2:]

    remember_where_i_am()

    # Before refusing an old Python, look for a newer one. The refusal is the
    # last resort, not the first answer.
    handed_over = relaunch_under_newer_python(argv)
    if handed_over is not None:
        return handed_over

    if not check_python_version():
        # A hook must not fail the command it is inspecting because of the
        # Python version. Fail open, in the safety gate's own words.
        return 0 if module in HOOKS else 1

    if module in HOOKS:
        if not venv_python().exists():
            return 0
        return run_module(module, arguments)

    if not ensure_venv():
        return 1
    if not ensure_dependencies():
        return 1

    return run_module(module, arguments)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
