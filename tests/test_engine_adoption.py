"""The installer must not still be part of the product.

The maintainer unzipped a release, installed, and asked whether he could delete the
unzipped folder. The answer was no, and every wire back to it was invisible:
an editable install naming `<unzipped>/src`, scheduled tasks calling a runner
inside it, a launcher naming its bootstrap. Nothing announced the dependency
and nothing would have announced the breakage either -- the tasks would simply
have stopped firing.

So these tests are about *absence of a reference*, which is why several of
them assert on the text of generated files rather than on return values.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import engine, launcher, paths, schedule


@pytest.fixture
def unzipped(tmp_path) -> Path:
    """A folder shaped like an unzipped release, with the parts that matter."""
    root = tmp_path / "Aki-Agent-Beta-unzipped"
    (root / "src" / "aki_agent").mkdir(parents=True)
    (root / "src" / "aki_agent" / "__init__.py").write_text("", encoding="utf-8")
    (root / "bin").mkdir()
    (root / "bin" / "run-task.bat").write_text("@echo off\n", encoding="utf-8")
    (root / "bin" / "run-task.command").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "bin" / "_bootstrap.py").write_text("# bootstrap\n", encoding="utf-8")
    (root / "skills").mkdir()
    (root / "skills" / "doctor").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='aki-agent'\n",
                                         encoding="utf-8")
    # Things that must NOT come along.
    (root / "_release").mkdir()
    (root / "_release" / "old.zip").write_text("big", encoding="utf-8")
    (root / "src" / "aki_agent" / "__pycache__").mkdir()
    (root / "src" / "aki_agent" / "__pycache__" / "x.pyc").write_text(
        "cache", encoding="utf-8")
    return root


@pytest.fixture
def app_folder(tmp_path, monkeypatch) -> Path:
    """`01_Config`, the folder the engine should end up inside."""
    folder = tmp_path / "Assistant" / "01_Config"
    folder.mkdir(parents=True)
    monkeypatch.setenv("AKI_AGENT_HOME", str(folder))
    return folder


# ---------------------------------------------------------------------------
# The copy


def test_the_engine_lands_inside_the_assistants_own_folder(unzipped, app_folder):
    the_plan = engine.plan(source=unzipped)
    ok, message = engine.copy_engine(the_plan)

    assert ok, message
    assert (app_folder / "engine" / "src" / "aki_agent" / "__init__.py").is_file()
    assert (app_folder / "engine" / "bin" / "_bootstrap.py").is_file()
    assert (app_folder / "engine" / "skills" / "doctor").is_dir()


def test_caches_and_old_releases_do_not_come_along(unzipped, app_folder):
    engine.copy_engine(engine.plan(source=unzipped))
    copied = app_folder / "engine"

    assert not (copied / "_release").exists(), \
        "a release zip inside the engine is how a zip ends up containing itself"
    assert not (copied / "src" / "aki_agent" / "__pycache__").exists()


def test_copying_again_replaces_rather_than_merges(unzipped, app_folder):
    """A module deleted by an upgrade must not survive in the copy.

    A merge leaves it there, it still imports, and something old runs -- the
    worst shape of this bug, because everything appears to work.
    """
    engine.copy_engine(engine.plan(source=unzipped))
    stale = app_folder / "engine" / "src" / "aki_agent" / "removed_in_v2.py"
    stale.write_text("# from the previous version\n", encoding="utf-8")

    engine.copy_engine(engine.plan(source=unzipped))

    assert not stale.exists()


def test_adopting_the_copy_it_is_already_running_is_a_no_op(app_folder):
    target = app_folder / "engine"
    target.mkdir()
    the_plan = engine.plan(source=target)

    assert the_plan.already
    assert "can be deleted" in the_plan.describe()

    ok, message = engine.copy_engine(the_plan)
    assert ok and "already" in message


def test_the_plan_names_where_from_and_where_to(unzipped, app_folder):
    text = engine.plan(source=unzipped).describe()

    assert str(unzipped) in text
    assert str(app_folder / "engine") in text
    assert "not touched" in text, "say what is safe, not only what moves"


# ---------------------------------------------------------------------------
# The wires


def test_the_runner_can_be_asked_about_a_copy_other_than_this_one(tmp_path):
    """Re-pointing happens while the old copy is still the one running."""
    other = tmp_path / "elsewhere"
    runner = schedule.runner_script(other)

    assert runner.parent == other / "bin"
    assert runner.name in ("run-task.bat", "run-task.command")


def test_the_launcher_is_written_against_the_root_it_is_given(tmp_path,
                                                              app_folder):
    adopted = app_folder / "engine"
    options = launcher.LauncherOptions(workspace=tmp_path, title="Mira")

    ok, message = launcher.write_launcher(options, adopted, confirmed=True)
    text = launcher.launcher_path().read_text(encoding="utf-8")

    assert ok, message
    assert str(adopted) in text
    assert "Aki-Agent-Beta-unzipped" not in text


def test_rewriting_the_launcher_keeps_the_choices_already_in_it():
    """Auto mode disappearing is the quiet regression: it still starts, and
    it stops doing anything while nobody is watching."""
    with_auto = launcher.windows_launcher(
        launcher.LauncherOptions(auto_mode=True, open_dashboard=True),
        Path("C:/anywhere"))

    kept = launcher.choices_in(with_auto)

    assert kept["auto_mode"] and kept["open_dashboard"]
    assert launcher.choices_in("claude\n") == {"auto_mode": False,
                                               "open_dashboard": False,
                                               "assistant_agent": ""}

    # The persona too, since 2026-08-23. `cmd_repair` had its own inline copy
    # of this read-back that recovered two of the three and dropped the agent,
    # so repairing an install -- which is what somebody runs when something is
    # already wrong -- rewrote the launcher without it. Nothing errored; the
    # assistant simply started as a plain session from then on, and the repair
    # reported success.
    with_agent = launcher.windows_launcher(
        launcher.LauncherOptions(assistant_agent="mira"),
        Path("C:/anywhere"))
    assert launcher.choices_in(with_agent)["assistant_agent"] == "mira"


# ---------------------------------------------------------------------------
# The window that should not be there
#
# The maintainer: "there is a terminal pop up in a regular interval ... they should all
# run in background." Task Scheduler runs a .bat as the logged-in user and
# that always gets a console window; there is no schtasks flag for it, and the
# <Hidden> element in a task's XML hides the task from the list, not the
# window. run-task.bat's own header had promised silence since the day it was
# written -- it simply had no way to keep the promise by itself.


def test_a_scheduled_task_is_started_through_the_hidden_wrapper():
    task = schedule.DEFAULT_TASKS[0]
    program, arguments = schedule.windows_target(task,
                                                 schedule.runner_script())

    assert program == "wscript.exe", "a .bat run by the scheduler flashes a window"
    assert "run-task.vbs" in arguments
    assert task.key in arguments, "the wrapper still has to be told which task"


def test_an_install_without_the_wrapper_still_schedules(tmp_path):
    """Made before the wrapper existed: a window is bad, not running is worse."""
    bare = tmp_path / "old-install"
    (bare / "bin").mkdir(parents=True)
    runner = bare / "bin" / "run-task.bat"
    runner.write_text("@echo off\n", encoding="utf-8")

    program, arguments = schedule.windows_target(
        schedule.DEFAULT_TASKS[0], runner)

    assert "run-task.vbs" not in program
    assert program == str(runner)


def test_the_wrapper_ships_beside_the_runner_it_wraps():
    """The gap this package has hit five times: a path to a file nobody made."""
    assert schedule.hidden_runner().exists(), \
        "windows_target names this file, so it has to be in the package"


# ---------------------------------------------------------------------------
# Upgrading
#
# The maintainer: "你果兩步都太complicated, 我想喺claude code 打 [/upgrade] 就可以升級."
# The two steps were two because the package is two things -- a Python engine
# and a Claude Code plugin. That is the package's problem to hide, not his to
# remember, so these tests are about the single command doing both halves and
# refusing to do anything to a folder that is not this package.


def _release_zip(tmp_path, version="9.9.9"):
    """A zip shaped like a real release: one folder, package inside it."""
    import zipfile

    inner = f"aki-agent-beta-{version}"
    archive = tmp_path / f"Aki-Agent-Beta-20260101-001.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(f"{inner}/src/aki_agent/__init__.py",
                   f'__version__ = "{version}"\n')
        z.writestr(f"{inner}/bin/_bootstrap.py", "# bootstrap\n")
        z.writestr(f"{inner}/pyproject.toml", "[project]\n")
    return archive


def test_a_zip_is_unpacked_and_the_package_found_inside_it(tmp_path):
    archive = _release_zip(tmp_path)

    found, problem = engine.source_for_upgrade(archive, allow_unsigned=True,
                                               workspace=tmp_path / "work")

    assert found is not None, problem
    assert engine.looks_like_the_package(found)
    assert engine.version_of(found) == "9.9.9"


def test_a_folder_that_is_not_this_package_is_refused(tmp_path):
    """The cost of being wrong is an assistant that will not start."""
    somewhere = tmp_path / "holiday photos"
    somewhere.mkdir()

    found, problem = engine.source_for_upgrade(somewhere, allow_unsigned=True)

    assert found is None
    assert "does not look like this package" in problem


def test_a_zip_of_something_else_is_refused(tmp_path):
    import zipfile

    archive = tmp_path / "Aki-Agent-Beta-notreally.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("notes.txt", "hello")

    found, problem = engine.source_for_upgrade(archive, allow_unsigned=True,
                                               workspace=tmp_path / "work")

    assert found is None
    assert "does not contain this package" in problem


def test_a_missing_path_says_so_rather_than_guessing(tmp_path):
    found, problem = engine.source_for_upgrade(tmp_path / "nowhere.zip")

    assert found is None
    assert "not there" in problem


def test_the_newest_download_is_the_one_offered(tmp_path, monkeypatch):
    """Typing a path is most of what made the old instructions feel hard."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.setattr(engine.paths, "home", lambda: tmp_path)
    # Somewhere that is not itself a copy of the package: since the
    # folder you are standing in now wins, a test about Downloads has
    # to stand somewhere neutral to be about Downloads at all.
    monkeypatch.chdir(tmp_path)

    older = downloads / "Aki-Agent-Beta-20260818-001.zip"
    older.write_bytes(b"old")
    newer = downloads / "Aki-Agent-Beta-20260819-005.zip"
    newer.write_bytes(b"new")
    import os
    os.utime(older, (1_000_000, 1_000_000))
    os.utime(newer, (2_000_000, 2_000_000))

    assert engine.newest_release_nearby() == newer


