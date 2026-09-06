"""Atomic writes, locking, the three memory tiers, and the learning loop.

These are the quiet parts of the system. Nothing here is exciting, and all of
it is the reason the exciting parts can be trusted: a torn state file breaks a
notification, a lost human note breaks a recovery, and a memory tier that eats
another tier's data breaks the assistant's sense of what is true.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import threading
import time
from pathlib import Path

import pytest

from fake_credentials import FAKE_HEX_KEY, FAKE_HEX_TOKEN
from aki_agent import atomic, memory, paths, runner, traces


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


# ---------------------------------------------------------------------------
# Atomic writing
# ---------------------------------------------------------------------------

def test_a_failed_write_leaves_the_old_contents_intact(tmp_path, monkeypatch):
    """Never truncate the live file before the replacement has succeeded.

    Build the complete replacement, then swap. This test simulates the write
    blowing up half way through.
    """
    target = tmp_path / "state.txt"
    target.write_text("the good old contents", encoding="utf-8")

    real_replace = Path.replace

    def explode(self, other):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", explode)

    with pytest.raises(OSError):
        atomic.write_text(target, "the new contents")

    monkeypatch.setattr(Path, "replace", real_replace)
    assert target.read_text(encoding="utf-8") == "the good old contents"


def test_no_temporary_debris_is_left_behind(tmp_path, monkeypatch):
    target = tmp_path / "state.txt"

    def explode(self, other):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", explode)
    with pytest.raises(OSError):
        atomic.write_text(target, "x")

    leftovers = [path for path in tmp_path.iterdir()
                 if path.name.endswith(".tmp")]
    assert leftovers == []


def test_a_corrupt_json_file_does_not_stop_the_software(tmp_path):
    """A bad state file must not prevent starting -- doctor reports it."""
    path = tmp_path / "broken.json"
    path.write_text("{not json at all", encoding="utf-8")

    assert atomic.read_json(path, default={"safe": True}) == {"safe": True}


def test_concurrent_appends_do_not_interleave(tmp_path):
    """The failure this prevents is a half-line in a log nobody can parse."""
    target = tmp_path / "log.txt"
    line = "x" * 500

    def writer(index):
        for _ in range(20):
            atomic.append_line(target, f"{index}:{line}")

    threads = [threading.Thread(target=writer, args=(index,))
               for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    written = target.read_text(encoding="utf-8").splitlines()
    assert len(written) == 80
    for entry in written:
        index, payload = entry.split(":", 1)
        assert payload == line, "a line was torn by a concurrent append"


def test_the_lock_is_actually_exclusive(tmp_path):
    """The source system's locking was silently absent on its own platform.

    It guarded the import in a try/except, so on the machine it ran on the
    import failed and locking was skipped for the system's whole life. This
    implementation cannot do that: there is no optional import to fail.
    """
    target = tmp_path / "thing.txt"

    with atomic.lock(target):
        with pytest.raises(atomic.LockTimeout):
            with atomic.lock(target, timeout=0.3):
                pass        # pragma: no cover -- must not be reached


def test_a_lock_left_by_a_dead_process_is_broken(tmp_path):
    """A crash must not wedge the system until somebody notices.

    Note that the age is set with `os.utime`, not by writing a timestamp into
    the file. That is deliberate and it follows a fix: staleness is judged by
    the file's modification time and the lock file is never opened during
    contention, because on Windows an open file cannot be deleted and reading
    it turned the lock into a permanent deadlock.
    """
    target = tmp_path / "thing.txt"
    lock_file = target.with_name(target.name + ".lock")
    lock_file.write_text(json.dumps({"pid": 999_999_999}), encoding="utf-8")

    ancient = time.time() - 10_000
    os.utime(lock_file, (ancient, ancient))

    with atomic.lock(target, timeout=2):
        pass                # taking it at all is the assertion

    assert not lock_file.exists()


# ---------------------------------------------------------------------------
# Tier 1 — working state, and the notes that must survive
# ---------------------------------------------------------------------------

def test_human_notes_survive_a_mechanical_rewrite():
    """The single most important behaviour in the memory system.

    The mechanical half records what happened, which any summary could
    reconstruct. The notes record what I was in the middle of and why, which a
    summary destroys -- and which is exactly what is needed after a crash.
    """
    memory.write_working_state(memory.WorkingState(
        generated_at=_dt.datetime.now(),
        open_items=["first thing"],
        human_notes="I was half way through rewiring the thing. Do not "
                    "restart it until that is finished.",
    ))

    # A scheduled job rewrites the mechanical half and knows nothing about
    # the notes -- which is the realistic case.
    memory.write_working_state(memory.WorkingState(
        generated_at=_dt.datetime.now(),
        open_items=["a completely different thing"],
    ))

    state = memory.read_working_state()
    assert "half way through rewiring" in state.human_notes
    assert state.open_items == ["a completely different thing"]


def test_appending_a_note_does_not_disturb_the_mechanical_half():
    memory.write_working_state(memory.WorkingState(
        generated_at=_dt.datetime.now(),
        open_items=["keep me"], waiting_on=["and me"]))

    memory.append_human_note("remember the thing")

    state = memory.read_working_state()
    assert state.open_items == ["keep me"]
    assert state.waiting_on == ["and me"]
    assert "remember the thing" in state.human_notes


def test_old_working_state_declares_itself_stale():
    """A panel showing stale data confidently is worse than showing nothing."""
    fresh = memory.WorkingState(generated_at=_dt.datetime.now())
    old = memory.WorkingState(
        generated_at=_dt.datetime.now() - _dt.timedelta(days=2))

    assert fresh.is_stale is False
    assert old.is_stale is True
    assert "history" in old.staleness_note()


# ---------------------------------------------------------------------------
# Tier 2 — durable facts
# ---------------------------------------------------------------------------

def test_facts_are_written_read_and_forgotten():
    memory.remember("Prefers being told bad news first",
                    body="Said so directly.", source="conversation")

    found = memory.recall("bad news")
    assert len(found) == 1
    assert "bad news" in found[0].summary

    assert memory.forget(found[0].key) is True
    assert memory.recall("bad news") == []


def test_forgetting_is_possible_and_is_a_feature():
    """A store you cannot correct accumulates confident wrong answers."""
    fact = memory.remember("Something that turned out to be wrong")
    assert memory.forget(fact.key) is True
    assert memory.forget(fact.key) is False


def test_recall_with_no_query_returns_everything():
    memory.remember("first")
    memory.remember("second")
    assert len(memory.recall()) == 2


# ---------------------------------------------------------------------------
# Tier 3 — the daily narrative
# ---------------------------------------------------------------------------

def test_the_narrative_is_append_only():
    memory.log_event("first thing happened")
    memory.log_event("second thing happened")

    text = memory.read_day()
    assert "first thing happened" in text
    assert "second thing happened" in text
    assert text.index("first") < text.index("second")


def test_the_three_tiers_do_not_share_storage():
    """Merging them means the shortest-lived one dictates the rules."""
    memory.write_working_state(memory.WorkingState(
        generated_at=_dt.datetime.now(), open_items=["working"]))
    memory.remember("a durable fact")
    memory.log_event("a narrative line")

    assert memory.state_file().exists()
    assert list(paths.memory_dir().glob("*.md"))
    assert memory.daily_path().exists()

    # And rewriting the working state leaves the other two untouched.
    memory.write_working_state(memory.WorkingState(
        generated_at=_dt.datetime.now(), open_items=["different"]))

    assert memory.recall("durable fact")
    assert "a narrative line" in memory.read_day()


# ---------------------------------------------------------------------------
# The learning loop
# ---------------------------------------------------------------------------

def test_verdicts_become_a_card_the_assistant_can_read():
    traces.log("summary", output="a first attempt", verdict="rejected",
               correction="Too long. Three sentences maximum.")
    traces.log("summary", output="a shorter attempt", verdict="accepted")

    traces.distil("summary")
    card = traces.card_for("summary")

    assert "Three sentences maximum" in card
    assert "Accepted 1" in card
    assert "rejected 1" in card


def test_an_invalid_verdict_is_refused():
    with pytest.raises(ValueError):
        traces.log("summary", output="x", verdict="quite good actually")


def test_traces_are_redacted_before_being_written():
    traces.log("summary",
               output=f'api_key = "{FAKE_HEX_KEY}"',
               verdict="accepted")

    raw = traces.trace_file().read_text(encoding="utf-8")
    assert FAKE_HEX_KEY not in raw


def test_a_malformed_trace_line_does_not_destroy_the_log():
    traces.log("summary", output="good", verdict="accepted")
    atomic.append_line(traces.trace_file(), "{ this is not json")
    traces.log("summary", output="also good", verdict="accepted")

    assert len(traces.read_traces("summary")) == 2


def test_the_learning_loop_is_entirely_local():
    """No model call, no API, nothing leaves the machine.

    That is the point, not a limitation to be lifted later: a person's
    corrections about their own work are private.
    """
    import inspect

    source = inspect.getsource(traces)
    for outbound in ("requests", "urllib", "http", "openai", "anthropic"):
        assert f"import {outbound}" not in source


# ---------------------------------------------------------------------------
# The headless runner
# ---------------------------------------------------------------------------

@pytest.mark.real_runner
def test_the_prompt_goes_in_on_stdin_not_as_an_argument(monkeypatch):
    """Windows has a command-line length limit that a real prompt exceeds.

    The failure is not a clean error -- it is a truncated prompt or a
    mysterious refusal to start, which only appears once prompts get long
    enough to be useful.
    """
    captured = {}

    class FakeCompleted:
        returncode = 0
        stdout = "done"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["input"] = kwargs.get("input")
        captured["env"] = kwargs.get("env")
        return FakeCompleted()

    monkeypatch.setattr(runner, "find_claude", lambda: "claude")
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    long_prompt = "please summarise this. " * 2000
    result = runner.run(long_prompt)

    assert result.ok is True
    assert captured["input"] == long_prompt
    assert long_prompt not in " ".join(captured["command"])


@pytest.mark.real_runner
def test_the_child_process_is_given_a_utf8_environment(monkeypatch):
    """A Windows console cannot print non-Latin text by default.

    The exception it raises kills whatever shelled out, so an assistant that
    speaks anything other than English would break its own scheduled runs.
    """
    class FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    captured = {}

    def fake_run(command, **kwargs):
        captured["env"] = kwargs.get("env")
        return FakeCompleted()

    monkeypatch.setattr(runner, "find_claude", lambda: "claude")
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    runner.run("hello")
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"


def test_runner_output_is_redacted(monkeypatch):
    class FakeCompleted:
        returncode = 0
        stdout = f'token: {FAKE_HEX_TOKEN}'
        stderr = ""

    monkeypatch.setattr(runner, "find_claude", lambda: "claude")
    monkeypatch.setattr(runner.subprocess, "run",
                        lambda command, **kwargs: FakeCompleted())

    result = runner.run("hello")
    assert FAKE_HEX_TOKEN not in result.output


@pytest.mark.real_runner
def test_a_missing_claude_is_a_clear_message_not_a_crash(monkeypatch):
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    with pytest.raises(runner.ClaudeNotFound) as raised:
        runner.run("hello")
    assert "claude.com/claude-code" in str(raised.value)


# ---------------------------------------------------------------------------
# The rename that a virus scanner can lose you
# ---------------------------------------------------------------------------


def test_a_scanner_holding_the_file_for_a_moment_does_not_lose_the_write(
        tmp_path, monkeypatch):
    """On Windows a rename fails outright while ANY process holds a handle.

    Something usually does for a few milliseconds after a file is created --
    Defender, the search indexer, a backup agent, Google Drive -- and it
    surfaces as WinError 5. Found 2026-08-24 as a test that failed about one
    run in nine, always on this line. On somebody's laptop that is not a flaky
    test: it is their answer being lost while the software says it saved it.
    """
    target = tmp_path / "state.json"
    atomic.write_json(target, {"first": True})

    attempts = {"count": 0}
    real = Path.replace

    def busy_once(self, other):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise PermissionError(5, "Access is denied")
        return real(self, other)

    monkeypatch.setattr(Path, "replace", busy_once)
    atomic.write_json(target, {"second": True})

    assert attempts["count"] == 2, "it must try again rather than give up"
    assert json.loads(target.read_text(encoding="utf-8")) == {"second": True}


def test_a_folder_that_is_genuinely_not_writable_still_says_so(tmp_path,
                                                              monkeypatch):
    """Retrying is for a scanner, not for a real permissions problem.

    Retrying that one for ever would turn a clear error into a hang, which is
    the worse failure: nobody can act on software that has simply stopped.
    """
    target = tmp_path / "state.json"

    def always_busy(self, other):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(Path, "replace", always_busy)
    monkeypatch.setattr(atomic.time, "sleep", lambda _seconds: None)

    with pytest.raises(PermissionError):
        atomic.write_json(target, {"anything": True})


# ---------------------------------------------------------------------------
# Two writers on one working state
#
# Added 2026-09-01, before the fix, and confirmed failing against the code as
# it then stood. The clone design (several sessions sharing one memory) makes
# these paths concurrent for the first time; until now they were safe only
# because exactly one session existed.
#
# `atomic.write_text` prevents a reader seeing half a file. It does nothing
# about two writers that each read, modify their copy, and write it back --
# both succeed, and the second silently erases the first. `write_working_state`
# reads the human notes back off disk precisely so it cannot lose them, and
# that read is the half of the operation the lock has to cover.
# ---------------------------------------------------------------------------

def _interleave_after_read(monkeypatch, hold: float = 0.15):
    """Make the first reader slow, so a second writer lands inside its window.

    A race left to chance is a test that passes on a fast morning. This forces
    the exact interleaving the bug needs: the first caller reads, pauses long
    enough for the second to complete a whole write, and only then writes what
    it read. Without a lock the pause is fatal; with one, the second caller
    simply waits and the pause costs nothing but time.
    """
    real_read = memory.read_working_state
    first = threading.Event()

    def slow_read():
        state = real_read()
        if not first.is_set():
            first.set()
            time.sleep(hold)
        return state

    monkeypatch.setattr(memory, "read_working_state", slow_read)
    return real_read


def test_two_writers_do_not_lose_each_others_notes(monkeypatch):
    """The failure this whole locking step exists to prevent."""
    memory.write_working_state(memory.WorkingState(
        generated_at=_dt.datetime.now(), human_notes=""))

    real_read = _interleave_after_read(monkeypatch)
    errors: list[BaseException] = []

    def add(note: str):
        try:
            memory.append_human_note(note)
        except BaseException as exc:                     # noqa: BLE001
            errors.append(exc)

    one = threading.Thread(target=add, args=("clone one was here",))
    two = threading.Thread(target=add, args=("clone two was here",))

    one.start()
    time.sleep(0.02)        # let the first get past its read
    two.start()
    one.join(timeout=30)
    two.join(timeout=30)

    assert not errors, f"a writer raised: {errors!r}"

    monkeypatch.setattr(memory, "read_working_state", real_read)
    notes = memory.read_working_state().human_notes

    assert "clone one was here" in notes, "the first note was overwritten"
    assert "clone two was here" in notes, "the second note was overwritten"


def test_a_mechanical_rewrite_does_not_eat_a_concurrent_note(monkeypatch):
    """The same race across the two different entry points.

    A scheduled job rewriting the mechanical half is the likeliest real
    collision: it runs on a timer and does not know anybody is typing.
    """
    memory.write_working_state(memory.WorkingState(
        generated_at=_dt.datetime.now(), human_notes="the note that must live"))

    real_read = _interleave_after_read(monkeypatch)
    errors: list[BaseException] = []

    def rewrite():
        try:
            memory.write_working_state(memory.WorkingState(
                generated_at=_dt.datetime.now(),
                open_items=["something the scheduler found"]))
        except BaseException as exc:                     # noqa: BLE001
            errors.append(exc)

    def note():
        try:
            memory.append_human_note("typed while the job was running")
        except BaseException as exc:                     # noqa: BLE001
            errors.append(exc)

    job = threading.Thread(target=rewrite)
    typing = threading.Thread(target=note)

    job.start()
    time.sleep(0.02)
    typing.start()
    job.join(timeout=30)
    typing.join(timeout=30)

    assert not errors, f"a writer raised: {errors!r}"

    monkeypatch.setattr(memory, "read_working_state", real_read)
    state = memory.read_working_state()

    assert "the note that must live" in state.human_notes
    assert "typed while the job was running" in state.human_notes
    assert "something the scheduler found" in state.open_items
