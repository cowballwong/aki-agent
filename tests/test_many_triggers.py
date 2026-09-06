"""A task may be started by more than one thing.

reported 2026-08-21, looking at the Add-a-task form:



The dropdown was the symptom. The cause was that `hour`, `minute`,
`weekdays`, `every_minutes` and `watch_path` all sat flat on the task, so the
form had to show every one of them whichever kind you picked -- its own
caption read "only for the folder trigger", which is a form apologising for
its shape. The settings could not follow the choice while they belonged to
the task.

Four systems were read before deciding: Windows Task Scheduler, Home
Assistant, n8n and Zapier. The first three agree, and this file is what holds
Aki to that agreement.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from aki_agent import paths, schedule
from aki_agent.dashboard import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "configs" / "examples" / "architecture.yaml"
RUNNER = Path("/somewhere/run-task")


@pytest.fixture
def dashboard_browser(tmp_path, monkeypatch):
    """A dashboard whose task store is this test's own folder."""
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()

    app = create_app(CONFIG)
    app.config["TESTING"] = True
    with app.test_client() as browser:
        yield browser


# ---------------------------------------------------------------------------
# What several triggers mean
# ---------------------------------------------------------------------------

def test_several_triggers_read_as_or():
    """Not AND. A trigger is a moment, and two moments do not coincide.

    "Only on weekdays *and* only when the folder changed" is one trigger and
    one condition -- a different feature, deliberately not built.
    """
    task = schedule.ScheduledTask(
        key="k", title="T", why="w", prompt="p",
        triggers=(schedule.Trigger(hour=0, minute=0, weekdays=("MON",)),
                  schedule.Trigger(kind="watch", watch_path="C:/x")))

    # The watch half is worded per platform: Windows Task Scheduler has no
    # folder-watch trigger, so there it is a poll that checks the folder and
    # stops if nothing moved. The page prints what happens rather than what
    # was asked for.
    said = task.when()
    assert said.startswith("00:00, MON, or ")
    assert "C:/x" in said
    if schedule.paths.is_windows():
        assert "only if" in said, "Windows cannot watch a folder; say so"
    else:
        assert said.endswith("when C:/x changes")


def test_a_task_with_no_trigger_gets_one_rather_than_never_running():
    """A job that never runs, reported as installed, is this package's
    signature failure. It is refused at the source."""
    task = schedule.ScheduledTask(key="k", title="T", why="w", prompt="p")
    assert len(task.triggers) == 1
    assert task.triggers[0].kind == "time"


def test_two_intervals_are_refused_rather_than_written_down():
    """launchd has exactly one StartInterval per job.

    Writing a second would produce a plist that looks right, installs
    cleanly, and never fires the second one -- which is worse than being told
    no.
    """
    task = schedule.ScheduledTask(
        key="k", title="T", why="w", prompt="p",
        triggers=(schedule.Trigger(kind="interval", every_minutes=30),
                  schedule.Trigger(kind="interval", every_minutes=45)))

    assert any("only one" in problem.lower() for problem in task.problems())


def test_a_bad_trigger_is_reported_against_the_task():
    task = schedule.ScheduledTask(
        key="k", title="T", why="w", prompt="p",
        triggers=(schedule.Trigger(hour=9),
                  schedule.Trigger(kind="watch", watch_path="")))

    assert any("folder to watch" in problem for problem in task.problems())


# ---------------------------------------------------------------------------
# Both platforms carry all of them
# ---------------------------------------------------------------------------

def test_windows_gets_one_task_with_three_triggers():
    task = schedule.ScheduledTask(
        key="k", title="T", why="w", prompt="p",
        triggers=(schedule.Trigger(hour=0, minute=0, weekdays=("MON", "FRI")),
                  schedule.Trigger(kind="interval", every_minutes=15),
                  schedule.Trigger(kind="login")))
    xml = schedule.windows_task_xml(task, RUNNER)

    assert xml.count("<CalendarTrigger>") == 1
    assert xml.count("<TimeTrigger>") == 1
    assert xml.count("<LogonTrigger>") == 1
    assert "PT15M" in xml
    # One Windows task, so one row and one on/off switch.
    assert xml.count("<Task ") == 1


def test_launchd_gets_one_plist_with_all_of_them():
    task = schedule.ScheduledTask(
        key="k", title="T", why="w", prompt="p",
        triggers=(schedule.Trigger(hour=7, minute=0, weekdays=("TUE",)),
                  schedule.Trigger(hour=19, minute=30),
                  schedule.Trigger(kind="watch", watch_path="/Users/a/Docs"),
                  schedule.Trigger(kind="login")))

    parsed = plistlib.loads(
        schedule.launchd_plist(task, RUNNER).encode("utf-8"))

    times = parsed["StartCalendarInterval"]
    assert len(times) == 2
    assert times[0]["Weekday"] == 2 and times[0]["Hour"] == 7
    assert "Weekday" not in times[1] and times[1]["Hour"] == 19
    assert parsed["WatchPaths"] == ["/Users/a/Docs"]
    assert parsed["RunAtLoad"] is True


