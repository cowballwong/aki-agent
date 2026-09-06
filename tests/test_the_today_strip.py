"""What the strip at the top of Today claims, and what it can actually know.

Three reports from the maintainer on 2026-09-04, and all three are the same mistake in
different places: the page showing a number it had not earned.

  1.
     The button filled a box and said "now save" in small grey text beside
     itself. It looked like an action. It was not one.

  2.
     "idle" meant "no scheduled tasks are installed" -- a fact about the
     machine's task scheduler, printed beside a clock where it read as a
     statement about whether the assistant was doing anything.

  3.
     The five-hour ring drew this stretch against the busiest stretch of the
     week. A real ratio, and a terrible ring: it fills faster in a quiet
     week, shrinks for days after one heavy session, and sits beside a ring
     that means "of your weekly allowance".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aki_agent import today as today_module

TEMPLATES = (Path(__file__).resolve().parents[1] / "src" / "aki_agent"
             / "dashboard" / "templates")


@pytest.fixture(scope="module")
def page() -> str:
    return (TEMPLATES / "today.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def settings_page() -> str:
    return (TEMPLATES / "settings.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. The location button saves
# ---------------------------------------------------------------------------

def test_using_my_location_saves_rather_than_filling_a_box(settings_page):
    assert "form.submit()" in settings_page, (
        "the button has to save; filling a field and hoping the person "
        "presses Save is what lost his location")


def test_there_is_a_visible_choice_between_a_town_and_here(settings_page):
    assert 'name="location_mode"' in settings_page
    assert 'value="town"' in settings_page and 'value="here"' in settings_page


def test_the_mode_is_read_off_the_value_not_stored_separately():
    """Numbers can only have come from the browser; words were typed.

    A stored mode would be a second key to keep in step with a value that
    already says which it is.
    """
    assert today_module.coordinates("51.7520, -0.3360") is not None
    assert today_module.coordinates("Winchester") is None


def test_a_town_name_still_wins_when_that_is_what_was_chosen(tmp_path):
    """A town name still wins when that is what was chosen."""
    from aki_agent.config import Config
    from aki_agent.dashboard import settings as settings_module

    config = Config()
    config.user.location = "51.7520, -0.3360"
    updated, problems = settings_module.apply_form(config, {
        "location_mode": "town",
        "user_location": "Winchester",
        "user_here": "51.7520, -0.3360",
    })

    assert updated.user.location == "Winchester", problems


def test_a_failed_lookup_does_not_wipe_a_working_location():
    """The browser refusing must not cost somebody the town they had."""
    from aki_agent.config import Config
    from aki_agent.dashboard import settings as settings_module

    config = Config()
    config.user.location = "Winchester"
    updated, problems = settings_module.apply_form(config, {
        "location_mode": "here",
        "user_here": "",
    })

    assert updated.user.location == "Winchester"


# ---------------------------------------------------------------------------
# 2. The idle indicator is gone
# ---------------------------------------------------------------------------

def test_the_strip_no_longer_says_idle(page):
    """Read the markup, not the comment that explains its removal.

    The comment left in its place quotes the thing that was removed, so a
    plain substring check finds the words it is checking are gone. Same trap
    as the phone-layout tests, hit twice in one evening.
    """
    markup = re.sub(r"\{#.*?#\}", "", page, flags=re.S)

    assert "scheduled task(s)" not in markup
    assert 'class="server' not in markup


# ---------------------------------------------------------------------------
# 3. The five-hour and weekly rings are gone
#
# They were rebuilt to measure an allowance, and then removed the same
# evening.
#
# Three denominators were tried and each was worse than the blank:
#   - the busiest five hours of his own week: fills faster in a quiet week;
#   - a figure he types: he has no way to know it, and said so;
#   - the point where the service actually refused a request: measured at
#     369M, and the next window reached 458M without a refusal.
# ---------------------------------------------------------------------------

def test_the_two_rings_that_could_not_be_filled_are_gone(page):
    import re

    markup = re.sub(r"\{#.*?#\}", "", page, flags=re.S)

    assert "five_hour_fraction" not in markup
    assert "week_fraction" not in markup
    assert "Set your allowance" not in markup


def test_the_allowance_settings_went_with_them():
    """A settings card for a ring nobody draws reads as a broken feature."""
    settings = (TEMPLATES / "settings.html").read_text(encoding="utf-8")
    import re

    markup = re.sub(r"\{#.*?#\}", "", settings, flags=re.S)
    assert "weekly_token_limit" not in markup
    assert "five_hour_token_limit" not in markup


def test_the_totals_are_still_counted():
    """Only the rings went. The figures under the chart are still true."""
    usage = today_module.Usage(five_hours=1_000, week=9_000)

    assert usage.five_hours == 1_000
    assert usage.week == 9_000


# ---------------------------------------------------------------------------
# The refusal line, and why it is not here either
#
# For twenty minutes the strip carried a line read out of the transcripts --
# "You hit the five-hour limit today; it freed up at 15:00" -- because it is
# the one fact about the subscription that reaches this machine. The maintainer,
# 2026-09-04.
#
# The scanner that produced it went too. A scan that keeps running on every
# page load for a line nobody draws is the kind of cost that survives for
# years because nothing on screen points at it.
# ---------------------------------------------------------------------------

def test_the_refusal_line_and_its_scanner_are_both_gone():
    from pathlib import Path as _Path

    source = (_Path(__file__).resolve().parents[1] / "src" / "aki_agent"
              / "today.py").read_text(encoding="utf-8")

    assert "quotaLimits" not in source, (
        "the transcript scan was only ever there to feed a line that was "
        "removed; leaving it costs a walk of the new bytes on every load")
    assert not hasattr(today_module.Usage(), "limit_resets_at")


# ---------------------------------------------------------------------------
# The one ring that is left
#
# ---------------------------------------------------------------------------

def test_the_recycle_mark_is_the_number_the_recycler_actually_uses():
    """He said 200K. It is 180K, and the page must not quote his figure.

    A dashboard that draws the number somebody expected rather than the one
    the code uses is a dashboard that lies politely.
    """
    from aki_agent import guard

    assert guard.CONTEXT_LIMIT == 180_000
    usage = today_module.Usage(context=43_489, context_limit=200_000,
                               recycle_at=guard.CONTEXT_LIMIT)

    assert "136.5K to auto-recycle" == usage.recycle_note()


def test_the_mark_is_placed_against_the_window_not_the_threshold():
    """The notch and the fill have to share a scale or it points elsewhere."""
    usage = today_module.Usage(context=50_000, context_limit=200_000,
                               recycle_at=180_000)

    assert usage.recycle_fraction == pytest.approx(0.9)
    assert usage.context_fraction == pytest.approx(0.25)


def test_being_past_the_mark_is_a_state_rather_than_a_negative_countdown():
    """The recycle also needs an idle session and a gap since the last one,
    so sitting over the line is normal and lasts a while."""
    usage = today_module.Usage(context=190_000, context_limit=200_000,
                               recycle_at=180_000)

    assert usage.recycle_note() == "past the 180.0K recycle mark"


def test_nothing_is_drawn_when_the_window_is_unknown():
    usage = today_module.Usage(context=50_000, recycle_at=180_000)

    assert usage.context_fraction is None
    assert usage.recycle_fraction is None


def test_the_ring_reads_the_assistants_own_session_not_the_newest_on_the_machine():
    """The bug this fixed, and the reason the mark was needed to find it.

    `read_usage` walks every transcript on the computer, because that is what
    a usage total is. The context is a different question, and answering it
    from the machine-wide newest entry meant that on a machine running a
    second Claude Code session the ring showed that one. Measured on
    2026-09-04: 507K on the ring against 43K in the assistant's own session.
    """
    from pathlib import Path as _Path

    source = (_Path(__file__).resolve().parents[1] / "src" / "aki_agent"
              / "today.py").read_text(encoding="utf-8")

    assert "guard.context_size()" in source
    assert "page.usage.recycle_at = guard.CONTEXT_LIMIT" in source


def test_no_ring_element_paints_a_disc():
    """No ring element paints a disc.

    An SVG <circle> defaults to `fill: black`. The recycle mark was added as
    a circle and left out of the rule that sets `fill: none`, so it painted a
    black disc across the inside of the ring: invisible on the dark ground,
    and a black coin with the percentage on it in day mode. The stroke
    colours were never the problem.
    """
    css = (TEMPLATES / "base.html").read_text(encoding="utf-8")

    assert ".gauge .track, .gauge .fill, .gauge .mark {" in css, (
        "every circle in the gauge must be in the fill:none rule")


def test_the_gauge_track_is_visible_on_both_grounds():
    """It was 16% of the accent, which on a cream page is very nearly the
    page -- so the meter lost its track and became a floating arc."""
    css = (TEMPLATES / "base.html").read_text(encoding="utf-8")

    assert "var(--fg) 26%" in css, (
        "the track must be mixed from the foreground, which is defined per "
        "ground, rather than from the accent")


def test_the_strip_is_three_equal_columns():
    """the maintainer drew it on a screenshot, 2026-09-04: three circles across the
    strip, the middle one EMPTY, with.

    The empty circle was the whole message. The clock and the weather were
    crowded into the left, the ring was pinned to the right, and a third of
    the strip did nothing. Equal columns rather than content-sized ones, so
    the three keep the same rhythm at every width instead of shuffling as
    the weather text changes length.
    """
    css = (TEMPLATES / "base.html").read_text(encoding="utf-8")

    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in css
    assert ".todaybar .clock { margin: 0; text-align: left; justify-self: start; }" in css
    assert "justify-self: center;" in css
    assert "justify-self: end;" in css


def test_a_phone_falls_back_to_two_columns():
    """Three do not fit on a phone, and the date is what decides it.

    At 560px each of three columns is about 160 wide; the date under the
    clock alone measures 176. Below that the clock and the weather stack down
    the left with the ring spanning both rows on the right -- beside them,
    not on a band of its own, which was the shape the maintainer called "so bad
    placing".
    """
    css = (TEMPLATES / "base.html").read_text(encoding="utf-8")

    assert "@media (max-width: 560px) {" in css
    phone = css[css.index("@media (max-width: 560px) {"):]
    assert ".todaybar .gauges { grid-column: 2; grid-row: 1 / span 2; }" in phone
