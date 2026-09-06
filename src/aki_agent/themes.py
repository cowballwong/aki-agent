"""The colour schemes, and the one value the whole dashboard is built from.

WHY THERE IS ONLY ONE COLOUR IN A THEME
---------------------------------------
`config.Assistant` already carries a single accent, and every surface in the
dashboard is derived from it with `color-mix`. That was a deliberate decision
before this file existed: one value to choose and no way to produce a clash.

A theme here is therefore not a palette of twelve hex codes. It is **an accent
and a ground** -- light or dark -- and a name somebody can recognise. Anything
more would let a person build something unreadable, and the first thing they
would do with an unreadable dashboard is stop opening it.

WHY THEY HAVE NAMES AND NOT NUMBERS
-----------------------------------
"Slate" is something you can say you prefer. "#4E5D6C" is not. The names are
also the only thing that survives translation: a person running the assistant
in Chinese still sees a swatch, and the swatch is the real interface.

ONE OF THEM IS THE DEFAULT AND IT IS NOT AN ACCIDENT
----------------------------------------------------
Terracotta, warm and low-contrast, because the dashboard is a thing somebody
glances at forty times a day and a saturated interface is exhausting on the
fortieth. The bright ones are offered, not chosen.
"""

from __future__ import annotations

from dataclasses import dataclass


# Font stacks. Named once so a theme reads as a set of decisions rather than
# a wall of quoted family names.
#
# ALL SYSTEM FONTS, AND THAT IS THE DECISION. A dashboard that fetches a
# webfont looks wrong on a train, on a plane, and on the first run before
# anything is set up -- and this package's whole promise is that it works
# without an account or a connection. Five faces already installed on every
# Windows and macOS machine give five genuinely different pages.
SANS = '-apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif'
SERIF = 'Georgia, "Iowan Old Style", "Palatino Linotype", "Times New Roman", serif'
MONO = ('ui-monospace, "SF Mono", "Cascadia Mono", Consolas, '
        '"DejaVu Sans Mono", monospace')
GROTESK = ('"Segoe UI Variable Display", "Segoe UI", Inter, '
           '"Helvetica Neue", Arial, sans-serif')


@dataclass(frozen=True)
class Theme:
    """A whole look, not a colour.

    That was right -- seven entries that differed only
    in one hex value is a colour picker wearing the word "theme".

    So a theme now carries the four things that actually change how a page
    feels: its colour, its ground, its typography, and how solid it is --
    corners, shadow, and the weight of a rule.
    """

    key: str
    name: str
    accent: str
    # `dark` or `light`. The stylesheet reads this to decide the ground;
    # everything else is mixed from the accent.
    ground: str
    why: str = ""

    # --- typography --------------------------------------------------------
    display: str = SANS          # headings
    sans: str = SANS             # body
    mono: str = MONO             # numbers, labels, code
    body_size: str = "13px"
    body_leading: str = "1.55"
    label_spacing: str = "0.09em"   # the uppercase micro-labels

    # --- how solid it feels ------------------------------------------------
    radius: str = "6px"
    radius_sm: str = "4px"
    shadow: str = "0 1px 2px rgba(0,0,0,.18), 0 6px 18px rgba(0,0,0,.14)"
    border_weight: str = "1px"

    @property
    def on_accent(self) -> str:
        """What to write on top of a filled accent. See `on_accent()`."""
        return on_accent(self.accent)

    def sample(self) -> str:
        """One line describing the feel, for the picker."""
        face = ("serif" if "Georgia" in self.display
                else "mono" if "mono" in self.display.lower()
                else "sans")
        size = int(self.radius.rstrip("px") or 0)
        # 2px is square to the eye; the first version called it "rounded",
        # which described the number rather than the page.
        corners = "square" if size <= 2 else "soft" if size >= 8 else "rounded"
        depth = "flat" if self.shadow == "none" else "raised"
        return f"{face} · {corners} · {depth}"


