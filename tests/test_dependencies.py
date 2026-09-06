"""The external-tool table, and the promises it makes to the user.

Most of these tests are not about whether the code works. They are about
whether the code is honest, because this is the part of the package that
changes somebody else's machine.
"""

from __future__ import annotations

import pytest

from aki_agent import dependencies, paths

PLATFORMS = ("Windows", "macOS")


# ---------------------------------------------------------------------------
# The table itself
# ---------------------------------------------------------------------------

def test_every_tool_is_described_in_plain_language():
    """`why` is printed to a non-developer, so it has to read as a sentence."""
    for tool in dependencies.TOOLS:
        assert tool.why, f"{tool.key} has no explanation"
        assert tool.why[0].islower(), (
            f"{tool.key}: `why` is appended after the tool name, so it should "
            "continue the sentence rather than start a new one"
        )
        assert tool.needed_by, f"{tool.key} is needed by nothing -- remove it"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_every_tool_has_a_route_on_both_platforms(platform):
    """macOS is not a later port.

    A tool with a Windows install route and no macOS one would leave a Mac
    student stuck with no instruction at all -- not even a link.
    """
    for tool in dependencies.TOOLS:
        assert platform in tool.install, (
            f"{tool.key} has no install route for {platform}"
        )


def test_no_install_method_needs_an_administrator_password():
    """Everything installs into user scope. No elevation, ever.

    If a route genuinely needs elevation, the correct answer is to mark it
    user_scope=False, which makes `install()` refuse it and hand the user a
    link instead. This test is here so that flag cannot be set casually.
    """
    for tool in dependencies.TOOLS:
        for platform, method in tool.install.items():
            if method.command:
                assert method.user_scope, (
                    f"{tool.key} on {platform} would need elevation. Offer a "
                    "manual link instead of prompting for an admin password."
                )


def test_manual_methods_always_carry_a_link():
    """A 'do it yourself' with no URL is not an instruction."""
    for tool in dependencies.TOOLS:
        for platform, method in tool.install.items():
            if method.kind == "manual" or not method.command:
                assert method.manual_url, (
                    f"{tool.key} on {platform} has no automatic route and no "
                    "link -- the user would be told nothing useful"
                )


def test_automatic_methods_also_carry_a_fallback_link():
    """Automatic installs fail. The user must always have somewhere to go."""
    for tool in dependencies.TOOLS:
        for platform, method in tool.install.items():
            if method.command:
                assert method.manual_url, (
                    f"{tool.key} on {platform} has an automatic install but "
                    "no fallback link for when it fails"
                )


# ---------------------------------------------------------------------------
# Honesty about what has been tested
# ---------------------------------------------------------------------------

def test_unverified_commands_say_so_to_the_user():
    """An unverified install command must announce itself when offered.

    None of the install commands in this package have been run on a clean
    machine yet. That is an acceptable state to ship in; pretending otherwise
    is not.
    """
    for tool in dependencies.TOOLS:
        method = tool.install.get(paths.platform_label())
        if method is None or not method.command or method.verified:
            continue
        description = dependencies.describe_install(tool)
        assert "nobody has run it" in description, (
            f"{tool.key}: the install offer does not tell the user the "
            "command is untested"
        )


def test_describe_install_always_shows_the_exact_command():
    """The user approves a command, so they must be shown that command."""
    for tool in dependencies.TOOLS:
        method = tool.install.get(paths.platform_label())
        if method is None or not method.command:
            continue
        description = dependencies.describe_install(tool)
        assert " ".join(method.command) in description


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------

def test_install_refuses_without_confirmation():
    """The consent flag is load-bearing, not decorative."""
    tool = dependencies.TOOLS[0]
    ok, message = dependencies.install(tool, confirmed=False)
    assert ok is False
    assert "confirmed" in message.lower()


def test_install_refuses_a_method_that_would_need_elevation(monkeypatch):
    """Even if a future method sets user_scope=False, install() must decline."""
    tool = dependencies.TOOLS[0]
    elevated = dependencies.InstallMethod(
        kind="winget", command=("some", "command"), user_scope=False,
        manual_url="https://example.invalid/install",
    )
    monkeypatch.setattr(dependencies, "method_for", lambda _tool: elevated)

    ok, message = dependencies.install(tool, confirmed=True)
    assert ok is False
    assert "administrator" in message.lower()


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def test_detection_returns_a_status_for_every_tool():
    for tool in dependencies.TOOLS:
        status = dependencies.detect(tool)
        assert status.tool is tool
        # Either found with a location, or not found -- never half-way.
        assert (status.found_at is None) or bool(status.found_at)


def test_detect_all_only_looks_at_the_features_in_use():
    """Checking for tools the user does not need produces warnings they should
    ignore, and warnings that should be ignored teach people to ignore
    warnings."""
    core_only = dependencies.detect_all(("core",))
    keys = {status.tool.key for status in core_only}
    assert "bun" not in keys, (
        "Bun is only needed for messaging and should not be checked for "
        "someone who has not enabled it"
    )

    with_messaging = dependencies.detect_all(("core", "messaging"))
    assert "bun" in {status.tool.key for status in with_messaging}


def test_version_parsing_handles_the_real_formats():
    """Each of these is a real string one of these tools actually prints."""
    parse = dependencies._parse_version
    assert parse("Python 3.13.14") == (3, 13, 14)
    assert parse("git version 2.52.0.windows.1") == (2, 52, 0)
    assert parse("1.3.11") == (1, 3, 11)
    assert parse("2.1.233 (Claude Code)") == (2, 1, 233)
    assert parse("no numbers here") is None


def test_python_is_not_double_reported_in_the_health_check():
    """`doctor` is written in Python, so reporting it as a missing tool would
    be absurd -- and it briefly did, printing 'Python version: OK' and
    'Python: OK' two lines apart."""
    python_tool = next(tool for tool in dependencies.TOOLS
                       if tool.key == "python")
    assert "core" not in python_tool.needed_by
