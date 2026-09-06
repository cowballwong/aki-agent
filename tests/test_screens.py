"""Every border must be square, in every language.

WHY THESE ARE WORTH HAVING
--------------------------
The maintainer asked for better screens in the install and upgrade flows, and sent a
post making the case: an ASCII diagram is textual *graphics*, and its meaning
lives in the two-dimensional relationships between characters. A frame that is
two columns out does not look slightly worse than a square one — it looks like
a broken program, which is a poor first impression for something whose entire
job is to be trusted with somebody's work.

So almost every test here is the same assertion: **is every rendered line
exactly `WIDTH` columns wide**, measured the way a terminal measures, not the
way `len()` does.
"""

from __future__ import annotations

import pytest

from aki_agent import screens


def square(rendered: str) -> list[str]:
    """Any line that is not exactly the frame width."""
    return [one for one in rendered.splitlines()
            if screens.width(one) != screens.WIDTH]


# ---------------------------------------------------------------------------
# Width
# ---------------------------------------------------------------------------

def test_chinese_counts_two_columns_per_character():
    """`len("廣東話")` is 3 and it occupies 6. Every frame in this module
    depends on the difference."""
    assert len("廣東話") == 3
    assert screens.width("廣東話") == 6


def test_mixed_scripts_add_up():
    assert screens.width("Aki 助手") == 4 + 4


def test_a_combining_mark_takes_no_column_of_its_own():
    assert screens.width("é") == 1


# ---------------------------------------------------------------------------
# The frames
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rendered", [
    screens.banner("Aki Agent", "0.8.1"),
    screens.banner("Aki Agent · 安裝", "0.8.1 — 大約 15 分鐘"),
    screens.steps([("語言", "done"), ("你叫咩名", "now"), ("工作", "todo")]),
    screens.steps([("Language", "done"), ("You", "now")], title="Progress"),
    screens.menu("What do you call one piece of work?",
                 ["project", "case", "client", "none of these"]),
    screens.menu("你會點稱呼一件工作?",
                 ["專案", "個案", "客戶", "以上都唔啱 —— 我自己講"],
                 footer="回一個數字"),
    screens.flow(["read the release", "build engine.new", "swap it in"]),
    screens.flow(["解壓", "抄去 engine.new", "換入去"], title="升級"),
    screens.outcome(True, "裝好喇", "你可以刪咗解壓出嚟嗰個 folder。"),
    screens.outcome(False, "could not swap the new engine into place",
                    "The engine you had is still in place. Re-running this "
                    "is safe."),
])
def test_every_line_is_exactly_the_frame_width(rendered):
    assert not square(rendered), rendered


def test_a_label_too_long_for_its_frame_is_truncated_not_overflowed():
    rendered = screens.banner("x" * 200)
    assert not square(rendered)
    assert screens.MARKER in rendered


def test_a_chinese_label_too_long_is_also_contained():
    rendered = screens.banner("字" * 200)
    assert not square(rendered)


def test_an_empty_menu_option_list_still_renders_squarely():
    assert not square(screens.menu("Anything?", []))


def test_a_single_stage_flow_has_no_arrows():
    rendered = screens.flow(["one thing"])
    assert "v" not in rendered.replace("|", "")
    assert not square(rendered)


def test_the_arrow_sits_under_the_box_it_comes_from():
    """The relationship the whole module exists to preserve: an arrow that
    does not line up with its box is not a diagram, it is decoration."""
    rendered = screens.flow(["first", "second"])
    lines = rendered.splitlines()

    arrows = [one for one in lines if one.strip("| ").strip() == "v"]
    assert len(arrows) == 1

    stem = arrows[0].index("v")
    # A stage's own border: an inner `+---+` sitting inside the outer frame,
    # which starts and ends with `|`.
    top = next(one for one in lines
               if one.startswith("|") and "+-" in one and one.endswith("|"))
    left, right = top.index("+"), top.rindex("+")
    assert left < stem < right, "the arrow must fall inside the box above it"


# ---------------------------------------------------------------------------
# Menus
# ---------------------------------------------------------------------------

def test_options_are_numbered_from_one():
    rendered = screens.menu("Pick", ["alpha", "beta", "gamma"])
    for number, word in enumerate(["alpha", "beta", "gamma"], 1):
        assert f" {number}   {word}" in rendered


