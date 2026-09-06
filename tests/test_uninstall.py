"""Uninstalling, and the one thing it must never do.

The interesting question is not "does it delete the config folder". It is
"can it ever, under any arrangement of folders, delete something of the
user's". So most of what is below is adversarial: a workspace full of files, a
sandbox with a similar name, a plan built and then performed against a machine
that changed underneath it.

Written after the maintainer asked for an uninstall procedure on 2026-08-19, with the
requirement stated as: clean up everything, **never** remove user documents.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import paths, scaffold, uninstall
from aki_agent.config import Config, Layout


@pytest.fixture
def installed(tmp_path, monkeypatch) -> Path:
    """A real scaffolded install, with the home folder redirected."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(paths, "home", lambda: home)

    root = tmp_path / "Assistant"
    scaffold.build(scaffold.plan(root), confirmed=True)
    monkeypatch.setenv("AKI_AGENT_HOME", str(root / scaffold.CONFIG_DIR))
    paths.ensure_app_dirs()

    # Something of the user's, in their own project, which is the whole point.
    project = (root / scaffold.WORK_DIR / scaffold.DEFAULT_WORKSPACES[0]
               / scaffold.DEFAULT_PROJECTS[0])
    (project / "signed-contract.pdf").write_text("mine", encoding="utf-8")
    return root


def config_for(root: Path) -> Config:
    config = Config()
    config.layout = Layout(root=root,
                           workspaces=scaffold.DEFAULT_WORKSPACES)
    return config


# ---------------------------------------------------------------------------
# The rule


def test_the_users_work_is_never_on_the_removal_list(installed):
    """Stated in comments in three places; asserted here, from outside."""
    the_plan = uninstall.plan(config=config_for(installed), root=installed)

    removals = [str(item.path) for item in the_plan.removals if item.path]
    work = installed / scaffold.WORK_DIR

    assert not any(str(work) in path for path in removals)
    assert any(str(work) in str(item.path)
               for item in the_plan.kept if item.path), \
        "the work must be listed as kept, not merely left out"


def test_a_plan_that_named_the_work_would_refuse_rather_than_do_it(installed):
    """The failure has to be loud. A silent skip is how this goes wrong."""
    work = installed / scaffold.WORK_DIR
    reason = uninstall.refuse(work / scaffold.DEFAULT_WORKSPACES[0], installed)

    assert reason, "a path inside the work folder must be refused"
    assert "your work" in reason


def test_performing_checks_again_rather_than_trusting_the_plan(installed):
    """A plan can be built, sat on, and run against a changed machine."""
    doctored = uninstall.Plan(root=installed, removals=[
        uninstall.Item("folder", "the user's work",
                       installed / scaffold.WORK_DIR)])

    ok, message = uninstall.perform(doctored, confirmed=True,
                                    remove_plugin=False)

    assert not ok
    assert (installed / scaffold.WORK_DIR).is_dir(), "it deleted the work"
    assert "refused" in message


def test_a_folder_that_merely_looks_like_the_work_gets_no_protection(
        installed, tmp_path):
    """Protection is by path, not by name -- and the converse must hold too."""
    impostor = tmp_path / "elsewhere" / scaffold.WORK_DIR
    impostor.mkdir(parents=True)

    assert not uninstall.refuse(impostor, installed)


def test_it_will_not_remove_the_root_or_the_home_folder(installed):
    assert uninstall.refuse(installed, installed)
    assert uninstall.refuse(paths.home(), installed)


# ---------------------------------------------------------------------------
# What it does remove


def test_the_config_folder_is_removed_and_the_work_survives(installed):
    the_plan = uninstall.plan(config=config_for(installed), root=installed)
    ok, message = uninstall.perform(the_plan, confirmed=True,
                                    remove_plugin=False)

    contract = (installed / scaffold.WORK_DIR / scaffold.DEFAULT_WORKSPACES[0]
                / scaffold.DEFAULT_PROJECTS[0] / "signed-contract.pdf")

    assert ok, message
    assert not (installed / scaffold.CONFIG_DIR).exists()
    assert contract.read_text(encoding="utf-8") == "mine"
    assert not (installed / "CLAUDE.md").exists()


def test_nothing_happens_without_yes(installed):
    the_plan = uninstall.plan(config=config_for(installed), root=installed)
    ok, message = uninstall.perform(the_plan, confirmed=False)

    assert not ok
    assert (installed / scaffold.CONFIG_DIR).is_dir()
    assert "--yes" in message


def test_the_plan_says_what_stays_in_words_a_person_reads(installed):
    text = uninstall.plan(config=config_for(installed),
                          root=installed).describe()

    assert "left exactly as it is" in text
    assert "Your own documents are never removed." in text


def test_a_claude_md_the_user_wrote_themselves_is_kept(installed):
    """Ours carries a marker. Anything else is somebody's own notes."""
    (installed / "CLAUDE.md").write_text("# my own notes\n", encoding="utf-8")

    the_plan = uninstall.plan(config=config_for(installed), root=installed)

    assert any(item.path == installed / "CLAUDE.md" for item in the_plan.kept)
    assert not any(item.path == installed / "CLAUDE.md"
                   for item in the_plan.removals)


def test_the_plugin_is_named_so_a_person_can_run_it_themselves(installed):
    the_plan = uninstall.plan(config=config_for(installed), root=installed)
    plugin = [item for item in the_plan.removals if item.kind == "plugin"]

    assert plugin and "claude plugin uninstall" in plugin[0].detail


# ---------------------------------------------------------------------------
# Leftovers
#
# Both of the tests below exist because of a gap found by running the real
# thing rather than the suite: the sandbox and the top-level README were in
# neither list. Not removed, not reported as kept -- simply absent, so an
# "uninstall" left two folders behind and said nothing about them.


