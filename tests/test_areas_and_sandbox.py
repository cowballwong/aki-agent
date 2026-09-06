"""The workspace / sandbox / project shape, and the rule that protects it.

Two questions are being asked here, and only the second one is interesting:

1. Does an item get found when it lives inside a workspace? (Plumbing.)
2. Can anything of the user's be written without them agreeing?

The second is the one worth tests, because getting it wrong is silent. An
assistant that overwrites a document does not crash -- the user simply finds a
different file than the one they left, days later, with no way to tell what
happened. So the checks below are deliberately adversarial: the same folder
name somewhere else, a path that walks out through `..`, a workspace that does
not exist, a blank folder name in the config.

**The rule changed on 2026-08-17 (the maintainer).** It used to be "a `02_documents`
folder inside each project is protected". It is now "the project folder itself
is protected" -- anything the user drops into their own project is theirs,
whether or not they remembered to file it somewhere special. The exception is
the project's summary files, which the assistant maintains; an assistant that
must ask permission to update its own tracking notes tracks nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import config as config_module
from aki_agent.config import Config, Layout
from aki_agent import scaffold


WORKSPACES = ("01_Work", "02_Personal")
PROJECT = scaffold.DEFAULT_PROJECTS[0]


@pytest.fixture
def built(tmp_path) -> Path:
    """A real scaffolded folder, not a hand-made imitation of one."""
    root = tmp_path / "Aki-Agent"
    scaffold.build(scaffold.plan(root, workspaces=WORKSPACES), confirmed=True)
    return root


def layout_for(root: Path) -> Layout:
    return Layout(root=root, workspaces=WORKSPACES)


def work_path(root: Path, *parts: str) -> Path:
    return root.joinpath(scaffold.WORK_DIR, *parts)


# ---------------------------------------------------------------------------
# Finding the work


def test_items_are_found_one_level_inside_each_workspace(built):
    names = [path.name for path in layout_for(built).item_dirs()]
    assert names == [PROJECT, PROJECT]      # one per workspace


def test_the_sandbox_is_never_mistaken_for_a_project(built):
    """`00_Sandbox` is the assistant's desk, and must never be listed."""
    for item in layout_for(built).item_dirs():
        assert item.name != scaffold.SANDBOX_DIR


def test_the_config_folder_is_never_mistaken_for_a_project(built):
    """It sits beside the work, so a careless scan would list it as one."""
    names = [path.name for path in layout_for(built).item_dirs()]
    assert scaffold.CONFIG_DIR not in names
    assert scaffold.WORK_DIR not in names


def test_the_simple_shape_still_works(tmp_path):
    """No workspaces configured means items sit directly in the root."""
    root = tmp_path / "W"
    (root / "some-project").mkdir(parents=True)

    assert [p.name for p in Layout(root=root).item_dirs()] == ["some-project"]


def test_a_missing_workspace_is_skipped_rather_than_raising(tmp_path):
    root = tmp_path / "W"
    (root / scaffold.WORK_DIR / "01_Work").mkdir(parents=True)

    layout = Layout(root=root, workspaces=("01_Work", "99_Nonexistent"))
    assert layout.item_dirs() == []
    assert [p.name for p in layout.workspace_dirs()] == ["01_Work"]


# ---------------------------------------------------------------------------
# The rule that matters


def test_a_project_is_protected_and_the_sandbox_is_not(built):
    layout = layout_for(built)
    project = work_path(built, "01_Work", PROJECT)
    # From 2026-08-19 the sandbox is at the root, not inside the workspace.
    sandbox = built / scaffold.SANDBOX_DIR

    assert layout.is_protected(project / "signed-contract.pdf")
    assert not layout.is_protected(sandbox / "draft.docx")
    assert layout.is_sandboxed(sandbox / "draft.docx")


def test_the_tracking_notes_are_the_one_thing_it_may_write(built):
    """Otherwise the assistant would have to ask before every update."""
    layout = layout_for(built)
    project = work_path(built, "01_Work", PROJECT)

    assert not layout.is_protected(project / "state.md")
    assert not layout.is_protected(project / "actions.md")
    # A file the user made that merely looks similar is still theirs.
    assert layout.is_protected(project / "state-of-the-roof.md")


