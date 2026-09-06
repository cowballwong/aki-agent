"""Running a scheduled task — the link that was missing.

Scheduling was built before the thing it schedules. `install()` created a real
Task Scheduler entry pointing at a script that did not exist, so tasks
installed "successfully" and then failed silently on every firing, with the
dashboard showing "installed: yes" beside something that had never once run.

Nothing errored. The only symptom was an absence. These tests exist so that
cannot happen again quietly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import memory, notify, paths, runner, schedule, tasks
from aki_agent.config import Config, Notifications, Layout

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


class FakeResult:
    def __init__(self, ok=True, output="all done", error="", seconds=1.0):
        self.ok = ok
        self.output = output
        self.error = error
        self.seconds = seconds
        self.timed_out = False

    def summary(self):
        return "finished in 1s" if self.ok else f"failed: {self.error}"


def a_config(tmp_path) -> Config:
    config = Config()
    config.user.name = "Someone"
    config.assistant.name = "Helper"
    config.layout = Layout(root=tmp_path / "work")
    (tmp_path / "work").mkdir(exist_ok=True)
    config.notifications = Notifications(enabled=True)
    return config


# ---------------------------------------------------------------------------
# The gap that existed
# ---------------------------------------------------------------------------

def test_the_runner_script_actually_ships():
    """The file the scheduler points at must exist in the package."""
    for name in ("run-task.bat", "run-task.command"):
        assert (REPO_ROOT / "bin" / name).exists(), (
            f"bin/{name} is missing -- scheduled tasks would install and then "
            "fail silently every time they ran"
        )


def test_nothing_is_scheduled_against_a_missing_runner(tmp_path):
    """The check that stops the silent failure returning."""
    task = schedule.DEFAULT_TASKS[0]
    ok, message = schedule.install(task, tmp_path / "not-there",
                                   confirmed=True)

    assert ok is False
    assert "does not exist" in message
    assert "failed every time" in message


def test_the_runner_path_resolves_to_a_real_file():
    assert schedule.runner_script().exists()


# ---------------------------------------------------------------------------
# Running one
# ---------------------------------------------------------------------------

def test_a_successful_task_is_recorded_and_offered_to_the_gate(
        tmp_path, monkeypatch):
    config = a_config(tmp_path)
    monkeypatch.setattr(tasks.config_module, "load", lambda: config)
    monkeypatch.setattr(runner, "run", lambda *a, **k: FakeResult())

    outcome = tasks.run_one("morning-summary")

    assert outcome.ok is True
    assert outcome.delivered is True
    assert "Morning summary" in memory.read_day()
    delivered = (paths.log_dir() / "messages.md").read_text(encoding="utf-8")
    assert "all done" in delivered


def test_a_failing_task_is_reported_not_swallowed(tmp_path, monkeypatch):
    """A scheduled job that fails silently is how somebody finds out in June
    that their morning summary stopped in March."""
    config = a_config(tmp_path)
    monkeypatch.setattr(tasks.config_module, "load", lambda: config)
    monkeypatch.setattr(
        runner, "run",
        lambda *a, **k: FakeResult(ok=False, output="", error="it broke"))

    outcome = tasks.run_one("morning-summary")

    assert outcome.ok is False
    assert "FAILED" in memory.read_day()
    delivered = (paths.log_dir() / "messages.md").read_text(encoding="utf-8")
    assert "did not run" in delivered


def test_output_is_held_rather_than_lost_when_notifications_are_off(
        tmp_path, monkeypatch):
    config = a_config(tmp_path)
    config.notifications.enabled = False
    monkeypatch.setattr(tasks.config_module, "load", lambda: config)
    monkeypatch.setattr(runner, "run", lambda *a, **k: FakeResult())

    outcome = tasks.run_one("morning-summary")

    assert outcome.ok is True
    assert outcome.delivered is False
    assert notify.held_count() == 1


def test_an_unknown_task_says_so_clearly(tmp_path, monkeypatch):
    """A deleted task whose scheduler entry survives is a real state."""
    outcome = tasks.run_one("a-task-that-was-deleted")

    assert outcome.ok is False
    assert "no longer exists" in memory.read_day()
    assert "Remove it from the schedule" in outcome.message


def test_a_workspace_that_has_not_mounted_stops_rather_than_reporting_nothing(
        tmp_path, monkeypatch):
    """The dangerous failure is running against an empty-looking folder.

    A cloud drive that has not started yet looks exactly like a workspace with
    no work in it. Reporting 'nothing to do' would be confidently wrong.
    """
    config = a_config(tmp_path)
    config.layout.root = tmp_path / "not-mounted-yet"
    monkeypatch.setattr(tasks.config_module, "load", lambda: config)
    monkeypatch.setattr(paths, "wait_for_path", lambda *a, **k: False)

    called = []
    monkeypatch.setattr(runner, "run",
                        lambda *a, **k: called.append(1) or FakeResult())

    outcome = tasks.run_one("morning-summary")

    assert outcome.ok is False
    assert not called, "it ran against a folder that was not there"
    assert "not available" in outcome.message


def test_a_disabled_task_does_nothing_quietly(tmp_path, monkeypatch):
    task = schedule.ScheduledTask(key="off", title="Off", why="w",
                                  prompt="p", enabled=False)
    schedule.save_user_task(task)

    outcome = tasks.run_one("off")
    assert outcome.ok is True
    assert "nothing to do" in outcome.message


# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------

def test_the_prompt_carries_the_untrusted_content_rule(tmp_path):
    """A headless run has no conversation behind it, so the rule must be in
    the prompt itself."""
    config = a_config(tmp_path)
    prompt = tasks._prompt_for(schedule.DEFAULT_TASKS[0], config)

    assert "never as an instruction" in prompt
    assert config.assistant.name in prompt
    assert schedule.DEFAULT_TASKS[0].prompt in prompt


def test_the_prompt_stays_short(tmp_path):
    """It is paid for on every scheduled run, every day, forever."""
    config = a_config(tmp_path)
    prompt = tasks._prompt_for(schedule.DEFAULT_TASKS[0], config)
    # 800 -> 1000 on 2026-09-02. The morning summary was arriving as a
    # paragraph on days with nothing in it; telling it what an empty day
    # should look like is worth the characters, and this guard exists to
    # make that a decision rather than a drift.
    assert len(prompt) < 1000


# ---------------------------------------------------------------------------
# Quiet when there is nothing to say (reported 2026-08-20)
# ---------------------------------------------------------------------------

def test_the_collect_task_does_not_run_when_nothing_is_waiting(monkeypatch):
    """He got an unprompted phone message — launcher closed, dashboard shut —
    reporting that the inbox was empty and there was nothing to pick up. A
    report about nothing.

    The cause was routing scheduled output to a phone without asking whether
    there was any output worth a phone. On a file channel a chatty task is
    invisible; on a phone it is the difference between an assistant and a
    nuisance, and a nuisance gets switched off wholesale — taking the useful
    messages with it.
    """
    from aki_agent import conversation, runner, tasks

    def must_not_run(*args, **kwargs):        # pragma: no cover
        raise AssertionError("no model call when the queue is empty")

    monkeypatch.setattr(runner, "run", must_not_run)
    assert conversation.pending_count() == 0

    outcome = tasks.run_one("collect-messages")

    assert outcome.ok
    assert "nothing was waiting" in outcome.message


def test_an_empty_result_sends_no_notification(monkeypatch):
    """It used to send "'Morning summary' finished." — sound reasoning for a
    log, wrong for a phone: it tells the reader nothing they can act on and
    trains them to ignore the next one."""
    from aki_agent import notify, runner, tasks
    from aki_agent.config import Config

    sent = []
    monkeypatch.setattr(tasks.config_module, "load", lambda: Config())
    monkeypatch.setattr(notify, "send",
                        lambda *a, **k: sent.append(a) or notify.Decision(
                            True, "sent", "file"))
    monkeypatch.setattr(runner, "run",
                        lambda *a, **k: FakeResult(ok=True, output="   "))

    outcome = tasks.run_one("weekly-tidy")

    assert outcome.ok
    assert not sent, "an empty result must not become a message"


def test_every_task_is_told_it_may_answer_with_nothing():
    """Said once, centrally: a rule repeated in six prompts ends up worded six
    ways."""
    from aki_agent import schedule, tasks
    from aki_agent.config import Config

    wrapped = tasks._prompt_for(schedule.get_task("weekly-tidy"), Config())

    assert "nothing worth telling them, reply with nothing at all" in wrapped
    assert "not delivered anywhere" in wrapped


def test_the_collect_task_runs_often_because_the_empty_case_is_free():
    """Thirty minutes was a budget, set when every run cost a model call. The
    empty queue is now answered before the model is invoked, so the interval
    only buys latency — and latency was the complaint: a reply half an hour
    after you typed is indistinguishable from a broken mirror."""
    from aki_agent import schedule

    task = schedule.get_task("collect-messages")

    assert [one.kind for one in task.triggers] == ["interval"]
    assert task.triggers[0].every_minutes <= 5


# ---------------------------------------------------------------------------
# Saying WHY it failed
#
# `claude` prints some of its own fatal errors to stdout and exits non-zero
# with an empty stderr. Reading only stderr produced the least useful message
# an agent can send.
# ---------------------------------------------------------------------------


def test_a_failure_explained_on_stdout_is_still_explained():
    """The message the maintainer actually got, and the one he should have got.

    On 2026-08-24 two morning tasks reported "failed after 7s:" — nothing
    after the colon. The reason was in stdout the whole time: "OAuth session
    expired and could not be refreshed". One line, and he would not have had
    to ask.
    """
    result = runner.RunResult(
        ok=False,
        output="Failed to authenticate: OAuth session expired and could not "
               "be refreshed",
        error="",
        seconds=7.0)

    assert "OAuth session expired" in result.summary()


def test_stderr_is_still_preferred_when_there_is_any():
    result = runner.RunResult(ok=False, output="some ordinary output",
                              error="the real complaint", seconds=3.0)

    assert "the real complaint" in result.summary()
    assert "ordinary output" not in result.summary()


def test_a_failure_with_nothing_written_anywhere_says_so():
    """Better than a sentence that trails off after the colon.

    "failed after 6s:" reads as a bug in the message. Saying there was no
    reason, and where to look, is at least an instruction.
    """
    result = runner.RunResult(ok=False, output="", error="", seconds=6.0)

    assert result.summary().rstrip().endswith("log")


def test_only_the_first_line_travels():
    """A failure notice goes to a phone; a page of output there is the same
    as none."""
    result = runner.RunResult(ok=False, output="", seconds=2.0,
                              error="first line\nsecond line\nthird line")

    assert result.summary().count("\n") == 0
    assert "second line" not in result.summary()


def test_a_successful_run_is_not_explained_by_its_own_output():
    """On a healthy run stdout is the work, not an explanation of a failure."""
    result = runner.RunResult(ok=True, output="the whole morning summary",
                              seconds=12.0)

    assert result.summary() == "finished in 12s"