def test_a_midnight_time_survives_the_translation():
    """A midnight time survives the translation.

    Worth its own test because midnight is where zero-vs-falsy bugs live.
    """
    task = schedule.ScheduledTask(
        key="k", title="T", why="w", prompt="p",
        triggers=(schedule.Trigger(hour=0, minute=0),))

    assert task.when().startswith("00:00")
    assert "T00:00:00" in schedule.windows_task_xml(task, RUNNER)

    parsed = plistlib.loads(
        schedule.launchd_plist(task, RUNNER).encode("utf-8"))
    assert parsed["StartCalendarInterval"][0]["Hour"] == 0


# ---------------------------------------------------------------------------
# The migration, which has to be right the first time
# ---------------------------------------------------------------------------

OLD_SHAPE = {
    "key": "watch-drawings",
    "title": "Watch the drawings folder",
    "why": "so I notice new ones",
    "prompt": "tell me what changed",
    "enabled": True,
    "trigger": "watch",
    "hour": 7,
    "minute": 15,
    "weekdays": ["MON", "TUE"],
    "every_minutes": 30,
    "watch_path": "C:/Shared",
    "announce": False,
}


def test_a_file_written_before_today_still_reads():
    """Getting this wrong does not error. It empties somebody's schedule."""
    task = schedule._task_from_dict(OLD_SHAPE)

    assert len(task.triggers) == 1
    one = task.triggers[0]
    assert one.kind == "watch"
    assert one.watch_path == "C:/Shared"
    assert one.hour == 7 and one.minute == 15
    assert one.weekdays == ("MON", "TUE")
    assert task.announce is False


def test_what_is_written_now_reads_back_identical():
    task = schedule.ScheduledTask(
        key="k", title="T", why="w", prompt="p", announce=False,
        triggers=(schedule.Trigger(hour=6, minute=5, weekdays=("SAT",)),
                  schedule.Trigger(kind="login")))

    again = schedule._task_from_dict(schedule._task_to_dict(task))

    assert again.triggers == task.triggers
    assert again.announce is False
    assert again.when() == task.when()


def test_the_old_keys_are_not_written_back_out():
    """One place says when a task runs. Two would drift."""
    task = schedule.ScheduledTask(
        key="k", title="T", why="w", prompt="p",
        triggers=(schedule.Trigger(hour=6),))
    written = schedule._task_to_dict(task)

    for gone in ("trigger", "hour", "minute", "weekdays",
                 "every_minutes", "watch_path"):
        assert gone not in written, f"{gone} is the trigger's, not the task's"


@pytest.mark.parametrize("kind", schedule.TRIGGERS)
def test_every_kind_is_named_for_the_moment_not_the_mechanism(kind):
    """Home Assistant's 2026 lesson, taken deliberately.

    Their release renamed every trigger after what happens rather than how it
    is detected, because nobody scheduling their own work thinks in intervals
    and watches.
    """
    name = schedule.KIND_NAMES[kind]
    assert name[0].isupper()
    # A phrase describing a moment, not the storage key. "interval" and
    # "watch" were what a person used to be shown.
    assert name.lower() != kind
    assert len(name.split()) >= 3, f"{name} reads like a key, not a moment"


# ---------------------------------------------------------------------------
# The form and the server have to agree about what a time looks like
# ---------------------------------------------------------------------------

def test_midnight_from_the_form_stays_midnight(dashboard_browser):
    """It did not, once, and the failure was silent.

    The card posts `<input type="time">`, which sends "00:00" in one field.
    The first version split that in JavaScript just before submitting, so any
    submit that did not fire the submit event -- `form.submit()` does not --
    sent "00:00" into a number parser, which fell back to its default. The
    task saved happily and ran at nine in the morning.
    """
    from aki_agent.dashboard import app as app_module

    dashboard_browser.post("/schedule/save", data={
        "token": app_module.SESSION_TOKEN,
        "title": "Midnight sweep", "why": "x", "prompt": "y",
        "t0_kind": "time", "t0_hour": "00:00", "t0_day_MON": "on",
    })

    one = schedule.read_user_tasks()[-1].triggers[0]
    assert (one.hour, one.minute) == (0, 0)
    assert one.weekdays == ("MON",)


