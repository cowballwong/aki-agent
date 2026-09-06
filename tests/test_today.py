"""The Today page: the landing page the maintainer asked for on 2026-08-19.

The interesting thing about this page is not that it renders. It is that
every number on it had to come from somewhere that needs no API key -- the
promise the whole package rests on -- and that each panel says when it does
not know, because a confident zero and a quiet day look identical.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest
import yaml

from aki_agent import today
from aki_agent.dashboard import create_app


@pytest.fixture
def transcripts(tmp_path, monkeypatch) -> Path:
    """A fake Claude Code transcript folder, in the real shape."""
    home = tmp_path / "home"
    folder = home / ".claude" / "projects" / "some-project"
    folder.mkdir(parents=True)
    monkeypatch.setattr(today.paths, "home", lambda: home)
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))
    return folder


def write_turns(folder: Path, turns, name: str = "session.jsonl") -> Path:
    lines = []
    for when, tokens, model in turns:
        lines.append(json.dumps({
            "timestamp": when.isoformat().replace("+00:00", "Z"),
            # Split across the fields the real thing uses, adding up to
            # exactly `tokens` so the arithmetic in the assertions is
            # about the windows rather than about this fixture.
            "message": {"model": model, "usage": {
                "input_tokens": 0,
                "cache_creation_input_tokens": tokens // 2,
                "cache_read_input_tokens": tokens - tokens // 2,
                "output_tokens": 0,
            }},
        }))
    path = folder / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Usage, read from this machine rather than from an API


def test_the_two_windows_count_only_what_falls_in_them(transcripts):
    now = _dt.datetime(2026, 8, 19, 20, 0, tzinfo=_dt.timezone.utc)
    write_turns(transcripts, [
        (now - _dt.timedelta(hours=1), 1_000, "claude-opus-5"),
        (now - _dt.timedelta(hours=4), 1_000, "claude-opus-5"),
        (now - _dt.timedelta(days=2), 1_000, "claude-opus-5"),
        (now - _dt.timedelta(days=30), 9_999, "claude-opus-5"),
    ])

    usage = today.read_usage(now=now)

    assert usage.five_hours == 2_000
    assert usage.week == 3_000, "a month ago is not this week"


def test_a_context_bigger_than_the_window_corrects_the_window(transcripts):
    """The transcript says `claude-opus-5` for both the 200K and the 1M
    variant. Believing the name drew a full gauge on a session 45% used."""
    now = _dt.datetime(2026, 8, 19, 20, 0, tzinfo=_dt.timezone.utc)
    write_turns(transcripts, [(now, 900_000, "claude-opus-5")])

    usage = today.read_usage(now=now)

    assert usage.context_limit == 1_000_000
    assert usage.context_fraction < 1.0


def test_an_unknown_model_gets_no_percentage_rather_than_a_guess(transcripts):
    now = _dt.datetime(2026, 8, 19, 20, 0, tzinfo=_dt.timezone.utc)
    write_turns(transcripts, [(now, 5_000, "some-other-model")])

    usage = today.read_usage(now=now)

    assert usage.context_limit is None
    assert usage.context_fraction is None


def test_the_second_read_does_not_re_parse_the_whole_file(transcripts):
    """Ten seconds on the landing page is what made this incremental.

    Asserted through behaviour rather than timing: after one read, the stored
    offset is at the end of the file, so a second read has nothing to do.
    """
    now = _dt.datetime(2026, 8, 19, 20, 0, tzinfo=_dt.timezone.utc)
    path = write_turns(transcripts, [(now, 1_000, "claude-opus-5")])

    today.read_usage(now=now)
    store = json.loads(today._buckets_file().read_text(encoding="utf-8"))
    remembered = store["files"][str(path)]["offset"]

    assert remembered == path.stat().st_size

    # And new lines still land: the offset is a resume point, not a stop sign.
    write_turns(transcripts, [
        (now, 1_000, "claude-opus-5"), (now, 2_000, "claude-opus-5")])
    again = today.read_usage(now=now)

    assert again.five_hours > 1_000


def test_no_transcripts_says_so_instead_of_showing_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(today.paths, "home", lambda: tmp_path)
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    usage = today.read_usage()

    assert usage.problem, "a zero here reads as 'you have used nothing'"


# ---------------------------------------------------------------------------
# Weather, with no key


def test_the_weather_asks_for_a_town_when_none_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    weather = today.read_weather("")

    assert not weather.known
    assert "No town set" in weather.problem
    # It used to say "add `location` under `user` in your settings" -- an
    # instruction to hand-edit a YAML file, given because there was no field
    # anywhere in the dashboard to set it. There is one now, and the card
    # links to it, so the sentence is short and the way out is a click.
    assert "yaml" not in weather.problem.lower()
    assert "`" not in weather.problem, "a config key is not an instruction"


def test_a_town_name_is_enough(tmp_path, monkeypatch):
    """Open-Meteo geocodes for free, so nobody has to find coordinates."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))
    asked = []

    def fake(url, params, timeout=6.0):
        asked.append(url)
        if "geocoding" in url:
            return {"results": [{"name": "Winchester", "latitude": 51.75,
                                 "longitude": -0.33}]}
        return {"current": {"temperature_2m": 16.2, "weather_code": 3},
                "daily": {"temperature_2m_max": [22.0],
                          "temperature_2m_min": [15.0],
                          "precipitation_probability_max": [80]}}

    weather = today.read_weather("Winchester", fetcher=fake)

    assert weather.known
    assert weather.place == "Winchester"
    assert weather.description == "cloudy"
    assert weather.rain_chance == 80
    assert len(asked) == 2, "geocode, then forecast"


