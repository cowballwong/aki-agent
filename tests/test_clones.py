"""Shadow clones: several agents, one memory, one conversation.

The clone is the reason everything else in this change exists, so the tests
that matter here are the ones about addressing and about not being able to
create something that collides with the main body.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aki_agent import atomic, chat, clones, mcp, paths


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    monkeypatch.delenv(chat.SESSION_ENV, raising=False)
    paths.ensure_app_dirs()
    yield


@pytest.fixture()
def project(tmp_path):
    folder = tmp_path / "a-project"
    folder.mkdir()
    return folder


def _never_starts(name, folder):
    """A spawn that records nothing and starts nothing."""
    return 4242


# ---------------------------------------------------------------------------
# Naming — a name is an address
# ---------------------------------------------------------------------------

def test_a_clone_cannot_be_called_main(project):
    """It would receive the main agent's messages, with no error to see."""
    with pytest.raises(clones.CloneError) as raised:
        clones.create("main", project, spawn=_never_starts)

    assert "main body" in str(raised.value)


def test_a_name_is_refused_rather_than_sanitised(project):
    """A name quietly changed is a message delivered to the wrong session."""
    for attempt in ("../escape", "with space", "emoji🙂", "", "   ",
                    "x" * 40):
        with pytest.raises(clones.CloneError):
            clones.create(attempt, project, spawn=_never_starts)


def test_a_name_is_taken_as_typed_apart_from_case(project):
    made = clones.create("David-2", project, spawn=_never_starts)

    assert made.name == "david-2"
    assert clones.get("david-2") is not None


def test_two_clones_cannot_share_a_name(project):
    clones.create("david-2", project, spawn=_never_starts)

    with pytest.raises(clones.CloneError) as raised:
        clones.create("david-2", project, spawn=_never_starts)

    assert "already" in str(raised.value)


# ---------------------------------------------------------------------------
# What a clone is
# ---------------------------------------------------------------------------

def test_a_clone_needs_a_folder_that_exists(tmp_path):
    with pytest.raises(clones.CloneError) as raised:
        clones.create("david-2", tmp_path / "not-made-yet",
                      spawn=_never_starts)

    assert "not a folder" in str(raised.value)


def test_a_clone_gets_its_own_channel_naming_it(project):
    clones.create("david-2", project, spawn=_never_starts)

    written = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
    server = written["mcpServers"][clones.CHANNEL_SERVER]

    assert server["env"][chat.SESSION_ENV] == "david-2"
    assert server["args"][-1].endswith("channel_server")


def test_a_clone_records_no_permission_that_nothing_enforces(project):
    """What replaced `test_a_clone_may_not_write_shared_state_unless_it_is_said`.

    That test read: "Defaulting to no is what makes a clone unable to corrupt
    the memory" -- and then asserted only that `may_write_shared` came back
    False on one clone and True on another. It never went near a write,
    because there was nothing to go near: no code anywhere read that field to
    decide anything. The flag was set, stored, and consulted by nobody, and
    the test's own docstring is what made it look enforced.

    So the flag is gone (2026-09-06), and this stands in its place: a clone
    row carries no permission at all, which is honest, rather than one that
    reads as a restriction and is not.
    """
    made = clones.create("david-2", project, spawn=_never_starts)
    row = made.as_dict()

    assert "may_write_shared" not in row
    assert not any("may_write" in key or "permission" in key for key in row), (
        f"a clone row is claiming a permission again: {sorted(row)}. If one "
        f"is wanted, something has to read it and refuse a write.")


def test_a_new_clone_does_not_wake_to_the_mornings_conversation(project):
    chat.say("user", "a long morning", session="david-2")

    clones.create("david-2", project, spawn=_never_starts)
    fresh, _ = chat.unread("david-2")

    assert fresh == []


def test_a_clone_is_handed_only_what_is_addressed_to_it(project):
    clones.create("david-2", project, spawn=_never_starts)

    chat.say("user", "for the main body", session="main")
    chat.say("user", "for the clone", session="david-2")

    for_clone, _ = chat.unread("david-2")

    assert [one.text for one in for_clone] == ["for the clone"]


# ---------------------------------------------------------------------------
# Somebody has to stop somewhere
# ---------------------------------------------------------------------------

def test_there_is_a_ceiling_on_how_many(project, monkeypatch):
    monkeypatch.setattr(clones, "MAX_CLONES", 2)
    clones.create("one", project, spawn=_never_starts)
    clones.create("two", project, spawn=_never_starts)

    with pytest.raises(clones.CloneError) as raised:
        clones.create("three", project, spawn=_never_starts)

    assert "limit" in str(raised.value)


# ---------------------------------------------------------------------------
# Dispelling
# ---------------------------------------------------------------------------

def test_dispelling_stops_the_session_and_takes_the_channel_away(project):
    clones.create("david-2", project, spawn=_never_starts)
    stopped: list[int] = []

    clones.dispel("david-2", stop=stopped.append)

    assert stopped == [4242]
    assert clones.get("david-2") is None
    written = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
    assert clones.CHANNEL_SERVER not in (written.get("mcpServers") or {})


def test_dispelling_something_that_is_not_there_says_so(project):
    with pytest.raises(clones.CloneError) as raised:
        clones.dispel("never-existed")

    assert "no clone" in str(raised.value)


def test_dispelling_one_leaves_the_others(project):
    clones.create("david-2", project, spawn=_never_starts)
    clones.create("david-3", project, spawn=_never_starts)

    clones.dispel("david-2", stop=lambda pid: None)

    assert [one.name for one in clones.listing()] == ["david-3"]