def test_the_footer_says_how_to_answer():
    assert "reply with a number" in screens.menu("Pick", ["a", "b"])
    assert "回一個數字" in screens.menu("揀", ["a", "b"], footer="回一個數字")


# ---------------------------------------------------------------------------
# Wrapping
# ---------------------------------------------------------------------------

def test_a_long_sentence_wraps_rather_than_being_cut_off():
    """`outcome` used to truncate, and ended a failure message with
    "Re-running this is sa…" — cutting off the reassurance that was the only
    reason to print the sentence."""
    rendered = screens.outcome(
        False, "it did not work",
        "The engine you had is still in place. Re-running this is safe.")
    assert "safe." in rendered
    assert not square(rendered)


def test_chinese_wraps_even_with_no_spaces_to_break_on():
    lines = screens.wrap("字" * 80, 40)
    assert len(lines) > 1
    assert all(screens.width(one) <= 40 for one in lines)
    assert "".join(lines) == "字" * 80


def test_wrapping_keeps_every_word():
    text = "one two three four five six seven eight nine ten"
    assert " ".join(screens.wrap(text, 12)).split() == text.split()


# ---------------------------------------------------------------------------
# The command the skills call
# ---------------------------------------------------------------------------

def test_the_skills_can_draw_a_menu_without_composing_it(capsys):
    from aki_agent import cli

    code = cli.main(["screen", "menu", "--title", "揀邊個?",
                     "--option", "專案", "--option", "個案"])

    assert code == 0
    printed = capsys.readouterr().out
    assert not square(printed.strip())
    assert "專案" in printed


def test_a_menu_with_no_options_is_refused(capsys):
    from aki_agent import cli

    assert cli.main(["screen", "menu", "--title", "?"]) == 1
    assert "dead end" in capsys.readouterr().out


def test_steps_states_come_through_the_command(capsys):
    from aki_agent import cli

    cli.main(["screen", "steps", "--item", "語言:done", "--item", "工作:now"])
    printed = capsys.readouterr().out

    assert screens.DONE in printed and screens.NOW in printed
    assert not square(printed.strip())


def test_a_failed_outcome_is_drawn_differently_from_a_good_one(capsys):
    from aki_agent import cli

    cli.main(["screen", "outcome", "--title", "done"])
    good = capsys.readouterr().out
    cli.main(["screen", "outcome", "--title", "done", "--failed"])
    bad = capsys.readouterr().out

    assert good != bad
    assert screens.DONE not in bad


# ---------------------------------------------------------------------------
# Ambiguous width — the bug found by looking at a picture, not at a test
# ---------------------------------------------------------------------------

def test_characters_whose_width_depends_on_the_font_are_removed():
    """Middle dot, em dash, ellipsis and friends are East-Asian *Ambiguous*:
    one column in a Western terminal, two under a CJK font. Two attempts to
    guess which both produced visibly crooked borders. They are normalised
    away instead, so the question is never asked."""
    assert screens.safe("以上都唔啱 —— 我自己講") == "以上都唔啱 -- 我自己講"
    assert screens.safe("Aki · 安裝") == "Aki - 安裝"
    assert "…" not in screens.safe("等等…")


def test_no_frame_ever_contains_an_ambiguous_character():
    """The property that makes these render identically in every terminal."""
    import unicodedata

    rendered = chr(10).join([
        screens.banner("Aki Agent · 安裝", "0.8.2 — 大約 15 分鐘"),
        screens.menu("你會點稱呼一件工作?",
                     ["專案 · project", "以上都唔啱 —— 我自己講"]),
        screens.steps([("語言 · 廣東話", "done")]),
        screens.outcome(True, "裝好喇 —— 可以刪咗個 folder…"),
        screens.flow(["解壓 · unpack", "換入去"]),
        screens.banner("x" * 200),
    ])

    stray = sorted({char for char in rendered
                    if unicodedata.east_asian_width(char) == "A"})
    assert not stray, f"ambiguous characters reached a frame: {stray}"


def test_the_option_line_that_started_this_lines_up():
    rendered = screens.menu("你會點稱呼一件工作?",
                            ["專案 project", "個案 case", "客戶 client",
                             "以上都唔啱 —— 我自己講"])
    assert not square(rendered)
