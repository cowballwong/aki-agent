"""Make the assistant stop depending on the folder it was unzipped in.

THE BUG THIS EXISTS FOR (reported 2026-08-19)
-------------------------------------------
He unzipped a release, installed the plugin, ran `/aki-agent:setup`, and then asked the
obvious question: can I delete the unzipped folder now? The answer was no, and
it should have been yes. An installer that leaves the product wired to the
box it came in has not finished installing.

Three separate wires ran back to that folder, none of which announced itself:

  * the virtual environment held an **editable** install, so the `.pth` file
    in it named `<unzipped>/src`. Delete the folder and every command, the
    dashboard and every scheduled task stop importing -- with a traceback, if
    anyone is watching, and silence if nobody is.
  * every scheduled task ran `<unzipped>/bin/run-task.bat`.
  * the launcher named `<unzipped>/bin/_bootstrap.py` and the dashboard
    script beside it.

WHAT THIS DOES INSTEAD
----------------------
Copies the package into the assistant's own config folder -- `01_Config/engine`
-- reinstalls the environment from *that*, and re-points the launcher and the
scheduled tasks at it. After that the unzipped folder is a spent installer and
can go in the bin.

WHY A COPY RATHER THAN A NORMAL (NON-EDITABLE) INSTALL
------------------------------------------------------
A plain `pip install <path>` would also cut the wire, by copying the code into
`site-packages`. It was rejected for two reasons, both of them this package's
existing decisions rather than new ones:

  * **the editable install is deliberate.** This is teaching material; a
    student opening the engine, changing a line and seeing the change is the
    point. `site-packages` inside a hidden virtual environment is where code
    goes to become unreadable.
  * **one visible folder is the assistant.** `01_Config` already holds the
    settings, the memory, the logs and the launcher, and the whole design
    rests on a person being able to see, back up and move that folder. The
    engine belongs in it for the same reason everything else does.

The cost is about 2 MB of duplicated text files and the need to re-adopt after
an upgrade -- which `doctor` reports, because the alternative is a person
discovering it months later.
"""

from __future__ import annotations

import ast
import os
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

# What a working copy of the engine needs. Named explicitly, never "everything
# except" -- the same inclusion rule the uninstall follows, for the same
# reason: a list of exclusions silently adopts whatever is added next.
COPIED = (
    "src",                 # the engine itself
    "bin",                 # the bootstrap, the runners, the dashboard scripts
    "skills",              # so the folder is still a complete plugin
    "library",             # the 100+ shipped skills and specialists;
                           # without this an adopted engine has an
                           # empty library and nothing says why
    "agents",
    "configs",             # the two example configs INTEGRATE.md points at
    "examples",            # the worked plugin somebody copies to write their
                           # own; `plugin add examples/plugins/...` is the
                           # first thing PLUGIN.md tells anyone to run, and
                           # it has to be there for that to be true
    "tests",               # INTEGRATE.md tells a student's agent to run these
    ".claude-plugin",      # the manifest, so it can be re-added as a market
    "pyproject.toml",
    "README.md",
    "INSTALL.md",
    "INTEGRATE.md",
)

# Never copied: caches and build droppings, which are large, useless and in
# the case of `_release` recursive -- a release zip containing every previous
# release zip is a mistake this project has already made once.
SKIPPED = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".pytest_cache", "_release", ".git",
    "desktop.ini", "*.egg-info", "venv", ".venv",
)

ENGINE_DIR_NAME = "engine"

# Where an upgrade zip is unpacked before it is copied in. Scratch: it is
# deleted once the copy has been made. Deliberately NOT `_upgrade`, which
# holds the permanent record of past upgrades -- see `upgrade_log.py`.
UNPACK_DIR_NAME = "_incoming"


def engine_dir() -> Path:
    """Where the adopted copy lives: inside the assistant's config folder."""
    return paths.app_dir() / ENGINE_DIR_NAME


def running_from() -> Path:
    """The copy of the package this process is actually importing.

    `parents[2]` because this file is `<root>/src/aki_agent/engine.py`. The
    same derivation appears in `schedule.py` and `situation.py`; it is here so
    that the question "which copy am I?" has one answer to import.
    """
    return Path(__file__).resolve().parents[2]


def bootstrap() -> Path:
    """The entry point every generated command must go through.

    WHY `python -m aki_agent.…` IS WRONG IN GENERATED TEXT (2026-08-20)
    -------------------------------------------------------------------
    Three shipped places told the assistant to run `python -m aki_agent.inbox
    pending`, and on a real install it fails with *No module named
    'aki_agent'*: the package lives in the assistant's own virtual
    environment, and a bare `python` started in the user's workspace is not
    that interpreter. `bin/_bootstrap.py` exists precisely to find the right
    one.

    The damage was not obvious, which is why it survived. One of the three was
    the shipped scheduled task **whose entire job is collecting messages typed
    into the dashboard** -- so those messages queued, nothing picked them up,
    and the symptom reaching the user was "I typed in the chat panel and
    nothing happened". A broken instruction inside a prompt does not raise
    anything; the model simply reports that the command failed, into a log
    nobody reads.

    So: generated text asks *here* for its command line, and there is one
    answer.
    """
    installed = engine_dir() / "bin" / "_bootstrap.py"
    if installed.is_file():
        return installed
    return running_from() / "bin" / "_bootstrap.py"


