"""Scheduling, including the half that cannot be run on this machine.

THE POINT OF THIS FILE
----------------------
The translation from a task definition to a native scheduler entry is written
as a **pure function** on both platforms, so it can be tested anywhere.

That is not a stylistic preference. There is no Mac available to this project.
Writing the launchd half as a pure function is the only way to have any
confidence in it at all — the alternative is code nobody has ever exercised.

It is still not the same as running it. What these tests prove is that the
plist is well-formed, complete, user-scope and correct in its weekday mapping.
What they cannot prove is that launchd accepts it. That gap is real, and is
written down in docs/STATUS.md rather than papered over.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from aki_agent import paths, schedule

RUNNER = Path("/somewhere/run-task")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    yield


# ---------------------------------------------------------------------------
# The default set
# ---------------------------------------------------------------------------

def test_the_default_set_is_small_enough_to_hold_in_your_head():
    """The source system accumulated 43 scheduled tasks.

    Nobody audits 43 tasks. When one silently stops, nobody notices.

    A ceiling, not a fixed number. Seven since 2026-08-23, when the Me time
    watch was built -- the half of that feature that had never existed. What
    is being guarded is that the set stays readable in one sitting, and an
    exact count only asserts that today's list is today's list.

    TWO CEILINGS SINCE 2026-09-05, and the split is the point of the guard
    rather than a way around it. The harm being prevented is jobs firing on
    somebody's machine that nobody chose and nobody audits -- and a task that
    ships `enabled=False` fires nothing. It is a worked example on a page,
    which costs a paragraph of reading once.

    So the tight ceiling counts what actually runs, and a looser one keeps
    the list itself readable. Raising the first should feel expensive; that
    is the number the original 43 were.
    """
    running = [one for one in schedule.DEFAULT_TASKS if one.enabled]

    assert len(running) <= 8, (
        "too many tasks start themselves on a fresh install")
    assert len(schedule.DEFAULT_TASKS) <= 12, (
        "the list itself has stopped being readable in one sitting")


def test_a_task_that_ships_switched_off_is_never_auto_installed():
    """The guard that makes the split above honest.

    `cli schedule-install` walks `DEFAULT_TASKS` and installs everything
    whose `enabled` is True. It runs at setup and again on repair, so an
    Event example added with the default value would have switched itself on
    for every existing install -- including the students' -- as a side effect
    of upgrading. Adding a capability must not be the same act as starting it
    on somebody else's machine.
    """
    from aki_agent import schedule as sched

    examples = [one for one in sched.DEFAULT_TASKS
                if one.work == "event"]

    assert examples, "the Event tab ships with nothing to read"
    for one in examples:
        assert not one.enabled, (
            f"{one.key} would start itself on every machine that upgrades")


def test_every_default_task_explains_itself():
    """`why` is shown to the user before anything is installed."""
    for task in schedule.DEFAULT_TASKS:
        assert task.why, f"{task.key} does not say why it exists"
        assert task.title
        assert task.triggers, f"{task.key} has nothing to start it"
        for one in task.triggers:
            assert not one.problems(), f"{task.key}: {one.problems()}"


def test_triggers_ship_with_the_tools():
    """A tool is not automation.

    The source system's recycle mechanism worked for weeks while nothing ever
    triggered it. Shipping a default set is the correction.
    """
    assert schedule.DEFAULT_TASKS, "no default schedule ships at all"
    assert any(task.enabled for task in schedule.DEFAULT_TASKS)


def test_the_install_description_is_written_for_a_person():
    text = schedule.describe_install()
    assert "as you" in text
    assert "administrator" in text
    for task in schedule.DEFAULT_TASKS:
        if task.enabled:
            assert task.title in text


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

def test_windows_tasks_are_user_scope():
    """Never SYSTEM, never HighestAvailable -- both need elevation.

    And elevation is not a theoretical worry: a task registered with a raised
    run level can only be changed by an administrator, which on 2026-08-21
    left every built-in task impossible to switch off from the dashboard.
    """
    for task in schedule.DEFAULT_TASKS:
        xml = schedule.windows_task_xml(task, RUNNER)
        assert "<RunLevel>LeastPrivilege</RunLevel>" in xml
        assert "<LogonType>InteractiveToken</LogonType>" in xml
        assert "SYSTEM" not in xml
        assert "HighestAvailable" not in xml


def test_the_xml_carries_the_right_time_and_days():
    task = schedule.ScheduledTask(
        key="test", title="Test", why="testing",
        triggers=(schedule.Trigger(hour=7, minute=45,
                                   weekdays=("MON", "WED")),))
    xml = schedule.windows_task_xml(task, RUNNER)

    assert "T07:45:00" in xml
    assert "<ScheduleByWeek>" in xml
    assert "<Monday/>" in xml and "<Wednesday/>" in xml
    assert "<Tuesday/>" not in xml


def test_a_daily_task_is_daily_not_weekly():
    task = schedule.ScheduledTask(
        key="d", title="D", why="w",
        triggers=(schedule.Trigger(hour=9),))
    xml = schedule.windows_task_xml(task, RUNNER)
    assert "<ScheduleByDay>" in xml
    assert "<ScheduleByWeek>" not in xml


def test_several_triggers_become_several_windows_triggers():
    """The reason the command line had to go.

    `schtasks /Create /SC ...` says exactly one trigger. Windows itself has
    taken many per task for twenty years; only the command line could not
    describe it.
    """
    task = schedule.ScheduledTask(
        key="many", title="Many", why="w",
        triggers=(
            schedule.Trigger(hour=0, minute=0, weekdays=("MON",)),
            schedule.Trigger(hour=18, minute=30),
            schedule.Trigger(kind="login"),
        ))
    xml = schedule.windows_task_xml(task, RUNNER)

    assert xml.count("<CalendarTrigger>") == 2
    assert xml.count("<LogonTrigger>") == 1
    assert "T00:00:00" in xml and "T18:30:00" in xml
    # and it is still ONE Windows task, so the on/off switch stays one switch
    assert xml.count("<Actions") == 1


def test_the_command_just_registers_the_file():
    task = schedule.DEFAULT_TASKS[0]
    command = schedule.windows_command(task, Path("C:/tmp/x.xml"))
    assert command[:3] == ["schtasks", "/Create", "/TN"]
    assert "/XML" in command
    assert "/F" in command


def test_every_task_name_is_prefixed():
    """Listing and removing must never touch somebody else's scheduled work."""
    for task in schedule.DEFAULT_TASKS:
        assert task.task_name.startswith(schedule.TASK_PREFIX)


