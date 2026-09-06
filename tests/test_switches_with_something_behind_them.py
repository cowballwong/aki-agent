"""The C tail: settings and switches that were read by nothing.

The shape these share is the one this whole audit kept finding — a correct
mechanism with nothing wired to it. What makes them worse than dead code is
that the user believes them: a switch that says "drafts are checked" and does
not check is not a missing feature, it is a false statement on a control
panel.
"""

from __future__ import annotations

import datetime as _dt
import os
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# C8, C14. Two stores that were written and never read back
# ---------------------------------------------------------------------------

def test_a_correction_is_read_back_the_next_time_the_task_runs(tmp_path,
                                                               monkeypatch):
    """`README.md:157`: "it notes the correction and reads it back next time".

    Cards were written by `record_verdict`; `traces.card_for()` had zero
    callers. No prompt builder mentioned it, no command read one, the
    generated CLAUDE.md said nothing. So a person could correct the same thing
    every week and be corrected-at again the week after.
    """
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import schedule, tasks, traces

    traces.record_verdict("morning-summary", "the draft I sent", "rejected",
                          correction="never open with a greeting")

    built = tasks.resolve_prompt(schedule.get_task("morning-summary"))

    assert "never open with a greeting" in built
    assert "corrections your user has already made" in built


def test_the_knowledge_shelf_reaches_the_assistant(tmp_path, monkeypatch):
    """`knowledge.html:6` promised it held "the documents and links you want
    the assistant to know about". `knowledge.find()` had zero callers and no
    skill mentioned it."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import knowledge, schedule, tasks

    knowledge.add(title="Party wall act 1996", kind="link",
                  target="https://legislation.gov.uk/ukpga/1996/40",
                  why="the sections I keep re-reading")

    built = tasks.resolve_prompt(schedule.get_task("morning-summary"))

    assert "Party wall act 1996" in built
    # And where to find it -- the field is `target`, not `path`, and writing
    # the wrong name would have produced a list of bare titles with no way to
    # open any of them, silently.
    assert "legislation.gov.uk" in built
    assert "Open one only if this task actually needs it" in built


def test_a_task_with_nothing_learned_gets_an_unchanged_prompt(tmp_path,
                                                              monkeypatch):
    """No card and an empty shelf must add nothing at all. Otherwise every
    prompt grows a section of headings with nothing under them."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import schedule, tasks

    task = schedule.get_task("morning-summary")
    assert tasks.resolve_prompt(task) == task.prompt


# ---------------------------------------------------------------------------
# C9. Four settings with no reader
# ---------------------------------------------------------------------------

def test_who_the_assistant_works_for_is_written_where_it_is_read(tmp_path,
                                                                 monkeypatch):
    """Each of these was asked for at setup, validated, stored, and read by
    nothing. `identity_aliases` is the one that stings: this package's opening
    argument is that the system it derives from guesses ownership by
    substring-matching a name, and that asking is the fix. Asking and then not
    looking is the same outcome by a longer route."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import config as config_module
    from aki_agent import scaffold

    loaded = config_module.Config()
    loaded.user.name = "Sam Okafor"
    loaded.user.occupation = "architect"
    loaded.user.identity_aliases = ("Sam", "SO")
    loaded.user.timezone = "Europe/London"
    loaded.assistant.tone = "Direct, no preamble."
    loaded.layout.root = tmp_path / "Agent"
    config_module.save(loaded, tmp_path / "01_Config" / "config.yaml")

    written = scaffold._who_section()

    assert "Sam Okafor" in written
    assert "Direct, no preamble." in written
    assert "Sam, SO" in written
    assert "Europe/London" in written
    assert "09:00" in written

    # It is one of the sections that gets replaced on every upgrade, so an
    # existing install gains it without anybody remembering to think about it.
    assert any(one.name == "who" for one in scaffold.sections())


def test_the_who_section_leaves_out_what_it_does_not_know(tmp_path,
                                                          monkeypatch):
    """"Timezone:" with nothing after it tells the assistant less than
    silence does."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import config as config_module
    from aki_agent import scaffold

    loaded = config_module.Config()
    loaded.user.name = "Sam"
    loaded.layout.root = tmp_path / "Agent"
    config_module.save(loaded, tmp_path / "01_Config" / "config.yaml")

    written = scaffold._who_section()

    assert "Sam" in written
    # `timezone` and `identity_aliases` both default to empty, so they are the
    # honest test of this. `tone` is not: it ships with a sensible default, so
    # it is never absent and would test nothing.
    assert "timezone" not in written.casefold()
    assert "all mean them" not in written


