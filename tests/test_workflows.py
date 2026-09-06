"""Workflows: a whole job, installed as a folder.

The distinction this file exists to defend (settled on 2026-08-29,
written down in `docs/PACKAGES.md`): a skill is one move, a workflow is a job.
A workflow owns a project folder, carries sign-off gates, resumes after a stop
and ends in something you hand to somebody else. A feasibility study is a
workflow; writing an email is a skill.

Two properties matter more than the features:

* **Nothing is imported to list one.** A workflow is described entirely from
  its `WORKFLOW.md`, so a workflow with a syntax error still lists cleanly and
  says so only when you try to run it. `test_a_broken_workflow_still_lists`
  is the one that proves it.
* **Nothing runs on install.** Installing copies a folder. Running is a
  separate, explicit act, because that is when somebody else's code executes
  as the user.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from aki_agent import plugins, workflows


MANIFEST = """---
name: feasibility
version: 0.1.0
title: Feasibility study
description: A development appraisal, start to finish.
entry: run.py
deliverable: report.pdf
gates: [brief signed off, drawings signed off]
requires_capabilities: [drawing]
---

# Feasibility study

Long prose a person reads before installing.
"""


def _write_workflow(folder: Path, manifest: str = MANIFEST,
                    entry: str | None = "print('ran')\n") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "WORKFLOW.md").write_text(manifest, encoding="utf-8")
    if entry is not None:
        (folder / "run.py").write_text(entry, encoding="utf-8")
    return folder


@pytest.fixture(autouse=True)
def empty_workflows_dir(monkeypatch):
    """No test may see the workflows the person running it happens to have.

    The same rule as `no_installed_plugins` in `conftest.py`, for the same
    reason: a suite whose result depends on what the author installed proves
    nothing to the student running it.
    """
    folder = Path(tempfile.mkdtemp(prefix="aki-test-workflows-"))
    monkeypatch.setattr(workflows, "workflows_dir", lambda: folder)
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# --------------------------------------------------------------- describing

def test_a_workflow_is_described_from_its_manifest(empty_workflows_dir):
    _write_workflow(empty_workflows_dir / "feasibility")

    found, problems = workflows.installed()

    assert problems == []
    assert len(found) == 1
    one = found[0]
    assert one.name == "feasibility"
    assert one.title == "Feasibility study"
    assert one.deliverable == "report.pdf"
    assert one.gates == ("brief signed off", "drawings signed off")
    assert one.requires == ("drawing",)


def test_a_broken_workflow_still_lists_and_fails_only_when_run(
        empty_workflows_dir):
    """The property that makes listing safe.

    Its entry file is not valid Python. If listing imported anything, this
    test would raise during `installed()` instead of reaching the assertion.
    """
    _write_workflow(empty_workflows_dir / "feasibility",
                    entry="def broken(:\n")

    found, problems = workflows.installed()

    assert problems == []
    assert found[0].title == "Feasibility study"

    code, _message = workflows.run("feasibility")
    assert code != 0


def test_a_folder_with_no_manifest_is_reported_rather_than_ignored(
        empty_workflows_dir):
    """Somebody who unzipped one level too deep should be told, not left
    wondering why nothing appeared."""
    (empty_workflows_dir / "loose").mkdir()
    (empty_workflows_dir / "loose" / "run.py").write_text("x = 1\n",
                                                          encoding="utf-8")

    found, problems = workflows.installed()

    assert found == []
    assert "WORKFLOW.md" in problems[0]


def test_a_workflow_with_no_entry_is_reference_only(empty_workflows_dir):
    """Readable but not runnable is a legitimate state, not an error: a
    workflow written as instructions for a person still belongs on the list."""
    _write_workflow(empty_workflows_dir / "feasibility",
                    manifest=MANIFEST.replace("entry: run.py\n", ""),
                    entry=None)

    found, problems = workflows.installed()

    assert problems == []
    assert found[0].entry == ""
    assert found[0].problem == ""


# ----------------------------------------------------------------- consent

def test_nothing_is_copied_until_somebody_says_yes(empty_workflows_dir,
                                                   tmp_path):
    source = _write_workflow(tmp_path / "feasibility")

    candidate = workflows.examine(str(source))
    text = workflows.consent_text(candidate)

    assert "Feasibility study" in text
    assert list(empty_workflows_dir.iterdir()) == []
    workflows.cleanup(candidate)


def test_installing_copies_the_folder_and_runs_none_of_it(empty_workflows_dir,
                                                          tmp_path):
    """A workflow that tried to run at install time would be a workflow that
    ran before anyone agreed to it. So the entry file here writes a file: if
    installing executed anything, that file would exist."""
    source = _write_workflow(
        tmp_path / "feasibility",
        entry="from pathlib import Path\nPath(r'%s').write_text('x')\n"
              % (tmp_path / "evidence.txt"))

    candidate = workflows.examine(str(source))
    ok, _message = workflows.install(candidate)
    workflows.cleanup(candidate)

    assert ok
    assert (empty_workflows_dir / "feasibility" / "WORKFLOW.md").is_file()
    assert not (tmp_path / "evidence.txt").exists()


def test_installing_over_an_existing_one_is_flagged_before_it_happens(
        empty_workflows_dir, tmp_path):
    _write_workflow(empty_workflows_dir / "feasibility")
    source = _write_workflow(tmp_path / "feasibility")

    candidate = workflows.examine(str(source))
    warnings = " ".join(candidate.warnings)
    workflows.cleanup(candidate)

    assert "already installed" in warnings


def test_removing_one_takes_the_whole_folder(empty_workflows_dir):
    _write_workflow(empty_workflows_dir / "feasibility")

    ok, _message = workflows.remove("feasibility")

    assert ok
    assert not (empty_workflows_dir / "feasibility").exists()


# ------------------------------------------------------- carried in a box

def test_a_workflow_inside_a_plugin_is_found(empty_workflows_dir):
    """The package model: a plugin is a box, and a whole trade arrives in one.

    Nothing is copied out of the box on install — each registry looks in —
    so deleting the plugin folder takes its workflows with it and leaves
    nothing behind. See `docs/PACKAGES.md`.
    """
    box = plugins.plugins_dir() / "hk-feasibility"
    box.mkdir(parents=True)
    (box / "PLUGIN.md").write_text("---\nname: hk-feasibility\n---\n",
                                   encoding="utf-8")
    _write_workflow(box / "workflows" / "feasibility")

    found, _problems = workflows.installed()

    assert [one.name for one in found] == ["feasibility"]


def test_one_installed_by_hand_beats_a_plugins_of_the_same_name(
        empty_workflows_dir):
    """What somebody put there themselves wins — the same precedence rule the
    rest of the system uses for anything a person can override."""
    box = plugins.plugins_dir() / "hk-feasibility"
    box.mkdir(parents=True)
    (box / "PLUGIN.md").write_text("---\nname: hk-feasibility\n---\n",
                                   encoding="utf-8")
    _write_workflow(box / "workflows" / "feasibility",
                    manifest=MANIFEST.replace("Feasibility study",
                                              "The plugin's one"))
    _write_workflow(empty_workflows_dir / "feasibility")

    found, _problems = workflows.installed()

    assert len(found) == 1
    assert found[0].title == "Feasibility study"
