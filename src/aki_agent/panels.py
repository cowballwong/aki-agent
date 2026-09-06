"""Panels -- a workspace's own screen, declared rather than coded.

WHY A PANEL IS DATA AND NOT CODE
--------------------------------
The tempting version of this file is "a panel is a Python function plus a
template". It is more expressive and it kills the upgrade path: a user-made
panel would be code running inside their own dashboard, and every release
would have to ask "have you edited this one?". `library.py` argues the same
case for skills and reaches the same answer -- ship read-only, fork on edit,
and keep the thing the user touches as data.

So a panel is a markdown file with frontmatter that declares **what it reads**
and **how to draw it**. The renderer is ours.

WHERE THE NUMBERS COME FROM, AND THE RULE THAT MATTERS MOST
-----------------------------------------------------------
A panel reads one of two things:

  * `reads: items`  -- the projects already scanned by `workspace.scan()`,
                       filtered on the fields the user declared in config.
  * `reads: rows`   -- a list inside one markdown file per project, e.g.
                       `programme.md` or `cost.md`.

Nothing here writes those files. They are written by a skill, from a source
document the user supplied, and **every row carries a `source:`** naming the
document the figure came out of. That is not decoration: the whole product
promise on a construction job is that a date or a figure on the screen can be
traced back to the programme or the cost plan it came from. A row with no
source renders as unsourced rather than being quietly drawn like the rest --
see `Row.unsourced`. An assistant that types a plausible number onto a
schedule is worse than one that says it does not know.

WHY THE RENDERER KNOWS NOTHING ABOUT CONSTRUCTION
-------------------------------------------------
`gantt` draws "things with a start and an end"; the spec says which keys hold
them. The same primitive is a build programme in one workspace and a term
plan in another. If the word "milestone" ever appears in the drawing code,
this design has failed the same way an `Item.stage` attribute would have.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

from . import paths

# The kinds the renderer can actually draw. A spec naming anything else is
# reported on the page rather than raising -- an unknown panel is a version
# skew between a library and an engine, and skew must degrade, not crash.
KINDS = ("table", "gantt", "bars", "counter", "notes")

# The file a workspace uses to say which panels it shows, in what order.
WORKSPACE_FILE = "_workspace.md"


def library_panels_dir() -> Path:
    from . import library
    return library.library_dir() / "panels"


def custom_panels_dir() -> Path:
    """A user's own panels, forked from ours or written from scratch.

    In the config folder rather than in the workspace folder, matching what
    already happens to a forked skill: one place, and every workspace can name
    it. Putting them beside the work would mean copying a panel to reuse it,
    and two copies of an edited thing is the divergence `library.py` exists to
    prevent.
    """
    return paths.app_dir() / "panels"


# ---------------------------------------------------------------------------
# The spec
# ---------------------------------------------------------------------------

@dataclass
class Panel:
    """One panel, as declared. No data in here -- see `render()`."""

    key: str
    kind: str
    title: str
    description: str = ""
    industries: tuple = ()
    category: str = "General"
    keywords: tuple = ()
    # "items" or "rows"
    reads: str = "items"
    # For `reads: rows` -- which file inside each project folder, and which
    # key inside its frontmatter holds the list.
    source_file: str = ""
    rows_key: str = "rows"
    # Field mapping. Every one of these names a key in the row (or a schema
    # field, for `reads: items`), never a domain concept.
    columns: tuple = ()
    label_key: str = "label"
    start_key: str = "start"
    end_key: str = "end"
    baseline_key: str = "baseline_end"
    status_key: str = "status"
    value_keys: tuple = ()
    unit: str = ""
    where: dict = dataclass_field(default_factory=dict)
    limit: int = 0
    # What the panel says when rows carry no source, and when it has no data
    # at all. Both live in the SPEC and not in the engine: the engine may not
    # know the word for the document these figures came out of. The default
    # below names no trade.
    unsourced_note: str = "{n} of {total} rows carry no source."
    empty_note: str = ""
    path: Path | None = None
    body: str = ""

    @property
    def is_ours(self) -> bool:
        return bool(self.path) and library_panels_dir() in self.path.parents


def _as_tuple(raw) -> tuple:
    if raw is None:
        return ()
    if isinstance(raw, (list, tuple)):
        return tuple(str(one).strip() for one in raw if str(one).strip())
    return tuple(part.strip() for part in str(raw).split(",") if part.strip())


def read_spec(path: Path) -> Panel | None:
    """Read one panel spec. A malformed one is skipped, never raised."""
    from .workspace import split_frontmatter

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    data, body = split_frontmatter(text)
    if not isinstance(data, dict) or data.get("__frontmatter_error__"):
        return None

    kind = str(data.get("kind") or "").strip()
    if not kind:
        return None

    return Panel(
        key=str(data.get("name") or path.stem).strip(),
        kind=kind,
        title=str(data.get("title") or data.get("name") or path.stem).strip(),
        description=str(data.get("description") or "").strip(),
        industries=_as_tuple(data.get("industries")),
        category=str(data.get("category") or "General").strip(),
        keywords=_as_tuple(data.get("keywords")),
        reads=str(data.get("reads") or "items").strip(),
        source_file=str(data.get("file") or "").strip(),
        rows_key=str(data.get("rows") or "rows").strip(),
        columns=_as_tuple(data.get("columns")),
        label_key=str(data.get("label") or "label").strip(),
        start_key=str(data.get("start") or "start").strip(),
        end_key=str(data.get("end") or "end").strip(),
        baseline_key=str(data.get("baseline") or "baseline_end").strip(),
        status_key=str(data.get("status") or "status").strip(),
        value_keys=_as_tuple(data.get("values")),
        unit=str(data.get("unit") or "").strip(),
        where=data.get("where") if isinstance(data.get("where"), dict) else {},
        limit=int(data.get("limit") or 0),
        unsourced_note=str(data.get("unsourced_note")
                           or "{n} of {total} rows carry no source.").strip(),
        empty_note=str(data.get("empty_note") or "").strip(),
        path=path,
        body=body.strip(),
    )


def plugin_panels_dirs() -> list[Path]:
    """A `panels/` folder inside any installed plugin.

    This is what makes a whole profession installable rather than built in: a
    plugin ships the panels, the skills and the field list for one trade
    together, and the engine gains a screen it has never heard of.

    Failures here are swallowed on purpose. A broken plugin must cost the user
    its own panels and nothing else -- a dashboard that will not render because
    a third party shipped a bad manifest is a worse outcome than a missing box.
    """
    try:
        from . import plugins

        installed, _ = plugins.installed()
        return [plugin.path / "panels" for plugin in installed]
    except Exception:
        return []


def catalogue() -> list[Panel]:
    """Every panel available: the user's own first, then plugins, then ours.

    A user's panel with the same key wins, which is what makes forking work --
    the fork is found first and the shipped one stays on disk untouched for
    the next upgrade to replace. A plugin's panel beats a shipped one of the
    same name for the same reason the seam registry lets a later layer
    override an earlier one.
    """
    found: list[Panel] = []
    for directory in (custom_panels_dir(), *plugin_panels_dirs(),
                      library_panels_dir()):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            panel = read_spec(path)
            if panel and not any(one.key == panel.key for one in found):
                found.append(panel)
    return found


def by_key(key: str) -> Panel | None:
    for panel in catalogue():
        if panel.key == key:
            return panel
    return None


# ---------------------------------------------------------------------------
# Which panels a workspace shows
# ---------------------------------------------------------------------------

def declared_for(workspace_dir: Path) -> list[str]:
    """The panel keys named in a workspace's `_workspace.md`, in order.

    No file means no declaration, which is not an error: the caller falls back
    to a default screen. A workspace that has never been configured must show
    something rather than a blank page with an explanation on it.
    """
    from .workspace import split_frontmatter

    spec = workspace_dir / WORKSPACE_FILE
    if not spec.is_file():
        return []
    try:
        data, _ = split_frontmatter(spec.read_text(encoding="utf-8"))
    except OSError:
        return []
    if not isinstance(data, dict):
        return []
    return list(_as_tuple(data.get("panels")))


def panels_for(workspace_dir: Path | None, items: list) -> list[Panel]:
    """The panels to draw for one workspace.

    Declared ones first. Where nothing is declared, a panel is offered only if
    the projects in the workspace actually carry the file it reads -- a Gantt
    with no programme file anywhere is not a screen, it is an empty box asking
    the user what they did wrong.
    """
    everything = catalogue()
    by_name = {panel.key: panel for panel in everything}

    declared = declared_for(workspace_dir) if workspace_dir else []
    if declared:
        return [by_name[key] for key in declared if key in by_name]

    return [panel for panel in everything
            if panel.reads == "rows"
            and any(_rows_file(item, panel).is_file() for item in items)]


# ---------------------------------------------------------------------------
# Reading rows
# ---------------------------------------------------------------------------

@dataclass
class Row:
    """One line of a panel's data, with where it came from."""

    values: dict
    item_key: str = ""
    item_title: str = ""
    source: str = ""

    @property
    def unsourced(self) -> bool:
        """Drawn differently, and counted on the page.

        A row without a `source:` is a figure nobody can trace. It is still
        shown -- hiding it would be worse -- but it is never allowed to look
        like the sourced ones.
        """
        return not self.source.strip()

    def get(self, key: str, default=None):
        return self.values.get(key, default)


