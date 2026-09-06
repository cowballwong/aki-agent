"""The upgrade must not be able to destroy the thing it is upgrading.

WHAT THESE ARE ABOUT
--------------------
On 2026-08-20 a 0.5.0 -> 0.8.0 upgrade failed on Windows and left the product
unrunnable — twice, because re-running it repeated the damage. The root cause
was one line (`shutil.rmtree` cannot remove a ReadOnly directory), but the
reason a one-line bug became a destroyed install was the order of operations:
the working engine was deleted before the replacement existed.

So most of what is tested here is not "does the copy work" — that was already
covered — but **what is still standing after it does not work.**
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from aki_agent import engine, paths


@pytest.fixture
def release(tmp_path):
    """A folder shaped like an unzipped release."""
    root = tmp_path / "release"
    (root / "src" / "aki_agent").mkdir(parents=True)
    (root / "src" / "aki_agent" / "__init__.py").write_text(
        '__version__ = "9.9.9"\n', encoding="utf-8")
    (root / "src" / "aki_agent" / "engine.py").write_text(
        'COPIED = ("src", "bin", "skills", "library")\n', encoding="utf-8")
    (root / "bin").mkdir()
    (root / "bin" / "_bootstrap.py").write_text("# bootstrap\n",
                                                encoding="utf-8")
    (root / "skills").mkdir()
    (root / "skills" / "doctor").mkdir()
    (root / "library").mkdir()
    (root / "library" / "one.md").write_text("a skill\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname="aki-agent"\nversion = "9.9.9"\n', encoding="utf-8")
    return root


@pytest.fixture
def home(tmp_path, monkeypatch):
    folder = tmp_path / "Assistant" / "01_Config"
    folder.mkdir(parents=True)
    monkeypatch.setenv("AKI_AGENT_HOME", str(folder))
    monkeypatch.setattr(paths, "app_dir", lambda: folder)
    return folder


def _install(release) -> None:
    ok, message = engine.copy_engine(engine.plan(source=release))
    assert ok, message


# ---------------------------------------------------------------------------
# The manifest comes from the incoming release
# ---------------------------------------------------------------------------

def test_a_new_release_can_add_a_folder_the_old_one_never_heard_of(release):
    """`library` — 103 shipped skills — was silently never copied, because the
    *old* engine's file list decided what the *new* one consists of."""
    wanted = engine.manifest_for(release)

    assert wanted == ("src", "bin", "skills", "library")
    assert "library" in wanted


def test_an_unreadable_manifest_falls_back_rather_than_copying_nothing(tmp_path):
    empty = tmp_path / "not-a-package"
    empty.mkdir()
    assert engine.manifest_for(empty) == engine.COPIED


def test_a_manifest_that_is_not_a_list_of_names_is_ignored(tmp_path):
    odd = tmp_path / "odd"
    (odd / "src" / "aki_agent").mkdir(parents=True)
    (odd / "src" / "aki_agent" / "engine.py").write_text(
        "COPIED = (1, 2, 3)\n", encoding="utf-8")
    assert engine.manifest_for(odd) == engine.COPIED


def test_the_manifest_is_read_without_executing_the_package(tmp_path):
    """Parsed, not imported. This runs before anything about the incoming
    package has been checked, so importing it would be running unverified
    code as the first act of trusting it."""
    hostile = tmp_path / "hostile"
    (hostile / "src" / "aki_agent").mkdir(parents=True)
    (hostile / "src" / "aki_agent" / "engine.py").write_text(
        'import os\nos.environ["SHOULD_NOT_HAPPEN"] = "1"\n'
        'COPIED = ("src",)\n', encoding="utf-8")

    assert engine.manifest_for(hostile) == ("src",)
    assert "SHOULD_NOT_HAPPEN" not in os.environ


# ---------------------------------------------------------------------------
# A failure leaves the working engine alone
# ---------------------------------------------------------------------------

def test_a_copy_that_fails_leaves_the_previous_engine_untouched(
        release, home, monkeypatch):
    _install(release)
    before = (engine.engine_dir() / "bin" / "_bootstrap.py").read_text(
        encoding="utf-8")

    import shutil as shutil_module

    def explode(*_args, **_kwargs):
        raise OSError("disk went away")

    monkeypatch.setattr(shutil_module, "copytree", explode)

    ok, message = engine.copy_engine(engine.plan(source=release))

    assert not ok
    assert "still in place" in message
    # The thing that actually matters: it can still run.
    assert (engine.engine_dir() / "bin" / "_bootstrap.py").read_text(
        encoding="utf-8") == before


