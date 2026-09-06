"""Tools: Skills, Specialists and the Library, and none of them a long page.

reported 2026-09-05:






He asked for an on/off on each row in the same message and withdrew it a few
minutes later -- so there is none,
and nothing here should grow one back by accident.

The Library button was the interesting one. `library.activate` already copied
a skill into the folder Claude Code reads and wrote a specialist into the
specialists file, so the chosen thing already landed in one of these two
lists. Only the word was wrong: "turn on" describes a switch on that page,
and what happens is that a copy arrives somewhere else.
"""

from __future__ import annotations

import re
from pathlib import Path

from aki_agent import skills_store, specialists
from aki_agent.dashboard import app as app_module, navigation

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "src" / "aki_agent" / "dashboard" / "templates"


def without_comments(text: str) -> str:
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


# ---------------------------------------------------------------------------
# The tab, and what is inside it
# ---------------------------------------------------------------------------

def test_the_tab_is_called_tools():
    group = next(g for g in navigation.GROUPS if g.key == "abilities")
    labels = [page.label for page in group.pages]

    assert "Tools" in labels
    assert "Yours" not in labels


def test_the_library_is_no_longer_a_tab_of_its_own():
    """The library is no longer a tab of its own."""
    group = next(g for g in navigation.GROUPS if g.key == "abilities")
    labels = [page.label for page in group.pages]

    assert "Library" not in labels

    # But its address still resolves to this tab, so the rail highlights
    # Tools while you are on it.
    tools = next(page for page in group.pages if page.label == "Tools")
    assert "/library" in tools.also


def test_the_address_did_not_move():
    """`/tools` is the API-keys page under System.

    Taking that name would have meant either a collision or moving a page
    nobody asked to move, so the label changed and the address did not.
    """
    group = next(g for g in navigation.GROUPS if g.key == "abilities")
    tools = next(page for page in group.pages if page.label == "Tools")

    assert tools.path == "/yours"


def test_all_three_tabs_appear_on_all_three_pages(dashboard_client):
    for url in ("/yours?tab=skills", "/yours?tab=specialists", "/library"):
        page = dashboard_client.get(url).get_data(as_text=True)
        assert "/yours?tab=skills" in page, url
        assert "/yours?tab=specialists" in page, url
        assert 'href="/library"' in page, url


def test_the_old_list_addresses_still_answer(dashboard_client):
    """Linked from guides, from earlier notes, and from bookmarks."""
    for url, tab in (("/skills", "skills"), ("/specialists", "specialists")):
        answer = dashboard_client.get(url)
        assert answer.status_code == 302
        assert f"tab={tab}" in answer.headers["Location"]

        landed = dashboard_client.get(url, follow_redirects=True)
        assert landed.status_code == 200


def test_there_is_only_one_template_drawing_each_list():
    """The redirect exists so that there is not a second one.

    Rendering the same partial from two routes means two places deciding
    what the edit dialog contains, and the second is the one that goes
    stale.
    """
    assert not (TEMPLATES / "skills.html").exists()
    assert not (TEMPLATES / "specialists.html").exists()


# ---------------------------------------------------------------------------
# The rows
# ---------------------------------------------------------------------------

def test_a_row_shows_the_name_and_hides_the_rest(dashboard_client):
    dashboard_client.post("/skills/save", data={
        "token": app_module.SESSION_TOKEN,
        "name": "Weekly update",
        "description": "Use when I ask for my Monday report.",
        "body": "READ THE WEEK AND SAY WHAT MOVED",
    })

    page = dashboard_client.get("/yours?tab=skills").get_data(as_text=True)

    assert "Weekly update" in page
    assert "<summary>Open</summary>" in page
    # The body is on the page but inside the closed `<details>`, which is
    # what "click 個打開button 先睇到detail" means -- not fetched later.
    assert "READ THE WEEK AND SAY WHAT MOVED" in page
    assert "<details" in page


def test_neither_list_is_a_table_any_more():
    """They were four-column tables with a whole edit form folded into every
    second row, which is what made the page unreachable at the bottom."""
    for name in ("_skills.html", "_specialists.html"):
        page = without_comments((TEMPLATES / name).read_text(encoding="utf-8"))
        assert "<table>" not in page, name
        assert "rowitem" in page, name


def test_no_on_off_switch_was_added_to_either_list():
    """Asked for and withdrawn within a few minutes.

    Guarded because it was half-built when he changed his mind -- a
    `held_dir()` in `skills_store` and an `on` flag on `Skill` -- and a
    half-removed feature is the kind that grows back.
    """
    assert not hasattr(skills_store, "held_dir")
    assert "on" not in skills_store.Skill.__dataclass_fields__
    assert "enabled" not in specialists.Specialist.__dataclass_fields__

    for name in ("_skills.html", "_specialists.html"):
        page = without_comments((TEMPLATES / name).read_text(encoding="utf-8"))
        assert "/skills/toggle" not in page
        assert "/specialists/toggle" not in page


