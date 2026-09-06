"""One agent, two workspaces, two different shapes of work.

`test_two_configs.py` proves the engine can serve an architect *or* a music
teacher. This file proves it can serve the architect *who also teaches piano
at weekends* — one assistant, one memory, one install, with each half of the
work described in its own terms.

The maintainer's words, 2026-08-17: *"一個 agent, 但有唔同 workspace… 一個 architect 都
可以 part time 教琴㗎!"* — and he is right that it is common. The design until
now assumed one person does one kind of work.

WHAT WOULD GO WRONG WITHOUT THIS
--------------------------------
Nothing would error. Every building project would show empty Grade and
Instrument columns, every pupil an empty Stage column, and the whole thing
would read as "you have not filled anything in" rather than "these fields
belong to the other half of your life". That is why the tests below assert on
what is *shown*, not only on what is loaded.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import config as config_module
from aki_agent import workspace as workspace_module
from aki_agent.config import Config, Layout
from aki_agent.schema import Field, ItemSchema


BUILDINGS = ItemSchema(
    item_label="Project", item_label_plural="Projects",
    summary_files=("state",),
    fields=(Field(key="stage", label="Stage", type="text"),
            Field(key="client", label="Client", type="text")))

PUPILS = ItemSchema(
    item_label="Pupil", item_label_plural="Pupils",
    summary_files=("state",),
    fields=(Field(key="grade", label="Grade", type="text"),
            Field(key="instrument", label="Instrument", type="text")))


@pytest.fixture
def both_trades(tmp_path) -> Config:
    """An architect who teaches piano. One workspace, two workspaces."""
    root = tmp_path / "Workspace"

    project = root / "01_Work" / "Riverside Hall"
    project.mkdir(parents=True)
    (project / "state.md").write_text(
        "---\ntitle: Riverside Hall\nstage: Stage 4\nclient: The Trust\n"
        "---\n\nGoing well.\n", encoding="utf-8")

    pupil = root / "02_Personal" / "Saturday pupil"
    pupil.mkdir(parents=True)
    (pupil / "state.md").write_text(
        "---\ntitle: Saturday pupil\ngrade: 5\ninstrument: Piano\n"
        "---\n\nExam in March.\n", encoding="utf-8")

    config = Config()
    config.layout = Layout(
        root=root,
        workspaces=("01_Work", "02_Personal"),
        schema=BUILDINGS,
        workspace_schemas={"02_Personal": PUPILS},
    )
    return config


def test_each_area_is_read_with_its_own_fields(both_trades):
    space = workspace_module.scan(both_trades)
    by_key = {item.key: item for item in space.items}

    # Keys carry the workspace: two workspaces may each hold a folder of the same name,
    # and the default scaffold gives both a "Project 1".
    hall = by_key["01_Work/Riverside Hall"]
    assert hall.values["stage"].display == "Stage 4"
    assert "grade" not in hall.values, "a building project has no grade"

    pupil = by_key["02_Personal/Saturday pupil"]
    assert pupil.values["instrument"].display == "Piano"
    assert "client" not in pupil.values, "a pupil has no client"


def test_an_area_without_its_own_schema_uses_the_default(both_trades):
    """Only the second workspace was given its own fields; the first inherits."""
    space = workspace_module.scan(both_trades)
    hall = space.item_by_key("01_Work/Riverside Hall")

    assert hall.schema is BUILDINGS
    assert hall.workspace == "01_Work"


def test_two_areas_may_hold_the_same_folder_name(tmp_path):
    """The default scaffold gives every workspace a "Project 1".

    Before keys carried the workspace, both got the key "Project 1", the lookup
    returned the first, and clicking the second in the dashboard opened the
    first with nothing on screen to say so.
    """
    root = tmp_path / "Workspace"
    for workspace in ("01_Work", "02_Personal"):
        directory = root / workspace / "Project 1"
        directory.mkdir(parents=True)
        (directory / "state.md").write_text(
            f"---\ntitle: {workspace} one\n---\n\nNotes.\n", encoding="utf-8")

    config = Config()
    config.layout = Layout(root=root, workspaces=("01_Work", "02_Personal"),
                                 schema=BUILDINGS)

    space = workspace_module.scan(config)
    keys = [item.key for item in space.items]

    assert len(keys) == len(set(keys)), "each item must be reachable"
    assert space.item_by_key("02_Personal/Project 1").title == "02_Personal one"
    # A bare folder name still resolves, so anything that stored one before
    # the change keeps working.
    assert space.item_by_key("Project 1") is not None


def test_an_area_named_without_its_number_still_reads(tmp_path):
    """The failure a real install hit on 2026-08-17.

    The interview writes what the user said ("work"); the scaffold creates
    what sorts properly ("01_work"). Every lookup missed and the dashboard
    came up blank with no error anywhere.
    """
    directory = tmp_path / "Workspace" / "01_work" / "Project 1"
    directory.mkdir(parents=True)
    (directory / "state.md").write_text("---\ntitle: One\n---\n\nx\n",
                                        encoding="utf-8")

    config = Config()
    config.layout = Layout(root=tmp_path / "Workspace",
                                 workspaces=("work",), schema=BUILDINGS)

    space = workspace_module.scan(config)

    assert [item.title for item in space.items] == ["One"]
    assert space.items[0].workspace == "work", "the item keeps its workspace's schema"
    assert any("01_work" in problem for problem in space.problems), \
        "working around a wrong config must not hide it"


def test_an_area_may_be_two_folders_deep(tmp_path):
    """the maintainer's own interview produced `01_Work/02_Piano`.

    A nested workspace must read normally *and* must not be reported as renamed:
    comparing the configured `01_Work/02_Piano` against the last segment
    `02_Piano` flagged every correct nested workspace as a mismatch.
    """
    root = tmp_path / "Aki-Workspace"
    for workspace in ("01_Work/01_Architecture", "01_Work/02_Piano"):
        directory = root / workspace / "Project 1"
        directory.mkdir(parents=True)
        (directory / "state.md").write_text(f"---\ntitle: {workspace}\n---\n\nx\n",
                                            encoding="utf-8")

    config = Config()
    config.layout = Layout(
        root=root, workspaces=("01_Work/01_Architecture", "01_Work/02_Piano"),
        schema=BUILDINGS)

    space = workspace_module.scan(config)

    assert len(space.items) == 2
    assert space.problems == []
    assert config.layout.renamed_workspaces() == []
    assert {item.workspace for item in space.items} == {"01_Work/01_Architecture",
                                                   "01_Work/02_Piano"}


def test_a_nested_area_missing_its_prefixes_still_reads(tmp_path):
    """The same forgiveness, at every level of the path."""
    directory = tmp_path / "W" / "01_Work" / "02_Piano" / "A pupil"
    directory.mkdir(parents=True)
    (directory / "state.md").write_text("---\ntitle: A pupil\n---\n\nx\n",
                                        encoding="utf-8")

    config = Config()
    config.layout = Layout(root=tmp_path / "W", workspaces=("Work/Piano",),
                                 schema=BUILDINGS)

    space = workspace_module.scan(config)

    assert [item.title for item in space.items] == ["A pupil"]
    assert config.layout.renamed_workspaces() == [
        ("Work/Piano", "01_Work/02_Piano")]


def test_an_area_that_matches_nothing_is_reported(tmp_path):
    root = tmp_path / "Workspace"
    (root / "01_Work").mkdir(parents=True)

    config = Config()
    config.layout = Layout(root=root, workspaces=("01_Work", "Church"),
                                 schema=BUILDINGS)

    assert config.layout.unmatched_workspaces() == ["Church"]
    space = workspace_module.scan(config)
    assert any("Church" in problem for problem in space.problems)


def test_the_two_halves_are_grouped_and_never_mixed(both_trades):
    space = workspace_module.scan(both_trades)
    grouped = {workspace: (schema, items)
               for workspace, schema, items in space.by_workspace()}

    assert set(grouped) == {"01_Work", "02_Personal"}
    assert grouped["01_Work"][0].item_label == "Project"
    assert grouped["02_Personal"][0].item_label == "Pupil"


def test_the_front_page_lists_the_workspaces_and_opens_into_one(both_trades,
                                                                monkeypatch,
                                                                tmp_path):
    """Proven at the rendered page, not just the loader.

    The same standard `test_dashboard.py` holds: a loader that gets this right
    and a template that draws one set of columns would still show the user the
    wrong thing.

    The navigation the maintainer asked for on 2026-08-17 -- workspaces first, projects
    one click in -- is the reason the front page must NOT be showing a piano
    pupil's Grade column beside a building project.
    """
    from aki_agent import paths
    from aki_agent.dashboard import create_app

    monkeypatch.setattr(paths, "home", lambda: tmp_path / "home")
    paths.ensure_app_dirs()
    monkeypatch.setattr(config_module, "load", lambda *a, **k: both_trades)

    client = create_app().test_client()
    front = client.get("/projects").get_data(as_text=True)

    assert "01_Work" in front and "02_Personal" in front
    assert "/workspace/01_Work" in front
    # The front page is a list of workspaces, not of everything at once.
    assert "Riverside Hall" not in front
    assert "<table" not in front

    work = client.get("/workspace/01_Work").get_data(as_text=True)
    assert "Riverside Hall" in work
    assert "Stage" in work and "Client" in work
    assert "Grade" not in work, "the other trade's fields must not appear"

    personal = client.get("/workspace/02_Personal").get_data(as_text=True)
    assert "Saturday pupil" in personal
    assert "Grade" in personal and "Instrument" in personal
    assert "Client" not in personal


def test_one_workspace_shows_its_projects_without_a_click(tmp_path,
                                                          monkeypatch):
    """A person with one kind of work should not click through a list of one."""
    from aki_agent import paths
    from aki_agent.dashboard import create_app

    root = tmp_path / "Aki-Agent"
    # Built from the configured name rather than a literal: a test that
    # hardcodes a folder name quietly stops testing the day it is renamed,
    # which this package has already had happen to it once.
    project = root / Layout().work_dir / "01_Work" / "01_Project-1"
    project.mkdir(parents=True)
    (project / "state.md").write_text(
        "---\ntitle: Only job\nstage: Stage 2\n---\n\nx\n", encoding="utf-8")

    config = Config()
    config.layout = Layout(root=root, workspaces=("01_Work",),
                           schema=BUILDINGS)

    monkeypatch.setattr(paths, "home", lambda: tmp_path / "home")
    paths.ensure_app_dirs()
    monkeypatch.setattr(config_module, "load", lambda *a, **k: config)

    front = create_app().test_client().get(
        "/projects").get_data(as_text=True)

    assert "Only job" in front
    # A card, not a table, since 2026-09-05. What this test is for is that ONE workspace shows its
    # projects straight away rather than making somebody click through a list
    # of one -- the shape they arrive in is not the point.
    assert 'class="favour itcard' in front
    assert "Stage 2" in front, (
        "the card has to keep the fields the table carried, or the redesign "
        "lost information")


def test_area_schemas_survive_the_config_file(tmp_path):
    config = Config()
    config.layout = Layout(
        root=tmp_path, workspaces=("01_Work", "02_Personal"),
        schema=BUILDINGS, workspace_schemas={"02_Personal": PUPILS})

    written = tmp_path / "config.yaml"
    config_module.save(config, written)
    reloaded = config_module.load(written)

    assert set(reloaded.layout.workspace_schemas) == {"02_Personal"}
    assert reloaded.layout.schema_for("02_Personal").item_label == "Pupil"
    assert reloaded.layout.schema_for("01_Work").item_label == "Project"
    assert reloaded.layout.schema_for(None).item_label == "Project"


def test_a_one_trade_config_gains_nothing(tmp_path):
    """Most people do one kind of work; their file must not grow a section."""
    config = Config()
    config.layout = Layout(root=tmp_path, workspaces=("01_Work",),
                                 schema=BUILDINGS)

    assert "workspace_schemas" not in config.to_dict()["layout"]


# ---------------------------------------------------------------------------
# The shipped example, which is also the documentation


def test_the_shipped_two_trades_example_actually_works():
    """`configs/examples/two_trades.yaml` is read by people, so it must be true.

    An example config that no longer loads is worse than none: it is the file
    a student copies, and it teaches them a shape the engine has stopped
    accepting.
    """
    example = (Path(__file__).resolve().parents[1]
               / "configs" / "examples" / "two_trades.yaml")
    config = config_module.load(example)
    space = workspace_module.scan(config)

    assert space.problems == []

    labels = {workspace: schema.item_label_plural
              for workspace, schema, _ in space.by_workspace()}
    assert labels == {"01_Work": "Projects", "02_Personal": "Pupils"}

    pupil = next(item for item in space.items if item.workspace == "02_Personal")
    assert pupil.values["instrument"].display == "Piano"
    assert "stage" not in pupil.values
