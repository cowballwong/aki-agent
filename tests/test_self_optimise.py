"""Self-optimisation, and the two things it must never do.


MUST NEVER DO, ONE: report a run as successful because it finished. That
happened in an earlier system -- the code checked that the script exited and
that a card had been rewritten, and a rewritten card is evidence of a file
having been written, not of anything having been learned.

MUST NEVER DO, TWO: let somebody pick one of Ollama's *hosted* models thinking
it is local. Ollama lists those in the same place as the ones on your disk;
The maintainer's own machine has `gemma4:31b-cloud` sitting between two local ones.
Choosing it silently makes "nothing leaves the machine" false and starts
spending metered credit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aki_agent import optimising, paths, traces

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "src" / "aki_agent" / "dashboard" / "templates"
PAGE = TEMPLATES / "_optimise.html"


@pytest.fixture
def own_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    return tmp_path


# ---------------------------------------------------------------------------
# What it costs, said where the choice is made
# ---------------------------------------------------------------------------

def test_the_local_option_is_offered_first():
    """It is the only one of the three that keeps the promise `traces.py`
    makes about this data."""
    assert optimising.PROVIDERS[0][0] == "ollama"


def test_the_page_says_this_one_sends_your_corrections_away():
    """"Learn from You" is local and free and its module defends that at
    length. This is the other road, and the difference belongs where the
    choice is made rather than in a message that scrolls past."""
    # Whitespace collapsed: the sentence is wrapped across lines in the
    # template, and asserting on the raw text would fail on a line break
    # rather than on anything a reader would notice.
    page = " ".join(PAGE.read_text(encoding="utf-8").split())

    assert "sends your corrections to a model" in page
    assert "nothing leaves the machine" in page
    assert "Learn from You" in page, "the contrast has to be reachable"


def test_every_provider_says_what_it_needs_and_where_it_sends():
    for key, label, why in optimising.PROVIDERS:
        assert label and why
        if key == "ollama":
            assert "leaves" in why or "Nothing leaves" in why
        else:
            assert "sent to" in why
            assert "KEY" in why, f"{key} does not say which key it needs"


def test_dspy_is_not_a_hard_dependency():
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "dspy" not in text


# ---------------------------------------------------------------------------
# Ollama's cloud models
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, cloud", [
    ("gemma4:31b-cloud", True),
    ("qwen2.5:7b-instruct", False),
    ("qwen2.5:3b", False),
    ("", False),
])
def test_a_hosted_model_is_recognised(name, cloud):
    assert optimising.is_cloud(name) is cloud


def test_the_page_marks_them_and_says_they_are_metered():
    page = PAGE.read_text(encoding="utf-8")

    assert "one.cloud" in page, "the list does not distinguish them at all"
    assert "metered" in page


def test_a_hosted_model_is_marked_in_the_state(monkeypatch):
    monkeypatch.setattr(optimising, "local_models",
                        lambda: (True, ["gemma4:31b-cloud", "qwen2.5:3b"]))

    listed = optimising.state()["local_models"]
    assert listed == [{"name": "gemma4:31b-cloud", "cloud": True},
                      {"name": "qwen2.5:3b", "cloud": False}]


def test_not_running_and_no_models_are_different_answers(monkeypatch):
    """One empty list cannot say which it is, and the two need different
    things done about them."""
    monkeypatch.setattr(optimising, "_ask_ollama", lambda *a, **k: (False, None))
    assert optimising.local_models() == (False, [])

    monkeypatch.setattr(optimising, "_ask_ollama",
                        lambda *a, **k: (True, {"models": []}))
    assert optimising.local_models() == (True, [])


def test_ollama_being_absent_is_an_answer_not_an_exception(monkeypatch):
    """It is the normal state on most machines."""
    monkeypatch.setattr(optimising, "OLLAMA_URL", "http://localhost:1")
    reachable, found = optimising.local_models()
    assert reachable is False and found == []


def test_pulling_without_ollama_changes_nothing(monkeypatch):
    monkeypatch.setattr(optimising, "local_models", lambda: (False, []))

    ok, said = optimising.pull_model("qwen2.5:7b")
    assert not ok
    assert "not answering" in said
    assert "nothing was downloaded" in said.lower()


def test_pulling_checks_afterwards_rather_than_trusting_the_reply(monkeypatch):
    """A success code is not the thing itself -- the same rule every other
    install in this package follows."""
    monkeypatch.setattr(optimising, "local_models", lambda: (True, []))
    monkeypatch.setattr(optimising, "_ask_ollama", lambda *a, **k: (True, {}))

    ok, said = optimising.pull_model("qwen2.5:7b")
    assert not ok
    assert "not in its list afterwards" in said


# ---------------------------------------------------------------------------
# The page loading must not wait on the network
# ---------------------------------------------------------------------------

def test_the_state_can_be_read_without_touching_ollama(monkeypatch):
    """`local_models()` is an HTTP request with a timeout, and this was being
    called on every render of the Memory page -- so the EOD tab paid for a
    connection attempt, and a machine with no Ollama paid the whole timeout.
    Measured in the suite as 74s -> 155s before this existed."""
    called = []
    monkeypatch.setattr(optimising, "local_models",
                        lambda: (called.append(1), (True, []))[1])

    optimising.state(ask_ollama=False)
    assert not called

    optimising.state(ask_ollama=True)
    assert called


def test_only_its_own_tab_pays_for_it():
    source = (REPO_ROOT / "src" / "aki_agent" / "dashboard"
              / "app.py").read_text(encoding="utf-8")
    assert 'ask_ollama=(tab == "optimise")' in source


# ---------------------------------------------------------------------------
# Refusing to claim it worked
# ---------------------------------------------------------------------------

def test_it_will_not_run_without_dspy(own_home, monkeypatch):
    monkeypatch.setattr(optimising, "available", lambda: False)

    done = optimising.run()
    assert not done.ok
    assert "not installed" in done.sentence()


def test_it_refuses_to_learn_from_too_little(own_home, monkeypatch):
    """Below about a dozen verdicts an "optimisation" is fitting to noise --
    and worse, fitting to noise convincingly, because the output is prose
    that reads like insight."""
    monkeypatch.setattr(optimising, "available", lambda: True)
    for number in range(3):
        traces.log("summary", f"draft {number}", "edited",
                   correction="shorter please")

    done = optimising.run()
    assert not done.ok
    assert "noise" in done.sentence()


def test_the_outcome_can_say_it_changed_nothing(own_home):
    """"It ran" and "it learned" are different sentences, and the second one
    must not be printed for the first."""
    nothing = optimising.Outcome(ok=True, examples=40, tasks_looked_at=2,
                                 unchanged=["summary", "email"])
    said = nothing.sentence()

    assert "nothing worth changing" in said
    assert "Nothing was overwritten" in said
    assert "improved" not in said


def test_the_outcome_names_what_it_improved(own_home):
    done = optimising.Outcome(ok=True, examples=40, tasks_looked_at=2,
                              improved=["summary"], unchanged=["email"])
    said = done.sentence()

    assert "improved 1: summary" in said
    assert "1 left as they were" in said


def test_a_card_is_only_replaced_by_a_better_one():
    """The heart of it. Not "DSPy finished", not "a card was produced" --
    both of those were true on the day an earlier system reported success
    having learned nothing."""
    source = (REPO_ROOT / "src" / "aki_agent"
              / "optimising.py").read_text(encoding="utf-8")

    start = source.index("def run(")
    body = source[start:]

    assert "covers(suggested) <= covers(before)" in body, (
        "nothing compares the new guidance with the old one")
    assert "held = corrections[-2:]" in body, (
        "the score is being marked against the same lines it was written "
        "from, which is not a score")


def test_the_scheduled_run_reports_what_the_optimiser_said():
    """Flattening its answer into "ran" is how the earlier system came to
    report a failure as a success."""
    source = (REPO_ROOT / "src" / "aki_agent"
              / "tasks.py").read_text(encoding="utf-8")

    start = source.index('if task.prompt.strip() == "__optimise__":')
    body = source[start:start + 700]

    assert "done.sentence()" in body
    assert "TaskOutcome(key, done.ok" in body, (
        "a failed optimisation must not be recorded as a successful run")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def test_settings_round_trip(own_home):
    optimising.save_settings("openai", "gpt-4.1-mini", 5, 30)
    back = optimising.read_settings()

    assert back["provider"] == "openai"
    assert back["model"] == "gpt-4.1-mini"
    assert (back["hour"], back["minute"]) == (5, 30)


def test_an_unknown_provider_falls_back_to_the_local_one(own_home):
    optimising.save_settings("something-else", "x", 4, 0)
    assert optimising.read_settings()["provider"] == "ollama"


def test_an_impossible_time_is_clamped(own_home):
    optimising.save_settings("ollama", "qwen2.5:3b", 99, 99)
    back = optimising.read_settings()
    assert (back["hour"], back["minute"]) == (23, 59)


def test_the_provider_decides_which_model_field_is_read():
    """The form shows one and hides the other, and a hidden input still
    posts -- so "whichever is not empty" would read the stale one."""
    source = (REPO_ROOT / "src" / "aki_agent" / "dashboard"
              / "app.py").read_text(encoding="utf-8")
    assert 'if provider == "ollama"' in source
    assert 'request.form.get("model_local", "")' in source
    assert 'request.form.get("model_api", "")' in source


def test_it_borrows_the_scheduler_rather_than_building_one():
    source = (REPO_ROOT / "src" / "aki_agent"
              / "optimising.py").read_text(encoding="utf-8")
    assert "schedule.save_user_task" in source
    assert "schedule.install" in source
    assert optimising.task_for(4, 0).work == "loop"
    assert optimising.task_for(4, 0).prompt == "__optimise__"
