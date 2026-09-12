"""`doctor` -- tells the user what is wrong, in words they can act on.

WHY THIS FILE EXISTS
--------------------
The audience for this package does not read stack traces. A traceback is not
an error message; it is a request that the reader do the diagnosis themselves.

So every check in this file answers three questions:

    What is wrong?      one sentence, no jargon
    Why does it matter? what will not work until it is fixed
    What do I do now?   a specific next action, copy-pasteable

THE HARD CONSTRAINT ON THIS FILE
--------------------------------
It must run when NOTHING is installed. That is the whole point -- it is what
you run when the install failed. So:

    * standard library only, at module level
    * every optional dependency imported inside a function, in a try/except
    * no import of the rest of this package at module level either

If you add `import yaml` to the top of this file, you have broken the one
thing it is for.

Run it as:  python -m aki_agent.doctor
"""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# The minimum Python this package is tested against. 3.10 is the floor because
# the code uses `X | None` type syntax throughout.
MINIMUM_PYTHON = (3, 10)

# Packages the software genuinely imports, with the plain-language reason.
#
# INHERITED DEFECT BEING FIXED HERE: the source system's dependency manifest
# declared three packages while its dashboard imported at least nine. A new
# user's very first install command therefore failed. The fix is not just a
# longer list -- it is this check, which tells the user which ones are missing
# and exactly what to type.
REQUIRED_PACKAGES = {
    "yaml": ("PyYAML", "reading your configuration file"),
}

OPTIONAL_PACKAGES = {
    "keyring": ("keyring", "storing secrets in your operating system's "
                           "password manager"),
    "flask": ("Flask", "showing the dashboard in your browser"),
    "psutil": ("psutil", "checking whether the assistant is running, and "
                         "whether a restart actually worked"),
    "telethon": ("Telethon", "the dashboard's chat box — without it the panel "
                             "keeps its own list instead of showing your real "
                             "Telegram conversation"),
}


@dataclass
class Check:
    """One diagnosis."""

    name: str
    ok: bool
    detail: str = ""
    fix: str = ""
    # A failed check that is not fatal -- the software still runs, but
    # something is unavailable. Rendered differently so the user can tell the
    # difference between "broken" and "not set up yet".
    warning_only: bool = False

    @property
    def symbol(self) -> str:
        if self.ok:
            return "OK  "
        return "note" if self.warning_only else "FAIL"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _run(module: str, arguments: str) -> str:
    """A fix line the reader can paste and have work.

    These are copy-pasted by a person looking at a broken install, so
    `python -m aki_agent.…` is exactly wrong: the package lives in the
    assistant's virtual environment and their shell's `python` is not that
    interpreter. Same defect as the scheduled task that silently collected
    nothing for months -- found 2026-08-20, fixed in every generated command
    rather than only in the one that was noticed.
    """
    from . import engine

    return engine.how_to_run(module, arguments)


def check_python() -> Check:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info >= MINIMUM_PYTHON:
        return Check("Python version", True, f"Python {version}")

    wanted = ".".join(str(part) for part in MINIMUM_PYTHON)
    return Check(
        "Python version", False,
        detail=f"You have Python {version}, which is older than {wanted}.",
        fix=("Install a current Python from https://www.python.org/downloads/ "
             "and tick 'Add Python to PATH' during setup."),
    )


def check_packages() -> list[Check]:
    checks: list[Check] = []

    for module_name, (package_name, reason) in REQUIRED_PACKAGES.items():
        try:
            importlib.import_module(module_name)
            checks.append(Check(f"Package: {package_name}", True))
        except ImportError:
            checks.append(Check(
                f"Package: {package_name}", False,
                detail=f"Not installed. It is needed for {reason}.",
                fix=f'Run:  {_pip_hint()} install "{package_name}"',
            ))

    for module_name, (package_name, reason) in OPTIONAL_PACKAGES.items():
        try:
            importlib.import_module(module_name)
            checks.append(Check(f"Package: {package_name}", True))
        except ImportError:
            checks.append(Check(
                f"Package: {package_name}", False, warning_only=True,
                detail=f"Not installed. Without it, {reason} will not work.",
                fix=f'Run:  {_pip_hint()} install "{package_name}"',
            ))

    return checks


def _pip_hint() -> str:
    """The pip command that matches the Python actually running this.

    Using `python -m pip` rather than a bare `pip` matters: a user with two
    Pythons installed will otherwise install into the wrong one and be told,
    confusingly, that the package they just installed is missing.
    """
    return f'"{sys.executable}" -m pip'


def check_app_dir() -> Check:
    from . import paths

    directory = paths.app_dir()
    if directory.exists():
        return Check("Personal folder", True, detail=str(directory))
    return Check(
        "Personal folder", False, warning_only=True,
        detail=f"Not created yet: {directory}",
        fix="This is created during setup. In Claude Code, type /aki-agent:setup.",
    )


