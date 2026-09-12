"""The permissions this assistant grants itself, and the ones it must not.

A user asked their assistant, from their phone, to look something up, and was
told the web tools had no permission in that session. They did not: nothing in
this package had ever written a permission of any kind.

At a keyboard that is a prompt somebody presses a key on. From a phone it is
a session waiting on an answer nobody can see.
"""

from __future__ import annotations

import json

import pytest

from aki_agent import permissions


def test_the_web_tools_are_granted(tmp_path):
    ok, said = permissions.ensure(tmp_path)

    assert ok, said
    written = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert written["permissions"]["allow"] == ["WebSearch", "WebFetch"]


def test_it_is_written_in_the_workspace_not_the_home_folder(tmp_path):
    """`~/.claude/settings.json` applies to every Claude Code session on the
    machine, including other people's assistants. This package has already
    installed hooks globally once and done damage inside a different
    assistant's sessions. An assistant configures itself, never the machine."""
    permissions.ensure(tmp_path)

    assert (tmp_path / ".claude" / "settings.json").is_file()
    assert str(permissions.settings_file(tmp_path)).startswith(str(tmp_path))


def test_nothing_the_user_put_there_is_lost(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({
        "model": "opus",
        "permissions": {"allow": ["Bash(ls)"], "deny": ["Read(./secrets/**)"]},
    }), encoding="utf-8")

    permissions.ensure(tmp_path)

    written = json.loads(settings.read_text(encoding="utf-8"))
    assert written["model"] == "opus"
    assert written["permissions"]["deny"] == ["Read(./secrets/**)"]
    assert "Bash(ls)" in written["permissions"]["allow"]
    assert "WebSearch" in written["permissions"]["allow"]


def test_running_it_twice_changes_nothing(tmp_path):
    permissions.ensure(tmp_path)
    first = (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")

    ok, said = permissions.ensure(tmp_path)

    assert ok and "already" in said
    assert (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8") == first


def test_a_file_that_will_not_parse_is_left_alone(tmp_path):
    """Overwriting it would destroy settings this package did not write."""
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{ this is not json", encoding="utf-8")

    ok, said = permissions.ensure(tmp_path)

    assert not ok
    assert "could not be read" in said
    assert settings.read_text(encoding="utf-8") == "{ this is not json"


def test_scheduled_work_is_not_widened():
    """Headless runs carry their own explicit allowlist, and it is deliberately
    narrow. Granting the web tools to the assistant's own sessions must not
    reach a scheduled job nobody is watching."""
    from aki_agent import runner

    allowed = runner.scheduled_tools()

    assert "WebSearch" not in allowed
    assert "WebFetch" not in allowed


@pytest.mark.parametrize("tool", permissions.GRANTED)
def test_every_granted_tool_is_read_only(tool):
    """The list is allowed to grow, but not in this direction. Anything that
    writes, sends or spends belongs behind the prompt."""
    assert tool in ("WebSearch", "WebFetch")