def _rows_file(item, panel: Panel) -> Path:
    name = panel.source_file or "rows.md"
    if not name.endswith(".md"):
        name += ".md"
    return Path(item.path) / name


def read_rows(items: list, panel: Panel) -> list[Row]:
    """Every row from every project in the workspace, in project order."""
    from .workspace import split_frontmatter

    rows: list[Row] = []
    for item in items:
        path = _rows_file(item, panel)
        if not path.is_file():
            continue
        try:
            data, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if not isinstance(data, dict):
            continue
        raw_rows = data.get(panel.rows_key)
        if not isinstance(raw_rows, list):
            continue
        # A source declared once at the top of the file applies to every row in
        # it -- a whole programme usually comes out of one document, and making
        # the user repeat the filename on twenty rows is how the field ends up
        # empty.
        file_source = str(data.get("source") or "").strip()
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            rows.append(Row(
                values=raw,
                item_key=item.key,
                item_title=item.title,
                source=str(raw.get("source") or file_source or "").strip(),
            ))
    return rows


def _date(raw) -> _dt.date | None:
    if isinstance(raw, _dt.datetime):
        return raw.date()
    if isinstance(raw, _dt.date):
        return raw
    if not raw:
        return None
    try:
        return _dt.date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None


def _number(raw) -> float | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    cleaned = (str(raw).replace(",", "").replace("£", "")
               .replace("$", "").strip())
    try:
        return float(cleaned)
    except ValueError:
        return None


