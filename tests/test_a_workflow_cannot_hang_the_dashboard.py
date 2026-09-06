"""`run` is called from a web request, so it must always come back.

Two defects, both in the same four lines. A workflow that waited forever held
the dashboard request open forever -- no page, no way to stop it from the
interface that started it, and nothing to distinguish it from "still
working". And a workflow that failed came back as a return code and an empty
string, so the page said it had failed and could not say why: the workflow's
own explanation went to the dashboard's stdout, where nobody is looking.
"""
from __future__ import annotations

import textwrap
import time

import pytest

from aki_agent import workflows


@pytest.fixture
def workflow_folder(tmp_path, monkeypatch):
    """A workflows folder of this test's own, with one workflow in it."""
    folder = tmp_path / "workflows"
    folder.mkdir(parents=True)
    monkeypatch.setattr(workflows, "workflows_dir", lambda: folder)
    monkeypatch.setattr(workflows, "is_on", lambda name: True)
    return folder


def _make(folder, name, script, timeout_line=""):
    where = folder / name
    where.mkdir(parents=True, exist_ok=True)
    (where / workflows.MANIFEST).write_text(
        "---\n"
        f"name: {name}\n"
        f"title: {name}\n"
        "entry: run.py\n"
        f"{timeout_line}"
        "---\n\nA workflow.\n", encoding="utf-8")
    (where / "run.py").write_text(textwrap.dedent(script), encoding="utf-8")
    return where


def test_a_workflow_that_never_finishes_is_stopped(workflow_folder):
    """Twenty seconds, not ten minutes, and deliberately.

    Written first with `sleep(600)`, this test proved the point by hanging
    for ten minutes against the unfixed code -- which is a true result and a
    useless one. A test that catches a regression by never finishing is a
    test somebody eventually kills and skips. Twenty seconds is long enough
    that a two-second timeout is unambiguously doing the work, and short
    enough that the failure arrives as a failure.
    """
    _make(workflow_folder, "hangs", """
        import time
        time.sleep(20)
        """, timeout_line="timeout_seconds: 2\n")

    started = time.time()
    code, message = workflows.run("hangs")
    took = time.time() - started

    assert code != 0
    assert "still running" in message, message
    assert took < 10, f"it waited {took:.0f}s -- the timeout did not apply"


def test_a_workflow_that_fails_says_why(workflow_folder):
    _make(workflow_folder, "breaks", """
        import sys
        print("the input file was not where the manifest said", file=sys.stderr)
        sys.exit(3)
        """)

    code, message = workflows.run("breaks")
    assert code == 3
    assert "the input file was not where the manifest said" in message, message


def test_a_workflow_that_fails_silently_still_says_something(workflow_folder):
    """Nothing printed, non-zero code. The page must not show a blank."""
    _make(workflow_folder, "quiet", """
        import sys
        sys.exit(4)
        """)

    code, message = workflows.run("quiet")
    assert code == 4
    assert message.strip(), "a failure came back with nothing to show"


def test_a_workflow_that_works_is_left_alone(workflow_folder):
    _make(workflow_folder, "fine", """
        print("done")
        """)
    code, message = workflows.run("fine")
    assert code == 0
    assert message == ""


def test_a_manifest_asking_for_forever_gets_the_default(workflow_folder):
    """An unreadable timeout is a mistake to fall back from, never a licence
    to wait indefinitely."""
    _make(workflow_folder, "silly", """
        print("hello")
        """, timeout_line="timeout_seconds: forever\n")

    found = workflows.get("silly")
    assert found is not None
    assert found.timeout == workflows.DEFAULT_RUN_TIMEOUT


def test_a_declared_timeout_is_honoured(workflow_folder):
    _make(workflow_folder, "patient", """
        print("hello")
        """, timeout_line="timeout_seconds: 60\n")

    found = workflows.get("patient")
    assert found is not None and found.timeout == 60