# ---------------------------------------------------------------------------
# The forms
# ---------------------------------------------------------------------------

def test_adding_opens_a_sheet_rather_than_a_form_down_the_page(
        dashboard_client):
    """Adding opens a sheet rather than a form down the page."""
    for tab, sheet in (("skills", "skillform"),
                       ("specialists", "specialistform")):
        shut = dashboard_client.get(
            f"/yours?tab={tab}").get_data(as_text=True)
        opened = dashboard_client.get(
            f"/yours?tab={tab}&add=1").get_data(as_text=True)

        assert f'id="{sheet}"' in shut, tab
        assert "open>" in opened, tab
        assert "open>" not in shut.split(f'id="{sheet}"')[1][:80], tab


def test_editing_opens_the_same_sheet_already_filled(dashboard_client):
    """Editing opens the same sheet already filled."""
    dashboard_client.post("/skills/save", data={
        "token": app_module.SESSION_TOKEN,
        "name": "Site notes",
        "description": "Use after a site visit.",
        "body": "Write it up.",
    })

    page = dashboard_client.get(
        "/yours?tab=skills&edit=site-notes").get_data(as_text=True)

    assert 'value="Site notes"' in page
    assert 'name="key" value="site-notes"' in page
    assert "Save changes" in page


def test_an_edit_of_something_that_is_not_there_does_not_claim_to_be_one(
        dashboard_client):
    """Otherwise Save would quietly create a second thing under the name in
    the address, which is the worst possible answer to a stale link."""
    page = dashboard_client.get(
        "/yours?tab=skills&edit=never-existed").get_data(as_text=True)

    assert "Save changes" not in page
    assert 'name="key" value=""' in page


def test_the_sheet_is_opened_by_the_address_not_by_script():
    """So Add and Edit work with JavaScript switched off, which a dialog
    opened by `showModal()` alone would quietly have cost."""
    for name in ("_skills.html", "_specialists.html"):
        page = (TEMPLATES / name).read_text(encoding="utf-8")
        assert "{{ 'open' if showing_form }}" in page, name
        assert "showModal" not in page, name


def test_one_script_makes_every_sheet_modal():
    """It was written into `schedule.html` first, and within the hour the
    Tools page got the markup without the script -- so its form opened
    un-modal, in the flow, and looked broken. Measured before the fix:
    `dialog.matches(':modal')` was false on Tools and true on Schedule."""
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert "dialog.sheet[open]" in base
    assert "showModal" in base

    # The page that had the first copy must not have grown it back. Narrowed
    # to the task form: `schedule.html` legitimately calls `showModal` on the
    # FOLDER PICKER, which is a different dialog that a button opens rather
    # than the address, and asserting on the bare word failed on that.
    schedule = (TEMPLATES / "schedule.html").read_text(encoding="utf-8")
    assert "taskform" in schedule
    assert "taskform').showModal" not in schedule
    assert "form.showModal" not in schedule


# ---------------------------------------------------------------------------
# The Library
# ---------------------------------------------------------------------------

def test_the_library_button_says_add(dashboard_client):
    """The assertion used to be `<the exact markup> or "Add" in page`.

    The second half is satisfied by any occurrence of those three letters
    anywhere on the page -- and there are six, including "Adding one puts a
    copy..." in a comment `base.html` serves to the browser. So the whole
    assertion could not fail while the page rendered at all, and the exact
    markup it names has not matched since the button was re-indented. Only
    the two `not in` lines below ever tested anything.
    """
    import re

    page = dashboard_client.get("/library").get_data(as_text=True)

    buttons = re.findall(r"<button[^>]*>(.*?)</button>", page, re.DOTALL)
    assert buttons, "no buttons rendered at all"
    assert any(one.strip() == "Add" for one in buttons), (
        "no button says exactly Add -- found: "
        + ", ".join(sorted({one.strip()[:20] for one in buttons})))
    assert "Turn on" not in page
    assert "Turn off" not in page


def test_adding_from_the_library_lands_in_one_of_the_two_lists(
        dashboard_client, monkeypatch):
    """Adding from the library lands in one of the two lists.

    Already true before the rename -- this is the test that says so, and
    that would catch the day the button stopped doing it.
    """
    from aki_agent import library as library_module

    catalogue = library_module.catalogue()
    skill = next((one for one in catalogue if one.kind == "skill"), None)
    assert skill is not None, "the library ships no skills at all"

    dashboard_client.post("/library/toggle", data={
        "token": app_module.SESSION_TOKEN,
        "key": skill.key,
        "state": "on",
    })

    listed = dashboard_client.get(
        "/yours?tab=skills").get_data(as_text=True)
    assert skill.name in listed
