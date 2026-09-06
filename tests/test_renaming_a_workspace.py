"""Renaming a workspace, and catching up with one somebody renamed themselves.


The two belong together. A workspace's name lives in two places -- the folder
on disk and the `workspaces:` list in the config -- and this package has
already been bitten by letting them drift: a config saying `work` beside a
folder called `01_work` gave two real installs an empty dashboard with
nothing reporting an error. So renaming moves both, and refreshing is how the
config catches up when the folder moved without it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import config as config_module
from aki_agent import favourites, paths, workspace


@pytest.fixture
def space(tmp_path):
    root = tmp_path / "Aki"
    work = root / "03_Workspace"
    for name in ("01_Architecture", "02_Teaching"):
        (work / name / "01_Project-1").mkdir(parents=True)
    (root / "01_Config").mkdir(parents=True, exist_ok=True)
    (root / "02_Sandbox").mkdir(parents=True, exist_ok=True)

    config = config_module.Config()
    config.layout.root = root
    config.layout.workspaces = ("01_Architecture", "02_Teaching")
    return config


def _folders(config) -> list[str]:
    return sorted(one.name for one in config.layout.work_root().iterdir())


# ---------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------

def test_the_folder_and_the_config_move_together(space):
    ok, said = workspace.rename_workspace(space, "01_Architecture",
                                          "01_Buildings")

    assert ok, said
    assert space.layout.workspaces == ("01_Buildings", "02_Teaching")
    assert _folders(space) == ["01_Buildings", "02_Teaching"]


@pytest.mark.parametrize("wanted, because", [
    ("", "a workspace needs a name"),
    ("01_Architecture", "that is the name it already has"),
    ("02_Teaching", "something else is already called that"),
    ("../escape", "a rename is not a move"),
    ("sub/folder", "a rename is not a move"),
    (".hidden", "a workspace should not start with a dot"),
])
def test_it_refuses_rather_than_guesses(space, wanted, because):
    ok, said = workspace.rename_workspace(space, "01_Architecture", wanted)

    assert not ok, because
    assert said
    # And nothing moved.
    assert _folders(space) == ["01_Architecture", "02_Teaching"]
    assert space.layout.workspaces == ("01_Architecture", "02_Teaching")


def test_a_workspaces_own_fields_follow_it(space):
    """`workspace_schemas` is keyed by name.

    Left behind, the renamed workspace silently falls back to the default
    schema -- which shows as a row of empty columns rather than an error, the
    exact failure mode this package keeps having.
    """
    schema = space.layout.schema_for(None)
    space.layout.workspace_schemas = {"01_Architecture": schema}

    workspace.rename_workspace(space, "01_Architecture", "01_Buildings")

    assert "01_Buildings" in space.layout.workspace_schemas
    assert "01_Architecture" not in space.layout.workspace_schemas


def test_pinned_cards_follow_the_rename(tmp_path, monkeypatch):
    """A pin is `workspace/project`, so a rename orphans every card in it.

    And this module keeps a pin whose folder has gone, on purpose -- so they
    would sit in the file for ever, invisible, counting against the six.
    """
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    favourites.pin("01_Architecture/01_Project-1")
    favourites.pin("02_Teaching/01_Project-1")

    moved = favourites.rename_workspace_in_pins("01_Architecture",
                                                "01_Buildings")

    assert moved == 1
    assert favourites.read_pins() == ["01_Buildings/01_Project-1",
                                      "02_Teaching/01_Project-1"]


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------

def test_refresh_catches_up_with_a_folder_renamed_elsewhere(space):
    (space.layout.work_root() / "02_Teaching").rename(
        space.layout.work_root() / "02_Lessons")

    changed, said = workspace.rescan_workspaces(space)

    assert changed
    assert space.layout.workspaces == ("01_Architecture", "02_Lessons")
    assert "02_Lessons" in said and "02_Teaching" in said


def test_refresh_says_so_when_there_is_nothing_to_do(space):
    changed, said = workspace.rescan_workspaces(space)

    assert not changed
    assert "up to date" in said.lower()


def test_refresh_never_touches_the_disk(space):
    """A button labelled Refresh must not be the one that removes a folder."""
    (space.layout.work_root() / "03_Extra").mkdir()
    before = _folders(space)

    workspace.rescan_workspaces(space)

    assert _folders(space) == before


def test_refresh_leaves_a_name_that_already_resolves_alone(space):
    """`resolved_workspaces` matches `work` to `01_work` on purpose.

    Rewriting that to the folder name would be a refresh quietly renaming
    things in the config that nobody asked it to touch.
    """
    space.layout.workspaces = ("Architecture", "02_Teaching")

    changed, said = workspace.rescan_workspaces(space)

    assert not changed, said
    assert "Architecture" in space.layout.workspaces


def test_the_house_folders_are_not_mistaken_for_workspaces(space):
    """`01_Config` and `02_Sandbox` sit beside the work when there is no
    `03_Workspace` folder, and a refresh must not adopt them."""
    space.layout.root = space.layout.root
    names = workspace.folders_on_disk(space)

    assert "01_Config" not in names
    assert "02_Sandbox" not in names


# ---------------------------------------------------------------------------
# One Edit button for all of them
#
#
# ---------------------------------------------------------------------------

TEMPLATES = (Path(__file__).resolve().parents[1] / "src" / "aki_agent"
             / "dashboard" / "templates")


def test_the_page_has_one_edit_button_and_one_refresh():
    page = (TEMPLATES / "index.html").read_text(encoding="utf-8")

    assert page.count('id="wsedit"') == 1
    assert page.count('id="wssave"') == 1
    assert page.count('action="/workspace/refresh"') == 1
    # The per-card fold-out is gone.
    assert 'class="renamer"' not in page


def test_every_name_is_a_field_inside_one_form():
    """Several at once was the point: ."""
    page = (TEMPLATES / "index.html").read_text(encoding="utf-8")

    assert 'id="renameall"' in page
    assert 'name="was"' in page and 'name="to"' in page, (
        "parallel lists, so one submit can carry every rename")


def test_saving_asks_before_it_moves_anything():
    page = (TEMPLATES / "index.html").read_text(encoding="utf-8")

    assert "window.confirm(" in page
    assert "The folders on disk are renamed too." in page, (
        "the confirmation has to say what it is about to do on disk")


def test_the_folder_shown_is_where_the_workspaces_are():
    """The folder shown is where the workspaces are.

    It printed `space.root` -- the assistant's own folder, one level up from
    the workspaces. Somebody reading that line goes looking in the wrong
    place.
    """
    page = (TEMPLATES / "index.html").read_text(encoding="utf-8")

    assert "Folder: {{ work_root }}" in page
    assert "Folder: {{ space.root }}" not in page


def test_renaming_several_at_once_reports_each_one(space, tmp_path,
                                                   monkeypatch):
    """And a refusal in the middle must not stop the others."""
    monkeypatch.setattr(paths, "home", lambda: tmp_path / "state")
    paths.ensure_app_dirs()

    ok_one, _ = workspace.rename_workspace(space, "01_Architecture",
                                           "01_Buildings")
    bad, said = workspace.rename_workspace(space, "02_Teaching", "01_Buildings")
    ok_two, _ = workspace.rename_workspace(space, "02_Teaching", "02_Lessons")

    assert ok_one and ok_two
    assert not bad and "already called" in said
    assert _folders(space) == ["01_Buildings", "02_Lessons"]


# ---------------------------------------------------------------------------
# Renaming a project, and why renaming its folder alone did nothing
#
# -- four folders renamed in Explorer, all four still reading
# `01_Project 1` on the page.
#
# `read_item` takes the title from the frontmatter and only falls back to the
# folder name. The scaffold writes `title:` into `state.md`, so from then on
# the folder name is not what anybody sees. That is a real feature -- the
# example configs use it to show "Riverside School" for a folder called
# something tidier -- so the fix is not to ignore the frontmatter. It is that
# a rename has to move both.
# ---------------------------------------------------------------------------

@pytest.fixture
def project(tmp_path):
    root = tmp_path / "Aki"
    folder = root / "03_Workspace" / "01_Arch" / "01_Project-1"
    folder.mkdir(parents=True)
    (folder / "state.md").write_text(
        "---\ntitle: 01_Project 1\nstage: design\n---\n\nSome notes.\n",
        encoding="utf-8")
    (root / "01_Config").mkdir(parents=True, exist_ok=True)

    config = config_module.Config()
    config.layout.root = root
    config.layout.workspaces = ("01_Arch",)
    return config


def test_a_folder_renamed_outside_the_dashboard_is_not_the_name(project):
    """The behaviour that confused him, stated so it is not a surprise."""
    scanned = workspace.scan(project)
    (scanned.items[0].path).rename(
        scanned.items[0].path.parent / "01_Chan Tai Man")

    again = workspace.scan(project)

    assert again.items[0].path.name == "01_Chan Tai Man"
    assert again.items[0].title == "01_Project 1", (
        "the frontmatter title wins, which is why renaming the folder in "
        "Explorer changed nothing on screen")


def test_renaming_from_the_dashboard_moves_both(project):
    scanned = workspace.scan(project)

    ok, said = workspace.rename_item(project, scanned.items[0].key,
                                     "01_Riverside")

    assert ok, said
    again = workspace.scan(project)
    assert again.items[0].path.name == "01_Riverside"
    assert again.items[0].title == "01_Riverside"


def test_the_rest_of_the_file_is_left_exactly_as_it_was(project):
    """Edited line by line, not round-tripped through YAML.

    Re-serialising somebody's own file reorders their keys, drops their
    comments and reformats their quoting. A rename has no business doing any
    of that.
    """
    scanned = workspace.scan(project)
    workspace.rename_item(project, scanned.items[0].key, "01_Riverside")

    text = (project.layout.work_root() / "01_Arch" / "01_Riverside"
            / "state.md").read_text(encoding="utf-8")

    assert "stage: design" in text
    assert "Some notes." in text
    assert text.count("title:") == 1


@pytest.mark.parametrize("wanted", ["", "../out", "a/b", ".hidden"])
def test_a_project_rename_refuses_rather_than_guesses(project, wanted):
    scanned = workspace.scan(project)

    ok, _ = workspace.rename_item(project, scanned.items[0].key, wanted)

    assert not ok
    assert workspace.scan(project).items[0].path.name == "01_Project-1"


def test_a_pin_follows_the_project(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    favourites.pin("01_Arch/01_Project-1")

    moved = favourites.rename_key_in_pins("01_Arch/01_Project-1",
                                          "01_Arch/01_Riverside")

    assert moved
    assert favourites.read_pins() == ["01_Arch/01_Riverside"]


def test_the_project_table_sorts_and_can_be_edited():
    page = (TEMPLATES / "_items.html").read_text(encoding="utf-8")

    assert "items|sort(attribute='title')" in page
    assert 'id="renameitems"' in page
    assert 'formaction="/projects/pin"' in page, (
        "the pin had to move into the rename form; a form cannot nest")


def test_the_workspace_page_goes_back_to_the_workspaces():
    """`/` is Today. The list of workspaces is `/projects`.

    The absence checks read the markup with the Jinja comments stripped: the
    notes left where each removed thing stood quote it in full, which is a
    trap this evening set five separate times.
    """
    import re

    page = (TEMPLATES / "workspace.html").read_text(encoding="utf-8")
    markup = re.sub(r"\{#.*?#\}", "", page, flags=re.S)

    assert 'class="back" href="/projects"' in markup
    assert "all workspaces" not in markup
    assert "Drafts go in" not in markup


# ---------------------------------------------------------------------------
# The name you edit is the name you see
#
#
# The field showed the FOLDER name while the page showed the frontmatter
# title. On a project whose `state.md` still said `01_Project 1`, Edit opened
# with `01_Travel` already in the box, Save saw nothing to change, and the
# page went on showing the stale one. Two names, one field, and no way
# through it.
# ---------------------------------------------------------------------------

def test_the_field_offers_the_name_that_is_on_screen():
    page = (TEMPLATES / "_items.html").read_text(encoding="utf-8")

    assert 'name="to" value="{{ item.title }}"' in page
    assert 'name="to" value="{{ item.path.name }}"' not in page


def test_saving_the_shown_name_fixes_a_stale_title(project):
    """Folder already right, title still wrong, and the field agrees with
    the folder -- the exact state he was stuck in."""
    scanned = workspace.scan(project)
    scanned.items[0].path.rename(scanned.items[0].path.parent / "01_Travel")

    space = workspace.scan(project)
    assert space.items[0].title == "01_Project 1"

    ok, _ = workspace.rename_item(project, space.items[0].key, "01_Travel")

    assert ok
    again = workspace.scan(project)
    assert again.items[0].title == "01_Travel"
    assert again.items[0].path.name == "01_Travel"


def test_refresh_takes_every_name_from_its_folder(project):
    scanned = workspace.scan(project)
    scanned.items[0].path.rename(scanned.items[0].path.parent / "01_Travel")

    changed, said = workspace.refresh_titles(project)

    assert changed == 1
    assert workspace.scan(project).items[0].title == "01_Travel"
    assert "folders" in said


def test_refresh_says_so_when_everything_already_matches(project):
    workspace.refresh_titles(project)          # first pass fixes nothing here
    changed, said = workspace.refresh_titles(project)

    assert changed == 0
    assert "already matches" in said


def test_refresh_only_touches_the_workspace_it_was_pressed_in(tmp_path):
    root = tmp_path / "Aki"
    for space_name, folder in (("01_Arch", "01_Travel"),
                               ("02_Church", "01_Sermon")):
        item = root / "03_Workspace" / space_name / folder
        item.mkdir(parents=True)
        (item / "state.md").write_text(
            "---\ntitle: 01_Project 1\n---\n\nnotes\n", encoding="utf-8")
    (root / "01_Config").mkdir(parents=True, exist_ok=True)

    config = config_module.Config()
    config.layout.root = root
    config.layout.workspaces = ("01_Arch", "02_Church")

    changed, _ = workspace.refresh_titles(config, "01_Arch")

    assert changed == 1
    titles = {one.workspace: one.title for one in workspace.scan(config).items}
    assert titles["01_Arch"] == "01_Travel"
    assert titles["02_Church"] == "01_Project 1", "the other one is untouched"


def test_refresh_never_touches_the_folders(project):
    before = sorted(one.name for one in
                    (project.layout.work_root() / "01_Arch").iterdir())

    workspace.refresh_titles(project)

    after = sorted(one.name for one in
                   (project.layout.work_root() / "01_Arch").iterdir())
    assert before == after
