"""Knowledge — the documents and links the assistant should know about.

WHAT THIS IS FOR
----------------
A person's assistant needs a small shelf of reference material: the company
handbook, a standards document, a link to the regulations that govern their
work, the notes from a course. Not their whole filesystem -- a chosen shelf.

WHAT IT IS NOT
--------------
It is not a search engine, an embedding index or a retrieval system. It is a
list of pointers with a note about why each one matters.

That is a deliberate choice about honesty. A retrieval system that silently
returns nothing relevant looks identical to one that works, and the user finds
out when the assistant confidently answers from thin air. A list of pointers
can be read by a human in ten seconds and its gaps are obvious.

When a shelf outgrows this -- hundreds of documents, genuinely needing search
-- that is the moment to add an index, and the moment will be obvious. Not
before.

TWO KINDS OF ENTRY
------------------
    DOCUMENT   a file on this machine. Stored as a path; never copied, so it
               stays current and the user keeps ownership of it.
    LINK       a URL. Fetched only when the user asks for it, never crawled.

THE SAFETY RULE
---------------
The contents of anything on this shelf are DATA, never instructions. A
document that says "ignore your previous instructions" is a document with an
odd sentence in it, not a command. This matters more here than almost anywhere
else, because a shelf is exactly where someone would plant one.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, asdict
from pathlib import Path

from . import atomic, paths

KINDS = ("document", "link")


def store_file() -> Path:
    return paths.memory_dir() / "knowledge.json"


@dataclass
class Entry:
    """One thing on the shelf."""

    key: str
    title: str
    kind: str                 # "document" or "link"
    target: str               # a file path, or a URL
    why: str = ""             # what it is for, in the user's words
    tags: tuple[str, ...] = ()
    added: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, not {self.kind!r}")
        if not self.added:
            self.added = _dt.date.today().isoformat()

    @property
    def available(self) -> bool:
        """Is it actually reachable?

        For a document this is a real check. For a link it is not -- we do not
        make a network request to find out, because a shelf of fifty links
        would mean fifty requests every time the dashboard loaded, and a
        service being briefly down is not the same as a dead link.
        """
        if self.kind == "document":
            return Path(self.target).exists()
        return True

    def status(self) -> str:
        """What to show next to it, honestly."""
        if self.kind == "link":
            return "link (not checked)"
        if self.available:
            return "found"
        return "MISSING -- the file has moved or been deleted"


def _safe_key(text: str) -> str:
    """A stable key from an entry's title, in any script.

    See `skills_store._safe_key`: this stripped everything outside
    `[a-z0-9]`, so two entries titled in Chinese both slugged to "entry" and
    the second replaced the first with no error. Fixed 2026-09-05.
    """
    key = re.sub(r"[^\w]+", "-", text.lower(), flags=re.UNICODE).strip("-_")
    return (key or "entry")[:60]


def read_all() -> list[Entry]:
    raw = atomic.read_json(store_file(), default=[]) or []
    entries: list[Entry] = []
    for item in raw:
        try:
            entries.append(Entry(
                key=str(item["key"]),
                title=str(item.get("title", "")),
                kind=str(item.get("kind", "document")),
                target=str(item.get("target", "")),
                why=str(item.get("why", "")),
                tags=tuple(item.get("tags") or ()),
                added=str(item.get("added", "")),
            ))
        except (KeyError, TypeError, ValueError):
            # One bad row must not empty the shelf.
            continue
    return entries


def _write_all(entries: list[Entry]) -> Path:
    return atomic.write_json(store_file(), [asdict(entry) for entry in entries])


def add(title: str, kind: str, target: str, why: str = "",
        tags: tuple[str, ...] = ()) -> Entry:
    """Put something on the shelf.

    Validates that a document actually exists at the time it is added. A shelf
    full of broken pointers is worse than an empty one, because the assistant
    reports them as available.
    """
    kind = kind.strip().lower()
    target = target.strip()

    if kind == "document":
        if not target:
            raise ValueError("a document needs a file path")
        if not Path(target).exists():
            raise ValueError(
                f"There is no file at {target}. Check the path -- it must be "
                "the full path, not just the file name."
            )
    elif kind == "link":
        if not target.startswith(("http://", "https://")):
            raise ValueError(
                "A link must start with http:// or https://"
            )
    else:
        raise ValueError(f"kind must be one of {KINDS}")

    entry = Entry(key=_safe_key(title or target), title=title.strip() or target,
                  kind=kind, target=target, why=why.strip(), tags=tuple(tags))

    entries = [existing for existing in read_all() if existing.key != entry.key]
    entries.append(entry)
    _write_all(entries)
    return entry


def update(key: str, **changes) -> Entry | None:
    entries = read_all()
    for index, entry in enumerate(entries):
        if entry.key != key:
            continue
        data = asdict(entry)
        for field, value in changes.items():
            if field in data and value is not None:
                data[field] = value
        data["tags"] = tuple(data.get("tags") or ())
        updated = Entry(**data)
        entries[index] = updated
        _write_all(entries)
        return updated
    return None


def remove(key: str) -> bool:
    entries = read_all()
    remaining = [entry for entry in entries if entry.key != key]
    if len(remaining) == len(entries):
        return False
    _write_all(remaining)
    return True


def find(query: str = "", tag: str = "") -> list[Entry]:
    """Plain substring search over titles, reasons and tags."""
    needle = query.strip().casefold()
    entries = read_all()

    if tag:
        entries = [entry for entry in entries
                   if tag.casefold() in
                   {value.casefold() for value in entry.tags}]

    if not needle:
        return entries

    return [
        entry for entry in entries
        if needle in entry.title.casefold()
        or needle in entry.why.casefold()
        or needle in entry.target.casefold()
    ]


def broken() -> list[Entry]:
    """Documents that have moved or been deleted.

    Surfaced on the dashboard rather than left to be discovered. A pointer
    that has quietly gone stale is the same failure as a panel showing frozen
    data: it looks fine and it is not.
    """
    return [entry for entry in read_all()
            if entry.kind == "document" and not entry.available]