# ---------------------------------------------------------------------------
# macOS — tested without a Mac
# ---------------------------------------------------------------------------

def test_launchd_plist_is_valid_property_list():
    """Parsed with the standard library's own plist reader.

    If `plistlib` can read it, the file is at least structurally what launchd
    expects, which is the strongest check available without the platform.
    """
    for task in schedule.DEFAULT_TASKS:
        text = schedule.launchd_plist(task, RUNNER)
        parsed = plistlib.loads(text.encode("utf-8"))

        assert parsed["Label"] == task.label
        assert parsed["ProgramArguments"][0] == str(RUNNER)
        assert parsed["ProgramArguments"][1] == task.key


def test_launchd_weekday_numbers_are_right():
    """launchd counts weekdays 0-6 with Sunday as 0.

    Getting this wrong produces a task that runs on the wrong day, which is
    the kind of bug that takes a week to even notice.
    """
    task = schedule.ScheduledTask(
        key="test", title="Test", why="testing",
        triggers=(schedule.Trigger(hour=6, minute=15,
                                   weekdays=("MON", "FRI", "SUN")),))

    parsed = plistlib.loads(
        schedule.launchd_plist(task, RUNNER).encode("utf-8"))
    intervals = parsed["StartCalendarInterval"]

    assert {entry["Weekday"] for entry in intervals} == {1, 5, 0}
    assert all(entry["Hour"] == 6 for entry in intervals)
    assert all(entry["Minute"] == 15 for entry in intervals)


def test_a_daily_launchd_task_has_no_weekday_key():
    task = schedule.ScheduledTask(
        key="d", title="D", why="w",
        triggers=(schedule.Trigger(hour=9, minute=30),))
    parsed = plistlib.loads(
        schedule.launchd_plist(task, RUNNER).encode("utf-8"))
    interval = parsed["StartCalendarInterval"]

    # An array of one, not a bare dict: the same code path has to be able to
    # hold several times, and launchd reads either.
    assert isinstance(interval, list) and len(interval) == 1
    assert "Weekday" not in interval[0]
    assert interval[0]["Hour"] == 9
    assert interval[0]["Minute"] == 30


def test_launchd_agents_go_in_the_user_folder_never_the_system_one():
    """LaunchAgents is user scope. LaunchDaemons would need root."""
    for task in schedule.DEFAULT_TASKS:
        path = schedule.launchd_plist_path(task)
        assert "LaunchAgents" in str(path)
        assert "LaunchDaemons" not in str(path)
        assert str(path).startswith(str(paths.home()))


