"""Generated commands have to be runnable on the platform they land on.

Every change to this package ships both halves, and a Windows-only fix is not
a finished fix. This file is that rule applied to one word. macOS has no bare
`python` -- Apple removed Python 2 and never shipped one -- so every generated
line beginning with `python` was a line a Mac user could not run, including
the launcher's own preflight and every `fix:` line `doctor` prints.
"""

from __future__ import annotations

from pathlib import Path

from aki_agent import engine, launcher


def test_the_word_for_python_follows_the_platform(monkeypatch):
    monkeypatch.setattr(engine.os, "name", "nt")
    assert engine.python_word() == "python"

    monkeypatch.setattr(engine.os, "name", "posix")
    assert engine.python_word() == "python3"


def test_a_generated_command_uses_that_word(monkeypatch):
    """Patched at `python_word` rather than at `os.name`: pathlib reads the
    same flag, and flipping it on Windows makes every Path in the call stack
    refuse to exist."""
    monkeypatch.setattr(engine, "python_word", lambda: "python3")
    assert engine.how_to_run("aki_agent.doctor").startswith("python3 ")


def test_the_macos_launcher_never_says_bare_python():
    """The preflight line runs at every start. On a Mac the old one printed
    `command not found`, and the check it was guarding -- is the messaging
    channel connected -- never ran. A silent absence, which is the exact
    failure the preflight exists to prevent."""
    options = launcher.LauncherOptions(title="Assistant", check_channel=True)
    text = launcher.macos_launcher(options, Path("/opt/engine"))

    for line in text.splitlines():
        assert not line.strip().startswith("python "), line


def test_the_windows_launcher_still_says_python():
    """`python3` is not a thing on Windows, and the Store stub is what a
    machine without Python answers with. Neither half may fix the other."""
    options = launcher.LauncherOptions(title="Assistant", check_channel=True)
    text = launcher.windows_launcher(options, Path(r"C:\engine"))

    assert 'python "' in text
    assert "python3" not in text
