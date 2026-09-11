"""A scheduled task on macOS cannot read the folder people keep work in.

Found on a real Mac: a one-off job fired exactly on time and died
with exit 126, because macOS would not let a process started by launchd read a
script inside `Documents`. Nothing was wrong with the job, the schedule or the
script — TCC was doing its job to a process with no Full Disk Access.

Which makes `~/Documents/Workspace`, the folder setup used to suggest, a place
where every scheduled task installs cleanly, reports success, and then fails at
every firing for as long as it exists, saying nothing. The same shape this
codebase keeps returning to.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import doctor, paths, scaffold


# ---------------------------------------------------------------------------
# Knowing which folders they are
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["Documents", "Desktop", "Downloads"])
def test_the_three_folders_macos_restricts(tmp_path, monkeypatch, name):
    monkeypatch.setattr(paths, "is_macos", lambda: True)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    target = tmp_path / name / "Workspace"
    target.mkdir(parents=True)

    assert paths.inside_a_protected_folder(target) == name


def test_somewhere_else_in_the_home_folder_is_fine(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "is_macos", lambda: True)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    target = tmp_path / "Workspace"
    target.mkdir()

    assert paths.inside_a_protected_folder(target) == ""


def test_windows_has_no_such_restriction(tmp_path, monkeypatch):
    """Windows has no TCC, and a warning about a restriction that does not
    exist is worse than no warning — it teaches people to ignore the ones that
    do."""
    monkeypatch.setattr(paths, "is_macos", lambda: False)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    target = tmp_path / "Documents" / "Workspace"
    target.mkdir(parents=True)

    assert paths.inside_a_protected_folder(target) == ""


# ---------------------------------------------------------------------------
# Not suggesting it in the first place
# ---------------------------------------------------------------------------

def test_macos_setup_does_not_suggest_documents(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "is_macos", lambda: True)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    monkeypatch.setattr(scaffold.files_connector, "detect", lambda: [])
    (tmp_path / "Documents").mkdir()

    assert "Documents" not in str(scaffold.suggest_root())


def test_windows_setup_still_suggests_documents(tmp_path, monkeypatch):
    """The familiar place stays the suggestion where it costs nothing."""
    monkeypatch.setattr(paths, "is_macos", lambda: False)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    monkeypatch.setattr(scaffold.files_connector, "detect", lambda: [])
    (tmp_path / "Documents").mkdir()

    assert "Documents" in str(scaffold.suggest_root())


# ---------------------------------------------------------------------------
# Saying so when somebody chose it anyway
# ---------------------------------------------------------------------------

class Loaded:
    def __init__(self, root):
        self.layout = type("L", (), {"root": str(root)})()


def test_a_workspace_in_documents_is_reported(tmp_path, monkeypatch):
    """Not refused. Choosing Documents is allowed; discovering months later
    that the morning summary silently never ran is not."""
    monkeypatch.setattr(paths, "is_macos", lambda: True)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    root = tmp_path / "Documents" / "Workspace"
    root.mkdir(parents=True)
    from aki_agent import schedule
    monkeypatch.setattr(schedule, "installed_names", lambda: {"com.aki.x"})

    check = doctor.check_scheduling_can_reach_the_workspace(Loaded(root))

    assert check.ok is False
    assert check.warning_only is True
    assert "Documents" in check.detail
    assert "Full Disk Access" in check.fix


def test_nothing_scheduled_yet_is_said_out_loud(tmp_path, monkeypatch):
    """The difference between "this will break" and "this is breaking now" is
    the difference between a note somebody reads and one they panic about."""
    monkeypatch.setattr(paths, "is_macos", lambda: True)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    root = tmp_path / "Desktop" / "Workspace"
    root.mkdir(parents=True)
    from aki_agent import schedule
    monkeypatch.setattr(schedule, "installed_names", lambda: set())

    check = doctor.check_scheduling_can_reach_the_workspace(Loaded(root))

    assert "nothing is failing today" in check.detail


def test_it_is_one_of_the_checks_that_actually_runs():
    import inspect

    source = inspect.getsource(doctor.run_all)
    assert "check_scheduling_can_reach_the_workspace(loaded)" in source


# ---------------------------------------------------------------------------
# Refusing to create a task that could only ever fail
# ---------------------------------------------------------------------------

def _a_runner_at(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    runner = folder / "run-task.command"
    runner.write_text("#!/bin/bash\n", encoding="utf-8")
    return runner


def test_a_task_whose_runner_is_in_documents_is_not_created(tmp_path,
                                                            monkeypatch):
    """The exists() check above this one passes every time: `install` runs in
    a Terminal, and a Terminal can read Documents. launchd cannot. Seven tasks
    walked through that gap and died at every firing."""
    from aki_agent import schedule

    monkeypatch.setattr(paths, "is_macos", lambda: True)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    monkeypatch.setattr(schedule, "running_elevated", lambda: False)
    runner = _a_runner_at(tmp_path / "Documents" / "Workspace" / "bin")

    ok, message = schedule.install(schedule.DEFAULT_TASKS[0], runner,
                                   confirmed=True)

    assert ok is False
    assert "Documents" in message
    assert "Nothing was scheduled" in message


def test_the_same_runner_somewhere_unrestricted_is_allowed_through(
        tmp_path, monkeypatch):
    """Whatever happens next, it is not this refusal -- the check must not
    become a reason nobody can schedule anything."""
    from aki_agent import schedule

    monkeypatch.setattr(paths, "is_macos", lambda: True)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    monkeypatch.setattr(schedule, "running_elevated", lambda: False)
    runner = _a_runner_at(tmp_path / "Aki-Agent" / "bin")

    _, message = schedule.install(schedule.DEFAULT_TASKS[0], runner,
                                  confirmed=True)

    assert "Documents" not in message


def test_windows_schedules_from_documents_without_complaint(tmp_path,
                                                            monkeypatch):
    from aki_agent import schedule

    monkeypatch.setattr(paths, "is_macos", lambda: False)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    runner = _a_runner_at(tmp_path / "Documents" / "Workspace" / "bin")

    _, message = schedule.install(schedule.DEFAULT_TASKS[0], runner,
                                  confirmed=True)

    assert "macOS" not in message


# ---------------------------------------------------------------------------
# Moving it, as one command rather than three manual steps
# ---------------------------------------------------------------------------

class _Args:
    def __init__(self, to="", yes=False):
        self.to = to
        self.yes = yes


def _config_rooted_at(root):
    layout = type("L", (), {"root": str(root)})()
    return type("C", (), {"layout": layout})()


def test_moving_into_another_restricted_folder_is_refused(tmp_path,
                                                          monkeypatch, capsys):
    """Documents to Desktop is not a fix, and a command that says "done"
    after doing it would be the same silent failure wearing a new hat."""
    from aki_agent import cli

    monkeypatch.setattr(paths, "is_macos", lambda: True)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    source = tmp_path / "Documents" / "Workspace"
    source.mkdir(parents=True)
    monkeypatch.setattr(cli, "_load_config",
                        lambda: (_config_rooted_at(source), ""))

    code = cli.cmd_move_workspace(_Args(to=str(tmp_path / "Desktop" / "W"),
                                        yes=True))

    assert code == 1
    assert "Desktop" in capsys.readouterr().out
    assert source.exists(), "nothing may be moved when the target is refused"


def test_nothing_moves_without_yes(tmp_path, monkeypatch, capsys):
    from aki_agent import cli

    monkeypatch.setattr(paths, "is_macos", lambda: True)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    source = tmp_path / "Documents" / "Workspace"
    source.mkdir(parents=True)
    monkeypatch.setattr(cli, "_load_config",
                        lambda: (_config_rooted_at(source), ""))

    code = cli.cmd_move_workspace(_Args(to=str(tmp_path / "Aki-Agent")))

    assert code == 0
    assert "Nothing moved" in capsys.readouterr().out
    assert source.exists()


def test_an_occupied_target_is_not_merged(tmp_path, monkeypatch, capsys):
    """Two workspaces poured into one folder is not a thing anybody can undo."""
    from aki_agent import cli

    monkeypatch.setattr(paths, "is_macos", lambda: True)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    source = tmp_path / "Documents" / "Workspace"
    source.mkdir(parents=True)
    target = tmp_path / "Aki-Agent"
    target.mkdir()
    (target / "something-of-theirs.md").write_text("mine", encoding="utf-8")
    monkeypatch.setattr(cli, "_load_config",
                        lambda: (_config_rooted_at(source), ""))

    code = cli.cmd_move_workspace(_Args(to=str(target), yes=True))

    assert code == 1
    assert "not empty" in capsys.readouterr().out
    assert (target / "something-of-theirs.md").read_text(
        encoding="utf-8") == "mine"


def test_the_move_happens_and_the_new_location_is_recorded(tmp_path,
                                                           monkeypatch, capsys):
    """The part that touches somebody's actual files. Re-pointing is stubbed
    here because launchd is not on this machine; what is checked is that the
    work arrives intact and that the config is saved BEFORE re-pointing reads
    it back -- saved after, the launcher would be written against a path that
    no longer exists."""
    from aki_agent import cli
    from aki_agent import config as config_module

    monkeypatch.setattr(paths, "is_macos", lambda: True)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    source = tmp_path / "Documents" / "Workspace"
    (source / "03_Workspace").mkdir(parents=True)
    (source / "03_Workspace" / "notes.md").write_text("theirs",
                                                      encoding="utf-8")
    config = _config_rooted_at(source)
    monkeypatch.setattr(cli, "_load_config", lambda: (config, ""))

    saved_root_at_save_time = {}
    monkeypatch.setattr(config_module, "save",
                        lambda c, path=None: saved_root_at_save_time
                        .setdefault("root", str(c.layout.root)))
    seen = {}

    def _remember_and_succeed(root=None):
        seen["root"] = root
        return 0

    monkeypatch.setattr(cli, "_repoint", _remember_and_succeed)

    target = tmp_path / "Aki-Agent"
    code = cli.cmd_move_workspace(_Args(to=str(target), yes=True))

    assert code == 0
    assert not source.exists()
    assert (target / "03_Workspace" / "notes.md").read_text(
        encoding="utf-8") == "theirs"
    assert saved_root_at_save_time["root"] == str(target)
    assert seen["root"] == target / "01_Config" / "engine"


# ---------------------------------------------------------------------------
# Not installing there in the first place
# ---------------------------------------------------------------------------

class _ScaffoldArgs:
    def __init__(self, root="", yes=False):
        self.root = root
        self.yes = yes
        self.workspaces = ""
        self.no_examples = True


class _Layout:
    def __init__(self):
        self.root = None
        self.workspaces = ()
        self.schema = None


class _Config:
    def __init__(self):
        self.layout = _Layout()


def test_a_first_install_in_documents_goes_somewhere_that_works(
        tmp_path, monkeypatch, capsys):
    """A note saying "this will not work" is still an install that does not
    work. Nothing is asked; the folder is changed and said out loud."""
    from aki_agent import cli

    monkeypatch.setattr(paths, "is_macos", lambda: True)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    started_in = tmp_path / "Documents"
    started_in.mkdir()
    monkeypatch.setattr(cli.paths_module, "default_root", lambda: started_in)
    config = _Config()
    monkeypatch.setattr(cli, "_load_config", lambda: (config, ""))

    cli.cmd_scaffold(_ScaffoldArgs())

    out = capsys.readouterr().out
    assert config.layout.root == tmp_path / "Aki-Agent"
    assert "Not installing in" in out
    assert str(tmp_path / "Aki-Agent") in out


def test_the_plan_is_built_against_the_folder_that_is_announced(
        tmp_path, monkeypatch, capsys):
    """Changed after `scaffold.plan()` and the plan creates Documents while
    the message names somewhere else -- the config and the disk disagreeing,
    which is the failure `default_root()` exists to prevent."""
    from aki_agent import cli, scaffold

    monkeypatch.setattr(paths, "is_macos", lambda: True)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    started_in = tmp_path / "Documents"
    started_in.mkdir()
    monkeypatch.setattr(cli.paths_module, "default_root", lambda: started_in)
    monkeypatch.setattr(cli, "_load_config", lambda: (_Config(), ""))

    planned = []
    real_plan = scaffold.plan
    monkeypatch.setattr(scaffold, "plan",
                        lambda root, **kw: planned.append(root) or
                        real_plan(root, **kw))

    cli.cmd_scaffold(_ScaffoldArgs())

    assert planned == [tmp_path / "Aki-Agent"]


def test_an_explicit_root_is_a_decision_and_is_honoured(tmp_path, monkeypatch,
                                                        capsys):
    """`--root` is somebody saying where they want it. Overriding that would
    be worse than the problem: the install would land somewhere they did not
    name and could not find."""
    from aki_agent import cli

    monkeypatch.setattr(paths, "is_macos", lambda: True)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    chosen = tmp_path / "Documents" / "Mine"
    config = _Config()
    monkeypatch.setattr(cli, "_load_config", lambda: (config, ""))

    cli.cmd_scaffold(_ScaffoldArgs(root=str(chosen)))

    assert config.layout.root == chosen
    assert "Not installing in" not in capsys.readouterr().out


def test_windows_installs_in_documents_without_being_moved(tmp_path,
                                                           monkeypatch, capsys):
    """Windows has no such restriction, and moving somebody's folder for a
    problem their machine does not have is its own bug."""
    from aki_agent import cli

    monkeypatch.setattr(paths, "is_macos", lambda: False)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    started_in = tmp_path / "Documents"
    started_in.mkdir()
    monkeypatch.setattr(cli.paths_module, "default_root", lambda: started_in)
    config = _Config()
    monkeypatch.setattr(cli, "_load_config", lambda: (config, ""))

    cli.cmd_scaffold(_ScaffoldArgs())

    assert config.layout.root == started_in
    assert "Not installing in" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# launchd hands a job four directories, and `claude` is in none of them
#
# Reported from a real Mac, 2026-09-11. Every scheduled task raised
# ClaudeNotFound and died, while the same command run by hand in a terminal
# worked. launchd gives its children `/usr/bin:/bin:/usr/sbin:/sbin`; Claude
# Code's installer puts `claude` in `~/.local/bin`.


def test_claude_is_found_when_path_does_not_contain_it(tmp_path, monkeypatch):
    from aki_agent import runner

    installed = tmp_path / ".local" / "bin" / "claude"
    installed.parent.mkdir(parents=True)
    installed.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    monkeypatch.setattr(runner.paths, "is_windows", lambda: False)
    monkeypatch.setattr(paths, "extra_bin_dirs", lambda: (installed.parent,))

    assert runner.find_claude() == str(installed)


def test_the_path_still_wins_when_it_has_an_answer(tmp_path, monkeypatch):
    """Only after PATH has failed. Somebody who put a particular `claude` on
    their PATH chose it, and a list of guesses must never overrule that."""
    from aki_agent import runner

    theirs = tmp_path / "theirs" / "claude"
    theirs.parent.mkdir(parents=True)
    theirs.write_text("#!/bin/sh\n", encoding="utf-8")
    ours = tmp_path / ".local" / "bin" / "claude"
    ours.parent.mkdir(parents=True)
    ours.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(runner.shutil, "which", lambda name: str(theirs))
    monkeypatch.setattr(runner.paths, "is_windows", lambda: False)
    monkeypatch.setattr(paths, "extra_bin_dirs", lambda: (ours.parent,))

    assert runner.find_claude() == str(theirs)


def test_it_still_says_so_when_claude_really_is_not_there(tmp_path,
                                                          monkeypatch):
    """The guesses must not turn a missing install into a confusing failure
    further down."""
    import pytest as _pytest

    from aki_agent import runner

    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    monkeypatch.setattr(runner.paths, "is_windows", lambda: False)
    monkeypatch.setattr(paths, "extra_bin_dirs",
                        lambda: (tmp_path / "nowhere",))

    with _pytest.raises(runner.ClaudeNotFound):
        runner.find_claude()


def test_the_two_lists_are_one_list(tmp_path, monkeypatch):
    """0.48.5 shipped this as a PATH in the plist and a separate list of
    candidates in `find_claude()`. Within the hour a scheduled run failed
    because `bun` -- which the channel plugins run on -- was in neither.

    Pinned because the failure mode is silent: nothing errors when the two
    drift, a scheduled task just cannot find something."""
    from aki_agent import schedule

    monkeypatch.setattr(schedule.paths, "home", lambda: tmp_path)

    written = schedule.launchd_plist(schedule.DEFAULT_TASKS[0],
                                     tmp_path / "bin" / "run-task.command")

    for folder in paths.extra_bin_dirs():
        assert folder.as_posix() in written, folder


def test_bun_is_on_the_path_so_the_channel_plugins_can_start(tmp_path,
                                                             monkeypatch):
    """Reported from a real Mac: the task ran, and the Telegram plugin could
    not start because `bun` was not found."""
    monkeypatch.setattr(paths, "home", lambda: tmp_path)

    assert f"{tmp_path.as_posix()}/.bun/bin" in paths.job_path()


def test_the_plist_carries_a_path_for_whatever_the_task_runs(tmp_path,
                                                             monkeypatch):
    """The other half. `find_claude` fixes this package; the plist fixes
    everything the task goes on to invoke."""
    from aki_agent import schedule

    monkeypatch.setattr(schedule.paths, "home", lambda: tmp_path)

    written = schedule.launchd_plist(schedule.DEFAULT_TASKS[0],
                                     tmp_path / "bin" / "run-task.command")

    assert "<key>EnvironmentVariables</key>" in written
    assert f"{tmp_path.as_posix()}/.local/bin" in written
    assert "/opt/homebrew/bin" in written
    assert "/usr/bin" in written


def test_the_plist_path_is_expanded_not_a_tilde(tmp_path, monkeypatch):
    """launchd does not expand `~` inside a plist value, so a tilde there is
    a directory that does not exist rather than the user's home."""
    from aki_agent import schedule

    monkeypatch.setattr(schedule.paths, "home", lambda: tmp_path)

    written = schedule.launchd_plist(schedule.DEFAULT_TASKS[0],
                                     tmp_path / "bin" / "run-task.command")
    inside = written.split("<key>EnvironmentVariables</key>", 1)[1]

    assert "~" not in inside.split("</dict>", 1)[0]