def test_being_offline_is_a_sentence_not_a_traceback(tmp_path, monkeypatch):
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    def explode(url, params, timeout=6.0):
        raise OSError("no network")

    weather = today.read_weather("Winchester", fetcher=explode)

    assert not weather.known
    assert "weather service" in weather.problem


# ---------------------------------------------------------------------------
# The page


@pytest.fixture
def installed(tmp_path) -> Path:
    root = tmp_path / "Assistant"
    (root / "01_Config").mkdir(parents=True)
    (root / "03_Workspace" / "01_Work" / "01_Project-1").mkdir(parents=True)

    config_path = root / "01_Config" / "config.yaml"
    config_path.write_text(yaml.safe_dump({
        "schema_version": 1,
        "assistant": {"name": "Mira"},
        "user": {"name": "Sam"},
        "layout": {"root": str(root), "workspaces": ["01_Work"],
                   "item_label": "Project", "item_label_plural": "Projects",
                   "summary_files": ["state"]},
    }), encoding="utf-8")
    return config_path


def test_the_landing_page_is_today(installed):
    app = create_app(installed)
    app.config["TESTING"] = True

    html = app.test_client().get("/").get_data(as_text=True)

    # "Last 5 hours" was here until the ring around it was removed on
    # 2026-09-04. What this test is for is that the landing page is Today
    # rather than something else, so it asks about two parts that are on it
    # whether or not this machine has any usage to draw -- the chart and its
    # caption are not, which the first attempt at this rediscovered.
    assert "Context" in html
    assert "Calendar" in html


def test_an_unconnected_calendar_still_draws_the_month(installed):
    """An unconnected calendar still draws the month."""
    app = create_app(installed)
    app.config["TESTING"] = True

    html = app.test_client().get("/").get_data(as_text=True)

    assert "No calendar connected yet" in html
    assert 'class="cal"' in html, "the empty month is the finished state"


def test_the_work_list_kept_its_own_address(installed):
    app = create_app(installed)
    app.config["TESTING"] = True

    assert app.test_client().get("/projects").status_code == 200


# ---------------------------------------------------------------------------
# The safety gate, made visible
#
# It has refused irreversible commands since it was written and kept no record
# of doing it, so it was protecting the user in a way the user could never
# see. The log came first; these are about the page that shows it.


def test_the_gate_writes_down_what_it_refused(tmp_path, monkeypatch):
    from aki_agent import safety_gate

    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    assert safety_gate.check("ls -la").allowed
    assert not safety_gate.check("rm -rf /").allowed

    written = safety_gate.recent()
    assert len(written) == 1, "only the refusal is worth a line"
    assert "rm -rf /" in written[0]["command"]
    assert written[0]["why"]


def test_a_refused_command_is_truncated_before_it_is_written(tmp_path,
                                                             monkeypatch):
    """A blocked command can carry a pasted secret, and this file is read by
    a web page."""
    from aki_agent import safety_gate

    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))
    # Straight at the writer: the block rules are anchored, so a long enough
    # command to test truncation would not be blocked at all, and the test
    # would pass by never writing anything.
    safety_gate._remember("rm -rf / " + "x" * 900, "the reason")

    assert len(safety_gate.recent()[0]["command"]) <= 300


def test_the_safety_page_shows_the_rules_and_the_record(installed, tmp_path,
                                                        monkeypatch):
    from aki_agent import safety_gate

    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "gatehome"))
    safety_gate.check("rm -rf /")

    app = create_app(installed)
    app.config["TESTING"] = True
    html = app.test_client().get("/safety").get_data(as_text=True)

    assert "refused outright" in html
    assert "rm -rf /" in html


def test_an_empty_record_does_not_claim_it_never_fired(installed, tmp_path,
                                                       monkeypatch):
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "quiet"))

    app = create_app(installed)
    app.config["TESTING"] = True
    html = app.test_client().get("/safety").get_data(as_text=True)

    assert "does not mean it has never" in html


# ---------------------------------------------------------------------------
# The update button


def test_updating_needs_the_dashboards_own_token(installed):
    app = create_app(installed)
    app.config["TESTING"] = True

    assert app.test_client().post("/update").status_code == 403


def test_updating_with_nothing_to_update_from_says_so(installed, tmp_path,
                                                      monkeypatch):
    from aki_agent import engine
    from aki_agent.dashboard import app as dashboard_app

    monkeypatch.setattr(engine, "source_for_upgrade",
                        lambda given: (None, "nothing to upgrade from"))

    app = create_app(installed)
    app.config["TESTING"] = True
    stopped = []
    app.config["PERSONAL_AGENT_STOPPER"] = lambda: stopped.append(True)

    response = app.test_client().post(
        "/update", data={"token": dashboard_app.SESSION_TOKEN})

    assert b"nothing to upgrade from" in response.data
    assert not stopped, "nothing happened, so nothing should have stopped"


# The five-hour and weekly rings were removed on 2026-09-04, and five tests
# of the weekly one went with them. The maintainer, after being shown that no
# denominator for either could be got honestly.
#
# What replaced them is in `test_the_today_strip.py`: the totals are still
# counted and still shown as figures, and the one remaining ring measures the
# session the auto-recycle actually restarts.
