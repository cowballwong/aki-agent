"""the maintainer's five, sent one at a time on 2026-09-05 with a screenshot each.

  1.
  2.
  3.
  4.
  5.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aki_agent import atomic, favourites, paths

TEMPLATES = (Path(__file__).resolve().parents[1] / "src" / "aki_agent"
             / "dashboard" / "templates")


def _markup(name: str) -> str:
    """The template with its Jinja comments taken out.

    Every "this is gone" check below has to read markup rather than the file:
    the note left where each removed thing stood quotes it in full. Five
    separate tests were written wrong that way on 2026-09-04 before the habit
    stuck.
    """
    text = (TEMPLATES / name).read_text(encoding="utf-8")
    return re.sub(r"\{#.*?#\}", "", text, flags=re.S)


# ---------------------------------------------------------------------------
# 1. Workspaces get the same plus and minus as the projects
# ---------------------------------------------------------------------------

def test_a_workspace_is_added_from_an_empty_card():
    page = _markup("index.html")

    assert 'id="addspace"' in page
    assert 'formaction="/workspace/new"' in page or \
           'action="/workspace/new"' in page


def test_a_workspace_is_retired_from_a_minus_on_its_card():
    page = _markup("index.html")

    assert 'class="itdrop wsdrop"' in page
    assert 'formaction="/workspace/remove"' in page


def test_the_old_fold_outs_are_gone():
    page = _markup("index.html")

    assert "Add a workspace</summary>" not in page
    assert "Remove a workspace</summary>" not in page


def test_removing_a_workspace_still_asks_twice():
    """And the second question is the name, which the route checks itself."""
    page = TEMPLATES / "index.html"
    text = page.read_text(encoding="utf-8")

    assert "window.confirm(" in text and "window.prompt(" in text
    assert 'id="wsconfirm"' in text
    assert "_removed" in text, (
        "the first question has to say the folder is moved, not deleted")


# ---------------------------------------------------------------------------
# 2. A project card says how the project is doing
# ---------------------------------------------------------------------------

def test_the_card_carries_the_state_line_and_the_counts():
    page = _markup("_items.html")

    assert 'class="itnote"' in page
    assert "lines_starting('- [ ]')" in page
    assert "lines_starting('- ')" in page


def test_the_counts_come_from_the_same_function_the_favourites_use():
    """A second copy of the rule is how "1 open" here and "2 open" on Today
    start disagreeing about the same file."""
    assert favourites.count_lines("- [ ] a\n- [x] b\n", "- [ ]") == 1
    assert favourites.count_lines("- one\n- two\n", "- ") == 2


def test_jinja_has_no_match_test():
    """The first version used `select('match', ...)`, which compiles and then
    raises `No test named 'match'` on the first real render -- so a template
    that parsed was still broken for every visitor."""
    page = _markup("_items.html")

    assert "select('match'" not in page


# ---------------------------------------------------------------------------
# 3. The toolbar row lines up
# ---------------------------------------------------------------------------

def test_the_toolbar_clears_the_margin_that_pushed_save_down():
    """Measured, not eyeballed: every button in the row is 28px tall and the
    row centres them, and Save still read `top: 107` against `100`. The
    generic primary-button rule carries a top margin meant for a submit
    button at the foot of a form."""
    css = (TEMPLATES / "base.html").read_text(encoding="utf-8")

    assert ".wstools button { margin: 0; }" in css


def test_the_card_head_centres_its_controls():
    """A 33px field, a 15px star and an 18px minus on a baseline is what made
    edit mode look ragged."""
    css = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    block = css[css.index(".favour.itcard .favourhead {"):]
    block = block[:block.index("}")]

    assert "align-items: center" in block


# ---------------------------------------------------------------------------
# 4. Arranging the favourite cards
# ---------------------------------------------------------------------------

@pytest.fixture
def pinned(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    for key in ("a", "b", "c"):
        favourites.pin(key)
    return favourites


def test_a_card_moves_one_place_at_a_time(pinned):
    moved, _ = pinned.move("c", -1)

    assert moved
    assert pinned.read_pins() == ["a", "c", "b"]


def test_a_move_off_the_end_does_nothing_rather_than_wrapping(pinned):
    """An arrow that teleports the first card to the last place is a surprise
    every time it happens."""
    moved, said = pinned.move("a", -1)

    assert not moved
    assert pinned.read_pins() == ["a", "b", "c"]
    assert "end" in said


def test_moving_something_that_is_not_pinned_is_refused(pinned):
    moved, said = pinned.move("nope", 1)

    assert not moved
    assert "not on Today" in said


def test_the_arrows_are_outside_the_card_link():
    """A button inside an anchor navigates instead of submitting."""
    page = _markup("_favourites.html")

    head = page.index('class="favourbody"')
    arrows = page.index('class="favarrow favleft"')
    closes = page.index("</a>", head)

    assert arrows > closes, "the arrows must sit after the link closes"


def test_arranging_holds_until_save():
    """Arranging holds until save.

    Each arrow used to submit and reload, so one press was one round trip and
    the order was written before he had finished deciding. The arrows now
    move the cards on the page and the finished sequence goes in one post.
    """
    page = _markup("_favourites.html")

    assert 'name="order"' in page, "the finished sequence is what is sent"
    assert 'id="favsave"' in page and 'id="favcancel"' in page
    assert "e.preventDefault();" in page, (
        "an arrow must not submit while arranging")


def test_the_arrows_still_work_with_no_script():
    """`formaction` and `by` stay on the buttons.

    Without them a page whose script did not run would have two dead arrows
    on every card. One move per press is worse than many, and much better
    than none.
    """
    page = _markup("_favourites.html")

    assert 'formaction="/projects/arrange"' in page
    assert "this.form.by.value" in page


def test_cancel_puts_the_cards_back():
    """Otherwise Cancel is Save with extra steps."""
    page = _markup("_favourites.html")

    assert "original.forEach" in page


def test_a_reorder_cannot_add_lose_or_exceed():
    """A form left open in another tab is exactly how a rearrangement would
    otherwise turn into something else."""
    import tempfile
    from unittest.mock import patch

    from aki_agent import paths as paths_module

    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(paths_module, "home", lambda: Path(tmp)):
            paths_module.ensure_app_dirs()
            for key in "abcd":
                favourites.pin(key)

            favourites.set_order(["z", "a"])

            assert sorted(favourites.read_pins()) == ["a", "b", "c", "d"]
            assert favourites.read_pins()[0] == "a"


def test_a_pin_with_no_project_is_named_rather_than_silent():
    """A pin with no project is named rather than silent.

    Five cards, six pins, and the sixth pointing at a folder he had renamed
    in Explorer. The `+` was correctly hidden at the cap; the page just never
    said why, which reads as a broken button.

    Keeping the pin is deliberate -- a cloud drive that has not mounted must
    not cost somebody their row -- so the answer is to say it, not to drop
    it.
    """
    page = _markup("_favourites.html")

    assert "favourites_lost" in page
    assert "Forget" in page

    class _Item:
        def __init__(self, key):
            self.key = key

    class _Space:
        items = [_Item("a")]

    import tempfile
    from unittest.mock import patch

    from aki_agent import paths as paths_module

    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(paths_module, "home", lambda: Path(tmp)):
            paths_module.ensure_app_dirs()
            favourites.pin("a")
            favourites.pin("gone/away")

            assert favourites.missing_pins(_Space()) == ["gone/away"]


# ---------------------------------------------------------------------------
# 5. The queue pills read on both grounds
# ---------------------------------------------------------------------------

def test_the_pills_are_filled_rather_than_outlined():
    css = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    block = css[css.index("button.pilltab {"):]
    block = block[:block.index("}")]

    assert "background: var(--raised)" in block
    assert "color: var(--fg)" in block
    assert "background: transparent" not in block


def test_a_pill_with_something_behind_it_says_so():
    """Three identical pills say nothing about which of them wants you."""
    css = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    page = _markup("_columns.html")

    assert "button.pilltab.waiting {" in css
    assert "' waiting' if rows" in page
