"""Bringing somebody's own assistant across, and being honest about what stays.

The failure this file guards against is not "the import did not work". It is
"the import worked, said so, and quietly left a third of it behind" — which is
the bug this codebase found in its own upgrade path the same morning, where
103 files never copied and every check passed.

So most of these assert on `skipped` and on what `report()` says, not on what
came across.
"""

from __future__ import annotations

import pytest

from aki_agent import importer


@pytest.fixture
def theirs(tmp_path):
    """A folder shaped like something somebody built themselves."""
    root = tmp_path / "my-agent"
    (root / "prompts").mkdir(parents=True)
    (root / "notes").mkdir()
    (root / "scripts").mkdir()
    (root / ".venv" / "lib").mkdir(parents=True)

    (root / "CLAUDE.md").write_text("You are my assistant.\n", encoding="utf-8")
    (root / "prompts" / "persona.md").write_text("Be brief.\n", encoding="utf-8")
    (root / "config.yaml").write_text("name: Sam\n", encoding="utf-8")
    (root / "notes" / "clients.md").write_text("things\n", encoding="utf-8")
    (root / "notes" / "ideas.txt").write_text("more things\n", encoding="utf-8")
    (root / "scripts" / "run.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "scripts" / "start.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "cron.yaml").write_text("daily: 8am\n", encoding="utf-8")
    (root / "secrets.yaml").write_text("key: sk-do-not-read\n",
                                       encoding="utf-8")
    (root / ".env").write_text("TOKEN=nope\n", encoding="utf-8")
    (root / ".venv" / "lib" / "thing.py").write_text("x\n", encoding="utf-8")
    return root


def kinds(found, kind):
    return {one.path.name for one in found.of_kind(kind)}


# ---------------------------------------------------------------------------
# What comes
# ---------------------------------------------------------------------------

def test_their_instructions_are_recognised(theirs):
    found = importer.survey(theirs)
    assert "CLAUDE.md" in kinds(found, importer.INSTRUCTIONS)
    assert "persona.md" in kinds(found, importer.INSTRUCTIONS)


def test_their_notes_and_settings_are_recognised(theirs):
    found = importer.survey(theirs)
    assert {"clients.md", "ideas.txt"} <= kinds(found, importer.NOTES)
    assert "config.yaml" in kinds(found, importer.SETTINGS)


def test_a_timer_is_recognised_as_a_schedule_not_a_setting(theirs):
    found = importer.survey(theirs)
    assert "cron.yaml" in kinds(found, importer.SCHEDULE)


def test_dependency_folders_are_not_even_looked_at(theirs):
    found = importer.survey(theirs)
    assert not [one for one in found.items if ".venv" in str(one.path)]


# ---------------------------------------------------------------------------
# What does not, and why it must say so
# ---------------------------------------------------------------------------

def test_their_code_does_not_come(theirs):
    """Their Python is theirs; this package has its own engine. A "bring the
    scripts too" import stops being an import and becomes a bad integration."""
    found = importer.survey(theirs)
    code = found.of_kind(importer.CODE)

    assert {"run.py", "start.sh"} <= {one.path.name for one in code}
    assert all(not one.takeable for one in code)
    assert all("own engine" in one.why_skipped for one in code)


def test_a_secret_is_classified_before_anything_else_can_claim_it(theirs):
    """`secrets.yaml` is a settings file by every other test here. Order of
    classification is what stops it being treated as one."""
    found = importer.survey(theirs)
    secrets = {one.path.name for one in found.of_kind(importer.SECRET)}

    assert "secrets.yaml" in secrets
    assert ".env" in secrets
    assert "secrets.yaml" not in kinds(found, importer.SETTINGS)


def test_a_secret_is_never_takeable(theirs):
    found = importer.survey(theirs)
    assert all(not one.takeable for one in found.of_kind(importer.SECRET))


def test_something_far_too_large_to_be_a_note_is_left_behind(tmp_path):
    root = tmp_path / "agent"
    root.mkdir()
    (root / "log.md").write_text("x" * (importer.TOO_BIG + 10),
                                 encoding="utf-8")

    only = importer.survey(root).items[0]

    assert not only.takeable
    assert "too big" in only.why_skipped


def test_every_skipped_item_carries_a_reason(theirs):
    """A skipped file with no reason is the same as a silently dropped one."""
    found = importer.survey(theirs)
    assert found.skipped
    assert all(one.why_skipped for one in found.skipped)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def test_the_report_names_what_is_not_coming(theirs):
    text = importer.report(importer.survey(theirs))
    assert "NOT coming, and why" in text
    assert "own engine" in text
    assert "password or key" in text


