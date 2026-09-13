"""Group D: what a student hits before anything has worked once.

These failures are worse than their size suggests, because they all land
before the person has any reason to believe the software works at all. A bug
on day thirty is a bug; the same bug on the first screen is the whole product.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
BIN = PACKAGE_ROOT / "bin"


# ---------------------------------------------------------------------------
# D1. The commands in the skills have to run where skills actually run
# ---------------------------------------------------------------------------

def test_the_launcher_is_written_where_the_skills_look_for_it(tmp_path,
                                                              monkeypatch):
    """The plugin records its own location every time it runs.

    It can, because the hooks in `plugin.json` DO get the plugin-root variable
    substituted and they fire on every prompt. So by the time anybody runs a
    command by hand, the launcher is already there and correct -- including
    straight after an update that moved the plugin into a new version folder.
    """
    sys.path.insert(0, str(BIN))
    import _bootstrap                                     # noqa: E402

    monkeypatch.setattr(_bootstrap.Path, "home", staticmethod(lambda: tmp_path))

    _bootstrap.remember_where_i_am()

    pointer = tmp_path / ".aki-agent" / "plugin-root"
    shim = tmp_path / ".aki-agent" / "aki.py"

    assert pointer.read_text(encoding="utf-8").strip() == str(PACKAGE_ROOT)
    assert shim.exists(), "the skills have nothing to call"

    # It points at this copy of the package, not a guess at one. Compared
    # against the `repr`, because that is how the path is embedded -- a raw
    # Windows path in a Python source file would read `\a` as a bell.
    assert repr(str(BIN / "_bootstrap.py")) in shim.read_text(encoding="utf-8")


def test_the_launcher_is_rewritten_when_the_plugin_moves(tmp_path,
                                                         monkeypatch):
    """An update lands in a new version folder. A launcher left pointing at
    the old one runs a copy that is about to be deleted, and nothing about
    that looks wrong until it silently stops working."""
    sys.path.insert(0, str(BIN))
    import _bootstrap                                     # noqa: E402

    monkeypatch.setattr(_bootstrap.Path, "home", staticmethod(lambda: tmp_path))

    shim = tmp_path / ".aki-agent" / "aki.py"
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text("# left over from version 0.28.0\n", encoding="utf-8")

    _bootstrap.remember_where_i_am()

    assert "0.28.0" not in shim.read_text(encoding="utf-8")


def test_the_launcher_is_valid_python(tmp_path, monkeypatch):
    """It is generated from a template that contains braces and a docstring.

    The first version built it with `str.format`, and the template documents a
    `${...}` variable -- so `format` read those braces as fields of its own and
    raised. The whole function swallows exceptions, so the pointer appeared and
    the launcher silently did not.
    """
    sys.path.insert(0, str(BIN))
    import _bootstrap                                     # noqa: E402

    monkeypatch.setattr(_bootstrap.Path, "home", staticmethod(lambda: tmp_path))
    _bootstrap.remember_where_i_am()

    body = (tmp_path / ".aki-agent" / "aki.py").read_text(encoding="utf-8")
    compile(body, "aki.py", "exec")


def test_recording_where_we_are_never_stops_the_command(tmp_path, monkeypatch):
    """It runs at the top of every launch, including from a read-only home."""
    sys.path.insert(0, str(BIN))
    import _bootstrap                                     # noqa: E402

    def refuse(*_args, **_kwargs):
        raise OSError(13, "read-only file system")

    monkeypatch.setattr(_bootstrap.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(_bootstrap.Path, "mkdir", refuse)

    _bootstrap.remember_where_i_am()          # must not raise


# ---------------------------------------------------------------------------
# D8. A hook is not the place to build a virtual environment
# ---------------------------------------------------------------------------

def test_the_hooks_never_trigger_an_install():
    """Claude Code kills a hook at 60 seconds.

    Both hooks went through the full bootstrap, which on an unprepared machine
    means creating a venv and a cold `pip install .[full]` -- Telethon
    included. That is past the timeout on Windows, so the student's first Bash
    command hung and was killed, and then so was the next one, because nothing
    about the failure was remembered.
    """
    source = (BIN / "_bootstrap.py").read_text(encoding="utf-8")
    main = source[source.index("def main("):]

    assert "HOOKS" in main, "main does not distinguish a hook from a command"

    sys.path.insert(0, str(BIN))
    import _bootstrap                                     # noqa: E402

    for module in ("aki_agent.safety_gate", "aki_agent.pending_hook",
                   "aki_agent.config_guard"):
        assert module in _bootstrap.HOOKS

    # And the hooks named here are exactly the ones plugin.json runs.
    plugin = json.loads(
        (PACKAGE_ROOT / ".claude-plugin" / "plugin.json").read_text(
            encoding="utf-8"))
    named = set()
    for entries in plugin.get("hooks", {}).values():
        for entry in entries:
            for hook in entry.get("hooks", []):
                named.update(word for word in hook.get("command", "").split()
                             if word.startswith("aki_agent."))
    assert named == set(_bootstrap.HOOKS), (
        f"plugin.json runs {named}, and the exemption list says "
        f"{set(_bootstrap.HOOKS)}")


def test_a_hook_on_an_unprepared_machine_does_nothing_quietly(tmp_path,
                                                              monkeypatch):
    """Fail open. The safety gate says so about itself in its own docstring;
    this is that promise holding one level further out."""
    sys.path.insert(0, str(BIN))
    import _bootstrap                                     # noqa: E402

    monkeypatch.setattr(_bootstrap.Path, "home", staticmethod(lambda: tmp_path))

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("a hook tried to build the environment")

    monkeypatch.setattr(_bootstrap, "ensure_venv", must_not_run)
    monkeypatch.setattr(_bootstrap, "ensure_dependencies", must_not_run)

    assert _bootstrap.main(["_bootstrap.py", "aki_agent.safety_gate"]) == 0


# ---------------------------------------------------------------------------
# D2. A dashboard that cannot start has to say so
# ---------------------------------------------------------------------------

def test_a_taken_port_is_explained_rather_than_opened(tmp_path, monkeypatch):
    """It used to open the browser on a timer BEFORE binding, so the tab
    opened whatever happened -- onto a refused connection, or onto whatever
    else owned port 4321. And `dashboard.vbs` starts it with no window, so the
    exception went somewhere nobody could read."""
    import socket

    from aki_agent import paths
    from aki_agent.dashboard import app as dashboard_app

    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()

    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]

    def must_not_open(*_args, **_kwargs):
        raise AssertionError("the browser was opened onto a port we do not own")

    try:
        import webbrowser

        monkeypatch.setattr(webbrowser, "open", must_not_open)
        with pytest.raises(SystemExit):
            dashboard_app.run(port=port, open_browser=True)
    finally:
        holder.close()

    written = paths.state_dir() / "dashboard-last-error.txt"
    said = written.read_text(encoding="utf-8")
    assert f"port {port}" in said
    assert "already using" in said


# ---------------------------------------------------------------------------
# D3. Elevation is refused, not warned about and then done anyway
# ---------------------------------------------------------------------------

def test_installing_a_task_from_an_administrator_window_is_refused(monkeypatch):
    """A task made by an administrator can only be changed by one, and the
    dashboard is not. `schtasks` cannot set a different security descriptor --
    the XML carries no DACL and the SDDL parameter exists only on the COM
    call -- so the only reliable fix is not to create it.

    Refused inside `install` rather than in the CLI, because `repair`,
    `upgrade` and the dashboard's own button never checked at all.
    """
    from aki_agent import schedule

    monkeypatch.setattr(schedule, "running_elevated", lambda: True)

    task = schedule.DEFAULT_TASKS[0]
    ok, message = schedule.install(task, schedule.runner_script(),
                                   confirmed=True)

    assert not ok
    assert "administrator" in message.lower()
    assert "Nothing has been scheduled" in message


def test_the_refusal_can_be_overridden_deliberately(monkeypatch):
    """the maintainer runs an elevated SSH session on purpose sometimes. A guard with
    no way past it gets removed rather than understood."""
    from aki_agent import schedule

    monkeypatch.setattr(schedule, "running_elevated", lambda: True)
    monkeypatch.setattr(schedule, "runner_script", lambda: Path("nope"))

    ok, message = schedule.install(schedule.DEFAULT_TASKS[0], Path("nope"),
                                   confirmed=True, allow_elevated=True)

    # It gets past the elevation check and fails on the missing runner, which
    # is the next check along -- not on being an administrator.
    assert "administrator" not in message.lower()


# ---------------------------------------------------------------------------
# D4. A synced drive that has not arrived is not an uninstalled agent
# ---------------------------------------------------------------------------

def test_a_folder_that_has_not_synced_yet_does_not_recommend_setup(
        tmp_path, monkeypatch):
    """The dangerous one.

    Google Drive, OneDrive and iCloud all mount some seconds after sign-in,
    and the login-triggered tasks fire immediately. In that window everything
    read "No configuration file yet" and doctor said to run setup -- which
    INSTALL.md names as the one act that cannot be undone.
    """
    from aki_agent import doctor, paths

    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    monkeypatch.delenv("AKI_AGENT_HOME", raising=False)

    (tmp_path / paths.POINTER_NAME).write_text(
        str(tmp_path / "G_Drive" / "Aki-Agent" / "01_Config") + "\n",
        encoding="utf-8")

    check, loaded = doctor.check_config()

    assert loaded is None
    assert not check.ok
    assert "not there right now" in check.detail
    assert "Do not run setup" in check.fix
    assert "sync" in check.fix.lower()


def test_a_machine_with_no_pointer_at_all_is_still_told_to_run_setup(
        tmp_path, monkeypatch):
    """The opposite case has to keep working, or this fix has traded one
    wrong instruction for another."""
    from aki_agent import doctor, paths

    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    monkeypatch.delenv("AKI_AGENT_HOME", raising=False)

    check, loaded = doctor.check_config()

    assert loaded is None
    assert not check.ok
    assert "/aki-agent:setup" in check.fix


# ---------------------------------------------------------------------------
# D6, D7. What the documents say, and what the launchers do
# ---------------------------------------------------------------------------

def test_the_documented_folders_are_the_ones_the_code_builds():
    """`uninstall.py` protects the real ones, so a student whose config failed
    to load had the WRONG folder protected on the strength of the README."""
    from aki_agent import scaffold

    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
    layout = readme[readme.index("Aki-Agent/"):]
    layout = layout[:layout.index("```")]

    for folder in (scaffold.CONFIG_DIR, scaffold.SANDBOX_DIR,
                   scaffold.WORK_DIR):
        assert folder in layout, f"README does not show {folder}"
    assert "02_Workspace" not in layout, "README shows a folder nothing builds"


def test_the_documents_agree_on_how_to_install_it():
    """README and INSTALL gave different commands, and both wrote the setup
    skill as a bare `/setup` -- there is no `commands/` directory, so Claude
    Code namespaces it and a bare one is an unknown command."""
    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
    install = (PACKAGE_ROOT / "INSTALL.md").read_text(encoding="utf-8")

    for text, name in ((readme, "README.md"), (install, "INSTALL.md")):
        assert "/plugin install aki-agent@aki-agent" in text, name
        assert "/aki-agent:setup" in text, name


def test_the_documented_task_count_is_the_real_one():
    """It said four. Six shipped.

    Counted against what STARTS ITSELF, since 2026-09-05. The list grew by
    three Event examples that ship switched off, and "ten ship with it" would
    have been true of the file and wrong about the machine -- somebody
    reading it would expect ten things to begin happening at setup. What the
    sentence is for is telling a person how much starts without them.
    """
    from aki_agent import schedule

    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
    words = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
             6: "Six", 7: "Seven", 8: "Eight"}
    running = len([one for one in schedule.DEFAULT_TASKS if one.enabled])

    assert f"{words[running]} ship switched on" in readme

    # And the ones that do not start themselves are still accounted for, so
    # the sentence describes the whole set rather than only the loud half.
    waiting = len(schedule.DEFAULT_TASKS) - running
    assert f"{words[waiting].lower()} more" in readme


def test_getting_out_names_the_command_that_actually_does_it():
    """CHOOSING.md said "delete the folder", which leaves six scheduled tasks
    firing at a runner that is no longer there. `uninstall.py` handles all of
    it properly and was mentioned in none of the three documents."""
    choosing = (PACKAGE_ROOT / "CHOOSING.md").read_text(encoding="utf-8")
    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")

    assert "uninstall" in choosing
    assert "uninstall" in readme
    assert "nothing to get out of" not in choosing.lower()


def test_the_windows_launchers_check_that_python_runs():
    """`where python` finds the zero-byte Microsoft Store stub, which is on
    PATH by default. It reports success on a machine with no Python, and then
    running a script opens the Store instead -- silently."""
    for name in ("check.bat", "dashboard.bat", "run-task.bat"):
        text = (BIN / name).read_text(encoding="utf-8")
        assert "where python" not in text, f"{name} trusts PATH"
        assert "_find_python.bat" in text, f"{name} does not probe"

    probe = (BIN / "_find_python.bat").read_text(encoding="utf-8")
    assert "python -c" in probe, "the probe does not actually run python"
    assert "py -3" in probe, "no fallback to the py launcher"


def test_the_batch_files_have_ordinary_line_endings():
    """They carried \\r\\r\\n -- a stray carriage return that cmd tolerates and
    every text tool reads as a blank line between every real one."""
    for path in sorted(BIN.glob("*.bat")):
        raw = path.read_bytes()
        assert b"\r\r" not in raw, f"{path.name} has doubled carriage returns"
