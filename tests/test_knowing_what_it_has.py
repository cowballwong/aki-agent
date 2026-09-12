"""What the assistant has, and being able to say so.

Asked what specialists were available, an assistant answered "none, only the
main assistant", and then invented four plausible examples. There was a
built-in checker, and ten more in the library.

Nothing was broken in the code that knows. `cli specialists` had been correct
for weeks. The gap was that no file the assistant reads had ever mentioned it,
so a question about what exists was answered by a model guessing, and it
sounded exactly like an inventory.

These tests hold both halves of the fix: the command that answers, and the
instruction that sends the assistant to it.
"""

from __future__ import annotations

from pathlib import Path

from aki_agent import inventory

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_the_report_names_the_checker_that_is_always_there():
    """The one specialist every install has. Reporting "none" while this exists
    is the exact sentence that started this."""
    text = inventory.report()

    assert "sentinel" in text
    assert "built in" in text


def test_the_report_offers_what_the_library_ships():
    """A person asking what specialists they have is usually asking what they
    could have. Listed separately, because available and ready to be given work
    are different answers."""
    text = inventory.report()

    assert "document-reviewer" in text
    assert "regulation-reader" in text


def test_the_report_covers_skills_and_knowledge_too():
    """The same hole, two more stores. Neither even had a command."""
    text = inventory.report()

    assert "SKILLS" in text
    assert "KNOWLEDGE" in text


def test_an_unreadable_store_says_so_rather_than_reporting_none(monkeypatch):
    """"You have no specialists" and "I could not open the file" send a person
    to completely different places, and only one of them is ever true."""
    from aki_agent import specialists

    def refuse():
        raise OSError("the store is locked")

    monkeypatch.setattr(specialists, "read_all", refuse)
    text = inventory.report()

    assert "could not be read" in text
    assert "none of your own yet" not in text


def test_the_assistant_is_told_to_run_it():
    """The command existing is not the fix. Being sent to it is."""
    persona = (REPO_ROOT / "agents" / "assistant.md").read_text(encoding="utf-8")

    assert "aki_agent.cli inventory" in persona
    assert "never answer this one from memory" in persona.lower()


def test_the_command_is_registered():
    """A command reachable only by importing the module is not reachable."""
    source = (REPO_ROOT / "src" / "aki_agent" / "cli.py").read_text(encoding="utf-8")

    assert '"inventory"' in source
    assert "cmd_inventory" in source
