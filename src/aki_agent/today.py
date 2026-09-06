"""What the assistant knows about today, gathered in one place.

The maintainer asked for a Today page as the dashboard's landing page: token usage for
the hour and the week, the context left, weather, whether things are running,
what is waiting, and the calendar.

THE CONSTRAINT THAT SHAPED EVERY FIGURE HERE
--------------------------------------------
No API key, for anything. That is the promise the whole package is built on,
so a panel that needs a key is a panel that does not ship. It turned out not
to cost much:

* **Token usage** is read from the transcripts Claude Code already writes on
  this machine (`~/.claude/projects/**/*.jsonl`). Every assistant turn records
  its own usage, with a timestamp. Nothing is asked of any server, it works
  offline, and it is the user's own data on the user's own disk.
* **Weather** is Open-Meteo, which needs no key at all -- including its
  geocoder, so a person can type "Winchester" rather than find coordinates.

EVERY PANEL SAYS WHEN IT DOES NOT KNOW
--------------------------------------
A dashboard that prints a plausible zero is worse than one that says "no
calendar connected", because the first cannot be told apart from a quiet day.
Each piece here carries its own `problem` string and the page prints it.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import atomic, paths

# ---------------------------------------------------------------------------
# Token usage, from the transcripts on this machine
# ---------------------------------------------------------------------------

# Claude Code writes one JSONL per session under here.
TRANSCRIPT_ROOT = ".claude/projects"

# What a model's context window holds. Only what can be stated confidently --
# an unknown model gives a token count and no percentage, which is honest,
# rather than a percentage of a number somebody guessed.
CONTEXT_WINDOWS = (
    ("[1m]", 1_000_000),
    ("-1m", 1_000_000),
    ("opus", 200_000),
    ("sonnet", 200_000),
    ("haiku", 200_000),
)


def transcript_files(within_days: int = 8) -> list[Path]:
    """Session transcripts touched recently, newest first.

    Filtered by modification time before anything is opened: a long-running
    install accumulates hundreds of megabytes of these, and reading all of
    them to draw one page would make the page the slowest thing in the
    product.
    """
    root = paths.home() / TRANSCRIPT_ROOT
    if not root.is_dir():
        return []

    cutoff = _dt.datetime.now().timestamp() - within_days * 86_400
    found: list[Path] = []
    try:
        for path in root.glob("*/*.jsonl"):
            try:
                if path.stat().st_mtime >= cutoff:
                    found.append(path)
            except OSError:                               # pragma: no cover
                continue
    except OSError:                                       # pragma: no cover
        return []
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def _tokens_in(usage: dict) -> int:
    """Everything that was charged for, added up.

    Cache reads are included deliberately. They are cheaper per token, not
    free, and leaving them out shows a number that bears no relation to what
    the session is actually consuming.
    """
    return sum(int(usage.get(key) or 0) for key in (
        "input_tokens", "cache_creation_input_tokens",
        "cache_read_input_tokens", "output_tokens"))


def _entries(path: Path):
    """Yield (when, usage, model) for each assistant turn in one transcript."""
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                # Cheap reject before parsing: most lines are not assistant
                # turns and JSON parsing all of them is the whole cost.
                if '"usage"' not in line:
                    continue
                try:
                    record = json.loads(line)
                except (ValueError, TypeError):
                    continue
                message = record.get("message") or {}
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue
                stamp = record.get("timestamp") or ""
                try:
                    when = _dt.datetime.fromisoformat(
                        stamp.replace("Z", "+00:00"))
                except ValueError:
                    continue
                yield when, usage, str(message.get("model") or "")
    except OSError:                                       # pragma: no cover
        return


@dataclass
class Usage:
    """Tokens over two windows, and how full the current context is."""

    five_hours: int = 0
    week: int = 0
    busiest_five_hours: int = 0
    # US dollars this would have cost at API prices. NOT a bill: this package
    # runs on the user's Claude Code subscription and nobody is charged per
    # token. Labelled as such everywhere it is shown.
    five_hour_cost: float = 0.0
    week_cost: float = 0.0
    last_24_hours: list = field(default_factory=list)
    context: int = 0
    context_limit: int | None = None
    # The context size at which the assistant restarts itself. From `guard`,
    # so the page and the recycler can never quote different numbers.
    recycle_at: int = 0
    model: str = ""
    problem: str = ""

    @property
    def recycle_fraction(self) -> float | None:
        """Where the auto-recycle mark sits on the ring.

        A fraction of the WINDOW, not of the threshold: the notch has to be
        drawn at the same scale as the fill or it points at the wrong place.
        """
        if not self.context_limit or not self.recycle_at:
            return None
        return min(1.0, self.recycle_at / self.context_limit)

    def recycle_note(self) -> str:
        """How much room is left before the session is restarted.

        It is 180K, not 200K -- `guard.
        CONTEXT_LIMIT` -- and the difference is worth stating rather than
        quietly drawing his number.

        Past the mark it says so instead of a negative: the recycle also needs
        the session to be idle and a gap since the last one, so being over the
        line is a normal state that lasts a while rather than a countdown that
        has run out.
        """
        if not self.recycle_at:
            return ""
        left = self.recycle_at - self.context
        if left <= 0:
            return f"past the {_short_tokens(self.recycle_at)} recycle mark"
        return f"{_short_tokens(left)} to auto-recycle"

    @property
    def context_fraction(self) -> float | None:
        if not self.context_limit:
            return None
        return min(1.0, self.context / self.context_limit)


def _short_tokens(value: int) -> str:
    """1,234,567,890 -> 1.2B. The same shape the page's own filter makes."""
    for size, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if value >= size:
            return f"{value / size:.1f}{suffix}"
    return str(value)


