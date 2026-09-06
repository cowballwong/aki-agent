"""The launcher and the scheduled tasks must reach the same brain the session did.



Ollama publishes the recipe — three environment variables and `--model` on the
command line. Both halves live somewhere this package could not see: the
variables in the terminal the student typed them into, the model in one
argument to one command.

So an assistant set up by somebody running a local model would write a
launcher that starts a Claude Code talking to a service they are not signed in
to, and install scheduled tasks that do the same every morning. It would work
all day in their own terminal and fail everywhere else, and the error would
name none of it.
"""

from __future__ import annotations

import pytest

from aki_agent import backend, launcher, paths


OLLAMA = {
    "ANTHROPIC_BASE_URL": "http://localhost:11434",
    "ANTHROPIC_AUTH_TOKEN": "ollama",
    "ANTHROPIC_API_KEY": "",
}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    return tmp_path


# ---------------------------------------------------------------------------
# Knowing


def test_an_ordinary_install_is_recognised_as_ordinary():
    found = backend.detect({})

    assert found.is_default
    assert found.environment() == {}
    assert found.arguments() == []


def test_an_ollama_session_is_recognised(home):
    found = backend.detect(OLLAMA)

    assert found.is_default is False
    assert found.is_ollama
    assert found.is_local
    assert "Ollama" in found.sentence()


def test_a_custom_endpoint_that_is_not_ollama_is_not_called_ollama():
    """Naming it wrongly sends somebody to the wrong documentation."""
    found = backend.detect({"ANTHROPIC_BASE_URL": "https://gateway.example.com",
                            "ANTHROPIC_AUTH_TOKEN": "sk-real-credential"})

    assert found.is_ollama is False
    assert found.is_local is False
    assert "gateway.example.com" in found.sentence()


# ---------------------------------------------------------------------------
# Refusing to keep a credential


def test_a_real_token_is_never_written_down(home):
    """The fact that one is needed is recorded. The value is not.

    A config file sits in a synced folder. A key that reaches one cannot be
    recalled from everywhere it then travels.
    """
    found = backend.detect({"ANTHROPIC_BASE_URL": "https://gateway.example.com",
                            "ANTHROPIC_AUTH_TOKEN": "sk-real-credential"})
    backend.remember(found)

    kept = backend.stored()
    written = (paths.app_dir() / "state" / "backend.json").read_text(
        encoding="utf-8")

    assert kept.needs_token is True
    assert kept.token == ""
    assert "sk-real-credential" not in written


def test_ollamas_own_word_is_kept_because_it_is_not_a_secret(home):
    """`ANTHROPIC_AUTH_TOKEN=ollama` is a literal the client requires and the
    server ignores. Refusing it would break the thing this exists to fix."""
    backend.remember(backend.detect(OLLAMA))

    assert backend.stored().token == "ollama"


# ---------------------------------------------------------------------------
# Reproducing it


def test_the_environment_a_fresh_process_needs(home):
    settings = backend.detect(OLLAMA).environment()

    assert settings["ANTHROPIC_BASE_URL"] == "http://localhost:11434"
    assert settings["ANTHROPIC_AUTH_TOKEN"] == "ollama"
    assert settings["ANTHROPIC_API_KEY"] == "", (
        "left set, the client prefers the key and never reaches localhost")


def test_the_model_travels_as_a_command_line_argument(home):
    """It is never in the environment, so carrying only the variables reaches
    the right endpoint and asks it for the wrong model."""
    found = backend.detect(OLLAMA)
    found.model = "qwen3.5"

    assert found.arguments() == ["--model", "qwen3.5"]


def test_the_windows_launcher_carries_the_variables(home):
    backend.remember(backend.detect(OLLAMA))

    block = launcher.backend_block(windows=True)

    assert "set ANTHROPIC_BASE_URL=http://localhost:11434" in block
    assert "set ANTHROPIC_AUTH_TOKEN=ollama" in block
    assert block.endswith("\r\n"), "a .bat needs CRLF or it runs as one line"


def test_the_unix_launcher_carries_them_too(home):
    backend.remember(backend.detect(OLLAMA))

    block = launcher.backend_block(windows=False)

    assert 'export ANTHROPIC_BASE_URL="http://localhost:11434"' in block


def test_an_ordinary_install_gets_no_block_at_all(home):
    """Nothing changes for anybody who changed nothing."""
    backend.remember(backend.detect({}))

    assert launcher.backend_block(windows=True) == ""
    assert launcher.backend_block(windows=False) == ""


def test_scheduled_runs_read_the_record_not_their_own_environment(home,
                                                                  monkeypatch):
    """A task inherits whatever Task Scheduler holds.

    Guessing from that would make the assistant's brain depend on which
    process happened to start it — the failure this whole thing prevents.
    """
    backend.remember(backend.detect(OLLAMA))
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

    assert backend.stored().base_url == "http://localhost:11434"


def test_nothing_recorded_means_ordinary_not_whatever_is_lying_around(home,
                                                                     monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:11434")

    assert backend.stored().is_default, (
        "an unrecorded install must not inherit a stray variable")


# ---------------------------------------------------------------------------
# Saying so


def test_doctor_says_which_brain_and_warns_when_it_changed(home, monkeypatch):
    """Set up on Anthropic, now running Ollama: the background work still
    expects the old one, and nothing else would ever mention it."""
    from aki_agent import doctor

    backend.remember(backend.detect({}))
    monkeypatch.setattr(backend, "detect", lambda *a, **k: backend.Backend(
        base_url="http://localhost:11434", token="ollama"))

    check = doctor.check_which_brain()

    assert check.ok is False
    assert "scheduled tasks" in check.detail
    assert check.fix, "a warning with no next step is a nag"


def test_the_local_model_note_no_longer_says_it_cannot_be_done():
    """It said so for a while, "verified in `claude --help`".

    The observation was true and the conclusion was not: `--help` lists the
    first-party providers and says nothing about `ANTHROPIC_BASE_URL`, which
    is the documented way to point the client elsewhere. Ollama publishes the
    recipe. Checking the right thing badly reads exactly like checking the
    right thing.
    """
    note = launcher.local_model_note()

    assert "ANTHROPIC_BASE_URL" in note, "it should give the actual recipe"
    assert "cannot" not in note.lower()
    assert "not one of them" not in note.lower()


def test_the_note_still_says_what_has_not_been_tested():
    """Correcting one overclaim is not licence for another.

    The plumbing is reproduced faithfully. How well a small model drives a
    multi-step task is a different question and nobody here has run it.
    """
    note = launcher.local_model_note()

    assert "has been tested end to end" in note
    assert "slower" in note