def money(value: float | None, unit: str = "") -> str:
    """A figure a quantity surveyor would not wince at: no decimals, grouped."""
    if value is None:
        return "--"
    return f"{unit}{value:,.0f}"


# ---------------------------------------------------------------------------
# Geometry -- computed here, so it can be tested without a browser
# ---------------------------------------------------------------------------

# The drawing is a fixed-width SVG scaled by CSS. Fixed because the maths has
# to happen server-side -- no chart library is reachable, the dashboard works
# offline and ships no JavaScript for this -- and scaled because a person will
# open it on a laptop and on a phone.
CHART_WIDTH = 980
LABEL_WIDTH = 250
ROW_HEIGHT = 30
HEADER_HEIGHT = 34
BAR_HEIGHT = 13


@dataclass
class GanttBar:
    label: str
    item_title: str
    x: float
    width: float
    y: float
    baseline_x: float = 0.0
    baseline_width: float = 0.0
    slip_days: int = 0
    status: str = ""
    dates: str = ""
    source: str = ""
    unsourced: bool = False

    @property
    def late(self) -> bool:
        return self.slip_days > 0

    @property
    def slip_label(self) -> str:
        if self.slip_days > 0:
            return f"+{self.slip_days}d"
        if self.slip_days < 0:
            return f"{self.slip_days}d"
        return ""


