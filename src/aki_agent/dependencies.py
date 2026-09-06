"""External tools this package needs, and how to get them.

WHAT THIS IS FOR
----------------
A student should not have to know what Python is, let alone install it from a
website while reading a version number off a table. So the installer detects
what is missing and offers to fetch it.

THE THREE RULES, AND THEY ARE NOT NEGOTIABLE
--------------------------------------------
1. **Never install anything without asking.** Show the exact command that will
   run, wait for a yes, then run it. A tool that silently changes a person's
   machine is a tool they are right to distrust.

2. **Never elevate.** No administrator prompt, no `sudo`, no machine-wide
   install. Everything goes into the user's own account. If the only route to
   a tool needs elevation, we do not offer it -- we hand over a link and let
   the person decide, which is what an honest installer does when it has run
   out of safe options.

3. **Never claim a command works when nobody has run it.** Every install
   method below carries a `verified` flag. The ones marked False have been
   written from each tool's official documentation and NOT executed. That flag
   is printed to the user. Guessing quietly is how an installer earns a
   reputation for breaking machines.

WHY IT IS A TABLE RATHER THAN A SCRIPT
--------------------------------------
Because the answer to "what do I need?" depends on which parts of the package
the person is using. Someone who only wants the assistant needs Python and
Claude Code. Someone who wants a messaging bridge also needs Bun. Someone who
wants to install it as a plugin from a marketplace also needs git.

A script would have to encode all of that in branches. A table lets `doctor`
ask "what is missing for the things this person actually turned on?", which is
a different and much more useful question.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field as dataclass_field

from . import paths


@dataclass(frozen=True)
class InstallMethod:
    """One way to obtain a tool on one platform."""

    # What kind of thing this is, in words the user might recognise.
    kind: str                       # "winget" | "homebrew" | "script" | "manual"
    command: tuple[str, ...] = ()   # exactly what would be run
    user_scope: bool = True         # False means it would need an admin prompt
    # Has this exact command been run and observed to work?
    #
    # Set True ONLY after somebody has actually watched it succeed on a clean
    # machine. It is printed to the user, so a false True is a lie told at the
    # worst possible moment.
    verified: bool = False
    # Where to send the user if the automatic route is unavailable or refused.
    manual_url: str = ""
    manual_note: str = ""


@dataclass(frozen=True)
class Tool:
    """An external program the package can use."""

    key: str
    display_name: str
    # What breaks without it, in plain language. Shown to the user.
    why: str
    # Which parts of the package need it. "core" means everything.
    needed_by: tuple[str, ...]
    # Command names to look for on PATH, in order of preference.
    commands: tuple[str, ...]
    version_args: tuple[str, ...] = ("--version",)
    minimum_version: tuple[int, ...] | None = None
    install: dict[str, InstallMethod] = dataclass_field(default_factory=dict)

    @property
    def essential(self) -> bool:
        return "core" in self.needed_by


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------

TOOLS: tuple[Tool, ...] = (
    Tool(
        key="python",
        display_name="Python",
        why="runs the assistant's own code and the dashboard",
        # "bootstrap", not "core", on purpose.
        #
        # By the time `doctor` runs, Python is self-evidently present -- doctor
        # is written in it. Listing it as a core tool made the health report
        # say "Python version: OK" and then "Python: OK" two lines later,
        # which is noise, and noise is what people learn to skip past.
        #
        # It stays in this table because the *installer* genuinely needs to
        # reason about it when setting up a machine that has nothing.
        needed_by=("bootstrap",),
        commands=("python3", "python", "py"),
        minimum_version=(3, 10),
        install={
            "Windows": InstallMethod(
                kind="winget",
                # --scope user keeps it out of Program Files, so no admin
                # prompt appears.
                command=("winget", "install", "--id", "Python.Python.3.13",
                         "--scope", "user", "--silent",
                         "--accept-package-agreements",
                         "--accept-source-agreements"),
                user_scope=True,
                verified=False,
                manual_url="https://www.python.org/downloads/",
                manual_note=("On the first screen of the installer, tick "
                             "'Add Python to PATH'."),
            ),
            "macOS": InstallMethod(
                kind="homebrew",
                command=("brew", "install", "python@3.13"),
                user_scope=True,
                verified=False,
                manual_url="https://www.python.org/downloads/",
                manual_note=("If you do not have Homebrew, the installer from "
                             "python.org is the simpler route."),
            ),
        },
    ),
    Tool(
        key="claude",
        display_name="Claude Code",
        why="is the assistant itself -- nothing works without it",
        needed_by=("core",),
        commands=("claude",),
        install={
            # Deliberately manual on both platforms. Claude Code's install
            # route changes, and sending a student through a stale scripted
            # install is worse than sending them to the page that is always
            # current.
            "Windows": InstallMethod(
                kind="manual",
                manual_url="https://claude.com/claude-code",
                manual_note="Install it, then sign in with your Claude "
                            "account. No API key is needed.",
            ),
            "macOS": InstallMethod(
                kind="manual",
                manual_url="https://claude.com/claude-code",
                manual_note="Install it, then sign in with your Claude "
                            "account. No API key is needed.",
            ),
        },
    ),
    Tool(
        key="bun",
        display_name="Bun",
        why="runs the messaging bridge, so the assistant can reach you on "
            "your phone",
        needed_by=("messaging",),
        commands=("bun",),
        install={
            "Windows": InstallMethod(
                kind="script",
                command=("powershell", "-NoProfile", "-Command",
                         "irm bun.sh/install.ps1 | iex"),
                user_scope=True,
                verified=False,
                manual_url="https://bun.sh/docs/installation",
            ),
            "macOS": InstallMethod(
                kind="script",
                command=("/bin/bash", "-c",
                         "curl -fsSL https://bun.sh/install | bash"),
                user_scope=True,
                verified=False,
                manual_url="https://bun.sh/docs/installation",
            ),
        },
    ),
    Tool(
        key="git",
        display_name="Git",
        why="is needed to install this package as a plugin from a marketplace",
        needed_by=("plugin-install",),
        commands=("git",),
        install={
            "Windows": InstallMethod(
                kind="winget",
                command=("winget", "install", "--id", "Git.Git",
                         "--scope", "user", "--silent",
                         "--accept-package-agreements",
                         "--accept-source-agreements"),
                user_scope=True,
                verified=False,
                manual_url="https://git-scm.com/downloads",
            ),
            "macOS": InstallMethod(
                kind="manual",
                # `xcode-select --install` opens a GUI dialogue, which is not
                # something to launch behind someone's back.
                manual_url="https://git-scm.com/downloads",
                manual_note=("On a Mac, running `git --version` in Terminal "
                             "will offer to install the developer tools, "
                             "which include git."),
            ),
        },
    ),
)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

@dataclass
class ToolStatus:
    tool: Tool
    found_at: str | None = None
    version_text: str = ""
    version_tuple: tuple[int, ...] | None = None
    too_old: bool = False

    @property
    def present(self) -> bool:
        return self.found_at is not None and not self.too_old


def _parse_version(text: str) -> tuple[int, ...] | None:
    """Pull the first dotted number out of a version string.

    Tools print wildly different things -- "Python 3.13.14", "git version
    2.52.0.windows.1", "1.3.11", "2.1.233 (Claude Code)". Rather than a parser
    per tool, take the first thing that looks like a version and accept that
    it is approximate. It is only used for a minimum check.
    """
    import re

    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    if not match:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


def detect(tool: Tool) -> ToolStatus:
    """Look for one tool on this machine."""
    for command in tool.commands:
        location = shutil.which(command)
        if not location:
            continue

        version_text = ""
        try:
            result = subprocess.run(
                [location, *tool.version_args],
                capture_output=True, text=True, timeout=20, check=False,
            )
            version_text = (result.stdout or result.stderr).strip()
            version_text = version_text.splitlines()[0] if version_text else ""
        except (OSError, subprocess.SubprocessError):
            # Present but would not run. Report it as found; `doctor` will show
            # the empty version, which is itself a useful signal.
            pass

        parsed = _parse_version(version_text)
        too_old = bool(
            tool.minimum_version and parsed
            and parsed[:len(tool.minimum_version)] < tool.minimum_version
        )

        return ToolStatus(tool=tool, found_at=location,
                          version_text=version_text, version_tuple=parsed,
                          too_old=too_old)

    return ToolStatus(tool=tool)


def detect_all(features: tuple[str, ...] = ("core",)) -> list[ToolStatus]:
    """Detect the tools needed for the given features.

    `features` is what the user has actually turned on. Checking for Bun on a
    machine whose owner does not want a messaging bridge produces a warning
    they cannot act on and should ignore -- and a warning that should be
    ignored teaches people to ignore warnings.
    """
    wanted = set(features)
    return [
        detect(tool) for tool in TOOLS
        if wanted.intersection(tool.needed_by)
    ]


# ---------------------------------------------------------------------------
# Installing
# ---------------------------------------------------------------------------

def method_for(tool: Tool) -> InstallMethod | None:
    """The install method for this tool on the platform we are running on."""
    return tool.install.get(paths.platform_label())


def describe_install(tool: Tool) -> str:
    """What we would do, in words, before asking whether to do it.

    This is what the user reads before saying yes, so it has to be complete
    and it has to be honest about what has not been tested.
    """
    method = method_for(tool)
    if method is None:
        return (f"{tool.display_name} is not installed, and there is no "
                f"automatic route for it on {paths.platform_label()}.")

    lines = [f"{tool.display_name} -- {tool.why}."]

    if method.kind == "manual" or not method.command:
        lines.append(f"Install it yourself from: {method.manual_url}")
        if method.manual_note:
            lines.append(method.manual_note)
        return "\n".join(lines)

    lines.append("This exact command would run:")
    lines.append("    " + " ".join(method.command))
    lines.append("It installs into your user account only -- no administrator "
                 "password is needed.")

    if not method.verified:
        lines.append(
            "NOTE: this command comes from the tool's own documentation, but "
            "nobody has run it on a clean machine yet. If it does not work, "
            f"install it yourself from {method.manual_url} and tell whoever "
            "gave you this package."
        )
    if method.manual_note:
        lines.append(method.manual_note)

    return "\n".join(lines)


def install(tool: Tool, confirmed: bool) -> tuple[bool, str]:
    """Run the install, but only if the caller has actually asked the user.

    `confirmed` is not a formality. The caller must have shown the user
    `describe_install()` and received a yes. Passing True without doing that
    is the bug this parameter exists to make visible in review.
    """
    if not confirmed:
        return False, ("Not installed: nobody confirmed it. Show the user "
                       "what would run and ask first.")

    method = method_for(tool)
    if method is None or not method.command:
        return False, (f"There is no automatic install for "
                       f"{tool.display_name} on {paths.platform_label()}. "
                       f"See {method.manual_url if method else ''}")

    if not method.user_scope:
        # Refusing here rather than prompting for elevation is deliberate.
        return False, (f"Installing {tool.display_name} this way would need "
                       "an administrator password, so it is not offered. "
                       f"Install it yourself from {method.manual_url}")

    try:
        result = subprocess.run(list(method.command), capture_output=True,
                                text=True, timeout=900, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"The install command would not start: {exc}"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        tail = "\n".join(detail.splitlines()[-6:])
        return False, (f"The install did not finish.\n{tail}\n\n"
                       f"You can install it yourself from {method.manual_url}")

    # Do not trust the exit code alone -- confirm the tool is now findable.
    # INHERITED RULE: never report a step as done that has not been verified
    # against something that cannot be faked.
    fresh = detect(tool)
    if not fresh.present:
        return False, (f"The install reported success, but {tool.display_name} "
                       "still cannot be found. You may need to close this "
                       "window and open a new one so it picks up the change.")

    return True, f"{tool.display_name} is installed ({fresh.version_text})."
