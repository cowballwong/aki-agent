"""The command surface the skills call, and the skills that call it.

Two things are checked here, and the second one is the one that has already
been got wrong twice in this codebase:

1. Each command behaves when there is nothing there — no config, no memory,
   no projects. That is the state of every machine on its first day, and a
   traceback at that moment is the whole first impression.
2. **Every command a shipped skill tells the assistant to run actually
   exists.** A skill is markdown; nothing compiles it, nothing type-checks it,
   and a command that was renamed leaves the skill looking perfectly healthy
   while doing nothing at all. This is the "correct mechanism, nothing wired
   to it" shape, one level up.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aki_agent import cli, memory, paths, specialists


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = PACKAGE_ROOT / "skills"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


def run(capsys, *argv) -> tuple[int, str]:
    code = cli.main(list(argv))
    return code, capsys.readouterr().out


# ---------------------------------------------------------------------------
# The empty machine


def test_search_on_an_empty_machine_says_so_in_words(capsys):
    code, out = run(capsys, "search", "anything")
    assert code == 0
    assert "Nothing remembered" in out


def test_projects_without_a_config_explains_itself_once(capsys):
    """And does not stack two instructions on top of each other.

    The first version appended "Run /setup to create one." to a message that
    already ended "…in Claude Code, type /setup." The result read as sloppy in
    the very first command a new user runs.
    """
    code, out = run(capsys, "projects")

    assert code == 1
    assert "/aki-agent:setup" in out
    assert out.count("/aki-agent:setup") == 1


def _configured(tmp_path) -> Path:
    """A config pointing at a workspace folder that does not exist yet."""
    from aki_agent import config as config_module

    config = config_module.Config()
    config.layout.root = tmp_path / "Aki-Agent"
    config_module.save(config)
    return config.layout.root


def test_the_scaffold_is_reachable_as_a_command(tmp_path, capsys):
    """The gap that produced a workspace with folders and nothing in them.

    `scaffold.plan()`/`build()` were reachable only from Python, and the only
    thing that runs at setup is a markdown skill. So the folders got made by
    hand and every file the scaffold writes -- CLAUDE.md, the READMEs,
    `.claude/`, the sandbox, the summary files -- was never created, with
    nothing reporting a failure because nothing ran.
    """
    from aki_agent import scaffold

    root = _configured(tmp_path)

    code, out = run(capsys, "scaffold", "--workspaces", "work,church")
    assert code == 0
    assert "CLAUDE.md" in out
    assert not root.exists(), "planning must write nothing"

    code, out = run(capsys, "scaffold", "--workspaces", "work,church", "--yes")
    work = root / scaffold.WORK_DIR / "01_work"

    assert code == 0
    assert (root / "CLAUDE.md").exists()
    assert (root / ".claude" / "skills").is_dir()
    assert (root / scaffold.CONFIG_DIR).is_dir()
    assert (root / scaffold.SANDBOX_DIR / "README.md").exists()
    assert (work / scaffold.DEFAULT_PROJECTS[0] / "state.md").exists()


def test_the_scaffold_records_the_names_it_actually_created(tmp_path, capsys):
    """The config and the folders come from one command, so they cannot drift.

    Written as the numbered names, not the words the user said: `work` beside a
    folder called `01_work` is the mismatch that showed as an empty dashboard.
    """
    from aki_agent import config as config_module

    _configured(tmp_path)
    run(capsys, "scaffold", "--workspaces", "work,church", "--yes")

    assert config_module.load().layout.workspaces == ("01_work", "02_church")


def test_running_the_scaffold_twice_changes_nothing(tmp_path, capsys):
    """Which is what makes it the repair for an install that missed pieces."""
    root = _configured(tmp_path)
    run(capsys, "scaffold", "--workspaces", "work", "--yes")
    (root / "CLAUDE.md").write_text("mine, edited\n", encoding="utf-8")

    code, out = run(capsys, "scaffold", "--workspaces", "work", "--yes")

    assert code == 0
    assert "Nothing to do" in out
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == "mine, edited\n"


def test_recall_and_today_are_calm_when_there_is_nothing(capsys):
    assert run(capsys, "recall")[0] == 0
    assert run(capsys, "today")[0] == 0


def test_an_unexpected_failure_never_shows_a_traceback(capsys, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("the drive fell off")

    monkeypatch.setattr(memory, "search", explode)
    code, out = run(capsys, "search", "x")

    assert code == 1
    assert "That did not work" in out
    assert "Traceback" not in out
    assert "RuntimeError" not in out


# ---------------------------------------------------------------------------
# Writing


def test_remember_then_find_it_again(capsys):
    run(capsys, "remember", "client", "prefers", "bad", "news", "first")
    code, out = run(capsys, "search", "bad news")

    assert code == 0
    assert "bad news first" in out


def test_a_fact_written_in_chinese_is_searchable_in_chinese(capsys):
    run(capsys, "remember", "客戶想先聽壞消息")
    code, out = run(capsys, "search", "壞消息")

    assert code == 0
    assert "客戶" in out


def test_log_writes_to_todays_file(capsys):
    code, out = run(capsys, "log", "decided", "to", "postpone")
    assert code == 0
    assert "postpone" in memory.read_day()


# ---------------------------------------------------------------------------
# Specialists


def test_two_specialists_named_in_chinese_do_not_collide(capsys):
    """The `memory` slug bug, found again in `specialists.save`.

    Names were slugged with `[^a-z0-9]`, so a name written entirely in Chinese
    produced an empty slug and fell back to the constant "specialist" — and
    the second one silently replaced the first, because `save()` drops any
    entry sharing the new key.

    Nothing errors. The user creates two and sees one. It happens only to
    people who do not name things in Latin script.
    """
    run(capsys, "new-specialist", "合約審閱員", "--purpose", "睇合約", "--brief", "x")
    run(capsys, "new-specialist", "文件校對員", "--purpose", "校對", "--brief", "x")

    keys = [one.key for one in specialists.read_all()]
    assert len(set(keys)) == 2, f"collided into {keys}"
    assert len(specialists.read_all()) == 2


def test_a_new_specialist_cannot_write_unless_asked(capsys):
    run(capsys, "new-specialist", "Reader", "--purpose", "reads", "--brief", "x")
    assert specialists.read_all()[0].may_write is False


def test_an_incomplete_specialist_is_reported_not_silently_accepted(capsys):
    code, out = run(capsys, "new-specialist", "Nameless", "--purpose", "")

    assert code == 1
    assert "needs" in out.lower()


# ---------------------------------------------------------------------------
# The skills and the commands they call


def _skill_files() -> list[Path]:
    return sorted(SKILLS_DIR.glob("*/SKILL.md"))


def test_every_skill_has_the_frontmatter_that_makes_it_load():
    for path in _skill_files():
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\n"), path.name
        assert re.search(r"^name: \S+", text, re.M), path.name
        description = re.search(r"^description: (.+)$", text, re.M)
        assert description, path.name
        # A description that does not say *when* to use it is the single
        # commonest reason a skill exists and never triggers.
        assert len(description.group(1)) > 80, f"{path.name}: too vague"


def test_the_skill_name_matches_its_folder():
    """Claude Code loads by folder; a mismatch is invisible until it is not."""
    for path in _skill_files():
        declared = re.search(r"^name: (\S+)", path.read_text(encoding="utf-8"),
                             re.M).group(1)
        assert declared == path.parent.name, path


def test_every_cli_command_a_skill_mentions_actually_exists():
    """The check that catches a rename before a user does.

    Nothing compiles a markdown file. A skill that says `cli summarise` when
    the command is `cli today` fails at the moment a person is watching, and
    looks like the assistant being stupid rather than a typo.
    """
    known = set(cli.build_parser()._subparsers._group_actions[0].choices)

    for path in _skill_files():
        for referenced in re.findall(r"aki_agent\.cli\s+([a-z-]+)",
                                     path.read_text(encoding="utf-8")):
            if referenced == "--help":
                continue
            assert referenced in known, (
                f"{path.parent.name} calls `cli {referenced}`, "
                f"which does not exist. Known: {sorted(known)}")


def test_no_skill_tells_the_assistant_to_write_into_documents():
    """The rule, checked in the place it would actually be broken.

    A skill is the most likely route to a document being changed without
    approval, because it is the part a user can rewrite themselves.
    """
    for path in _skill_files():
        text = path.read_text(encoding="utf-8").lower()
        if "02_documents" not in text:
            continue
        assert ("approv" in text or "ask" in text or "never" in text), (
            f"{path.parent.name} mentions the documents folder without "
            "mentioning approval")


# ---------------------------------------------------------------------------
# More than one agent on one machine


def test_a_second_agent_gets_its_own_everything(tmp_path, monkeypatch):
    """Two professions on one laptop, each with its own memory.

    The engine could already read two different configs -- that is what
    `test_two_configs.py` proves. What it could not do was *write* to two
    places: config, memory, specialists and state all resolved to one folder,
    so a second agent would have quietly shared the first one's mind.
    """
    first = tmp_path / "architect"
    second = tmp_path / "teacher"

    monkeypatch.setenv("AKI_AGENT_HOME", str(first))
    paths.ensure_app_dirs()
    memory.remember("drawings are issued on Fridays")

    monkeypatch.setenv("AKI_AGENT_HOME", str(second))
    paths.ensure_app_dirs()

    assert paths.app_dir() == second
    assert memory.recall() == [], "the second agent can see the first's memory"

    memory.remember("reports go out at half term")
    assert len(memory.recall()) == 1

    monkeypatch.setenv("AKI_AGENT_HOME", str(first))
    summaries = [fact.summary for fact in memory.recall()]
    assert summaries == ["drawings are issued on Fridays"]


def test_without_the_variable_nothing_changes(tmp_path, monkeypatch):
    monkeypatch.delenv("AKI_AGENT_HOME", raising=False)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)

    assert paths.app_dir() == tmp_path / paths.APP_DIR_NAME


# ---------------------------------------------------------------------------
# The continuity chain: something writes the handoff, something reads it,
# and something installs the schedule that drives both.
#
# All three mechanisms existed and shipped dormant — the checkpoint was only
# reachable from a scheduled task nobody installed, the state was only read by
# the dashboard, and setup never mentioned either. Each test below guards one
# link, because every one of them fails silently: the symptom is an absence.


def test_state_on_a_machine_that_has_never_checkpointed_says_so(capsys):
    code, out = run(capsys, "state")
    assert code == 0
    assert "Nothing saved yet" in out


def test_checkpoint_then_state_reads_back_what_was_written(capsys):
    memory.write_working_state(memory.WorkingState(
        generated_at=__import__("datetime").datetime.now(),
        open_items=["the tender letter"],
        waiting_on=["the structural engineer"]))

    code, out = run(capsys, "state")
    assert code == 0
    assert "the tender letter" in out
    assert "the structural engineer" in out


def test_schedule_install_without_yes_installs_nothing(capsys, monkeypatch):
    from aki_agent import schedule

    def refuse(*args, **kwargs):
        raise AssertionError("nothing may be scheduled without --yes")

    monkeypatch.setattr(schedule, "install", refuse)
    code, out = run(capsys, "schedule-install")
    assert code == 0
    assert "Nothing has been scheduled" in out


def test_schedule_status_names_what_is_lost_when_nothing_is_installed(
        capsys, monkeypatch):
    from aki_agent import schedule

    monkeypatch.setattr(schedule, "installed_names", lambda: [])
    code, out = run(capsys, "schedule-status")
    assert code == 0
    assert "schedule-install --yes" in out
    assert "NOT installed" in out


def test_doctor_fails_the_machine_where_nothing_is_scheduled(monkeypatch):
    from aki_agent import doctor, schedule

    monkeypatch.setattr(schedule, "installed_names", lambda: [])
    check = doctor.check_schedule()
    assert not check.ok
    assert "schedule-install" in check.fix


def test_the_scaffolded_notes_tell_the_assistant_to_read_the_handoff():
    from aki_agent import scaffold

    notes = scaffold._content_for(Path("CLAUDE.md"), schema=None,
                                  assistant_name="Bo", user_name="Wing",
                                  root=Path("."))
    assert "session-state" in notes, (
        "a handoff nothing reads is the same as no handoff")
    assert (SKILLS_DIR / "session-state" / "SKILL.md").exists(), (
        "the notes point at a skill that does not ship")


def test_setup_does_not_interview_anybody_about_notifications():
    """reported 2026-08-17: don't ask — they can set it in the dashboard.

    On install day nobody knows what they want to be interrupted about, so the
    answers are guesses that then look like decisions. The bracketed
    `[config.key]` form is how this skill marks something to ask for, so its
    absence is what this checks -- along with the two things that must remain
    true for the answer "change it later" to be honest.
    """
    setup = (SKILLS_DIR / "setup" / "SKILL.md").read_text(encoding="utf-8")

    for question in ("[notifications.quiet_hours]", "[notifications.enabled]",
                     "[notifications.urgent_keywords]"):
        assert question not in setup, f"setup still interviews about {question}"

    assert "Settings" in setup, "nobody is told where to change it"
    assert "Schedule" in setup, "nor where to change the scheduled tasks"


def test_setup_turns_the_schedule_on_and_points_at_the_dashboard():
    setup = (SKILLS_DIR / "setup" / "SKILL.md").read_text(encoding="utf-8")
    assert "schedule-install --yes" in setup, (
        "setup that leaves nothing scheduled ships a dormant assistant")
    assert "dashboard.bat" in setup, (
        "the only route to the schedule page is one the user is never told about")


def test_no_skill_uses_a_path_relative_to_wherever_the_user_happens_to_be():
    """A relative path in a skill resolves from the USER'S folder.

    Not the plugin's. So `python bin/_bootstrap.py ...` only ran when the user
    was sitting inside the unzipped package — which is why installs ended up
    treating the installer as the assistant's home folder.

    The rule is about where the path starts from, not about which mechanism
    supplies it. That distinction matters, because the mechanism changed on
    2026-08-23: skills used to say `${CLAUDE_PLUGIN_ROOT}/bin/_bootstrap.py`,
    and that variable is NOT set in the environment of an ordinary Bash call —
    only in plugin hooks and slash-command frontmatter. It expanded to nothing,
    so the student's first screen was `can't open file '/bin/_bootstrap.py'`.

    A skill therefore starts from `~`, which means the same thing whatever
    folder anybody happens to be standing in.
    """
    offenders = []
    for skill in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        text = skill.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "_bootstrap.py" not in line and "aki.py" not in line:
                continue
            if "~/" in line:
                continue
            offenders.append(f"{skill.parent.name}: {line.strip()}")
    assert not offenders, (
        "these do not start from a place that means the same on every "
        "machine:\n" + "\n".join(offenders))


def test_no_skill_still_expects_the_plugin_root_variable():
    """It is empty where skills run, and an empty path fails in the worst way.

    `python "${CLAUDE_PLUGIN_ROOT}/bin/_bootstrap.py"` became
    `python "/bin/_bootstrap.py"`. A model usually recovers from that by
    guessing a path, and a wrong guess runs a stale copy of the package from
    an old install — which looks like it worked.
    """
    offenders = [skill.parent.name
                 for skill in sorted(SKILLS_DIR.glob("*/SKILL.md"))
                 if "${CLAUDE_PLUGIN_ROOT}" in
                 skill.read_text(encoding="utf-8")]
    assert not offenders, (
        f"{offenders} expect a variable that is not set where skills run")


def test_setup_tells_them_the_installer_can_be_deleted():
    """Otherwise the download becomes the assistant, and the next release
    either overwrites their work or gets kept forever beside it."""
    setup = (SKILLS_DIR / "setup" / "SKILL.md").read_text(encoding="utf-8")
    assert "delete the zip" in setup
    assert ".aki-agent" in setup, "say where their assistant actually lives"


def test_a_fresh_install_lands_in_the_folder_claude_code_is_running_in(
        tmp_path, capsys, monkeypatch):
    """"Install it here" (reported 2026-08-19), with no question asked.

    Setup used to ask where the assistant should live, and twice the answer
    and the folders on disk disagreed -- an empty dashboard and no error. The
    current folder is the one answer that cannot disagree with anything.
    """
    from aki_agent import config as config_module, scaffold

    here = tmp_path / "wherever-they-opened-the-terminal"
    here.mkdir()
    monkeypatch.chdir(here)
    config_module.save(config_module.Config())        # no root recorded

    code, out = run(capsys, "scaffold", "--yes")

    assert code == 0
    assert "Installing here" in out
    for folder in (scaffold.CONFIG_DIR, scaffold.SANDBOX_DIR,
                   scaffold.WORK_DIR):
        assert (here / folder).is_dir(), f"{folder} was not created in {here}"

    # And the config now agrees with the disk, from the one command that made
    # both -- which is the whole reason the mismatch cannot come back.
    assert config_module.load().layout.root == here


def test_a_skill_that_asks_for_a_number_shows_the_numbers():
    """reported 2026-08-20: "it did not give me MC". The upgrade skill said
    *reply with a number* and drew nothing. A number belongs to an option; on
    its own it is a riddle.

    Every skill that asks for a numbered answer must also call the command
    that draws one.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    offences = []

    for path in (root / "skills").rglob("SKILL.md"):
        text = path.read_text(encoding="utf-8")
        asks = "reply with a number" in text.lower()
        draws = "screen menu" in text
        if asks and not draws:
            offences.append(path.parent.name)

    assert not offences, (
        "these ask for a number without drawing the options: "
        + ", ".join(offences))
