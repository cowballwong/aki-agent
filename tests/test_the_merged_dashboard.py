"""Twenty-three pages became fourteen, and nothing was allowed to go missing.

WHY (reported 2026-08-21)
-----------------------
Offered a reordering of the rail, he asked for something else: *"in fact....i
found that the side bar item grouping is not very user friendly.... I Want you
to redesign!!!! Not just moving page, but really think what to put in a page"*.

Reading every template first turned up five outright duplications — the
working-state panel drawn on two pages, one colour field with two editors, one
quiet-hours form on two pages, the same "where secrets live" card at the foot
of two pages, and a Library whose on-switch writes into the very stores the
next two pages list.

THE RULE THIS FILE ENFORCES
---------------------------
A merge must never be a rewrite. Each merged page includes the *same template
pieces* the old pages rendered, unedited — so if one turns out wrong, the piece
is pulled back out and nothing has to be reconstructed from memory. These
tests check that the pieces are still shared rather than copied, that every old
address still answers, and that no content was quietly dropped on the way.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aki_agent.dashboard import create_app, navigation

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "src" / "aki_agent" / "dashboard" / "templates"
EXAMPLE = REPO_ROOT / "configs" / "examples" / "architecture.yaml"

MERGED = {
    # Notifications was merged in here and came back out again on
    # 2026-08-21, at the maintainer's request: waiting-for-a-decision is a
    # queue, being-interrupted is a rule, and a rule is not an item.
    "inbox.html": ["_waiting.html"],
    "yours.html": ["_skills.html", "_specialists.html"],
    "running.html": ["_watching.html", "_sessions.html"],
    # History carried all three of these until 2026-09-04, when the maintainer asked
    # for it to be two tabs -- EOD and Handover -- and nothing else. The
    # event feed and the raw files went back to being their own pages, which
    # they had never stopped being; `_activity.html` went entirely, because
    # the EOD tab reads the same files in a way you can navigate.
    # See `test_history_is_two_tabs_and_still_reaches_the_other_two`.
    "keys.html": ["_tools.html", "_mcp.html"],
    "rules_and_limits.html": ["_rules.html", "_safety.html"],
    "knowledge.html": ["_learned.html"],
}


@pytest.fixture(scope="module")
def browser():
    app = create_app(EXAMPLE)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_every_page_in_the_rail_answers(browser):
    """The whole point of a rail is that everything on it goes somewhere."""
    broken = []
    for group in navigation.GROUPS:
        for page in group.pages:
            if browser.get(page.path).status_code != 200:
                broken.append(page.path)
    assert not broken, f"pages in the rail that do not load: {broken}"


def test_every_old_address_still_answers(browser):
    """Nothing was deleted, so no bookmark may break.

    A 404 here would teach somebody the feature was removed. It was not — it
    became a section of another page, and the old route still renders it.
    """
    broken = []
    for old in navigation.MOVED:
        # `follow_redirects`, because an old address is allowed to have
        # become a door rather than a page -- `/activity` did. What may
        # never happen is that it stops arriving somewhere, which is what
        # this measures.
        if browser.get(old, follow_redirects=True).status_code != 200:
            broken.append(old)
    assert not broken, f"old addresses that stopped working: {broken}"


def test_each_merged_page_includes_the_original_pieces():
    """Included, not copied.

    If a merged page ever grows its own copy of a section instead of including
    the piece, the two drift — and drift is exactly the failure this whole
    exercise was cleaning up.
    """
    for page, pieces in MERGED.items():
        text = (TEMPLATES / page).read_text(encoding="utf-8")
        for piece in pieces:
            assert f'{{% include "{piece}" %}}' in text, (
                f"{page} does not include {piece}")


def test_the_pieces_are_shared_not_duplicated():
    """Each piece has exactly one owner among the old pages, plus its new home.

    Two merged pages including the same piece would put one section in two
    places — which is where this started.
    """
    for piece in {p for pieces in MERGED.values() for p in pieces}:
        users = [path.name for path in TEMPLATES.glob("*.html")
                 if f'{{% include "{piece}" %}}' in
                 path.read_text(encoding="utf-8")]
        assert len(users) in (1, 2), (
            f"{piece} is included by {users} — expected its new home, and "
            "its old page if that page still exists")
        assert len(users) == len(set(users)), f"{piece} included twice"


def test_every_old_page_has_somewhere_its_content_went():
    """The map is complete: no page was dropped from the rail without a home."""
    in_rail = {page.path for group in navigation.GROUPS
               for page in group.pages}
    for old, new in navigation.MOVED.items():
        assert old not in in_rail, f"{old} is both moved and still in the rail"
        assert new in in_rail, f"{old} points at {new}, which is not in the rail"


def test_no_group_is_a_dumping_ground():
    """System was ten pages and had become the place things went when nobody
    knew where they belonged. Five is a list; ten is a search."""
    # Six is the ceiling from 2026-08-23, when Notifications moved into
    # System. The rule guards against a group becoming the place things go
    # when nobody knows where they belong -- System was TEN. A sixth page put
    # there deliberately, by the person who uses it, is not that.
    for group in navigation.GROUPS:
        assert len(group.pages) <= 6, (
            f"{group.label} has {len(group.pages)} pages — at that size a "
            "group stops being a grouping")


def test_the_two_shared_names_were_renamed_rather_than_left_to_collide():
    """`rules` and `starter` each meant two things once the pieces shared a page.

    A silent collision would have drawn the hard limits under the heading for
    the editable rules — a page that looks right and says the opposite of what
    it means.
    """
    safety = (TEMPLATES / "_safety.html").read_text(encoding="utf-8")
    assert "hard_rules" in safety
    assert not re.search(r"\bfor rule in rules\b", safety)

    specialists = (TEMPLATES / "_specialists.html").read_text(encoding="utf-8")
    assert "specialist_starter" in specialists


def test_the_rail_is_smaller_than_it_was():
    """Twenty-three was the problem.

    Sixteen, not fifteen, since 2026-08-21: Notifications was pulled back out
    of Inbox. The point of the number was never the number -- it was that
    twenty-three pages could not be held in anyone's head. One page back for
    a reason a person gave is not the failure this guards against; a slow
    return to twenty-three is.
    """
    pages = sum(len(group.pages) for group in navigation.GROUPS)
    assert pages <= 16, f"{pages} pages in the rail"
    # A ceiling, not a fixed number. This line has been edited three times
    # now -- 15, 16, 6 -- each time because a group legitimately moved, and
    # each edit taught a little less. The claim worth keeping is that the rail
    # does not grow back towards twenty-three; equality only asserts that
    # today's arrangement is today's arrangement, which the rest of this file
    # already covers.
    #
    # Five since 2026-08-23: Inbox left the rail, because Today's three queue
    # buttons open the same items split by whose move it is.
    assert len(navigation.GROUPS) <= 6


def test_a_section_that_moved_pages_brought_its_data_with_it(browser):
    """Including a template piece is not enough — the view has to feed it.

    The theme picker moved onto Settings and rendered a heading with nothing
    under it, because `settings_page` did not pass `themes`. Jinja treats an
    undefined name as empty and loops over it silently, so the page returned
    200 and looked finished. The maintainer found it within the hour by asking where
    the colours had gone.

    So each merged section is checked for something only its DATA can produce,
    not merely for the include.
    """
    filled = {
        "/theme": "theme/choose",         # the specimen cards
        "/inbox": "quiet",                # the notification settings form
        "/rules": "safety",               # the hard-limit list
        "/keys": "mcp",                   # the server table
    }
    empty = []
    for path, evidence in filled.items():
        html = browser.get(path).get_data(as_text=True)
        if evidence not in html:
            empty.append(f"{path} is missing {evidence!r}")
    assert not empty, (
        "these merged sections render but have no data behind them: "
        + "; ".join(empty))


def test_history_is_two_tabs_and_still_reaches_the_other_two():
    """Two tabs, and no orphans.


    The event feed and the raw log browser were only ever reachable through
    History. Dropping their tabs without leaving a way in would have left two
    working routes that nothing in the dashboard points at -- which is how a
    page quietly stops existing.
    """
    text = (TEMPLATES / "history.html").read_text(encoding="utf-8")

    assert '("eod", "EOD")' in text
    assert '("handoff", "Handover")' in text
    assert 'href="/events"' in text
    assert 'href="/logs"' in text
