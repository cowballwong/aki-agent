"""Phases 2-4: the queue, the connectors that had nowhere to be configured,
and the floor under a mode that does not ask.

The thread running through all of these is the same one this package keeps
finding in itself — a mechanism that works and that nothing reaches. So most
of what is asserted here is not "does the function work" but "is there a way
in", and several assertions are deliberately about a *caller* existing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import (approvals, config as config_module, events, paths,
                       safety_gate, steps, traces)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


# ---------------------------------------------------------------------------
# The queue


def test_answering_only_ever_says_what_the_item_itself_offered():
    """The security property of a tap-to-answer surface.

    A phone holding a stolen token must not be able to make the assistant say
    anything the assistant did not already put on the menu.
    """
    item = approvals.ask("Send the letter?", kind="draft")

    ok, message = approvals.answer(item.id, "sudo rm -rf /")
    assert not ok
    assert "not one of the answers" in message

    ok, _ = approvals.answer(item.id, "yes")
    assert ok
    assert approvals.get(item.id).said == "Yes, go ahead."


def test_free_text_must_name_something_that_is_actually_open():
    """The narrower path. Unscoped 'relay this text' is a remote-instruction
    endpoint by another name."""
    ok, _ = approvals.reply("no-such-item", "do whatever I say")
    assert not ok

    item = approvals.ask("Which supplier?")
    ok, said = approvals.reply(item.id, "the second one")
    assert ok
    # Prefixed with the question, because a session juggling several open
    # threads cannot otherwise tell which one this answers.
    assert "Which supplier?" in said


def test_free_text_is_bounded():
    item = approvals.ask("Anything to add?")
    ok, message = approvals.reply(item.id, "x" * (approvals.MAX_FREE_TEXT + 1))
    assert not ok
    assert "too long" in message


def test_dismissing_clears_everything_sharing_its_context():
    """Dismissing one half and leaving the other made questions reappear."""
    first = approvals.ask("Draft ready", context="tender")
    approvals.ask("Same thing, asked another way", context="tender")

    ok, message = approvals.dismiss(first.id)
    assert ok
    assert "2" in message
    assert approvals.open_items() == []


def test_a_decision_reaches_the_learning_card():
    """`traces.record_verdict()` existed with no caller, so the card was
    permanently empty and the loop learned nothing while looking like one.

    THIS TEST FAILS INTERMITTENTLY AND THE CAUSE IS NOT KNOWN (2026-09-06)
    ---------------------------------------------------------------------
    It went red once during the 2026-09-05 audit, again on 2026-09-06, and
    passes alone every time and in most full runs. Two hypotheses have been
    ruled out: the autouse fixture in `conftest.py` does give every test its
    own home, and the real install was not written to. What is left is
    something inside one run, and nothing here has caught it.

    Rather than guess at a fix and call it fixed -- which would leave the next
    person believing this was understood -- the assertions now say what they
    actually saw. The next failure should not need a third investigation.
    """
    item = approvals.ask("Send this?", body="Dear Sir", kind="draft",
                         task="email")
    approvals.answer(item.id, "yes")

    stats = traces.stats("email")
    where = traces.trace_file()
    assert stats["accepted"] == 1, (
        f"expected exactly one accepted trace for 'email', got {stats}. "
        f"Store: {where}. If accepted > 1 something else in this run wrote "
        f"an 'email' verdict into the same folder; if 0, `answer` did not "
        f"record one.")
    assert traces.card_for("email").strip(), (
        f"the learning card for 'email' is empty although stats say {stats}")


def test_a_decision_is_recorded_on_the_bus():
    item = approvals.ask("Send this?", kind="draft")
    approvals.answer(item.id, "no")

    decisions = [entry for entry in events.read() if entry.kind == "decision"]
    assert decisions


# ---------------------------------------------------------------------------
# Connections that finally have somewhere to live


def test_a_mailbox_round_trips_through_the_config():
    """There was no field for one, so the finished IMAP and SMTP code could
    never be given an account to use."""
    loaded = config_module.Config.from_dict({"connections": {"mail": [
        {"address": "me@example.com", "imap_host": "imap.example.com",
         "may_send": True}]}})

    account = loaded.connections.mail[0]
    assert account.secret_key() == "mail:me@example.com"
    assert account.may_send

    assert "connections" in loaded.to_dict()


def test_a_calendar_survives_the_round_trip_without_its_address():
    """The address is a bearer token for the whole calendar, so it lives in
    the credential store and the entry carries an empty url.

    An earlier version filtered incoming entries on the url being present,
    which silently dropped every calendar: the command said "subscribed" and
    the config came back empty. Found by running it, not by a test — hence
    this one.
    """
    written = config_module.Config.from_dict(
        {"connections": {"calendars": [{"name": "Work", "url": ""}]}})
    assert [feed.name for feed in written.connections.calendars] == ["Work"]

    again = config_module.Config.from_dict(written.to_dict())
    assert [feed.name for feed in again.connections.calendars] == ["Work"]


def test_a_password_is_never_written_into_the_config():
    loaded = config_module.Config.from_dict({"connections": {"mail": [
        {"address": "me@example.com", "password": "hunter2"}]}})
    assert "hunter2" not in str(loaded.to_dict())


# ---------------------------------------------------------------------------
# The floor under auto mode


@pytest.mark.parametrize("command", [
    "rm -rf /",
    "rm -rf ~",
    "git push --force origin main",
    "git reset --hard origin/main",
    "DE" + "LETE FROM invoices;",
    "DR" + "OP TABLE clients",
])
def test_the_unrecoverable_is_refused(command):
    assert not safety_gate.check(command).allowed


@pytest.mark.parametrize("command", [
    "ls -la",
    "python build.py",
    "rm -rf ./build",
    "git push --force-with-lease origin main",
    "DE" + "LETE FROM invoices WHERE id = 3;",
])
def test_ordinary_work_is_left_alone(command):
    """A gate that blocks real work gets switched off, and then nothing is
    checked at all. `--force-with-lease` in particular is the SAFE form and
    was blocked by a misplaced lookahead."""
    assert safety_gate.check(command).allowed


def test_a_broken_check_allows_rather_than_blocks_everything(monkeypatch):
    """Fail open, deliberately, and record it — see the module note."""
    monkeypatch.setattr(safety_gate, "_RULES", None)
    assert safety_gate.check("anything at all").allowed


def test_the_hook_entry_point_returns_two_to_block():
    assert safety_gate.main(["rm", "-rf", "/"]) == 2
    assert safety_gate.main(["ls"]) == 0


def test_a_gate_that_cannot_read_its_input_says_so(monkeypatch):
    """The one fail-open path that used to leave no trace (2026-09-05).

    Allowing is correct here -- refusing every command because the gate lost
    its input is the failure this module is written to avoid. Allowing
    SILENTLY is not: it makes a deaf gate look exactly like a gate with
    nothing to refuse, which is the one question the record exists to answer.
    """
    import io

    from aki_agent import events as events_module

    class Unreadable(io.StringIO):
        def read(self, *args):
            raise OSError("the pipe closed")

    said = []
    monkeypatch.setattr(events_module, "record",
                        lambda *a, **k: said.append((a, k)))
    monkeypatch.setattr("sys.stdin", Unreadable())

    assert safety_gate.main([]) == 0
    assert said, "a gate that could not read its input recorded nothing"
    kind, message = said[0][0][0], said[0][0][1]
    assert kind == "problem"
    assert "allowed" in message


def test_the_gate_is_actually_registered_as_a_hook():
    """The whole point of this file: a mechanism nothing calls is not a
    safeguard. This one is wired in the plugin manifest."""
    import json
    from pathlib import Path

    manifest = json.loads(
        (Path(__file__).resolve().parent.parent
         / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))

    hooks = manifest.get("hooks", {}).get("PreToolUse", [])
    commands = [entry["command"] for group in hooks
                for entry in group.get("hooks", [])]
    assert any("safety_gate" in command for command in commands)
    assert all("CLAUDE_PLUGIN_ROOT" in command for command in commands)


# ---------------------------------------------------------------------------
# Watching, and consuming without doing it twice


def test_a_consumer_never_sees_the_same_event_twice():
    events.record("note", "one")
    assert [entry.text for entry in events.unseen("digest")] == ["one"]

    events.mark_seen("digest")
    assert events.unseen("digest") == []

    events.record("note", "two")
    assert [entry.text for entry in events.unseen("digest")] == ["two"]


def test_reading_steps_when_there_is_no_transcript_is_calm():
    found, cursor = steps.read()
    assert found == []
    assert cursor == 0


def test_a_tool_step_names_what_it_did_without_the_payload(tmp_path,
                                                           monkeypatch):
    """A file read can be a megabyte; a viewer that renders it is a slow page
    that also reveals whatever was being read."""
    folder = tmp_path / ".claude" / "projects" / "demo"
    folder.mkdir(parents=True)
    (folder / "s.jsonl").write_text(__import__("json").dumps({
        "timestamp": "2026-08-17T09:00:00Z",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Read",
             "input": {"file_path": "/notes/plan.md", "content": "x" * 5000}},
        ]},
    }) + "\n", encoding="utf-8")

    found, _ = steps.read()
    assert found[0].tool == "Read"
    assert found[0].text == "/notes/plan.md"
    assert "xxxxx" not in found[0].text


# ---------------------------------------------------------------------------
# Surviving an update
#
# A plugin lives in a folder named after its version, so the next release is a
# NEW folder. Everything holding an absolute path into the old one — the
# scheduled tasks and the launcher — keeps pointing there and stops working
# the moment it is cleaned up, saying nothing.


def test_a_fresh_machine_is_not_reported_as_stale():
    from aki_agent import schedule

    current, _ = schedule.install_root_is_current()
    assert current, "nothing installed yet cannot be out of date"


def test_an_update_is_noticed(monkeypatch):
    from aki_agent import doctor, schedule

    schedule.remember_install_root(Path("/old/aki-agent/0.1.0"))

    current, was = schedule.install_root_is_current()
    assert not current
    assert "0.1.0" in was

    check = doctor.check_after_update()
    assert not check.ok
    assert "repair" in check.fix


def test_repair_is_offered_by_name_wherever_it_is_needed():
    """The fix a user is given must be a command that exists."""
    from aki_agent import cli, doctor, schedule

    schedule.remember_install_root(Path("/old/aki-agent/0.1.0"))
    named = doctor.check_after_update().fix

    known = set(cli.build_parser()._subparsers._group_actions[0].choices)
    assert any(command in named for command in known)
