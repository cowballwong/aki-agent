"""Session lifecycle — the six rules, each one a real incident.

The most valuable file in the package to keep passing, because every rule here
represents a failure that was invisible at the time. A restart that reports
success while the wrong process is running does not look like a bug; it looks
like everything is fine.
"""

from __future__ import annotations

import datetime as _dt
import os
import time
from pathlib import Path

import pytest

from aki_agent import paths, session


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


# ---------------------------------------------------------------------------
# RULE 5 — verification against something that cannot be faked
# ---------------------------------------------------------------------------

def test_a_process_that_started_before_the_instruction_is_not_a_restart():
    """The exact failure this rule exists for.

    Something is running, so a naive "is it up?" check says yes. But it is the
    OLD process: the restart never happened, and reporting success here is how
    a system records a recycle that did not occur.
    """
    pytest.importorskip("psutil")

    # Our own process started before "now", so it stands in for the old one.
    session.record_launch(os.getpid(), launcher="pytest")
    instructed_at = time.time()          # instruction comes AFTER it started

    result = session.verify_restart(instructed_at, expected_launcher="pytest")

    assert result.verified is False
    assert "before the restart was requested" in result.reason


def test_verification_requires_the_expected_launcher():
    """RULE 2 in verification form: recent is not the same as ours."""
    pytest.importorskip("psutil")

    session.record_launch(os.getpid(), launcher="pytest")
    # Pretend the instruction came long ago, so the timing check passes and
    # only the lineage check can fail.
    long_ago = time.time() - 86_400

    result = session.verify_restart(
        long_ago, expected_launcher="some-other-launcher-entirely")

    assert result.verified is False
    assert "did not come from" in result.reason


def test_verification_passes_when_both_checks_pass():
    pytest.importorskip("psutil")

    session.record_launch(os.getpid(), launcher="pytest")
    long_ago = time.time() - 86_400

    result = session.verify_restart(long_ago, expected_launcher="python")
    assert result.verified is True
    assert result.pid == os.getpid()


def test_verification_of_a_dead_process_fails_cleanly():
    pytest.importorskip("psutil")

    # A pid that will not exist. Very large pids are not allocated.
    session.record_launch(999_999_999, launcher="pytest")
    result = session.verify_restart(0)

    assert result.verified is False
    assert "not running" in result.reason


def test_verification_without_a_marker_says_so():
    result = session.verify_restart(time.time())
    assert result.verified is False
    assert "no record" in result.reason


# ---------------------------------------------------------------------------
# RULE 6 — never report success on an unverified step
# ---------------------------------------------------------------------------

def test_a_failed_verification_reports_loudly_and_does_not_say_done():
    result = session.Verification(False, "the check matched the wrong process")
    report = result.report()

    assert "NOT CONFIRMED" in report
    assert "not treating this as a successful restart" in report
    # The word that must never appear on an unverified step.
    assert "done" not in report.lower()


def test_a_passed_verification_reports_the_evidence():
    result = session.Verification(
        True, "ok", pid=1234,
        started_at=_dt.datetime(2026, 8, 16, 19, 30, 15))
    report = result.report()

    assert "Confirmed" in report
    assert "1234" in report
    assert "19:30:15" in report


# ---------------------------------------------------------------------------
# RULE 4 — idle time outranks size
# ---------------------------------------------------------------------------

def test_a_busy_session_is_never_restarted():
    now = _dt.datetime(2026, 8, 16, 12, 0, 0)
    recently_active = now - _dt.timedelta(seconds=30)

    advice = session.is_safe_to_restart(recently_active, now=now)

    assert advice.safe is False
    assert "work may be in progress" in advice.reason


def test_an_idle_session_may_be_restarted():
    now = _dt.datetime(2026, 8, 16, 12, 0, 0)
    idle_since = now - _dt.timedelta(minutes=45)

    advice = session.is_safe_to_restart(idle_since, now=now)

    assert advice.safe is True


