"""The frames the install, upgrade, adoption and uninstall flows draw.

WHY THIS IS CODE AND NOT A FORMAT IN THE SKILL FILE (reported 2026-08-20)
-----------------------------------------------------------------------
He asked for better screens in these flows, and sent along a post making the
argument for him: an ASCII diagram is not text, it is *textual graphics*. Its
meaning lives in the two-dimensional relationships between characters -- which
box lines up under which, where an arrow starts and lands -- and a language
model handles a token sequence, with no guarantee at all that the geometry
survives. Delete two spaces from `| Head |------>| Tail |` and nothing much
happened to the sentence; the drawing is destroyed.

That is the whole design decision here. **The model must not draw these
frames. It calls something that draws them.** A skill file saying "print a
nice box around it" produces a different, subtly misaligned box every run --
and misaligned is worse than plain, because it reads as a broken program.

WIDTH IS THE PART THAT ACTUALLY BITES
-------------------------------------
This interview runs in whatever language the user answered question 1 in, and
for most of the people it was written for that is Chinese. `len("廣東話")` is
3; it occupies **6 columns**. Pad a frame by character count and every line
with CJK in it hangs six columns past the border -- which is precisely the
failure above, arrived at from the other direction.

So `width()` measures East Asian display width, and every frame is built from
it. Mixed English and Chinese on one line is the normal case here, not an edge
case.

PURE ASCII, DELIBERATELY
------------------------
`+`, `-`, `|` rather than the box-drawing block. Box-drawing characters are
East-Asian *Ambiguous*: one column in a Western terminal, two in a terminal
running a CJK locale. A frame that is square on the author's machine and
ragged on the student's is the exact defect this module exists to prevent, and
the reference the maintainer sent draws in ASCII for the same reason.
"""

from __future__ import annotations

import unicodedata

# Wide enough for a sentence, narrow enough to survive a default terminal and
# a phone screenshot of one -- which is how most of these get looked at.
WIDTH = 64


def width(text: str) -> int:
    """Display columns, not characters.

    'W' (wide) and 'F' (fullwidth) take two columns; everything else takes
    one. Ambiguous characters never reach here — `safe()` has replaced them
    before any content enters a frame. See the note on that function; it is
    the whole reason this can be a four-line function that is actually right.
    """
    return sum(
        2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        for char in text if not unicodedata.combining(char))


# The characters whose width cannot be decided from the string, and what they
# become. Middle dot, both dashes, the ellipsis, curly quotes: East Asian
# *Ambiguous* — one column in a Western terminal, two under a CJK font, and
# there is no third option that is right in both.
#
# TWO ATTEMPTS AT GUESSING, BOTH WRONG (2026-08-20)
# -------------------------------------------------
# First they were counted as one: correct in a Western terminal, and the
# option line `以上都唔啱 —— 我自己講` came out a column short of its border
# when rendered in a CJK face. Then they were counted as two whenever the line
# held any wide character — which broke the *same line* in MS Gothic, where
# the em dash is drawn narrow. The border moved the other way.
#
# The lesson is not that the heuristic needed more cases. It is that the
# question is undecidable from the string: the answer lives in the font the
# reader happens to have. So the characters are removed instead, and the
# question stops being asked. The frames lose a typographic nicety and gain
# the property they exist for.
AMBIGUOUS = {
    "·": "-", "—": "-", "–": "-", "…": "...",
    "“": '"', "”": '"', "‘": "'", "’": "'",
    "×": "x", "→": "->", "←": "<-", "✓": "v", "✗": "x",
}


def safe(text: str) -> str:
    """Strip characters whose column count depends on the reader's font."""
    for char, plain in AMBIGUOUS.items():
        if char in text:
            text = text.replace(char, plain)
    return text


MARKER = "..."


def pad(text: str, columns: int) -> str:
    """Pad to a column count. Truncates rather than overflowing a frame.

    Content is normalised on the way in (see `safe`), and the truncation
    marker is plain ASCII, so no character in the result has a width that
    depends on the reader's font.
    """
    text = safe(text)
    if width(text) <= columns:
        return text + " " * (columns - width(text))
    if columns <= 0:
        return ""

    kept = ""
    for char in text:
        if width(kept + char + MARKER) > columns:
            break
        kept += char

    out = kept + MARKER
    if width(out) > columns:                              # no room even for it
        return " " * columns
    return out + " " * (columns - width(out))


def centre(text: str, columns: int) -> str:
    """Centre by display columns. Used inside the little boxes in a flow."""
    text = safe(text)
    spare = columns - width(text)
    if spare <= 0:
        return pad(text, columns)
    left = spare // 2
    return " " * left + text + " " * (spare - left)