def how_to_run(*arguments: str) -> str:
    """A command line a future process can actually execute."""
    return f'python "{bootstrap()}" ' + " ".join(arguments)


def is_adopted() -> bool:
    """Is the code running now the copy inside the assistant's folder?"""
    try:
        return running_from().resolve() == engine_dir().resolve()
    except OSError:                                       # pragma: no cover
        return False


def env_for(target: Path) -> dict:
    """The environment a subprocess needs to actually run the NEW engine.

    WHY THIS EXISTS (reported 2026-09-04)
    -----------------------------------
    `_repoint_after_upgrade` hands the re-pointing to a fresh process on
    purpose, so that the NEW code does it rather than the version being
    replaced. That reasoning is sound and it was silently defeated.

    `bin/_bootstrap.py` puts its own `PACKAGE_ROOT/src` at the front of
    `PYTHONPATH` before handing over. Every child process inherits it, and an
    explicit `PYTHONPATH` beats an editable install -- so the "new process"
    imported the old package out of the old folder anyway.

    What that cost him, in one upgrade: his launcher was rewritten by 0.41.3,
    which dropped the `TELEGRAM_STATE_DIR` line 0.41.4 added. Without that
    line this assistant starts in `~/.claude/channels/telegram`, which is
    shared, and takes over the bot belonging to the other assistant on his
    machine. A silently reverted safety line is worse than a failed upgrade,
    because nothing about it looks wrong.

    So: keep every `PYTHONPATH` entry that lives inside the engine being run,
    drop the ones that point somewhere else. A path the person set themselves
    for their own reasons is left alone unless it shadows this package.
    """
    environment = dict(os.environ)
    existing = environment.get("PYTHONPATH", "")
    if not existing:
        return environment

    try:
        inside = Path(target).resolve()
    except Exception:                                     # noqa: BLE001
        return environment

    kept = []
    for entry in existing.split(os.pathsep):
        if not entry.strip():
            continue
        try:
            where = Path(entry).resolve()
        except Exception:                                 # noqa: BLE001
            kept.append(entry)
            continue
        shadows = (where / "aki_agent").is_dir()
        ours = where == inside or inside in where.parents
        if shadows and not ours:
            continue
        kept.append(entry)

    if kept:
        environment["PYTHONPATH"] = os.pathsep.join(kept)
    else:
        environment.pop("PYTHONPATH", None)
    return environment


def venv_python() -> Path | None:
    """The interpreter that owns the install, or None if there is no venv.

    Prefers the one running this process when that is already a virtual
    environment -- which it is whenever the launcher or a scheduled task
    started us. The fallback repeats `bin/_bootstrap.py`'s location, and the
    duplication is deliberate for the same reason it is deliberate there: the
    bootstrap must work before this package is importable, so neither file can
    import the other.
    """
    if sys.prefix != sys.base_prefix:
        return Path(sys.executable)

    guess = (paths.home() / paths.APP_DIR_NAME / "venv"
             / ("Scripts" if paths.is_windows() else "bin")
             / ("python.exe" if paths.is_windows() else "python"))
    return guess if guess.exists() else None


@dataclass
class Adoption:
    """What adopting would copy, and where from and to."""

    source: Path
    target: Path
    items: list[str] = field(default_factory=list)
    already: bool = False

    def describe(self) -> str:
        if self.already:
            return (f"The engine already lives in your own folder:\n\n"
                    f"  {self.target}\n\n"
                    "Nothing to copy. The folder you installed from is not "
                    "needed and can be deleted.")
        lines = [
            "This would copy the engine into your own folder, so that nothing",
            "points at the folder you unzipped:",
            "",
            f"  from  {self.source}",
            f"  to    {self.target}",
            "",
            "Copying:",
            "",
        ]
        lines += [f"  - {name}" for name in self.items]
        lines += [
            "",
            "Then it reinstalls the environment from the copy, and rewrites",
            "the launcher and the scheduled tasks to point at it.",
            "",
            "Your settings, memory and work are not touched.",
        ]
        return "\n".join(lines)


