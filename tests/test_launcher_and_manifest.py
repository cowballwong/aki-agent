"""Checks on the things that are duplicated because they have to be.

A few constants genuinely cannot be shared. `bin/_bootstrap.py` runs *before*
the package is installed, so it cannot import from the package. That means one
constant exists in two files.

Duplication like that is fine as long as it cannot drift silently. These tests
are what stop it drifting.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from aki_agent import doctor, paths

REPO_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = REPO_ROOT / "bin" / "_bootstrap.py"
PLUGIN_DIR = REPO_ROOT / ".claude-plugin"


def _literal_from(source_path: Path, name: str):
    """Read a module-level constant without importing the module.

    Importing `_bootstrap.py` would be the obvious approach and is the wrong
    one: it is a script, and importing scripts to inspect them is how tests
    acquire side effects.
    """
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {source_path.name}")


def test_app_dir_name_matches_between_package_and_launcher():
    """The launcher and the package must agree on where things live.

    If these drift, the launcher creates an environment in one folder and the
    package looks for its config in another, and the symptom is 'setup worked
    but the assistant says it is not configured' -- which is a genuinely
    horrible afternoon.
    """
    assert _literal_from(BOOTSTRAP, "APP_DIR_NAME") == paths.APP_DIR_NAME


def test_minimum_python_matches_between_doctor_and_launcher():
    """Both places that check the Python version must want the same version."""
    assert _literal_from(BOOTSTRAP, "MINIMUM_PYTHON") == doctor.MINIMUM_PYTHON


def test_launchers_exist_for_both_platforms():
    """macOS is not a later port. It ships from day one.

    There are already students on both platforms, so a Windows-only launcher
    is not a smaller version of the product -- it is a broken one.
    """
    assert (REPO_ROOT / "bin" / "check.bat").exists(), "Windows launcher"
    assert (REPO_ROOT / "bin" / "check.command").exists(), "macOS launcher"


def test_windows_launcher_uses_crlf_line_endings():
    """A .bat file with Unix line endings misbehaves on some Windows shells."""
    raw = (REPO_ROOT / "bin" / "check.bat").read_bytes()
    assert b"\r\n" in raw
    # And no stray lone-LF lines, which is what a careless editor leaves behind.
    assert raw.replace(b"\r\n", b"") .count(b"\n") == 0


def test_mac_launcher_does_not_use_crlf():
    """Conversely, CRLF in a shell script breaks the shebang on macOS.

    The error it produces -- 'bad interpreter: /bin/bash^M' -- is completely
    opaque to a non-developer, which is exactly why it is worth a test.
    """
    raw = (REPO_ROOT / "bin" / "check.command").read_bytes()
    assert b"\r\n" not in raw


@pytest.mark.parametrize("manifest_name", ["plugin.json", "marketplace.json"])
def test_plugin_manifests_are_valid_json(manifest_name):
    """A malformed manifest makes the plugin silently not load."""
    path = PLUGIN_DIR / manifest_name
    assert path.exists(), f"{manifest_name} is missing"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("name"), f"{manifest_name} has no name"
    assert data.get("description"), f"{manifest_name} has no description"


def test_skills_have_frontmatter_with_a_description():
    """Every skill needs a description or the model cannot decide to use it."""
    skills = sorted((REPO_ROOT / "skills").glob("*/SKILL.md"))
    assert skills, "no skills found"

    for skill in skills:
        text = skill.read_text(encoding="utf-8")
        assert text.startswith("---"), f"{skill.parent.name}: no frontmatter"
        block = text.split("---", 2)[1]
        assert "name:" in block, f"{skill.parent.name}: no name"
        assert "description:" in block, f"{skill.parent.name}: no description"


# Files allowed to contain credential-shaped text, and why.
#
# Deliberately tiny, and deliberately a list rather than a pattern. Every entry
# is a hole in the check, so each one has to be argued for in writing. If this
# list starts growing, that is the signal -- not an inconvenience to route
# around.
CREDENTIAL_SCAN_ALLOWLIST = {
    # The single place invented credential SHAPES are allowed to live.
    #
    # Three separate test files need something that looks like a credential.
    # Rather than widen this allowlist three times -- which is how a check
    # stops meaning anything -- the fakes were consolidated into one module
    # that every test imports from. Nothing in it is real.
    "tests/fake_credentials.py",
}


def test_no_credentials_committed_anywhere():
    """The guard against inheriting the defect that matters most.

    The source system this package derives from contains plaintext credentials
    committed in more than one script, plus a hardcoded fallback login on an
    endpoint its own comments admitted was exposed.

    This test exists so that the same thing cannot happen here quietly. Note
    that it can still happen *loudly* -- someone can add a file to the
    allowlist above. That is the intended escape hatch: a deliberate, reviewed,
    written-down decision rather than an accident.
    """
    from aki_agent import secrets

    suspicious: list[str] = []
    skip_dirs = {".git", "__pycache__", "venv", ".pytest_cache", "node_modules"}

    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.suffix.lower() not in {
                ".py", ".yaml", ".yml", ".json", ".md", ".bat", ".sh",
                ".command", ".toml"}:
            continue

        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative in CREDENTIAL_SCAN_ALLOWLIST:
            continue
        # This file necessarily contains the words it is looking for.
        if path.name == Path(__file__).name:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        # Line numbers only -- a check that finds a secret must never print it.
        lines = secrets.scan_for_committed_secrets(text)
        if lines:
            suspicious.append(
                f"{relative} (line{'s' if len(lines) > 1 else ''} "
                f"{', '.join(str(number) for number in lines)})"
            )

    assert not suspicious, (
        "something that looks like a credential is committed in these files. "
        "Secrets belong in the OS password manager, never in the package:\n  "
        + "\n  ".join(suspicious)
    )


def test_the_credential_allowlist_stays_small():
    """An allowlist that grows is an allowlist that has stopped meaning anything."""
    assert len(CREDENTIAL_SCAN_ALLOWLIST) <= 2, (
        "more than two files are now exempt from the credential scan. Each "
        "exemption is a place a real secret could hide -- justify it or "
        "remove it."
    )


def test_allowlisted_files_still_exist():
    """A stale allowlist entry is a silent hole."""
    for relative in CREDENTIAL_SCAN_ALLOWLIST:
        assert (REPO_ROOT / relative).exists(), (
            f"{relative} is exempt from the credential scan but no longer "
            "exists -- remove it from the allowlist."
        )


# ---------------------------------------------------------------------------
# Versions, and the day that proved they matter


def test_every_place_that_declares_a_version_agrees():
    """Three files carried it and nothing checked they matched.

    The reason first written here was that the manifest version names the
    folder the plugin installs into. CHECKED ON A REAL MACHINE 2026-08-24 and
    it does not: Claude Code caches the plugin under its NAME
    (`.claude/plugins/cache/aki-agent/aki-agent`), with no version in the path,
    so a mismatch breaks no scheduled task. The test was right and its stated
    reason was invented, which is worse than having no reason -- a reader who
    trusts it draws conclusions from it.

    The real reason to keep it: the manifest version is what `claude plugin`
    reports and what the upgrade compares against, so three files disagreeing
    means at least one of them is telling somebody the wrong version is
    installed. This one caught exactly that on 2026-08-24, when 0.33.0 shipped
    with the manifest still saying 0.32.0.
    """
    import json
    import re
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parent.parent

    package = re.search(
        r'__version__ = "([^"]+)"',
        (root / "src" / "aki_agent" / "__init__.py").read_text(
            encoding="utf-8")).group(1)
    project = re.search(
        r'^version = "([^"]+)"',
        (root / "pyproject.toml").read_text(encoding="utf-8"),
        re.M).group(1)
    plugin = json.loads(
        (root / ".claude-plugin" / "plugin.json").read_text(
            encoding="utf-8"))["version"]

    assert package == project == plugin, (
        f"package {package}, project {project}, plugin {plugin}")


def test_two_builds_on_one_day_get_different_names():
    """A date alone is not an identity.

    On the day this package changed most, five different zips were written to
    one date-stamped filename, so "the 17 August build" named five different
    pieces of software. The per-day counter fixes that, and an existing build
    is never overwritten.
    """
    import importlib.util
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "make_release", root / "bin" / "make_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    name = module._unused_name(module.package_version(), "2026-01-01").name
    assert name == "Aki-Agent-Beta-20260101-001.zip", name


def test_auto_mode_says_what_it_still_will_not_do():
    """The floor under auto mode is real; it used to be unadvertised.

    A person turning off "ask me each time" is deciding how much to let this
    run unattended, and that screen said only that permission checks are not
    bypassed "entirely" -- a sentence they had to take on faith. The gate
    could always list itself. Nothing called it where anybody was reading.
    """
    from aki_agent import launcher, safety_gate

    on = launcher.describe(launcher.LauncherOptions(workspace="X",
                                                    auto_mode=True))
    off = launcher.describe(launcher.LauncherOptions(workspace="X",
                                                     auto_mode=False))

    assert "refused outright" in on
    # Not a fixed sentence: whatever the gate refuses today is what is shown,
    # so a rule added later cannot go unmentioned here.
    for _pattern, why in safety_gate._RULES:
        assert why in on, why
    assert "refused outright" not in off
