"""Standing instructions the user writes, and the line between told and cannot.

The failure to avoid is not "the page does not save". It is a page that makes
somebody believe their assistant is *unable* to do something when it has
merely been *asked* not to — because that is the belief on which they decide
how much to leave it running unattended.
"""

from __future__ import annotations

import pytest

from aki_agent import house_rules, paths


@pytest.fixture
def home(tmp_path, monkeypatch):
    folder = tmp_path / "01_Config"
    folder.mkdir(parents=True)
    monkeypatch.setattr(paths, "app_dir", lambda: folder)
    return folder


# ---------------------------------------------------------------------------
# Keeping them
# ---------------------------------------------------------------------------

def test_no_rules_is_a_normal_state_not_an_error(home):
    assert house_rules.read() == []


def test_a_rule_survives_the_round_trip(home):
    house_rules.add("No email goes out until I have seen it.")
    assert house_rules.read() == ["No email goes out until I have seen it."]


def test_order_is_kept(home):
    for rule in ("First.", "Second.", "Third."):
        house_rules.add(rule)
    assert house_rules.read() == ["First.", "Second.", "Third."]


def test_the_same_rule_twice_is_refused(home):
    house_rules.add("Ask before spending money.")
    ok, message = house_rules.add("ask BEFORE spending money.")

    assert not ok
    assert "already there" in message
    assert len(house_rules.read()) == 1


def test_an_empty_rule_is_refused(home):
    assert house_rules.add("   ")[0] is False


def test_a_paragraph_is_refused_with_a_reason(home):
    ok, message = house_rules.add("x" * 500)

    assert not ok
    assert "hold in their head" in message


def test_a_rule_can_be_removed(home):
    house_rules.add("One.")
    house_rules.add("Two.")

    assert house_rules.remove("One.")[0]
    assert house_rules.read() == ["Two."]


def test_removing_one_that_is_not_there_says_so(home):
    assert house_rules.remove("never written")[0] is False


# ---------------------------------------------------------------------------
# The file the assistant reads
# ---------------------------------------------------------------------------

def test_the_file_tells_the_reader_to_follow_them(home):
    """It is read by a model at the start of a session, so the file itself has
    to say what it is. A bare list reads as notes."""
    house_rules.add("Ask first.")
    text = house_rules.rules_file().read_text(encoding="utf-8")

    assert "Follow them" in text
    assert "not the same as the safety gate" in text


def test_the_file_says_when_it_last_changed(home):
    house_rules.add("Ask first.")
    assert "Last changed" in house_rules.rules_file().read_text(
        encoding="utf-8")


def test_an_empty_list_still_writes_a_readable_file(home):
    house_rules.add("One.")
    house_rules.remove("One.")

    text = house_rules.rules_file().read_text(encoding="utf-8")
    assert "None set" in text


def test_the_workspace_notes_point_at_the_file(home):
    """A rule that only lives in a dashboard is decoration. This is the wire
    between the page and the assistant, so it is tested."""
    from aki_agent import scaffold

    notes = scaffold.mirror_section()

    assert "house rules" in notes.lower()
    assert str(house_rules.rules_file()) in notes


def test_the_agent_is_told_to_follow_them():
    from pathlib import Path

    persona = (Path(__file__).resolve().parents[1] / "agents"
               / "assistant.md").read_text(encoding="utf-8")

    assert "house rules" in persona.lower()
    assert "outrank your own judgement" in persona
    assert "each session rather than remembering" in persona


# ---------------------------------------------------------------------------
# Told versus cannot
# ---------------------------------------------------------------------------

def test_a_rule_that_is_also_enforced_says_where():
    """the maintainer's own example. `connectors/mail.send` refuses without an explicit
    yes, every message — so this one has teeth and should say so."""
    backing = house_rules.backed_by_code(
        "No email goes out until I have seen it.")

    assert backing is not None
    assert "mail" in backing.where


def test_an_ordinary_rule_claims_no_enforcement():
    """Claiming enforcement that does not exist is worse than claiming none:
    it is the difference between careful and unable, and somebody leaving an
    agent running unattended is making exactly that judgement."""
    assert house_rules.backed_by_code(
        "Write in British English, not American.") is None


def test_the_backed_list_stays_short():
    """Every entry is a promise. A long list of them is a long list of things
    that have to stay true."""
    assert len(house_rules.BACKED) <= 5