def test_the_plugin_half_repoints_at_the_adopted_engine(monkeypatch, tmp_path):
    """`marketplace update` would re-read the OLD path -- the folder being
    replaced -- and faithfully reinstall the version being upgraded away
    from. So the entry is removed and added, in that order."""
    calls = []

    def fake(arguments):
        calls.append(arguments)
        return True, ""

    monkeypatch.setattr(engine, "_claude", fake)
    adopted = tmp_path / "01_Config" / "engine"

    engine.refresh_plugin(adopted)

    assert calls[0][:3] == ["plugin", "marketplace", "remove"]
    assert calls[1][:3] == ["plugin", "marketplace", "add"]
    assert calls[1][3] == str(adopted)
    assert calls[2][:2] == ["plugin", "install"]


def test_a_failed_marketplace_add_does_not_go_on_to_install(monkeypatch,
                                                            tmp_path):
    """Installing against a marketplace that was not added reinstalls the old
    version and reports success -- the worst possible outcome for an upgrade."""
    def fake(arguments):
        return ("add" not in arguments), "no"

    monkeypatch.setattr(engine, "_claude", fake)

    lines = engine.refresh_plugin(tmp_path / "engine")

    assert not any("plugin:" in line for line in lines), lines
    assert any("FAILED" in line for line in lines)