def wrap(text: str, columns: int) -> list[str]:
    """Break a sentence to fit, by display width.

    `pad` truncates, which is right for a label that must not push a border
    out and wrong for a sentence somebody has to read -- the first version of
    `outcome` ended a failure message with "Re-running this is sa…", cutting
    off the reassurance that was the entire point of printing it.

    Splits on spaces where there are any, and per-character where there are
    not, because Chinese has no spaces and a line of it must still break.
    """
    text = safe(text)
    if width(text) <= columns:
        return [text]

    lines: list[str] = []
    current = ""
    for word in (text.split(" ") if " " in text else list(text)):
        candidate = (current + " " + word) if (current and " " in text) else (
            current + word)
        if width(candidate) > columns and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def rule(label: str = "", char: str = "-", inner: int = WIDTH - 2) -> str:
    """A horizontal line, optionally with a label sitting in it."""
    if not label:
        return "+" + char * inner + "+"
    text = f" {safe(label)} "
    left = 2
    right = max(0, inner - left - width(text))
    return "+" + char * left + text + char * right + "+"


def line(text: str = "", inner: int = WIDTH - 2) -> str:
    return "| " + pad(text, inner - 2) + " |"


def box(lines: list[str], title: str = "", footer: str = "") -> str:
    """One framed block."""
    out = [rule(title)]
    out += [line(one) for one in lines]
    out.append(rule(footer))
    return "\n".join(out)


def banner(title: str, subtitle: str = "") -> str:
    """The header a flow opens with."""
    body = [title] + ([subtitle] if subtitle else [])
    return box(body)


# ---------------------------------------------------------------------------
# Progress through a flow
# ---------------------------------------------------------------------------

DONE = "[x]"
NOW = "[>]"
TODO = "[ ]"


def steps(items: list[tuple[str, str]], title: str = "") -> str:
    """Where we are in a multi-step flow.

    `items` is (label, state) where state is done / now / to-do. Shown as a
    list rather than a horizontal bar because the labels are user-language and
    a horizontal bar cannot survive five Chinese words without wrapping.
    """
    marks = {"done": DONE, "now": NOW, "todo": TODO}
    body = []
    for label, state in items:
        body.append(f"{marks.get(state, TODO)}  {label}")
    return box(body, title=title)


def flow(nodes: list[str], title: str = "") -> str:
    """A vertical chain of boxed stages with arrows between them.

    Used by `upgrade` to show what is about to happen before it happens, which
    is most of what "a better screen" means here: the flows were opaque, and a
    person watching an install had no idea what stage they were at or how many
    were left.
    """
    # Rows are built as plain inner content and handed to `box`, rather than
    # each one re-deriving the borders. The first version did the latter and
    # every row came out two columns wide -- the same class of mistake the
    # module docstring is about, made inside the module that exists to prevent
    # it. One function owns the frame; everything else owns only its content.
    content = WIDTH - 4
    widest = max((width(one) for one in nodes), default=0)
    span = min(widest + 4, content)
    left = max(0, (content - span) // 2)
    stem = left + span // 2

    rows: list[str] = []
    for index, node in enumerate(nodes):
        if index:
            rows.append(" " * stem + "|")
            rows.append(" " * stem + "v")
        rows.append(" " * left + "+" + "-" * (span - 2) + "+")
        rows.append(" " * left + "|" + centre(node, span - 2) + "|")
        rows.append(" " * left + "+" + "-" * (span - 2) + "+")
    return box(rows, title=title)


# ---------------------------------------------------------------------------
# Asking
# ---------------------------------------------------------------------------

def menu(question: str, options: list[str], footer: str = "") -> str:
    """A numbered choice.

    THE REASON THERE ARE MORE OF THESE NOW
    --------------------------------------
    The maintainer's second ask on 2026-08-20: more multiple choice. A blank prompt is
    the most expensive thing an interview can do to somebody who does not
    already know the vocabulary -- "what do you call one piece of work?" is
    unanswerable until you have seen that "a case" and "a matter" were options.
    Numbers also survive a phone: he answers these from Telegram, where typing
    a sentence is work and typing `2` is not.

    Free text stays only where the answer is genuinely theirs to invent -- a
    name, a folder, the word their trade actually uses when none of the
    offered ones fit. Every such menu ends with that escape.
    """
    body = [""]
    for index, option in enumerate(options, 1):
        body.append(f" {index}   {option}")
    body.append("")
    return box(body, title=question,
               footer=footer or "reply with a number")


def outcome(ok: bool, headline: str, detail: str = "") -> str:
    """How a flow ends. One shape for done, one for did-not."""
    mark = "[ok]" if ok else "[!!]"
    body = wrap(f"{mark}  {headline}", WIDTH - 4)
    if detail:
        body += [""] + wrap(detail, WIDTH - 4)
    return box(body)


def note(text: str) -> str:
    """An aside, unboxed. Not everything deserves a frame -- a screen made
    entirely of boxes is as unreadable as one with none."""
    return "     " + text
