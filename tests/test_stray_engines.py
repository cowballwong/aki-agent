"""Leftover `engine (2)` folders — cleared, but only when certainly litter.

WHY (reported 2026-08-20)
-----------------------
He opened his config folder and asked *"why so many engine folders?"* There
were four — `engine (1)` to `engine (4)` — each created within a minute of an
upgrade, and every one of them completely empty, hidden files included.

**What creates them is not established.** The upgrade log for each of those
minutes records the swap as successful, and the swap this package performs
never invents a numbered name: it renames `engine` to `engine.old` and puts
the new one in place. They stopped appearing after 17:48 that day, which fits
something outside this code holding the folder open — a hypothesis, not a
finding, and it is written down as one.

So the code does the part that is certain. An empty numbered folder beside
the engine is litter whoever dropped it, and clearing litter needs no theory
about where it came from. The rule that carries the risk is the other one:
anything with something inside is left alone and reported, because at that
point a guess about what it is would be doing real work.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import engine


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    (tmp_path / "engine").mkdir()
    (tmp_path / "engine.old").mkdir()
    return tmp_path


def test_an_empty_numbered_folder_is_recognised_as_litter(home):
    (home / "engine (1)").mkdir()
    (home / "engine (12)").mkdir()

    assert [p.name for p in engine.stray_engine_dirs(home)] == [
        "engine (1)", "engine (12)"]


def test_the_real_engine_and_its_backup_are_never_candidates(home):
    """`engine.old` is the rollback. Sweeping it up would take away the only
    way back from a bad upgrade, which is the one thing that must survive."""
    assert engine.stray_engine_dirs(home) == []


def test_a_folder_that_merely_looks_similar_is_left_alone(home):
    """`engine (x)`, `engine backup`, `engine-2` — none of them match.

    The pattern is deliberately narrow. Something this deletes should be
    recognisable at a glance as one specific machine-made name, not as
    anything a person might have called a folder themselves.
    """
    for name in ("engine (x)", "engine backup", "engine-2", "engines (1)"):
        (home / name).mkdir()

    assert engine.stray_engine_dirs(home) == []


def test_clearing_removes_the_empty_ones(home):
    (home / "engine (1)").mkdir()
    (home / "engine (2)").mkdir()

    removed, kept = engine.clear_stray_engines(home)

    assert (removed, kept) == (2, [])
    assert sorted(p.name for p in home.iterdir()) == ["engine", "engine.old"]


def test_a_leftover_with_anything_in_it_is_kept_and_reported(home):
    """The rule that carries the risk.

    It might be somebody's own copy, made by hand before an upgrade they were
    nervous about. Deleting that because the name matched a pattern would be
    the single worst thing in this file.
    """
    (home / "engine (1)").mkdir()
    (home / "engine (2)").mkdir()
    (home / "engine (2)" / "notes.txt").write_text("mine", encoding="utf-8")

    removed, kept = engine.clear_stray_engines(home)

    assert removed == 1
    assert kept == ["engine (2)"]
    assert (home / "engine (2)" / "notes.txt").exists()


def test_a_hidden_file_still_counts_as_not_empty(home):
    """"Empty" has to mean empty, not "empty in Explorer".

    A dot-file is invisible in a listing and is still somebody's data. This
    is checked because the obvious implementation -- iterdir on visible names
    -- would pass every other test in this file and delete it.
    """
    (home / "engine (1)").mkdir()
    (home / "engine (1)" / ".env").write_text("SECRET=1", encoding="utf-8")

    removed, kept = engine.clear_stray_engines(home)

    assert removed == 0
    assert kept == ["engine (1)"]
    assert (home / "engine (1)" / ".env").exists()


def test_a_nested_empty_folder_still_counts_as_not_empty(home):
    """Something made a folder tree in there. That is not litter this owns."""
    (home / "engine (1)" / "src" / "deep").mkdir(parents=True)

    removed, kept = engine.clear_stray_engines(home)

    assert removed == 0
    assert kept == ["engine (1)"]


def test_doctor_says_nothing_when_there_is_nothing_to_say(monkeypatch, home):
    """Absence of news is not news — the rule the whole package follows."""
    from aki_agent import doctor

    monkeypatch.setattr(engine, "stray_engine_dirs", lambda beside=None: [])
    check = doctor.check_no_stray_engines()

    assert check.ok


def test_doctor_distinguishes_litter_from_something_it_will_not_touch(
        monkeypatch, home):
    """Two different sentences, because they need two different actions.

    Empty ones the next upgrade clears by itself and nobody need do anything.
    A full one is a decision only the person can make, so it says so and stops.
    """
    from aki_agent import doctor

    (home / "engine (1)").mkdir()
    (home / "engine (2)").mkdir()
    (home / "engine (2)" / "thing.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(engine, "stray_engine_dirs",
                        lambda beside=None: [home / "engine (1)",
                                             home / "engine (2)"])

    check = doctor.check_no_stray_engines()

    assert not check.ok
    assert check.warning_only, "nothing is broken; this is a tidiness note"
    assert "engine (2)" in check.detail
    assert "not touched it" in check.detail