def context_limit_for(model: str, observed: int = 0) -> int | None:
    """The window this model holds, or None when it cannot be said.

    `observed` is load-bearing. The transcript records `claude-opus-5` for
    both the 200K and the 1M variant, so the name alone said 200K for a
    session already carrying 440K -- and the gauge drew a full bar on a
    session that was 44% used. A context bigger than the assumed window is
    proof the assumption is wrong, so the evidence wins over the name.
    """
    lowered = (model or "").lower()
    limit = None
    for marker, size in CONTEXT_WINDOWS:
        if marker in lowered:
            limit = size
            break

    if limit and observed > limit:
        bigger = [size for _, size in CONTEXT_WINDOWS if size > observed]
        return min(bigger) if bigger else None
    return limit


# 2 -> 3 on 2026-09-04, when the store began remembering the last rate-limit
# refusal as well as the hourly totals. The bump is what forces the one slow
# re-read: the offsets in a shape-2 store already sit at the end of every
# transcript, so without it the new field would stay empty for ever on any
# machine that had ever drawn this page.
BUCKET_SHAPE = 3


def _buckets_file() -> Path:
    return paths.app_dir() / "state" / "usage-buckets.json"


def _hour_key(when: _dt.datetime) -> str:
    return when.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H")


def _refresh_buckets(now: _dt.datetime) -> dict:
    """Fold new transcript lines into per-hour totals, reading only the new ones.

    Transcripts are append-only, so the offset each file was last read to is
    all that is needed to avoid re-parsing gigabytes. The buckets are hourly
    because the two windows the page shows -- five hours and a week -- are
    both whole numbers of hours, and an hour of resolution costs nothing.

    This is the difference between a landing page that takes ten seconds and
    one that takes none, measured on a machine with 4.7 billion tokens of
    history.
    """
    store = atomic.read_json(_buckets_file(), default={}) or {}
    # The stored shape changed when cost was added. Rebuilding is one slow
    # read, once; half-reading an old file would show a week of work as
    # costing nothing, which is worse than the wait.
    if store.get("shape") != BUCKET_SHAPE:
        store = {}
    files = store.get("files") or {}
    latest = store.get("latest") or {}

    for path in transcript_files():
        key = str(path)
        known = files.get(key) or {}
        try:
            size = path.stat().st_size
        except OSError:                                   # pragma: no cover
            continue

        offset = int(known.get("offset") or 0)
        # A file that shrank was rewritten, so anything remembered about it is
        # about a different file wearing the same name.
        if size < offset:
            known, offset = {}, 0

        buckets = dict(known.get("buckets") or {})
        spend = dict(known.get("spend") or {})
        if offset < size:
            for when, usage, model, position in _entries_from(path, offset):
                stamp = _hour_key(when)
                buckets[stamp] = buckets.get(stamp, 0) + _tokens_in(usage)
                spend[stamp] = spend.get(stamp, 0.0) + cost_of(usage, model)
                seen = latest.get("when") or ""
                if when.isoformat() >= seen:
                    latest = {
                        "when": when.isoformat(),
                        "model": model,
                        "context": sum(int(usage.get(name) or 0) for name in (
                            "input_tokens", "cache_creation_input_tokens",
                            "cache_read_input_tokens")),
                    }
                offset = position

        # Buckets older than the longest window are dead weight for ever.
        cutoff = _hour_key(now - _dt.timedelta(days=8))
        buckets = {k: v for k, v in buckets.items() if k >= cutoff}
        spend = {k: v for k, v in spend.items() if k >= cutoff}
        files[key] = {"offset": offset, "buckets": buckets, "spend": spend}

    # Forget files that have nothing left to say.
    #
    # The buckets inside each entry were already pruned to eight days; the
    # `files` dict itself was not, so it grew by one key per transcript for
    # ever. Measured on this machine: 124,854 bytes and 406 entries after six
    # days, every byte of it re-parsed on each landing-page load, and all but
    # a handful of those entries holding two empty dicts and an offset into a
    # session nobody will look at again.
    #
    # An entry is kept while it still carries a bucket inside the window. Once
    # every bucket has aged out there is nothing to add up, and the offset is
    # only worth keeping if the file is still on disk and might yet be
    # appended to -- a Claude Code transcript that has not been touched in
    # eight days is finished.
    files = {key: entry for key, entry in files.items()
             if (entry.get("buckets") or entry.get("spend")
                 or _recently_touched(key, now))}

    store = {"shape": BUCKET_SHAPE, "files": files, "latest": latest}
    try:
        paths.ensure_app_dirs()
        atomic.write_json(_buckets_file(), store)
    except Exception:                                     # noqa: BLE001
        pass                                              # pragma: no cover
    return store