# ---------------------------------------------------------------------------
# Which release an upgrade means when nobody says
#
# The maintainer unzipped the new release, cd-ed into it, ran its own bootstrap and was
# told "I could not find a release to upgrade from" -- by the new version,
# about itself. Reproducing it with a stale zip in Downloads showed something
# worse than the error message: standing in the new release, it would have
# upgraded him to the OLD zip, quietly.


def test_the_copy_being_run_is_what_upgrade_means(tmp_path, monkeypatch):
    """Running `<new>/bin/_bootstrap.py` runs the new code, so the answer is
    already in hand. Searching the disk for something you are holding is how
    you fail to find it."""
    new_release = tmp_path / "aki-agent-beta-20260819-007"
    (new_release / "src" / "aki_agent").mkdir(parents=True)
    (new_release / "src" / "aki_agent" / "__init__.py").write_text(
        '__version__ = "9.9.9"\n', encoding="utf-8")
    (new_release / "bin").mkdir()
    (new_release / "bin" / "_bootstrap.py").write_text("#", encoding="utf-8")

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "Aki-Agent-Beta-20260101-001.zip").write_bytes(b"stale")

    monkeypatch.setattr(engine, "running_from", lambda: new_release)
    monkeypatch.setattr(engine, "engine_dir", lambda: tmp_path / "01_Config" / "engine")
    monkeypatch.setattr(engine.paths, "home", lambda: tmp_path)

    found, problem = engine.source_for_upgrade(None, allow_unsigned=True)

    assert found == new_release, problem or found
    assert engine.version_of(found) == "9.9.9"


