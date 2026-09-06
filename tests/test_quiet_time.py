"""Quiet Time: named windows, and which task obeys which.

reported 2026-08-21:



One quiet window for everything was one answer to a question people ask
several times. The morning summary and the folder-watcher do not deserve the
same silence, and a weekend is not a weekday.

The rule that does not change: quiet stops the message, never the work.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from aki_agent import paths, quiet, schedule
from aki_agent.dashboard import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "configs" / "examples" / "architecture.yaml"

FRIDAY_NIGHT = dt.datetime(2026, 8, 21, 23, 30)
SATURDAY_1AM = dt.datetime(2026, 8, 22, 1, 0)
MONDAY_NOON = dt.datetime(2026, 8, 24, 12, 0)


@pytest.fixture(autouse=True)
def own_state(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


@pytest.fixture
def browser():
    app = create_app(CONFIG)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def token() -> str:
    from aki_agent.dashboard import app as app_module

    return app_module.SESSION_TOKEN


# ---------------------------------------------------------------------------
# When a window holds
# ---------------------------------------------------------------------------

def test_a_night_window_crosses_midnight():
    """22:00 to 07:00 is "after 22 OR before 7", never "after 22 AND before 7".

    Written out because the naive reading is silently never quiet at all --
    the kind of bug whose only symptom is a phone that buzzes at 3am and a
    setting that looks correct.
    """
    daily = quiet.get_mode("daily")
    assert daily.holds(FRIDAY_NIGHT)
    assert daily.holds(SATURDAY_1AM)
    assert not daily.holds(MONDAY_NOON)


def test_one_in_the_morning_belongs_to_the_night_before():
    """A Friday-night window has to cover Saturday 01:00.

    Otherwise "quiet on Friday night" stops at midnight, which is the half of
    Friday night nobody means.
    """
    friday_night = quiet.Mode(key="f", name="Friday night",
                              start="22:00", end="07:00", days=("FRI",))
    assert friday_night.holds(SATURDAY_1AM)
    assert not friday_night.holds(dt.datetime(2026, 8, 23, 1, 0))   # Sunday


def test_the_same_time_twice_means_all_day():
    """Not "never", which is what a naive start<now<end would answer."""
    weekend = quiet.get_mode("weekend")
    assert weekend.start == weekend.end
    assert weekend.holds(SATURDAY_1AM)
    assert weekend.holds(dt.datetime(2026, 8, 22, 14, 0))
    assert not weekend.holds(MONDAY_NOON)


# ---------------------------------------------------------------------------
# Modes as data
# ---------------------------------------------------------------------------

def test_a_shipped_mode_can_be_adjusted_without_being_replaced():
    """Its window is the user's; its name is not.

    Tasks point at the key and a person points at the word. Renaming "Daily"
    would leave every assignment reading as something it is not.
    """
    quiet.save_built_in(quiet.Mode(key="daily", name="ignored",
                                   start="23:00", end="06:00",
                                   days=("MON", "TUE")))
    again = quiet.get_mode("daily")
    assert again.name == "Daily"
    assert again.built_in is True
    assert again.when() == "23:00 to 06:00, MON, TUE"


def test_adding_a_mode_does_not_lose_an_adjusted_shipped_one():
    """Both live in one file; rewriting it from the merged list drops one."""
    quiet.save_built_in(quiet.Mode(key="daily", name="Daily",
                                   start="23:00", end="06:00"))
    quiet.save_mode(quiet.Mode(key="", name="School run",
                               start="09:00", end="15:00", days=("MON",)))

    assert quiet.get_mode("daily").start == "23:00"
    assert quiet.get_mode("school-run").name == "School run"


def test_a_shipped_mode_cannot_be_deleted():
    assert quiet.delete_mode("daily") is False
    assert quiet.get_mode("daily") is not None


def test_deleting_a_mode_frees_the_tasks_that_used_it():
    """A task pointing at a mode that no longer exists is a task that goes
    silent for a reason nothing on screen can explain."""
    quiet.save_mode(quiet.Mode(key="", name="School run", start="09:00",
                               end="15:00"))
    quiet.assign("morning-summary", "school-run")
    assert quiet.mode_for("morning-summary") == "school-run"

    quiet.delete_mode("school-run")
    assert quiet.mode_for("morning-summary") == quiet.ALWAYS


def test_a_task_nobody_has_decided_about_reaches_you():
    """Silence has to be chosen. A default of quiet is a message that never
    arrives and never explains why."""
    assert quiet.mode_for("morning-summary") == quiet.ALWAYS
    assert quiet.holds_for("morning-summary", FRIDAY_NIGHT) is False


def test_assigning_a_mode_holds_that_task_and_only_that_task():
    quiet.assign("morning-summary", "daily")

    assert quiet.holds_for("morning-summary", FRIDAY_NIGHT) is True
    assert quiet.holds_for("morning-summary", MONDAY_NOON) is False
    assert quiet.holds_for("evening-wrapup", FRIDAY_NIGHT) is False


# ---------------------------------------------------------------------------
# What the gate does with it
# ---------------------------------------------------------------------------

def test_the_gate_holds_a_task_by_its_own_mode():
    from aki_agent import config as config_module, notify

    loaded = config_module.load(CONFIG)
    loaded.notifications.quiet_hours = None      # no global window at all
    quiet.assign("morning-summary", "daily")

    held = notify.decide(
        _message("the summary", origin="task:morning-summary"),
        loaded, "file", now=FRIDAY_NIGHT,
        mode=quiet.get_mode("daily"))
    assert held.deliver is False
    assert "Daily" in held.reason

    through = notify.decide(
        _message("the summary", origin="task:morning-summary"),
        loaded, "file", now=MONDAY_NOON, mode=quiet.get_mode("daily"))
    assert through.deliver is True


def test_always_beats_the_global_quiet_window():
    """"Always tell me" has to mean it, or it is just another maybe."""
    from aki_agent import config as config_module, notify

    loaded = config_module.load(CONFIG)
    loaded.notifications.quiet_hours = ("22:00", "07:00")

    decision = notify.decide(
        _message("wake up", origin="task:morning-summary"),
        loaded, "file", now=FRIDAY_NIGHT,
        mode=quiet.Mode(key=quiet.ALWAYS, name="always", start="", end=""))
    assert decision.deliver is True


def test_a_message_that_is_not_a_task_still_obeys_the_global_window():
    from aki_agent import config as config_module, notify

    loaded = config_module.load(CONFIG)
    loaded.notifications.quiet_hours = ("22:00", "07:00")

    decision = notify.decide(_message("hello", origin="chat"),
                             loaded, "file", now=FRIDAY_NIGHT)
    assert decision.deliver is False


def test_quiet_holds_the_message_and_never_the_work():
    """The one rule that does not move. Held, then delivered -- never lost."""
    from aki_agent import config as config_module, notify

    loaded = config_module.load(CONFIG)
    quiet.assign("morning-summary", "daily")

    notify.send("the summary", loaded, "file",
                origin="task:morning-summary", now=FRIDAY_NIGHT)

    held = notify.read_held()
    assert any("the summary" in one.get("text", "") for one in held), (
        "a held message must be in the queue, not gone")


def _message(text: str, origin: str):
    from aki_agent.channels import Message

    return Message(text=text, origin=origin)


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

def test_the_notifications_page_asks_the_question_schedule_used_to(browser):
    page = browser.get("/notifications").get_data(as_text=True)

    assert "Quiet Time" in page
    assert "Daily" in page and "Weekend" in page
    # every task, so a decision can be made about each
    for task in schedule.DEFAULT_TASKS:
        assert task.title in page


def test_choosing_never_keeps_it_in_the_log(browser):
    browser.post("/notifications/assign",
                 data={"token": token(), "key": "morning-summary",
                       "mode": "never"})

    assert schedule.announces("morning-summary") is False
    assert quiet.mode_for("morning-summary") == quiet.ALWAYS


def test_choosing_a_mode_switches_it_back_on(browser):
    browser.post("/notifications/assign",
                 data={"token": token(), "key": "morning-summary",
                       "mode": "never"})
    browser.post("/notifications/assign",
                 data={"token": token(), "key": "morning-summary",
                       "mode": "daily"})

    assert schedule.announces("morning-summary") is True
    assert quiet.mode_for("morning-summary") == "daily"


def test_a_mode_can_be_made_from_the_page(browser):
    browser.post("/notifications/mode",
                 data={"token": token(), "key": "", "name": "School run",
                       "start": "08:30", "end": "09:15",
                       "day_MON": "on", "day_TUE": "on"})

    made = quiet.get_mode("school-run")
    assert made is not None
    assert made.when() == "08:30 to 09:15, MON, TUE"


# ---------------------------------------------------------------------------
# What a ticked box means
# ---------------------------------------------------------------------------

def test_ticked_days_are_the_days_it_applies():
    """Ticked days are the days it applies.

    It used to be that an empty list meant every day, so the *unticked* state
    carried the broadest meaning. Seven empty boxes read as "no days" to
    everybody who is not the person who wrote it.
    """
    weekdays_only = quiet.Mode(key="w", name="W", start="09:00", end="17:00",
                               days=("MON", "TUE", "WED", "THU", "FRI"))
    assert weekdays_only.holds(dt.datetime(2026, 8, 24, 10, 0))    # Monday
    assert not weekdays_only.holds(dt.datetime(2026, 8, 22, 10, 0))  # Saturday


def test_a_mode_with_no_day_ticked_does_nothing_and_says_so():
    empty = quiet.Mode(key="n", name="N", start="09:00", end="10:00", days=())

    assert not empty.holds(dt.datetime(2026, 8, 24, 9, 30))
    assert any("never applies" in problem for problem in empty.problems())
    assert "never" in empty.when()


def test_a_file_written_under_the_old_rule_keeps_its_quiet_hours():
    """An empty day list used to mean every day.

    Reading it as "no day" would switch off somebody's quiet hours during an
    upgrade, without a word on screen. That is the failure this whole package
    is written against.
    """
    old = {"key": "x", "name": "X", "start": "22:00", "end": "07:00"}
    migrated = quiet.Mode.from_dict(old)

    assert migrated.days == quiet.WEEKDAYS
    assert migrated.holds(dt.datetime(2026, 8, 24, 23, 30))


def test_the_shipped_daily_mode_ticks_every_day():
    daily = quiet.get_mode("daily")
    assert set(daily.days) == set(quiet.WEEKDAYS)
    assert daily.when().endswith("every day")