def test_nothing_of_ours_is_left_behind_at_the_root(installed):
    """The one assertion that catches a whole class of this.

    Naming the individual leftovers (as the two tests below do) only ever
    finds the leftover somebody thought of. Asserting on what is left in the
    folder finds the next one too.
    """
    the_plan = uninstall.plan(config=config_for(installed), root=installed)
    ok, message = uninstall.perform(the_plan, confirmed=True,
                                    remove_plugin=False)

    assert ok, message
    remaining = {entry.name for entry in installed.iterdir()}
    assert remaining == {scaffold.WORK_DIR}, (
        f"the user's work should be all that is left, found: {remaining}")


def test_the_sandbox_goes_and_the_plan_says_how_much_is_in_it(installed):
    """It is the assistant's desk, and the scaffolded README says outright
    that nothing in it is safe -- so removing it is the stated contract. The
    file count is shown because the plan is printed before `--yes`."""
    sandbox = installed / scaffold.SANDBOX_DIR
    (sandbox / "draft.md").write_text("scratch", encoding="utf-8")

    the_plan = uninstall.plan(config=config_for(installed), root=installed)
    listed = [item for item in the_plan.removals if item.path == sandbox]

    assert listed, "the sandbox was in neither list"
    assert "files" in (listed[0].detail or ""), "say how much is going"

    ok, message = uninstall.perform(the_plan, confirmed=True,
                                    remove_plugin=False)
    assert ok, message
    assert not sandbox.exists()


def test_an_old_style_sandbox_inside_the_work_folder_is_left_alone(installed):
    """Installs made before 2026-08-19 kept a sandbox inside each workspace.

    Those sit under the work folder, which is protected all the way down, so
    they stay with the work -- and, importantly, without a blocker: refusing
    loudly is right for a plan that named the work, wrong for a folder the
    plan should never have reached for in the first place.
    """
    old_sandbox = (installed / scaffold.WORK_DIR
                   / scaffold.DEFAULT_WORKSPACES[0] / "00_Sandbox")
    old_sandbox.mkdir(parents=True)
    (old_sandbox / "old-draft.md").write_text("keep me", encoding="utf-8")

    the_plan = uninstall.plan(config=config_for(installed), root=installed)

    assert not any(item.path == old_sandbox for item in the_plan.removals)
    assert not the_plan.blockers, the_plan.blockers

    uninstall.perform(the_plan, confirmed=True, remove_plugin=False)
    assert (old_sandbox / "old-draft.md").read_text(encoding="utf-8") == "keep me"


def test_the_readme_we_wrote_is_removed(installed):
    """It describes three folders that will not exist afterwards."""
    readme = installed / "README.md"

    assert readme.is_file(), "the scaffold should have written one"
    the_plan = uninstall.plan(config=config_for(installed), root=installed)

    assert any(item.path == readme for item in the_plan.removals)

    uninstall.perform(the_plan, confirmed=True, remove_plugin=False)
    assert not readme.exists()


def test_a_readme_the_user_rewrote_is_kept(installed):
    """Same marker test as CLAUDE.md: no marker, not ours, not our call."""
    readme = installed / "README.md"
    readme.write_text("# my folder, my words\n", encoding="utf-8")

    the_plan = uninstall.plan(config=config_for(installed), root=installed)

    assert any(item.path == readme for item in the_plan.kept)
    assert not any(item.path == readme for item in the_plan.removals)


# ---------------------------------------------------------------------------
# The plugin step
#
# It failed on every Windows machine and nobody could see it from the suite:
# a bare "claude" in an argument list is not found, because CreateProcess does
# not apply PATHEXT and the command is a .CMD shim. The uninstall reported it
# politely and carried on, which is exactly why it survived.


def test_the_plugin_step_runs_the_resolved_command_not_a_bare_name(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(uninstall.runner, "find_claude",
                        lambda: r"C:\tools\claude.CMD")
    monkeypatch.setattr(uninstall.subprocess, "run", fake_run)

    ok, message = uninstall._remove_plugin()

    assert ok, message
    assert seen["command"][0].endswith("claude.CMD"), (
        f"a bare name never runs on Windows: {seen['command'][0]}")


def test_a_missing_claude_is_said_plainly_rather_than_raised(monkeypatch):
    def missing():
        raise uninstall.runner.ClaudeNotFound("not here")

    monkeypatch.setattr(uninstall.runner, "find_claude", missing)

    ok, message = uninstall._remove_plugin()

    assert not ok
    assert "claude plugin uninstall" in message


def test_a_plugin_that_was_never_installed_is_not_a_failure(monkeypatch):
    """The normal case for a zip install, and it used to end on a red line."""

    class Result:
        returncode = 1
        stdout = ""
        stderr = ('Failed to uninstall plugin "aki-agent@aki-agent": '
                  'Plugin "aki-agent@aki-agent" not found in installed plugins')

    monkeypatch.setattr(uninstall.runner, "find_claude",
                        lambda: r"C:\tools\claude.CMD")
    monkeypatch.setattr(uninstall.subprocess, "run",
                        lambda command, **kwargs: Result())

    ok, message = uninstall._remove_plugin()

    assert ok, message
    assert "not installed" in message


def test_a_real_refusal_is_still_reported_as_one(monkeypatch):
    class Result:
        returncode = 1
        stdout = ""
        stderr = "permission denied"

    monkeypatch.setattr(uninstall.runner, "find_claude",
                        lambda: r"C:\tools\claude.CMD")
    monkeypatch.setattr(uninstall.subprocess, "run",
                        lambda command, **kwargs: Result())

    ok, message = uninstall._remove_plugin()

    assert not ok
    assert "permission denied" in message
