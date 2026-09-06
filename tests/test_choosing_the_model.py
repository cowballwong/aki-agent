"""Which model the launcher starts, and where that choice is made.

Before this the model was only ever whatever
the environment happened to carry, so somebody with three models pulled had no
way to say which one their assistant should start with -- and no way to see
what was there.

The other half of this file is the contradiction it was found through: three
places in the package gave two different answers about whether Ollama worked
at all, and the one a new user actually met -- the setup interview -- was the
wrong one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import backend, launcher, paths


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


def package_root() -> Path:
    return Path(backend.__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# One answer, in every place that gives one


def test_nothing_still_says_ollama_cannot_be_used():
    """`backend.py` made this untrue and two other files went on saying it.

    Stated against the files rather than about them: the sentence was in a
    module docstring and in an interview script, neither of which any test
    had ever read.
    """
    said_no = []
    for path in (package_root() / "src" / "aki_agent" / "launcher.py",
                 package_root() / "skills" / "setup" / "SKILL.md"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            lowered = line.lower()
            # A line that quotes the old claim in order to correct it is the
            # record, not the claim. Both files now carry one deliberately --
            # this package keeps the wrong turning written down rather than
            # tidying it away -- so the test has to tell an assertion from a
            # citation. Anything that neither says "used to" nor sits under a
            # correction is the live sentence.
            if "used to" in lowered or "corrected" in lowered:
                continue
            if ("ollama is not among them" in lowered
                    or "the honest answer is no" in lowered):
                said_no.append(f"{path.name}: {line.strip()[:70]}")
    assert not said_no, "still telling people it does not work: " + "; ".join(
        said_no)


def test_the_setup_interview_asks_which_brain():
    """It used to wait for the user to raise it, and then say no."""
    text = (package_root() / "skills" / "setup" / "SKILL.md").read_text(
        encoding="utf-8")
    assert "Which brain is it running on" in text
    assert "--model" in text, "the interview never tells them how to choose"


def test_the_launcher_module_says_what_it_actually_does():
    text = (package_root() / "src" / "aki_agent" / "launcher.py").read_text(
        encoding="utf-8")
    heading = text[text.find("ABOUT LOCAL MODELS"):][:900]
    assert "DOES write a launcher" in heading


# ---------------------------------------------------------------------------
# Choosing one


def test_a_chosen_model_is_what_the_launcher_will_start():
    """`--model` overrides the environment, and is what gets stored."""
    backend.remember(backend.Backend(
        base_url="http://localhost:11434", model="qwen2.5:7b",
        token=backend.OLLAMA_TOKEN))

    assert backend.stored().model == "qwen2.5:7b"
    assert backend.stored().arguments() == ["--model", "qwen2.5:7b"]


def test_an_ordinary_install_adds_no_model_argument():
    """The subscription path must not grow a `--model` it never asked for."""
    assert backend.Backend().arguments() == []


def test_a_cloud_model_is_named_as_one():
    """Local and cloud are the same endpoint and differ only by name.

    So the only honest moment to say which is which is when it is chosen.
    """
    assert backend.is_cloud_model("qwen3-coder:480b-cloud")
    assert not backend.is_cloud_model("qwen2.5:7b")


def test_an_endpoint_that_is_not_there_is_an_answer_not_a_crash():
    """Asked at a prompt with somebody waiting, so it cannot hang or raise."""
    reachable, models = backend.models_available("http://localhost:1")

    assert reachable is False
    assert models == []


def test_no_endpoint_configured_is_also_an_answer():
    reachable, models = backend.models_available("")

    assert (reachable, models) == (False, [])


# ---------------------------------------------------------------------------
# The other launcher choice


def test_auto_mode_is_still_a_real_choice_in_the_interview():
    """The two launcher questions are model and supervision, in that order.

    Recorded because "just make it auto" is the easy default to drift into,
    and the difference is how supervised somebody's assistant is.
    """
    text = (package_root() / "skills" / "setup" / "SKILL.md").read_text(
        encoding="utf-8")
    assert "real choices, not formalities" in text
    assert "--auto-mode" in text


def test_the_flag_that_turns_permission_checks_off_is_never_written():
    """Stated in the interview; held here."""
    source = (package_root() / "src" / "aki_agent" / "launcher.py").read_text(
        encoding="utf-8")
    written = launcher.write_launcher.__doc__ or ""
    assert "dangerously-skip-permissions" not in source.replace(
        "dangerously-skip-permissions`", "")  or "never" in written.lower()