def plan(source: Path | None = None, target: Path | None = None) -> Adoption:
    """Work out what adopting would do. Writes nothing."""
    source = Path(source) if source else running_from()
    target = Path(target) if target else engine_dir()

    try:
        already = source.resolve() == target.resolve()
    except OSError:                                       # pragma: no cover
        already = False

    # The manifest comes from the source, not from this running copy -- see
    # `manifest_for`. When the source *is* this copy (a plain adopt) the two
    # are the same, so nothing changes for that path.
    wanted = manifest_for(source)
    items = [name for name in wanted if (source / name).exists()]
    return Adoption(source=source, target=target, items=items, already=already)


# ---------------------------------------------------------------------------
# Replacing the engine safely
#
# WHAT WENT WRONG, AND WHY THE SHAPE OF THIS CHANGED (2026-08-20)
# --------------------------------------------------------------
# A 0.5.0 -> 0.8.0 upgrade on Windows failed three times and left the product
# unusable twice. The root cause was one line: `shutil.rmtree` ends each
# directory with `os.rmdir`, which returns WinError 5 on a directory carrying
# the Windows ReadOnly attribute -- and every directory in the release package
# carries it, because `copytree` calls `copystat` and brings the attribute
# across from the zip.
#
# But the root cause is the least interesting part. What turned a one-line bug
# into a destroyed install was the *order*: the working engine was deleted
# before the replacement was staged. `rmtree` got through `.claude-plugin`,
# `agents` and `bin`, hit `configs/examples`, and threw. `bin/_bootstrap.py`
# was gone -- the entry point for every command AND for the PreToolUse hook --
# so the tool could no longer run, diagnose itself, or repair itself. The
# obvious human response, running it again, repeated the destruction.
#
# So three things changed, and only one of them is the ReadOnly fix:
#
#   1. Copy to `engine.new`, verify it, then swap. A failure at any point
#      before the swap leaves the working engine untouched, which makes
#      retrying safe -- and retrying is what people actually do.
#   2. `engine.old` is kept until the next upgrade, so there is a rollback.
#   3. The ReadOnly attribute is cleared on the way in and on the way out, so
#      it neither blocks a delete nor gets handed to the next upgrade.
#
# The general lesson, worth more than the specific bug: an operation that
# destroys the only working copy before it has a replacement is not a risky
# operation, it is a broken one, however reliable the replacement step is.
# ---------------------------------------------------------------------------

STAGING_SUFFIX = ".new"
PREVIOUS_SUFFIX = ".old"

# Written into the installed engine after a successful copy, so a later
# `doctor` can tell a complete install from one that lost a folder on the way.
MANIFEST_FILE = ".installed-manifest"


def clear_readonly(root: Path) -> int:
    """Drop the Windows ReadOnly attribute from a tree. Returns the count.

    Applied to the *installed* copy as well as before a delete, because the
    attribute travels: `copytree` copies directory metadata, so an install
    that merely worked around the attribute hands the same landmine to the
    next upgrade. Done here as well as in `bin/make_release.py`, which is belt
    and braces on purpose -- a package built before that fix, or unzipped by a
    tool that sets the bit itself, still has to install.
    """
    cleared = 0
    if not root.exists():
        return 0
    for path in [root, *root.rglob("*")]:
        try:
            mode = path.stat().st_mode
            if not mode & stat.S_IWRITE:
                path.chmod(mode | stat.S_IWRITE)
                cleared += 1
        except OSError:
            continue
    return cleared