# ---------------------------------------------------------------------------
# C11. Quiet hours that could not be reached
# ---------------------------------------------------------------------------

def test_typing_quiet_hours_actually_holds_a_scheduled_message(tmp_path,
                                                               monkeypatch):
    """`_mode_for` answered with a real mode for every task, because
    `mode_for` defaults an unassigned task to ALWAYS. `decide()` reads a
    non-None mode as "this task has its own rule", so the global window was
    never consulted for any scheduled message — and scheduled messages are
    very nearly all of them.

    Somebody could type 22:00 to 07:00, see it saved, see it displayed back,
    and be messaged at midnight.
    """
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import config as config_module
    from aki_agent import notify

    loaded = config_module.Config()
    loaded.notifications.quiet_hours = ("22:00", "07:00")

    midnight = _dt.datetime(2026, 8, 24, 0, 30)
    message = notify.Message(text="the weekly tidy is done",
                             origin="task:weekly-tidy",
                             created_at=midnight)

    decision = notify.decide(message, loaded, "file", now=midnight,
                             mode=notify._mode_for("task:weekly-tidy"))

    assert not decision.deliver
    assert "quiet" in decision.reason


def test_a_task_deliberately_set_to_always_still_overrides(tmp_path,
                                                           monkeypatch):
    """"Always tell me" has to mean it. Never assigned and deliberately
    assigned are different answers, and only the second one overrides."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import config as config_module
    from aki_agent import notify, quiet

    quiet.assign("weekly-tidy", quiet.ALWAYS)

    loaded = config_module.Config()
    loaded.notifications.quiet_hours = ("22:00", "07:00")

    midnight = _dt.datetime(2026, 8, 24, 0, 30)
    message = notify.Message(text="done", origin="task:weekly-tidy",
                             created_at=midnight)

    decision = notify.decide(message, loaded, "file", now=midnight,
                             mode=notify._mode_for("task:weekly-tidy"))

    assert decision.deliver


# ---------------------------------------------------------------------------
# C12. A nightly restart that could never restart a stale session
# ---------------------------------------------------------------------------

def test_the_nightly_restart_does_not_need_the_context_to_be_full():
    """"Nightly at 04:00" promised a time and delivered a condition.

    It required the same three things as the automatic route, so a session at
    40,000 tokens that had been open for three days met none of them — and
    that is exactly the session a nightly restart exists for.
    """
    from aki_agent import guard

    stale = guard.Assessment(
        conditions=[
            guard.Condition("Context", "over 180,000", 40_000, 180_000, False),
            guard.Condition("Idle", "needs 12 min+", 90, 12, True),
            guard.Condition("Since last restart", "needs 3 h+", 40, 3, False),
        ],
        auto=False,
        nightly_due=True,
    )

    assert not stale.all_met
    assert stale.would_recycle
    assert "tonight's restart window" in stale.sentence()


def test_the_nightly_restart_still_refuses_to_interrupt_somebody():
    """Rule 2, which is not negotiable. A rhythm that cuts across live work
    is not a rhythm, it is an interruption."""
    from aki_agent import guard

    busy = guard.Assessment(
        conditions=[
            guard.Condition("Context", "over 180,000", 40_000, 180_000, False),
            guard.Condition("Idle", "needs 12 min+", 1, 12, False),
        ],
        auto=False,
        nightly_due=True,
    )

    assert not busy.would_recycle
    assert "still being used" in busy.sentence()


# ---------------------------------------------------------------------------
# C16. Rule 3, which this package stated and then broke
# ---------------------------------------------------------------------------

def test_the_guard_reads_the_live_transcript_not_the_newest_file(tmp_path,
                                                                 monkeypatch):
    """`session.py` Rule 3: "a restart can leave a dead transcript with a
    NEWER timestamp than the live one... a decision made by reading the wrong
    transcript is worse than making no decision."

    `session.pick_live_transcript` was written for exactly this and had zero
    callers. What fed the automatic recycle instead was
    `sorted(glob, key=mtime)[-1]` — the implementation that rule names as the
    wrong one.
    """
    from aki_agent import guard

    folder = tmp_path / "transcripts"
    folder.mkdir()
    monkeypatch.setattr(guard, "transcript_dir", lambda _w=None: folder)

    dead = folder / "dead.jsonl"
    dead.write_text("old session\n", encoding="utf-8")
    time.sleep(0.05)

    live = folder / "live.jsonl"
    live.write_text("current session\n", encoding="utf-8")

    # The restart's dying session writes one last line, so the DEAD file now
    # has the newer modification time. This is the exact situation Rule 3
    # describes, and the only one where the two implementations disagree.
    time.sleep(0.05)
    later = time.time()
    os.utime(dead, (later, later))

    assert guard.newest_transcript() == dead, "the fixture is not set up"
    assert guard.live_transcript() == live


def test_a_long_idle_session_is_still_found(tmp_path, monkeypatch):
    """The trap in fixing Rule 3.

    `session.pick_live_transcript` calls anything untouched for fifteen
    minutes dead, which is right for its own question and wrong for this one:
    the guard exists to notice a session that has been idle a LONG time. Using
    that window would make such a session invisible, `idle_minutes` would
    answer 0.0, and 0.0 reads as "somebody is typing" — so the guard would
    refuse to recycle precisely the sessions it was built for. Rule 3 traded
    for Rule 4.
    """
    from aki_agent import guard

    folder = tmp_path / "transcripts"
    folder.mkdir()
    monkeypatch.setattr(guard, "transcript_dir", lambda _w=None: folder)

    sleeping = folder / "sleeping.jsonl"
    sleeping.write_text("quiet for hours\n", encoding="utf-8")
    hours_ago = time.time() - 5 * 3600
    os.utime(sleeping, (hours_ago, hours_ago))

    assert guard.live_transcript() == sleeping


def test_nothing_recent_means_we_do_not_know(tmp_path, monkeypatch):
    """None means "I do not know", never "the newest one, probably"."""
    from aki_agent import guard

    folder = tmp_path / "transcripts"
    folder.mkdir()
    monkeypatch.setattr(guard, "transcript_dir", lambda _w=None: folder)

    ancient = folder / "last-month.jsonl"
    ancient.write_text("x\n", encoding="utf-8")
    long_ago = time.time() - guard.RECENT_TRANSCRIPT_HOURS * 3600 - 60
    os.utime(ancient, (long_ago, long_ago))

    assert guard.live_transcript() is None


# ---------------------------------------------------------------------------
# C1. The Me time watcher, which did not exist
# ---------------------------------------------------------------------------

def _mailbox(config, address="me@example.com"):
    from aki_agent import config as config_module

    config.connections.mail = (config_module.MailAccount(
        address=address, label="Work", imap_host="imap.example.com"),)
    config.notifications.urgent_keywords = ("planning", "invoice")
    return config


def test_the_watcher_does_nothing_at_all_when_the_button_is_off(tmp_path,
                                                                monkeypatch):
    """The cheap exit, and the one that runs on every day nobody presses it.

    It reads one small file and stops -- no mailbox connection, no model, no
    message. A watcher that costs something while switched off is a watcher
    somebody switches off at the scheduler, and then it is gone for good.
    """
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import config as config_module
    from aki_agent import me_time
    from aki_agent.connectors import mail as mail_module

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("a mailbox was opened with me time off")

    monkeypatch.setattr(mail_module, "recent", must_not_run)

    count, said = me_time.look_for_something_urgent(
        _mailbox(config_module.Config()))

    assert (count, said) == (0, "")


def test_something_urgent_while_you_are_away_is_raised(tmp_path, monkeypatch):
    """Everything around this existed -- the switch, the state, the
    de-duplication, and copy telling the user their email was being watched
    while they walked away trusting it. Nothing read a mailbox."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import config as config_module
    from aki_agent import me_time
    from aki_agent.connectors import mail as mail_module

    me_time.turn_on()

    monkeypatch.setattr(mail_module, "from_config", lambda entry: entry)
    monkeypatch.setattr(mail_module, "recent", lambda *_a, **_k: [
        mail_module.Message(uid="1", sender="planners@borough.gov.uk",
                            subject="Planning decision issued",
                            date="Mon, 24 Aug 2026", unread=True),
        mail_module.Message(uid="2", sender="a@b.com", subject="Lunch?",
                            date="Mon, 24 Aug 2026", unread=True),
    ])

    count, said = me_time.look_for_something_urgent(
        _mailbox(config_module.Config()))

    assert count == 1
    assert "Planning decision issued" in said
    assert "Lunch?" not in said, "it interrupted for something not urgent"