def test_standing_in_the_new_release_finds_it(tmp_path, monkeypatch):
    """The folder itself, not only folders inside it -- which is the shape of
    the miss: unzip, step in, run, and the one place it could not look."""
    release = tmp_path / "aki-agent-beta-20260819-007"
    (release / "src" / "aki_agent").mkdir(parents=True)
    (release / "src" / "aki_agent" / "__init__.py").write_text("", encoding="utf-8")
    (release / "bin").mkdir()
    (release / "bin" / "_bootstrap.py").write_text("#", encoding="utf-8")

    monkeypatch.chdir(release)
    monkeypatch.setattr(engine, "engine_dir", lambda: tmp_path / "engine")
    monkeypatch.setattr(engine.paths, "home", lambda: tmp_path)

    assert engine.newest_release_nearby() == release


def test_the_installed_engine_is_never_offered_as_the_upgrade(tmp_path,
                                                              monkeypatch):
    """Running from the installed copy means there is nothing new to hand, so
    it has to go and look rather than propose upgrading to itself."""
    engine_folder = tmp_path / "01_Config" / "engine"
    (engine_folder / "src" / "aki_agent").mkdir(parents=True)
    (engine_folder / "src" / "aki_agent" / "__init__.py").write_text(
        "", encoding="utf-8")
    (engine_folder / "bin").mkdir()
    (engine_folder / "bin" / "_bootstrap.py").write_text("#", encoding="utf-8")

    monkeypatch.setattr(engine, "running_from", lambda: engine_folder)
    monkeypatch.setattr(engine, "engine_dir", lambda: engine_folder)
    monkeypatch.setattr(engine.paths, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    found, problem = engine.source_for_upgrade(None, allow_unsigned=True)

    assert found is None
    assert "could not find" in problem
    assert "Downloads" in problem, "say where it looked"


# ---------------------------------------------------------------------------
# The chat mirror, and where its instructions live
#
# reported 2026-08-19: Telegram connected, and neither direction mirrored. The
# instruction to run `aki_agent.inbox` existed only in `agents/assistant.md`,
# which a normal install never loads -- `make-launcher` passes `--agent` only
# when somebody asks for one. So `inbox.py`, written to fix "a mechanism with
# nothing wired to it", had the same defect one level up.


def test_a_new_claude_md_tells_the_session_to_mirror(tmp_path):
    from aki_agent import scaffold

    text = scaffold._content_for(tmp_path / "CLAUDE.md", None, "Mira", "Sam",
                                 tmp_path)

    assert "aki_agent.inbox pending" in text, "dashboard -> assistant"
    assert "aki_agent.inbox said" in text, "phone -> dashboard"
    assert "aki_agent.inbox replied" in text


def test_an_older_claude_md_of_ours_is_topped_up(tmp_path):
    from aki_agent import scaffold

    marker = (f"<!-- written by {scaffold.OURS_MARKER}; delete this line and "
              "uninstall will leave this file alone -->")
    (tmp_path / "CLAUDE.md").write_text(f"# Notes\n\n{marker}\n",
                                        encoding="utf-8")

    said = scaffold.top_up(tmp_path)
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")

    assert "added" in said
    assert "aki_agent.inbox" in text
    assert text.rstrip().endswith("-->"), "the provenance line stays last"


def test_topping_up_twice_does_not_repeat_itself(tmp_path):
    from aki_agent import scaffold

    marker = f"<!-- written by {scaffold.OURS_MARKER} -->"
    (tmp_path / "CLAUDE.md").write_text(f"# Notes\n\n{marker}\n",
                                        encoding="utf-8")

    scaffold.top_up(tmp_path)
    second = scaffold.top_up(tmp_path)
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")

    assert second == ""
    assert text.count("aki_agent.inbox pending") == 1


def test_a_claude_md_the_person_wrote_is_never_appended_to(tmp_path):
    from aki_agent import scaffold

    (tmp_path / "CLAUDE.md").write_text("# my own notes\n", encoding="utf-8")

    said = scaffold.top_up(tmp_path)

    assert "not touched it" in said
    assert "aki_agent.inbox" not in (tmp_path / "CLAUDE.md").read_text(
        encoding="utf-8")


def test_the_dashboard_starts_without_a_console_window():
    """the maintainer: "the ONLY terminal show should be the Claude Code session."

    `/min` is still a console on the taskbar, and it takes focus on the way
    there.
    """
    from pathlib import Path as _Path

    from aki_agent import launcher, schedule

    text = launcher.windows_launcher(
        launcher.LauncherOptions(open_dashboard=True), _PACKAGE_ROOT)

    assert "dashboard.vbs" in text
    assert "/min" not in text
    assert (_PACKAGE_ROOT / "bin" / "dashboard.vbs").is_file(), \
        "named by the launcher, so it has to ship"
    # And the scheduled-task wrapper is still the other hidden one.
    assert schedule.hidden_runner().name == "run-task.vbs"


_PACKAGE_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# A program that replaces itself cannot ask itself for the replacement
# ---------------------------------------------------------------------------

class _Recorder:
    """Just enough of the upgrade log to see what was written down."""

    def __init__(self):
        self.steps = []

    def step(self, title, message, ok=True):
        self.steps.append((title, message, ok))


def test_the_repoint_runs_in_a_process_that_can_see_the_new_engine(monkeypatch):
    """Every upgrade on the Surface printed this, unnoticed for a day:

        That did not work: cannot import name 'launcher' from 'aki_agent'

    By the time that step runs, the environment has been repointed at the new
    engine -- but `aki_agent` was imported into the running process from the
    old location minutes earlier, and an already-imported package keeps the
    path it was imported from. Asking it for a submodule it has not loaded
    yet sends it looking in a folder that is now a shim.

    The consequence was not cosmetic: re-pointing is what keeps the scheduled
    tasks and the launcher aimed at the engine that exists, so every upgrade
    left them aimed at the one being deleted.

    A new process has no such history. This checks the work is handed to one.
    """
    from aki_agent import cli, engine

    calls = {}

    class _Done:
        returncode = 0
        stdout = "  ok - launcher: written\n"
        stderr = ""

    def fake_run(argv, **kwargs):
        calls["argv"] = list(argv)
        return _Done()

    monkeypatch.setattr(engine, "venv_python", lambda: Path(__file__))
    import subprocess

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(cli, "_repoint", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("re-pointed in the process that is being replaced")))

    record = _Recorder()
    failures = cli._repoint_after_upgrade(Path("."), record)     # noqa: SLF001

    assert failures == []
    assert calls["argv"][1:] == ["-m", "aki_agent.cli", "repair", "--yes"], (
        "the new engine was not the one asked to do the re-pointing")
    assert record.steps and record.steps[0][2] is True


def test_a_repoint_that_cannot_start_a_process_still_happens(monkeypatch):
    """The fallback matters: a re-point done by the old code beats none.

    If the environment has no python of its own to call -- which is a real
    state during an adoption, and on a machine somebody has moved folders
    around on -- the step is done here rather than skipped. It may be the
    outgoing version doing it, and that is still better than scheduled tasks
    left pointing at a folder about to be deleted.
    """
    from aki_agent import cli, engine

    done = {}
    monkeypatch.setattr(engine, "venv_python", lambda: None)
    monkeypatch.setattr(cli, "_repoint",
                        lambda *a, **k: done.setdefault("ran", []) or [])

    record = _Recorder()
    assert cli._repoint_after_upgrade(Path("."), record) == []   # noqa: SLF001
    assert "ran" in done, "the fallback never ran"

