"""The event bus — one file every subsystem writes to, one the dashboard reads.

WHY THIS EXISTS
---------------
Before this, each part of the package kept its own record or none at all: the
notifier had held messages, traces had verdicts, the scheduler had whatever the
OS remembered, and the dashboard had to know about each of them separately to
show anything. Nothing could answer the simplest question a person asks of an
assistant — *what have you been doing?*

Both reference systems solve it the same way, and it is the component their
dashboards are built on: **one append-only log, one writer function that every
subsystem imports, one reader the interface polls.** The interface never has to
know who produced an entry. Adding a new subsystem costs one `record()` call
rather than a new panel.

WHAT IT IS NOT
--------------
Not a queue, and not an approval store. Nothing consumes these entries to
decide what to do next; they are a record, and a record only. Anything that
needs a status field that changes over time belongs somewhere else — mixing
mutable state into an append-only log is how you end up rewriting history.

Not a debug log either. `log_dir()` already holds those. An entry here is
something a *person* would recognise as having happened.

THE RULES
---------
1. **Writing an event must never break the thing that emitted it.** A full
   disk, a locked file, a bad value — all are swallowed. An assistant that
   fails to answer because it could not write its own diary is worse than one
   with an incomplete diary.
2. **Never write a secret.** Everything goes through `secrets.redact` first,
   because event text is assembled from user content and tool output, and
   people paste passwords into notes.
3. **One line, one JSON object, always with `at`, `kind`, `text`.** Extra
   fields go in `detail`, so a reader written today survives a writer that
   learns new tricks tomorrow.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any

from . import atomic, paths, secrets

# The kinds a reader can rely on existing. Anything else is allowed — this is a
# vocabulary, not a validator — but these are the ones the interface groups by.
KINDS = (
    "said",         # the assistant told the user something
    "heard",        # the user told the assistant something
    "task",         # a scheduled task started, finished or failed
    "change",       # something on disk was created or modified
    "decision",     # a verdict: approved, rejected, edited
    "problem",      # something went wrong and a person may need to know
    "note",         # anything else worth showing
)

MAX_TEXT = 2000

# How much history to keep, and when to start caring.
#
# The log had no trim at all, so it grew for the life of the install. These
# numbers are chosen so that trimming is rare and invisible: five thousand
# events is months of ordinary use for one person, and four megabytes is well
# past the point where anything reads the file whole.
#
# The trim is not a retention policy and is not offered as one. It is a
# backstop against a file that would otherwise grow without limit on somebody
# else's machine, where nobody is watching it.
KEEP_EVENTS = 5_000
MAX_LOG_BYTES = 4 * 1024 * 1024


def event_file() -> Path:
    return paths.log_dir() / "events.jsonl"


@dataclass
class Event:
    at: _dt.datetime
    kind: str
    text: str
    source: str = ""
    detail: dict[str, Any] = dataclass_field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(timespec="seconds"),
            "kind": self.kind,
            "text": self.text,
            "source": self.source,
            "detail": self.detail,
        }

    @property
    def when(self) -> str:
        """For an interface that wants a short human stamp."""
        return self.at.strftime("%H:%M")


def record(kind: str, text: str, *, source: str = "",
           detail: dict[str, Any] | None = None) -> None:
    """Write one event. Never raises — see rule 1.

    `source` names the subsystem ("schedule", "notify", "setup"), so the
    interface can say who did it without parsing the text.
    """
    try:
        clean = secrets.redact(str(text or "")).strip()
        if not clean:
            return
        if len(clean) > MAX_TEXT:
            clean = clean[:MAX_TEXT - 1] + "…"

        entry = Event(at=_dt.datetime.now(), kind=str(kind or "note"),
                      text=clean, source=str(source or ""),
                      detail=_clean_detail(detail))
        paths.ensure_app_dirs()
        atomic.append_line(event_file(),
                           json.dumps(entry.as_dict(), ensure_ascii=False))
        # Housekeeping, on the write rather than on a schedule -- nothing has
        # to remember to call it, and the check is one `stat` in the usual
        # case. See MAX_LOG_BYTES for why the log is allowed to be this big.
        atomic.trim_log(event_file(), KEEP_EVENTS, MAX_LOG_BYTES)
    except Exception:                                    # noqa: BLE001
        # Deliberately silent. See rule 1 — this must never be the reason
        # something else failed.
        return


def _clean_detail(detail: dict[str, Any] | None) -> dict[str, Any]:
    """Redact the values too. Detail is where a token would hide."""
    if not detail:
        return {}
    out: dict[str, Any] = {}
    for key, value in detail.items():
        if isinstance(value, str):
            out[str(key)] = secrets.redact(value)
        elif isinstance(value, (int, float, bool)) or value is None:
            out[str(key)] = value
        else:
            out[str(key)] = secrets.redact(str(value))
    return out


def read(limit: int = 100, *, kind: str = "",
         since_line: int = 0) -> list[Event]:
    """The most recent events, newest first.

    `since_line` supports the cursor pattern a live view needs: pass the line
    count you last saw and get only what has been added since, oldest first.
    A corrupt line is skipped rather than fatal — a half-written last line is
    normal when something is appending while you read.
    """
    path = event_file()
    if not path.exists():
        return []

    if since_line:
        # Resuming from a known line means the whole file has to be counted
        # through, so this branch reads it all. It is the live-follow path and
        # runs on a fixed small interval, not on every page load.
        try:
            raw = path.read_text(encoding="utf-8",
                                 errors="replace").splitlines()
        except OSError:
            return []
        chosen = raw[since_line:]
        newest_first = False
    else:
        # The common path: the last few, read from the end of the file.
        # This used to load the entire log to show twenty lines, so the cost
        # of drawing today's page grew with everything that had ever happened.
        wanted = (limit * 4 if limit else 400)
        chosen = atomic.tail_lines(path, wanted)
        newest_first = True

    events: list[Event] = []
    for line in chosen:
        parsed = _parse(line)
        if parsed is None:
            continue
        if kind and parsed.kind != kind:
            continue
        events.append(parsed)

    if newest_first:
        events.reverse()
    return events[:limit] if limit else events


def line_count() -> int:
    """Where a live reader should resume from next time."""
    path = event_file()
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def _parse(line: str) -> Event | None:
    line = line.strip()
    if not line:
        return None
    try:
        data = json.loads(line)
        return Event(
            at=_dt.datetime.fromisoformat(data["at"]),
            kind=str(data.get("kind", "note")),
            text=str(data.get("text", "")),
            source=str(data.get("source", "")),
            detail=data.get("detail") or {},
        )
    except (ValueError, KeyError, TypeError):
        return None


def summary(events: list[Event] | None = None) -> str:
    """One plain sentence about recent activity, for a person.

    Used by the health check and the brief, which is why it says "nothing yet"
    in words rather than returning an empty string — an empty panel reads as
    broken, and "nothing yet" reads as calm.
    """
    entries = events if events is not None else read(limit=50)
    if not entries:
        return "Nothing recorded yet."

    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.kind] = counts.get(entry.kind, 0) + 1
    parts = [f"{count} {kind}" for kind, count in
             sorted(counts.items(), key=lambda pair: -pair[1])]
    latest = entries[0]
    return (f"{len(entries)} recent: " + ", ".join(parts)
            + f". Last at {latest.when} — {latest.text[:80]}")


# ---------------------------------------------------------------------------
# Consuming the bus without doing it twice
# ---------------------------------------------------------------------------

def watermark_file(name: str) -> Path:
    """Where one consumer remembers how far it has read."""
    safe = "".join(char if char.isalnum() or char in "-_" else "-"
                   for char in name) or "consumer"
    return paths.state_dir() / f"seen-{safe}.json"


def unseen(name: str, limit: int = 200) -> list[Event]:
    """Events this consumer has not processed, oldest first.

    ANY background process that reads this bus and ACTS on what it finds needs
    a watermark, or a restart makes it act twice. Double-notifying is the
    polite failure; double-sending an email is not. Reading is free — it is
    acting that must be exactly once — so the mark is advanced by the caller,
    after the work, rather than here.
    """
    mark = atomic.read_json(watermark_file(name), default={}) or {}
    return read(limit=limit, since_line=int(mark.get("line", 0)))


def mark_seen(name: str, line: int | None = None) -> None:
    """Record how far this consumer got. Call AFTER the work, never before."""
    try:
        paths.ensure_app_dirs()
        atomic.write_json(watermark_file(name),
                          {"line": int(line if line is not None
                                       else line_count()),
                           "at": _dt.datetime.now().isoformat(
                               timespec="seconds")})
    except Exception:                                    # noqa: BLE001
        return