def test_suggestions_are_not_written_by_being_offered(home):
    """A rule somebody did not choose is one they will not remember agreeing
    to, and the first time it gets in their way they distrust the whole
    list."""
    assert house_rules.SUGGESTIONS
    assert house_rules.read() == []


# ---------------------------------------------------------------------------
# The wire has to reach an install that already exists
# ---------------------------------------------------------------------------

def test_an_older_workspace_gains_the_house_rules_line(home, tmp_path):
    """THE BUG THIS EXISTS FOR (2026-08-20)

    `top_up` was one block guarded by one test: if the file already mentions
    `aki_agent.inbox`, there is nothing to do. True for exactly as long as
    there was one block.

    The day house rules shipped, every existing install upgraded, got the new
    page, and did NOT get the line telling the assistant to read the rules
    file — because their CLAUDE.md already mentioned the inbox. They would
    have had a page saving rules that nothing ever read.

    Found by reading a real upgrade log and noticing a step that was absent.
    """
    from aki_agent import scaffold

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "CLAUDE.md").write_text(
        "# My assistant\n\nNotes I wrote myself.\n\n"
        "## Keeping the chat in one piece\n\n"
        "python \"x/bin/_bootstrap.py\" aki_agent.inbox pending\n\n"
        f"<!-- {scaffold.OURS_MARKER} -->\n", encoding="utf-8")

    said = scaffold.top_up(root)
    after = (root / "CLAUDE.md").read_text(encoding="utf-8")

    assert said, "it must report that it changed something"
    assert str(house_rules.rules_file()) in after
    assert "Notes I wrote myself." in after, "their own words are untouched"
    # The section mentions the inbox three times (pending / said / replied),
    # so counting the phrase proves nothing. One anchor pair does.
    assert after.count("<!-- aki-agent:mirror -->") == 1, "not duplicated"
    assert "python -m " + "aki_agent.inbox" not in after


def test_topping_up_twice_changes_nothing_the_second_time(home, tmp_path):
    from aki_agent import scaffold

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "CLAUDE.md").write_text(
        f"# Notes\n\n<!-- {scaffold.OURS_MARKER} -->\n", encoding="utf-8")

    assert scaffold.top_up(root)
    assert scaffold.top_up(root) == ""


def test_a_file_that_is_not_ours_is_still_left_alone(home, tmp_path):
    """Appending to somebody's own notes is not a repair."""
    from aki_agent import scaffold

    root = tmp_path / "workspace"
    root.mkdir()
    theirs = "# My own CLAUDE.md\n\nEverything here is mine.\n"
    (root / "CLAUDE.md").write_text(theirs, encoding="utf-8")

    said = scaffold.top_up(root)

    assert "not touched it" in said
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == theirs


def test_every_section_is_anchored(home):
    """The property that makes the next section reach existing installs, and
    makes a stale one repairable rather than merely detectable."""
    from aki_agent import scaffold

    seen = set()
    for one in scaffold.sections():
        assert one.name, "a section with no name cannot be anchored"
        assert one.name not in seen, "two sections cannot share an anchor"
        seen.add(one.name)
        assert one.find_in(one.wrapped()) is not None, \
            "a section must be findable inside its own wrapping"


def test_doctor_notices_a_claude_md_that_is_present_but_out_of_date(
        home, tmp_path, monkeypatch):
    """Present is not the same as current.

    An upgrade is performed by the engine it is replacing, so a top-up taught
    about a new section only applies from the *following* upgrade. Between the
    two the file exists, the old check passed, and the assistant had never
    been told to read the house rules — a page saving into a file nothing
    read. Found by reading a real upgrade log twice and noticing the same step
    missing both times.
    """
    from aki_agent import config as config_module
    from aki_agent import doctor, scaffold

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "CLAUDE.md").write_text(
        "# Notes\n\naki_agent.inbox pending\n", encoding="utf-8")

    loaded = config_module.Config()
    loaded.layout.root = root

    check = doctor.check_workspace_notes(loaded)

    assert not check.ok
    assert "missing" in check.detail
    assert "repair" in check.fix


def test_doctor_is_content_once_every_section_is_there(home, tmp_path):
    from aki_agent import config as config_module
    from aki_agent import doctor, scaffold

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "CLAUDE.md").write_text(
        "# Notes\n\n" + "".join(one.wrapped() for one in scaffold.sections()),
        encoding="utf-8")

    loaded = config_module.Config()
    loaded.layout.root = root

    assert doctor.check_workspace_notes(loaded).ok


