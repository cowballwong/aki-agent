"""Today shows what you chose, and one empty card to choose with.

reported 2026-09-04, over a screenshot of three cards he had never picked:



The row used to fill its empty slots by recency and label each guess "not
pinned". `favourites.py` had already argued against exactly that in its own
docstring: a pin is a statement about what matters, a timestamp is a
statement about what happened. A guess with a disclaimer is still a guess.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aki_agent import atomic, favourites, paths

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "src" / "aki_agent" / "dashboard" / "templates"


class _Item:
    def __init__(self, key, title, workspace=""):
        self.key = key
        self.title = title
        self.workspace = workspace
        self.sections = {}
        self.last_modified = None


class _Space:
    def __init__(self, items):
        self.items = items


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    return tmp_path


def test_an_untouched_machine_shows_no_cards_at_all(home):
    """Not six strangers. The empty card is the whole of the empty state."""
    space = _Space([_Item("a", "One"), _Item("b", "Two"), _Item("c", "Three")])

    assert favourites.cards_for(space) == []


def test_a_pinned_project_is_the_only_thing_that_appears(home):
    space = _Space([_Item("a", "One"), _Item("b", "Two")])
    favourites.pin("b")

    cards = favourites.cards_for(space)

    assert [card.title for card in cards] == ["Two"]
    assert cards[0].pinned


def test_recency_no_longer_fills_the_empty_slots(home):
    """The behaviour this replaced, pinned so it does not come back.

    It was defensible -- a blank row on day one looks broken -- and it was
    still the machine putting five projects on the front page and writing
    "not pinned" on each.
    """
    import datetime as when

    space = _Space([
        _Item("a", "Touched today"),
        _Item("b", "Touched last year"),
    ])
    space.items[0].last_modified = when.datetime.now()
    favourites.pin("b")

    assert [card.title for card in favourites.cards_for(space)] == [
        "Touched last year"]


def test_six_is_the_cap(home):
    for n in range(favourites.HOW_MANY):
        changed, _ = favourites.pin(f"p{n}")
        assert changed

    changed, said = favourites.pin("one-too-many")

    assert not changed
    assert "6" in said


# ---------------------------------------------------------------------------
# The empty card and its picker
# ---------------------------------------------------------------------------

def test_the_empty_card_is_offered_while_there_is_room():
    page = (TEMPLATES / "_favourites.html").read_text(encoding="utf-8")

    assert 'id="addfavour"' in page
    assert "{% if favourites_pinned < favourites_max %}" in page, (
        "the card must appear while there is room and stop at the cap")


def test_the_plus_counts_pins_rather_than_cards():
    """They are not always the same number.

    A pin whose project has been renamed is skipped as a card and still
    counts against the six -- `favourites.py` keeps it on purpose, because
    renaming a folder should not quietly forget that somebody cared. Gating
    the button on the cards drawn would offer an Add that `pin()` can only
    refuse. Reproduced with six pins, three of them stale: cards 3, plus
    button gone.
    """
    page = (TEMPLATES / "_favourites.html").read_text(encoding="utf-8")

    assert "favourites | length < favourites_max" not in page
    assert "favourites_pinned < favourites_max" in page


def test_the_picker_lives_outside_the_main_column():
    """`main` is a stacking context, and this dashboard has now been bitten
    three times by putting a modal inside it.

    First render of the picker did it again: the backdrop's z-index of 120
    was measured inside main's 1 and lost to the rail's 20, so
    `elementFromPoint` over the navigation returned NAV while the picker was
    up. Split into its own partial and included after `</main>`.
    """
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")

    closes_main = base.index("</main>")
    include = base.index('{% include "_picker.html" %}')

    assert include > closes_main
    assert 'id="picker"' not in (
        TEMPLATES / "_favourites.html").read_text(encoding="utf-8")


def test_the_picker_is_grouped_by_workspace_and_says_what_is_already_on():
    page = (TEMPLATES / "_picker.html").read_text(encoding="utf-8")

    assert "{% for group in pickable %}" in page
    assert "group.projects" in page, (
        "`group.items` resolves to the dict's own .items METHOD in Jinja, "
        "which rendered 'builtin_function_or_method is not iterable' on the "
        "landing page for every visitor")
    assert "on Today" in page


def test_both_ways_in_post_to_the_same_route():
    """ -- the empty
    card and the button on a project's own page. Two doors, one lock."""
    picker = (TEMPLATES / "_picker.html").read_text(encoding="utf-8")
    items = (TEMPLATES / "_items.html").read_text(encoding="utf-8")

    assert 'action="/projects/pin"' in picker
    assert "/projects/pin" in items


def test_the_card_look_is_never_tied_to_the_anchor_tag():
    """Three times in one evening, so it is a rule now.

    The card look was written as `a.favour`, back when a card WAS a link.
    Arranging needed arrows, a button inside an anchor navigates instead of
    submitting, so each card became `<div class="favour favwrap">` with the
    link inside -- and every card on Today lost its background, its border
    and its accent spine.

    The same bug had already eaten the empty card's dashed outline
    (`button.favour.addcard`), and was still sitting unfixed in the phone
    media query afterwards, where `a.favour` was the only thing keeping a
    card from standing 8.4rem tall on a narrow screen.

    A rule tied to the tag rather than to the thing breaks the moment the
    markup around it changes. So: no styling selector may name the tag.
    """
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    base = re.sub(r"/\*.*?\*/", "", base, flags=re.S)

    offenders = re.findall(r"(?<![\w.-])a\.favour\b[^{;]*\{", base)

    assert not offenders, (
        "the card look must hang off `.favour`, not off the anchor: "
        + ", ".join(one.strip() for one in offenders))


def test_a_phone_card_is_shorter_than_a_desktop_one():
    """The point of the phone rule, which the tag selector had silently
    switched off. The wrapper carries no padding -- that moved to the body
    when the card stopped being a single element -- so the phone override
    has to name the body too, or a card keeps desktop padding inside a
    shorter box."""
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")

    assert ".favour { min-height: 6.2rem" in base
    assert ".favourbody { padding: 0.55rem 0.7rem; }" in base
