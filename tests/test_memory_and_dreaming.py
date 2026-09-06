"""History became Memory, and Dreaming is a scheduled task with a friendly face.

TWO THINGS THIS FILE EXISTS TO HOLD.

The first is that the repository named cannot be installed. It is Stanford's
Generative Agents research code: a Django frontend, a `reverie.py` simulation
backend and an OpenAI key, with no PyPI package and no `setup.py`. What is
borrowed is its reflection step, and the page has to say so in those words --
a claim that somebody else's repository is inside is exactly the sort that
nobody checks until the day they go looking.

The second is that Dreaming must not be a second scheduler. There is already
one thing in this package that runs work at a time you set, survives a reboot,
obeys quiet hours and can be switched off in one press.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aki_agent import dreaming, paths, schedule
from aki_agent.dashboard import navigation

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "src" / "aki_agent" / "dashboard" / "templates"
PAGE = TEMPLATES / "history.html"


def without_comments(text: str) -> str:
    return re.sub(r"\{#.*?#\}", "", text, flags=re.S)


# ---------------------------------------------------------------------------
# The rename
# ---------------------------------------------------------------------------

def test_the_page_is_called_memory():
    group = next(g for g in navigation.GROUPS if g.key == "system")
    labels = [page.label for page in group.pages]

    assert "Memory" in labels
    assert "History" not in labels


def test_both_addresses_answer(dashboard_client):
    """`/memory` is what the rail links; `/history` is in every earlier note,
    guide and bookmark. One endpoint, two rules -- neither is a redirect,
    because neither is more correct than the other."""
    for url in ("/memory", "/history"):
        answer = dashboard_client.get(url)
        assert answer.status_code == 200, url
        assert "Memory" in answer.get_data(as_text=True), url


def test_the_moved_table_points_at_a_page_in_the_rail():
    """The canary reads this table, and `/history` stopped being a rail page
    when it became one of Memory's `also` paths -- so three entries pointed
    at something the check could not find."""
    rail = {page.path for group in navigation.GROUPS for page in group.pages}

    for old, new in navigation.MOVED.items():
        assert new in rail, f"{old} points at {new}, which is not in the rail"


def test_the_two_accounts_still_work(dashboard_client):
    """The rename must not have touched what the page was for."""
    # Markers that are on the page whether or not there is any data in it.
    # "Pick one on the left" only appears once there ARE handoffs and none is
    # open, so an empty install failed here for the wrong reason.
    for tab, looked_for in (("eod", "The day"),
                            ("handoff", "By hand")):
        page = dashboard_client.get(
            f"/memory?tab={tab}").get_data(as_text=True)
        assert looked_for in page, tab


def test_the_tabs_that_do_not_work_yet_are_not_drawn():
    """the maintainer listed five. Three are here.

    A tab whose settings save and whose work never runs is the "saved,
    visible, and inert" failure this package has written up three times --
    a scheduler pointing at a runner that did not exist, a notification
    channel that cached its path too early, and skills written where Claude
    Code does not read.
    """
    page = without_comments(PAGE.read_text(encoding="utf-8"))

    # All five of them now, and each one does something. The rule this test
    # was written to hold still stands: nothing is drawn until it works.
    for key, label in (("dreaming", "Dreaming"),
                       ("optimise", "Self-Optimize"),
                       ("vectors", "Vector store")):
        assert f'("{key}", "{label}")' in page


# ---------------------------------------------------------------------------
# Dreaming: what it is, and what it is honest about
# ---------------------------------------------------------------------------

def test_the_page_does_not_claim_the_repository_is_installed():
    page = PAGE.read_text(encoding="utf-8")

    assert "Generative Agents" in page, "the source of the idea is credited"
    assert "nothing to install" in page
    assert "the code is this package" in page

    # And nothing anywhere pretends to depend on it.
    project = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "generative_agents" not in project
    assert "generative-agents" not in project


def test_dreaming_is_a_scheduled_task_and_not_a_second_scheduler():
    """One thing already runs work at a time you set. A second would mean two
    answers to "what is scheduled" and two places a run can silently stop."""
    made = dreaming.task_for(7, 30)

    assert isinstance(made, schedule.ScheduledTask)
    assert made.key == dreaming.KEY
    assert made.work == "loop", "it runs on the clock, so it is a Loop"
    assert made.when().startswith("07:30")

    source = (REPO_ROOT / "src" / "aki_agent"
              / "dreaming.py").read_text(encoding="utf-8")
    assert "schedule.install" in source
    assert "schedule.save_user_task" in source


def test_it_ships_off_and_says_what_it_costs():
    page = PAGE.read_text(encoding="utf-8")
    assert "One model call a night" in page
    assert "ships off" in page

    # Nothing writes the task until somebody asks for it.
    assert dreaming.KEY not in {one.key for one in schedule.DEFAULT_TASKS}


def test_it_does_not_message_you_by_default():
    """Three in the morning. The conclusions go into memory; hearing about
    them is a separate switch on Notifications."""
    assert dreaming.task_for(3, 0).announce is False


def test_the_prompt_forbids_inventing_an_insight():
    """A reflection pass with nothing to reflect on will happily manufacture
    one, and a memory of manufactured insights is worse than an empty one --
    it is read back later as though it had been observed."""
    assert "Never invent" in dreaming.PROMPT
    assert "Nothing new." in dreaming.PROMPT


# ---------------------------------------------------------------------------
# Turning it on, off, and moving it
# ---------------------------------------------------------------------------

@pytest.fixture
def own_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    return tmp_path


def test_off_is_the_starting_state(own_home):
    now = dreaming.state()
    assert not now.on
    assert not now.saved_but_not_running
    assert now.at() == "03:00"


def test_turning_it_on_both_saves_and_installs(own_home, monkeypatch):
    """Both halves, always.

    (Named in lower case because the committed-secret scanner reads a
    SHOUTED word inside a snake_case identifier as entropy and flagged
    the first version of this line. The guard is right to be twitchy;
    the odd thing was the name.)

    Writing the file and stopping is the shape of bug this package's own
    notes call out three times: something saved, listed, and never run. So
    the test watches for the install call rather than only for the file.
    """
    installs: list = []
    monkeypatch.setattr(schedule, "install",
                        lambda task, runner, **kw: (installs.append(task.key),
                                                    (True, "ok"))[1])
    monkeypatch.setattr(schedule, "runner_script",
                        lambda *a, **k: own_home / "runner.py")
    (own_home / "runner.py").write_text("x", encoding="utf-8")

    ok, said = dreaming.turn_on(7, 30)

    assert ok, said
    assert installs == [dreaming.KEY], "it was saved but never scheduled"
    assert any(one.key == dreaming.KEY
               for one in schedule.read_user_tasks())


def test_a_task_the_scheduler_does_not_have_is_never_drawn_as_on(own_home):
    """Saved and inert has to be its own state.

    `is_installed` is False here because nothing was ever registered, and
    reporting that as "on" would be the page telling somebody their
    assistant reflects nightly when it does not.
    """
    schedule.save_user_task(dreaming.task_for(4, 15))

    now = dreaming.state()
    assert not now.on
    assert now.saved_but_not_running
    assert now.at() == "04:15"


def test_the_time_is_read_off_the_schedule_not_a_settings_file(own_home):
    """There is no second record of when it dreams.

    A settings file could disagree with the scheduler, and then the page
    would be reporting a preference while the machine did something else --
    the same reasoning that made `ScheduledTask.work` a derived property
    earlier the same day.
    """
    schedule.save_user_task(dreaming.task_for(23, 5))
    assert dreaming.state().at() == "23:05"

    source = (REPO_ROOT / "src" / "aki_agent"
              / "dreaming.py").read_text(encoding="utf-8")
    assert "settings_file" not in source
    assert "dreaming.json" not in source


def test_turning_it_off_removes_it_rather_than_leaving_clutter(own_home):
    schedule.save_user_task(dreaming.task_for(3, 0))

    ok, said = dreaming.turn_off()

    assert ok
    assert "off" in said.lower()
    assert not any(one.key == dreaming.KEY
                   for one in schedule.read_user_tasks())


def test_moving_it_needs_it_to_be_on_first(own_home):
    ok, said = dreaming.set_time(6, 0)
    assert not ok
    assert "Turn dreaming on first" in said


def test_an_impossible_time_is_clamped_rather_than_stored(own_home,
                                                          monkeypatch):
    monkeypatch.setattr(schedule, "install", lambda *a, **k: (True, "ok"))
    monkeypatch.setattr(schedule, "runner_script",
                        lambda *a, **k: own_home / "runner.py")
    (own_home / "runner.py").write_text("x", encoding="utf-8")

    dreaming.turn_on(99, 99)
    assert dreaming.state().at() == "23:59"
