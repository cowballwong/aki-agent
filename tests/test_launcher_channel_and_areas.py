"""Two defects a user found by installing it, and one this file exists to stop.

Both were reported by the maintainer on 2026-08-17 after a full install on a second
machine, and both share a shape worth naming: **the code was right and reality
disagreed, quietly.**

1. THE LAUNCHER OPENED AN ORDINARY SESSION. It never passed `--channels`,
   because an earlier check had concluded the flag did not exist -- it is
   absent from `--help`. It is a hidden flag, and it is what registers a
   session to receive pushed messages. Without it the assistant still SENDS
   fine, so every outward sign says the channel works; only messages sent to it
   go nowhere.

2. AREAS WERE CREATED WITHOUT THEIR NUMBER PREFIX. `01_Work` and `02_Personal`
   were the documented defaults, but defaults are only used by someone with no
   preference. Everybody else names their own workspaces out loud -- "work",
   "church" -- and that is what got created.

The third thing tested here was never reported, because it cannot be seen: that
a repair re-derives the channel flag instead of preserving what the old file
said. Preserving it would leave every existing user unable to receive messages
after a repair that reported success.
"""

from __future__ import annotations

from pathlib import Path

from aki_agent import launcher, scaffold, telegram_setup

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# The channel flag
# ---------------------------------------------------------------------------

def test_the_flag_is_decided_when_the_launcher_runs():
    """reported 2026-08-19: connected Telegram, and inbound never worked.

    The flag used to be baked in only if the plugin was installed at the
    moment setup wrote the launcher. Installing it afterwards -- the normal
    order -- left the launcher permanently wrong, silently. So the decision
    now happens on every start, from Claude Code's own registry.
    """
    for windows in (True, False):
        block = launcher.channel_block(windows=windows)
        assert telegram_setup.PLUGIN_ID in block, "it has to look for the plugin"
        assert f"--channels {telegram_setup.CHANNEL_SERVER}" in block
        assert "installed_plugins.json" in block


def test_the_flag_is_not_in_the_static_argument_list():
    """Nothing may decide this at write time any more, including for a
    connected user -- two places deciding is how they disagree."""
    connected = launcher.LauncherOptions(
        channel_server=telegram_setup.CHANNEL_SERVER)

    assert launcher.claude_arguments(connected) == []
    assert launcher.claude_arguments(launcher.LauncherOptions()) == []


def test_the_flag_comes_before_anything_else():
    """`--channels` takes a list, so it swallows whatever follows it."""
    script = launcher.windows_launcher(
        launcher.LauncherOptions(auto_mode=True, assistant_agent="assistant"),
        PACKAGE_ROOT)
    line = [row for row in script.splitlines()
            if row.startswith("call claude")][0]

    after = line.split("%AKI_CHANNELS%", 1)[1].split()
    assert line.index("%AKI_CHANNELS%") < line.index("--permission-mode")
    # Everything after the expansion must be a flag, or it is read as another
    # server name rather than as the argument it was meant to be.
    assert after[0].startswith("--"), after


def test_the_server_name_matches_the_plugin_it_refers_to():
    """A typo here starts normally and receives nothing, for ever."""
    assert telegram_setup.CHANNEL_SERVER.endswith(telegram_setup.PLUGIN_ID)
    assert telegram_setup.CHANNEL_SERVER.startswith("plugin:")


def test_the_windows_launcher_contains_the_flag_and_calls_claude():
    script = launcher.windows_launcher(
        launcher.LauncherOptions(channel_server=telegram_setup.CHANNEL_SERVER),
        PACKAGE_ROOT)

    assert "--channels plugin:telegram@claude-plugins-official" in script
    # Without CALL, a .bat invoking the claude .cmd shim never returns, so
    # every line after it is dead.
    assert "call claude" in script


def test_the_macos_launcher_contains_the_flag():
    script = launcher.macos_launcher(
        launcher.LauncherOptions(channel_server=telegram_setup.CHANNEL_SERVER),
        PACKAGE_ROOT)
    assert "--channels plugin:telegram@claude-plugins-official" in script