def test_the_report_promises_their_folder_is_untouched(theirs):
    text = importer.report(importer.survey(theirs))
    assert "moved, changed or deleted" in text


def test_the_report_groups_reasons_rather_than_listing_every_file(theirs):
    """Forty lines of "skipped" is a wall nobody reads; the reason is the
    useful part."""
    text = importer.report(importer.survey(theirs))
    assert text.count("own engine") == 1


def test_a_folder_that_is_not_there_says_so_rather_than_crashing(tmp_path):
    found = importer.survey(tmp_path / "nope")
    assert not found.items
    assert "not a folder that exists" in importer.report(found)


def test_an_empty_folder_says_nothing_can_come(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert "nothing here can be brought across" in importer.report(
        importer.survey(empty))


# ---------------------------------------------------------------------------
# It only ever reads
# ---------------------------------------------------------------------------

def test_surveying_changes_nothing_in_their_folder(theirs):
    before = {path: path.stat().st_mtime for path in theirs.rglob("*")
              if path.is_file()}

    importer.survey(theirs)

    after = {path: path.stat().st_mtime for path in theirs.rglob("*")
             if path.is_file()}
    assert before == after
    assert set(before) == set(after), "no file may be added or removed"


def test_the_survey_does_not_open_their_files(theirs, monkeypatch):
    """Contents are read later, one at a time, with the user watching. A
    survey that slurps every file has already done the thing it was supposed
    to ask permission for."""
    from pathlib import Path

    def refuse(*_args, **_kwargs):
        raise AssertionError("survey must not read file contents")

    monkeypatch.setattr(Path, "read_text", refuse)
    monkeypatch.setattr(Path, "read_bytes", refuse)

    found = importer.survey(theirs)
    assert found.items


# ---------------------------------------------------------------------------
# The written explanation
# ---------------------------------------------------------------------------

def test_the_three_paths_are_documented():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "CHOOSING.md").read_text(
        encoding="utf-8")

    for phrase in ("Side by side", "Import", "Integrate"):
        assert phrase in text
    # Each path states the thing people want and do not know to ask for.
    assert text.count("Getting out:") == 3
    assert text.count("The cost") == 3


def test_the_explanation_says_integrate_is_the_risky_one():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "CHOOSING.md").read_text(
        encoding="utf-8")
    assert "break something that currently works" in text


# ---------------------------------------------------------------------------
# A separate bug, found in a real install's handoff the same day
# ---------------------------------------------------------------------------

def test_two_workspace_names_pointing_at_one_folder_do_not_double_everything(
        tmp_path):
    """the test laptop install showed every project twice, in both halves of
    its handoff, and nothing errored.

    `resolved_workspaces` matches a configured name that does not exist
    exactly by ignoring number prefixes and separators -- so "Work" and
    "01_Work" both land on `01_Work`, `workspace_dirs` returns it twice, and
    every item inside is read twice.
    """
    from aki_agent import config as config_module

    root = tmp_path / "Assistant"
    (root / "03_Workspace" / "01_Work" / "01_Project-1").mkdir(parents=True)
    layout = config_module.Layout(root=root, workspaces=("Work", "01_Work"))

    found = layout.item_dirs()

    assert [one.name for one in found] == ["01_Project-1"]


def test_the_collision_is_reported_rather_than_silently_absorbed(tmp_path):
    """Deduplicating fixes the symptom. The config still says something the
    user did not mean, and quietly working around a wrong config is how a
    wrong config survives."""
    from aki_agent import config as config_module

    root = tmp_path / "Assistant"
    (root / "03_Workspace" / "01_Work" / "01_Project-1").mkdir(parents=True)
    layout = config_module.Layout(root=root, workspaces=("Work", "01_Work"))

    assert layout.colliding_workspaces() == [("Work", "01_Work")]


def test_distinct_workspaces_are_not_reported_as_colliding(tmp_path):
    from aki_agent import config as config_module

    root = tmp_path / "Assistant"
    for name in ("01_Work", "02_Personal"):
        (root / "03_Workspace" / name / "01_Thing").mkdir(parents=True)
    layout = config_module.Layout(root=root,
                                  workspaces=("01_Work", "02_Personal"))

    assert layout.colliding_workspaces() == []
    assert len(layout.item_dirs()) == 2