def test_protection_is_by_path_not_by_folder_name(tmp_path, built):
    """A folder with the same name elsewhere gets no protection from it.

    And the converse, which is the dangerous direction: a path that leaves a
    sandbox through `..` is not sandboxed just because it starts inside one.
    """
    layout = layout_for(built)

    impostor = tmp_path / "somewhere-else" / PROJECT / "x.md"
    assert not layout.is_protected(impostor)

    escaped = (work_path(built, "01_Work", scaffold.SANDBOX_DIR) / ".."
               / PROJECT / "cv.docx")
    assert not layout.is_sandboxed(escaped)
    assert layout.is_protected(escaped)


def test_an_unclassified_folder_is_not_treated_as_safe(built):
    """Protection is decided by inclusion, never by exclusion.

    A folder nobody has classified is not a sandbox. If that answer were the
    other way round, every folder added later would silently become writable.
    """
    layout = layout_for(built)
    new_folder = work_path(built, "01_Work", "03_Invoices", "may.pdf")

    assert not layout.is_sandboxed(new_folder)


def test_a_blank_folder_name_in_config_cannot_disarm_the_rule(tmp_path):
    """An empty `sandbox_dir` would resolve to the workspace itself.

    That would hand the assistant free rein over every project in it. The
    loader substitutes the default instead.
    """
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "assistant:\n  name: A\n"
        "layout:\n"
        "  root: .\n"
        "  workspaces: ['01_Work']\n"
        "  sandbox_dir: ''\n"
        "  config_dir: ''\n"
        "  work_dir: ''\n",
        encoding="utf-8")

    config = config_module.load(config_file)
    assert config.layout.sandbox_dir == scaffold.SANDBOX_DIR
    assert config.layout.config_dir == scaffold.CONFIG_DIR
    assert config.layout.work_dir == scaffold.WORK_DIR


# ---------------------------------------------------------------------------
# Configuration round-trip


def test_workspaces_survive_being_saved_and_loaded(tmp_path):
    config = Config()
    config.layout = Layout(root=tmp_path, workspaces=WORKSPACES)

    written = tmp_path / "config.yaml"
    config_module.save(config, written)

    reloaded = config_module.load(written)
    assert reloaded.layout.workspaces == WORKSPACES
    assert reloaded.layout.sandbox_dir == scaffold.SANDBOX_DIR


def test_a_config_written_under_the_old_names_still_loads(tmp_path):
    """`workspace:` / `areas:` were the names until 2026-08-17.

    A config that stops being understood does not announce itself -- it comes
    back empty, which is the failure this package spent an evening chasing.
    """
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "assistant:\n  name: A\n"
        "workspace:\n"
        "  root: .\n"
        "  areas: ['01_Work', '02_Personal']\n"
        "  item_label: Job\n",
        encoding="utf-8")

    config = config_module.load(config_file)

    assert config.layout.workspaces == ("01_Work", "02_Personal")
    assert config.layout.schema.item_label == "Job"


def test_a_simple_config_stays_simple(tmp_path):
    """Nobody using the flat shape should find layout settings in their file."""
    config = Config()
    config.layout = Layout(root=tmp_path)

    assert "workspaces" not in config.to_dict()["layout"]


def test_a_folder_built_by_the_old_version_still_has_a_sandbox(tmp_path):
    """The sandbox moved to the root on 2026-08-19. Existing folders did not.

    An upgrade that quietly took away the assistant's only place to write
    would leave it with two options, both bad: refuse to work, or start
    drafting inside the user's project folders. So both shapes are found.
    """
    root = tmp_path / "OldInstall"
    old_sandbox = root / "02_Workspace" / "01_Work" / "00_Sandbox"
    old_sandbox.mkdir(parents=True)

    layout = Layout(root=root, workspaces=("01_Work",),
                    work_dir="02_Workspace", sandbox_dir="00_Sandbox")

    assert layout.sandbox_dirs() == [old_sandbox]
    assert layout.is_sandboxed(old_sandbox / "draft.docx")


def test_the_new_shape_puts_the_only_sandbox_at_the_root(built):
    layout = layout_for(built)

    assert layout.sandbox_dirs() == [built / scaffold.SANDBOX_DIR]