def test_the_description_states_it_either_way():
    """A silent "no" reads exactly like a yes to somebody approving this."""
    connected = launcher.describe(launcher.LauncherOptions(
        channel_server=telegram_setup.CHANNEL_SERVER))
    alone = launcher.describe(launcher.LauncherOptions())

    assert "messages sent TO" in connected
    assert "NOT receive messages" in alone


def test_the_package_no_longer_claims_the_flag_does_not_exist():
    """The wrong conclusion is what shipped the bug; it must not survive.

    Verified 2026-08-17 against Claude Code 2.1.233 by searching the installed
    binary, which carries:
        --channels <servers...>
        MCP servers whose channel notifications (inbound push) should register
        this session.
    """
    source = (PACKAGE_ROOT / "src" / "aki_agent" / "telegram_setup.py").read_text(
        encoding="utf-8")
    assert "hidden flag" in source.lower()
    assert "does not exist" not in source.split("A CORRECTION")[0]


# ---------------------------------------------------------------------------
# Area numbering
# ---------------------------------------------------------------------------

def test_spoken_names_get_numbered():
    assert scaffold.numbered(("Work", "Church")) == ("01_Work", "02_Church")


def test_names_that_already_have_a_number_are_left_alone():
    assert scaffold.numbered(("01_Work", "05_Church")) == ("01_Work",
                                                           "05_Church")


def test_a_new_area_does_not_steal_a_number_in_use():
    """Two folders numbered 01_ is worse than not numbering at all."""
    assert scaffold.numbered(("01_Work", "Church")) == ("01_Work", "02_Church")


def test_deliberate_gaps_are_respected():
    """`01_`, `05_`, `10_` means somebody left room on purpose."""
    result = scaffold.numbered(("01_Work", "05_Church", "Music"))
    assert result == ("01_Work", "05_Church", "02_Music")


def test_blank_names_are_dropped_not_numbered():
    assert scaffold.numbered(("Work", "", "  ")) == ("01_Work",)


def test_the_plan_creates_numbered_folders(tmp_path):
    plan = scaffold.plan(tmp_path, workspaces=("Work", "Church"),
                         with_examples=False)
    created = {path.name for path in plan.directories}

    assert "01_Work" in created
    assert "02_Church" in created
    assert "Work" not in created, "created the spoken name, not the folder name"


def test_the_plan_reports_the_names_it_used(tmp_path):
    """What goes into the config must be what went onto the disk.

    Writing `Church` into `workspace.workspaces` beside a folder called `02_Church`
    gives a config that points at nothing, and the dashboard renders an empty
    workspace with no error anywhere.
    """
    plan = scaffold.plan(tmp_path, workspaces=("Work", "Church"),
                         with_examples=False)
    assert plan.workspaces == ("01_Work", "02_Church")


def test_the_defaults_were_already_right():
    assert scaffold.numbered(scaffold.DEFAULT_WORKSPACES) == scaffold.DEFAULT_WORKSPACES


def test_the_windows_launcher_reopens_itself_in_windows_terminal():
    """Double-clicking a .bat gets the old console host (reported 2026-08-19).

    Three things have to be true together, and each one on its own is a bug:
    it re-launches through `wt`, it stops when already inside Terminal, and it
    falls through to the ordinary console on a machine that has no `wt`.
    """
    script = launcher.windows_launcher(launcher.LauncherOptions(),
                                       PACKAGE_ROOT)

    assert "start \"\" wt cmd /c" in script
    # Set by Windows Terminal itself. Without this check the relaunched copy
    # would relaunch again, for ever.
    assert "if defined WT_SESSION goto run" in script
    # Windows 10 without the Store app has no `wt`; it must still start.
    assert "where wt >nul 2>&1" in script
    assert "if errorlevel 1 goto run" in script
    assert ":run" in script

    # The relaunch has to come before the work, or the first copy does the
    # work and Terminal opens a second one doing it again.
    assert script.index("start \"\" wt") < script.index("call claude")