def _recently_touched(key: str, now: _dt.datetime) -> bool:
    """Whether a transcript could still gain lines worth counting.

    A file that is gone, or that has not been written to inside the longest
    window the page shows, can never contribute again — so remembering where
    we read up to in it is pure weight.
    """
    try:
        touched = Path(key).stat().st_mtime
    except OSError:
        return False        # deleted, or on a drive that is not mounted today
    age = now.timestamp() - touched
    return age < 8 * 24 * 3600


def _entries_from(path: Path, offset: int):
    """Like `_entries`, but starting part-way in and reporting where it got to."""
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            # `readline`, not `for line in handle`: iterating a text file
            # disables `tell()` ("telling position disabled by next() call"),
            # which raised OSError, was caught as "this file is unreadable",
            # and produced a page of confident zeroes.
            while True:
                line = handle.readline()
                if not line:
                    break
                position = handle.tell()
                if '"usage"' not in line:
                    continue
                try:
                    record = json.loads(line)
                except (ValueError, TypeError):
                    continue
                message = record.get("message") or {}
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue
                stamp = record.get("timestamp") or ""
                try:
                    when = _dt.datetime.fromisoformat(
                        stamp.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if when.tzinfo is None:
                    when = when.replace(tzinfo=_dt.timezone.utc)
                yield when, usage, str(message.get("model") or ""), position
    except OSError:                                       # pragma: no cover
        return


def read_usage(now: _dt.datetime | None = None) -> Usage:
    """Add up what this machine has spent, and how full the newest session is.

    The five-hour and weekly totals are still added up: they are shown as
    figures under the chart, where a number with no denominator belongs. It
    is the rings around them that went.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)

    if not transcript_files():
        return Usage(
            problem="No Claude Code transcripts on this machine yet.")

    store = _refresh_buckets(now)

    five = _hour_key(now - _dt.timedelta(hours=5))
    week = _hour_key(now - _dt.timedelta(days=7))

    result = Usage()
    peak = 0
    hourly: dict[str, int] = {}
    money: dict[str, float] = {}
    for known in (store.get("files") or {}).values():
        for stamp, spent in (known.get("buckets") or {}).items():
            hourly[stamp] = hourly.get(stamp, 0) + spent
        for stamp, amount in (known.get("spend") or {}).items():
            money[stamp] = money.get(stamp, 0.0) + amount

    for stamp, spent in hourly.items():
        if stamp >= week:
            result.week += spent
        if stamp >= five:
            result.five_hours += spent

    for stamp, amount in money.items():
        if stamp >= week:
            result.week_cost += amount
        if stamp >= five:
            result.five_hour_cost += amount

    # The last 24 hours, oldest first, for the shape under the gauges. Hours
    # with nothing in them are zeros rather than gaps: a quiet night is part
    # of the shape.
    series: list[int] = []
    for step in range(23, -1, -1):
        stamp = _hour_key(now - _dt.timedelta(hours=step))
        series.append(hourly.get(stamp, 0))
    result.last_24_hours = series

    # A five-hour total means nothing without something to compare it to, and
    # there is no plan limit to read without an API key. Their own busiest
    # stretch this week is a comparison they can act on: "this is a heavy
    # session for you" is the useful sentence.
    ordered = sorted(hourly)
    for index, stamp in enumerate(ordered):
        window = sum(hourly[s] for s in ordered[max(0, index - 4):index + 1])
        peak = max(peak, window)
    result.busiest_five_hours = peak

    latest = store.get("latest") or {}

    for path in transcript_files():
        key = str(path)
        known = files.get(key) or {}
        try:
            size = path.stat().st_size
        except OSError:                                   # pragma: no cover
            continue

        offset = int(known.get("offset") or 0)
        # A file that shrank was rewritten, so anything remembered about it is
        # about a different file wearing the same name.
        if size < offset:
            known, offset = {}, 0

        buckets = dict(known.get("buckets") or {})
        spend = dict(known.get("spend") or {})
        if offset < size:
            for when, usage, model, position in _entries_from(path, offset):
                stamp = _hour_key(when)
                buckets[stamp] = buckets.get(stamp, 0) + _tokens_in(usage)
                spend[stamp] = spend.get(stamp, 0.0) + cost_of(usage, model)
                seen = latest.get("when") or ""
                if when.isoformat() >= seen:
                    latest = {
                        "when": when.isoformat(),
                        "model": model,
                        "context": sum(int(usage.get(name) or 0) for name in (
                            "input_tokens", "cache_creation_input_tokens",
                            "cache_read_input_tokens")),
                    }
                offset = position

        # Buckets older than the longest window are dead weight for ever.
        cutoff = _hour_key(now - _dt.timedelta(days=8))
        buckets = {k: v for k, v in buckets.items() if k >= cutoff}
        spend = {k: v for k, v in spend.items() if k >= cutoff}
        files[key] = {"offset": offset, "buckets": buckets, "spend": spend}

    # Forget files that have nothing left to say.
    #
    # The buckets inside each entry were already pruned to eight days; the
    # `files` dict itself was not, so it grew by one key per transcript for
    # ever. Measured on this machine: 124,854 bytes and 406 entries after six
    # days, every byte of it re-parsed on each landing-page load, and all but
    # a handful of those entries holding two empty dicts and an offset into a
    # session nobody will look at again.
    #
    # An entry is kept while it still carries a bucket inside the window. Once
    # every bucket has aged out there is nothing to add up, and the offset is
    # only worth keeping if the file is still on disk and might yet be
    # appended to -- a Claude Code transcript that has not been touched in
    # eight days is finished.
    files = {key: entry for key, entry in files.items()
             if (entry.get("buckets") or entry.get("spend")
                 or _recently_touched(key, now))}

    store = {"shape": BUCKET_SHAPE, "files": files, "latest": latest}
    try:
        paths.ensure_app_dirs()
        atomic.write_json(_buckets_file(), store)
    except Exception:                                     # noqa: BLE001
        pass                                              # pragma: no cover
    return store


def _recently_touched(key: str, now: _dt.datetime) -> bool:
    """Whether a transcript could still gain lines worth counting.

    A file that is gone, or that has not been written to inside the longest
    window the page shows, can never contribute again — so remembering where
    we read up to in it is pure weight.
    """
    try:
        touched = Path(key).stat().st_mtime
    except OSError:
        return False        # deleted, or on a drive that is not mounted today
    age = now.timestamp() - touched
    return age < 8 * 24 * 3600


def _entries_from(path: Path, offset: int):
    """Like `_entries`, but starting part-way in and reporting where it got to."""
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            # `readline`, not `for line in handle`: iterating a text file
            # disables `tell()` ("telling position disabled by next() call"),
            # which raised OSError, was caught as "this file is unreadable",
            # and produced a page of confident zeroes.
            while True:
                line = handle.readline()
                if not line:
                    break
                position = handle.tell()
                if '"usage"' not in line:
                    continue
                try:
                    record = json.loads(line)
                except (ValueError, TypeError):
                    continue
                message = record.get("message") or {}
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue
                stamp = record.get("timestamp") or ""
                try:
                    when = _dt.datetime.fromisoformat(
                        stamp.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if when.tzinfo is None:
                    when = when.replace(tzinfo=_dt.timezone.utc)
                yield when, usage, str(message.get("model") or ""), position
    except OSError:                                       # pragma: no cover
        return


def read_usage(now: _dt.datetime | None = None) -> Usage:
    """Add up what this machine has spent, and how full the newest session is.

    The five-hour and weekly totals are still added up: they are shown as
    figures under the chart, where a number with no denominator belongs. It
    is the rings around them that went.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)

    if not transcript_files():
        return Usage(
            problem="No Claude Code transcripts on this machine yet.")

    store = _refresh_buckets(now)

    five = _hour_key(now - _dt.timedelta(hours=5))
    week = _hour_key(now - _dt.timedelta(days=7))

    result = Usage()
    peak = 0
    hourly: dict[str, int] = {}
    money: dict[str, float] = {}
    for known in (store.get("files") or {}).values():
        for stamp, spent in (known.get("buckets") or {}).items():
            hourly[stamp] = hourly.get(stamp, 0) + spent
        for stamp, amount in (known.get("spend") or {}).items():
            money[stamp] = money.get(stamp, 0.0) + amount

    for stamp, spent in hourly.items():
        if stamp >= week:
            result.week += spent
        if stamp >= five:
            result.five_hours += spent

    for stamp, amount in money.items():
        if stamp >= week:
            result.week_cost += amount
        if stamp >= five:
            result.five_hour_cost += amount

    # The last 24 hours, oldest first, for the shape under the gauges. Hours
    # with nothing in them are zeros rather than gaps: a quiet night is part
    # of the shape.
    series: list[int] = []
    for step in range(23, -1, -1):
        stamp = _hour_key(now - _dt.timedelta(hours=step))
        series.append(hourly.get(stamp, 0))
    result.last_24_hours = series

    # A five-hour total means nothing without something to compare it to, and
    # there is no plan limit to read without an API key. Their own busiest
    # stretch this week is a comparison they can act on: "this is a heavy
    # session for you" is the useful sentence.
    ordered = sorted(hourly)
    for index, stamp in enumerate(ordered):
        window = sum(hourly[s] for s in ordered[max(0, index - 4):index + 1])
        peak = max(peak, window)
    result.busiest_five_hours = peak

    latest = store.get("latest") or {}
    result.context = int(latest.get("context") or 0)
    result.model = str(latest.get("model") or "")
    result.context_limit = context_limit_for(result.model, result.context)
    return result