# ---------------------------------------------------------------------------
# The three things a user's own assistant reported, 2026-08-20
# ---------------------------------------------------------------------------

def test_the_rules_file_exists_as_soon_as_anything_points_at_it(home):
    """His assistant opened a session by reporting a fault: it had been told
    to read house rules and the file was not there.

    An instruction pointing at a missing file is worse than no instruction."""
    from aki_agent import scaffold

    assert not house_rules.rules_file().exists()
    scaffold.sections()
    assert house_rules.rules_file().exists()
    assert "None set" in house_rules.rules_file().read_text(encoding="utf-8")


def test_a_stale_instruction_is_removed_not_duplicated(home, tmp_path):
    """The old form (`python -m aki_agent.inbox`) fails on every install. The
    first version of `top_up` detected the section by a phrase inside it, so a
    file carrying the broken form looked present and correct.

    Two contradictory instructions in a file an assistant reads every session
    is worse than one wrong one: it has to choose, with no way to know which
    is current."""
    from aki_agent import scaffold

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "CLAUDE.md").write_text(
        "# Notes\n\nMine.\n\n## Keeping the chat in one piece\n\n"
        "```bash\npython -m aki_agent.inbox pending\n```\n\n"
        f"<!-- {scaffold.OURS_MARKER} -->\n", encoding="utf-8")

    said = scaffold.top_up(root)
    after = (root / "CLAUDE.md").read_text(encoding="utf-8")

    assert "no longer works" in said
    assert "python -m aki_agent.inbox" not in after
    assert "_bootstrap.py\" aki_agent.inbox" in after
    assert "Mine." in after


def test_topping_up_is_idempotent(home, tmp_path):
    """It compares the section's body, not the block plus its blank lines.
    The first version differed every run, rewrote every run, and ate a newline
    each time."""
    from aki_agent import scaffold

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "CLAUDE.md").write_text(
        f"# Notes\n\n<!-- {scaffold.OURS_MARKER} -->\n", encoding="utf-8")

    assert scaffold.top_up(root)
    first = (root / "CLAUDE.md").read_text(encoding="utf-8")

    assert scaffold.top_up(root) == ""
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == first


def test_a_section_that_has_changed_is_brought_up_to_date(home, tmp_path):
    """The question an upgrade actually has is not "is something like this
    here" but "is the current version of this here". Only an anchor can
    answer it."""
    from aki_agent import scaffold

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "CLAUDE.md").write_text(
        f"# Notes\n\n<!-- {scaffold.OURS_MARKER} -->\n", encoding="utf-8")
    scaffold.top_up(root)

    text = (root / "CLAUDE.md").read_text(encoding="utf-8")
    (root / "CLAUDE.md").write_text(
        text.replace("Follow them", "SOMETHING OLD"), encoding="utf-8")

    said = scaffold.top_up(root)

    assert "up to date" in said
    assert "SOMETHING OLD" not in (root / "CLAUDE.md").read_text(
        encoding="utf-8")

# ---------------------------------------------------------------------------
# Two documents, one instruction
# ---------------------------------------------------------------------------

def test_the_session_brief_does_not_ask_for_the_recital_it_forbids():
    """The bug was a contradiction between two files, not a missing rule.

    WHAT HAPPENED (reported 2026-08-20)
    ---------------------------------
    He typed "this is a test from dashboard" and got back an account of the
    handoff, the house rules and the dashboard queue -- *"half of the reply is
    rubbish"*. He had complained about exactly this earlier the same day, and
    the rule against it had been written: into `agents/assistant.md`.

    Meanwhile the generated `CLAUDE.md`, which is loaded into every session in
    the folder, still said:

        Then say where you think we left off, in one or two sentences,
        **before** changing anything.

    That is a standing instruction to open with a status report, and it was
    followed to the letter. Nothing was broken. Two documents disagreed, and
    the one that gets loaded won.

    So this reads the pair together. A rule that lives in one file and is
    contradicted in another is not a rule, and the only way to catch that is
    to read both at once -- which is the thing nobody does.
    """
    from pathlib import Path

    from aki_agent import scaffold

    brief = scaffold._content_for(                        # noqa: SLF001
        Path("CLAUDE.md"), None, "Aki", "the maintainer", Path("."))
    lowered = brief.lower()

    # The fix, in the form that fixes it: read first, report only on demand.
    assert "read it silently" in lowered, (
        "CLAUDE.md no longer tells the assistant to read without reporting")

    # The report is still owed -- when work is being picked up. That condition
    # is the whole of the fix, so losing it is the regression.
    assert "when they pick work up" in lowered, (
        "the handoff report has lost the condition that makes it useful")

    # And the absence-of-news rule belongs in this file too, not only in the
    # specialist brief that lost the argument last time.
    assert "absence of news" in lowered

    # Both halves of the pair, so they cannot drift apart again.
    assistant = (Path(__file__).resolve().parents[1] / "agents"
                 / "assistant.md").read_text(encoding="utf-8").lower()
    for document, name in ((lowered, "CLAUDE.md"), (assistant, "assistant.md")):
        assert "absence of news" in document, f"{name} lost the rule"
        assert "never recite" in document, (
            f"{name} does not forbid reciting what was read")