def test_two_cards_become_two_triggers(dashboard_browser):
    from aki_agent.dashboard import app as app_module

    dashboard_browser.post("/schedule/save", data={
        "token": app_module.SESSION_TOKEN,
        "title": "Both", "why": "x", "prompt": "y",
        "t0_kind": "time", "t0_hour": "06:30",
        "t1_kind": "watch", "t1_path": str(Path.home()),
    })

    task = schedule.read_user_tasks()[-1]
    assert [one.kind for one in task.triggers] == ["time", "watch"]
    assert task.triggers[0].hour == 6 and task.triggers[0].minute == 30


def test_the_separate_hour_and_minute_spelling_still_works(dashboard_browser):
    """Anything posting the old two-field shape must not silently drift."""
    from aki_agent.dashboard import app as app_module

    dashboard_browser.post("/schedule/save", data={
        "token": app_module.SESSION_TOKEN,
        "title": "Split", "why": "x", "prompt": "y",
        "t0_kind": "time", "t0_hour": "7", "t0_minute": "45",
    })

    one = schedule.read_user_tasks()[-1].triggers[0]
    assert (one.hour, one.minute) == (7, 45)


# ---------------------------------------------------------------------------
# Re-pointing must not be able to lose a task
# ---------------------------------------------------------------------------

def test_repointing_replaces_and_never_deletes_first():
    """An upgrade on the test laptop, 2026-08-21, came back saying
    "Re-pointed 2 scheduled task(s)" and four of his six scheduled tasks were
    gone.

    It did not recur and the reason that one install failed was never
    established. What was establishable is that `_repoint` deleted each task
    before installing its replacement -- so any failure, from any cause,
    destroyed a job the user had not asked to lose. Both platforms already
    replace in place: `schtasks /Create /F` overwrites, and the plist is
    rewritten before anything is unloaded.

    A step that can lose somebody's work when something else goes wrong is
    worth removing even without knowing what the something else was.
    """
    # Read as code. A comment explaining why the delete was removed contains
    # the very text a string search looks for -- the same trap that made an
    # earlier canary on this page fail against its own explanation.
    import ast

    source = (Path(__file__).resolve().parents[1] / "src" / "aki_agent"
              / "cli.py").read_text(encoding="utf-8")
    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_repoint")

    called = {
        f"{node.func.value.id}.{node.func.attr}"
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }

    assert "schedule.remove" not in called, (
        "re-pointing replaces a task; it must never delete one first")
    assert "schedule.install" in called


def test_the_windows_create_replaces_an_existing_task():
    """Which is what makes deleting first unnecessary."""
    command = schedule.windows_command(schedule.DEFAULT_TASKS[0],
                                       Path("C:/tmp/x.xml"))
    assert "/F" in command, "without /F, replacing would need a delete"


def test_editing_an_installed_task_reaches_the_scheduler(dashboard_browser, monkeypatch):
    """Saving used to stop at the file.

    reported 2026-08-23: his [Good morning] task was set to 8am on the page and
    kept firing at 6am. The page was reading schedule.json, which was
    correct; Windows still held the definition from when the task was first
    switched on. An edit that changes only what the screen reads is the worst
    kind of silent failure -- everything agrees with you except the machine.
    """
    from aki_agent import schedule
    from aki_agent.dashboard import app as app_module

    installed = []
    monkeypatch.setattr(schedule, "is_installed", lambda task, known=None: True)
    monkeypatch.setattr(schedule, "runner_script", lambda *a: Path(__file__))
    monkeypatch.setattr(schedule, "install",
                        lambda task, runner, confirmed=False: (
                            installed.append(task) or (True, "ok")))

    dashboard_browser.post("/schedule/save", data={
        "token": app_module.SESSION_TOKEN, "key": "good-morning",
        "title": "Good morning", "why": "x", "prompt": "y",
        "t0_kind": "time", "t0_hour": "08:00",
    })

    assert installed, "an installed task must be re-registered when edited"
    assert installed[-1].triggers[0].hour == 8


def test_saving_a_task_that_is_off_does_not_switch_it_on(dashboard_browser, monkeypatch):
    from aki_agent import schedule
    from aki_agent.dashboard import app as app_module

    installed = []
    monkeypatch.setattr(schedule, "is_installed", lambda task, known=None: False)
    monkeypatch.setattr(schedule, "install",
                        lambda task, runner, confirmed=False: (
                            installed.append(task) or (True, "ok")))

    dashboard_browser.post("/schedule/save", data={
        "token": app_module.SESSION_TOKEN, "key": "",
        "title": "Draft one", "why": "x", "prompt": "y",
        "t0_kind": "time", "t0_hour": "08:00",
    })

    assert not installed, "saving a draft must not schedule it"