# ---------------------------------------------------------------------------
# What it would have cost
# ---------------------------------------------------------------------------

# Published API prices, US dollars per million tokens, checked 2026-08-19.
# (input, output). Anything not listed falls back to DEFAULT_PRICE and the
# page says the model was not recognised rather than quietly using it.
PRICES = {
    "fable": (10.00, 50.00),
    "mythos": (10.00, 50.00),
    "opus": (5.00, 25.00),
    "sonnet": (3.00, 15.00),
    "haiku": (1.00, 5.00),
}
DEFAULT_PRICE = (5.00, 25.00)

# Cache writes cost more than fresh input and cache reads cost far less.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


def price_for(model: str) -> tuple[float, float]:
    lowered = (model or "").lower()
    for marker, rates in PRICES.items():
        if marker in lowered:
            return rates
    return DEFAULT_PRICE


def cost_of(usage: dict, model: str) -> float:
    """Dollars this one turn would have cost on the API.

    Not what the user pays: they are on a subscription. This is the number
    that answers "is my assistant expensive?", which is a different and more
    useful question than "what is my bill?".
    """
    input_rate, output_rate = price_for(model)
    million = 1_000_000

    def field(name):
        return int(usage.get(name) or 0)

    return (
        field("input_tokens") * input_rate / million
        + field("cache_creation_input_tokens")
          * input_rate * CACHE_WRITE_MULTIPLIER / million
        + field("cache_read_input_tokens")
          * input_rate * CACHE_READ_MULTIPLIER / million
        + field("output_tokens") * output_rate / million
    )