@dataclass
class Gantt:
    bars: list = dataclass_field(default_factory=list)
    ticks: list = dataclass_field(default_factory=list)
    width: int = CHART_WIDTH
    height: int = HEADER_HEIGHT
    label_width: int = LABEL_WIDTH
    bar_height: int = BAR_HEIGHT
    row_height: int = ROW_HEIGHT
    today_x: float | None = None
    first: _dt.date | None = None
    last: _dt.date | None = None
    unsourced: int = 0
    problems: list = dataclass_field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.bars

    @property
    def late_count(self) -> int:
        return sum(1 for bar in self.bars if bar.late)


def _month_starts(first: _dt.date, last: _dt.date) -> list[_dt.date]:
    months = []
    year, month = first.year, first.month
    while _dt.date(year, month, 1) <= last:
        months.append(_dt.date(year, month, 1))
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return months


def build_gantt(rows: list, panel: Panel, today: _dt.date | None = None) -> Gantt:
    """Turn dated rows into bar geometry.

    Two bars per row where a baseline is known: the plan underneath, thin, and
    what is actually forecast on top. The slip is then a thing you see rather
    than a number you have to compare -- which is the entire reason a
    programme is drawn instead of tabulated.
    """
    today = today or _dt.date.today()

    dated: list[tuple] = []
    problems: list[str] = []
    for row in rows:
        start = _date(row.get(panel.start_key))
        end = _date(row.get(panel.end_key)) or start
        baseline = _date(row.get(panel.baseline_key))
        label = str(row.get(panel.label_key) or "").strip() or "(unnamed)"
        if start is None:
            problems.append(f"{label}: no {panel.start_key} date")
            continue
        if end < start:
            problems.append(f"{label}: ends before it starts")
            end = start
        dated.append((row, label, start, end, baseline))

    chart = Gantt(problems=problems)
    if not dated:
        return chart

    first = min(min(start, baseline or start)
                for _, _, start, _, baseline in dated)
    last = max(max(end, baseline or end)
               for _, _, _, end, baseline in dated)
    # Never divide by zero, and never draw a one-week programme full width:
    # pad a short span out to a month so it reads as a moment, not a project.
    if (last - first).days < 30:
        last = first + _dt.timedelta(days=30)

    span = (last - first).days or 1
    plot = CHART_WIDTH - LABEL_WIDTH - 12

    def x_for(day: _dt.date) -> float:
        return round(LABEL_WIDTH + ((day - first).days / span) * plot, 2)

    for index, (row, label, start, end, baseline) in enumerate(dated):
        x = x_for(start)
        bar = GanttBar(
            label=label,
            item_title=row.item_title,
            x=x,
            width=max(x_for(end) - x, 3.0),
            y=HEADER_HEIGHT + index * ROW_HEIGHT,
            status=str(row.get(panel.status_key) or "").strip().lower(),
            dates=f"{start.isoformat()} → {end.isoformat()}",
            source=row.source,
            unsourced=row.unsourced,
        )
        if baseline:
            bar.baseline_x = x
            bar.baseline_width = max(x_for(baseline) - x, 3.0)
            bar.slip_days = (end - baseline).days
        chart.bars.append(bar)

    chart.first, chart.last = first, last
    chart.height = HEADER_HEIGHT + len(chart.bars) * ROW_HEIGHT + 12
    months = _month_starts(first, last)
    chart.ticks = [
        {
            "x": x_for(month),
            "label": month.strftime("%b"),
            # The year is written once, and again whenever it turns over --
            # a twelve-month bar chart with no year on it has been misread by
            # somebody in every office that has ever printed one.
            "year": month.strftime("%Y") if (month.month == 1 or month == months[0]) else "",
        }
        for month in months
    ]
    if first <= today <= last:
        chart.today_x = x_for(today)
    chart.unsourced = sum(1 for bar in chart.bars if bar.unsourced)
    return chart


