"""When a long-running session may be restarted, and when it may not.

The dangerous failure here is not "it never recycles" — that shows up as a
slow assistant and somebody asks. It is **restarting a session while its user
is in the middle of using it**, which destroys real work to tidy a number and
which the user experiences as the software randomly losing the thread.

So the tests that matter are the ones asserting it *declines*.
"""

from __future__ import annotations

import datetime as _dt
import json
import time

import pytest

from aki_agent import guard, paths


@pytest.fixture
def home(tmp_path, monkeypatch):
    folder = tmp_path / "01_Config"
    folder.mkdir(parents=True)
    monkeypatch.setenv("AKI_AGENT_HOME", str(folder))
    monkeypatch.setattr(paths, "app_dir", lambda: folder)
    return folder


@pytest.fixture
def transcripts(tmp_path, monkeypatch):
    """A folder standing in for Claude Code's own."""
    folder = tmp_path / "projects" / "somewhere"
    folder.mkdir(parents=True)
    monkeypatch.setattr(guard, "transcript_dir", lambda workspace=None: folder)
    return folder


def write_transcript(folder, context: int, idle_minutes: float = 0.0):
    path = folder / "session.jsonl"
    path.write_text(json.dumps({
        "message": {"usage": {"input_tokens": 1000,
                              "cache_read_input_tokens": context - 1000,
                              "cache_creation_input_tokens": 0}}}) + "\n",
        encoding="utf-8")
    if idle_minutes:
        old = time.time() - idle_minutes * 60
        import os
        os.utime(path, (old, old))
    return path


# ---------------------------------------------------------------------------
# Reading the window
# ---------------------------------------------------------------------------

def test_the_window_is_all_three_token_counts_added_up():
    """Reading only `input_tokens` reports a fraction of the truth, and
    reports it confidently. A cached read occupies the window exactly as much
    as a fresh one."""
    line = json.dumps({"message": {"usage": {
        "input_tokens": 5_000,
        "cache_read_input_tokens": 400_000,
        "cache_creation_input_tokens": 20_000}}})

    assert guard._context_from_lines([line]) == 425_000


def test_the_most_recent_usage_wins():
    lines = [
        json.dumps({"message": {"usage": {"input_tokens": 10}}}),
        json.dumps({"message": {"usage": {"input_tokens": 99}}}),
    ]
    assert guard._context_from_lines(lines) == 99


def test_a_half_written_line_at_the_tail_is_skipped_not_fatal():
    """The transcript is being appended to while this reads it."""
    lines = [
        json.dumps({"message": {"usage": {"input_tokens": 42}}}),
        '{"message": {"usage": {"input_tok',
    ]
    assert guard._context_from_lines(lines) == 42


def test_no_transcript_reads_as_zero_rather_than_crashing(transcripts):
    assert guard.context_size() == 0


def test_the_transcript_folder_matches_claude_codes_naming():
    """`G:\\My Drive\\AI_Development` becomes `G--My-Drive-AI-Development`.
    Derived, not configured: a stored copy of somebody else's convention goes
    stale without saying anything."""
    from pathlib import Path

    name = guard.transcript_dir(Path("G:/My Drive/AI_Development")).name
    assert name == "G--My-Drive-AI-Development"


# ---------------------------------------------------------------------------
# The decision — mostly, refusing to make it
# ---------------------------------------------------------------------------

def test_a_busy_session_is_never_cut_however_full_it_is(home, transcripts):
    """Rule 2, and the one that must not be traded away. Size may suggest a
    recycle; only idleness may authorise one."""
    write_transcript(transcripts, 900_000, idle_minutes=0)
    guard.record_recycle(_dt.datetime.now() - _dt.timedelta(hours=99))

    found = guard.assess()

    assert not found.all_met
    assert not found.would_recycle
    context = next(one for one in found.conditions if one.name == "Context")
    assert context.met, "the context condition itself is met"


# A time that is never inside tonight's restart window.
#
# THE FLAKE THIS FIXES (2026-09-05). Two tests below called `guard.assess()`
# with no `now`, so they read the wall clock -- and `nightly_due` is true for
# twenty-five minutes after the configured recycle hour. They passed all day
# and failed at 03:0x, which is exactly the hour somebody is most likely to
# be running a long session and least likely to trust the result.
#
# The window starts at `recycle_hour:00` and runs `NIGHTLY_WINDOW_MINUTES`.
# Any minute past that is outside it whatever the hour is: after the window
# if the hour matches, hours past it if later, and negative if earlier.
OUTSIDE_THE_WINDOW = _dt.datetime.now().replace(
    minute=55, second=0, microsecond=0)


def test_an_idle_session_that_is_not_full_is_left_alone(home, transcripts):
    write_transcript(transcripts, 1_000, idle_minutes=600)
    guard.record_recycle(_dt.datetime.now() - _dt.timedelta(hours=99))

    assert not guard.assess(now=OUTSIDE_THE_WINDOW).would_recycle


def test_a_recent_restart_blocks_another_one(home, transcripts):
    """Without this, a machine that cannot complete a restart tries again
    every twenty minutes for ever."""
    write_transcript(transcripts, 900_000, idle_minutes=600)
    guard.record_recycle(_dt.datetime.now())

    assert not guard.assess().would_recycle


def test_all_three_together_do_authorise_it(home, transcripts):
    write_transcript(transcripts, 900_000, idle_minutes=600)
    guard.record_recycle(_dt.datetime.now() - _dt.timedelta(hours=99))

    found = guard.assess()

    assert found.all_met
    assert found.would_recycle


