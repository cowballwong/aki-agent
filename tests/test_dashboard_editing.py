"""Adding and removing workspaces and projects from the dashboard.

reported 2026-08-19: a [+] and a [-] on the workspace and project pages, with a
double confirmation on the [-]. The interesting half is the [-], because what
is behind it is a folder of the user's own documents -- the thing everything
else in this package refuses to touch.

The two confirmations are different in kind, and both are tested here:

  1. the person types the folder name back, checked on the server, so a stray
     click cannot remove anything even with the browser dialog defeated;
  2. what "remove" does is a move into the sandbox, so being wrong is
     recoverable rather than final.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aki_agent.dashboard import app as dashboard_app
from aki_agent.dashboard import create_app


@pytest.fixture
def installed(tmp_path) -> Path:
    """A real folder tree with a config pointing at it."""
    root = tmp_path / "Assistant"
    for folder in ("01_Config", "02_Sandbox"):
        (root / folder).mkdir(parents=True)
    project = root / "03_Workspace" / "01_Work" / "01_Project-1"
    project.mkdir(parents=True)
    (project / "state.md").write_text("# State\n", encoding="utf-8")
    (project / "signed-contract.pdf").write_text("mine", encoding="utf-8")

    config_path = root / "01_Config" / "config.yaml"
    config_path.write_text(yaml.safe_dump({
        "schema_version": 1,
        "assistant": {"name": "Mira"},
        "user": {"name": "Sam"},
        "layout": {
            "root": str(root),
            "workspaces": ["01_Work"],
            "item_label": "Project",
            "item_label_plural": "Projects",
            "summary_files": ["state"],
        },
    }), encoding="utf-8")
    return config_path


def browser_for(config_path: Path):
    app = create_app(config_path)
    app.config["TESTING"] = True
    return app.test_client()


def token() -> str:
    return dashboard_app.SESSION_TOKEN


# ---------------------------------------------------------------------------
# The buttons are on the page at all
#
# Written first because the whole class of bug this package keeps hitting is a
# control that exists in the code and never appears: `space.workspaces` was
# Undefined in Jinja, which is falsy, so the remove panel rendered as nothing
# at all and no error was raised anywhere.


def test_the_front_page_offers_adding_and_removing_a_workspace(installed):
    """Both, from the cards, since 2026-09-05.

    They were fold-outs at the foot of the page -- "+ Add a workspace" and
    "- Remove a workspace". so the empty card adds one and the minus on a
    card retires it, exactly as the projects do.
    """
    html = browser_for(installed).get("/projects").get_data(as_text=True)

    assert 'id="addspace"' in html, "the empty card adds one"
    assert "01_Work" in html, "the workspace has to be listed to be removable"


def test_removing_a_workspace_is_offered_once_there_is_a_choice(installed):
    """The minus rides on the workspace cards, and those are only drawn when
    there is more than one workspace -- with a single one the page shows its
    projects instead. Nothing is lost by that: removing your only workspace
    is not a thing to make one click away."""
    from aki_agent.dashboard.templates import __file__ as _  # noqa: F401
    from pathlib import Path as _Path

    page = (_Path(__file__).resolve().parents[1] / "src" / "aki_agent"
            / "dashboard" / "templates" / "index.html").read_text(
        encoding="utf-8")

    assert 'formaction="/workspace/remove"' in page


def test_a_workspace_page_offers_adding_and_removing_a_project(installed):
    """Both, from the cards. reported 2026-09-05.

    They were fold-outs at the foot of the page until then -- "+ Add project"
    and "- Remove project", three clicks deeper than the thing they act on.
    The empty card adds one and the minus on a card retires it, so this now
    asks for the controls rather than for the old headings.
    """
    html = browser_for(installed).get("/workspace/01_Work").get_data(as_text=True)

    assert 'id="additem"' in html, "the empty card adds one"
    assert 'formaction="/item/remove"' in html, "the minus retires one"
    assert "01_Project-1" in html


def test_pages_reached_from_another_page_have_a_back_link(installed):
    client = browser_for(installed)

    workspace_page = client.get("/workspace/01_Work").get_data(as_text=True)
    item_page = client.get("/item/01_Work/01_Project-1").get_data(as_text=True)

    assert 'class="back"' in workspace_page
    assert 'class="back"' in item_page
    assert 'href="/workspace/01_Work"' in item_page


# ---------------------------------------------------------------------------
# Adding


def test_adding_a_workspace_creates_the_folder_and_records_it(installed):
    root = installed.parent.parent
    response = browser_for(installed).post("/workspace/new", data={
        "token": token(), "name": "Church"})

    assert response.status_code in (302, 303)
    assert (root / "03_Workspace" / "02_Church").is_dir(), \
        [p.name for p in (root / "03_Workspace").iterdir()]

    written = yaml.safe_load(installed.read_text(encoding="utf-8"))
    assert "02_Church" in written["layout"]["workspaces"], \
        "the folder and the config must be written by the same action"


def test_adding_a_project_creates_its_summary_files(installed):
    root = installed.parent.parent
    browser_for(installed).post("/item/new", data={
        "token": token(), "workspace": "01_Work", "name": "Barn Conversion"})

    made = [p for p in (root / "03_Workspace" / "01_Work").iterdir()
            if p.is_dir() and "Barn" in p.name]
    assert made, [p.name for p in (root / "03_Workspace" / "01_Work").iterdir()]
    assert (made[0] / "state.md").is_file()


# ---------------------------------------------------------------------------
# Removing -- the half that matters


def test_removing_a_project_does_nothing_without_the_typed_name(installed):
    root = installed.parent.parent
    project = root / "03_Workspace" / "01_Work" / "01_Project-1"

    browser_for(installed).post("/item/remove", data={
        "token": token(), "workspace": "01_Work",
        "folder": "01_Project-1", "confirm": "yes"})

    assert (project / "signed-contract.pdf").is_file(), \
        "a wrong confirmation removed the user's work"


def test_removing_a_project_moves_it_into_the_sandbox(installed):
    root = installed.parent.parent
    project = root / "03_Workspace" / "01_Work" / "01_Project-1"

    browser_for(installed).post("/item/remove", data={
        "token": token(), "workspace": "01_Work",
        "folder": "01_Project-1", "confirm": "01_Project-1"})

    assert not project.exists()
    moved = list((root / "02_Sandbox" / "_removed").glob("01_Project-1-*"))
    assert moved, "removed work must still exist somewhere"
    assert (moved[0] / "signed-contract.pdf").read_text(encoding="utf-8") == "mine"


def test_removing_a_workspace_takes_it_out_of_the_config_too(installed):
    root = installed.parent.parent

    browser_for(installed).post("/workspace/remove", data={
        "token": token(), "name": "01_Work", "confirm": "01_Work"})

    written = yaml.safe_load(installed.read_text(encoding="utf-8"))
    # `.get`: removing the only workspace leaves the list empty, and an empty
    # list is not written out at all.
    assert "01_Work" not in written["layout"].get("workspaces", []), \
        "a workspace left in the config with no folder is the mismatch that " \
        "gave two real installs an empty dashboard"
    assert list((root / "02_Sandbox" / "_removed").glob("01_Work-*"))


def test_nothing_can_be_removed_without_the_dashboards_own_token(installed):
    root = installed.parent.parent
    project = root / "03_Workspace" / "01_Work" / "01_Project-1"

    response = browser_for(installed).post("/item/remove", data={
        "workspace": "01_Work", "folder": "01_Project-1",
        "confirm": "01_Project-1"})

    assert response.status_code == 403
    assert project.is_dir()


# ---------------------------------------------------------------------------
# Stopping it
#
# The maintainer asked for a Shut Down button: the launcher starts the dashboard in a
# window nobody keeps, so stopping it meant hunting for the process. Werkzeug
# removed `werkzeug.server.shutdown` in 2.1 and there is no replacement for a
# plain `app.run()`, so the button answers the request and then ends the
# process. That last part is injected here rather than executed, for reasons
# that should be obvious in a test suite.


def test_the_stop_button_is_on_the_page(installed):
    html = browser_for(installed).get("/").get_data(as_text=True)

    assert "Stop the dashboard" in html


def test_stopping_needs_the_dashboards_own_token(installed):
    called = []
    app = create_app(installed)
    app.config["TESTING"] = True
    app.config["PERSONAL_AGENT_STOPPER"] = lambda: called.append(True)

    refused = app.test_client().post("/shutdown")

    assert refused.status_code == 403
    assert not called, "a page on another site could stop it"


def test_stopping_says_the_assistant_is_still_running(installed):
    """The fear the button creates is 'have I just killed my assistant?'."""
    called = []
    app = create_app(installed)
    app.config["TESTING"] = True
    app.config["PERSONAL_AGENT_STOPPER"] = lambda: called.append(True)

    response = app.test_client().post("/shutdown", data={"token": token()})

    assert called == [True]
    assert response.status_code == 200
    assert "still running" in response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# The rail, after it was cut from twenty entries to six
#
# Grouping costs a
# click, so the tests below are mostly about the three things that pay it
# back: no address moved, the counts still show, and the user's own word
# survives in the chrome.


def test_every_address_the_rail_offers_still_answers(installed):
    from aki_agent.dashboard import navigation

    client = browser_for(installed)

    dead = [path for path in navigation.every_path()
            if client.get(path).status_code != 200]

    assert not dead, f"the rail points at pages that do not answer: {dead}"


def test_the_rail_entries_are_the_ones_the_rail_claims(installed):
    import re

    html = browser_for(installed).get("/").get_data(as_text=True)

    # Inbox left the rail on 2026-08-23, at the maintainer's request -- Today's three
    # queue buttons open the same items, split by whose move it is.
    assert re.findall(r'data-group="(\w+)"', html) == [
        "today", "work", "abilities", "system", "settings"]


def test_a_group_page_shows_its_tabs(installed):
    html = browser_for(installed).get("/yours").get_data(as_text=True)

    assert 'class="tabs"' in html
    # Abilities after the 2026-08-21 redesign: Skills and Specialists became
    # one page because their split was a storage detail, and Learned became a
    # section of Knowledge because it was a read-only page of three lines.
    #
    # Renamed to "Tools" on 2026-09-05, when the Library moved inside it as a
    # third sub-tab -- so Library is no longer a tab of this group, and
    # looking for it here would now find the sub-tab strip instead and pass
    # for the wrong reason.
    for label in ("Tools", "Knowledge", "Schedule"):
        assert label in html
    assert "Yours" not in html


def test_a_group_of_one_shows_no_tabs(installed):
    """A tab strip with a single tab is furniture, not navigation."""
    # Settings gained a second page in the redesign (Rules & limits), so the
    # group of one is now Workspace.
    html = browser_for(installed).get("/projects").get_data(as_text=True)

    assert 'class="tabs"' not in html


def test_the_rail_never_says_projects_to_someone_who_does_not_have_any():
    """No profession word in shared chrome -- the rule the whole package
    rests on. The first draft of the rail hardcoded "Projects".

    The tab used to be renamed to whatever the person calls their work, since
    it led to a list of those. It now leads to the list of **workspaces**,
    and "workspace" is this package's own word rather than any profession's.
    So the rule is satisfied by there being nothing to rename -- which is a
    stronger position than renaming correctly, because it cannot be got wrong
    later.

    The test therefore checks the outcome the rule is about, not the
    mechanism that used to deliver it: no word belonging to one trade may
    appear in the chrome shown to another.
    """
    from aki_agent.dashboard import navigation

    for plural in ("Students", "Projects", "Cases"):
        groups = navigation.for_label(plural)
        work = [g for g in groups if g.key == "work"][0]
        assert work.pages[0].label == "Workspace"
        assert navigation.current("/projects", groups).label == "Workspace"

    every_label = " ".join(page.label for group in navigation.GROUPS
                           for page in group.pages)
    for trade_word in ("Students", "Projects", "Patients", "Cases", "Clients"):
        assert trade_word not in every_label, (
            f"'{trade_word}' is one profession's word and is in the rail")


def test_a_count_shows_on_the_group_and_not_only_inside_it(installed):
    """A badge you have to open a group to see is a badge that does nothing.

    Waiting moved next to Notifications (reported 2026-08-20) -- they answer the
    same question and were a group apart -- so the badge moved with it. That
    is the part worth holding: a page can be moved anywhere, but its count has
    to keep showing on whichever group now holds it, or the move quietly makes
    the number invisible.
    """
    from aki_agent.dashboard import navigation

    # Tested on a group built here rather than on one from the rail. As of
    # 2026-08-23 no rail entry declares a badge -- Inbox was the last one and
    # it left -- so reaching for a live group would only prove that a page
    # with no badge shows no number, which is not the claim.
    #
    # The facility is kept because it is one word per page to use and the
    # next queue to earn a number will need it. What is guarded is that it
    # still adds up correctly when something does.
    group = navigation.Group("q", "Queue", "*", (
        navigation.Page("/one", "One", badge="waiting_count"),
        navigation.Page("/two", "Two", badge="held_count,pending_count"),
    ))

    assert group.count({"waiting_count": 3}) == 3
    assert group.count({}) == 0

    # More than one count on a page adds up, rather than the badge showing
    # one of them and sending somebody to a page with more on it than the
    # number promised.
    assert group.count({"waiting_count": 2, "held_count": 5,
                        "pending_count": 1}) == 8

    # And a group whose pages ask for nothing shows nothing, however many
    # counts are going spare. Notifications lost its badge on 2026-08-23 --
    # A number on a page of rules counts something that page
    # cannot help you with.
    system = navigation.current("/notifications")
    assert system.count({"held_count": 5}) == 0


# ---------------------------------------------------------------------------
# A workspace made from the dashboard, and the first project in it
#
# Reported: a project could not be created inside a workspace made from the
# dashboard, while the workspaces that came with the install were fine.
#
# Both halves were covered and the join between them was not. One test adds a
# workspace; another adds a project to the workspace the fixture already had.
# Nothing had ever added a project to a workspace the dashboard itself had
# just made -- which is empty, which is the whole of the bug.


def test_an_empty_workspace_still_offers_the_add_card(installed):
    """The [+] is what puts the first project in, so it cannot be hidden until
    there is one. `workspace.html` showed the card grid only `{% if items %}`,
    and a workspace is empty at the moment it is created."""
    client = browser_for(installed)
    client.post("/workspace/new", data={"token": token(), "name": "Church"})

    html = client.get("/workspace/02_Church").get_data(as_text=True)

    assert 'id="additem"' in html, "an empty workspace has no way to add the first project"
    assert 'name="workspace" value="02_Church"' in html, \
        "the add form must say which workspace it is adding to"


def test_a_project_can_be_added_to_a_workspace_made_from_the_dashboard(installed):
    root = installed.parent.parent
    client = browser_for(installed)

    client.post("/workspace/new", data={"token": token(), "name": "Church"})
    made = root / "03_Workspace" / "02_Church"
    assert made.is_dir(), [p.name for p in (root / "03_Workspace").iterdir()]

    client.post("/item/new", data={
        "token": token(), "workspace": "02_Church", "name": "Choir Rota"})

    assert [p for p in made.iterdir() if p.is_dir()], (
        "a project added to a dashboard-made workspace was not created")


def test_the_single_workspace_front_page_names_its_workspace(installed):
    """With one workspace the front page shows its projects directly, and the
    add form has to carry that workspace's name. It read `name`, which only the
    workspace page sets, so the field went out empty."""
    html = browser_for(installed).get("/projects").get_data(as_text=True)

    assert 'name="workspace" value="01_Work"' in html, \
        "the front page's add form must name the workspace it is adding to"


def test_a_project_is_never_created_outside_a_workspace(installed):
    """The guard behind the template fix.

    A blank workspace used to collapse to the work root, and the project was
    created beside the workspaces rather than inside one -- with no error, so
    the user simply could not find what they had just added."""
    root = installed.parent.parent
    before = sorted(p.name for p in (root / "03_Workspace").iterdir())

    browser_for(installed).post("/item/new", data={
        "token": token(), "workspace": "", "name": "Ghost"})

    after = sorted(p.name for p in (root / "03_Workspace").iterdir())
    assert after == before, f"a stray folder was created: {set(after) - set(before)}"