# ---------------------------------------------------------------------------
# Weather, with no key and no account
# ---------------------------------------------------------------------------

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# Coordinates -> the name of the place they are in.
#
# 」. Open-Meteo geocodes by name only, so this is the one extra
# service in the weather path. It is asked the same question the forecast is
# already being asked -- these coordinates -- so it learns nothing the
# forecast call did not already carry, and it needs no key and no account.
#
# Soft everywhere: a failure here leaves the card saying "Your location",
# which is what it said before. The name is a courtesy, not the feature.
REVERSE_URL = "https://api.bigdatacloud.net/data/reverse-geocode-client"
WEATHER_CACHE_MINUTES = 30

# WMO weather codes, in the words a person would use. Grouped rather than
# exhaustive: "light drizzle" and "moderate drizzle" are the same decision
# about whether to take a coat.
WEATHER_WORDS = {
    0: "clear", 1: "mostly clear", 2: "some cloud", 3: "cloudy",
    45: "fog", 48: "freezing fog",
    51: "drizzle", 53: "drizzle", 55: "drizzle",
    56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "showers", 81: "showers", 82: "heavy showers",
    85: "snow showers", 86: "snow showers",
    95: "thunderstorms", 96: "thunderstorms", 99: "thunderstorms",
}


@dataclass
class Weather:
    place: str = ""
    temperature: float | None = None
    description: str = ""
    high: float | None = None
    low: float | None = None
    rain_chance: int | None = None
    problem: str = ""
    # Whether it is daylight WHERE THE WEATHER IS, which is not the same as
    # the hour on this machine's clock -- and the icon is drawn from it, so a
    # clear night should not show a sun. Open-Meteo answers this directly
    # rather than it being worked out from a sunrise table here.
    is_day: bool = True

    @property
    def known(self) -> bool:
        return self.temperature is not None

    def advice(self) -> str:
        """One line, only when there is something to do about it.


        The bar for saying anything is that it changes what somebody picks up
        on the way out of the door. "Mild and cloudy" changes nothing, so it
        gets no line -- a card that comments on every kind of weather is one
        people stop reading before the day it matters.
        """
        if not self.known:
            return ""

        kind = weather_kind(self.description)
        chance = self.rain_chance or 0

        if kind == "storm":
            return "Thunderstorms about — an umbrella will not help much."
        if kind == "snow":
            return "Snow — leave a bit earlier."
        if kind == "rain" or chance >= 50:
            return "Take an umbrella."
        if chance >= 30:
            return "Rain is possible — an umbrella would not be wasted."

        low = self.low if self.low is not None else self.temperature
        if low is not None and low <= 2:
            return "Cold enough to ice over — take care underfoot."
        if self.temperature is not None and self.temperature >= 28:
            return "Hot — water, and stay out of the sun at midday."
        return ""


def weather_kind(description: str) -> str:
    """Which shape to draw for a described sky.

    The words come from `WEATHER_WORDS`, which is already grouped the way a
    person thinks -- "light rain" and "heavy rain" are the same decision
    about a coat. This groups one step further, into the shapes worth
    drawing. Anything unrecognised gets the haze lines rather than a wrong
    picture: a sun over a rainy day is worse than no picture.

    IT LIVED IN THE DASHBOARD as a template filter until 2026-09-04, when the
    advice line needed the same answer. Two copies of a classifier is how the
    icon and the sentence under it end up disagreeing about the same sky.
    """
    text = str(description or "").lower()
    if "thunder" in text:
        return "storm"
    if "snow" in text:
        return "snow"
    if "rain" in text or "drizzle" in text or "shower" in text:
        return "rain"
    if "clear" in text:
        return "sun"
    if "cloud" in text:
        return "cloud"
    return "fog"