@dataclass
class MoneyBar:
    label: str
    item_title: str
    parts: list = dataclass_field(default_factory=list)
    headline: float = 0.0
    over: float = 0.0
    over_display: str = ""
    source: str = ""
    unsourced: bool = False


@dataclass
class Bars:
    rows: list = dataclass_field(default_factory=list)
    totals: list = dataclass_field(default_factory=list)
    keys: tuple = ()
    unit: str = ""
    width: int = CHART_WIDTH
    label_width: int = LABEL_WIDTH
    unsourced: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.rows


def build_bars(rows: list, panel: Panel) -> Bars:
    """Compare two or three figures per line against the largest of them.

    Scaled to the biggest figure across the whole panel, not per row, because
    the question anybody asks of a cost page is "which line is the big one",
    and per-row scaling answers a different question convincingly.
    """
    keys = panel.value_keys or ("budget", "committed", "spent")
    plot = CHART_WIDTH - LABEL_WIDTH - 12

    parsed: list[tuple] = []
    for row in rows:
        values = {key: _number(row.get(key)) for key in keys}
        if all(value is None for value in values.values()):
            continue
        parsed.append((row, values))

    chart = Bars(keys=tuple(keys), unit=panel.unit)
    if not parsed:
        return chart

    biggest = max((value or 0.0)
                  for _, values in parsed
                  for value in values.values()) or 1.0

    for row, values in parsed:
        bar = MoneyBar(
            label=str(row.get(panel.label_key) or "").strip() or "(unnamed)",
            item_title=row.item_title,
            source=row.source,
            unsourced=row.unsourced,
        )
        # The first key is the allowance; everything after it is measured
        # against it. Flagging only the LAST one was wrong in the way that
        # matters: an order placed over budget shows up in `committed` months
        # before it shows up in `spent`, and that is the whole point of
        # looking. Whichever figure breaches, the panel says so.
        allowance = values.get(keys[0])
        bar.headline = allowance or 0.0
        for key in keys:
            value = values.get(key)
            over_by = (value - allowance
                       if value is not None and allowance is not None
                       and value > allowance else 0.0)
            bar.parts.append({
                "key": key,
                "label": key.replace("_", " "),
                "value": value,
                "display": money(value, panel.unit),
                "over": over_by > 0,
                "over_display": f"+{money(over_by, panel.unit)} over" if over_by > 0 else "",
                "width": 0.0 if value is None else round(max((value / biggest) * plot, 1.0), 2),
            })
        bar.over = max((part["value"] or 0.0) - (allowance or 0.0)
                       for part in bar.parts[1:]) if len(keys) > 1 and allowance is not None else 0.0
        if bar.over > 0:
            bar.over_display = f"+{money(bar.over, panel.unit)}"
        chart.rows.append(bar)

    chart.totals = [
        {
            "key": key,
            "label": key.replace("_", " "),
            "display": money(sum((values.get(key) or 0.0) for _, values in parsed),
                             panel.unit),
        }
        for key in keys
    ]
    chart.unsourced = sum(1 for bar in chart.rows if bar.unsourced)
    return chart


# ---------------------------------------------------------------------------
# What the template gets
# ---------------------------------------------------------------------------