def test_unknown_activity_means_do_not_touch_it():
    """When we cannot tell, we do not interrupt. Doubt favours the work."""
    advice = session.is_safe_to_restart(None)
    assert advice.safe is False


# ---------------------------------------------------------------------------
# RULE 1 — kill order
# ---------------------------------------------------------------------------

def test_the_connection_is_released_before_the_process_is_terminated():
    """Only one process may hold a messaging token.

    Terminate first and the replacement starts while the old connection is
    still held, gets refused, and you end up with an assistant that is running
    and silently unreachable -- the worst state, because it looks fine.
    """
    steps = session.shutdown_order(holds_connection=True)

    release = next(index for index, step in enumerate(steps)
                   if "release" in step)
    terminate = next(index for index, step in enumerate(steps)
                     if "terminate" in step)

    assert release < terminate


def test_verification_is_the_last_step_and_reporting_follows_it():
    steps = session.shutdown_order(holds_connection=False)

    verify = next(index for index, step in enumerate(steps)
                  if "verify" in step)
    report = next(index for index, step in enumerate(steps)
                  if "report" in step)

    assert verify < report
    assert "ONLY what was verified" in steps[report]


# ---------------------------------------------------------------------------
# RULE 3 — the newest transcript is not necessarily the live one
# ---------------------------------------------------------------------------

def test_a_newer_dead_transcript_is_not_chosen(tmp_path):
    """A recycle can leave a dead transcript newer than the live one."""
    live = tmp_path / "live.jsonl"
    dead_but_newer = tmp_path / "dead.jsonl"

    live.write_text("live", encoding="utf-8")
    dead_but_newer.write_text("dead", encoding="utf-8")

    now = time.time()
    # `dead` is newer, but far outside the liveness window.
    os.utime(live, (now - 60, now - 60))
    os.utime(dead_but_newer, (now - 10_000, now - 10_000))

    chosen = session.pick_live_transcript([live, dead_but_newer],
                                          max_age_seconds=900, now=now)

    assert chosen == live


def test_no_live_transcript_returns_none_rather_than_guessing():
    """'I do not know' must be representable.

    Returning the newest anyway is how a decision gets made from the wrong
    transcript, which is worse than making no decision at all.
    """
    assert session.pick_live_transcript([]) is None


def test_stale_only_candidates_return_none(tmp_path):
    old = tmp_path / "old.jsonl"
    old.write_text("x", encoding="utf-8")
    now = time.time()
    os.utime(old, (now - 10_000, now - 10_000))

    assert session.pick_live_transcript([old], max_age_seconds=900,
                                        now=now) is None


# ---------------------------------------------------------------------------
# RULE 2 — identify by launcher, never by process name
# ---------------------------------------------------------------------------

def test_orphan_search_matches_the_launcher_not_the_process_name():
    """A sweep matching on name would kill somebody else's assistant.

    Every agent on a machine is `python` or `node`. Only the launcher in the
    command line distinguishes 'mine' from 'one exactly like mine'.
    """
    pytest.importorskip("psutil")

    # Our own command line contains 'pytest'; it does not contain this.
    assert session.find_orphans("a-launcher-that-does-not-exist",
                                exclude_pid=-1) == []


def test_orphan_search_excludes_our_own_process():
    pytest.importorskip("psutil")
    assert os.getpid() not in session.find_orphans("python")


# ---------------------------------------------------------------------------
# Degrading honestly
# ---------------------------------------------------------------------------

def test_missing_psutil_refuses_rather_than_guessing(monkeypatch):
    """A degraded check that reports success is rule 6's exact failure."""
    def no_psutil():
        raise session.ProcessInspectionUnavailable("psutil is not installed")

    monkeypatch.setattr(session, "_psutil", no_psutil)

    with pytest.raises(session.ProcessInspectionUnavailable):
        session.verify_restart(time.time())