def check_config() -> tuple[Check, object | None]:
    """Load the config, and report on it. Returns the config if it loaded."""
    from . import paths

    config_path = paths.config_file()
    if not config_path.exists():
        # "Not set up" and "set up, on a drive that has not arrived yet" look
        # identical from here, and the advice for them is opposite.
        #
        # A pointer naming a folder that is not present is what a synced drive
        # looks like at login -- Google Drive, OneDrive and iCloud all mount
        # some seconds after sign-in, and the login-triggered tasks fire
        # immediately. Telling that student to run setup would have them
        # overwrite a configuration that is on its way, and setup over an
        # existing config is the one act INSTALL.md calls impossible to undo.
        promised = paths.pointer_says()
        if promised is not None and not promised.is_dir():
            return (
                Check("Configuration", False,
                      detail=(f"Your assistant's folder is not there right "
                              f"now: {promised}"),
                      fix=("If that folder is on Google Drive, OneDrive or "
                           "iCloud, it has probably not finished syncing "
                           "yet — wait a minute and run this again. "
                           "**Do not run setup**: that would start a new "
                           "assistant over the top of the one you have. If "
                           "you moved the folder on purpose, run "
                           "`aki repair` and point it at the new place.")),
                None,
            )

        return (
            Check("Configuration", False,
                  detail="No configuration file yet.",
                  fix="In Claude Code, type /aki-agent:setup to answer the "
                      "questions."),
            None,
        )

    try:
        from . import config as config_module
        loaded = config_module.load()
    except ImportError:
        return (
            Check("Configuration", False,
                  detail="Cannot read the configuration because PyYAML is "
                         "not installed.",
                  fix=f'Run:  {_pip_hint()} install "PyYAML"'),
            None,
        )
    except Exception as exc:  # noqa: BLE001 -- doctor must never crash
        # A broad catch is correct in exactly one place, and this is it: the
        # tool whose job is to explain failures must not itself fail.
        return (
            Check("Configuration", False,
                  detail=f"The configuration file could not be read: {exc}",
                  fix=f"Open {config_path} and check it, or run /aki-agent:setup again "
                      "to rewrite it."),
            None,
        )

    problems = loaded.validate()
    if problems:
        return (
            Check("Configuration", False,
                  detail="Loaded, but with problems:\n    - "
                         + "\n    - ".join(problems),
                  fix="In Claude Code, type /aki-agent:setup to answer those questions "
                      "again."),
            loaded,
        )

    return (
        Check("Configuration", True,
              detail=f"{loaded.assistant.name} is set up for "
                     f"{loaded.user.name}."),
        loaded,
    )


def check_workspace(loaded) -> Check:
    if loaded is None:
        return Check("Workspace folder", False, warning_only=True,
                     detail="Cannot check without a configuration.")

    root: Path | None = loaded.layout.root
    if root is None:
        return Check("Workspace folder", False,
                     detail="No workspace folder is set.",
                     fix="Run /aki-agent:setup and choose the folder your work is in.")

    if root.exists():
        count = len(loaded.layout.item_dirs())
        label = loaded.layout.schema.item_label_plural.lower()
        missing = loaded.layout.unmatched_workspaces()
        renamed = loaded.layout.renamed_workspaces()

        # A configured workspace that names no folder is the reason a dashboard
        # comes up blank on a workspace that looks perfectly correct in
        # Explorer. It has to be a failure here, not a note, because "0
        # projects found" reported as a tick is what let it stand.
        if missing:
            present = sorted(child.name for child in root.iterdir()
                             if child.is_dir()
                             and not child.name.startswith("."))
            return Check(
                "Workspace folder", False,
                detail=(f"No folder for {', '.join(missing)} in {root}.\n"
                        f"    Folders there: {', '.join(present) or 'none'}"),
                fix=("The workspace names in your settings must match the folder "
                     "names exactly, prefix included. Open the dashboard's "
                     "Settings page, or run /aki-agent:setup again."),
            )

        if renamed:
            pairs = ", ".join(f"{workspace} -> {folder}" for workspace, folder in renamed)
            return Check(
                "Workspace folder", False, warning_only=True,
                detail=(f"{count} {label} found in {root}, but the settings "
                        f"and the folders disagree: {pairs}"),
                fix="Rename in Settings so both say the same thing.",
            )

        if count == 0:
            return Check(
                "Workspace folder", False, warning_only=True,
                detail=f"No {label} found in {root}",
                fix=("Each one is a folder"
                     + (" inside an workspace folder"
                        if loaded.layout.workspaces else "")
                     + f" in {root}. Ask me to make one, or say "
                       "\"new project\"."),
            )

        return Check("Workspace folder", True,
                     detail=f"{count} {label} found in {root}")

    return Check(
        "Workspace folder", False,
        detail=f"Not available right now:\n    {root}",
        fix=("If this folder is on Google Drive, OneDrive, iCloud or Dropbox, "
             "wait for it to finish starting up and try again. If you have "
             "moved it, run /aki-agent:setup again."),
    )