def test_plist_escapes_values_that_would_break_the_xml():
    """A path containing an ampersand must not produce invalid XML.

    Note `PurePosixPath` rather than `Path`. This test ran on Windows, where
    `str(Path("/Users/a & b/run"))` comes back with backslashes, because
    `Path` normalises separators for whatever platform it is on.

    That is worth knowing rather than working around silently: generating a
    macOS plist *on Windows* would produce Windows separators. It does not
    happen in practice — you generate the plist on the Mac you are installing
    on — but the assumption is now written down instead of being a surprise
    for whoever first tries to cross-generate.
    """
    from pathlib import PurePosixPath

    task = schedule.ScheduledTask(
        key="t", title="T", why="w",
        triggers=(schedule.Trigger(hour=1),))
    text = schedule.launchd_plist(task, PurePosixPath("/Users/a & b/run"))

    parsed = plistlib.loads(text.encode("utf-8"))
    assert parsed["ProgramArguments"][0] == "/Users/a & b/run"


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------

def test_nothing_is_scheduled_without_confirmation():
    ok, message = schedule.install(schedule.DEFAULT_TASKS[0], RUNNER,
                                   confirmed=False)
    assert ok is False
    assert "confirmed" in message.lower()


# ---------------------------------------------------------------------------
# Which tasks are allowed to interrupt (reported 2026-08-20)
# ---------------------------------------------------------------------------

def test_housekeeping_is_quiet_and_the_summaries_are_not():
    """The default is per task, not global: a morning summary exists to be
    read, and a checkpoint doing its job correctly is one nobody should ever
    hear from."""
    assert schedule.announces("morning-summary")
    assert schedule.announces("evening-wrapup")
    assert not schedule.announces("checkpoint")


def test_the_user_can_change_their_mind_either_way(tmp_path, monkeypatch):
    from aki_agent import paths as paths_module

    monkeypatch.setattr(paths_module, "app_dir", lambda: tmp_path)

    schedule.set_announce("morning-summary", False)
    assert not schedule.announces("morning-summary")

    schedule.set_announce("checkpoint", True)
    assert schedule.announces("checkpoint")


def test_only_differences_are_stored(tmp_path, monkeypatch):
    """So a default improved in a later release still reaches everybody who
    never had an opinion about it."""
    from aki_agent import paths as paths_module

    monkeypatch.setattr(paths_module, "app_dir", lambda: tmp_path)

    schedule.set_announce("weekly-tidy", False)

    assert set(schedule.announce_overrides()) == {"weekly-tidy"}


def test_a_quiet_task_still_runs(tmp_path, monkeypatch):
    """Quiet is not off. It still runs, still writes to the day's log, still
    appears on the events feed — it just stops reaching a phone."""
    from aki_agent import channels, config as config_module
    from aki_agent import paths as paths_module, runner, tasks

    monkeypatch.setattr(paths_module, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(tasks.config_module, "load",
                        lambda: config_module.Config())

    ran = []
    monkeypatch.setattr(runner, "run",
                        lambda *a, **k: ran.append(1) or _Anything())
    monkeypatch.setattr(channels, "best",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("a quiet task must not ask for the "
                                           "user's channel")))

    schedule.set_announce("weekly-tidy", False)
    outcome = tasks.run_one("weekly-tidy")

    assert ran, "it still runs"
    assert outcome.ok


class _Anything:
    ok = True
    output = "something worth saying"
    seconds = 1.0

    def summary(self):
        return "done"


# ---------------------------------------------------------------------------
# One answer to "is it installed" (2026-08-20)
# ---------------------------------------------------------------------------

def test_a_task_is_recognised_by_the_name_the_scheduler_uses():
    """`installed_names()` returns `aki-agent-morning-summary`; a task's `key`
    is `morning-summary`. Comparing those never matches — which is why every
    upgrade reported "Re-pointed 0 scheduled task(s)" and `doctor` said
    "6 installed, 6 not" in the same breath."""
    task = schedule.get_task("morning-summary")

    assert schedule.is_installed(task, [task.task_name])
    assert not schedule.is_installed(task, [])


def test_the_bare_key_is_accepted_too():
    """Older installs recorded it that way. Accepting both costs nothing and
    an upgrade that silently skips somebody's tasks costs a lot."""
    task = schedule.get_task("morning-summary")
    assert schedule.is_installed(task, [task.key])


def test_another_task_does_not_count_as_this_one():
    task = schedule.get_task("morning-summary")
    other = schedule.get_task("weekly-tidy")

    assert not schedule.is_installed(task, [other.task_name])


def test_repoint_and_doctor_and_the_page_all_ask_the_same_function():
    """Three hand-written copies of one comparison was three chances to get it
    wrong, and two of them were taken."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "aki_agent"
    for name in ("cli.py", "doctor.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "is_installed(" in text, f"{name} should ask"
        assert "task.key not in set(installed)" not in text
        assert "task.key not in installed" not in text

    page = (root / "dashboard" / "templates" / "schedule.html").read_text(
        encoding="utf-8")
    assert "task.task_name in installed" not in page
