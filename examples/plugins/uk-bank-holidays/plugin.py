"""Every England & Wales bank holiday, worked out rather than looked up.

WHY THIS IS A GOOD FIRST PLUGIN TO READ
---------------------------------------
It needs no account, no address, no network and no configuration, so it works
the moment it is installed — which makes it the cheapest possible way to see
whether the plugin system does what it says.

It also does real work. The movable feasts are computed, not typed into a
table that goes stale in January: Easter comes out of the anonymous Gregorian
algorithm, the May and August holidays are the first or last Monday of their
month, and Christmas and Boxing Day roll forward to the next working day when
they land on a weekend. That substitute rule is the part everybody gets wrong
by hand.
"""

from __future__ import annotations

import datetime as _dt


def easter_sunday(year: int) -> _dt.date:
    """The anonymous Gregorian algorithm. Exact for any year 1583-4099."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return _dt.date(year, month, day + 1)


def _first_monday(year: int, month: int) -> _dt.date:
    day = _dt.date(year, month, 1)
    return day + _dt.timedelta(days=(7 - day.weekday()) % 7)


def _last_monday(year: int, month: int) -> _dt.date:
    if month == 12:
        day = _dt.date(year, 12, 31)
    else:
        day = _dt.date(year, month + 1, 1) - _dt.timedelta(days=1)
    return day - _dt.timedelta(days=(day.weekday() - 0) % 7)


def _substitute(day: _dt.date, taken: set) -> _dt.date:
    """Roll a weekend holiday forward to the next free weekday.

    `taken` matters: Christmas Day on a Saturday moves to the Monday, so
    Boxing Day cannot also be the Monday and goes to the Tuesday. Written out
    because this is the rule a hand-made list always gets wrong.
    """
    while day.weekday() >= 5 or day in taken:
        day += _dt.timedelta(days=1)
    return day


def holidays(year: int) -> list:
    """`(date, name)` for England & Wales, in date order."""
    easter = easter_sunday(year)
    taken: set = set()
    found = []

    def add(day, name, substitutes=False):
        if substitutes:
            moved = _substitute(day, taken)
            if moved != day:
                name += " (substitute day)"
            day = moved
        taken.add(day)
        found.append((day, name))

    add(_dt.date(year, 1, 1), "New Year's Day", substitutes=True)
    add(easter - _dt.timedelta(days=2), "Good Friday")
    add(easter + _dt.timedelta(days=1), "Easter Monday")
    add(_first_monday(year, 5), "Early May bank holiday")
    add(_last_monday(year, 5), "Spring bank holiday")
    add(_last_monday(year, 8), "Summer bank holiday")
    add(_dt.date(year, 12, 25), "Christmas Day", substitutes=True)
    add(_dt.date(year, 12, 26), "Boxing Day", substitutes=True)

    return sorted(found)


class UkBankHolidays:
    """A calendar that is always right and never needs connecting."""

    name = "uk-holidays"

    def available(self, config=None):
        # Nothing to connect, nothing to fail. The one provider that is
        # always ready is genuinely useful: it proves the plumbing works on a
        # machine where nothing else is set up yet.
        return True, ""

    def capabilities(self):
        # A bank holiday is a fact about the country, not an appointment.
        return frozenset({"read"})

    def read(self, limit=25, config=None, upcoming_only=True):
        from aki_agent import calendar_seam

        today = _dt.date.today()
        years = range(today.year, today.year + 3)

        found = []
        for year in years:
            for day, name in holidays(year):
                if upcoming_only and day < today:
                    continue
                found.append(calendar_seam.Entry(
                    summary=name,
                    start=_dt.datetime(day.year, day.month, day.day),
                    all_day=True,
                    source="UK bank holidays",
                ))
        return found[:limit], []


def register(seams):
    seams.seam("calendar").register(UkBankHolidays())