def test_a_window_closed_by_hand_stops_claiming_to_be_an_agent(project,
                                                               monkeypatch):
    clones.create("david-2", project, spawn=_never_starts)
    monkeypatch.setattr(clones, "_is_running", lambda pid: False)

    dropped = clones.forget_dead()

    assert dropped == 1
    assert clones.listing() == []


# ---------------------------------------------------------------------------
# The registry is read-modify-write, which is the bug fixed this morning
# ---------------------------------------------------------------------------

def test_the_registry_is_written_under_its_lock(project, monkeypatch):
    """Two clones created at once must not erase one another.

    Asserted by watching for the lock rather than by racing threads: the race
    is the thing the lock prevents, and a test that has to lose a race first
    is a test that passes on a fast morning.
    """
    taken: list[str] = []
    real_lock = atomic.lock

    def watched(target, *args, **kwargs):
        taken.append(Path(target).name)
        return real_lock(target, *args, **kwargs)

    monkeypatch.setattr(atomic, "lock", watched)
    clones.create("david-2", project, spawn=_never_starts)

    assert clones.REGISTRY_NAME in taken


# ---------------------------------------------------------------------------
# The main body's own channel
#
# Missing until 2026-09-01, and it was the whole point: every clone got a
# .mcp.json and the main agent never did, so the dashboard wrote into the
# conversation and nothing was listening. The maintainer saw it as his assistant
# carrying on with Telegram after Telegram had supposedly been replaced.
# ---------------------------------------------------------------------------

def test_the_main_agents_project_entry_is_taken_out():
    """The main channel moved into the plugin, so a project copy is a double.

    Both would start, both would tail the same log, and every line the person
    typed would arrive twice. The old entry is removed rather than left to sit
    there, because an upgrade is the only moment anything looks at it.
    """
    mcp.add(clones.CHANNEL_SERVER, "python", ("-m", "aki_agent.channel_server"),
            root=mcp.project_file().parent, env={chat.SESSION_ENV: clones.MAIN})

    clones.configure_main()

    written = json.loads(mcp.project_file().read_text(encoding="utf-8"))
    assert clones.CHANNEL_SERVER not in written["mcpServers"]


def test_removing_a_main_channel_that_was_never_there_is_not_an_error():
    """An upgrade runs this every time, and most times there is nothing."""
    clones.configure_main()
    clones.configure_main()


def test_the_main_agent_starts_at_the_end_of_the_conversation():
    """An upgrade should not replay this morning at the assistant."""
    chat.say("user", "said before the upgrade", session=clones.MAIN)

    clones.configure_main()
    fresh, _ = chat.unread(clones.MAIN)

    assert fresh == []


def test_the_launcher_carries_the_approved_channel_again():
    """Rewritten 2026-09-01 evening, and the reason is not a bug.

    The package's own channel works and cannot be automated AS A `server:`
    REFERENCE: that route stops on an interactive prompt at every start, and
    an assistant meant to run scheduled work unattended cannot begin with a
    keypress. So Telegram -- which IS on the approved list -- carries inbound.

    Still true on 2026-09-04, and now for a second reason. The package's own
    channel existed to carry the dashboard's chat box; the maintainer removed that
    panel, so there is nothing left for it to carry and it is not named here
    at all. Telegram is the only way in, which is what he asked for.
    """
    from aki_agent import launcher

    for windows in (True, False):
        block = launcher.channel_block(windows=windows)
        assert "--channels plugin:telegram@claude-plugins-official" in block


def test_a_clone_inherits_what_was_chosen_for_the_main_body(monkeypatch,
                                                            tmp_path):
    """A clone is the same assistant, not a stranger in a project folder."""
    from aki_agent import launcher

    written = tmp_path / "start-assistant.bat"
    written.write_text(
        "call claude %AKI_CHANNELS% --permission-mode auto --agent david\n",
        encoding="utf-8")
    monkeypatch.setattr(launcher, "launcher_path", lambda name="x": written)

    arguments = clones.clone_arguments()

    assert "--permission-mode" in arguments and "auto" in arguments
    assert "--agent" in arguments and "david" in arguments


def test_a_missing_launcher_costs_the_persona_and_nothing_worse(monkeypatch,
                                                                 tmp_path):
    """Reading the person's choices is a bonus, not a precondition."""
    from aki_agent import launcher

    monkeypatch.setattr(launcher, "launcher_path",
                        lambda name="x": tmp_path / "not-there.bat")

    assert clones.clone_arguments() == []


def test_the_clone_is_told_which_name_it_answers_to(project, monkeypatch):
    """Two agents reading the same lines is the failure this prevents."""
    seen = {}

    def watched(executable, *args, **kwargs):
        seen["env"] = kwargs.get("env") or {}
        seen["argv"] = executable
        return type("P", (), {"pid": 99})()

    monkeypatch.setattr(clones.subprocess, "Popen", watched)
    monkeypatch.setattr(clones.runner, "find_claude", lambda: "claude")

    clones.launch("david-2", project)

    assert seen["env"][chat.SESSION_ENV] == "david-2"
    # No channel flag: a clone is reached by the main agent over cross-session
    # messaging, and the only self-written-channel flag available stops on an
    # interactive prompt -- a clone launched with it waits for a keypress that
    # never comes, which is what looked like clones dying instantly.
    assert "--dangerously-load-development-channels" not in seen["argv"]
