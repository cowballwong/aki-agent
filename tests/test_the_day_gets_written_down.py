"""The evening wrap-up could not save a word of what it wrote.

reported 2026-08-24, forwarding what his assistant had just told him:



It was right. A headless run has nobody to answer a permission prompt, so
every write it attempted was refused. It composed the whole day's account,
could not keep one line of it, and the run was recorded as
`finished in 194s` — a success.

The file on disk that evening held six lines of task timings and nothing they
were timings of.

The fix is not to give an unattended agent a way to write files. It is that
the package was already holding the text.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from aki_agent import memory, paths, schedule


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    return tmp_path


def test_a_written_passage_is_kept_as_it_was_written(home):
    """`log_event` records that a thing happened; this records what was said."""
    memory.log_entry("Evening wrap-up",
                     "Two tasks failed this morning.\n"
                     "Both were the expired login.\n"
                     "Still open: the workspace is untouched.")

    written = memory.read_day()

    assert "Evening wrap-up" in written
    assert "Both were the expired login." in written
    assert "Still open: the workspace is untouched." in written


def test_the_passage_keeps_its_lines(home):
    """A narrative folded onto one line is a narrative nobody re-reads."""
    memory.log_entry("Evening wrap-up", "first line\nsecond line\nthird line")

    body = memory.read_day()

    assert "first line\nsecond line\nthird line" in body


def test_a_credential_pasted_into_the_day_is_redacted(home):
    """The day's file is exactly where a key ends up by accident.

    Everything that happens gets an entry here, including the entry about
    connecting a mailbox.
    """
    token = ":".join(("1234567890",
                      "AAHfake0Token1For2" + "Tests3Only4Never5Real6x"))
    memory.log_entry("Evening wrap-up", f"connected the bot with {token}")

    assert token not in memory.read_day()


def test_an_empty_passage_writes_nothing(home):
    memory.log_entry("Evening wrap-up", "   \n  \n")

    assert "Evening wrap-up" not in memory.read_day()


def test_the_day_still_takes_ordinary_events_too(home):
    """The two shapes share one file and must not tread on each other."""
    memory.log_event("Morning summary: finished in 38s")
    memory.log_entry("Evening wrap-up", "A quiet day.")
    memory.log_event("Weekly tidy: finished in 66s")

    body = memory.read_day()

    assert "Morning summary: finished in 38s" in body
    assert "A quiet day." in body
    assert "Weekly tidy: finished in 66s" in body


def test_the_wrap_up_is_the_task_that_records_the_day():
    """And it is marked as such rather than recognised by its name."""
    wrapup = schedule.get_task("evening-wrapup")

    assert wrapup is not None
    assert wrapup.records_day is True


def test_no_other_shipped_task_claims_to_record_the_day():
    """One file, one author. Two tasks appending narratives to the same day
    would produce a record nobody could read back."""
    recording = [task.key for task in schedule.DEFAULT_TASKS
                 if getattr(task, "records_day", False)]

    assert recording == ["evening-wrapup"]


def test_the_headless_grant_still_has_no_wildcard_shell():
    """The fix that was NOT taken, pinned so it is not taken later.

    Allowing the run to write meant granting a shell command with a wildcard
    argument, and a wildcard reaches past the command it is attached to. The
    package's own permission test forbids it, correctly. Recording the
    temptation here because it looked like the obvious answer for an hour.
    """
    from aki_agent import runner

    for granted in runner.scheduled_tools():
        if granted.startswith("Bash"):
            assert "*" not in granted


def test_a_wrap_up_that_wrote_nothing_is_not_a_quiet_success(home,
                                                             monkeypatch):
    """The original failure, in one line.

    It ran, produced nothing that reached the day's file, and was recorded as
    a success. Whatever else changes, that combination must be visible.
    """
    from aki_agent import events, runner, tasks
    from aki_agent.config import Config, Layout, Notifications

    config = Config()
    config.user.name = "Someone"
    config.assistant.name = "Helper"
    config.layout = Layout(root=home / "work")
    (home / "work").mkdir(exist_ok=True)
    config.notifications = Notifications(enabled=True)

    monkeypatch.setattr(tasks.config_module, "load", lambda: config)
    monkeypatch.setattr(runner, "run", lambda *a, **k: runner.RunResult(
        ok=True, output="   ", seconds=3.0))
    monkeypatch.setattr(runner, "write_output", lambda *a, **k: None)
    monkeypatch.setattr(tasks.notify, "send", lambda *a, **k: True)

    tasks.run_one("evening-wrapup", channel="file",
                  now=_dt.datetime(2026, 8, 24, 18, 30))

    problems = [one for one in events.read() if one.kind == "problem"]
    assert any("wrote nothing" in one.text for one in problems), (
        "a wrap-up that saved nothing must say so")


# ---------------------------------------------------------------------------
# How it reads when it lands
# ---------------------------------------------------------------------------


def _a_prompt():
    from aki_agent import schedule, tasks
    from aki_agent.config import Config, Layout

    config = Config()
    config.user.name = "Someone"
    config.assistant.name = "Helper"
    config.layout = Layout(root=None)
    return tasks._prompt_for(schedule.get_task("evening-wrapup"), config)


def test_the_run_is_told_where_its_words_are_going():
    """Nothing had ever said "this lands on a phone".

    The model was writing prose for
    a document because nobody had told it otherwise — which is the package's
    omission, not the model's mistake.
    """
    prompt = _a_prompt()

    assert "phone" in prompt.lower()
    assert "blank line" in prompt.lower()


def test_the_no_run_on_rule_carries_an_example():
    """The rule alone was not enough, twice over.

    First attempt said "one idea per line" folded into a sentence with three
    other rules, and the model kept writing
    -- it followed the blank-line half and ignored this half. Instructions
    packed tightly get read as one instruction.

    A counter-example is what makes it land, so the counter-example is what is
    pinned here rather than the wording around it.
    """
    prompt = _a_prompt()

    assert "semicolon" in prompt
    assert "That is three lines" in prompt, (
        "the rule needs the example; the rule alone did not work")


def test_the_prompt_is_still_inside_its_budget():
    """It costs tokens on every scheduled run, every day, for ever.

    The first draft of the formatting rules came in at 985 against a limit of
    800. The limit is right; the rules were made to fit it rather than the
    other way round.
    """
    from aki_agent import schedule, tasks
    from aki_agent.config import Config, Layout

    config = Config()
    config.user.name = "Someone"
    config.assistant.name = "Helper"
    config.layout = Layout(root=None)

    # The LONGEST shipped task, not a convenient one. Measuring the short one
    # is how the first attempt passed here at 731 and failed the package's own
    # guard at 865.
    # EVERY PROMPT THE PACKAGE WRITES, not only the shipped list.
    #
    # `dreaming.PROMPT` was written on 2026-09-05 and is not in
    # `DEFAULT_TASKS` -- Dreaming writes itself into the user's schedule when
    # switched on -- so it slipped past this guard entirely and measured
    # 1070. That is a loophole, not permission: it runs every night for ever,
    # which is exactly the thing this limit exists to protect. Trimmed to 990
    # and the guard widened, rather than the other way round.
    from aki_agent import dreaming

    candidates = list(schedule.DEFAULT_TASKS) + [dreaming.task_for(3, 0)]
    worst = max(candidates,
                key=lambda task: len(tasks._prompt_for(task, config)))

    # 800 -> 1000 on 2026-09-02. The morning summary was arriving as a
    # paragraph on days with nothing in it; telling it what an empty day
    # should look like is worth the characters, and this guard exists to
    # make that a decision rather than a drift.
    assert len(tasks._prompt_for(worst, config)) < 1000, worst.key


def test_the_run_is_told_which_markup_survives_and_which_does_not():
    """Half a rule is worse than none.

    "Do not use markdown" would also have banned the one thing that now works.
    """
    prompt = _a_prompt()

    assert "**bold**" in prompt, "the one thing that survives must be named"
    assert "other markdown" in prompt, (
        "and the rest must be ruled out, or it comes back as punctuation")


# ---------------------------------------------------------------------------
# What the entry is actually about
#
# reported 2026-09-04, of a wrap-up that was fifteen engine upgrades, eight
# session recycles and three port collisions.
#
# The old wording -- "what changed, what I decided, what is still open" --
# named no subject, and the machine's own log is by far the loudest thing a
# headless run can read. So it wrote up itself.
# ---------------------------------------------------------------------------

def test_the_entry_is_about_the_users_projects_first():
    prompt = _a_prompt()

    assert "my projects" in prompt.lower()
    assert "tomorrow" in prompt.lower()
    assert "waiting on me" in prompt.lower()


def test_an_empty_section_has_a_short_way_out():
    """Every section says what to write when there is nothing in it.

    Without it the model pads: a day with no project work came back as a tour
    of the demo folders. The maintainer, of the same failure in the morning summary:
    """
    prompt = _a_prompt()

    assert "No project work today." in prompt
    assert "Nothing waiting." in prompt


def test_the_machine_gets_one_line_at_most():
    """The ceiling, and the exclusion, both in the prompt.

    The ceiling alone was not enough to imagine relying on: "keep it short"
    is what the previous wording effectively said. Naming the specific things
    that are not news -- upgrades, restarts -- is what makes it land.
    """
    prompt = _a_prompt()

    assert "ONE line" in prompt, "the ceiling has to be stated"
    assert "upgrades" in prompt and "restarts" in prompt, (
        "the ceiling needs the counter-example; these are what filled the "
        "message it replaced")


# ---------------------------------------------------------------------------
# One file, two kinds of line
#
# `log_event` writes "- HH:MM something happened"; `log_entry` writes
# "## HH:MM Title" and a passage. They share a file, and the dashboard used
# to print the whole thing -- so on a day with ten recycles the wrap-up
# somebody came to read was below a hundred lines of timings.
# ---------------------------------------------------------------------------

def test_a_day_separates_what_was_written_from_what_merely_happened(home):
    memory.log_event("recycle: restarted and confirmed")
    memory.log_entry("Evening wrap-up",
                     "No project work today.\n"
                     "Nothing on tomorrow.\n"
                     "Nothing waiting.")
    memory.log_event("recycle: restarted and confirmed again")

    entries, events = memory.split_day(memory.read_day())

    assert [one.title for one in entries] == ["Evening wrap-up"]
    assert "No project work today." in entries[0].body
    # Each event keeps the time it was logged at -- `log_event` writes it
    # into the line, and a timeline without times is a list.
    assert len(events) == 2
    assert all(one[:5].count(":") == 1 for one in events), events
    assert events[0].endswith("recycle: restarted and confirmed")
    # The timings must not leak into the passage: they are what the passage
    # was competing with.
    assert "recycle" not in entries[0].body


def test_the_files_own_date_heading_is_neither(home):
    """`# Friday 04 September 2026` opens the file and is not an entry."""
    memory.log_event("something")
    entries, events = memory.split_day(memory.read_day())

    assert entries == []
    assert len(events) == 1 and events[0].endswith("something")


def test_an_entry_keeps_the_time_it_was_written(home):
    memory.log_entry("Evening wrap-up", "A line.")
    entries, _ = memory.split_day(memory.read_day())

    assert len(entries[0].at) == 5 and ":" in entries[0].at
