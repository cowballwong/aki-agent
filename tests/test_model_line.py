"""One line in the launcher chooses the model, and everything obeys it.

A user, 2026-09-13, on the launcher this version writes: it is very long in
there -- is that necessary? And Ollama users should be able to switch to
another model themselves by changing one line.

The trap this file guards is the edit that only half works: a student changes
the model in the launcher, the double-click obeys, the scheduled tasks go on
running the old model from `state/backend.json`, and the next upgrade rewrites
the launcher with the old value. So the line is not a copy of the record -- it
is read back as the answer.
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


@pytest.fixture(params=[True, False], ids=["windows", "macos"])
def platform(request, monkeypatch):
    monkeypatch.setattr(paths, "is_windows", lambda: request.param)
    return request.param


def ollama(model="qwen3.5"):
    backend.remember(backend.Backend(base_url="http://localhost:11434",
                                     model=model, token="ollama"))


def options():
    return launcher.LauncherOptions(workspace=Path.home(), assistant_agent="assistant",
                                    auto_mode=True, open_dashboard=True, title="Aki")


def write(platform):
    ok, _ = launcher.write_launcher(options(), Path.home() / "engine", confirmed=True)
    assert ok
    return launcher.launcher_path().read_text(encoding="utf-8")


def edit_model(text, new, windows):
    old_line = next(l for l in text.splitlines() if "AKI_MODEL=" in l)
    new_line = f"set AKI_MODEL={new}" if windows else f'AKI_MODEL="{new}"'
    launcher.launcher_path().write_text(text.replace(old_line, new_line), encoding="utf-8")


def test_the_model_is_one_line_near_the_top(platform):
    ollama()
    text = write(platform)
    lines = text.splitlines()
    setting = [i for i, l in enumerate(lines) if "AKI_MODEL=" in l]
    assert len(setting) == 1, "exactly one place to change it"
    assert setting[0] < 10, "found without scrolling"
    assert "qwen3.5" in lines[setting[0]]
    uses = "--model %AKI_MODEL%" if platform else '--model "$AKI_MODEL"'
    assert uses in text
    assert "--model qwen3.5" not in text, "no second literal to fall out of step"


def test_scheduled_work_uses_the_edited_line(platform):
    ollama("qwen3.5")
    edit_model(write(platform), "llama3.1:8b", platform)
    brain = backend.stored()
    assert brain.model == "llama3.1:8b"
    assert brain.arguments() == ["--model", "llama3.1:8b"]


def test_rewriting_the_launcher_keeps_the_edit(platform):
    ollama("qwen3.5")
    edit_model(write(platform), "gemma3:12b", platform)
    text = write(platform)                       # what repair / upgrade does
    assert launcher.model_in(text) == "gemma3:12b"


def test_an_ordinary_install_has_no_setting_and_no_model(platform):
    text = write(platform)
    assert "AKI_MODEL" not in text
    assert "--model" not in text
    assert backend.stored().is_default


def test_the_record_still_answers_when_the_launcher_has_no_line(platform):
    ollama("qwen3.5")
    assert not launcher.launcher_path().exists()
    assert backend.stored().model == "qwen3.5"


def test_the_launcher_is_mostly_commands_not_prose(platform):
    """The reasons live in launcher.py; the file a student opens stays short."""
    ollama()
    text = write(platform)
    marker = "REM" if platform else "#"
    comments = [l for l in text.splitlines()
                if l.strip().startswith(marker) and not l.startswith("#!")]
    assert len(comments) <= 6, comments
    assert len(text.splitlines()) <= 55
    # The choices a repair reads back are all still there.
    assert launcher.choices_in(text) == {"auto_mode": True, "open_dashboard": True,
                                         "assistant_agent": "assistant"}
