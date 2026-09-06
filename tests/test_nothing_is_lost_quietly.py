"""Group E: data loss and unattended failure.

Every test here corresponds to a way this package could lose somebody's
things, or fail for a week without saying so. They are written as the failure
rather than as the feature — each one passes trivially against the fix and
fails loudly against the code as it was.

The unifying fault was not any single bug. It was that the failure path had
been designed to be quiet: an unreadable file answered as an empty one, a task
that threw wrote its traceback to a hidden console, and a log grew until the
page that read it got slow, with nothing at any point saying a word.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest

from aki_agent import atomic


# ---------------------------------------------------------------------------
# E1. An unreadable file must not be mistaken for an empty one
# ---------------------------------------------------------------------------

def test_a_corrupt_file_is_kept_rather_than_overwritten(tmp_path):
    """The bug: read → default → write → the real contents are gone for ever.

    Every queue in this package is read, changed and written back. Answering
    "the file would not parse" with an empty list meant the very next write
    replaced real data with nothing, permanently, with no backup anywhere.
    """
    path = tmp_path / "held.json"
    path.write_text('[{"text": "something real"} <<< truncated',
                    encoding="utf-8")

    assert atomic.read_json(path, default=[]) == []

    # The bytes survived, under a dated name, so the write that follows
    # cannot flatten them.
    kept = atomic.quarantined(tmp_path)
    assert len(kept) == 1
    assert "something real" in kept[0].read_text(encoding="utf-8")

    # And the original name is now genuinely free, so the next read starts
    # clean rather than quarantining the same file on every single call.
    assert not path.exists()
    atomic.write_json(path, [{"text": "new"}])
    assert len(atomic.quarantined(tmp_path)) == 1


def test_a_missing_file_is_not_treated_as_corrupt(tmp_path):
    """Absent is an ordinary answer and must stay one."""
    assert atomic.read_json(tmp_path / "nothing.json", default=[]) == []
    assert atomic.quarantined(tmp_path) == []


def test_a_second_corruption_does_not_erase_the_first(tmp_path):
    """Dated names, so the evidence accumulates instead of overwriting."""
    for text in ("first broken", "second broken"):
        path = tmp_path / "held.json"
        path.write_text(text, encoding="utf-8")
        atomic.read_json(path, default=[])

    kept = atomic.quarantined(tmp_path)
    assert len(kept) == 2
    assert {one.read_text(encoding="utf-8") for one in kept} == {
        "first broken", "second broken"}


def test_a_file_that_will_not_open_stops_a_caller_that_meant_to_write(tmp_path):
    """The third case, and the reason there are two readers.

    A file that exists and cannot be opened says nothing about its contents.
    Quarantining it would be wrong — it is probably fine, just held for an
    instant by a backup agent. Returning a default would be worse: the caller
    writes an empty structure over data it never saw.

    So the update reader refuses, and the file is left exactly as it was.
    """
    path = tmp_path / "held.json"
    path.write_text('["real"]', encoding="utf-8")

    class WillNotOpen(type(path)):
        pass

    original = Path.read_text

    def refuse(self, *args, **kwargs):
        if self.name == "held.json":
            raise OSError(13, "in use by another process")
        return original(self, *args, **kwargs)

    Path.read_text = refuse
    try:
        with pytest.raises(atomic.Unreadable):
            atomic.read_json_for_update(path, default=[])
    finally:
        Path.read_text = original

    assert path.read_text(encoding="utf-8") == '["real"]'
    assert atomic.quarantined(tmp_path) == [], "a locked file is not corrupt"


def test_the_queues_all_use_the_reader_that_refuses_to_guess():
    """Named individually, because this is a one-word difference per file and
    the wrong word is invisible in review."""
    for module, function in (("notify", "read_held"),
                             ("conversation", "read_pending"),
                             ("approvals", "_read"),
                             ("schedule", "read_user_tasks")):
        source = Path(f"src/aki_agent/{module}.py").read_text(encoding="utf-8")
        body = source[source.index(f"def {function}("):]
        body = body[:body.index("\ndef ", 1)]
        assert "read_json_for_update" in body, (
            f"{module}.{function} reads with the forgiving reader and then "
            "writes the file back")


# ---------------------------------------------------------------------------
# E2, E3. A task that fails must say so, somewhere findable
# ---------------------------------------------------------------------------

def test_a_task_that_throws_does_not_take_the_process_with_it(tmp_path,
                                                              monkeypatch):
    """`run-task.bat` hides the console, so a traceback went nowhere at all.

    ClaudeNotFound — the likeliest failure on a fresh machine — looked exactly
    like a task that had never been scheduled.
    """
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import task_runs, tasks

    def explode(_key, **_kwargs):
        raise RuntimeError("claude is not installed")

    monkeypatch.setattr(tasks, "run_one", explode)

    assert tasks.main(["run-task", "morning-summary"]) == 1

    # And it was written down where doctor will find it.
    run = task_runs.for_task("morning-summary")
    assert run.failing
    assert "claude is not installed" in run.last_message


def test_a_run_that_works_clears_the_failure(tmp_path, monkeypatch):
    """A counter that only goes up is a counter nobody trusts."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import task_runs

    task_runs.record("nightly", False, "could not reach the mailbox")
    task_runs.record("nightly", False, "could not reach the mailbox")
    assert task_runs.for_task("nightly").failures_in_a_row == 2

    task_runs.record("nightly", True, "sent")
    run = task_runs.for_task("nightly")
    assert not run.failing
    assert run.failures_in_a_row == 0


