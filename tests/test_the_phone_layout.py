"""What the dashboard looks like on a phone, and the CSS traps it fell into.


On a wide screen the rail and the chat panel are columns beside the content and
cost nothing. On a phone they are not columns — the narrow-screen rules put
them into the flow — so the rail became a block of twenty links on top of every
page and the content started below the fold. Reading anything meant scrolling
past the menu, every time.

THE SECOND HALF OF THAT, FOUND 2026-09-04
------------------------------------------
Hiding it was only half a fix. `.rail` was still `position: static` inside the
narrow-screen block, so *opening* the menu put all twenty links back into the
document above the page.

So the contract these tests hold is no longer "hidden, then shown". It is: on a
phone the rail never rejoins the document. It stays the fixed vertical column
it is on a desktop and slides in *over* the page, which is why
`position: static` is now the thing asserted against rather than for.

THE TRAP THE FIRST HALF OF THIS FILE EXISTS TO CATCH AGAIN
-----------------------------------------------------------
A media query adds no specificity. A base rule written *after* one therefore
beats the rule inside it, purely by being later. The first version of the menu
button put `.railbtn { display: none }` at the end of the stylesheet, so the
`display: inline-flex` inside `@media (max-width: 980px)` never won and the
button was invisible on a phone — the one screen it exists for.

base.html already carries a comment about exactly this ("Order decides"),
written after the same mistake with the Today page. Making it twice is what
turns a comment into a test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BASE = (Path(__file__).resolve().parents[1] / "src" / "aki_agent"
        / "dashboard" / "templates" / "base.html")
PHONE = "@media (max-width: 980px) {"


@pytest.fixture(scope="module")
def css() -> str:
    return BASE.read_text(encoding="utf-8")


def _declarations_only(text: str) -> str:
    """The same stylesheet with its prose taken out.

    Every "this must NOT appear" assertion below has to read declarations
    rather than the file, because the comments explain the very mistakes
    being guarded against and name them in full. Both such tests failed on
    their first run against their own explanation of why they exist.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)     # CSS
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)     # Jinja
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)     # JS


def _phone_block(css: str) -> str:
    start = css.index(PHONE)
    depth = 0
    for i in range(start, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[start:i + 1]
    raise AssertionError("the narrow-screen block is not closed")


# ---------------------------------------------------------------------------
# Order decides
# ---------------------------------------------------------------------------

def test_the_menu_buttons_base_rule_comes_before_the_phone_rules(css):
    """The whole bug, in one assertion.

    If `.railbtn {` moves below the media query again, the button disappears on
    phones and nothing else looks wrong.
    """
    base_rule = css.index(".railbtn {")
    phone_rules = css.index(PHONE)
    assert base_rule < phone_rules, (
        ".railbtn's base rule must come before the narrow-screen block, or "
        "display:none wins by being later and the menu button vanishes on a "
        "phone")


# ---------------------------------------------------------------------------
# A panel over the page, never a block in it
# ---------------------------------------------------------------------------

def test_the_rail_never_rejoins_the_page_on_a_phone(css):
    """The 2026-09-04 bug, pinned.

    `position: static` is what made the open menu shove the page down instead
    of floating over it. It is one word, it looks harmless, and it was there
    for a week.
    """
    block = _declarations_only(_phone_block(css))
    assert "position: static" not in block, (
        "the rail must stay out of the document flow on a phone -- static is "
        "what pushed the page below the menu")
    assert "position: fixed" in block


def test_the_rail_is_folded_away_on_a_phone(css):
    """Slid out of view AND taken out of the tab order.

    Offscreen alone is not folded: a panel at translateX(-101%) still catches
    Tab and hands focus to links nobody can see.
    """
    block = _phone_block(css)
    assert "transform: translateX(-101%); visibility: hidden;" in block


def test_the_rail_can_be_brought_back(css):
    """Folded, not removed."""
    block = _phone_block(css)
    assert "transform: none; visibility: visible;" in block


def test_the_menu_button_appears_on_a_phone(css):
    assert ".railbtn { display: inline-flex; }" in _phone_block(css)


def test_the_button_is_in_the_top_bar(css):
    assert 'class="railbtn" onclick="foldRail()"' in css


# ---------------------------------------------------------------------------
# Getting out of it again
# ---------------------------------------------------------------------------

def test_there_is_something_to_press_beside_the_panel(css):
    """The scrim is the close button.

    The panel has no × of its own, deliberately -- tapping beside a drawer is
    the gesture everybody already has. That only holds while the scrim is
    actually there and actually closes it.
    """
    assert 'class="railscrim" onclick="foldRail(false)"' in css
    assert ".rail-open .railscrim { opacity: 1; pointer-events: auto; }" in css


def test_escape_closes_it(css):
    assert "if (e.key === 'Escape') { foldRail(false); }" in css


def test_close_only_means_close(css):
    """`foldRail(false)` must not be able to toggle the drawer back open.

    The scrim and Escape both only ever want to close. Bound to a plain
    toggle, pressing Escape on an already-closed page opens the menu.
    """
    assert "function foldRail(want)" in css
    assert "(want === undefined)" in css


def test_the_drawer_does_not_reopen_itself_on_the_next_page(css):
    """The opposite of what this file used to assert, on purpose.

    While the rail was part of the page, remembering "left it open" was a
    reasonable thing to store, and `pa-rail-open` did. As a panel that floats
    over the content, restoring it open means every page load starts under a
    menu the reader has to dismiss before they can read anything.

    So the stored value is gone, and its absence is the thing pinned here --
    otherwise it comes back as a helpful-looking three-line patch.
    """
    assert "pa-rail-open" not in _declarations_only(css)


# ---------------------------------------------------------------------------
# Order decides, for the third time
# ---------------------------------------------------------------------------

def test_the_pill_rows_phone_rules_come_after_its_base_rules(css):
    """The same trap as the menu button, hit again on 2026-09-04.

    A media query adds no specificity. The phone overrides for the queue bar
    were written with the rest of the bar's positioning, two hundred lines
    above the plain `button.pilltab` rule -- so every line of them lost, and
    the three pills went on wrapping onto two rows at the one width where
    vertical space is scarcest. Measured as needing 389px of 357 both before
    and after the "fix", which is what said the rule was not applying at all.
    """
    base = css.index("button.pilltab {")
    phone = css.index("@media (max-width: 560px) {\n  .pilltabs {")

    assert phone > base, (
        "the phone overrides for the pills must come after their base rule, "
        "or they lose to it by being earlier")


def test_there_is_only_one_narrow_screen_block(css):
    """`_phone_block` reads the FIRST `@media (max-width: 980px)` in the file.

    A second one, added above it for the queue bar, made four of the tests in
    this file inspect the wrong twelve lines and fail for a reason that had
    nothing to do with the rail.
    """
    assert css.count(PHONE) == 1, (
        "keep the narrow-screen rules in one block; the helper in this file "
        "reads the first one")