def _get_json(url: str, params: dict, timeout: float = 6.0):
    query = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}?{query}", timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def coordinates(place: str) -> tuple[float, float] | None:
    """Read "51.75, -0.34" as a pair of numbers, or None for a town name.

    WHY BOTH (reported 2026-08-20)
    ----------------------------
    *"最好有個 option 係 auto get computer location"*. The browser can answer
    that exactly -- it asks the person, and it is the only party in this
    picture that knows where the machine is -- but what it gives back is a
    latitude and a longitude, not a town.

    Rather than add a second field, a second config key and a second thing to
    keep in step, the one `location` setting accepts either. Somebody typing
    "Winchester" is unaffected; somebody pressing the button gets numbers in
    the same box.
    """
    parts = [part.strip() for part in str(place).split(",")]
    if len(parts) != 2:
        return None
    try:
        latitude, longitude = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None
    return latitude, longitude


def _weather_cache_file() -> Path:
    return paths.app_dir() / "state" / "weather.json"


def _named(latitude: float, longitude: float, call) -> str:
    """The town these coordinates are in, or the words we used to show.

    Never raises and never blocks the weather: the forecast is the point of
    this card, and a nameless "Your location" with a real temperature beats
    an error where the temperature should be.
    """
    try:
        found = call(REVERSE_URL, {"latitude": latitude,
                                   "longitude": longitude,
                                   "localityLanguage": "en"}) or {}
    except Exception:                                     # noqa: BLE001
        return "Your location"

    # In the order a person would say where they are. `locality` is often a
    # district and `city` the town; either is better than a county, and a
    # county is better than nothing.
    for key in ("city", "locality", "principalSubdivision"):
        name = str(found.get(key) or "").strip()
        if name:
            return name
    return "Your location"


def read_weather(place: str, now: _dt.datetime | None = None,
                 fetcher=None) -> Weather:
    """Today's weather for a place named in plain words.

    Cached on disk for half an hour. Not politeness to somebody else's free
    service -- though it is that too -- but because this is drawn on every
    page load, and a page that makes two network calls before it renders is a
    page that feels broken on a train.
    """
    if not place.strip():
        return Weather(problem="No town set yet.")

    now = now or _dt.datetime.now()
    cached = atomic.read_json(_weather_cache_file(), default={}) or {}
    if (cached.get("place") == place
            and cached.get("at")
            and _dt.datetime.fromisoformat(cached["at"])
            > now - _dt.timedelta(minutes=WEATHER_CACHE_MINUTES)):
        return Weather(**{k: v for k, v in cached.items()
                          if k in Weather.__dataclass_fields__})

    call = fetcher or _get_json
    fixed = coordinates(place)
    try:
        if fixed is None:
            found = call(GEOCODE_URL, {"name": place, "count": 1,
                                       "language": "en", "format": "json"})
            results = (found or {}).get("results") or []
            if not results:
                return Weather(
                    place=place,
                    problem=f"I could not find a place called {place}.")
            spot = results[0]
        else:
            # Straight from the browser's own location, so there is nothing to
            # look up and nobody to ask. It also means the weather works for
            # somewhere with no name in a gazetteer, which a town-name-only
            # field quietly cannot do.
            spot = {"latitude": fixed[0], "longitude": fixed[1],
                    "name": _named(fixed[0], fixed[1], call)}

        forecast = call(FORECAST_URL, {
            "latitude": spot["latitude"], "longitude": spot["longitude"],
            "current": "temperature_2m,weather_code,is_day",
            "daily": ("temperature_2m_max,temperature_2m_min,"
                      "precipitation_probability_max"),
            "timezone": "auto", "forecast_days": 1,
        })
    except Exception as exc:                              # noqa: BLE001
        # Offline is the normal case on a laptop, not an error worth a
        # traceback. Say it in one line and let the rest of the page draw.
        return Weather(place=place,
                       problem=f"Could not reach the weather service ({exc}).")

    current = (forecast or {}).get("current") or {}
    daily = (forecast or {}).get("daily") or {}

    def first(key):
        values = daily.get(key) or []
        return values[0] if values else None

    weather = Weather(
        place=spot.get("name") or place,
        temperature=current.get("temperature_2m"),
        description=WEATHER_WORDS.get(int(current.get("weather_code") or 0),
                                      ""),
        high=first("temperature_2m_max"),
        low=first("temperature_2m_min"),
        rain_chance=first("precipitation_probability_max"),
        # Open-Meteo returns 1 or 0. Missing means day, which is the safer
        # default: a sun on a dark evening is a smaller error than a moon at
        # noon, and only one of the two makes the page look broken.
        is_day=bool(current.get("is_day", 1)),
    )

    try:
        paths.ensure_app_dirs()
        atomic.write_json(_weather_cache_file(), {
            "at": now.isoformat(timespec="seconds"),
            "place": place,
            **{field_name: getattr(weather, field_name)
               for field_name in Weather.__dataclass_fields__},
        })
    except Exception:                                     # noqa: BLE001
        pass                                              # pragma: no cover

    return weather