def test_a_staged_copy_missing_the_entry_point_is_never_swapped_in(
        release, home):
    _install(release)

    (release / "bin" / "_bootstrap.py").unlink()
    ok, message = engine.copy_engine(engine.plan(source=release))

    assert not ok
    assert "_bootstrap.py" in message
    assert (engine.engine_dir() / "bin" / "_bootstrap.py").is_file(), \
        "the working entry point must survive a bad release"


def test_failing_twice_is_no_worse_than_failing_once(release, home,
                                                     monkeypatch):
    """Re-running after a failure is what people actually do. Before this, each
    attempt repeated the same partial delete."""
    _install(release)
    (release / "bin" / "_bootstrap.py").unlink()

    for _ in range(3):
        ok, _message = engine.copy_engine(engine.plan(source=release))
        assert not ok
        assert (engine.engine_dir() / "bin" / "_bootstrap.py").is_file()


def test_nothing_is_left_lying_around_after_a_failure(release, home):
    _install(release)
    (release / "bin" / "_bootstrap.py").unlink()
    engine.copy_engine(engine.plan(source=release))

    staging = engine.engine_dir().with_name(
        engine.engine_dir().name + engine.STAGING_SUFFIX)
    assert not staging.exists()


# ---------------------------------------------------------------------------
# A success keeps a way back
# ---------------------------------------------------------------------------

def test_the_previous_engine_is_kept(release, home):
    _install(release)
    (engine.engine_dir() / "marker.txt").write_text("v1", encoding="utf-8")

    _install(release)

    previous = engine.engine_dir().with_name(
        engine.engine_dir().name + engine.PREVIOUS_SUFFIX)
    assert (previous / "marker.txt").read_text(encoding="utf-8") == "v1"


def test_rollback_puts_it_back(release, home):
    _install(release)
    (engine.engine_dir() / "marker.txt").write_text("v1", encoding="utf-8")
    _install(release)
    assert not (engine.engine_dir() / "marker.txt").exists()

    ok, message = engine.rollback()

    assert ok, message
    assert (engine.engine_dir() / "marker.txt").read_text(
        encoding="utf-8") == "v1"


def test_rollback_with_nothing_to_go_back_to_says_so(release, home):
    _install(release)
    ok, message = engine.rollback()
    assert not ok
    assert "nothing to roll back to" in message


def test_replacing_still_removes_files_the_new_release_dropped(release, home):
    """The reason the copy replaces rather than merges: a stale module that
    still imports is the worst kind of leftover."""
    _install(release)
    stale = engine.engine_dir() / "src" / "aki_agent" / "gone_in_v2.py"
    stale.write_text("# old\n", encoding="utf-8")

    _install(release)

    assert not stale.exists()


def test_a_successful_copy_records_what_it_copied(release, home):
    _install(release)
    manifest = engine.engine_dir() / engine.MANIFEST_FILE
    assert manifest.exists()
    assert "library" in manifest.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# ReadOnly — the root cause
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32",
                    reason="the ReadOnly attribute is a Windows failure")
def test_a_readonly_directory_no_longer_blocks_the_replace(release, home):
    """`rmtree` ends each directory with `os.rmdir`, which returns WinError 5
    on a ReadOnly directory. Every directory in the release carried it."""
    _install(release)
    victim = engine.engine_dir() / "skills"
    victim.chmod(victim.stat().st_mode & ~stat.S_IWRITE)

    ok, message = engine.copy_engine(engine.plan(source=release))

    assert ok, message


def test_the_installed_copy_does_not_keep_the_attribute(release, home):
    """Otherwise the fix lasts exactly one upgrade: `copytree` copies
    directory metadata, so the attribute is handed straight to the next one."""
    _install(release)

    still_set = [path for path in engine.engine_dir().rglob("*")
                 if path.is_dir() and not path.stat().st_mode & stat.S_IWRITE]
    assert not still_set


def test_force_rmtree_removes_a_readonly_tree(tmp_path):
    tree = tmp_path / "tree"
    (tree / "inner").mkdir(parents=True)
    (tree / "inner" / "file.txt").write_text("x", encoding="utf-8")
    for path in (tree / "inner", tree):
        path.chmod(path.stat().st_mode & ~stat.S_IWRITE)

    engine.force_rmtree(tree)

    assert not tree.exists()


# ---------------------------------------------------------------------------
# The preflight
# ---------------------------------------------------------------------------

