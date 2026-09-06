"""The environment handed to a process that must be the NEW engine.

A program that replaces itself has one recurring trap: the process doing the
replacing is the version being replaced. `upgrade` works around it with a
subprocess; these tests are about that subprocess actually getting there.
"""

from __future__ import annotations

from aki_agent import engine


# ---------------------------------------------------------------------------
# The environment a new process needs to be the NEW engine
# ---------------------------------------------------------------------------

def test_a_stale_package_on_pythonpath_is_dropped(tmp_path, monkeypatch):
    """The defect this exists for (reported 2026-09-04).

    `upgrade` hands the re-pointing to a fresh process so the NEW code does
    it. The bootstrap had exported the OLD package's `src` on `PYTHONPATH`,
    the child inherited it, and an explicit `PYTHONPATH` beats an editable
    install -- so the fresh process ran 0.41.3 and rewrote his launcher
    without the `TELEGRAM_STATE_DIR` line 0.41.4 added.
    """
    old = tmp_path / "old-release" / "src"
    (old / "aki_agent").mkdir(parents=True)
    target = tmp_path / "engine"
    (target / "src" / "aki_agent").mkdir(parents=True)

    monkeypatch.setenv("PYTHONPATH", str(old))

    assert "PYTHONPATH" not in engine.env_for(target)


def test_the_engine_being_run_stays_on_the_path(tmp_path, monkeypatch):
    target = tmp_path / "engine"
    mine = target / "src"
    (mine / "aki_agent").mkdir(parents=True)

    monkeypatch.setenv("PYTHONPATH", str(mine))

    assert engine.env_for(target)["PYTHONPATH"] == str(mine)


def test_someone_elses_pythonpath_is_left_alone(tmp_path, monkeypatch):
    """It only removes what shadows this package. Anything else is theirs."""
    theirs = tmp_path / "their-own-library"
    theirs.mkdir()
    target = tmp_path / "engine"
    (target / "src" / "aki_agent").mkdir(parents=True)

    monkeypatch.setenv("PYTHONPATH", str(theirs))

    assert engine.env_for(target)["PYTHONPATH"] == str(theirs)


def test_no_pythonpath_at_all_is_not_invented(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    assert "PYTHONPATH" not in engine.env_for(tmp_path)


# ---------------------------------------------------------------------------
# What an install is made of
# ---------------------------------------------------------------------------

def test_the_manifest_is_a_file_that_exists_in_this_checkout():
    """Every entry has to be real, or an install is missing part of itself."""
    from pathlib import Path

    root = Path(engine.__file__).resolve().parents[2]
    missing = [one for one in engine.COPIED if not (root / one).exists()]
    assert not missing, missing