def test_switching_auto_off_stops_it_while_still_watching(home, transcripts):
    write_transcript(transcripts, 900_000, idle_minutes=600)
    guard.record_recycle(_dt.datetime.now() - _dt.timedelta(hours=99))
    guard.save_settings(auto_recycle=False, nightly_recycle=False)

    found = guard.assess()

    assert found.all_met, "it still sees that the conditions are met"
    assert not found.would_recycle
    assert "watching only" in found.sentence()


# ---------------------------------------------------------------------------
# Session age is shown and never acted on
# ---------------------------------------------------------------------------

def test_session_age_is_marked_as_not_deciding(home, transcripts):
    write_transcript(transcripts, 1_000)
    age = next(one for one in guard.assess().conditions
               if one.name == "Session age")

    assert not age.decides
    assert "not a trigger" in age.detail
    assert age.line().startswith(" . "), "it must not look like a checkbox"


def test_an_old_session_alone_authorises_nothing(home, transcripts):
    """A number on a dashboard that looks like a threshold and is not one will
    eventually be read as the reason something happened."""
    path = write_transcript(transcripts, 1_000, idle_minutes=600)
    import os
    old = time.time() - 60 * 60 * 100
    os.utime(path, (old, old))

    assert not guard.assess().would_recycle


# ---------------------------------------------------------------------------
# The switches
# ---------------------------------------------------------------------------

def test_auto_is_on_before_anybody_chooses(home):
    """A student will not open a dashboard for weeks. An assistant that
    quietly fills up and stops working is worse for them than one that
    restarts itself while nobody is typing."""
    assert guard.settings()["auto_recycle"] is True
    assert not guard.settings_file().exists()


def test_an_unreadable_settings_file_leaves_it_on(home):
    """Failing open. A deliberate OFF is a written `false`; an absence is an
    accident, and an accident must not disable the thing keeping the session
    alive."""
    guard.settings_file().parent.mkdir(parents=True, exist_ok=True)
    guard.settings_file().write_text("{ not json", encoding="utf-8")

    assert guard.settings()["auto_recycle"] is True


def test_the_hour_is_clamped_to_a_real_hour(home):
    assert guard.save_settings(recycle_hour=99)["recycle_hour"] == 23
    assert guard.save_settings(recycle_hour=-4)["recycle_hour"] == 0


def test_the_nightly_window_is_a_window_not_an_instant():
    """The guard ticks every twenty minutes: an equality test on the hour
    fires several times and a test on the minute usually misses."""
    config = {"nightly_recycle": True, "recycle_hour": 4}
    at = _dt.datetime(2026, 8, 20, 4, 10)

    assert guard.nightly_due(config, gap_hours=99, now=at)
    assert not guard.nightly_due(config, gap_hours=99,
                                 now=at.replace(hour=3, minute=50))
    assert not guard.nightly_due(config, gap_hours=99,
                                 now=at.replace(minute=40))


def test_the_nightly_run_still_respects_the_gap(home):
    """`MIN_GAP_HOURS` is what stops the second tick inside the window
    recycling a session that the first one just restarted."""
    config = {"nightly_recycle": True, "recycle_hour": 4}
    at = _dt.datetime(2026, 8, 20, 4, 5)

    assert not guard.nightly_due(config, gap_hours=0.2, now=at)


def test_nightly_off_means_off(home):
    config = {"nightly_recycle": False, "recycle_hour": 4}
    assert not guard.nightly_due(config, gap_hours=99,
                                 now=_dt.datetime(2026, 8, 20, 4, 5))


# ---------------------------------------------------------------------------
# What it says
# ---------------------------------------------------------------------------

def test_the_sentence_says_what_will_happen_not_what_state_it_is_in(
        home, transcripts):
    write_transcript(transcripts, 900_000, idle_minutes=0)
    guard.save_settings(auto_recycle=False, nightly_recycle=False)

    said = guard.assess().sentence()

    assert "Nothing will restart on its own" in said
    assert "only the button" in said


def test_when_it_is_waiting_it_names_what_on(home, transcripts):
    write_transcript(transcripts, 900_000, idle_minutes=0)
    guard.save_settings(auto_recycle=True)

    said = guard.assess(now=OUTSIDE_THE_WINDOW).sentence()

    assert "Waiting on" in said
    assert "idle" in said
    assert "context" not in said.split("Waiting on")[1], \
        "the context condition is met, so it is not what we are waiting on"


def test_a_restart_stamps_the_time_before_it_tries(home, monkeypatch,
                                                   transcripts):
    """A recycle that gets part-way and does not come back must still count as
    one, or the guard immediately tries again on a machine that has just shown
    it cannot finish one."""
    from aki_agent import recycle, session

    monkeypatch.setattr(session, "is_safe_to_restart",
                        lambda *a, **k: session.RestartAdvice(True, "idle"))
    monkeypatch.setattr(session, "shutdown_order", lambda holds: [])
    monkeypatch.setattr(recycle, "_start", lambda command: None)

    assert guard.hours_since_recycle() > 1000
    recycle.perform(["launcher"], holds_connection=False, confirmed=True)

    assert guard.hours_since_recycle() < 1


def test_the_note_beside_the_default_still_points_at_a_real_test():
    """`guard.DEFAULTS` carries a comment saying auto-recycle may be True
    only because rule 2 is enforced, and names the test holding rule 2 down.

    A pointer to a test that has been renamed is worse than no pointer: the
    next person reads a reassurance, cannot find what it cites, and is left
    guessing whether the guarantee moved or vanished. So the citation is
    checked like any other claim.
    """
    import inspect
    from pathlib import Path

    from aki_agent import guard

    source = inspect.getsource(guard)
    cited = "test_a_busy_session_is_never_cut_however_full_it_is"
    assert cited in source, "the note beside DEFAULTS no longer names a test"
    assert f"def {cited}(" in Path(__file__).read_text(encoding="utf-8")