@dataclass
class Rendered:
    panel: Panel
    gantt: Gantt | None = None
    bars: Bars | None = None
    rows: list = dataclass_field(default_factory=list)
    number: str = ""
    caption: str = ""
    note: str = ""

    @property
    def kind(self) -> str:
        return self.panel.kind

    @property
    def is_empty(self) -> bool:
        if self.panel.kind == "gantt":
            return self.gantt is None or self.gantt.is_empty
        if self.panel.kind == "bars":
            return self.bars is None or self.bars.is_empty
        if self.panel.kind == "counter":
            return not self.number
        return not self.rows


def render(panel: Panel, items: list, today: _dt.date | None = None) -> Rendered:
    """One panel, filled with what is actually on disk.

    Never raises for want of data. A panel whose file nobody has written yet
    renders as "nothing here yet" with the panel's own description under it --
    an empty dashboard that explains itself is a working dashboard on day one.
    """
    if panel.kind not in KINDS:
        return Rendered(panel=panel,
                        note=f"This panel needs a newer version of the engine "
                             f"({panel.kind!r} is not a kind it can draw).")

    if panel.reads == "rows":
        rows = read_rows(items, panel)
        if panel.kind == "gantt":
            chart = build_gantt(rows, panel, today=today)
            return Rendered(panel=panel, gantt=chart,
                            note=_unsourced_note(panel, chart.unsourced,
                                                 len(chart.bars)),
                            caption=_span_caption(chart))
        if panel.kind == "bars":
            chart = build_bars(rows, panel)
            return Rendered(panel=panel, bars=chart,
                            note=_unsourced_note(panel, chart.unsourced,
                                                 len(chart.rows)))
        if panel.kind == "counter":
            key = (panel.value_keys or ("value",))[0]
            total = sum((_number(row.get(key)) or 0.0) for row in rows)
            return Rendered(panel=panel, number=money(total, panel.unit),
                            caption=f"{len(rows)} lines")
        return Rendered(panel=panel, rows=rows)

    # reads: items
    chosen = [item for item in items if _matches(item, panel.where)]
    if panel.limit:
        chosen = chosen[:panel.limit]
    if panel.kind == "counter":
        return Rendered(panel=panel, number=str(len(chosen)))
    return Rendered(panel=panel, rows=chosen)


def _unsourced_note(panel: Panel, unsourced: int, total: int) -> str:
    """What the page says about rows nobody can trace, in the spec's words.

    Written by the panel, not by the engine, because only the spec knows what
    kind of document these figures were supposed to come out of.
    """
    if not unsourced:
        return ""
    try:
        return panel.unsourced_note.format(n=unsourced, total=total)
    except (KeyError, IndexError, ValueError):
        # A spec with a broken placeholder must still tell the truth.
        return f"{unsourced} of {total} rows carry no source."


def _span_caption(chart: Gantt) -> str:
    if not chart.first or not chart.last:
        return ""
    span = f"{chart.first.strftime('%b %Y')} – {chart.last.strftime('%b %Y')}"
    if chart.late_count:
        return f"{span} · {chart.late_count} behind baseline"
    return span


def _matches(item, where: dict) -> bool:
    """Filter an item on the fields the user declared. Unknown field = no filter.

    A panel naming a field this user's schema does not have must not empty the
    page. It shows everything and the panel says the field is missing, because
    "I could not filter" is information and "no projects" is a lie.
    """
    for key, wanted in (where or {}).items():
        value = item.values.get(key)
        if value is None:
            continue
        allowed = wanted if isinstance(wanted, (list, tuple)) else [wanted]
        if str(value.display).casefold() not in {str(one).casefold() for one in allowed}:
            return False
    return True


def missing_fields(panel: Panel, schema) -> list[str]:
    """Fields a panel names that this user's schema does not have."""
    if panel.reads != "items":
        return []
    known = {field.key for field in getattr(schema, "fields", [])}
    named = set(panel.columns) | set(panel.where or {})
    return sorted(name for name in named if name not in known)
