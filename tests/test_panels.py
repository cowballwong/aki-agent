"""Panels: a workspace's screen, and the promise that every figure on it is
traceable.

The tests worth having here are not "does it draw a rectangle". They are:

  * a figure with no source is never allowed to look like one that has a source
  * an overspend is reported by whichever column breaches, not only the last
  * the renderer stays profession-neutral -- the same spec draws a term plan
  * nothing raises for want of data, because half-filled folders are normal
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from aki_agent import panels
from aki_agent.dashboard import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "workspace_controls"
CONFIG = REPO_ROOT / "configs" / "examples" / "project_controls.yaml"


class FakeItem:
    """Just enough of `workspace.Item` for a panel to read."""

    def __init__(self, path: Path, title: str):
        self.path = path
        self.title = title
        self.key = path.name
        self.values: dict = {}


def _items() -> list:
    return [FakeItem(path, path.name)
            for path in sorted(FIXTURE.iterdir()) if path.is_dir()]


def _panel(key: str) -> panels.Panel:
    found = panels.by_key(key)
    assert found is not None, f"{key} is not in the shipped panel library"
    return found


# ---------------------------------------------------------------------------
# The spec
# ---------------------------------------------------------------------------

def test_the_library_ships_panels_and_they_all_declare_a_drawable_kind():
    catalogue = panels.catalogue()
    assert catalogue, "no panels found in the library"
    for panel in catalogue:
        assert panel.kind in panels.KINDS, f"{panel.key} declares {panel.kind}"


def test_a_spec_with_no_kind_is_skipped_rather_than_raising(tmp_path):
    broken = tmp_path / "half-written.md"
    broken.write_text("---\nname: half\n---\n", encoding="utf-8")
    assert panels.read_spec(broken) is None


def test_a_workspace_declares_its_panels_in_order():
    assert panels.declared_for(FIXTURE) == [
        "programme-gantt", "cost-position", "next-dates"]


def test_an_undeclared_workspace_offers_only_panels_whose_data_exists(tmp_path):
    (tmp_path / "a-project").mkdir()
    offered = panels.panels_for(tmp_path, [FakeItem(tmp_path / "a-project", "A")])
    assert offered == [], "a panel with no data behind it must not be offered"


# ---------------------------------------------------------------------------
# Traceability -- the rule the product rests on
# ---------------------------------------------------------------------------

def test_a_source_at_the_top_of_the_file_covers_every_row_in_it():
    rows = panels.read_rows(_items(), _panel("programme-gantt"))
    marlow = [row for row in rows if row.item_key == "marlow-court"]
    assert marlow and all(not row.unsourced for row in marlow)


def test_rows_with_no_source_anywhere_are_counted_not_hidden():
    panel = _panel("programme-gantt")
    chart = panels.build_gantt(panels.read_rows(_items(), panel), panel)
    # The fixture's third project deliberately carries no source at all.
    assert chart.unsourced == 3
    assert len(chart.bars) > chart.unsourced, "sourced rows are still drawn"


def test_the_unsourced_sentence_comes_from_the_spec_not_the_engine():
    panel = _panel("programme-gantt")
    shown = panels.render(panel, _items())
    assert "3 of" in shown.note
    # And a spec that says nothing gets a wording that names no trade.
    plain = panels.Panel(key="x", kind="gantt", title="x", reads="rows")
    assert "rows carry no source" in panels._unsourced_note(plain, 2, 5)


def test_a_broken_placeholder_in_a_spec_still_tells_the_truth():
    wrong = panels.Panel(key="x", kind="gantt", title="x",
                         unsourced_note="{nope} of {total}")
    assert panels._unsourced_note(wrong, 2, 5) == "2 of 5 rows carry no source."


# ---------------------------------------------------------------------------
# Programme geometry
# ---------------------------------------------------------------------------

def test_slippage_is_measured_against_the_baseline_and_flagged():
    panel = _panel("programme-gantt")
    rows = panels.read_rows(_items(), panel)
    chart = panels.build_gantt(rows, panel, today=_dt.date(2026, 8, 27))

    late = {bar.label: bar.slip_days for bar in chart.bars if bar.late}
    assert late.get("Frame and envelope") == 14
    assert late.get("Stage 3 design") == 21
    # Something finished on its baseline date is not late.
    on_time = [bar for bar in chart.bars if bar.label == "Enabling works"]
    assert on_time and not on_time[0].late


def test_every_bar_is_drawn_inside_the_chart():
    panel = _panel("programme-gantt")
    chart = panels.build_gantt(panels.read_rows(_items(), panel), panel)
    for bar in chart.bars:
        assert bar.x >= chart.label_width
        assert bar.x + bar.width <= chart.width + 0.5, bar.label


def test_a_row_that_ends_before_it_starts_is_reported_and_survives():
    panel = panels.Panel(key="x", kind="gantt", title="x", reads="rows")
    rows = [panels.Row(values={"label": "Backwards", "start": "2026-05-01",
                               "end": "2026-04-01"}, source="a note")]
    chart = panels.build_gantt(rows, panel)
    assert chart.problems and "ends before it starts" in chart.problems[0]
    assert len(chart.bars) == 1


def test_a_row_with_no_start_is_named_rather_than_silently_dropped():
    panel = panels.Panel(key="x", kind="gantt", title="x", reads="rows")
    chart = panels.build_gantt(
        [panels.Row(values={"label": "Undated"}, source="s")], panel)
    assert chart.is_empty
    assert any("Undated" in problem for problem in chart.problems)


def test_today_is_marked_only_when_it_falls_inside_the_span():
    panel = _panel("programme-gantt")
    rows = panels.read_rows(_items(), panel)
    assert panels.build_gantt(rows, panel, today=_dt.date(2026, 8, 27)).today_x
    assert panels.build_gantt(rows, panel, today=_dt.date(2030, 1, 1)).today_x is None


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------

def test_an_overspend_is_flagged_by_whichever_column_breaches():
    """The bug this test exists for.

    The first version compared only the LAST column against the allowance, so
    an order placed over budget was invisible until it had been paid --
    months later, and long after anybody could do anything about it.
    """
    panel = _panel("cost-position")
    chart = panels.build_bars(panels.read_rows(_items(), panel), panel)

    line = next(bar for bar in chart.rows if bar.label == "Frame and envelope")
    committed = next(part for part in line.parts if part["key"] == "committed")
    spent = next(part for part in line.parts if part["key"] == "spent")

    assert committed["over"], "committed exceeds budget and must say so"
    assert not spent["over"], "spent is within budget"
    assert line.over_display == "+£78,000"


def test_a_line_within_budget_carries_no_overspend_marker():
    panel = _panel("cost-position")
    chart = panels.build_bars(panels.read_rows(_items(), panel), panel)
    line = next(bar for bar in chart.rows if bar.label == "Preliminaries")
    assert not line.over_display
    assert not any(part["over"] for part in line.parts)


def test_totals_add_up_across_every_project_in_the_workspace():
    panel = _panel("cost-position")
    chart = panels.build_bars(panels.read_rows(_items(), panel), panel)
    budget = next(total for total in chart.totals if total["key"] == "budget")
    assert budget["display"] == "£4,293,000"


def test_bars_are_scaled_to_the_largest_figure_on_the_panel():
    panel = _panel("cost-position")
    chart = panels.build_bars(panels.read_rows(_items(), panel), panel)
    widest = max(part["width"] for bar in chart.rows for part in bar.parts)
    assert widest <= chart.width - chart.label_width - 12 + 0.5


# ---------------------------------------------------------------------------
# Neutrality -- the same primitives, a different trade
# ---------------------------------------------------------------------------

def test_the_same_gantt_spec_draws_something_that_is_not_a_building(tmp_path):
    """A term plan, drawn by the identical panel code.

    If this ever needs a change in `panels.py` to pass, the renderer has
    learned a profession and the design has failed.
    """
    project = tmp_path / "year-9-music"
    project.mkdir()
    (project / "programme.md").write_text(
        "---\n"
        "source: Scheme of work, September\n"
        "milestones:\n"
        "  - label: Autumn term\n"
        "    start: 2026-09-07\n"
        "    end: 2026-12-18\n"
        "  - label: Spring term\n"
        "    start: 2027-01-05\n"
        "    end: 2027-03-26\n"
        "---\n", encoding="utf-8")

    panel = _panel("programme-gantt")
    chart = panels.build_gantt(
        panels.read_rows([FakeItem(project, "Year 9 music")], panel), panel)
    assert [bar.label for bar in chart.bars] == ["Autumn term", "Spring term"]
    assert chart.unsourced == 0


def test_a_panel_naming_a_field_this_user_does_not_have_shows_everything():
    panel = panels.Panel(key="x", kind="table", title="x", reads="items",
                         where={"nonexistent": "whatever"})
    items = _items()
    assert len(panels.render(panel, items).rows) == len(items)


# ---------------------------------------------------------------------------
# On the page
# ---------------------------------------------------------------------------

@pytest.fixture
def browser(tmp_path, monkeypatch):
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "home"))
    from aki_agent import dashboard_auth
    dashboard_auth.set_pin("314159")
    app = create_app(CONFIG)
    app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["in"] = True
        yield client


def test_the_workspace_page_draws_the_chart_itself(browser):
    html = browser.get("/projects").get_data(as_text=True)

    assert 'class="gantt"' in html, "the programme is drawn, not tabulated"
    assert "Frame and envelope" in html
    assert "£78,000 over" in html, "the overspend is stated as a figure"
    assert "carry no source" in html, "untraceable rows are declared"


def test_the_chart_needs_no_network(browser):
    """Nothing on this page may depend on a CDN.

    A chart that is blank when the machine is offline is worse than a table.
    """
    html = browser.get("/projects").get_data(as_text=True)
    body = html.split('class="gantt"')[1][:4000]
    assert "http://" not in body and "https://" not in body


# ---------------------------------------------------------------------------
# A profession arrives as a plugin
# ---------------------------------------------------------------------------

def test_a_plugin_can_ship_a_panel_the_engine_has_never_heard_of(tmp_path,
                                                                monkeypatch):
    """The point of the whole exercise: a trade is installable.

    A plugin drops a `panels/` folder beside its skills, and a screen the
    engine has no code for appears.
    """
    plugin = tmp_path / "surveying"
    (plugin / "panels").mkdir(parents=True)
    (plugin / "panels" / "site-visits.md").write_text(
        "---\nname: site-visits\nkind: table\ntitle: Site visits\n"
        "reads: rows\nfile: visits.md\nrows: visits\n"
        "columns: [label, end]\n---\n", encoding="utf-8")

    monkeypatch.setattr(panels, "plugin_panels_dirs", lambda: [plugin / "panels"])
    found = panels.by_key("site-visits")
    assert found is not None and found.kind == "table"


def test_a_broken_plugin_costs_its_own_panels_and_nothing_else(monkeypatch):
    monkeypatch.setattr(panels, "plugin_panels_dirs", lambda: [Path("nowhere")])
    assert panels.by_key("programme-gantt") is not None
