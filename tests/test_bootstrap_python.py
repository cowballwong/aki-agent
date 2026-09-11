"""Finding a Python that works, on a machine whose default one does not.

Apple ships 3.9.6 as `python3`. It is first on PATH, every `.command` here
resolves it, and this package needs 3.10. Until that was fixed, a stock Mac
install stopped there: `_bootstrap.py` printed "install a current Python" and
gave up, including to people who already had one installed somewhere it had
not looked.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

BOOTSTRAP = Path(__file__).resolve().parents[1] / "bin" / "_bootstrap.py"


def load():
    spec = importlib.util.spec_from_file_location("_aki_bootstrap", BOOTSTRAP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# It has to be readable by the Python it is going to reject
# ---------------------------------------------------------------------------

def test_it_parses_under_the_oldest_python_it_must_speak_to():
    """The politest possible refusal is worth nothing if the file cannot be
    read far enough to print it. One `X | Y` annotation evaluated at runtime,
    or one `match`, and Apple's 3.9 raises SyntaxError instead -- which is the
    same dead end with a worse message."""
    ast.parse(BOOTSTRAP.read_text(encoding="utf-8"), feature_version=(3, 9))


# ---------------------------------------------------------------------------
# Where an installed Python actually is
# ---------------------------------------------------------------------------

def test_homebrew_and_python_org_are_named_outright(monkeypatch):
    """A `.command` double-clicked in Finder starts with a minimal PATH.
    Homebrew's folder is frequently not on it, and the python.org installer
    writes its PATH line into a shell profile a non-interactive bash never
    reads. Searching by bare name alone finds neither."""
    module = load()
    monkeypatch.setattr(module.sys, "platform", "darwin")
    flat = [" ".join(command) for command in module.python_candidates()]

    assert any("/opt/homebrew/bin/python3" in one for one in flat)
    assert any("Python.framework" in one for one in flat)
    assert any(one == "python3.12" for one in flat)


def test_windows_gets_the_py_launcher(monkeypatch):
    """Installed even when the user missed 'Add Python to PATH', which is the
    box people miss."""
    module = load()
    monkeypatch.setattr(module.sys, "platform", "win32")
    assert ["py", "-3"] in module.python_candidates()


def test_newer_is_preferred_to_merely_adequate(monkeypatch):
    module = load()
    monkeypatch.setattr(module.sys, "platform", "darwin")
    flat = [" ".join(command) for command in module.python_candidates()]
    assert flat.index("python3.13") < flat.index("python3.10")


# ---------------------------------------------------------------------------
# Handing over
# ---------------------------------------------------------------------------

def test_a_current_python_hands_over_to_nobody(monkeypatch):
    """None means "carry on in this process"."""
    module = load()
    assert module.relaunch_under_newer_python(["_bootstrap.py", "x"]) is None


def test_the_child_does_not_search_again(monkeypatch):
    """The loop guard. Without it, a machine where every candidate reports a
    version this file disagrees with forks until something falls over."""
    module = load()
    monkeypatch.setattr(module.sys, "version_info", (3, 9, 6))
    monkeypatch.setenv(module.RELAUNCH_FLAG, "1")
    assert module.relaunch_under_newer_python(["_bootstrap.py", "x"]) is None


def test_an_old_python_hands_the_whole_command_to_a_newer_one(monkeypatch):
    """What the user asked for has to survive the hand-over -- module name and
    arguments both. A relaunch that ran `doctor` because it forgot the rest
    would look like it worked."""
    module = load()
    monkeypatch.setattr(module.sys, "version_info", (3, 9, 6))
    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.delenv(module.RELAUNCH_FLAG, raising=False)
    monkeypatch.setattr(module, "python_candidates",
                        lambda: [["python3.9-too-old"], ["python3.12"]])
    monkeypatch.setattr(module, "is_new_enough",
                        lambda command: command == ["python3.12"])

    seen = {}

    class Done:
        returncode = 7

    def fake_run(command, env=None, check=False, **kw):
        seen["command"] = command
        seen["env"] = env
        return Done()

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    code = module.relaunch_under_newer_python(
        ["_bootstrap.py", "aki_agent.cli", "make-launcher", "--dashboard"])

    assert code == 7
    assert seen["command"][0] == "python3.12"
    assert seen["command"][-3:] == ["aki_agent.cli", "make-launcher",
                                    "--dashboard"]
    assert seen["env"][module.RELAUNCH_FLAG] == "1"


def test_nothing_newer_found_falls_through_to_the_advice(monkeypatch):
    """When there genuinely is no other Python, the old message is still the
    right answer -- so the caller must get None, not a failure code."""
    module = load()
    monkeypatch.setattr(module.sys, "version_info", (3, 9, 6))
    monkeypatch.delenv(module.RELAUNCH_FLAG, raising=False)
    monkeypatch.setattr(module, "is_new_enough", lambda command: False)
    assert module.relaunch_under_newer_python(["_bootstrap.py", "x"]) is None


def test_a_python_is_judged_by_running_it(monkeypatch):
    """Not by its name, and not by `which`. The Windows Store stub answers to
    `python`, is zero bytes, and opens a shop when you run it."""
    module = load()
    assert module.is_new_enough([sys.executable]) is True
    assert module.is_new_enough(["definitely-not-a-python-9f3a"]) is False
