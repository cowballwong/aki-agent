"""Connecting Telegram, and generating the user's own launcher.

The launcher is the file a non-developer double-clicks. If it is wrong, the
symptom is "nothing happens", which is the least diagnosable failure there is.
So the generation is written as pure functions and checked here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fake_credentials import FAKE_BOT_TOKEN
from aki_agent import launcher, paths, telegram_setup

# The package this test suite belongs to, for checking that files the
# launcher names are really shipped.
_PACKAGE = __import__('pathlib').Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def test_status_on_a_fresh_machine_says_what_to_do_first():
    current = telegram_setup.status()

    assert current.ready is False
    assert "/plugin install" in current.next_step()


def test_a_token_that_is_not_a_token_is_refused():
    """Catches the common paste mistakes without pretending to validate it."""
    for rubbish in ("@my_bot", "1234567890", "", "the whole BotFather message"):
        ok, message = telegram_setup.save_token(rubbish, confirmed=True)
        assert ok is False
        assert "does not look like" in message


def test_a_plausible_token_is_saved_where_the_plugin_reads_it():
    ok, message = telegram_setup.save_token(
        FAKE_BOT_TOKEN, confirmed=True)

    assert ok is True
    saved = telegram_setup.token_file()
    assert saved.exists()
    assert "TELEGRAM_BOT_TOKEN=" in saved.read_text(encoding="utf-8")


def test_the_token_is_never_echoed_back():
    """Not even partially. Confirm by name, never by value."""
    token = FAKE_BOT_TOKEN
    ok, message = telegram_setup.save_token(token, confirmed=True)

    assert ok is True
    assert token not in message
    assert "AAHfake" not in message


def test_nothing_is_written_without_confirmation():
    ok, _ = telegram_setup.save_token(FAKE_BOT_TOKEN, confirmed=False)
    assert ok is False
    assert not telegram_setup.token_file().exists()


def test_the_allowlist_uses_allowlist_policy_not_pairing():
    """A pairing flow replies to strangers; an allowlist ignores them."""
    ok, message = telegram_setup.allow_user("412587349", confirmed=True)

    assert ok is True
    import json
    saved = json.loads(
        telegram_setup.access_file().read_text(encoding="utf-8"))

    assert saved["dmPolicy"] == "allowlist"
    assert "412587349" in saved["allowFrom"]
    assert "ignored silently" in message


def test_a_non_numeric_id_is_refused_with_the_fix():
    ok, message = telegram_setup.allow_user("@someone", confirmed=True)
    assert ok is False
    assert "@userinfobot" in message


def test_adding_a_second_person_keeps_the_first():
    telegram_setup.allow_user("111111", confirmed=True)
    telegram_setup.allow_user("222222", confirmed=True)

    import json
    saved = json.loads(
        telegram_setup.access_file().read_text(encoding="utf-8"))
    assert saved["allowFrom"] == ["111111", "222222"]


def test_status_never_reads_the_token_value():
    """Knowing a secret exists is a different act from handling it."""
    import inspect

    source = inspect.getsource(telegram_setup.status)
    # It may check for the key's presence, but must not parse out the value.
    assert "partition" not in source
    assert "split(" not in source


# ---------------------------------------------------------------------------
# The launcher
# ---------------------------------------------------------------------------

def test_auto_mode_is_only_added_when_asked_for():
    without = launcher.claude_arguments(launcher.LauncherOptions())
    with_auto = launcher.claude_arguments(
        launcher.LauncherOptions(auto_mode=True))

    assert "--permission-mode" not in without
    assert with_auto == ["--permission-mode", "auto"]


def test_the_launcher_never_bypasses_permissions_entirely():
    """`--dangerously-skip-permissions` is never generated, for anyone.

    Auto mode means "get on with it". Skipping permissions means "no checks at
    all", and no personal assistant on somebody's own machine needs that.
    """
    options = launcher.LauncherOptions(auto_mode=True, workspace=Path("/w"),
                                       assistant_agent="assistant")

    for text in (launcher.windows_launcher(options, Path("/pkg")),
                 launcher.macos_launcher(options, Path("/pkg"))):
        # Named exactly, not matched on the word "dangerously" (2026-09-01).
        # The launcher now also carries
        # `--dangerously-load-development-channels`, which is a different
        # thing with a similar name: it lets the assistant's OWN channel
        # server reach the session, and Claude Code offers no other route for
        # a channel somebody wrote themselves. Skipping permissions removes
        # every check there is, and stays forbidden.
        assert "--dangerously-skip-permissions" not in text
        assert "--permission-mode auto" in text


def test_both_platforms_generate_a_launcher():
    """macOS is not a later port."""
    options = launcher.LauncherOptions(workspace=Path("/w"))

    windows = launcher.windows_launcher(options, Path("/pkg"))
    macos = launcher.macos_launcher(options, Path("/pkg"))

    assert windows.startswith("@echo off")
    assert macos.startswith("#!/bin/bash")


def test_each_launcher_explains_a_missing_claude_rather_than_failing():
    options = launcher.LauncherOptions()

    for text in (launcher.windows_launcher(options, Path("/pkg")),
                 launcher.macos_launcher(options, Path("/pkg"))):
        assert "claude.com/claude-code" in text


def test_the_windows_launcher_sets_a_utf8_code_page():
    """Otherwise a workspace path in another language prints as garbage."""
    text = launcher.windows_launcher(launcher.LauncherOptions(), Path("/pkg"))
    assert "chcp 65001" in text


def test_the_launcher_goes_in_the_users_folder(tmp_path):
    """It must survive a package update or the package being moved."""
    assert str(launcher.launcher_path()).startswith(str(tmp_path))


def test_nothing_is_written_without_confirmation():
    ok, _ = launcher.write_launcher(launcher.LauncherOptions(), Path("/pkg"),
                                    confirmed=False)
    assert ok is False
    assert not launcher.launcher_path().exists()


def test_writing_the_launcher_reports_where_it_went():
    ok, message = launcher.write_launcher(
        launcher.LauncherOptions(workspace=Path("/w"), auto_mode=True),
        Path("/pkg"), confirmed=True)

    assert ok is True
    assert launcher.launcher_path().exists()
    assert "Double-click" in message


def test_the_description_says_what_auto_mode_means():
    """The user is agreeing to something; they should know what."""
    text = launcher.describe(launcher.LauncherOptions(auto_mode=True))
    assert "AUTO mode" in text
    assert "rather than asking permission" in text
    assert "never bypasses permission checks entirely" in text


def test_the_local_model_answer_is_honest():
    """Asked for, and the answer is neither 'here you go' nor 'impossible'.

    This test used to pin the opposite claim: that Ollama could not be used,
    "verified in `claude --help`". The check was real and the conclusion was
    wrong -- `--help` lists the first-party providers and says nothing about
    `ANTHROPIC_BASE_URL`, which is how the client is pointed elsewhere and
    what Ollama's own documentation uses. A test can hold a false statement
    in place as firmly as a true one.

    What has to stay honest is the other half: the plumbing is reproduced
    faithfully, and how well a small model drives a multi-step task has not
    been tested by anybody here.
    """
    text = launcher.local_model_note()

    assert "ANTHROPIC_BASE_URL" in text, "give the recipe, it is documented"
    assert "has been tested end to end" in text, "and say what has not been"
    assert "slower" in text


def test_the_windows_launcher_points_at_a_dashboard_that_exists(tmp_path):
    """The relative walk-up resolved to the Users folder plus the package
    name, which exists on no machine — so "open the dashboard alongside"
    opened nothing, said nothing, and looked exactly like a working launcher.

    Written against the property rather than the filename: the Windows
    launcher moved from `dashboard.bat` to `dashboard.vbs` (so that no console
    appears), and a test naming the file would have failed for the change
    while a launcher pointing at nothing would still have passed.
    """
    import re
    from pathlib import Path as _Path

    package_root = tmp_path / "aki-agent"
    (package_root / "bin").mkdir(parents=True)

    text = launcher.windows_launcher(
        launcher.LauncherOptions(open_dashboard=True), package_root)

    named = re.findall(r'([A-Za-z]:[^"\r\n]*?bin\\dashboard\.[a-z]+)', text)
    assert named, f"the launcher names no dashboard file:\n{text}"

    shipped = _PACKAGE / "bin" / _Path(named[0]).name
    assert shipped.is_file(), f"{shipped} is named by the launcher and is not in the package"
    assert str(package_root) in named[0], "it must be under the package it was given"
    assert r"%~dp0..\.." not in text, "a path relative to the user's own folder"


def test_setup_writes_a_launcher_and_asks_the_two_questions():
    """The launcher generator was called by nothing but its own tests."""
    from pathlib import Path as _Path

    setup = (_Path(__file__).resolve().parent.parent
             / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")

    assert "make-launcher" in setup, "setup that leaves no launcher"
    assert "--yes" in setup, "a launcher written without showing it first"
    assert "--local-model" in setup, "the Ollama question needs an honest answer"
    assert "--channels" in setup, (
        "the flag that does not exist must stay called out, or it comes back")


# ---------------------------------------------------------------------------
# Whose folder is it? -- found on a real machine, 2026-09-03
# ---------------------------------------------------------------------------
#
# The owner ran setup on a laptop already running another Claude Code
# assistant. Setup offered to write the bot token straight over that
# assistant's, and the dashboard's forgotten-PIN reset went out through that
# assistant's bot. One cause: this module derived the state folder as the
# bare shared "telegram" while the launcher exported a private one.


def test_the_state_folder_is_never_the_shared_one():
    """The shared folder belongs to whoever got there first, which may not
    be us. A name nobody chose is still better than somebody else's."""
    assert telegram_setup.channel_name("David") == "telegram-david"
    assert telegram_setup.channel_name("") != "telegram"
    assert telegram_setup.channel_dir().name != "telegram"


def test_it_agrees_with_the_process_actually_holding_the_connection(
        tmp_path, monkeypatch):
    """The launcher exports TELEGRAM_STATE_DIR and the plugin obeys it. Any
    other answer describes a folder nothing is reading."""
    told = tmp_path / "somewhere" / "telegram-someone"
    monkeypatch.setenv("TELEGRAM_STATE_DIR", str(told))

    assert telegram_setup.channel_dir() == told
    assert telegram_setup.token_file() == told / ".env"


def test_the_generated_launcher_sets_the_folder_itself(monkeypatch):
    """It was added by hand once. Setup rewrites this file, so a hand-added
    line is one setup run away from being gone -- silently, and with a
    working assistant on the other side of it."""
    monkeypatch.delenv("TELEGRAM_STATE_DIR", raising=False)

    windows = launcher.channel_block(windows=True, assistant_name="David")
    posix = launcher.channel_block(windows=False, assistant_name="David")

    assert "TELEGRAM_STATE_DIR" in windows
    assert "TELEGRAM_STATE_DIR" in posix
    for written in (windows, posix):
        assert "telegram-david" in written
        # Not the shared folder, and not by an accident of substring matching.
        assert "channels/telegram\"" not in written
        assert "channels\\telegram\r" not in written