def _old_style_brief(marker: str) -> str:
    """A CLAUDE.md as it stood on a machine installed before today."""
    return (
        "# Notes for the assistant\n\n"
        "## Start every session by reading the handoff\n\n"
        "Use the **session-state** skill before doing anything else.\n\n"
        "Then say where you think we left off, in one or two sentences, "
        "**before**\nchanging anything.\n\n"
        "## How I like things done\n\n"
        "- keep it short\n\n"
        f"<!-- written by {marker}; delete this line -->\n")


def test_an_existing_install_loses_the_old_instruction_and_gains_the_new(tmp_path):
    """A fix that only reaches new installs has not shipped.

    The reply-size rule was written into the body of the generated CLAUDE.md
    first. That file is written once, at scaffold time, and never again --
    so the upgrade changed nothing for anybody who already had the package.
    Checked on the test machine after the upgrade rather than assumed: "still
    tells it to recite" came back True.

    Adding the new section is only half of it. The old sentence has to *go*,
    because an assistant reading both is reading a contradiction, and the
    older half is the one that produced the behaviour he complained about.
    """
    from aki_agent import scaffold

    brief = tmp_path / "CLAUDE.md"
    brief.write_text(_old_style_brief(scaffold.OURS_MARKER), encoding="utf-8")

    said = scaffold.top_up(tmp_path)
    text = brief.read_text(encoding="utf-8")

    assert "handoff" in said
    assert "Then say where you think we left off" not in text, (
        "the instruction that caused the recital is still in the file")
    assert "Read it silently" in text
    assert "keep it short" in text, "their own notes were not left alone"


def test_topping_up_twice_changes_nothing_the_second_time(tmp_path):
    """Idempotence, and it is not a nicety here.

    The removal list is matched against the file's text, and the replacement
    wording deliberately keeps the same sentence for the case where it is
    still wanted. A marker matching both would have `top_up` delete the block
    it had just written, every run, for ever -- rewriting somebody's brief on
    every upgrade and losing the rule each time.

    This is the test that caught exactly that, before it shipped.
    """
    from aki_agent import scaffold

    brief = tmp_path / "CLAUDE.md"
    brief.write_text(_old_style_brief(scaffold.OURS_MARKER), encoding="utf-8")

    scaffold.top_up(tmp_path)
    settled = brief.read_text(encoding="utf-8")

    assert scaffold.top_up(tmp_path) == "", "a second pass wanted to change it"
    assert brief.read_text(encoding="utf-8") == settled
    assert scaffold.top_up(tmp_path) == ""
    assert "Read it silently" in brief.read_text(encoding="utf-8")


def test_a_removal_marker_can_never_eat_a_managed_section(tmp_path):
    """The guard, tested on its own rather than through the wording above.

    Whatever gets added to the removal list later, a block this package
    maintains must survive it: those are updated in place a few lines further
    down, and deleting one on the way past would be silent.
    """
    from aki_agent import scaffold

    protected = scaffold.Section("handoff", "## Kept\n\nThen say where you "
                                            "think we left off.\n\n")
    text = ("# Notes\n\n" + protected.wrapped()
            + f"<!-- written by {scaffold.OURS_MARKER} -->\n")

    cleaned, dropped = scaffold._drop_superseded(text)      # noqa: SLF001

    assert dropped is False
    assert "## Kept" in cleaned