def test_the_dry_run_reports_what_is_in_the_way(release, home):
    _install(release)
    victim = engine.engine_dir() / "skills"
    victim.chmod(victim.stat().st_mode & ~stat.S_IWRITE)

    notes = engine.readiness()

    assert any("read-only" in note for note in notes)
    victim.chmod(victim.stat().st_mode | stat.S_IWRITE)


def test_the_dry_run_is_quiet_when_there_is_no_engine_yet(home):
    assert engine.readiness() == []


# ---------------------------------------------------------------------------
# The written record (reported 2026-08-20: "we should have this log in every
# upgrade, make it save in _upgrade folder")
# ---------------------------------------------------------------------------

def test_a_log_is_written_as_it_goes_not_at_the_end(home):
    """A failing upgrade is one of the few operations that can stop its own
    process reaching the end. If the log were assembled and written last, the
    only run worth keeping would be the one that never got written."""
    from aki_agent import upgrade_log

    record = upgrade_log.Recorder("0.5.0", "0.8.0")
    assert record.path.exists(), "the file exists before anything finished"

    record.step("replace the engine", "went wrong", ok=False)
    written = record.path.read_text(encoding="utf-8")
    assert "FAILED" in written
    assert "0.5.0 -> 0.8.0" in written


def test_the_log_lands_in_the_upgrade_folder(home):
    from aki_agent import upgrade_log

    record = upgrade_log.Recorder("0.5.0", "0.8.0")

    assert record.path.parent == home / "_upgrade"
    assert record.path.parent == upgrade_log.folder()


def test_a_failed_upgrade_is_recorded_as_failed(home):
    from aki_agent import upgrade_log

    record = upgrade_log.Recorder("0.5.0", "0.8.0")
    record.finish("failed")

    written = record.path.read_text(encoding="utf-8")
    assert "**Outcome:** failed" in written
    # And it says the reassuring, true thing, because at that moment the user
    # does not know whether their assistant still works.
    assert "still in place" in written or "Re-running it is safe" in written


def test_two_upgrades_on_one_day_do_not_overwrite_each_other(home):
    from aki_agent import upgrade_log

    first = upgrade_log.Recorder("0.5.0", "0.8.0")
    second = upgrade_log.Recorder("0.8.0", "0.8.1")

    assert first.path != second.path
    assert first.path.exists() and second.path.exists()


def test_latest_finds_the_most_recent(home):
    from aki_agent import upgrade_log

    assert upgrade_log.latest() is None
    record = upgrade_log.Recorder("0.5.0", "0.8.0")
    assert upgrade_log.latest() == record.path


def test_the_scratch_folder_and_the_log_folder_are_not_the_same_place(home):
    """They were, until 2026-08-20 — and the unpack path deletes its scratch
    folder when it is done, which would have taken every upgrade log with it
    the first time one was written."""
    from aki_agent import upgrade_log

    assert engine.UNPACK_DIR_NAME != upgrade_log.FOLDER_NAME


# ---------------------------------------------------------------------------
# The swap, and a lock somebody else is about to release
# ---------------------------------------------------------------------------

def test_a_transient_lock_on_the_swap_is_waited_out(release, home,
                                                    monkeypatch):
    """Observed in the field on the first real 0.9.0 upgrade: the swap failed
    with WinError 5 and succeeded ninety seconds later with nothing changed —
    an indexer or a sync client holding the folder for a moment, not a running
    program."""
    _install(release)
    monkeypatch.setattr(engine, "SWAP_PAUSE", 0)

    real = Path.rename
    state = {"failures": 2}

    def sticky(self, target):
        if state["failures"] and self.name.endswith(engine.STAGING_SUFFIX):
            state["failures"] -= 1
            raise OSError("[WinError 5] Access is denied")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", sticky)

    ok, message = engine.copy_engine(engine.plan(source=release))

    assert ok, message
    assert state["failures"] == 0, "it should have retried"


def test_a_lock_that_never_clears_still_leaves_the_engine_working(
        release, home, monkeypatch):
    _install(release)
    monkeypatch.setattr(engine, "SWAP_PAUSE", 0)

    real = Path.rename

    def stuck(self, target):
        if self.name.endswith(engine.STAGING_SUFFIX):
            raise OSError("[WinError 5] Access is denied")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", stuck)

    ok, message = engine.copy_engine(engine.plan(source=release))

    assert not ok
    assert "holding that folder open" in message
    assert "running this again is safe" in message
    # The point of the whole design: it still works.
    assert (engine.engine_dir() / "bin" / "_bootstrap.py").is_file()
