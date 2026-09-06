"""Knowledge in three tabs, and workflows you can switch off.

reported 2026-09-05:






Two defects were found while building these, and both are guarded below: a
Remove button that deleted files out of the middle of a plugin, and a switch
that drew every row as "off" because the page is handed dicts.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aki_agent import folders, paths, workflows
from aki_agent.dashboard import app as app_module

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "src" / "aki_agent" / "dashboard" / "templates"


def without_comments(text: str) -> str:
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


# ---------------------------------------------------------------------------
# Knowledge: three tabs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tab, looked_for", [
    ("docs", "shelf"),
    ("learned", "your own verdicts"),
])
def test_each_tab_shows_only_its_own_section(dashboard_client, tab, looked_for):
    """Two sections, one per tab.

    Three when this was written, until Matching by Meaning moved to Memory >
    Vector store the same evening -- a vector store on a page of documents,
    while a second vector store was being built on the Memory page.
    """
    page = dashboard_client.get(f"/knowledge?tab={tab}").get_data(as_text=True)
    assert looked_for in page

    others = {"docs": "your own verdicts",
              "learned": "Nothing on the shelf yet"}
    assert others[tab] not in page, f"{tab} is showing another tab's section"


def test_the_meaning_switch_went_somewhere_and_is_linked(dashboard_client):
    """Moving markup is not moving a capability.

    The section was cut out of this page; without the switch arriving on the
    other one, a working feature would simply have become unreachable -- and
    the page it left would say nothing about where it went.
    """
    page = dashboard_client.get("/knowledge?tab=docs").get_data(as_text=True)
    assert "/memory?tab=vectors" in page

    landed = dashboard_client.get("/memory?tab=vectors").get_data(as_text=True)
    assert "Your notes" in landed, "the section did not arrive"

    # The switch itself only draws once the embedding library is present, so
    # an install with nothing fetched shows "not installed" instead -- which
    # is right, and is why this half is asserted against the template rather
    # than against a page rendered on a bare machine.
    page_source = (TEMPLATES / "history.html").read_text(encoding="utf-8")
    assert 'action="/memory/meaning"' in page_source


def test_an_unknown_tab_lands_on_the_shelf(dashboard_client):
    page = dashboard_client.get("/knowledge?tab=nonsense").get_data(as_text=True)
    assert "shelf" in page


# ---------------------------------------------------------------------------
# Knowledge: picking a file instead of typing one
# ---------------------------------------------------------------------------

def test_the_shelf_form_no_longer_asks_anybody_to_type_a_path():
    """The shelf form offers a file picker, the same thing asked for folders
    on 2026-08-21.

    Nobody types a full path correctly from memory, and this is the worst
    place to get one wrong: a mistyped path is stored as a pointer that looks
    exactly like a working one until the day something reads it.
    """
    page = without_comments(
        (TEMPLATES / "knowledge.html").read_text(encoding="utf-8"))

    assert "C:\\Users\\you\\Documents\\handbook.pdf" not in page
    assert 'id="shelfbrowse"' in page
    assert "/knowledge/files/native" in page
    # And typing still works, for a machine with no desktop to draw on.
    assert 'name="target"' in page


def test_the_picker_can_list_files_and_still_lists_folders(tmp_path):
    (tmp_path / "drawings").mkdir()
    (tmp_path / "handbook.pdf").write_text("x", encoding="utf-8")
    (tmp_path / "notes.md").write_text("x", encoding="utf-8")

    folders_only = folders.listing(str(tmp_path))
    assert [one["name"] for one in folders_only["folders"]] == ["drawings"]
    assert folders_only["files"] == [], (
        "the schedule page's folder picker must read the same answer it "
        "always did")

    with_files = folders.listing(str(tmp_path), want_files=True)
    assert [one["name"] for one in with_files["folders"]] == ["drawings"]
    assert [one["name"] for one in with_files["files"]] == ["handbook.pdf",
                                                            "notes.md"]


def test_the_top_of_the_walk_answers_the_same_shape(tmp_path):
    """The drive list has no files in it, and the key still has to be there
    or the page's `data.files.forEach` throws on the first screen."""
    top = folders.listing("")
    assert "files" in top and top["files"] == []


def test_the_file_dialog_runs_in_its_own_process():
    """Tk taken up and torn down inside a serving thread does not raise when
    it goes wrong -- it takes the dashboard with it."""
    source = (REPO_ROOT / "src" / "aki_agent"
              / "folders.py").read_text(encoding="utf-8")

    where = source.index("def ask_for_file(")
    assert "_ask_with(" in source[where:where + 400]
    assert "askopenfilename" in source


def test_the_picker_routes_need_the_token(dashboard_client):
    """They change nothing, but they map the disk."""
    for route in ("/knowledge/files", "/knowledge/files/native"):
        assert dashboard_client.post(route, data={"at": ""}).status_code == 403


# ---------------------------------------------------------------------------
# Knowledge: matching by meaning
# ---------------------------------------------------------------------------

def test_installing_it_is_a_button_and_not_a_command_to_type():
    """Installing it is a button and not a command to type.

    The page printed `pip install fastembed` and stopped, which offers the
    fix only to people who open a terminal -- and the premise of this package
    is that its users do not.
    """
    page = without_comments(
        (TEMPLATES / "history.html").read_text(encoding="utf-8"))

    assert 'value="install"' in page
    assert "Set it up" in page

    from aki_agent import semantic
    assert hasattr(semantic, "install")


