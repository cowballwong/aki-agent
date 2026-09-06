"""Loops, Heartbeat, Event -- and the tab means WHEN, not whether it talks.

reported 2026-09-05, in six numbered points:

    1.
    2.
    3.
    4.
    5.
    6.

The six are one change. `work` used to mean "has something to tell you" while
the trigger beside it meant "when does it run" -- two questions filed as one,
which is why `release-held` could sit under Heartbeat and be scheduled for
08:05. Point 4 makes the tab the trigger; point 2 gives the other half of the
old meaning its own tick box.

Nothing was invented for point 2. `announce` has been on `ScheduledTask` since
2026-08-20 and `/notifications` has always read it -- it was simply never
reachable from the form, so every task anybody made arrived set to message
them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aki_agent import paths, schedule
from aki_agent.dashboard import app as app_module

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "src" / "aki_agent" / "dashboard" / "templates"
PAGE = TEMPLATES / "schedule.html"


def without_comments(text: str) -> str:
    """Jinja comments and CSS comments stripped.

    Five absence assertions in this package have been satisfied by their own
    explanatory comment. The note saying "the dropdown stood here" contains
    the words the test is looking for.
    """
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


# ---------------------------------------------------------------------------
# 4. Three tabs, and each is a way of being started
# ---------------------------------------------------------------------------

def test_there_are_three_tabs_and_each_one_is_a_trigger():
    assert list(schedule.KINDS_OF_WORK) == ["loop", "heartbeat", "event"]

    # Every trigger belongs to exactly one tab, and every tab has at least
    # one. A trigger in neither map is a task that can be built and then
    # cannot be found.
    assert set(schedule.WORK_OF_TRIGGER) == set(schedule.TRIGGERS)
    assert set(schedule.WORK_OF_TRIGGER.values()) == set(schedule.KINDS_OF_WORK)

    for tab, kinds in schedule.TRIGGERS_FOR_WORK.items():
        assert kinds, f"{tab} offers nothing"
        for kind in kinds:
            assert schedule.WORK_OF_TRIGGER[kind] == tab


def test_the_tab_is_read_off_the_trigger_and_never_stored():
    """The bug the whole restructure exists to make unsayable.

    A task could be filed as a heartbeat and scheduled for a clock time,
    because the two were separate fields and nothing compared them.
    """
    clocked = schedule.ScheduledTask(
        key="x", title="x", why="x",
        triggers=(schedule.Trigger(kind="time", hour=8, minute=5),))
    ticking = schedule.ScheduledTask(
        key="y", title="y", why="y",
        triggers=(schedule.Trigger(kind="interval", every_minutes=20),))
    waiting = schedule.ScheduledTask(
        key="z", title="z", why="z",
        triggers=(schedule.Trigger(kind="happening", event_kind="problem"),))

    assert clocked.work == "loop"
    assert ticking.work == "heartbeat"
    assert waiting.work == "event"

    # And it cannot be overridden by asking for it, because there is no
    # field to ask with.
    with pytest.raises(TypeError):
        schedule.ScheduledTask(key="w", title="w", why="w", work="heartbeat")


def test_a_stored_work_from_before_today_is_ignored(tmp_path, monkeypatch):
    """Every schedule.json on every existing install carries the old field.

    Reading it back would restore exactly the disagreement that was removed
    -- so it is written for a human reading the file and never read.
    """
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)

    from aki_agent import atomic

    atomic.write_json(schedule.user_tasks_file(), [{
        "key": "old-one", "title": "Old one", "why": "because",
        "prompt": "do a thing",
        "work": "heartbeat",                    # the stale opinion
        "triggers": [{"kind": "time", "hour": 8, "minute": 5}],
    }])

    (task,) = schedule.read_user_tasks()
    assert task.work == "loop", "the stored word won over the actual trigger"


def test_every_built_in_lands_where_it_actually_runs():
    for task in schedule.DEFAULT_TASKS:
        first = task.triggers[0].kind
        assert task.work == schedule.WORK_OF_TRIGGER[first], (
            f"{task.key} says {task.work} and is started by {first}")


# ---------------------------------------------------------------------------
# 1 and 3. Two options that had stopped meaning anything
# ---------------------------------------------------------------------------

def test_the_form_no_longer_asks_what_kind_of_work_it_is():
    """The form no longer asks what kind of work it is.

    Redundant twice: the tab had already said it, and the answer is read off
    the trigger now, so a field claiming otherwise could not be believed.
    """
    page = without_comments(PAGE.read_text(encoding="utf-8"))

    assert 'name="work"' not in page
    assert "What kind of work" not in page

    app = without_comments(
        (REPO_ROOT / "src" / "aki_agent" / "dashboard"
         / "app.py").read_text(encoding="utf-8"))
    assert 'form.get("work")' not in app


def test_the_form_no_longer_offers_to_add_a_trigger():
    """The form no longer offers to add a trigger.

    With one family per tab there is nothing left for it to offer on two of
    the three, and on Event the choice is between three shapes of the same
    question -- a field, not a list builder.
    """
    page = without_comments(PAGE.read_text(encoding="utf-8"))

    assert 'id="addtrigger"' not in page
    assert "Add trigger" not in page
    assert 'id="newkind"' not in page


def test_heartbeat_cannot_be_given_a_set_time():
    """Heartbeat cannot be given a set time.

    Not a rename. A task on a clock is a Loop now and says so, so the set
    time is not reachable from this tab at all.
    """
    assert schedule.TRIGGERS_FOR_WORK["heartbeat"] == ("interval",)
    assert "time" not in schedule.TRIGGERS_FOR_WORK["heartbeat"]
    assert schedule.KIND_NAMES["interval"] == "Every so often"


# ---------------------------------------------------------------------------
# 2. Does it reach you
# ---------------------------------------------------------------------------

def test_the_form_asks_whether_it_may_reach_you():
    page = without_comments(PAGE.read_text(encoding="utf-8"))
    assert 'name="announce"' in page
    assert 'type="checkbox"' in page


def test_an_unticked_task_is_saved_silent_and_shows_as_never(
        dashboard_client):
    """The whole point of point 2, end to end.


    -- so the test follows it as far as Notifications, not just as far as
    the file.
    """
    dashboard_client.post("/schedule/save", data={
        "token": app_module.SESSION_TOKEN,
        "title": "Quiet one", "why": "because",
        "prompt": "check something",
        "t0_kind": "interval", "t0_every": "30",
        # `announce` absent, which is what an unticked box posts
    }, follow_redirects=True)

    (made,) = [one for one in schedule.read_user_tasks()
               if one.title == "Quiet one"]
    assert made.announce is False
    assert schedule.announces(made.key) is False

    page = dashboard_client.get("/notifications").get_data(as_text=True)
    assert "Quiet one" in page


def test_a_ticked_task_is_saved_talking(dashboard_client):
    dashboard_client.post("/schedule/save", data={
        "token": app_module.SESSION_TOKEN,
        "title": "Loud one", "why": "because",
        "prompt": "check something",
        "t0_kind": "interval", "t0_every": "30",
        "announce": "on",
    }, follow_redirects=True)

    (made,) = [one for one in schedule.read_user_tasks()
               if one.title == "Loud one"]
    assert made.announce is True


def test_the_form_shows_the_tasks_own_setting_not_the_override():
    """`announces()` folds in a choice made on Notifications.

    Showing that here would mean opening a task and pressing Save silently
    rewrote a decision taken on another page.
    """
    app = (REPO_ROOT / "src" / "aki_agent" / "dashboard"
           / "app.py").read_text(encoding="utf-8")
    assert "editing_announce=editing.announce if editing else True" in app


# ---------------------------------------------------------------------------
# 6. Event
# ---------------------------------------------------------------------------

def test_every_event_kind_offered_is_one_something_actually_records():
    """An option that can be chosen and can never fire is worse than no
    option: the person who picks it concludes the feature is broken, and
    they are right.

    `events.KINDS` is the declared list and is NOT the list to check
    against -- it declares `change`, which nothing in the package has ever
    recorded. This reads the actual call sites.
    """
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "src" / "aki_agent").rglob("*.py"))

    recorded = set(re.findall(r'events\.record\(\s*"([a-z_]+)"', source))
    recorded |= set(re.findall(r'record\(\s*"([a-z_]+)"', source))

    offered = set(schedule.EVENT_KIND_NAMES) - {"any"}
    missing = offered - recorded

    assert not missing, (
        f"offered but never recorded anywhere: {sorted(missing)}")


def test_the_event_examples_ship_switched_off():
    """`cli schedule-install` installs every default whose `enabled` is
    True, and it runs at setup and again on repair. Shipping these on would
    have started three new jobs on every machine that upgraded, including
    the students'."""
    events = [one for one in schedule.DEFAULT_TASKS if one.work == "event"]

    assert len(events) >= 3, ""
    assert all(not one.enabled for one in events)


