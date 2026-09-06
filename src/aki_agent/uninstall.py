"""Take the assistant off a machine, and leave the person's work untouched.

WHY THIS FILE EXISTS
--------------------
Anything a student installs, a student must be able to remove. Without that,
"try it and see" is not a fair offer: the only way out is hunting through a
home folder, a scheduler and Claude Code's own plugin list, guessing which
things belong to which product.

THE ONE RULE THAT MATTERS
-------------------------
**Removal is decided by inclusion, never by exclusion.**

The tempting shape is "delete the root folder, except the bits the user
owns". That is one bad `except` away from deleting somebody's documents, and
the failure is unrecoverable. So nothing here deletes a folder because it is
*not* protected. Every single thing removed had to be named, individually, as
something this package created:

  - the config folder (`01_Config`), which holds settings, memory, state, logs
  - the pointer file that says where that folder is
  - the older `~/.aki-agent` folder, if an earlier install left one
  - scheduled tasks carrying our prefix, and only those
  - skills in `~/.claude/skills/` carrying our marker, and only those
  - the generated launcher
  - `CLAUDE.md` and `.claude/` at the root -- but only when they still carry
    the line this package wrote into them

`03_Workspace` -- the person's actual work -- is never in that list, and
`refuse()` below makes it an error rather than an omission if it ever is.
A test asserts the same thing from the outside, because a rule stated only in
a comment is a rule that lasts until the next edit.

WHAT IT DOES NOT DO
-------------------
It does not delete the unzipped package, and it does not delete Claude Code.
It reports the one command that removes the plugin, and runs it only if asked,
because that command belongs to Claude Code and can fail for its own reasons.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

from . import launcher, paths, runner, schedule, secrets, skills_store
# The line the scaffold writes into `CLAUDE.md`. Its presence is what tells us
# the file is ours to remove rather than something the user wrote themselves.
# Imported rather than repeated: a marker that exists twice is a marker that
# stops matching the first time one copy is edited.
from .scaffold import OURS_MARKER


@dataclass
class Item:
    """One thing that would be removed, or one that deliberately would not."""

    kind: str                     # folder | file | task | skill | plugin
                                  # | secrets
    label: str                    # what to call it in front of a person
    path: Path | None = None
    detail: str = ""

    def line(self) -> str:
        where = f"  ({self.path})" if self.path else ""
        tail = f" — {self.detail}" if self.detail else ""
        return f"{self.label}{tail}{where}"


@dataclass
class Plan:
    """Everything that would happen, for the person to read before it does."""

    root: Path | None = None
    # Carried so that `perform` can name the credentials to remove. They are
    # derived from the config -- mail accounts and calendar feeds are named
    # after the address and the feed -- so the plan has to remember which
    # config it was built from.
    config: object | None = None
    removals: list[Item] = dataclass_field(default_factory=list)
    kept: list[Item] = dataclass_field(default_factory=list)
    blockers: list[str] = dataclass_field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.removals

    def describe(self) -> str:
        lines: list[str] = []
        if self.root:
            lines += [f"Assistant folder: {self.root}", ""]

        if self.removals:
            lines.append("This would be removed:")
            lines.append("")
            for item in self.removals:
                lines.append(f"  - {item.line()}")
        else:
            lines.append("Nothing of this assistant was found on this machine.")

        if self.kept:
            lines += ["", "This would be left exactly as it is:", ""]
            for item in self.kept:
                lines.append(f"  - {item.line()}")

        if self.blockers:
            lines += ["", "Stop and deal with these first:", ""]
            for blocker in self.blockers:
                lines.append(f"  ! {blocker}")

        lines += ["", "Your own documents are never removed."]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

def protected_paths(root: Path | None,
                    work_dir: str = "03_Workspace") -> list[Path]:
    """Folders that must never be removed, even as an exact match.

    The root is here and the work folder is here, but they are protected
    differently -- see `refuse()`. The root has to stay removable *inside*,
    since `01_Config` and `.claude` live in it and are ours; the work folder
    is protected all the way down.
    """
    guarded = [paths.home()]
    if root:
        root = Path(root)
        guarded += [root, root / work_dir]
    return [path.resolve() for path in guarded if path]


def refuse(path: Path, root: Path | None,
           work_dir: str = "03_Workspace") -> str:
    """Why this path must not be removed, or "" if removing it is fine.

    Two different guards, and the difference is the whole design:

    - **Never as an exact match**: the home folder, the assistant's root, the
      work folder. Removing the root would take the work with it.
    - **Never anywhere below it**: the work folder only. Everything in there
      is the person's, however deeply nested.

    `01_Config` and `.claude` sit inside the root and *are* removable, which
    is why the root cannot simply be protected all the way down.

    Containment is decided on resolved paths with `Path.parents`, which
    compares whole segments -- so `03_Workspace-old` is not mistaken for
    `03_Workspace`, and a `..` that walks out of a folder does not keep the
    protection of the folder it started in.
    """
    try:
        candidate = Path(path).resolve()
    except OSError:                                       # pragma: no cover
        return "its location could not be read"

    if candidate.parent == candidate:
        return "it is the root of a drive"

    for guarded in protected_paths(root, work_dir):
        if candidate == guarded:
            return f"it is {guarded}, which this never removes"

    if root:
        work_root = (Path(root) / work_dir).resolve()
        if work_root in candidate.parents:
            return f"it is inside {work_root}, which holds your work"
    return ""


# ---------------------------------------------------------------------------
# Working out what is there
# ---------------------------------------------------------------------------

def _count_below(path: Path) -> int:
    try:
        return sum(1 for entry in path.rglob("*") if entry.is_file())
    except OSError:                                       # pragma: no cover
        return 0


def _is_ours(path: Path) -> bool:
    """Does this file still carry the line the scaffold wrote into it?"""
    try:
        return OURS_MARKER in path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def plan(config=None, root: Path | None = None) -> Plan:
    """Work out what removal would do. Writes nothing, deletes nothing."""
    work_dir = "03_Workspace"
    sandbox_dir = "02_Sandbox"
    if config is not None and getattr(config, "layout", None) is not None:
        root = root or config.layout.root
        work_dir = config.layout.work_dir or work_dir
        sandbox_dir = config.layout.sandbox_dir or sandbox_dir

    config_dir = paths.app_dir()
    if root is None and config_dir.name != paths.APP_DIR_NAME:
        # The config folder normally sits inside the assistant's root folder,
        # so the root is its parent. Only true for the visible-folder layout,
        # which is why the dotted-folder name is excluded.
        root = config_dir.parent

    result = Plan(root=Path(root) if root else None, config=config)

    def removal(item: Item) -> None:
        if item.path is not None:
            reason = refuse(item.path, result.root, work_dir)
            if reason:
                # Not silently skipped: something asked to remove a protected
                # path, and that is worth saying out loud.
                result.blockers.append(f"refused to remove {item.path}: {reason}")
                return
        result.removals.append(item)

    # -- the config folder ---------------------------------------------------
    if config_dir.is_dir():
        removal(Item("folder", "Settings, memory, state and logs",
                     config_dir, f"{_count_below(config_dir)} files"))

    # -- an older dotted folder, from before the visible-folder layout -------
    legacy = paths.home() / paths.APP_DIR_NAME
    if legacy.is_dir() and legacy.resolve() != config_dir.resolve():
        removal(Item("folder", "Older config folder from a previous install",
                     legacy, f"{_count_below(legacy)} files"))

    # -- the pointer ---------------------------------------------------------
    pointer = paths.pointer_file()
    if pointer.exists():
        removal(Item("file", "The note saying where the assistant lives",
                     pointer))

    # -- the launcher --------------------------------------------------------
    for name in ("start-assistant",):
        launcher_file = launcher.launcher_path(name)
        if launcher_file.exists():
            removal(Item("file", "The launcher", launcher_file))

    # -- scheduled tasks -----------------------------------------------------
    # If the list cannot be read, say so in the plan rather than producing a
    # plan with no tasks in it. An uninstall that silently leaves six jobs
    # running against a deleted folder is the worst version of this.
    try:
        for name in schedule.installed_names():
            removal(Item("task", f"Scheduled task {name}",
                         detail="stops running automatically"))
    except schedule.CouldNotAsk as problem:
        result.kept.append(Item(
            "task", "Scheduled tasks could not be listed",
            detail=f"{problem} — remove them yourself in Task Scheduler, "
                   f"or they will keep running"))

    # -- credentials ---------------------------------------------------------
    #
    # THE WORD "CREDENTIAL" APPEARED IN NEITHER LIST (2026-08-23)
    # ----------------------------------------------------------
    # This plan names what it removes and what it leaves, and said nothing
    # about the credential store either way. So a student who removed the
    # assistant kept their Gmail app password, their Google OAuth client
    # secret and refresh token, their Telegram API id and hash, and every
    # paid API key -- in Windows Credential Manager, with nothing left on the
    # machine to say what had put them there.
    #
    # `google_calendar.forget_everything()` had been written for exactly this
    # and had no callers.
    held = [key for key in secrets.every_key_we_might_hold(config)
            if secrets.get_secret(key)]
    if held:
        removal(Item("secrets", f"{len(held)} saved credential(s)",
                     detail="passwords, API keys and sign-ins, from this "
                            "computer's credential store"))

    # -- skills we installed into Claude Code --------------------------------
    #
    # The whole skill folder, not just its `SKILL.md`: leaving an empty folder
    # behind means the next `/find` still lists a skill that does nothing.
    everything = skills_store.read_all(include_others=True)
    for skill in everything:
        if skill.ours:
            removal(Item("skill", f"Skill /{skill.key}", skill.path.parent))

    others = [skill for skill in everything if not skill.ours]
    if others:
        result.kept.append(Item("skill", f"{len(others)} skill(s) in "
                                f"{skills_store.skills_dir()} written elsewhere",
                                detail="not ours to remove"))

    # -- the assistant's own desk --------------------------------------------
    #
    # The sandbox is the one folder the package tells the user is not safe
    # ("it writes here freely, and nothing in it is safe" -- the scaffolded
    # README), so removing it is the documented contract rather than a
    # judgement call. The file count is shown for the same reason the rest
    # of the plan is shown: it is printed before anything is deleted, and
    # `--yes` is a second step.
    #
    # Only the sandbox at the root. An older install kept one inside each
    # workspace, and those sit under the work folder, which is protected all
    # the way down -- they stay, with the work.
    if result.root:
        sandbox = result.root / sandbox_dir
        if sandbox.is_dir():
            removal(Item("folder", "The assistant's sandbox (its own "
                         "working files)", sandbox,
                         f"{_count_below(sandbox)} files"))

    # -- the assistant's own notes at the root -------------------------------
    if result.root:
        claude_md = result.root / "CLAUDE.md"
        if claude_md.is_file():
            if _is_ours(claude_md):
                removal(Item("file", "CLAUDE.md (the assistant's own notes)",
                             claude_md))
            else:
                result.kept.append(Item("file", "CLAUDE.md", claude_md,
                                        "does not look like ours"))

        # Same marker test as CLAUDE.md above, and for the same reason: it
        # describes three folders that will not exist afterwards, so leaving
        # it is worse than useless -- but if the person has rewritten it,
        # the words in it are theirs.
        readme = result.root / "README.md"
        if readme.is_file():
            if _is_ours(readme):
                removal(Item("file", "README.md (how this folder works)",
                             readme))
            else:
                result.kept.append(Item("file", "README.md", readme,
                                        "does not look like ours"))

        claude_dir = result.root / ".claude"
        if claude_dir.is_dir():
            removal(Item("folder", "The .claude folder at the root", claude_dir))

        work_root = result.root / work_dir
        if work_root.is_dir():
            result.kept.append(Item("folder", "Your work", work_root,
                                    f"{_count_below(work_root)} files, untouched"))

    # -- the plugin ----------------------------------------------------------
    result.removals.append(Item(
        "plugin", "The Claude Code plugin",
        detail="claude plugin uninstall aki-agent@aki-agent"))

    return result


# ---------------------------------------------------------------------------
# Doing it
# ---------------------------------------------------------------------------

def _remove_task(name: str) -> tuple[bool, str]:
    """Remove one scheduled task, named as the operating system knows it."""
    key = name.split(f"{schedule.TASK_PREFIX}-", 1)[-1]
    key = key.split("com.aki-agent.", 1)[-1]
    return schedule.remove(schedule.ScheduledTask(key=key, title=name, why=""))


def _remove_plugin() -> tuple[bool, str]:
    """Ask Claude Code to remove the plugin.

    WHY THE COMMAND IS RESOLVED FIRST
    ---------------------------------
    On Windows `claude` is a `.CMD` shim, and CreateProcess does not apply
    PATHEXT -- so a bare `"claude"` in the argument list raises WinError 2
    on every Windows machine, even while `claude --version` works in the
    same shell. Found by running the real uninstall, not by the suite.
    `runner.find_claude()` resolves it with `shutil.which`, which does
    apply PATHEXT, and it was already the only correct call site.
    """
    try:
        executable = runner.find_claude()
    except runner.ClaudeNotFound:
        return False, ("Claude Code was not found on this machine, so the "
                       "plugin could not be removed. If you reinstall it, "
                       "run: claude plugin uninstall aki-agent@aki-agent")
    try:
        result = subprocess.run(
            [executable, "plugin", "uninstall", "aki-agent@aki-agent"],
            capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, (f"could not run Claude Code's own uninstaller ({exc}). "
                       "Run this yourself: "
                       "claude plugin uninstall aki-agent@aki-agent")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:200]
        # Not installed is the state we are trying to reach, so reporting
        # it as a failure is wrong -- and it is the *normal* case for
        # anyone who installed from the zip rather than the marketplace,
        # who would otherwise end every uninstall on a red line about
        # something already the way they want it.
        if "not found in installed plugins" in detail:
            return True, "the plugin was not installed"
        return False, ("Claude Code declined to remove the plugin: "
                       f"{detail or 'no reason given'}")
    return True, "removed the plugin from Claude Code"


def perform(the_plan: Plan, confirmed: bool,
            remove_plugin: bool = True) -> tuple[bool, str]:
    """Carry out the plan. Refuses unless `confirmed` is true.

    Returns (everything succeeded, what to tell the person). One failure never
    stops the rest: a task that will not delete must not leave the config
    folder behind as well.
    """
    if not confirmed:
        return False, "Nothing was removed. Re-run with --yes to go ahead."
    if the_plan.blockers:
        return False, ("Refusing to remove anything while these are unresolved:\n  "
                       + "\n  ".join(the_plan.blockers))

    done: list[str] = []
    failed: list[str] = []

    for item in the_plan.removals:
        if item.kind == "plugin":
            if not remove_plugin:
                done.append("left the plugin installed, as asked")
                continue
            ok, message = _remove_plugin()
            (done if ok else failed).append(message)
            continue

        if item.kind == "task":
            name = item.label.replace("Scheduled task ", "")
            ok, message = _remove_task(name)
            (done if ok else failed).append(
                f"removed {name}" if ok else f"{name}: {message}")
            continue

        if item.kind == "secrets":
            gone = secrets.forget_everything(the_plan.config)
            done.append(f"removed {len(gone)} credential(s) from the "
                        "credential store")
            continue

        path = item.path
        if path is None:
            continue

        # Checked again here, not only in the plan. A plan can be built, sat
        # on, and performed against a machine that has changed underneath it.
        reason = refuse(path, the_plan.root)
        if reason:
            failed.append(f"refused to remove {path}: {reason}")
            continue

        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            else:
                continue
            done.append(f"removed {path}")
        except OSError as exc:
            failed.append(
                f"could not remove {path}: {exc}. "
                "On Windows this is almost always a program still using it — "
                "close the dashboard and any terminal sitting in that folder, "
                "then run this again.")

    lines = [f"Removed {len(done)} thing(s)."]
    lines += [f"  - {line}" for line in done]
    if failed:
        lines += ["", f"{len(failed)} could not be removed:"]
        lines += [f"  ! {line}" for line in failed]
    if the_plan.root:
        lines += ["", f"Your work is still in {the_plan.root}. "
                      "Nothing inside it was touched."]
    return not failed, "\n".join(lines)