def check_external_tools(features: tuple[str, ...]) -> list[Check]:
    """Check the outside programs needed for the features actually in use.

    Only checks what is relevant. Warning somebody about a missing messaging
    runtime when they never asked for messaging trains them to ignore
    warnings, and then they ignore the one that mattered.
    """
    from . import dependencies

    checks: list[Check] = []
    for status in dependencies.detect_all(features):
        tool = status.tool
        name = tool.display_name

        if status.present:
            checks.append(Check(name, True,
                                detail=status.version_text or status.found_at))
            continue

        if status.too_old:
            wanted = ".".join(str(part) for part in tool.minimum_version)
            checks.append(Check(
                name, False, warning_only=not tool.essential,
                detail=f"Found {status.version_text}, but {wanted} or newer "
                       "is needed.",
                fix=dependencies.describe_install(tool),
            ))
            continue

        checks.append(Check(
            name, False, warning_only=not tool.essential,
            detail=f"Not installed. It {tool.why}.",
            fix=dependencies.describe_install(tool),
        ))

    return checks


def features_in_use(loaded) -> tuple[str, ...]:
    """Which parts of the package this installation actually uses.

    Read from the user's config rather than assumed, so the health check is
    about their setup and not about a hypothetical full one.
    """
    features = ["core"]
    if loaded is not None and getattr(loaded, "notifications", None):
        if loaded.notifications.channels:
            features.append("messaging")
    return tuple(features)


def check_credential_store() -> Check:
    """Can we actually reach the OS password manager?

    Importing `keyring` is not the same as it working -- on a headless or
    locked-down machine the backend can be missing. So this asks the backend
    to identify itself rather than assuming.
    """
    try:
        import keyring
    except ImportError:
        return Check("Password manager", False, warning_only=True,
                     detail="The `keyring` package is not installed.",
                     fix=f'Run:  {_pip_hint()} install "keyring"')

    try:
        backend = keyring.get_keyring()
        name = type(backend).__name__
        if "fail" in name.lower():
            return Check(
                "Password manager", False, warning_only=True,
                detail="No working password manager was found on this "
                       "machine.",
                fix="Secrets will have to be stored in a file instead. Tell "
                    "whoever is supporting you -- this is unusual.",
            )
        return Check("Password manager", True, detail=name)
    except Exception as exc:  # noqa: BLE001 -- see check_config
        return Check("Password manager", False, warning_only=True,
                     detail=f"Could not be reached: {exc}")


# ---------------------------------------------------------------------------
# Running the lot
# ---------------------------------------------------------------------------

def check_schedule() -> Check:
    """Is any of the automatic work actually scheduled?

    THE CHECK THAT WOULD HAVE CAUGHT IT. Doctor knew whether Flask could be
    imported — the dashboard's dependency — but never whether a single task
    was installed. So an install where nothing automatic ran at all reported a
    clean bill of health, because every mechanism was present. Absence of
    triggering is the failure this package keeps producing; this is the check
    that names it.
    """
    from . import schedule

    try:
        installed = schedule.installed_names()
    except Exception as problem:            # a missing schtasks, a locked plist
        return Check("Scheduled work", False, warning_only=True,
                     detail=f"could not be read: {problem}",
                     fix="Open the dashboard's schedule page to see the list.")

    defined = [task for task in schedule.all_tasks() if task.enabled]
    if not installed:
        return Check(
            "Scheduled work", False, warning_only=True,
            detail=f"nothing installed, {len(defined)} defined — so no "
                   "morning summary, no evening write-up, and nothing saves "
                   "what you are in the middle of",
            fix=_run("aki_agent.cli", "schedule-install --yes"))

    missing = [task for task in defined
               if not schedule.is_installed(task, installed)]
    if missing:
        # False, not True (2026-08-23).
        #
        # This returned ok=True while naming the tasks that were missing, so
        # five of six could be gone and the line still read `[OK ]`. Combined
        # with every check here being warning_only, the report's summary line
        # said "Everything essential is working" to somebody whose automation
        # had entirely stopped, and `main()` exited 0.
        #
        # A check that lists what is broken and then reports itself as passing
        # is worse than no check: it is the thing a worried person opens
        # first, and it sends them away.
        names = ", ".join(one.title for one in missing[:3])
        more = f" and {len(missing) - 3} more" if len(missing) > 3 else ""
        # Not warning_only. Some tasks installed and some gone is a broken
        # state, not an unfinished one — the difference from the branch above,
        # where nothing is installed because setup has not run yet.
        return Check(
            "Scheduled work", False,
            detail=f"{len(installed)} installed, {len(missing)} missing "
                   f"({names}{more}) — that work is not happening",
            fix=_run("aki_agent.cli", "schedule-install --yes"))
    return Check("Scheduled work", True, detail=f"{len(installed)} installed")


def check_after_update() -> Check:
    """Does the schedule still point at the copy of the package running now?

    THE FAILURE THIS EXISTS TO CATCH
    --------------------------------
    A scheduled task stores an absolute path to the runner script inside the
    package. Installed as a plugin, the package lives in a folder named after
    its version — so the next release lands somewhere new and every task
    installed by the previous one still points at the old folder. Once that is
    cleaned up they all fail on every firing, silently.

    An update that quietly disables the automation is worse than an update
    that fails loudly, because the user has no reason to look.
    """
    from . import schedule

    current, was = schedule.install_root_is_current()
    if current:
        return Check("Still pointing at this version", True)
    return Check(
        "Still pointing at this version", False, warning_only=True,
        detail=("the scheduled work was set up against an older copy of the "
                f"package ({was}), so it may no longer run"),
        fix=_run("aki_agent.cli", "repair --yes"))


