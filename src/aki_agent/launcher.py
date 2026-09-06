"""Generating the user's own launcher — the thing they double-click.

WHY GENERATE IT RATHER THAN SHIP IT
-----------------------------------
The launcher has to know where this person's work lives, which folder to open
in, and what they want running. That is per-user, so it is written at setup
from their configuration rather than shipped as a fixed file.

WHAT THE LAUNCHER DOES
----------------------
Opens Claude Code, in the user's workspace, in a mode that does not stop to
ask permission for every small thing, with their assistant persona loaded.

The launcher passes `--channels aki-channel`, naming the package's own MCP
server. That is the inbound half: it registers the session to receive pushed
messages, and what it receives is whatever was typed into the dashboard.

`--channels` is a hidden flag -- real, present in the binary, absent from
`--help`. This file once claimed it did not exist on the strength of that
absence, and omitting it produced exactly the failure a user reported: the
launcher opened an ordinary session, replies still went out, and nothing sent
TO the assistant ever arrived.

**It used to name the Telegram plugin, and that was a bug of its own**
(reported 2026-09-01). He turned Telegram off and kept receiving messages,
because this file wrote it back on every upgrade. A generated file that
regenerates its own removal is worse than one that is merely wrong: turning
the thing off appears to work, and then quietly undoes itself.

ABOUT "AUTO MODE"
-----------------
`--permission-mode auto` is real and verified. It is the difference between an
assistant that works and one that interrupts constantly.

It is offered, explained, and **not** the default in the generated launcher
unless the user chooses it, because it genuinely does mean the assistant acts
without asking each time. `--dangerously-skip-permissions` is never generated
at all: it removes the checks entirely, and no personal assistant on somebody's
own machine needs that.

ABOUT LOCAL MODELS
------------------
This module DOES write a launcher that starts a local model: `backend_block()`
emits the three environment variables and `backend.arguments()` adds the
`--model`, so a person who set Claude Code up against Ollama gets an assistant
that starts the same way they did, and scheduled tasks that do too.

**This paragraph used to say the opposite** -- "Ollama is not among them,
verified in `claude --help`" -- and it stayed here for a fortnight after
`backend.py` made it untrue, while `skills/setup/SKILL.md` went on telling
people in an interview that the honest answer was no. Three places, two
answers, and the one a new user actually met was the wrong one.

The original observation was true and its conclusion was not: `--help` lists
the first-party providers and says nothing about `ANTHROPIC_BASE_URL`, which
is what points the client elsewhere. Corrected 2026-09-05. `local_model_note()`
explains the trade-offs and lists what the endpoint is holding.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import atomic, paths

# The MCP server's name, as written in `.mcp.json`.
CHANNEL_NAME = "aki-channel"

# This package's own plugin, and the channel reference naming it.
#
# The channel server ships INSIDE the plugin (a `.mcp.json` at the plugin
# root, the shape the official Telegram plugin uses) rather than in the
# assistant's own folder. That is not tidiness. A `server:` reference can
# only be enabled with `--dangerously-load-development-channels`, which
# shows a confirmation dialog at every start -- fatal for an assistant
# meant to run scheduled work unattended. A `plugin:` reference can be
# approved once, in managed settings, and then simply works.
OWN_PLUGIN_ID = "aki-agent@aki-agent"
OWN_CHANNEL = f"plugin:{OWN_PLUGIN_ID}"

# What `--channels` is given, which is NOT the same string, and the flag that
# has to accompany it. Four walls on 2026-09-01, every one of them invisible
# until the real machine said so:
#
#   1. `aki-channel`                 -> "entries must be tagged", exit 1
#      before anything renders, so the launcher window vanished and every
#      clone died as it started.
#   2. `server:aki-channel`          -> accepted, then "server: entries need
#      --dangerously-load-development-channels".
#   3. `plugin:aki-agent@aki-agent`  -> "not on the approved channels
#      allowlist". That list is Anthropic's; a locally built plugin cannot be
#      on it, so the plugin route is closed to anything but official channels.
#   4. and the declaration has to actually be installed -- see engine.COPIED.
#
# So this is the only route that exists for a channel somebody wrote
# themselves, and the flag is required rather than chosen.
#
#   5. and it is NOT a switch that accompanies `--channels`. It takes the
#      server list itself: `--dangerously-load-development-channels <servers>`,
#      used INSTEAD of `--channels`. Passing both got "argument missing",
#      which is the fifth distinct error message from the same two words.
#
# WHAT THE FLAG MEANS, PLAINLY: it lets channel notifications from MCP servers
# in this install's own config reach the session unprompted. That is exactly
# what a chat panel needs and exactly what Claude Code is right to gate -- an
# MCP server that can inject into a session is a real widening. Here the
# `.mcp.json` is the user's own, on their own machine, written by this package.
# It is still worth saying out loud rather than burying in a launcher nobody
# reads, and it is the reason this comment is longer than the code.
CHANNEL_REF = f"server:{CHANNEL_NAME}"
DEVELOPMENT_CHANNELS_FLAG = "--dangerously-load-development-channels"

# The whole argument, as it goes on a command line. One constant, because the
# order and the pairing are exactly what took five tries to get right.
CHANNEL_ARGUMENTS = (DEVELOPMENT_CHANNELS_FLAG, CHANNEL_REF)


# THE PACKAGE'S OWN CHANNEL IS NOT NAMED HERE ANY MORE (2026-09-04)
# ------------------------------------------------------------------
# It existed to carry the dashboard's chat box into the session. The maintainer removed
# that panel -- so there is
# nothing left for it to carry, and a channel with no sender is a server
# started in every session for no reason.
#
# `channel_server.py` stays: clones still use it, and the capability it was
# missing until 0.41.9 is now declared, so it works if it is ever named again.
# What was removed with the panel was the WAY IN, not the mechanism.
#
# For anyone picking this up later, the three doors Claude Code offers and
# what each costs: an approved `plugin:` reference (Anthropic's list, which a
# locally built plugin is never on); `--dangerously-load-development-channels`
# (works, and shows a confirmation dialog at EVERY start); and
# `allowedChannelPlugins` in machine policy (works, needs administrator once,
# and REPLACES Anthropic's default list -- so anything already relied on has
# to be listed again or it stops). `--managed-settings` is validated but does
# not move that allowlist: a parent process cannot approve itself.


@dataclass
class LauncherOptions:
    """What the user chose."""

    workspace: Path | None = None
    assistant_agent: str = ""        # the persona to load, if any
    auto_mode: bool = False          # --permission-mode auto
    open_dashboard: bool = False     # start the dashboard alongside
    title: str = "Assistant"
    check_channel: bool = True       # verify the messaging channel at launch
    # Kept for the launchers already on disk that were written with it, and
    # for anyone who deliberately points at a different server. Empty means
    # "the package's own", which is what everybody wants and what
    # `channel_block` writes.
    channel_server: str = ""


def _preflight_block(package_root: Path, windows: bool) -> str:
    """The check that runs before Claude Code starts.

    WHY A LAUNCHER SHOULD CHECK RATHER THAN ASSUME
    ----------------------------------------------
    The proven reference launcher rewrites its messaging credentials into
    place on every single start, unconditionally. That looked like belt and
    braces until you ask what the alternative failure looks like: the file is
    written once during setup, something later moves, clears or half-writes
    it, and from then on the launcher starts perfectly happily with no channel
    at all. Nothing errors. The user double-clicks, sees their assistant open,
    and simply never receives a message again.

    This package cannot rewrite the token — it is the user's own, held in the
    messaging plugin's file, and copying it into a second place is how two
    copies drift apart. So it does the next best thing and *checks*, out loud,
    before the session opens. A warning the user reads at launch is worth more
    than a silent absence they discover a week later.
    """
    if windows:
        return (
            "\r\n"
            "REM Say something if the messaging channel is not connected --\r\n"
            "REM silence here is indistinguishable from working.\r\n"
            f'python "{package_root}\\bin\\_bootstrap.py" '
            "aki_agent.cli channel-check\r\n"
        )
    return (
        "\n# Say something if the messaging channel is not connected --\n"
        "# silence here is indistinguishable from working.\n"
        f'python "{package_root}/bin/_bootstrap.py" '
        "aki_agent.cli channel-check\n"
    )


def launcher_path(name: str = "start-assistant") -> Path:
    """Where the generated launcher goes.

    Into the user's own folder, not into the package. The package may sit on a
    synced drive or be replaced by an update; their launcher should survive
    both.
    """
    suffix = ".bat" if paths.is_windows() else ".command"
    return paths.app_dir() / f"{name}{suffix}"


def choices_in(text: str) -> dict:
    """Which options a launcher we generated was built with.

    Read back out of the file rather than asked for again, because the
    person answered these at setup and the only reason to be regenerating
    the launcher is that the engine moved. Losing `auto_mode` here would
    be the quiet kind of regression: everything still starts, and the
    assistant simply stops doing anything unattended.

    THIS HAD NO CALLERS UNTIL 2026-08-23, AND THAT COST SOMETHING
    -------------------------------------------------------------
    `cli.cmd_repair` did the same read-back inline, and its copy recovered
    two of the three: `--agent` was simply not in it. So repairing an
    install — which is what somebody runs when something is already wrong —
    rewrote the launcher without the persona, and from then on the assistant
    started as a plain Claude Code session. Nothing errored. It just was not
    itself any more, and the repair reported success.

    Which is the argument for this function existing at all: one read-back,
    in one place, that gains a line when a field is added. The inline copy
    could not gain that line, because nobody knew it was there.
    """
    return {
        "auto_mode": "--permission-mode" in text,
        # By stem, not extension: the Windows launcher moved from
        # dashboard.bat to dashboard.vbs, and matching the extension
        # quietly started answering False.
        "open_dashboard": "dashboard." in text,
        "assistant_agent": _agent_in(text),
    }


def _agent_in(text: str) -> str:
    """The persona a generated launcher passes to `--agent`, or "".

    Matched against what `claude_arguments` writes, which is the flag and the
    name separated by a space. Quoting is tolerated because the shell
    templates differ between platforms and a name with a space in it is a
    thing somebody will eventually have.
    """
    import re

    found = re.search(r'--agent\s+["\']?([^"\'\s\r\n]+)', text)
    return found.group(1) if found else ""


def claude_arguments(options: LauncherOptions) -> list[str]:
    """The arguments passed to `claude`. Pure, so it can be tested."""
    arguments: list[str] = []

    # `--channels` is NOT here. It takes a list, so it has to come first on
    # the command line, and whether it applies is decided when the launcher
    # runs rather than when it is written -- see `channel_block()`.

    if options.auto_mode:
        arguments += ["--permission-mode", "auto"]

    if options.assistant_agent:
        arguments += ["--agent", options.assistant_agent]

    return arguments


def channel_block(windows: bool, assistant_name: str = "") -> str:
    """Shell that sets the `--channels` flag if the plugin is installed now.

    Read out of Claude Code's own registry rather than remembered from setup,
    because the answer changes after setup and nothing regenerates the file.
    A launcher written before the plugin existed starts working the moment the
    plugin is installed, with no repair step and nothing to notice.

    BACK TO TELEGRAM, 2026-09-01 EVENING -- AND NOT BECAUSE OF A BUG
    ---------------------------------------------------------------
    An evening went into replacing this with the package's own channel. The
    replacement works and cannot be automated. Claude Code allows two kinds of
    inbound channel and no third:

      * `plugin:<name>@<marketplace>` -- and the plugin must be on Anthropic's
        approved list. A locally built one never will be.
      * `--dangerously-load-development-channels` -- which works, and stops on
        an interactive "I am using this for local development" prompt EVERY
        time a session starts.

    A keypress at every start is fatal for this package in particular: the
    assistant is meant to run scheduled work unattended, and to be installed by
    students. An agent that cannot start without somebody at the keyboard is
    not one.

    That gate is deliberate on Claude Code's part -- a server able to inject
    into a session unprompted is worth refusing -- so the honest answer is to
    use the approved channel rather than to route around the refusal.

    **The clone design survives this**, which is the part worth knowing. Only
    the MAIN agent needs a channel. Clones are reached by the main agent over
    cross-session messaging, which needs no flag and no approval, and they
    report back the same way -- which is the merge the maintainer chose in 3a anyway.
    """
    from . import telegram_setup
    from .telegram_setup import CHANNEL_SERVER, PLUGIN_ID

    # Keep this assistant's Telegram state in its OWN folder.
    #
    # The plugin defaults to ~/.claude/channels/telegram, which is shared.
    # On a machine already running another Claude Code assistant that
    # folder is occupied, and starting here takes over its bot.pid and
    # speaks through its bot. Written by the generator rather than added
    # by hand, so that running setup again cannot quietly drop it.
    folder = telegram_setup.channel_name(assistant_name)

    if windows:
        return (
            "REM Keep this assistant\'s Telegram state in its own folder,\r\n"
            "REM so it cannot take over another assistant\'s bot here.\r\n"
            "set TELEGRAM_STATE_DIR=%USERPROFILE%\\.claude\\channels\\"
            f"{folder}\r\n"
            "\r\n"

            "REM Inbound messages need this flag, and whether it applies\r\n"
            "REM can change after setup -- so it is decided here, every\r\n"
            "REM start.\r\n"
            "set AKI_CHANNELS=\r\n"
            f'findstr /C:"{PLUGIN_ID}" '
            '"%USERPROFILE%\\.claude\\plugins\\installed_plugins.json" '
            ">nul 2>&1\r\n"
            "if not errorlevel 1 set "
            f"AKI_CHANNELS=--channels {CHANNEL_SERVER}\r\n"
            "\r\n"
        )
    return (
        "# Keep this assistant\'s Telegram state in its own folder, so it\n"
        "# cannot take over another assistant\'s bot on this machine.\n"
        f'export TELEGRAM_STATE_DIR=\"$HOME/.claude/channels/{folder}\"\n'
        "\n"
        "# Inbound messages need this flag, and whether it applies can change\n"
        "# after setup -- so it is decided here, every start.\n"
        'AKI_CHANNELS=""\n'
        f'if grep -q "{PLUGIN_ID}" '
        '"$HOME/.claude/plugins/installed_plugins.json" 2>/dev/null; then\n'
        f'  AKI_CHANNELS="--channels {CHANNEL_SERVER}"\n'
        "fi\n"
        "\n"
    )


def backend_block(windows: bool) -> str:
    """Point this launcher at the same brain the install was set up against.

    Empty for an ordinary install, which is the normal case and stays exactly
    as it was. For somebody running Ollama it is the three lines their own
    terminal had and this window would not: without them the launcher starts a
    Claude Code that talks to a service they are not signed in to, and the
    error names none of this.
    """
    from . import backend as backend_module

    brain = backend_module.stored()
    settings = brain.environment()
    if not settings:
        return ""

    break_ = "\r\n" if windows else "\n"
    lines = [("REM " if windows else "# ") + brain.sentence() + break_]
    for name, value in settings.items():
        if windows:
            lines.append(f"set {name}={value}{break_}")
        else:
            lines.append(f'export {name}="{value}"{break_}')
    lines.append(break_)
    return "".join(lines)


def _stop_note() -> str:
    """Where `recycle` leaves word that a stop was on purpose."""
    from . import recycle

    return str(recycle.deliberate_stop_file())


def windows_launcher(options: LauncherOptions,
                     package_root: Path) -> str:
    """The .bat a Windows user double-clicks."""
    from . import backend as backend_module

    workspace = str(options.workspace) if options.workspace else "%USERPROFILE%"
    # The model is chosen on the command line, never in the environment, so it
    # has to be written in beside the variables or the launcher reaches the
    # right endpoint and asks it for the wrong model.
    arguments = " ".join(claude_arguments(options)
                         + backend_module.stored().arguments())
    stop_note = _stop_note()
    preflight = (_preflight_block(package_root, windows=True)
                 if options.check_channel else "")

    dashboard_block = ""
    if options.open_dashboard:
        # The absolute path, not a walk up from the launcher. The launcher
        # lives in the user's own folder and the package may be anywhere --
        # `%~dp0..\..\<name>` resolved to C:\Users\<package name>\bin, which
        # exists on no machine. It opened nothing, silently, which is the same
        # failure this package keeps finding in itself.
        dashboard_block = (
            "\r\n"
            "REM Start the dashboard in its own window, then carry on.\r\n"
            # Through the hidden-window wrapper rather than `/min`: a
            # minimised console is still a console on the taskbar, and it
            # steals focus on the way there. The only terminal a person
            # should see is their assistant's own.
            f'start "" wscript.exe //B //Nologo '
            f'""{package_root}\\bin\\dashboard.vbs""\r\n'
        )

    return (
        "@echo off\r\n"
        "REM ------------------------------------------------------------\r\n"
        f"REM  Start {options.title}\r\n"
        "REM\r\n"
        "REM  This file was written for you during setup. It is yours --\r\n"
        "REM  edit it freely. Running setup again will offer to rewrite it.\r\n"
        "REM ------------------------------------------------------------\r\n"
        "\r\n"
        # Double-clicking a .bat gets the old console host, which is where
        # non-Latin text still breaks, the window cannot be resized sensibly
        # and scrollback is tiny. Windows Terminal is what a person actually
        # wants an interactive assistant to live in (reported 2026-08-19).
        #
        # Re-launched, not merely preferred: the file has already been started
        # by the time it can ask, so it starts itself again inside Terminal
        # and lets the first copy exit. `WT_SESSION` is set by Terminal
        # itself, so the second copy falls straight through to the real work
        # and this cannot loop. A machine without `wt` -- Windows 10 without
        # the Store app -- simply carries on in the console it already has,
        # which is exactly the old behaviour.
        "if defined WT_SESSION goto run\r\n"
        "if defined AKI_NO_WT goto run\r\n"
        "where wt >nul 2>&1\r\n"
        "if errorlevel 1 goto run\r\n"
        # No `-p <profile>`: profile names are localised, and naming one that
        # does not exist on this machine makes Terminal open on an error
        # instead of the assistant. The default profile is whatever they
        # already chose.
        'start "" wt cmd /c ""%~f0""\r\n'
        "exit /b 0\r\n"
        "\r\n"
        ":run\r\n"
        # Defined up front so the tidy-exit test below cannot read an empty
        # value and report a failure on the path that never ran a session.
        "set AKI_RC=0\r\n"
        "REM Show non-Latin characters properly.\r\n"
        "chcp 65001 >nul 2>&1\r\n"
        "\r\n"
        "where claude >nul 2>&1\r\n"
        "if errorlevel 1 goto noclaude\r\n"
        "\r\n"
        f'cd /d "{workspace}"\r\n'
        f"{preflight}"
        f"{dashboard_block}"
        "\r\n"
        f"{backend_block(windows=True)}"
        f"{channel_block(windows=True, assistant_name=options.title)}"
        # CALL is load-bearing. On Windows `claude` on PATH is a .cmd shim, and
        # one batch file invoking another WITHOUT `call` transfers control and
        # never comes back -- so everything after this line, including the tidy
        # exit, is dead code. Proved on the reference system, where every
        # restart left a dead terminal window on screen for weeks.
        f"call claude %AKI_CHANNELS% {arguments}\r\n"
        "set AKI_RC=%ERRORLEVEL%\r\n"
        "goto done\r\n"
        "\r\n"
        ":noclaude\r\n"
        "echo.\r\n"
        "echo   Claude Code is not installed, or Windows cannot find it.\r\n"
        "echo.\r\n"
        "echo   Get it from https://claude.com/claude-code\r\n"
        "echo   then sign in with your Claude account.\r\n"
        "echo.\r\n"
        "pause\r\n"
        "\r\n"
        ":done\r\n"
        # Exit 0 deliberately, whatever the session exited with. A terminal
        # keeps a dead pane on screen when its process ends badly and closes it
        # when the process ends cleanly, and a recycled session ends by being
        # stopped -- so without this line every restart leaves an old window
        # sitting there looking like a running assistant.
        #
        # BUT a silent exit 0 also hides a session that never started. That
        # happened within hours of adding this line: Claude Code's own updater
        # left no `claude.exe` behind, the launcher failed instantly, and the
        # window vanished so fast the owner saw only the dashboard come up and
        # no assistant (2026-09-04). A failure has to be visible; it just must
        # not become another window that stays for ever. So: say what
        # happened, hold long enough to read it, then still leave cleanly.
        # A REPLACED SESSION IS NOT A FAILED ONE (reported 2026-09-04)
        # ----------------------------------------------------------
        #
        #
        # He was watching two of this package's own timers fight. A recycled
        # session always exits non-zero -- it was stopped on purpose -- so it
        # always took the branch below, was always still inside that
        # thirty-second pause when `_terminate` ran out of patience at eight
        # seconds, and was always killed. A killed process is precisely what
        # makes Windows Terminal keep the pane, so every restart left one.
        #
        # `recycle.say_this_was_deliberate()` writes this file just before it
        # stops the session. Reading it here is what turns "explain for thirty
        # seconds" back into "close".
        f"if exist \"{stop_note}\" (\r\n"
        f"  del \"{stop_note}\" >nul 2>&1\r\n"
        "  exit /b 0\r\n"
        ")\r\n"
        "if not \"%AKI_RC%\"==\"0\" (\r\n"
        "  echo.\r\n"
        "  echo   The session ended with code %AKI_RC%.\r\n"
        "  echo   If it never started at all, Claude Code may be missing,\r\n"
        "  echo   mid-update, or signed out -- try running: claude --version\r\n"
        "  echo.\r\n"
        "  echo   This window closes in 30 seconds.\r\n"
        "  timeout /t 30 >nul 2>&1\r\n"
        ")\r\n"
        "exit /b 0\r\n"
    )


def macos_launcher(options: LauncherOptions, package_root: Path) -> str:
    """The .command a macOS user double-clicks."""
    workspace = str(options.workspace) if options.workspace else "$HOME"
    stop_note = _stop_note()
    from . import backend as backend_module

    arguments = " ".join(claude_arguments(options)
                         + backend_module.stored().arguments())
    preflight = (_preflight_block(package_root, windows=False)
                 if options.check_channel else "")

    dashboard_block = ""
    if options.open_dashboard:
        dashboard_block = (
            "\n# Start the dashboard in the background, then carry on.\n"
            f'"{package_root}/bin/dashboard.command" &\n'
        )

    return (
        "#!/bin/bash\n"
        "# ------------------------------------------------------------\n"
        f"#  Start {options.title}\n"
        "#\n"
        "#  This file was written for you during setup. It is yours --\n"
        "#  edit it freely. Running setup again will offer to rewrite it.\n"
        "#\n"
        "#  If macOS refuses to open it, right-click and choose Open. That\n"
        "#  is Gatekeeper asking once about a file it did not download.\n"
        "# ------------------------------------------------------------\n"
        "\n"
        "if ! command -v claude >/dev/null 2>&1; then\n"
        "  echo\n"
        "  echo \"  Claude Code is not installed.\"\n"
        "  echo\n"
        "  echo \"  Get it from https://claude.com/claude-code\"\n"
        "  echo \"  then sign in with your Claude account.\"\n"
        "  echo\n"
        "  read -r -p \"  Press return to close. \"\n"
        "  exit 1\n"
        "fi\n"
        "\n"
        f'cd "{workspace}" || exit 1\n'
        f"{preflight}"
        f"{dashboard_block}"
        "\n"
        f"{backend_block(windows=False)}"
        f"{channel_block(windows=False, assistant_name=options.title)}"
        f"claude $AKI_CHANNELS {arguments}\n"
        "AKI_RC=$?\n"
        "\n"
        # THE SAME TAIL AS WINDOWS, FOR THE SAME TWO REASONS
        # ---------------------------------------------------
        # said after a Windows-only fix, and this file was the clearest case
        # of it: the whole of tonight's work on what happens when a session
        # ends had been written into the .bat and nowhere else.
        #
        # `recycle.say_this_was_deliberate()` leaves this note before it stops
        # a session. Without reading it, a replaced session on a Mac would sit
        # here explaining a "failure" that was a restart -- and Terminal.app
        # keeps a window whose shell exited non-zero, which is the same corpse
        # window, on the other platform.
        f'if [ -f "{stop_note}" ]; then\n'
        f'  rm -f "{stop_note}"\n'
        "  exit 0\n"
        "fi\n"
        "\n"
        # A real failure still has to be visible. Terminal.app closes a window
        # on a clean exit when "close if the shell exited cleanly" is set, and
        # keeps it otherwise -- so this says what happened, holds long enough
        # to be read, and then leaves cleanly either way.
        "if [ \"$AKI_RC\" -ne 0 ]; then\n"
        "  echo\n"
        "  echo \"  The session ended with code $AKI_RC.\"\n"
        "  echo \"  If it never started at all, Claude Code may be missing,\"\n"
        "  echo \"  mid-update, or signed out -- try running: claude --version\"\n"
        "  echo\n"
        "  echo \"  This window closes in 30 seconds.\"\n"
        "  sleep 30\n"
        "fi\n"
        "exit 0\n"
    )


def write_launcher(options: LauncherOptions, package_root: Path,
                   confirmed: bool) -> tuple[bool, str]:
    """Write the launcher into the user's folder.

    Refuses without confirmation, like everything else that changes a person's
    machine.
    """
    if not confirmed:
        return False, "Not written: nobody confirmed it."

    path = launcher_path()
    text = (windows_launcher(options, package_root) if paths.is_windows()
            else macos_launcher(options, package_root))

    paths.ensure_app_dirs()
    atomic.write_text(path, text)

    if not paths.is_windows():
        # Without the executable bit, a double-click on macOS opens it in a
        # text editor, which looks exactly like "the file is broken".
        try:
            path.chmod(0o755)
        except OSError:
            return True, (f"Written to {path}, but I could not mark it as "
                          "runnable. In Terminal, run:  chmod +x "
                          f'"{path}"')

    return True, f"Written to {path}. Double-click it to start."


def describe(options: LauncherOptions) -> str:
    """What the launcher will do, for the user to approve first."""
    lines = ["The launcher will:", ""]
    lines.append(f"  - open your work folder: "
                 f"{options.workspace or 'your home folder'}")
    lines.append("  - start Claude Code, signed in as you")

    if options.auto_mode:
        lines.append("  - run in AUTO mode: it will get on with things "
                     "rather than asking permission for each step")
    else:
        lines.append("  - ask before doing things, as normal")

    if options.assistant_agent:
        lines.append(f"  - load your assistant, {options.assistant_agent}")
    if options.open_dashboard:
        lines.append("  - open the dashboard alongside")

    # Stated either way. "Can it be messaged" is the question people actually
    # have about a launcher, and a silent no reads exactly like a yes.
    if options.channel_server:
        lines.append("  - connect your messaging channel, so messages sent TO "
                     "your assistant reach this session")
    else:
        lines.append("  - NOT receive messages: nothing is connected, so it "
                     "can only be talked to in the window it opens")

    lines.append("")
    lines.append("It never runs as an administrator, and it never bypasses "
                 "permission checks entirely.")

    if options.auto_mode:
        # THE ONE MOMENT SOMEBODY IS LOOKING (2026-09-05)
        # -----------------------------------------------
        # `safety_gate.describe()` has always existed for "the user to read
        # once and trust afterwards", and nothing ever called it at a moment
        # a user was reading. So the floor under auto mode was real and
        # unadvertised, and the sentence above -- "never bypasses permission
        # checks entirely" -- was asking to be taken on faith.
        #
        # Turning auto mode on is the moment: it is the one screen where
        # somebody decides how much to let this thing do unattended. Nothing
        # here changes what the gate refuses. It just stops being a secret
        # from the person the gate is for.
        from . import safety_gate

        lines.append("")
        lines.append("Even in AUTO mode, these are refused outright:")
        lines.append("")
        for line in safety_gate.describe().splitlines():
            stripped = line.strip()
            if stripped.startswith("-"):
                lines.append(f"  {stripped}")

    return "\n".join(lines)


def local_model_note() -> str:
    """How to run this against a local model, and what to expect from it."""
    return (
        "You can run this against a local model. Ollama documents it, and no "
        "proxy is involved -- Ollama serves the shape Claude Code expects.\n"
        "\n"
        "Set it up in your own terminal first, the way Ollama describes:\n"
        "\n"
        "    set ANTHROPIC_AUTH_TOKEN=ollama\n"
        "    set ANTHROPIC_API_KEY=\n"
        "    set ANTHROPIC_BASE_URL=http://localhost:11434\n"
        "    claude --model <your model>\n"
        "\n"
        "Then, from inside that session, write the launcher. It records what "
        "that session is using and starts the same thing every time -- the "
        "endpoint AND the model, because the model is a command-line argument "
        "and would otherwise be lost. Your scheduled work uses it too.\n"
        "\n"
        "Two things to expect, said plainly rather than discovered: scheduled "
        "work is slower on a local model, and multi-step tool use is where "
        "small models are weakest -- a task may run, finish, and have done "
        "less than it would have. That is the model, not a fault here.\n"
        "\n"
        "Nothing in this package has been tested end to end against Ollama. "
        "The plumbing is reproduced faithfully; how well a given model drives "
        "it is a question only running it for a week answers."
    )
