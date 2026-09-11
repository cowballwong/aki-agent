"""What "update" has to mean for somebody who installed from the marketplace.

Somebody testing a fresh install was handed three commands to paste into a
terminal, and said -- reasonably -- that an update should resolve the problem
rather than produce more commands. Being two things, a Python engine and a
Claude Code plugin, is the package's problem and not the user's, and the
update path had quietly pushed it back onto them.

Two holes made that necessary, and this file is about both.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import engine


def make_package(folder: Path, version: str) -> Path:
    """The smallest thing `looks_like_the_package` will accept."""
    inside = folder / "src" / "aki_agent"
    inside.mkdir(parents=True, exist_ok=True)
    (inside / "__init__.py").write_text(
        f'__version__ = "{version}"' + chr(10), encoding="utf-8")
    (folder / "pyproject.toml").write_text(
        f'version = "{version}"' + chr(10), encoding="utf-8")
    (folder / "bin").mkdir(exist_ok=True)
    (folder / "bin" / "_bootstrap.py").write_text("", encoding="utf-8")
    return folder


# ---------------------------------------------------------------------------
# Where a marketplace update actually lands
# ---------------------------------------------------------------------------

def test_the_plugin_cache_is_searched(tmp_path, monkeypatch):
    """The whole of the first hole. `upgrade` looked in Downloads, Documents
    and Desktop -- every place a zip lands, and not the one place a
    marketplace update lands. It then said it could not find a release while
    the release sat on the disk."""
    monkeypatch.setattr(engine.paths, "home", lambda: tmp_path)
    cache = tmp_path / ".claude" / "plugins" / "cache" / "aki-agent" / "aki-agent"
    make_package(cache / "0.47.0", "0.47.0")
    make_package(cache / "0.47.1", "0.47.1")

    found = engine.newest_in_plugin_cache()

    assert found is not None
    assert found.name == "0.47.1"


def test_versions_are_compared_as_numbers(tmp_path, monkeypatch):
    """0.47.10 is newer than 0.47.9. Sorted as text it is not, and the update
    would hand somebody an older release while reporting success."""
    monkeypatch.setattr(engine.paths, "home", lambda: tmp_path)
    cache = tmp_path / ".claude" / "plugins" / "cache" / "m" / "aki-agent"
    make_package(cache / "0.47.9", "0.47.9")
    make_package(cache / "0.47.10", "0.47.10")

    assert engine.newest_in_plugin_cache().name == "0.47.10"


def test_a_folder_that_is_not_the_package_is_ignored(tmp_path, monkeypatch):
    """Other plugins live in the same cache. Copying one of those over
    somebody's engine is the worst outcome available here."""
    monkeypatch.setattr(engine.paths, "home", lambda: tmp_path)
    cache = tmp_path / ".claude" / "plugins" / "cache" / "m"
    (cache / "some-other-plugin" / "1.0.0").mkdir(parents=True)

    assert engine.newest_in_plugin_cache() is None


def test_no_cache_at_all_is_not_an_error(tmp_path, monkeypatch):
    """A zip install has no plugin cache, and must not be told off for it."""
    monkeypatch.setattr(engine.paths, "home", lambda: tmp_path)
    assert engine.newest_in_plugin_cache() is None


def test_the_cache_is_preferred_when_it_is_newer(tmp_path, monkeypatch):
    """Ahead of a zip in Downloads: for a marketplace user, a zip lying about
    is more likely to be an old copy they kept than the thing they just
    updated to."""
    monkeypatch.setattr(engine.paths, "home", lambda: tmp_path)
    installed = make_package(tmp_path / "home" / "engine", "0.47.0")
    monkeypatch.setattr(engine, "engine_dir", lambda: installed)
    monkeypatch.setattr(engine, "running_from", lambda: installed)
    cache = tmp_path / ".claude" / "plugins" / "cache" / "m" / "aki-agent"
    make_package(cache / "0.48.0", "0.48.0")
    monkeypatch.setattr(engine, "newest_release_nearby", lambda: None)

    assert engine._default_source().name == "0.48.0"


def test_a_cache_no_newer_than_what_is_installed_is_not_preferred(
        tmp_path, monkeypatch):
    """Running the update twice must not reinstall the same version over the
    top of itself just because the folder is there."""
    monkeypatch.setattr(engine.paths, "home", lambda: tmp_path)
    installed = make_package(tmp_path / "home" / "engine", "0.48.0")
    monkeypatch.setattr(engine, "engine_dir", lambda: installed)
    monkeypatch.setattr(engine, "running_from", lambda: installed)
    cache = tmp_path / ".claude" / "plugins" / "cache" / "m" / "aki-agent"
    make_package(cache / "0.47.1", "0.47.1")
    elsewhere = make_package(tmp_path / "Downloads" / "rel", "0.49.0")
    monkeypatch.setattr(engine, "newest_release_nearby", lambda: elsewhere)

    assert engine._default_source() == elsewhere


# ---------------------------------------------------------------------------
# A launcher that is not there
# ---------------------------------------------------------------------------

def test_repair_writes_a_launcher_that_was_never_created(tmp_path, monkeypatch):
    """The second hole. `_repoint` rewrote a launcher only `if
    launcher_file.exists()`, so an install whose setup stopped before its last
    step could be repaired, upgraded and health-checked for ever without
    anybody producing the file the person is supposed to double-click --
    and every one of those reported success, because every step they knew
    about had in fact succeeded."""
    from aki_agent import cli, launcher, schedule, telegram_setup

    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True)

    monkeypatch.setattr(schedule, "installed_names", lambda: set())
    monkeypatch.setattr(schedule, "all_tasks", lambda: [])
    monkeypatch.setattr(schedule, "runner_script", lambda root: root / "run")
    monkeypatch.setattr(schedule, "remember_install_root", lambda root: None)
    monkeypatch.setattr(telegram_setup, "status",
                        lambda: type("S", (), {"plugin_installed": False})())

    written = {}

    def fake_write(options, root, confirmed=False):
        written["options"] = options
        launcher.launcher_path().write_text("made", encoding="utf-8")
        return True, str(launcher.launcher_path())

    monkeypatch.setattr(launcher, "write_launcher", fake_write)
    monkeypatch.setattr(cli, "_register_channel_listener",
                        lambda *a, **k: None, raising=False)

    assert not launcher.launcher_path().exists()
    cli._repoint(tmp_path / "engine")                        # noqa: SLF001

    assert launcher.launcher_path().exists()
    assert written["options"].open_dashboard is True