def check_engine() -> Check:
    """Does anything still point at the folder the package was unzipped in?

    THE FAILURE THIS EXISTS TO CATCH (reported 2026-08-19)
    ----------------------------------------------------
    An install that is finished should not need its installer any more. This
    one did, in three places that each announced nothing: an editable install
    whose `.pth` named the unzipped folder, scheduled tasks calling a runner
    inside it, and a launcher naming its bootstrap. Deleting the folder — the
    obvious thing to do with a spent installer — broke every one of them.

    So the check is the user's own question, and a failure names the command
    that fixes it rather than describing the problem.
    """
    from . import engine, launcher, paths, schedule

    inside = paths.app_dir().resolve()
    outside: list[str] = []

    try:
        running = engine.running_from().resolve()
        if inside not in running.parents and running != inside:
            outside.append(f"the engine itself ({running})")
    except OSError:                                       # pragma: no cover
        pass

    launcher_file = launcher.launcher_path()
    if launcher_file.exists():
        text = launcher_file.read_text(encoding="utf-8", errors="replace")
        if str(inside) not in text and "_bootstrap.py" in text:
            outside.append(f"the launcher ({launcher_file.name})")

    current, was = schedule.install_root_is_current()
    if not current:
        outside.append(f"the scheduled tasks ({was})")

    if not outside:
        return Check("Everything runs from your own folder", True,
                     detail="the folder you installed from can be deleted")

    return Check(
        "Everything runs from your own folder", False, warning_only=True,
        detail=("these still point somewhere else, so deleting the folder "
                "you installed from would break them: "
                + "; ".join(outside)),
        fix=_run("aki_agent.cli", "adopt-engine --yes"))


def check_handoff() -> Check:
    """Has anything ever written the working state?

    A checkpoint that has never run is indistinguishable from a healthy one
    until the day something crashes, which is the worst moment to find out.
    """
    from . import memory

    state = memory.read_working_state()
    if state is None:
        return Check(
            "Handoff between sessions", False, warning_only=True,
            detail="never written — a restart would lose the thread",
            fix=_run("aki_agent.cli", "checkpoint"))
    if state.is_stale:
        return Check(
            "Handoff between sessions", False, warning_only=True,
            detail=f"last saved {state.generated_at:%Y-%m-%d %H:%M}, which is "
                   "old enough that the checkpoint is probably not running",
            fix=_run("aki_agent.cli", "schedule-status"))
    return Check("Handoff between sessions", True,
                 detail=f"saved {state.generated_at:%Y-%m-%d %H:%M}")


def check_workspace_notes(loaded) -> Check:
    """Is there a CLAUDE.md where the assistant will actually read it?

    It goes in the workspace folder, not in `~/.aki-agent` -- the launcher
    starts the session in the workspace, and Claude Code reads the CLAUDE.md
    of the folder it starts in. An install whose scaffold was skipped has no
    such file, so nothing tells a new session to read the handoff first, and
    the symptom is only that the assistant seems to have forgotten everything.
    """
    if loaded is None or loaded.layout.root is None:
        return Check("Session notes (CLAUDE.md)", False, warning_only=True,
                     detail="Cannot check without a workspace folder.")

    root = loaded.layout.root
    notes = root / "CLAUDE.md"
    if notes.exists():
        # Present is not the same as current.
        #
        # An upgrade is performed by the engine it is replacing, so a top-up
        # taught about a new section only applies from the *following*
        # upgrade. Between the two, the file exists, this check passed, and
        # the assistant was never told to read the house rules -- a page
        # saving into a file nothing read. So: check the contents, not the
        # existence.
        from . import scaffold as scaffold_module

        try:
            text = notes.read_text(encoding="utf-8", errors="replace")
        except OSError:                                   # pragma: no cover
            text = ""
        # By anchor, so "present" means "the current version is present".
        # Detecting by a phrase inside the block could only ever answer "is
        # something like this here", which is not the question an upgrade has.
        missing = [one.name for one in scaffold_module.sections()
                   if one.find_in(text) is None
                   or one.find_in(text) and
                   text[slice(*one.find_in(text))].strip() != one.body.strip()]
        if missing:
            return Check(
                "Session notes (CLAUDE.md)", False, warning_only=True,
                detail=f"{len(missing)} instruction block(s) missing or "
                       "out of date, so part of what the assistant reads at "
                       "the start of a session is wrong or absent: "
                       + ", ".join(missing),
                fix=_run("aki_agent.cli", "repair --yes"))
        return Check("Session notes (CLAUDE.md)", True, detail=str(notes))

    return Check(
        "Session notes (CLAUDE.md)", False, warning_only=True,
        detail=f"none in {root}",
        fix=("Ask me to write one. It is the file that tells every new "
             "session to read the handoff and to leave your documents alone."),
    )