def test_the_same_email_is_not_raised_twice(tmp_path, monkeypatch):
    """`already_told` / `remember_told` had zero callers and zero tests.

    Without them the watcher re-reports the same message every ten minutes,
    which teaches somebody to ignore it -- and the one it teaches them to
    ignore is, by construction, the urgent one.
    """
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import config as config_module
    from aki_agent import me_time
    from aki_agent.connectors import mail as mail_module

    me_time.turn_on()
    monkeypatch.setattr(mail_module, "from_config", lambda entry: entry)
    monkeypatch.setattr(mail_module, "recent", lambda *_a, **_k: [
        mail_module.Message(uid="1", sender="x@y.com",
                            subject="Invoice overdue", date="", unread=True),
    ])

    config = _mailbox(config_module.Config())
    assert me_time.look_for_something_urgent(config)[0] == 1
    assert me_time.look_for_something_urgent(config) == (0, "")


def test_a_mailbox_that_cannot_be_read_is_said_out_loud(tmp_path, monkeypatch):
    """"I watched and there was nothing" and "I could not look" are different
    sentences, and only one of them means you can relax."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import config as config_module
    from aki_agent import me_time
    from aki_agent.connectors import mail as mail_module

    me_time.turn_on()
    monkeypatch.setattr(mail_module, "from_config", lambda entry: entry)

    def refuse(*_a, **_k):
        raise mail_module.MailError("no app password saved")

    monkeypatch.setattr(mail_module, "recent", refuse)

    count, said = me_time.look_for_something_urgent(
        _mailbox(config_module.Config()))

    assert count == 0
    assert "could not check" in said
    assert "no app password saved" in said


def test_no_urgent_words_means_no_interruptions(tmp_path, monkeypatch):
    """Urgency is the user's word, not a guess. With nothing marked urgent
    this stays quiet, rather than deciding on their behalf what is worth
    interrupting a break for."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import config as config_module
    from aki_agent import me_time
    from aki_agent.connectors import mail as mail_module

    me_time.turn_on()
    monkeypatch.setattr(mail_module, "recent",
                        lambda *_a, **_k: (_ for _ in ()).throw(
                            AssertionError("read mail with no urgent words")))

    config = _mailbox(config_module.Config())
    config.notifications.urgent_keywords = ()

    assert me_time.look_for_something_urgent(config) == (0, "")


def test_the_button_no_longer_says_it_is_watching_when_it_cannot(tmp_path,
                                                                 monkeypatch):
    """The copy was corrected once already for overstating this. It must not
    overstate it again in the other direction: on, with no mailbox connected,
    is a real state and the sentence has to say so."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import config as config_module
    from aki_agent import me_time

    state = me_time.turn_on()

    bare = state.sentence(config_module.Config())
    assert "No mailbox is connected" in bare
    assert "Watching your mail" not in bare

    connected = state.sentence(_mailbox(config_module.Config()))
    assert "Watching your mail" in connected


def test_the_watch_task_is_scheduled_and_costs_nothing_when_off(tmp_path,
                                                                monkeypatch):
    """A capability with no trigger is the defect this package quotes at
    itself: "a tool is not automation"."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    from aki_agent import schedule, tasks

    task = schedule.get_task("me-time-watch")
    assert task is not None
    assert task.built_in
    assert task.announce, "the one task whose purpose is to interrupt"

    outcome = tasks.run_one("me-time-watch", channel="file")
    assert outcome.ok
    assert "me time is off" in outcome.message
