"""The chain that made a dead install report itself healthy.

Four faults that covered for each other. Fixed together on 2026-08-23, and
tested together here, because fixing any one alone only moves where the lie
is told.
"""
import subprocess

import pytest

from aki_agent import doctor, schedule


def test_a_refused_query_is_not_an_empty_list(monkeypatch):
    """"Nothing installed" and "could not ask" must not be the same answer.

    They were the same empty list, and on a Traditional Chinese Windows the
    query always fell into the second case -- schtasks localises its field
    labels, so the old `startswith("taskname:")` parse matched nothing for
    ever. Every caller then behaved as though the user had no tasks.
    """
    class Refused:
        returncode, stdout, stderr = 1, "", "ERROR: Access is denied."

    monkeypatch.setattr(schedule.paths, "is_windows", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Refused())

    with pytest.raises(schedule.CouldNotAsk):
        schedule.installed_names()

    # And the display-only helper still answers, on purpose.
    assert schedule.installed_names_or_empty() == []


def test_the_name_is_read_from_a_column_not_a_label(monkeypatch):
    """Localised field labels must not hide a task.

    The CSV form puts the name in the first column whatever the display
    language is. This feeds it output whose labels are in Chinese -- the
    exact case that returned [] before.
    """
    class Listed:
        returncode, stderr = 0, ""
        stdout = ('"\\AkiAgent-morning-summary","2026/8/24 8:00:00","就緒"\n'
                  '"\\SomebodyElsesJob","2026/8/24 9:00:00","就緒"\n')

    monkeypatch.setattr(schedule.paths, "is_windows", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Listed())

    assert schedule.installed_names() == ["AkiAgent-morning-summary"]


def test_doctor_does_not_call_missing_work_healthy(monkeypatch):
    """Five of six gone used to print [OK ].

    `Check("Scheduled work", True, ...)` while listing what was missing. A
    check that names the breakage and then reports itself as passing is worse
    than no check: it is what a worried person opens first.
    """
    defined = [one for one in schedule.all_tasks() if one.enabled]
    assert len(defined) > 1, "this test needs more than one default task"

    only_one = [f"{schedule.TASK_PREFIX}-{defined[0].key}"]
    monkeypatch.setattr(schedule, "installed_names", lambda: only_one)

    result = doctor.check_schedule()
    assert result.ok is False, "missing scheduled work reported as healthy"
    assert result.fix, "no way out offered"


def test_the_summary_never_calls_broken_work_optional():
    """The word that sent people away.

    Every check here is warning_only, so this line was what a student saw
    when their automation was gone: "Everything essential is working. 6
    optional thing(s) are not set up."
    """
    report = doctor.format_report([
        doctor.Check("Scheduled work", False, warning_only=True,
                     detail="nothing installed"),
    ])
    assert "optional" not in report.lower()
    assert "Everything essential is working" not in report
