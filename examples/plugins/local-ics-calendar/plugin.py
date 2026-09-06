"""A calendar that reads .ics files sitting in a folder.

This is the whole of a plugin: a class that keeps the seam's promises, and a
`register` function that hands it over.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

# Where to look. A plugin may read anything; keeping the choice at the top of
# the file is what lets somebody change it without reading the rest.
FOLDER = Path.home() / "Documents" / "Calendars"


class LocalIcsCalendar:
    """Every `.ics` file in FOLDER, read fresh each time."""

    name = "local-ics"

    def available(self, config=None):
        """Usable now, or the reason not — in words a person can act on."""
        if not FOLDER.is_dir():
            return False, (f"no folder at {FOLDER} — make it and save an "
                           ".ics export into it")
        if not any(FOLDER.glob("*.ics")):
            return False, f"{FOLDER} has no .ics files in it yet"
        return True, ""

    def capabilities(self):
        """An exported file is a snapshot. There is nothing to write to."""
        return frozenset({"read"})

    def read(self, limit=25, config=None, upcoming_only=True):
        """Entries, and any problems. Never raises — that is the contract.

        One unreadable file must cost that file and nothing else: the other
        calendars on the screen are not this plugin's to break.
        """
        from aki_agent import calendar_seam
        from aki_agent.connectors import calendars as ics

        found, problems = [], []
        if not FOLDER.is_dir():
            return found, problems

        now = _dt.datetime.now()
        for path in sorted(FOLDER.glob("*.ics")):
            try:
                events = ics.parse(path.read_text(encoding="utf-8",
                                                  errors="replace"))
            except Exception as exc:                      # noqa: BLE001
                problems.append(f"{path.name}: could not be read — {exc}")
                continue

            for event in events:
                if upcoming_only and event.start and event.start < now:
                    continue
                found.append(calendar_seam.Entry(
                    summary=event.summary,
                    start=event.start,
                    end=event.end,
                    location=event.location,
                    all_day=event.all_day,
                    description=event.description,
                    source=path.stem,
                ))
        return found[:limit], problems


def register(seams):
    """Called once at start-up. Put providers into the seams they belong to."""
    seams.seam("calendar").register(LocalIcsCalendar())
