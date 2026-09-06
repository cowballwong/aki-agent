"""The handful of projects you actually look at.

The maintainer's sketch for Today, 2026-08-23, puts six cards between the quick
buttons and the three columns,

A workspace can hold any number of projects. Six is what fits on the screen
above the fold, and more importantly six is what a person can hold in their
head -- the same reasoning that keeps the shipped schedule at six tasks
rather than the forty-three its ancestor accumulated.

WHY PINNED AND NOT "MOST RECENT"
--------------------------------
Most-recently-touched is the tempting default because it needs no decision
from anybody. It is also wrong for this: the project you touched last is
often the one you have just finished with, and the project you are avoiding
never appears at all. A pin is a statement about what matters; a timestamp is
a statement about what happened.

RECENCY USED TO FILL THE EMPTY SLOTS, and no longer does (2026-09-04). It
kept the row from being blank on day one at the cost of showing six projects
nobody had chosen, each wearing a "not pinned" label -- a guess with a
disclaimer is still a guess. Today shows what you pinned and an empty card
with a `+` on it; the empty state is a button rather than an apology.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import atomic, paths

HOW_MANY = 6


def pins_file() -> Path:
    return paths.state_dir() / "favourites.json"


def read_pins() -> list[str]:
    """The item keys somebody has pinned, in the order they pinned them."""
    stored = atomic.read_json(pins_file(), default=[]) or []
    if not isinstance(stored, list):
        return []
    return [str(one) for one in stored if str(one).strip()][:HOW_MANY]


def is_pinned(key: str) -> bool:
    return key in read_pins()


def pin(key: str) -> tuple[bool, str]:
    """Pin one project. Returns whether it changed, and what to say."""
    key = (key or "").strip()
    if not key:
        return False, "Nothing to pin."

    current = read_pins()
    if key in current:
        return False, "Already on Today."
    if len(current) >= HOW_MANY:
        return False, (
            f"Today holds {HOW_MANY}. Take one off first — the limit is the "
            "point of the row.")

    current.append(key)
    atomic.write_json(pins_file(), current)
    return True, "Added to Today."


def unpin(key: str) -> tuple[bool, str]:
    key = (key or "").strip()
    current = read_pins()
    if key not in current:
        return False, "It was not on Today."
    atomic.write_json(pins_file(), [one for one in current if one != key])
    return True, "Taken off Today."


def rename_workspace_in_pins(old: str, new: str) -> int:
    """Follow a workspace rename through the pins. Returns how many moved.

    A pin is stored as `workspace/project`, so renaming the workspace orphans
    every card in it -- and this module deliberately keeps a pin whose folder
    has gone, so they would sit in the file for ever, invisible, counting
    against the six.

    Called by the rename route AFTER the folder has actually moved, so a
    failed rename never rewrites the pins.
    """
    old, new = (old or "").strip(), (new or "").strip()
    if not old or not new or old == new:
        return 0

    current = read_pins()
    moved = [
        f"{new}/{one.split('/', 1)[1]}" if one.split("/", 1)[0] == old else one
        for one in current
    ]
    changed = sum(1 for a, b in zip(current, moved) if a != b)
    if changed:
        atomic.write_json(pins_file(), moved)
    return changed


def rename_key_in_pins(old: str, new: str) -> bool:
    """Follow one project's rename through the pins.

    An item's key is `workspace/folder`, so renaming the folder changes the
    key and orphans the pin. This module keeps a pin whose folder has gone on
    purpose, so an orphan sits in the file for ever -- invisible, and counting
    against the six.
    """
    old, new = (old or "").strip(), (new or "").strip()
    if not old or not new or old == new:
        return False

    current = read_pins()
    if old not in current:
        return False
    atomic.write_json(pins_file(),
                      [new if one == old else one for one in current])
    return True


def missing_pins(space) -> list[str]:
    """Pinned keys with no project behind them.

    A pin whose folder has gone is kept on purpose -- see `cards_for` -- and
    that is right: a cloud drive that has not mounted yet would otherwise
    quietly cost somebody their whole row. But a kept pin still counts
    against the six, so at the cap it is an invisible reason the `+` card has
    disappeared.

    Answered rather than acted on. The page can then say so, which is the
    honest version of both.
    """
    if space is None:
        return []
    have = {getattr(one, "key", "") for one in getattr(space, "items", []) or []}
    return [key for key in read_pins() if key not in have]


def forget(key: str) -> tuple[bool, str]:
    """Drop one pin, whether or not its project is still there."""
    return unpin(key)


def set_order(keys: list[str]) -> tuple[bool, str]:
    """Write a whole new order in one go.

    So the arrows rearrange the page and
    nothing is written until Save, which arrives here as the finished order.

    Anything not currently pinned is dropped and anything pinned but missing
    from the list is kept at the end. A reorder must never be able to add a
    pin, lose one, or exceed the six -- it is a rearrangement, and a form
    that has been sitting open in another tab is exactly how it would
    otherwise become something else.
    """
    current = read_pins()
    wanted = [str(one).strip() for one in keys if str(one).strip()]

    seen: list[str] = []
    for key in wanted:
        if key in current and key not in seen:
            seen.append(key)
    seen += [key for key in current if key not in seen]

    if seen == current:
        return False, "Nothing moved."
    atomic.write_json(pins_file(), seen)
    return True, "Order saved."


def move(key: str, by: int) -> tuple[bool, str]:
    """Shift one pin one place along the row. Returns whether it moved.


    The order was already the order they were pinned in, and the cards are
    drawn from it -- so arranging them is arranging this list, and no new
    store is needed for it.

    A move off either end does nothing and says so, rather than wrapping
    around: an arrow that teleports the first card to the last place is a
    surprise every time it happens.
    """
    key = (key or "").strip()
    current = read_pins()
    if key not in current:
        return False, "That is not on Today."

    at = current.index(key)
    to = at + by
    if to < 0 or to >= len(current):
        return False, "It is already at the end."

    current[at], current[to] = current[to], current[at]
    atomic.write_json(pins_file(), current)
    return True, "Moved."


def toggle(key: str) -> tuple[bool, str]:
    return unpin(key) if is_pinned(key) else pin(key)


@dataclass
class Card:
    """One project as it appears on Today."""

    key: str
    title: str
    area: str = ""
    note: str = ""
    open_count: int = 0
    waiting_count: int = 0
    last_touched: str = ""
    pinned: bool = True
    colour: str = ""

    @property
    def is_quiet(self) -> bool:
        return self.open_count == 0 and self.waiting_count == 0


def cards_for(space) -> list[Card]:
    """The six cards, pinned first and recency filling the rest.

    `space` is whatever `workspace.scan()` returned. Passed in rather than
    read here so the page's other panels and this one cannot disagree about
    what the workspace contains -- they are the same scan.
    """
    items = list(getattr(space, "items", []) or [])
    by_key = {getattr(one, "key", "") or getattr(one, "title", ""): one
              for one in items}

    chosen: list[tuple[str, bool]] = []
    for key in read_pins():
        if key in by_key:
            chosen.append((key, True))
        # A pin whose project has gone is skipped rather than shown as an
        # empty card. It is left in the file: renaming a folder should not
        # quietly forget that somebody cared about it.

    # NOTHING FILLS THE EMPTY SLOTS. It used to be recency, so a fresh
    # machine showed six cards nobody had chosen, each labelled "not pinned".
    #
    # The objection was right, and the docstring at the top of this file
    # already argued the same: a pin is
    # a statement about what matters, a timestamp is a statement about what
    # happened. Filling the row with timestamps and then writing "not pinned"
    # on each one was the design admitting it had guessed.
    #
    # An empty row now says so with one button that does something about it,
    # which is the shorter and more honest version.

    cards: list[Card] = []
    for key, pinned in chosen[:HOW_MANY]:
        item = by_key.get(key)
        if item is None:
            continue
        sections = getattr(item, "sections", {}) or {}
        cards.append(Card(
            key=key,
            title=getattr(item, "title", key),
            # The workspace it belongs to. Items carry `workspace`, not
            # `area` -- areas are a folder layer inside one, and what a person
            # wants on the card is which side of their life it is on.
            area=str(getattr(item, "workspace", "") or ""),
            note=(sections.get("state", "") or "").strip().splitlines()[0][:90]
                 if sections.get("state") else "",
            open_count=_count(sections.get("actions", ""), "- [ ]"),
            waiting_count=_count(sections.get("waiting", ""), "- "),
            last_touched=(getattr(item, "last_modified", None).strftime(
                "%d %b") if getattr(item, "last_modified", None) else ""),
            pinned=pinned,
            colour=getattr(item, "colour", "") or "",
        ))
    return cards


def count_lines(section: str, prefix: str) -> int:
    """How many lines of a section start with a prefix.

    Public because the project cards ask the same question the favourite
    cards do, and a second copy of the rule in a template is how "1 open"
    here and "2 open" there start disagreeing about the same file.
    """
    return _count(section, prefix)


def _count(section: str, prefix: str) -> int:
    return sum(1 for line in (section or "").splitlines()
               if line.strip().startswith(prefix))