# ---------------------------------------------------------------------------
# Everything else the page shows
# ---------------------------------------------------------------------------

@dataclass
class Card:
    """One small fact with a number and a caption."""

    label: str
    value: str
    detail: str = ""
    href: str = ""
    tone: str = ""            # "" | "good" | "warn" | "bad"


@dataclass
class Today:
    usage: Usage = field(default_factory=Usage)
    weather: Weather = field(default_factory=Weather)
    cards: list[Card] = field(default_factory=list)
    events: list = field(default_factory=list)
    calendar_problem: str = ""
    tasks_installed: int = 0
    last_activity: _dt.datetime | None = None

    @property
    def server_ok(self) -> bool:
        """The dashboard is answering, so the only real question is the rest."""
        return self.tasks_installed > 0


# ---------------------------------------------------------------------------
# The calendar, whether or not one is connected
# ---------------------------------------------------------------------------

CALENDAR_CACHE_MINUTES = 15


def _calendar_cache_file() -> Path:
    return paths.app_dir() / "state" / "calendar-cache.json"


def read_events(config, now: _dt.datetime | None = None) -> tuple[list, str]:
    """Everything on the connected calendars, and why there is nothing if so.

     -- so an empty month
    is a correct, finished state here, not a placeholder.

    Asks the calendar seam rather than the ICS connector, which is what makes
    that sentence true: a provider added later shows up here without this
    function being edited. It also means a Google account now appears in the
    month view, which it never did while this read one connector by name.

    Cached for a quarter of an hour: this is drawn on the landing page, and a
    page that downloads several calendars before it renders is a page nobody
    keeps open.
    """
    from . import calendar_seam

    now = now or _dt.datetime.now()
    if not calendar_seam.readers(config):
        return [], ("No calendar connected yet. Add one on the Connections "
                    "page and it will fill in here.")

    cached = atomic.read_json(_calendar_cache_file(), default={}) or {}
    fresh = (cached.get("at") and _dt.datetime.fromisoformat(cached["at"])
             > now - _dt.timedelta(minutes=CALENDAR_CACHE_MINUTES))

    if fresh and isinstance(cached.get("entries"), list):
        events = [_entry_from_cache(one) for one in cached["entries"]]
        return ([one for one in events if one is not None],
                "; ".join(cached.get("problems") or []))

    events, problems = calendar_seam.everything(config=config)
    try:
        paths.ensure_app_dirs()
        atomic.write_json(_calendar_cache_file(), {
            "at": now.isoformat(timespec="seconds"),
            "entries": [_entry_to_cache(one) for one in events],
            "problems": problems,
        })
    except Exception:                                     # noqa: BLE001
        # A cache that cannot be written is slower, not broken.
        pass
    return events, "; ".join(problems)


def _entry_to_cache(entry) -> dict:
    return {
        "summary": entry.summary,
        "start": entry.start.isoformat() if entry.start else None,
        "end": entry.end.isoformat() if entry.end else None,
        "location": entry.location,
        "all_day": entry.all_day,
        "description": entry.description,
        "source": entry.source,
        "ref": entry.ref,
        "link": entry.link,
        "changeable": entry.changeable,
    }


def _entry_from_cache(raw: dict):
    """One cached entry, or None if the file has been hand-edited into rubble.

    Returning None for a bad row rather than raising: a corrupt cache should
    cost the landing page one line, not the whole page.
    """
    from . import calendar_seam

    def _time(value):
        if not value:
            return None
        try:
            return _dt.datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    if not isinstance(raw, dict) or not raw.get("summary"):
        return None
    return calendar_seam.Entry(
        summary=raw.get("summary", ""),
        start=_time(raw.get("start")),
        end=_time(raw.get("end")),
        location=raw.get("location") or "",
        all_day=bool(raw.get("all_day")),
        description=raw.get("description") or "",
        source=raw.get("source") or "",
        ref=raw.get("ref") or "",
        link=raw.get("link") or "",
        changeable=bool(raw.get("changeable")),
    )


# Six months either side of today. Far enough to plan a term or look back at
# one; short enough that the arrows stop where the data does rather than
# marching into empty months and looking broken.
MONTH_RANGE = 6