def test_a_happening_trigger_says_it_is_not_instant():
    """On both platforms, unlike the folder one.

    macOS can watch a folder natively; nothing can be woken because a line
    arrived in a log. So this is not a Windows apology, it is what the
    feature is -- and the page has to print the sentence it can deliver.
    """
    one = schedule.Trigger(kind="happening", event_kind="problem",
                           every_minutes=10)
    said = one.when()

    assert "every 10 min" in said
    assert "only if" in said
    assert "when something goes wrong" != said

    assert "happening" in schedule.trigger_caveats()
    assert "happening" in schedule.supported_triggers()


@pytest.mark.parametrize("kind", ["happening", "watch"])
def test_a_polled_trigger_never_installs_as_a_daily_calendar_entry(kind):
    """The silent-wrong-install trap, guarded on both platforms.

    Neither generator raises on a kind it does not know -- they fall through
    to the bottom branch, which is "09:00 every day". So a trigger left out
    of the poll list installs as a working task that runs at the wrong time
    for ever while the page says it is event-driven. That is exactly what
    `watch_path` did until 2026-08-23.
    """
    one = schedule.Trigger(kind=kind, every_minutes=7,
                           watch_path=r"C:\somewhere")
    task = schedule.ScheduledTask(key="k", title="T", why="w",
                                  prompt="p", triggers=(one,))

    xml = schedule._windows_trigger_xml(one)
    assert "<Repetition>" in xml and "PT7M" in xml
    assert "CalendarTrigger" not in xml

    # The Mac half is NOT the same answer for both, and saying it was would
    # have been the mistake this test is about. launchd can watch a folder
    # natively, so `watch` becomes WatchPaths there and only `happening` --
    # which nothing anywhere can hook -- falls back to a poll. What both
    # must avoid is the daily calendar entry.
    plist = schedule.launchd_plist(task, Path("/tmp/runner.py"))
    assert "StartCalendarInterval" not in plist
    if kind == "happening":
        assert "StartInterval" in plist
    else:
        assert "WatchPaths" in plist


