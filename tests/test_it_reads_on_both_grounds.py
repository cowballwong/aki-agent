"""Colours have to survive the ground they are on.

Measured
with the light ground forced, nine controls were under 4.5:1. The two worst
had the same shape:

  * `--pale` is the primary button's fill. It flips to a dark brown on the
    light grounds -- correct -- while the text stayed hardcoded near-black.
    **The fill flipped and the text did not**: 1.47:1.
  * The semantic colours (`--critical` and friends) were defined once, for
    the dark ground only, so the Stop button used a red chosen to glow on
    near-black and sat at 2.56:1 on near-white.

Neither was a wrong colour. Both were a colour defined in one place and used
in two. That is what these tests look for.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aki_agent import themes

BASE = (Path(__file__).resolve().parents[1] / "src" / "aki_agent"
        / "dashboard" / "templates" / "base.html")

# The blocks that each define a complete palette for one ground.
GROUND_BLOCKS = (":root {", ":root.light {", "@media (prefers-color-scheme")


def _blocks() -> dict[str, str]:
    """Each palette block in base.html, by its selector."""
    text = BASE.read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for match in re.finditer(r"(:root[^\{]*)\{([^}]*)\}", text):
        selector = match.group(1).strip()
        if "--pale" in match.group(2) or "--critical" in match.group(2):
            found[selector] = match.group(2)
    return found


def test_every_ground_that_sets_a_fill_sets_its_text():
    """`--pale` and `--on-pale` are one decision, not two."""
    for selector, body in _blocks().items():
        if "--pale:" not in body:
            continue
        assert "--on-pale:" in body, (
            f"{selector} defines --pale without --on-pale — the fill can flip "
            "with the theme while the text stays behind")


def test_the_primary_button_takes_its_text_from_its_fill():
    text = BASE.read_text(encoding="utf-8")
    rule = re.search(r"button\.primary[^{]*\{([^}]*)\}", text)
    assert rule, "no primary button rule"
    body = rule.group(1)
    assert "var(--on-pale)" in body or "var(--on-accent)" in body, (
        "the primary button's text is hardcoded; it has to follow the fill")
    assert not re.search(r"color:\s*#[0-9a-fA-F]{3,6}", body), (
        "a hex text colour here is a guess about which ground it lands on")


def test_only_one_rule_claims_the_primary_button():
    """Two rules with the same name is a coin toss decided by line order.

    A duplicate `button.primary` was added on 2026-08-22 and never applied,
    because an older one sat further down the sheet. The same collision put
    the quiet-mode cards in a flex row the same afternoon.
    """
    text = BASE.read_text(encoding="utf-8")
    starts = re.findall(r"^button\.primary[^:\n]*\{", text, re.M)
    assert len(starts) == 1, (
        f"{len(starts)} rules define button.primary — merge them")


@pytest.mark.parametrize("token", ["--critical", "--good", "--warning",
                                   "--error"])
def test_a_semantic_colour_is_defined_for_every_ground(token):
    """One definition for two grounds is one of them being wrong."""
    blocks = _blocks()
    defines = [s for s, body in blocks.items() if f"{token}:" in body]
    assert len(defines) >= 2, (
        f"{token} is only defined in {defines} — a colour picked for one "
        "ground does not read on the other")


# ---------------------------------------------------------------------------
# The computed half
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("theme", themes.THEMES, ids=lambda t: t.key)
def test_every_theme_can_be_written_on(theme):
    """A filled accent needs text that reads on it.

    Written as a computation rather than a constant because the constant was
    wrong: "every theme's accent is a mid tone, so white reads on all five"
    is a sentence I wrote, and four of the five want dark text.
    """
    ratio = themes.contrast(theme.accent, theme.on_accent)
    assert ratio >= 4.5, (
        f"{theme.name}: {theme.on_accent} on {theme.accent} is {ratio:.2f}:1")


def test_contrast_is_symmetric_and_bounded():
    assert themes.contrast("#ffffff", "#000000") == pytest.approx(21, abs=0.1)
    assert themes.contrast("#000000", "#ffffff") == pytest.approx(21, abs=0.1)
    assert themes.contrast("#777777", "#777777") == pytest.approx(1, abs=0.01)


def test_an_unreadable_colour_is_rejected_not_rounded():
    """The helper must not quietly answer "close enough"."""
    assert themes.contrast("#8A6F4E", "#8A6F4E") < 4.5