def _add_months(day: _dt.date, months: int) -> _dt.date:
    total = day.year * 12 + (day.month - 1) + months
    return _dt.date(total // 12, total % 12 + 1, 1)


def month_from(text: str, today: _dt.date | None = None) -> _dt.date:
    """The month a `?m=YYYY-MM` asks for, clamped to what we will show.

    Anything unparseable falls back to this month rather than erroring: a
    mistyped URL should land somewhere sensible, not on a stack trace.
    """
    today = today or _dt.date.today()
    try:
        year, month = text.split("-")
        wanted = _dt.date(int(year), int(month), 1)
    except Exception:                                     # noqa: BLE001
        return today.replace(day=1)

    first = _add_months(today, -MONTH_RANGE)
    last = _add_months(today, MONTH_RANGE)
    return min(max(wanted, first), last)


def day_from(text: str, today: _dt.date | None = None) -> _dt.date:
    """The day a `?d=YYYY-MM-DD` asks for; today when it says nothing."""
    today = today or _dt.date.today()
    try:
        return _dt.date.fromisoformat(text)
    except Exception:                                     # noqa: BLE001
        return today


def step_month(shown: _dt.date, by: int,
               today: _dt.date | None = None) -> str:
    """The `?m=` value for the next or previous month — "" at the ends.

    An empty string is how the template knows to draw the arrow as spent
    rather than as a link to nowhere.
    """
    today = today or _dt.date.today()
    wanted = _add_months(shown, by)
    if wanted < _add_months(today, -MONTH_RANGE):
        return ""
    if wanted > _add_months(today, MONTH_RANGE):
        return ""
    return wanted.strftime("%Y-%m")


def events_on(events: list, day: _dt.date) -> list:
    """Just that day's events, in order."""
    return [event for event in events
            if event.start is not None and event.start.date() == day]


def month_grid(day: _dt.date | None = None) -> list[list[_dt.date | None]]:
    """The weeks of this month, Monday first, padded with None.

    Built here rather than in the template because a month is arithmetic and
    Jinja is not the place to do arithmetic anybody has to read.
    """
    import calendar as _calendar

    day = day or _dt.date.today()
    weeks = _calendar.Calendar(firstweekday=0).monthdatescalendar(
        day.year, day.month)
    return [[date if date.month == day.month else None for date in week]
            for week in weeks]


def gather(config, now: _dt.datetime | None = None) -> "Today":
    """Everything the Today page shows, in one call.

    One function so that the view has no logic in it, and so that a test can
    ask "what would today look like" without a browser.
    """
    from . import approvals, schedule, workspace

    now = now or _dt.datetime.now()
    page = Today()
    page.usage = read_usage()

    # THE CONTEXT RING MEASURES THE ASSISTANT'S OWN SESSION, not the newest
    # transcript on the machine.
    #
    # `read_usage` walks every transcript this computer has, because that is
    # what a usage total is. The context is a different question -- how full
    # is the window of the session I am looking at -- and answering it from
    # the machine-wide newest entry meant that on a computer running a second
    # Claude Code session the ring showed that one instead. Measured on
    # 2026-09-04: 507K on the ring, 43K in the assistant's own session.
    #
    # `guard` already reads the right file, by the rule in `session.py` that
    # the newest transcript is not necessarily the live one. Asking it here is
    # also what stops the page and the recycler quoting different numbers at
    # each other.
    try:
        from . import guard

        own = guard.context_size()
        if own:
            page.usage.context = own
            # The MODEL from the same session, not the machine-wide latest.
            # Taking the size from one session and the model name from another
            # is how the ring came out as "43K / 1M" while that session was
            # actually running a 200K window -- a first draft of this did
            # exactly that.
            live = guard.live_transcript()
            model = page.usage.model
            if live is not None:
                for _, _, seen in _entries(live):
                    if seen:
                        model = seen
            page.usage.model = model
            page.usage.context_limit = context_limit_for(model, own)
        page.usage.recycle_at = guard.CONTEXT_LIMIT
    except Exception:                                     # noqa: BLE001
        # The ring falls back to what `read_usage` found rather than
        # disappearing. A dashboard that hides a number when one of its two
        # sources is unavailable is harder to trust than one that shows the
        # other and says nothing.
        pass
    page.weather = read_weather(getattr(config.user, "location", "") or "")

    try:
        page.tasks_installed = len(schedule.installed_names_or_empty())
    except Exception:                                     # noqa: BLE001
        page.tasks_installed = 0

    waiting = []
    try:
        waiting = approvals.open_items()
    except Exception:                                     # noqa: BLE001
        pass

    scan = None
    try:
        scan = workspace.scan(config)
    except Exception:                                     # noqa: BLE001
        pass

    items = list(scan.items) if scan else []
    trouble = [item for item in items if item.has_problems]

    page.cards = [
        Card("Waiting for you", str(len(waiting)),
             "nothing to answer" if not waiting else "needs an answer",
             href="/waiting", tone="warn" if waiting else "good"),
        Card(config.layout.schema.item_label_plural or "Projects",
             str(len(items)),
             f"{len(trouble)} need a look" if trouble else "all healthy",
             href="/projects", tone="warn" if trouble else "good"),
        Card("Scheduled work", str(page.tasks_installed),
             "running in the background" if page.tasks_installed
             else "nothing installed yet",
             href="/schedule",
             tone="good" if page.tasks_installed else "warn"),
    ]

    events, problem = read_events(config, now)
    page.calendar_problem = problem
    today_date = now.date()
    page.events = [event for event in events
                   if event.start and event.start.date() >= today_date][:12]
    return page