def test_an_event_task_does_not_run_when_nothing_has_happened(
        tmp_path, monkeypatch):
    """Without this the three Event tasks would each run their prompt every
    ten minutes for ever and report "nothing to say" -- a bill, and a lie
    about what the page says they do."""
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()

    from aki_agent import events

    one = schedule.Trigger(kind="happening", event_kind="problem",
                           every_minutes=5)

    assert schedule.event_has_happened("nothing-yet", one) is False

    events.record("problem", "the roof fell in", source="test")
    assert schedule.event_has_happened("nothing-yet", one) is True

    # And it does not fire twice for the same one.
    assert schedule.event_has_happened("nothing-yet", one) is False


def test_an_event_task_ignores_the_kinds_it_did_not_ask_for(
        tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()

    from aki_agent import events

    one = schedule.Trigger(kind="happening", event_kind="problem")

    events.record("note", "just thinking out loud", source="test")
    assert schedule.event_has_happened("picky", one) is False

    events.record("problem", "actually broken", source="test")
    assert schedule.event_has_happened("picky", one) is True


def test_the_words_a_user_wrote_narrow_it_further(tmp_path, monkeypatch):
    """ -- free text, matched without
    case, no syntax to learn."""
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()

    from aki_agent import events

    one = schedule.Trigger(kind="happening", event_kind="problem",
                           match="Drawing")

    events.record("problem", "the invoice failed to send", source="test")
    assert schedule.event_has_happened("words", one) is False

    events.record("problem", "the drawing folder is unreadable", source="test")
    assert schedule.event_has_happened("words", one) is True


# ---------------------------------------------------------------------------
# The form as a sheet -- the maintainer's follow-up the same evening
# ---------------------------------------------------------------------------

def test_the_form_is_a_dialog_opened_by_the_address(dashboard_client):
    """The form is a dialog opened by the address.

    Opened by a LINK rather than by script, so Add, Edit and Custom all
    still work with JavaScript switched off -- which a dialog opened by
    `showModal()` alone would quietly have cost. The script only upgrades an
    already-open dialog to a modal one.
    """
    page = without_comments(PAGE.read_text(encoding="utf-8"))
    assert '<dialog id="taskform"' in page
    assert "{{ 'open' if showing_form }}" in page

    shut = dashboard_client.get("/schedule?tab=loop").get_data(as_text=True)
    opened = dashboard_client.get(
        "/schedule?tab=loop&add=1").get_data(as_text=True)

    assert '<dialog id="taskform" class="sheet" >' in shut or \
           'id="taskform" class="sheet" >' in shut
    assert "open>" in opened


def test_opening_a_task_shows_the_tab_that_task_actually_uses(
        dashboard_client):
    """A mismatch here is not cosmetic.

    The form draws whichever trigger the tab owns, so opening an Event task
    on Loops would render time fields and saving would silently replace its
    trigger with 09:00 daily. The address is not trusted for this.
    """
    page = dashboard_client.get(
        "/schedule?custom=on-problem").get_data(as_text=True)

    assert 'id="eventkind"' in page, "an Event task opened on another tab"
    assert 'value="happening"' in page


def test_saving_lands_back_on_the_tab_the_task_belongs_to(dashboard_client):
    """Without this, saving a Heartbeat dropped you on Loops and the task
    looked as though it had not saved."""
    answer = dashboard_client.post("/schedule/save", data={
        "token": app_module.SESSION_TOKEN,
        "title": "Ticker", "why": "because", "prompt": "tick",
        "t0_kind": "interval", "t0_every": "15", "announce": "on",
    })

    assert answer.status_code == 302
    assert "tab=heartbeat" in answer.headers["Location"]