def check_draft_check() -> Check:
    """Is the built-in checker on?

    Reported as a plain fact rather than a fault, because off is a legitimate
    choice somebody made. What is not legitimate is *not knowing* — an
    assistant that stopped verifying drafts and never mentioned it looks
    exactly like one that is verifying them and finding nothing wrong.
    """
    from . import sentinel

    if sentinel.is_on():
        return Check("Drafts are checked before they go out", True,
                     detail="sources, evidence, wording, privacy")
    return Check(
        "Drafts are checked before they go out", False, warning_only=True,
        detail="off — nothing is verified unless you ask for it",
        fix=_run("aki_agent.cli", "sentinel on"))


def check_workspace_names(loaded) -> Check:
    """Do two configured workspace names claim the same folder?

    Found on a real install (2026-08-20): every project appeared twice in the
    handoff, in both lists, and nothing anywhere errored. The duplicate is
    prevented now, but a config that says something the user did not mean is
    still a config worth fixing, and this is where somebody would look.
    """
    if loaded is None or loaded.layout.root is None:
        return Check("Workspace names", True,
                     detail="nothing configured to check")

    clashes = loaded.layout.colliding_workspaces()
    if not clashes:
        return Check("Workspace names", True, detail="each one is distinct")

    said = "; ".join(" and ".join(repr(name) for name in group)
                     for group in clashes)
    return Check(
        "Workspace names", False, warning_only=True,
        detail=f"these name the same folder: {said}. Only one of each pair is "
               "read, so nothing is lost or shown twice -- but the config says "
               "something you probably did not mean.",
        fix="Open Settings and remove or rename the duplicate.",
    )


def check_credential_store_reachable() -> Check:
    """Can the password store actually be read from where this is running?

    Distinct from "is there a store at all". A machine can have a perfectly
    good Credential Manager that this process cannot reach, because Windows
    ties it to an interactive logon — so a scheduled task or a remote session
    finds every saved password missing and nothing says why. `get_secret`
    deliberately answers None in that case; this is the one place that
    explains it.
    """
    from . import secrets as secrets_module

    problem = secrets_module.store_unavailable()
    if not problem:
        return Check("Saved passwords are reachable", True)

    return Check(
        "Saved passwords are reachable", False, warning_only=True,
        detail=problem + " Anything that needs a saved password — email, the "
                         "dashboard's chat box, paid services — will behave "
                         "as though nothing was ever saved.",
        fix="Run this from your own desktop session rather than remotely.",
    )


def check_keys_are_not_split_between_two_stores() -> Check:
    """Keys sitting in the file fallback while this process uses the keyring.

    The two halves of this package can disagree about where secrets live. The
    dashboard runs from the engine's environment; a session runs from whichever
    Python started it. One imports `keyring` and writes to the password
    manager, the other does not and writes a file. Both report success, and
    every later question about the key is answered "no key".

    `get_secret` now reads both, so this is no longer a failure -- but it is
    still worth saying, because half the user's keys are then in a file rather
    than in their password manager, which is not what they were told when they
    saved them.
    """
    from . import secrets as secrets_module

    if not secrets_module.using_os_store():
        # This process has no keyring, so the file IS the store here. That is
        # the documented fallback and `fallback_warning` already says it.
        return Check("Saved passwords are all in one place", True)

    try:
        stray = sorted(secrets_module._read_fallback().keys())
    except Exception:                                     # noqa: BLE001
        stray = []
    if not stray:
        return Check("Saved passwords are all in one place", True)

    return Check(
        "Saved passwords are all in one place", False, warning_only=True,
        detail=(f"{len(stray)} secret(s) are in the file store while this "
                "session uses your password manager, so they were written by "
                "a part of the assistant running a different Python. They are "
                "still found and used; they are simply less well protected "
                "than the ones in the password manager."),
        fix=("Re-enter those on the dashboard's API keys page from this "
             "machine, and they will move into the password manager."),
    )


def check_which_brain() -> Check:
    """Say which model this install talks to, and whether it still can.

    Not a fault to report -- a fact somebody needs when their assistant
    behaves differently from the one in the class. Somebody running a local
    model gets slower, less reliable multi-step work, and without this the
    only symptom is an assistant that seems worse for no reason.
    """
    from . import backend as backend_module

    recorded = backend_module.stored()
    running = backend_module.detect()

    if recorded.is_default and running.is_default:
        return Check("Which model it uses", True,
                     detail="Claude Code, signed in as you")

    if recorded.is_default and not running.is_default:
        # They set one up after installing, so nothing background knows.
        return Check(
            "Which model it uses", False, warning_only=True,
            detail=(f"this session is using {running.sentence()}, but the "
                    "launcher and the scheduled tasks were set up before "
                    "that and still expect the default"),
            fix=_run("aki_agent.cli", "make-launcher --yes"))

    detail = recorded.sentence()
    if recorded.needs_token:
        detail += " (its token comes from your environment, not from a file)"
    if not recorded.is_default:
        detail += " -- scheduled work is slower and less reliable on a local model"
    return Check("Which model it uses", True, detail=detail)


