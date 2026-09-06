"""Dashboard messages reaching the live session, without a wait.

This runs before every single thing the user says, which is what makes it
useful and what makes it dangerous. Most of these tests are about it staying
out of the way.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from aki_agent import conversation, paths, pending_hook


class _Stdin:
    """A payload the hook can read more than once.

    Several tests call the hook twice in a row, and a real pipe gives up its
    contents only the first time -- which would make the second call look
    correct for the wrong reason.
    """

    def __init__(self, text: str) -> None:
        self.text = text

    def read(self) -> str:
        return self.text


def _prompt_from(monkeypatch, cwd, *, root):
    """Pretend a prompt was typed in `cwd`, with the install rooted at `root`."""
    monkeypatch.setattr(
        sys, "stdin", _Stdin(json.dumps({"cwd": str(cwd)} if cwd else {})))

    from aki_agent import config as config_module
    monkeypatch.setattr(
        config_module, "load",
        lambda: SimpleNamespace(
            layout=SimpleNamespace(root=Path(root) if root else None)))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


@pytest.fixture(autouse=True)
def install_root(tmp_path, monkeypatch):
    """Every test below is a prompt typed in the assistant's own session.

    The hook refuses any other session now, so without this the whole file
    would be testing the refusal rather than the delivery.
    """
    root = tmp_path / "Assistant"
    root.mkdir(exist_ok=True)
    _prompt_from(monkeypatch, root, root=root)
    return root


# ---------------------------------------------------------------------------
# It carries the messages
# ---------------------------------------------------------------------------

def test_a_queued_message_reaches_the_session(capsys):
    conversation.queue("look at the invoice")

    assert pending_hook.main([]) == 0
    printed = capsys.readouterr().out

    assert "look at the invoice" in printed
    assert "dashboard-messages" in printed


def test_it_says_they_are_the_user_speaking(capsys):
    """Otherwise a model reads them as a document it has been handed."""
    conversation.queue("chase the builder")
    pending_hook.main([])

    assert "They are speaking to you" in capsys.readouterr().out


def test_several_arrive_in_order(capsys):
    for text in ("first", "second", "third"):
        conversation.queue(text)

    pending_hook.main([])
    printed = capsys.readouterr().out

    assert printed.index("first") < printed.index("second") < printed.index(
        "third")


def test_they_are_claimed_so_they_do_not_arrive_twice(capsys):
    conversation.queue("only once please")

    pending_hook.main([])
    capsys.readouterr()
    pending_hook.main([])

    assert capsys.readouterr().out.strip() == ""


# ---------------------------------------------------------------------------
# It stays out of the way
# ---------------------------------------------------------------------------

def test_nothing_waiting_prints_nothing_at_all(capsys):
    """It runs before every prompt. "No messages waiting" would put a line of
    noise into every turn for ever."""
    assert pending_hook.main([]) == 0
    assert capsys.readouterr().out == ""


def test_it_never_fails_however_broken_things_are(capsys, monkeypatch):
    """An exception here is an exception on every prompt, and the symptom is
    an assistant that has stopped working for no visible reason."""
    def explode():
        raise RuntimeError("the disk went away")

    monkeypatch.setattr(conversation, "take_pending", explode)

    assert pending_hook.main([]) == 0
    assert "Traceback" not in capsys.readouterr().out


def test_a_blank_message_is_not_carried(capsys):
    conversation.queue("   ")
    conversation.queue("a real one")

    pending_hook.main([])
    printed = capsys.readouterr().out

    assert "a real one" in printed
    assert printed.count("[") == 1, "the blank one contributes no line"


# ---------------------------------------------------------------------------
# The queue belongs to this assistant, and to no other session
# ---------------------------------------------------------------------------

def test_another_assistants_session_is_not_served(capsys, monkeypatch,
                                                  tmp_path, install_root):
    """The defect this guard exists for (reported 2026-09-04).

    He runs a second assistant out of a folder on his Google Drive. Its
    session got a prompt first, this hook fired inside it, and the message he
    had typed into THIS dashboard was answered somewhere he was not looking.
    """
    conversation.queue("look at the invoice")
    _prompt_from(monkeypatch, tmp_path / "SomewhereElse", root=install_root)

    assert pending_hook.main([]) == 0
    assert capsys.readouterr().out == ""


def test_and_the_message_is_still_waiting_afterwards(monkeypatch, tmp_path,
                                                     install_root):
    """Refusing is only half of it. Draining into silence would lose it."""
    conversation.queue("look at the invoice")
    _prompt_from(monkeypatch, tmp_path / "SomewhereElse", root=install_root)

    pending_hook.main([])

    assert [one["text"] for one in conversation.read_pending()] == [
        "look at the invoice"]


def test_a_folder_inside_the_install_counts_as_this_session(capsys, monkeypatch,
                                                            install_root):
    """The launcher starts at the root, but people cd into their own work."""
    conversation.queue("chase the builder")
    _prompt_from(monkeypatch, install_root / "03_Workspace" / "01_Architecture",
                 root=install_root)

    pending_hook.main([])

    assert "chase the builder" in capsys.readouterr().out


def test_a_payload_without_a_folder_is_refused(capsys, monkeypatch,
                                               install_root):
    """Cannot tell is not yes. A message that waits is recoverable."""
    conversation.queue("only for me")
    _prompt_from(monkeypatch, None, root=install_root)

    pending_hook.main([])

    assert capsys.readouterr().out == ""
    assert conversation.pending_count() == 1


def test_an_unreadable_config_is_refused_rather_than_guessed(capsys,
                                                             monkeypatch,
                                                             install_root):
    conversation.queue("only for me")
    _prompt_from(monkeypatch, install_root, root=None)

    pending_hook.main([])

    assert capsys.readouterr().out == ""
    assert conversation.pending_count() == 1


# ---------------------------------------------------------------------------
# It is actually wired
# ---------------------------------------------------------------------------

def test_the_hook_is_registered_in_the_plugin_manifest():
    """The mechanism is useless unwired — which is this package's most
    frequent defect, so the wiring is what gets tested."""
    import json
    from pathlib import Path

    manifest = json.loads(
        (Path(__file__).resolve().parents[1] / ".claude-plugin"
         / "plugin.json").read_text(encoding="utf-8"))

    entries = manifest["hooks"]["UserPromptSubmit"]
    commands = [inner["command"]
                for entry in entries for inner in entry["hooks"]]

    assert any("aki_agent.pending_hook" in one for one in commands)
    assert all("_bootstrap.py" in one for one in commands), \
        "it must go through the bootstrap, like every other shipped command"


def test_the_scheduled_collector_is_still_there():
    """Belt and braces on purpose: the hook covers the moments somebody is
    typing, the task covers the hours they are not."""
    from aki_agent import schedule

    assert schedule.get_task("collect-messages") is not None


def test_the_bootstrap_keeps_its_progress_off_stdout():
    """A prompt hook's stdout is added to the session's context.

    This file is the entry point for that hook, so on a machine where the
    environment has not been built yet the first prompt would otherwise carry
    "Setting up for the first time... Installing the pieces it needs..." into
    the conversation, as though the assistant had said it.

    Found by running the hook through the bootstrap for real. Every test above
    calls the module directly, and not one of them could see it. Progress is
    not data.
    """
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "bin"
            / "_bootstrap.py").read_text(encoding="utf-8")

    body = text.split("def say(")[1].split("\ndef ")[0]
    prints = [line for line in body.splitlines() if "print(" in line]

    assert prints, "say() should print something"
    assert all("file=sys.stderr" in line or "file=sys.stderr" in body
               for line in prints), "progress must go to stderr"
