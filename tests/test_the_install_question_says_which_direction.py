"""The install question has to say which way things move.

The maintainer built `import-my-agent` to bring an existing assistant's memory,
scheduled work and skills INTO this one. Installing on a machine that already
had an assistant then asked him whether to "merge the useful parts into
yours" -- which is `integrate`, the opposite direction -- and he had no way to
tell from the wording, because "merge" describes an operation and not a
destination.

The whole suite passed while that was true, which is why this file exists.
"""
from __future__ import annotations

import pytest

from aki_agent import situation


@pytest.fixture
def already_has_one(tmp_path, monkeypatch):
    """A machine with somebody else's assistant on it and none of ours."""
    from aki_agent import paths

    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    monkeypatch.setattr(situation, "_signs_of_another_assistant",
                        lambda: ["~/.my-agent/config.yaml"])
    monkeypatch.setattr(situation, "_plugin_installed", lambda: False)
    return tmp_path


def _the_existing_agent_answer():
    """The report this machine gets when it already has an assistant."""
    answer = situation.detect()
    return answer if answer.kind == situation.EXISTING_AGENT else None


def test_the_question_offers_both_directions(already_has_one):
    answer = _the_existing_agent_answer()
    if answer is None:
        pytest.skip("could not reach the existing-agent situation here")

    whole = f"{answer.do_next}\n{answer.ask}".lower()

    # Their agent's contents coming INTO this one.
    assert "import-my-agent" in whole or "bring your existing" in whole, whole
    # This package's parts going INTO theirs.
    assert "integrate" in whole, whole
    # And staying apart.
    assert "separate" in whole or "side by side" in whole, whole


def test_the_question_never_says_merge(already_has_one):
    """The word that caused this. It names an operation, not a destination,
    so both directions read as the one the person was hoping for."""
    answer = _the_existing_agent_answer()
    if answer is None:
        pytest.skip("could not reach the existing-agent situation here")

    assert "merge" not in answer.ask.lower(), answer.ask


def test_the_skill_lists_three_options_not_two():
    from pathlib import Path

    skill = (Path(__file__).resolve().parents[1]
             / "skills" / "install-check" / "SKILL.md").read_text(
                 encoding="utf-8")
    assert "Three" in skill or "three options" in skill
    assert "import-my-agent" in skill, \
        "the install skill never mentions the import direction"
    assert "integrate" in skill