THEMES = (
    Theme(
        "terracotta", "Terracotta", "#C4763C", "dark",
        "Warm and quiet, with serif headings. The default, because this is a "
        "page you glance at forty times a day and a loud one is tiring by the "
        "fortieth.",
        display=SERIF, sans=SANS, mono=MONO,
        body_leading="1.6", radius="6px", radius_sm="4px",
        shadow="0 1px 2px rgba(0,0,0,.18), 0 6px 18px rgba(0,0,0,.14)"),

    Theme(
        "blueprint", "Blueprint", "#6B87A6", "dark",
        "Everything in monospace, square corners, hairline rules and no "
        "shadows. Reads like a drawing sheet rather than a website — the one "
        "to pick if the rest of your day is spent in CAD.",
        display=MONO, sans=MONO, mono=MONO,
        body_size="12.5px", body_leading="1.5", label_spacing="0.12em",
        radius="0", radius_sm="0", shadow="none", border_weight="1px"),

    Theme(
        "paper", "Paper", "#8A6F4E", "light",
        "A printed page: light ground, serif throughout, wide leading, thin "
        "rules and no shadows at all. The one for a bright room, and the "
        "easiest of the five to read for a long stretch.",
        display=SERIF, sans=SERIF, mono=MONO,
        body_size="14px", body_leading="1.7", label_spacing="0.06em",
        radius="2px", radius_sm="2px", shadow="none"),

    Theme(
        "slate", "Slate", "#7C8B9A", "dark",
        "The undecorated one. Plain system sans, soft corners, barely any "
        "shadow. Nothing about it asks for attention, which is the point.",
        display=GROTESK, sans=SANS, mono=MONO,
        body_leading="1.55", radius="10px", radius_sm="7px",
        shadow="0 1px 2px rgba(0,0,0,.12)"),

    Theme(
        "ink", "Ink", "#1F4F82", "light",
        "High contrast on white, heavier type, square corners and firm rules. "
        "Built for a bright room or tired eyes — the most legible of the "
        "five, and the least soft.",
        display=GROTESK, sans=SANS, mono=MONO,
        body_size="13.5px", body_leading="1.6", label_spacing="0.08em",
        radius="0", radius_sm="0", shadow="none", border_weight="1.5px"),
)


# Themes that existed before 2026-08-21, pointed at their nearest survivor.
# A config naming one of these must keep opening the dashboard; changing the
# list is not a reason to break somebody's saved choice.
RETIRED = {
    "moss": "slate",
    "plum": "terracotta",
    "ember": "terracotta",
}


DEFAULT = THEMES[0]


def by_key(key: str) -> Theme:
    """A theme by name, falling back to the default rather than failing.

    A configuration naming a theme that no longer exists is a reason to show
    the default, never a reason for the dashboard not to load. Somebody whose
    page will not open cannot use the page to fix it.
    """
    wanted = (key or "").strip().lower()
    # A retired theme resolves to its nearest survivor rather than silently
    # becoming the default -- somebody who chose Moss gets the quiet grey one,
    # not the warm one they were avoiding.
    wanted = RETIRED.get(wanted, wanted)
    for theme in THEMES:
        if theme.key == wanted:
            return theme
    return DEFAULT


def _relative_luminance(hex_colour: str) -> float:
    """WCAG relative luminance of a #rrggbb colour, 0 (black) to 1 (white)."""
    value = (hex_colour or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return 0.5                       # unknown: assume the awkward middle
    channels = []
    for start in (0, 2, 4):
        part = int(value[start:start + 2], 16) / 255
        channels.append(part / 12.92 if part <= 0.03928
                        else ((part + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(one: str, two: str) -> float:
    """Contrast ratio between two hex colours, 1 to 21."""
    first, second = sorted(
        (_relative_luminance(one), _relative_luminance(two)), reverse=True)
    return (first + 0.05) / (second + 0.05)


def on_accent(accent: str) -> str:
    """Text colour that can be read on this accent.

    Computed, because guessing was wrong. A filled button on the Paper theme
    measured 1.47:1 with white text -- unreadable, and stated in a comment as
    fine. Whichever of near-white and near-black contrasts more wins; there
    is no third option worth having on a coloured fill.
    """
    light, dark = "#ffffff", "#1b1613"
    return light if contrast(accent, light) >= contrast(accent, dark) else dark


def matching(accent: str) -> Theme | None:
    """Which theme an accent came from, if any.

    Used so the page can show which swatch is current. Returns None for a
    colour somebody set by hand, which is a legitimate state and must not be
    silently rounded to the nearest named theme.
    """
    wanted = (accent or "").strip().lower()
    for theme in THEMES:
        if theme.accent.lower() == wanted:
            return theme
    return None


def ground_for(accent: str) -> str:
    """Light or dark, for a given accent.

    A colour somebody typed in by hand is not a theme and gets the dark
    ground, which is the default the whole stylesheet was written against.
    Guessing lightness from the hex would be cleverer and would occasionally
    hand somebody a page they cannot read.
    """
    found = matching(accent)
    return found.ground if found else "dark"
