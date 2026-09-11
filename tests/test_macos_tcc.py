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