def check_launcher() -> Check:
    """Is there a file to double-click, and can the machine actually run it?

    THE TWO FAILURES THIS EXISTS FOR
    ---------------------------------
    A real macOS install finished setup, started the assistant, and got a
    Claude Code session with no dashboard. Two separate causes, and `doctor`
    passed both.

    First, `~/.aki-agent/start-assistant.command` had never been written. The
    last step of setup had not run, nothing said so, and every other check
    here is about the *contents* of a launcher -- `check_engine` reads one
    only `if launcher_file.exists()`, and `_repoint` rewrites one on the same
    condition. A missing launcher was therefore not a fault anything could
    report; it was a file nothing had an opinion about.

    Second, `bin/dashboard.command` had arrived at 0o644. The launcher starts
    it in the background, so the permission denial went to a job nobody reads.
    A dashboard that never appears, and no error anywhere.

    Both are invisible on purpose here: they are exactly the kind of fault a
    person cannot report, because from where they sit nothing happened.
    """
    from . import engine, launcher, paths

    launcher_file = launcher.launcher_path()
    if not launcher_file.exists():
        return Check(
            "The file you double-click", False,
            detail=(f"there is no {launcher_file.name} in "
                    f"{paths.app_dir()} -- setup either did not finish or "
                    "was interrupted before its last step"),
            fix=_run("aki_agent.cli",
                     "make-launcher --dashboard --yes"))

    text = launcher_file.read_text(encoding="utf-8", errors="replace")
    opens_dashboard = "dashboard." in text

    if paths.is_windows():
        detail = str(launcher_file)
        if not opens_dashboard:
            detail += " (it does not open the dashboard)"
        return Check("The file you double-click", True, detail=detail)

    # macOS: a script without its executable bit is a script that cannot run,
    # and Finder says so in a dialog that names no cause.
    unrunnable: list[str] = []
    if not os.access(launcher_file, os.X_OK):
        unrunnable.append(launcher_file.name)
    if opens_dashboard:
        dashboard = engine.running_from() / "bin" / "dashboard.command"
        if dashboard.exists() and not os.access(dashboard, os.X_OK):
            unrunnable.append("bin/dashboard.command")

    if unrunnable:
        return Check(
            "The file you double-click", False,
            detail=("these have lost permission to run, so double-clicking "
                    "does nothing or fails silently: "
                    + ", ".join(unrunnable)),
            fix=_run("aki_agent.cli", "repair --yes"))

    detail = str(launcher_file)
    if not opens_dashboard:
        detail += " (it does not open the dashboard)"
    return Check("The file you double-click", True, detail=detail)


def check_scheduling_can_reach_the_workspace(loaded) -> Check:
    """On macOS, can a scheduled task actually read the workspace?

    THE FAILURE (2026-09-11)
    -------------------------
    A one-off job fired exactly on time and died with exit 126: macOS would
    not let a process started by launchd read a script inside `Documents`.
    Not a bug in the job, the schedule or the script -- TCC, doing its job,
    to a process with no Full Disk Access.

    Which means a workspace in `Documents`, `Desktop` or `Downloads` gives
    somebody scheduled tasks that install cleanly, report success, and then
    fail every time they run, for ever, saying nothing. `doctor` is the only
    place that can say this before the user finds out by noticing that their
    morning summary never came.

    A warning, not a failure: everything they do by hand still works, and the
    two ways out are theirs to choose between.
    """
    from . import paths, schedule

    if not paths.is_macos():
        return Check("Scheduled work can reach your files", True,
                     detail="not a macOS machine")

    root = getattr(getattr(loaded, "layout", None), "root", "") if loaded else ""
    if not root:
        return Check("Scheduled work can reach your files", True,
                     detail="no workspace is configured yet")

    guarded = paths.inside_a_protected_folder(root)
    if not guarded:
        return Check("Scheduled work can reach your files", True,
                     detail=f"{root} is not a folder macOS restricts")

    try:
        installed = bool(schedule.installed_names())
    except Exception:                                     # noqa: BLE001
        installed = True

    detail = (f"your workspace is inside {guarded}, and macOS does not let "
              "anything started by a scheduler read that folder. Tasks will "
              "install, report success, and then fail every time they run.")
    if not installed:
        detail += " Nothing is scheduled yet, so nothing is failing today."

    return Check(
        "Scheduled work can reach your files", False, warning_only=True,
        detail=detail,
        fix=("Run `move-workspace` and it does the whole thing: moves the "
             "folder somewhere macOS does not restrict, records the new "
             "location, and re-points your scheduled tasks and launcher at "
             "it. The alternative is granting Full Disk Access in System "
             "Settings > Privacy & Security, but that grant goes to "
             "/bin/bash rather than to your tasks, which is far more access "
             "than this needs, and macOS drops it on major updates."))


def check_no_stray_engines() -> Check:
    """Numbered engine folders beside the real one.

    A warning rather than a fault: nothing is broken by their presence. The
    honest reason to mention them is that anybody looking at that folder will
    wonder, exactly as the maintainer did -- an unexplained folder sitting next to the
    one holding all your software is a reasonable thing to be uneasy about.
    """
    from . import engine

    strays = engine.stray_engine_dirs()
    if not strays:
        return Check("No leftover engine folders", True)

    empty = [one.name for one in strays if engine.is_empty(one)]
    full = [one.name for one in strays if not engine.is_empty(one)]

    if full:
        detail = (f"{', '.join(full)} sits beside the engine and is not "
                  "empty, so I have not touched it")
        fix = "Look inside; if it is not yours, delete it."
    else:
        detail = f"{', '.join(empty)} - empty leftovers"
        fix = "The next upgrade clears these, or delete them yourself."

    return Check("No leftover engine folders", False, warning_only=True,
                 detail=detail, fix=fix)