def test_how_long_it_has_been_failing_is_answerable(tmp_path, monkeypatch):
    """"Is it broken" and "how long has it been broken" are both questions
    somebody asks, and only the second one decides whether to act."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import task_runs

    long_ago = _dt.datetime.now() - _dt.timedelta(days=6)
    task_runs.record("weekly", True, "fine", now=long_ago)
    for _ in range(3):
        task_runs.record("weekly", False, "no")

    said = task_runs.for_task("weekly").sentence()
    assert "6 days" in said
    assert "3 run(s)" in said


def test_doctor_reports_a_task_that_has_been_failing(tmp_path, monkeypatch):
    """The record is only worth keeping if something reads it back."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import doctor, task_runs

    assert doctor.check_scheduled_tasks_are_working().ok

    task_runs.record("morning-summary", False, "claude is not installed")

    check = doctor.check_scheduled_tasks_are_working()
    assert not check.ok
    assert "morning-summary" in check.detail
    assert "run-task morning-summary" in check.fix


def test_doctor_reports_a_file_that_was_set_aside(tmp_path, monkeypatch):
    """`read_json`'s docstring promised this for a long time before it was
    true. A promise with nothing behind it is the shape this whole audit was
    about."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import doctor, paths

    assert doctor.check_nothing_was_set_aside().ok

    paths.ensure_app_dirs()
    broken = paths.state_dir() / "quiet-modes.json"
    broken.write_text("{ not json", encoding="utf-8")
    atomic.read_json(broken, default=[])

    check = doctor.check_nothing_was_set_aside()
    assert not check.ok
    assert "quiet-modes.json" in check.detail
    assert "Nothing was lost" in check.fix


# ---------------------------------------------------------------------------
# E4. Logs that must not grow for ever, or be read whole
# ---------------------------------------------------------------------------

def test_the_end_of_a_log_is_read_without_reading_the_start(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text("".join(f"line {n}\n" for n in range(5_000)),
                    encoding="utf-8")

    assert atomic.tail_lines(path, 3) == ["line 4997", "line 4998",
                                          "line 4999"]
    # A short file still works, and does not lose its first line.
    short = tmp_path / "short.jsonl"
    short.write_text("only\n", encoding="utf-8")
    assert atomic.tail_lines(short, 10) == ["only"]


def test_a_log_is_trimmed_once_it_gets_large(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text("".join(f"line {n}\n" for n in range(4_000)),
                    encoding="utf-8")

    # Below the size threshold: left alone, whatever the line count.
    assert atomic.trim_log(path, keep_lines=10, max_bytes=10_000_000) == 0
    assert len(path.read_text(encoding="utf-8").splitlines()) == 4_000

    dropped = atomic.trim_log(path, keep_lines=100, max_bytes=1_000)
    assert dropped == 3_900
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 100
    assert lines[-1] == "line 3999", "the trim kept the wrong end"


def test_the_usage_store_forgets_transcripts_it_can_never_count_again(
        tmp_path, monkeypatch):
    """Measured at 124,854 bytes and 406 entries after six days, re-parsed on
    every landing-page load. The buckets inside each entry were pruned; the
    dict holding the entries was not."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import today

    home = tmp_path / "home"
    folder = home / ".claude" / "projects" / "p"
    folder.mkdir(parents=True)
    monkeypatch.setattr(today.paths, "home", lambda: home)

    def transcript(name: str, when: _dt.datetime) -> Path:
        path = folder / name
        path.write_text(json.dumps({
            "timestamp": when.isoformat().replace("+00:00", "Z"),
            "message": {"model": "claude-opus-5",
                        "usage": {"input_tokens": 10, "output_tokens": 0,
                                  "cache_creation_input_tokens": 0,
                                  "cache_read_input_tokens": 0}},
        }) + "\n", encoding="utf-8")
        return path

    now = _dt.datetime.now(_dt.timezone.utc)
    live = transcript("live.jsonl", now)
    stale = transcript("stale.jsonl", now - _dt.timedelta(days=30))

    store = today._refresh_buckets(now)
    assert str(live) in store["files"]

    # The stale one is the shape that accumulated: its buckets fall outside
    # every window the page shows, so it can never contribute a number again.
    # All that was left of it was an offset into a session nobody will look at
    # again -- one per transcript, for ever, re-parsed on every page load.
    assert store["files"][str(stale)]["buckets"] == {}
    stale.unlink()

    store = today._refresh_buckets(now)
    assert str(stale) not in store["files"]

    # Today's is kept, and keeps its tokens -- including after the transcript
    # itself is deleted. The tokens were genuinely spent, and this week's
    # total must not drop because a file was tidied away.
    assert store["files"][str(live)]["buckets"]
    live.unlink()
    store = today._refresh_buckets(now)
    assert store["files"][str(live)]["buckets"]