def test_the_install_button_says_what_it_costs_before_it_is_pressed():
    """A few hundred megabytes is not a surprise anybody should get after
    pressing something."""
    page = (TEMPLATES / "history.html").read_text(encoding="utf-8")
    assert "hundred megabytes" in page
    # And the page cannot answer while it downloads, so it raises the overlay
    # rather than looking dead for several minutes.
    assert 'data-working="Fetching what the vector store needs"' in page


def test_installing_does_not_also_switch_it_on():
    """Two different questions. Installing answers "do I want to spend the
    disk"; turning it on answers "do I want my searches to change"."""
    source = (REPO_ROOT / "src" / "aki_agent" / "dashboard"
              / "app.py").read_text(encoding="utf-8")
    start = source.index('if wanted == "install":')
    end = source.index('elif wanted == "on":', start)
    assert "turn_on" not in source[start:end]


def test_it_is_still_not_a_package_dependency():
    """Deliberately different from what was asked for, and said out loud.

    `fastembed` brings its model with it. Bundling it would put a few hundred
    megabytes on every student's machine, most of whom will never search
    their notes by meaning -- and `semantic.py`'s own rule is that such a
    feature must be chosen and never inherited.
    """
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "fastembed" not in text


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------

@pytest.fixture
def one_workflow(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()

    folder = workflows.workflows_dir() / "tender-report"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "WORKFLOW.md").write_text(
        "\n".join(["---", "name: tender-report", "title: Tender report",
                   "entry: run.py", "---", "", "Body.", ""]),
        encoding="utf-8")
    (folder / "run.py").write_text("print(1)", encoding="utf-8")
    return folder


def test_a_workflow_starts_on_and_can_be_switched_off(one_workflow):
    """A list of the OFF ones, so anything arriving later -- from a plugin
    update, or a folder somebody drops in -- is on by default."""
    assert workflows.is_on("tender-report")

    ok, said = workflows.set_on("tender-report", False)
    assert ok and not workflows.is_on("tender-report")
    assert "stays installed" in said

    workflows.set_on("tender-report", True)
    assert workflows.is_on("tender-report")


def test_a_switched_off_workflow_will_not_run(one_workflow):
    """Enforced in `run`, not by hiding a button.

    A switch honoured only by the page is not a switch: the CLI, a scheduled
    task and anything else reaching this function would still run it, and the
    person who switched it off would have no way of knowing.
    """
    workflows.set_on("tender-report", False)

    code, said = workflows.run("tender-report")
    assert code == 1
    assert "switched off" in said


def test_removing_a_plugins_workflow_is_refused(one_workflow, monkeypatch):
    """FOUND WHILE BUILDING THE SWITCH, and the reason the switch matters.

    `installed()` lists the user's own folder and every plugin's together,
    which is right for reading and was quietly wrong for `remove` -- that
    function is `shutil.rmtree(one.path)`, so pressing Remove on a plugin's
    workflow deleted files out of the middle of that plugin. The plugin was
    then missing a piece with nothing to say so.
    """
    monkeypatch.setattr(workflows, "plugin_workflow_dirs",
                        lambda: [one_workflow.parent])
    # Re-read so the row is marked as coming from a plugin folder.
    monkeypatch.setattr(workflows, "workflows_dir",
                        lambda: one_workflow.parent.parent / "elsewhere")

    one = workflows.get("tender-report")
    assert one is not None and one.from_plugin

    ok, said = workflows.remove("tender-report")
    assert not ok
    assert "part of that plugin" in said
    assert one_workflow.exists(), "the plugin's files were deleted anyway"


def test_the_page_is_told_the_switch_and_the_owner(one_workflow, monkeypatch):
    """The page is handed dicts, not `Workflow` objects.

    Jinja asking a dict for `one.on` finds neither an attribute nor a key and
    answers Undefined, which is falsy -- so adding the switch to the model and
    forgetting the row builder made every row draw as "off" while the button
    did nothing visible. It does not raise. Measured in the browser: both
    rows read "off" with only one of them switched off.
    """
    from aki_agent.dashboard.app import _workflow_rows

    rows, _ = _workflow_rows()
    assert rows, "no workflow was read at all"
    for row in rows:
        assert "on" in row, "the page cannot draw a switch it is not given"
        assert "from_plugin" in row


def test_the_list_is_rows_and_the_pack_form_is_a_sheet():
    page = without_comments(
        (TEMPLATES / "_workflows.html").read_text(encoding="utf-8"))
    assert "<table>" not in page
    assert "rowitem" in page
    assert "/workflows/switch" in page

    outer = without_comments(
        (TEMPLATES / "workflows.html").read_text(encoding="utf-8"))
    assert '<dialog id="packform"' in outer
    assert "{{ 'open' if showing_form }}" in outer
    # -- and a pack is just
    # as often the folder somebody unzipped, which `examine()` accepts too.
    assert "/knowledge/files/native" in outer
    assert "/schedule/folders/native" in outer


def test_the_sheet_stays_open_while_looking_at_a_pack():
    """Otherwise pressing "Look at it" closes the sheet and drops the answer
    behind it."""
    source = (REPO_ROOT / "src" / "aki_agent" / "dashboard"
              / "app.py").read_text(encoding="utf-8")
    assert 'showing_form=bool(request.args.get("add")\n' \
           '                              or request.args.get("check"))' in source