def check_session_is_current() -> Check:
    """Is the running session using the engine that is installed?

    Phrased as a consequence rather than a pair of timestamps, because the
    timestamps are not the point and nobody acts on them. "You are running
    yesterday's behaviour" is a sentence somebody restarts for.
    """
    from . import guard

    if not guard.session_predates_engine():
        return Check("Session is running the installed version", True)

    return Check(
        "Session is running the installed version", False, warning_only=True,
        detail="your session was started before this version was installed, "
               "so it is still using the previous instructions, skills and "
               "hooks — everything you have upgraded since then is on disk "
               "and not in use",
        fix="Restart your assistant: close the window and run the launcher.",
    )


def check_install_complete() -> Check:
    """Do the version markers agree, and did every folder actually arrive?

    THE FAILURE THIS WAS WRITTEN FOR (2026-08-20)
    ---------------------------------------------
    An upgrade died partway through replacing the engine. Four folders were
    already 0.8.0, three were still 0.5.0, and the entry point was gone. The
    tool reported `0.5.0 -> 0.8.0`, correctly and uselessly. `doctor` passed.

    Then the retry succeeded -- and `library`, 103 shipped skills and
    specialists, had never been copied at all, because the *old* engine's file
    list drove the copy. `doctor` passed that too, and said "Everything runs
    from your own folder."

    A health check that passes a tree missing a hundred files is not reporting
    health; it is reporting that it did not look. So this compares the three
    places a version is written, and the installed tree against the manifest
    the upgrade recorded.
    """
    from . import engine

    folder = engine.engine_dir()
    if not folder.exists():
        return Check("Install is complete and consistent", True,
                     detail="running from the package, not an adopted copy")

    said: list[str] = []

    # One version, or three disagreeing ones.
    seen = {}
    marker = folder / "pyproject.toml"
    if marker.exists():
        for line in marker.read_text(encoding="utf-8",
                                     errors="replace").splitlines():
            if line.strip().startswith("version"):
                seen["pyproject.toml"] = line.split("=", 1)[-1].strip().strip('"')
                break
    init = folder / "src" / "aki_agent" / "__init__.py"
    if init.exists():
        for line in init.read_text(encoding="utf-8",
                                   errors="replace").splitlines():
            if line.strip().startswith("__version__"):
                seen["__init__.py"] = line.split("=", 1)[-1].strip().strip('"')
                break

    distinct = {value for value in seen.values() if value}
    if len(distinct) > 1:
        said.append("two versions are installed at once (" + ", ".join(
            f"{where} says {what}" for where, what in seen.items()) + ")")

    # Everything the upgrade said it copied should be there.
    manifest = folder / engine.MANIFEST_FILE
    if manifest.exists():
        wanted = [line.strip() for line in
                  manifest.read_text(encoding="utf-8").splitlines()
                  if line.strip()]
        missing = [name for name in wanted if not (folder / name).exists()]
        if missing:
            said.append("missing from the install: " + ", ".join(missing))

    if not (folder / "bin" / "_bootstrap.py").is_file():
        said.append("bin/_bootstrap.py is missing, so no command can run")

    if said:
        return Check(
            "Install is complete and consistent", False,
            detail="; ".join(said),
            fix=_run("aki_agent.cli",
                     "upgrade --from <the release folder> --yes")
                + "    (or `rollback` to go back to the previous engine)",
        )

    return Check("Install is complete and consistent", True,
                 detail=(", ".join(sorted(distinct)) or "version readable")
                 + ", every expected folder present")


def check_scheduled_tasks_are_working() -> Check:
    """Whether anything that runs unattended has been failing.

    Nothing asked this before. Six tasks fire with the console hidden, so a
    task that broke on Monday was still "installed" on Friday and the person
    had no way to find out. `installed: yes` was answering a different
    question — whether Windows knows about it, not whether it works.
    """
    from . import task_runs

    try:
        broken = task_runs.failing()
    except Exception as exc:                             # noqa: BLE001
        return Check("Scheduled tasks are working", False, warning_only=True,
                     detail=f"could not read the record of runs: {exc}")

    if not broken:
        return Check("Scheduled tasks are working", True,
                     detail="nothing has failed since it last worked")

    worst = broken[0]
    detail = "; ".join(f"{one.key} {one.sentence()}" for one in broken[:4])
    return Check(
        "Scheduled tasks are working", False,
        detail=detail,
        fix=(f"Run it by hand to see what it says: "
             f"aki run-task {worst.key}"),
    )