def _on_remove_error(func, path, _exc):
    """Clear ReadOnly and retry once. The `rmtree` handler."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def force_rmtree(target: Path) -> None:
    """`rmtree` that survives a ReadOnly directory on Windows."""
    if not target.exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(target, onexc=_on_remove_error)
    else:                                                 # pragma: no cover
        shutil.rmtree(target, onerror=_on_remove_error)


def manifest_for(source: Path) -> tuple[str, ...]:
    """What to copy, read from the INCOMING release rather than this one.

    THE BUG THIS CLOSES
    -------------------
    `plan()` used the running engine's `COPIED`, so the *old* version decided
    what the *new* version consists of. `library` -- 103 shipped skills and
    specialists -- is in 0.8.0's list and was not in 0.5.0's, so a 0.5.0
    engine upgrading to 0.8.0 simply never copied it. Nothing failed. `doctor`
    passed. The install was quietly missing a hundred files, and the only way
    anyone found out was by reading both manifests side by side.

    Left as it was, no release could ever add a top-level folder.

    Parsed rather than imported: importing a module out of an unverified
    package would execute it, and this runs before anything about that package
    has been checked. `ast.literal_eval` on one assignment cannot run code.
    """
    theirs = source / "src" / "aki_agent" / "engine.py"
    try:
        tree = ast.parse(theirs.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return COPIED

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(one, ast.Name) and one.id == "COPIED"
                   for one in node.targets):
            continue
        try:
            found = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            return COPIED
        if isinstance(found, (tuple, list)) and found and all(
                isinstance(one, str) for one in found):
            return tuple(found)
    return COPIED


def readiness(target: Path | None = None) -> list[str]:
    """What a dry run should say beyond "nothing has changed".

    A preflight that reports only that the target exists, followed by a
    destructive failure, is the worst possible sequence -- it spends the
    user's trust before it spends their install. So: say what is actually in
    the way, and say it while nothing has been touched.
    """
    target = Path(target) if target else engine_dir()
    notes: list[str] = []
    if not target.exists():
        return notes

    readonly = 0
    for path in target.rglob("*"):
        try:
            if path.is_dir() and not path.stat().st_mode & stat.S_IWRITE:
                readonly += 1
        except OSError:
            continue
    if readonly:
        notes.append(str(readonly) + " folder(s) in the current engine are "
                     "read-only. They are cleared automatically now; before "
                     "2026-08-20 this is what made the upgrade fail.")

    previous = target.with_name(target.name + PREVIOUS_SUFFIX)
    if previous.exists():
        notes.append("a previous engine is still kept at " + previous.name
                     + " and will be replaced by this one.")
    return notes


def _verify(folder: Path, expected) -> list[str]:
    """Is this staged copy fit to become the engine? Checked before the swap.

    The entry point is checked by name rather than by counting files, because
    `bin/_bootstrap.py` is the thing whose absence takes the whole product
    down: it backs every CLI command and the PreToolUse hook, so a copy that
    lost it cannot even report that it lost it.
    """
    problems: list[str] = []

    if not (folder / "bin" / "_bootstrap.py").is_file():
        problems.append("bin/_bootstrap.py is missing, and nothing runs "
                        "without it")

    missing = [name for name in expected if not (folder / name).exists()]
    if missing:
        problems.append("did not arrive: " + ", ".join(missing))

    # An unreadable version is deliberately NOT a reason to refuse the copy.
    # It is diagnostic, not structural: an engine with every file and its
    # entry point runs perfectly well while its version line is missing, and
    # blocking here would turn a cosmetic defect into an install that cannot
    # proceed at all. `doctor.check_install_complete` reports it instead --
    # which is the right place, because that is where somebody is asking.
    return problems


# How long to keep trying the swap before giving up.
#
# WHY THIS EXISTS: OBSERVED IN THE FIELD, 2026-08-20
# --------------------------------------------------
# The very first real 0.8.2 -> 0.9.0 upgrade failed here -- `WinError 5`
# renaming `engine.new` onto `engine` -- and succeeded ninety seconds later
# with nothing else changed. That is the signature of a *transient* handle,
# not a running program: a search indexer, an antivirus scanner or a sync
# client had the folder open for a moment.
#
# Windows has no equivalent of the POSIX behaviour where an open file does not
# block a rename, so a single attempt turns a half-second of somebody else's
# housekeeping into a failed upgrade. Retrying costs nothing when the folder is
# free and rescues the common case when it is not.
#
# It does NOT retry forever. A genuinely running dashboard holds the folder
# indefinitely, and the honest answer there is the message telling them to
# close it -- which is what happens once these attempts are used up.
SWAP_ATTEMPTS = 6
SWAP_PAUSE = 1.0


def _rename_with_retry(source: Path, target: Path) -> None:
    """Rename, tolerating a lock somebody else is about to release."""
    last: OSError | None = None
    for attempt in range(SWAP_ATTEMPTS):
        try:
            source.rename(target)
            return
        except OSError as exc:
            last = exc
            if attempt < SWAP_ATTEMPTS - 1:
                time.sleep(SWAP_PAUSE)
    raise last  # type: ignore[misc]


# What identifies a running dashboard. Matched against the command line
# rather than the port, because the port only tells you *something* is
# listening -- and the thing that matters here is specifically a process
# running out of the folder about to be replaced.
DASHBOARD_MARKER = "aki_agent.dashboard"


def dashboard_processes() -> list[tuple[int, float]]:
    """Every running dashboard, as (pid, when it started).

    NOT COUNTING THIS PROCESS, and that is not a detail (2026-08-20). The
    first version of this check matched on command line and found itself --
    the query contained the marker it was searching for -- so it reported one
    dashboard more than existed, and I told the maintainer he had a duplicate to clean
    up. He did not. Anything that searches by command line has to exclude its
    own, or it is reading its own reflection.

    Returns an empty list when psutil is unavailable. The caller must treat
    that as "cannot tell", never as "none running".
    """
    import os

    try:
        import psutil
    except Exception:                                     # noqa: BLE001
        return []

    mine = os.getpid()
    found = []
    for process in psutil.process_iter(["pid", "cmdline", "create_time"]):
        try:
            if process.info["pid"] == mine:
                continue
            parts = process.info.get("cmdline") or []
            if any(DASHBOARD_MARKER in str(part) for part in parts):
                found.append((process.info["pid"],
                              process.info.get("create_time") or 0.0))
        except Exception:                                 # noqa: BLE001
            continue
    return sorted(found)


def can_see_processes() -> bool:
    """Is process inspection available at all on this machine?"""
    try:
        import psutil                                     # noqa: F401
    except Exception:                                     # noqa: BLE001
        return False
    return True


def stop_dashboard() -> tuple[int, list[str]]:
    """Close any running dashboard. Returns (how many, what went wrong).

    WHY THE UPGRADE DOES THIS (reported 2026-08-21)
    ---------------------------------------------
    The dashboard runs out of the engine folder, and an upgrade renames that
    folder underneath it. What survives is a process serving code that no
    longer exists on disk: it answers, it reports the new version number, and
    it hands back the old pages. On the 20th that cost a round trip -- the
    upgrade said 0.20.0 while the browser showed the previous build.

    His instruction: close it first, and say so. Both halves matter. A
    dashboard that vanishes without a word is a dashboard somebody assumes
    has crashed.
    """
    running = dashboard_processes()
    if not running:
        return 0, []

    import psutil

    stopped, problems = 0, []
    for pid, _started in running:
        try:
            process = psutil.Process(pid)
            process.terminate()
            try:
                process.wait(timeout=8)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            stopped += 1
        except psutil.NoSuchProcess:
            stopped += 1                 # it went on its own; same outcome
        except Exception as exc:                          # noqa: BLE001
            problems.append(f"pid {pid}: {type(exc).__name__}: {exc}")
    return stopped, problems


def stray_engine_dirs(beside: Path | None = None) -> list[Path]:
    """Folders named like `engine (2)` sitting next to the real one.

    WHY THIS IS HERE (reported 2026-08-20)
    ------------------------------------
    He opened his config folder and asked the obvious question: *"why so many
    engine folders?"* There were four — `engine (1)` through `engine (4)` —
    each created within a minute of an upgrade, and every one of them
    completely empty: no files, none hidden.

    **What creates them has not been established, and this deliberately does
    not pretend otherwise.** Every upgrade log for those four minutes records
    the swap as successful, and the swap this package performs never invents a
    numbered name — it renames `engine` to `engine.old` and nothing else. They
    stopped appearing after 17:48 that day, which fits something outside this
    code holding the folder open, but that is a hypothesis and not a finding.

    So this does the part that is certain: an empty numbered folder beside the
    engine is litter, whoever dropped it, and clearing litter needs no theory
    of where it came from. A *non*-empty one is left strictly alone and
    reported instead, because at that point the guess about what it is would
    be doing real work — and it might be somebody's own copy.
    """
    home = Path(beside) if beside else engine_dir().parent
    found = []
    try:
        children = list(home.iterdir())
    except OSError:
        return []
    for child in children:
        if not child.is_dir():
            continue
        name = child.name
        if not (name.startswith(engine_dir().name + " (") and name.endswith(")")):
            continue
        if not name[len(engine_dir().name) + 2:-1].isdigit():
            continue
        found.append(child)
    return sorted(found)


def is_empty(folder: Path) -> bool:
    """Nothing inside at all, hidden things included."""
    try:
        return not any(folder.rglob("*"))
    except OSError:                                       # pragma: no cover
        return False


def clear_stray_engines(beside: Path | None = None) -> tuple[int, list[str]]:
    """Delete the empty leftovers. Returns (removed, names left behind).

    Emptiness is checked at the moment of deleting rather than trusted from a
    listing taken earlier: a folder that has gained a file in between is not a
    leftover any more, and this must never be the thing that removes
    somebody's work.
    """
    removed = 0
    kept: list[str] = []
    for folder in stray_engine_dirs(beside):
        if not is_empty(folder):
            kept.append(folder.name)
            continue
        try:
            force_rmtree(folder)
            removed += 1
        except OSError:                                   # pragma: no cover
            kept.append(folder.name)
    return removed, kept


def copy_engine(the_plan: Adoption) -> tuple[bool, str]:
    """Put the copy in place, replacing an older copy if there is one.

    Staged and swapped -- never deleted-then-written. See the note above.
    """
    if the_plan.already:
        return True, "already adopted"

    target = the_plan.target
    staging = target.with_name(target.name + STAGING_SUFFIX)
    previous = target.with_name(target.name + PREVIOUS_SUFFIX)

    # ---- 1. build the replacement, off to one side ------------------------
    try:
        force_rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)

        for name in the_plan.items:
            source_item = the_plan.source / name
            destination = staging / name
            if source_item.is_dir():
                shutil.copytree(source_item, destination, ignore=SKIPPED)
            else:
                shutil.copy2(source_item, destination)
    except OSError as exc:
        force_rmtree(staging)
        # The phase is named. The old message said "could not copy" for an
        # exception thrown by the delete, which sent a reader to the wrong
        # function for half an hour.
        return False, ("could not build the new engine: " + str(exc)
                       + ". Nothing was changed -- the engine you had is "
                         "still in place.")

    # ---- 2. check it before trusting it -----------------------------------
    clear_readonly(staging)
    problems = _verify(staging, the_plan.items)
    if problems:
        force_rmtree(staging)
        return False, ("the new engine was copied but did not check out ("
                       + "; ".join(problems) + "). Nothing was changed -- the "
                       "engine you had is still in place.")

    try:
        (staging / MANIFEST_FILE).write_text(
            "\n".join(the_plan.items) + "\n", encoding="utf-8")
    except OSError:
        pass                    # a missing manifest weakens doctor, not this

    # What this copy looks like the moment it lands, so the NEXT upgrade can
    # tell whether anybody has edited it since. Written into the STAGED copy,
    # never the live one: the record has to travel with the engine it
    # describes, or it describes a program that is no longer there.
    try:
        from . import local_changes
        local_changes.record(staging)
    except Exception:                                     # noqa: BLE001
        pass                    # a missing record loses a warning, not a copy

    # ---- 3. swap ----------------------------------------------------------
    # The only destructive moment, and it is two renames rather than a delete
    # followed by a write. If the second one fails, the first is put back.
    try:
        force_rmtree(previous)
        moved = False
        if target.exists():
            _rename_with_retry(target, previous)
            moved = True
        try:
            _rename_with_retry(staging, target)
        except OSError:
            if moved:
                # Put it back. Not retried with a pause of its own: whatever
                # blocked the second rename would block this one too, and the
                # caller needs the truth quickly rather than another six
                # seconds of hoping.
                previous.rename(target)
            raise
    except OSError as exc:
        force_rmtree(staging)
        return False, ("could not swap the new engine into place: " + str(exc)
                       + ". The engine you had is still in place and nothing "
                         "was lost -- running this again is safe. Something "
                         "is holding that folder open: the dashboard, another "
                         "session, or a file explorer window sitting in it. "
                         "Close those and try once more.")

    clear_readonly(target)
    return True, ("copied the engine to " + str(target) + " (the previous one "
                  "is kept at " + previous.name + " until the next upgrade)")


def rollback(target: Path | None = None) -> tuple[bool, str]:
    """Put the previous engine back.

    Worth having for the same reason the swap is: at the moment somebody needs
    this, the thing that would have told them how to do it by hand is the
    thing that is broken.
    """
    target = Path(target) if target else engine_dir()
    previous = target.with_name(target.name + PREVIOUS_SUFFIX)

    if not previous.exists():
        return False, ("there is no previous engine kept -- nothing to roll "
                       "back to.")
    try:
        broken = target.with_name(target.name + ".failed")
        force_rmtree(broken)
        if target.exists():
            target.rename(broken)
        previous.rename(target)
        force_rmtree(broken)
    except OSError as exc:
        return False, "could not roll back: " + str(exc)

    clear_readonly(target)
    return True, ("rolled back to " + (version_of(target) or "the previous "
                  "version") + ". Run `doctor` to confirm, and reinstall the "
                  "environment if anything looks wrong.")


def reinstall(target: Path, extras: str = "full") -> tuple[bool, str]:
    """Point the virtual environment at the copy instead of the original."""
    python = venv_python()
    if python is None:
        return False, ("no virtual environment was found, so the copy is in "
                       "place but nothing is using it yet. Start the "
                       "assistant once with its launcher and run this again.")

    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "utf-8"
    # Without this the editable install can be satisfied from the old path
    # that is still on PYTHONPATH -- which is exactly the wire being cut.
    environment.pop("PYTHONPATH", None)

    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet",
         "-e", f"{target}[{extras}]"],
        capture_output=True, text=True, check=False, env=environment,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return False, ("the copy is in place, but reinstalling the "
                       "environment failed: "
                       + (detail[-1] if detail else "no reason given"))

    return True, "the environment now uses the copy"


# ---------------------------------------------------------------------------
# Finding the new version
# ---------------------------------------------------------------------------

RELEASE_GLOB = "Aki-Agent-Beta-*"


def looks_like_the_package(folder: Path) -> bool:
    """Is this really a copy of this package, rather than any old folder?

    Checked before anything is copied over a working install. The cost of
    being wrong here is an assistant that will not start, so the test is on
    the two files that must exist and cannot be coincidence.
    """
    folder = Path(folder)
    return ((folder / "src" / "aki_agent" / "__init__.py").is_file()
            and (folder / "bin" / "_bootstrap.py").is_file())


def version_of(folder: Path) -> str:
    """The version a copy of the package declares, or "" if it will not say."""
    marker = Path(folder) / "src" / "aki_agent" / "__init__.py"
    try:
        for line in marker.read_text(encoding="utf-8",
                                     errors="replace").splitlines():
            if line.startswith("__version__"):
                return line.split("=", 1)[1].strip().strip('"\'')
    except OSError:
        pass
    return ""


def _default_source() -> Path | None:
    """What to upgrade from when nobody said.

    The copy running now comes first. Running `<new release>/bin/_bootstrap.py`
    -- which is exactly what the instructions say to do -- means the new code
    is already what is executing, so it can simply name itself. Only when the
    running copy IS the installed engine (nothing new about it) does this fall
    back to looking around the disk.
    """
    running = running_from()
    try:
        installed = running.resolve() == engine_dir().resolve()
    except OSError:                                       # pragma: no cover
        installed = False

    if not installed and looks_like_the_package(running):
        return running
    return newest_release_nearby()


def newest_release_nearby() -> Path | None:
    """The most recent release zip or unpacked folder a person is likely to have.

    Downloads first, because that is where a downloaded zip lands and asking
    someone to type a path is most of what made the old instructions feel
    complicated. The current folder second, for anyone who unzipped beside
    their assistant.
    """
    here = Path.cwd()
    # The folder somebody is standing in, before anything inside it. Unzipping
    # a release and stepping into it is the obvious thing to do, and it was
    # the one case the old search could not see.
    if looks_like_the_package(here) and here.resolve() != engine_dir().resolve():
        return here

    # Downloads first, then the other three places a downloaded file actually
    # ends up. The maintainer's own copy arrives over Telegram and gets saved into
    # `Documents\aki-agent\`, which the first version of this list could not
    # see -- so the software said "I cannot find a release" while one sat on
    # the disk, and the answer was to type a path, which is most of what made
    # the old instructions feel like work.
    looked_in = (paths.home() / "Downloads", paths.home() / "Documents",
                 paths.home() / "Desktop", here)
    candidates: list[Path] = []
    for where in looked_in:
        try:
            # One level down as well as at the top: people put the zip in a
            # folder named after the thing, which is tidy and invisible to a
            # flat glob.
            candidates += [p for p in where.glob(RELEASE_GLOB)
                           if p.suffix.lower() == ".zip"
                           or (p.is_dir() and looks_like_the_package(p))]
            candidates += [p for p in where.glob("*/" + RELEASE_GLOB)
                           if p.suffix.lower() == ".zip"
                           or (p.is_dir() and looks_like_the_package(p))]
        except OSError:                                   # pragma: no cover
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def unpack(archive: Path, into: Path) -> tuple[Path | None, str]:
    """Extract a release zip and return the folder holding the package.

    A release zip carries one top-level folder, so the package is one level
    down -- but that is a convention of this project's own build script, not a
    guarantee about a file somebody hands us, so the answer is searched for
    rather than assumed.
    """
    into = Path(into)
    try:
        # `force_rmtree`, not `shutil.rmtree`. The ReadOnly fix was applied to
        # `copy_engine` on 2026-08-20 and this call was left behind -- so the
        # exact failure that destroyed an install twice was still sitting in
        # the *other* path into the same feature, waiting for the second time
        # somebody upgraded from a zip.
        #
        # That is the lesson from `specialists._safe_key`, which this codebase
        # already wrote down once: a fix applied to an instance is not applied
        # to the class. Worth grepping for the pattern, not just the caller.
        force_rmtree(into)
        into.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as opened:
            opened.extractall(into)
    except (OSError, zipfile.BadZipFile) as exc:
        return None, f"could not unpack {archive.name}: {exc}"

    if looks_like_the_package(into):
        return into, ""
    for child in sorted(into.iterdir()):
        if child.is_dir() and looks_like_the_package(child):
            return child, ""
    return None, (f"{archive.name} does not contain this package -- no "
                  "src/aki_agent inside it.")


def source_for_upgrade(given: str | Path | None,
                       workspace: Path | None = None,
                       allow_unsigned: bool = False
                       ) -> tuple[Path | None, str]:
    """Resolve what to upgrade from, unpacking a zip if that is what it is.

    Returns (folder holding the new package, message). The message is filled
    in on failure and names what to do about it, because the person running
    this is upgrading, not debugging.

    THE SIGNATURE CHECK LIVES HERE, NOT IN THE CALLERS
    --------------------------------------------------
    Three things upgrade: the CLI, the dashboard's button, and the upgrade
    skill. Putting the check in each would mean three places to forget it,
    and this codebase has already written down what that costs -- the
    ReadOnly fix that was applied to `copy_engine` and not to `unpack`, one
    feature, two paths, one of them still broken. Every route to an upgrade
    passes through this function, so the gate is here.

    `allow_unsigned` is the caller saying a person has been shown what could
    not be verified and said yes anyway. It is never a default.
    """
    chosen = Path(given) if given else _default_source()
    if chosen is None:
        return None, ("I could not find a release to upgrade from. I looked "
                      "at the copy I am running from, at this folder, and in "
                      "your Downloads, Documents and Desktop. Run this again "
                      "with the path -- and point it straight at the zip, "
                      "there is no need to unpack anything first:  "
                      "upgrade --from "
                      "~/Downloads/Aki-Agent-Beta-20260820-006.zip")

    chosen = chosen.expanduser()
    if not chosen.exists():
        return None, f"{chosen} is not there."

    if chosen.is_file():
        # `_incoming`, not `_upgrade`. The two were the same folder until
        # 2026-08-20, and the unpack path deletes it when it is finished --
        # which would have taken the upgrade logs with it the moment they
        # started being written. A scratch folder and a record of what
        # happened have opposite lifetimes and must not share a name.
        staging = (workspace or engine_dir().parent) / UNPACK_DIR_NAME
        unpacked, problem = unpack(chosen, staging)
        if unpacked is None:
            return None, problem
        return _if_trusted(unpacked, chosen, allow_unsigned)

    if not looks_like_the_package(chosen):
        return None, (f"{chosen} does not look like this package -- there is "
                      "no src/aki_agent inside it.")
    return _if_trusted(chosen, chosen, allow_unsigned)


def _if_trusted(unpacked: Path, source: Path,
                allow_unsigned: bool) -> tuple[Path | None, str]:
    """Let this through only if it is signed, or the person insisted.

    Refusing is the whole feature, so the refusal has to be usable: it says
    what was wrong, names the file and its fingerprint so they can check it
    against wherever they got it, and gives them the one flag that proceeds
    anyway. A wall with no door gets climbed by turning the check off.
    """
    from . import release_trust

    verdict = release_trust.verify_package(unpacked)
    if verdict.trusted:
        return unpacked, ""
    if allow_unsigned:
        return unpacked, ""

    verdict.fingerprint = (release_trust.fingerprint(source)
                           if source.is_file() else "")
    lines = [
        f"I will not install this: {verdict.problem}.",
        "",
        *release_trust.describe(source, verdict),
        "",
        "An upgrade replaces the code that reads your email, your files and",
        "your calendar, so it has to be code you meant to install. Anything",
        "named Aki-Agent-Beta-* that lands in Downloads gets picked up here,",
        "which is why this is not waved through.",
        "",
        "If you know where this came from and want it anyway:",
        f"    aki upgrade --from {source} --allow-unsigned",
    ]
    return None, "\n".join(lines)


# ---------------------------------------------------------------------------
# The other half: the Claude Code plugin
# ---------------------------------------------------------------------------

MARKETPLACE_NAME = "aki-agent"
PLUGIN_ID = "aki-agent@aki-agent"


def _claude(arguments: list[str]) -> tuple[bool, str]:
    """Run one `claude` sub-command, resolved properly.

    Never a bare "claude": on Windows it is a .CMD shim and CreateProcess does
    not apply PATHEXT, so the bare name raises WinError 2 while the same word
    works in the shell. That cost this package a silently broken uninstall.
    """
    from . import runner

    try:
        executable = runner.find_claude()
    except runner.ClaudeNotFound as exc:
        return False, str(exc)

    try:
        done = subprocess.run([executable, *arguments], capture_output=True,
                              text=True, timeout=180, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not run claude {' '.join(arguments)}: {exc}"

    output = (done.stdout or done.stderr or "").strip()
    return done.returncode == 0, output[:300]


def refresh_plugin(engine_folder: Path) -> list[str]:
    """Point Claude Code at the adopted engine and reinstall the plugin.

    Returns a line per step, for printing. Deliberately tolerant: removing a
    marketplace that is not there, or installing one that is already current,
    are both fine and must not stop the rest.
    """
    lines: list[str] = []

    # Removing first is what makes this an update rather than a second entry:
    # `marketplace update` re-reads the OLD path, which is the folder being
    # replaced, so it would faithfully reinstall the version being upgraded
    # away from.
    ok, message = _claude(["plugin", "marketplace", "remove", MARKETPLACE_NAME])
    lines.append(f"  {'ok' if ok else 'note'} - old marketplace entry: "
                 f"{message or 'removed'}")

    ok, message = _claude(["plugin", "marketplace", "add", str(engine_folder)])
    lines.append(f"  {'ok' if ok else 'FAILED'} - marketplace now points at "
                 f"{engine_folder}")
    if not ok:
        lines.append(f"       {message}")
        return lines

    ok, message = _claude(["plugin", "install", PLUGIN_ID])
    lines.append(f"  {'ok' if ok else 'FAILED'} - plugin: "
                 f"{message or 'installed'}")
    return lines