def check_nothing_was_set_aside() -> Check:
    """Whether any state file turned out to be unreadable and was kept.

    `atomic.read_json` has always said the user "gets told by doctor". Until
    2026-08-23 nothing here asked, so that sentence was a promise with nothing
    behind it — a corrupt file was replaced by its default and nobody ever
    heard about it.
    """
    from . import atomic, paths

    try:
        kept = atomic.quarantined(paths.state_dir())
    except Exception as exc:                             # noqa: BLE001
        return Check("State files are readable", False, warning_only=True,
                     detail=f"could not look: {exc}")

    if not kept:
        return Check("State files are readable", True)

    names = ", ".join(one.name for one in kept[:4])
    return Check(
        "State files are readable", False, warning_only=True,
        detail=(f"{len(kept)} file(s) could not be read and were set aside: "
                f"{names}"),
        fix=("Nothing was lost -- the original bytes are in those files, "
             "beside the ones now in use. If the assistant has been behaving "
             "as though it had forgotten something, this is where it went. "
             "Delete them once you are satisfied."),
    )


def check_the_library_is_there() -> Check:
    """The shipped skills, which go missing in a way that looks like emptiness.

    `pyproject.toml` ships only `src/`, so a plain `pip install .` leaves the
    library out entirely. `catalogue()` then globs a folder that is not there,
    gets an empty list, and the Library page renders as "nothing here" with no
    error at any point.

    Not the documented install route — the plugin install and the bootstrap
    both use an editable install, where it works — but silent is silent, and
    the whole point of this file is that nothing fails without a sentence.
    """
    from . import library

    if library.is_present():
        return Check("Skill library", True,
                     detail=f"{len(library.catalogue())} available")

    return Check(
        "Skill library", False, warning_only=True,
        detail=f"Not found at {library.library_dir()}",
        fix=("The Library page will show nothing at all until this is there. "
             "It ships with the plugin, so this usually means the package was "
             "installed from source with a plain `pip install .` rather than "
             "through Claude Code."),
    )


def run_all() -> list[Check]:
    checks: list[Check] = [check_python()]
    checks.extend(check_packages())

    # The config is read before the tool checks so that we only look for the
    # tools this person's setup actually uses.
    config_check, loaded = check_config()

    checks.extend(check_external_tools(features_in_use(loaded)))
    checks.append(check_app_dir())
    checks.append(config_check)
    checks.append(check_workspace(loaded))
    checks.append(check_workspace_notes(loaded))
    checks.append(check_credential_store())
    checks.append(check_schedule())
    checks.append(check_after_update())
    checks.append(check_engine())
    checks.append(check_handoff())
    checks.append(check_draft_check())
    checks.append(check_install_complete())
    checks.append(check_workspace_names(loaded))
    checks.append(check_session_is_current())
    checks.append(check_credential_store_reachable())
    checks.append(check_keys_are_not_split_between_two_stores())
    checks.append(check_launcher())
    checks.append(check_scheduling_can_reach_the_workspace(loaded))
    checks.append(check_no_stray_engines())
    checks.append(check_scheduled_tasks_are_working())
    checks.append(check_nothing_was_set_aside())
    checks.append(check_the_library_is_there())
    checks.append(check_which_brain())
    return checks


def format_report(checks: list[Check]) -> str:
    """Render the checks as something a person can read out loud."""
    from . import paths

    lines: list[str] = []
    lines.append("")
    lines.append("  Health check")
    lines.append("  " + "-" * 58)

    for check in checks:
        lines.append(f"  [{check.symbol}] {check.name}")
        if check.detail:
            for detail_line in check.detail.splitlines():
                lines.append(f"         {detail_line}")
        if not check.ok and check.fix:
            for fix_line in check.fix.splitlines():
                lines.append(f"         -> {fix_line}")
        lines.append("")

    failures = [check for check in checks
                if not check.ok and not check.warning_only]
    warnings = [check for check in checks
                if not check.ok and check.warning_only]

    lines.append("  " + "-" * 58)
    if failures:
        lines.append(f"  {len(failures)} thing(s) need fixing before this "
                     "will work.")
    elif warnings:
        # "optional" was the wrong word (2026-08-23).
        #
        # Every check that can fail here is warning_only, so this line was
        # what a student saw when their scheduled work was gone, their
        # schedule pointed at a deleted folder, or their CLAUDE.md had never
        # been written: "Everything essential is working. 6 optional thing(s)
        # are not set up." None of those is optional, and the sentence sent
        # people away from a report that was, just above, listing what was
        # wrong.
        #
        # It now says what is true — these are not set up, and it does not
        # claim anything about whether the rest is fine.
        lines.append(f"  {len(warnings)} thing(s) are not set up yet. "
                     "Nothing here stops it from starting.")
        lines.append("  Read the lines above — some of them are work that "
                     "is not happening.")
    else:
        lines.append("  Everything is working.")

    lines.append("")
    lines.append(f"  Running on {paths.platform_label()}, "
                 f"Python {'.'.join(str(p) for p in sys.version_info[:3])}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    """Entry point. Returns a shell exit code.

    0 = fine (warnings allowed), 1 = something is genuinely broken.
    """
    # INHERITED TRAP: a Windows console's default code page cannot render
    # non-Latin text, and the exception it raises kills whatever shelled out
    # to this script. Set the stream encoding explicitly before printing
    # anything -- a user's assistant name or workspace path may be in any
    # language.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # Older Python, or a stream that does not support it. Not worth
            # failing over -- the report is ASCII apart from user content.
            pass

    checks = run_all()
    print(format_report(checks))

    broken = any(not check.ok and not check.warning_only for check in checks)
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
