"""The README is the first thing anybody reads, and it goes stale silently.

Before 2026-09-05 it advertised 459 tests when there were 1,870, said the
dashboard would bind to localhost "when it exists" long after it existed, and
told the reader twice that there is no remote access while `exposure.py` had
been shipping it. None of that was carelessness — prose has no compiler, so
nothing anywhere could notice.

These tests give it one, for the handful of claims that are checkable. They
deliberately do NOT try to check the prose: a test that asserts on wording
gets deleted the first time somebody rewrites a sentence, and then the whole
file stops being trusted. Only the numbers, the commands and the file names.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import aki_agent
from aki_agent import schedule


def repo() -> Path:
    return Path(aki_agent.__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def readme() -> str:
    return (repo() / "README.md").read_text(encoding="utf-8")


def test_the_version_it_advertises_is_the_version_that_ships(readme):
    stated = re.search(r"\|\s*Version\s*\|\s*([0-9][^\s|]*)\s*\|", readme)
    assert stated, "the status table no longer states a version"
    assert stated.group(1) == aki_agent.__version__


def test_the_test_count_is_within_reach_of_the_real_one(readme):
    """Not exact -- the number moves with every commit and an exact match
    would make this file a chore. An order of magnitude out is the failure
    worth catching: 459 when there were 1,870."""
    collected = len(list((repo() / "tests").glob("test_*.py")))
    assert collected > 20, "the test folder moved; this check is not looking"

    claimed = re.findall(r"([0-9],[0-9]{3}) tests", readme)
    assert claimed, "the README no longer says how many tests there are"
    for one in claimed:
        number = int(one.replace(",", ""))
        assert 1000 < number < 5000, (
            f"{number} tests claimed, which is not a plausible count for "
            f"{collected} test files -- has it gone stale again?")


def test_every_slash_command_it_names_exists(readme):
    for name in sorted(set(re.findall(r"/aki-agent:([a-z-]+)", readme))):
        assert (repo() / "skills" / name / "SKILL.md").exists(), (
            f"README sends the reader to /aki-agent:{name}, which is not a "
            "skill in this package")


def test_every_file_it_points_at_exists(readme):
    named = set(re.findall(r"`((?:src/|tests/|bin/|docs/)[\w./-]+)`", readme))
    named |= set(re.findall(r"\*\*`([A-Z]+\.md)`\*\*", readme))
    assert named, "the README stopped naming any files; check the pattern"
    for one in sorted(named):
        assert (repo() / one).exists(), f"README points at {one}, which is gone"


def test_the_number_of_shipped_tasks_is_right(readme):
    """It said "seven ship switched on" for a fortnight after there were ten
    definitions, three of which ship off. The distinction matters: the three
    that ship off are the ones a reader has to go and enable."""
    on = len([one for one in schedule.DEFAULT_TASKS if one.enabled])
    off = len(schedule.DEFAULT_TASKS) - on

    assert f"**Seven ship switched on**" in readme or f"{on} ship" in readme, (
        f"{on} tasks ship enabled; the README no longer says so")
    assert "three more ship" in readme or f"{off} more ship" in readme, (
        f"{off} tasks ship disabled; the README no longer says so")


def test_it_does_not_claim_there_is_no_remote_access(readme):
    """`exposure.py` has shipped it, opt-in, for weeks.

    The old wording was "Localhost only, no remote access" and "there is no
    remote access, by choice". Both were false, and both were reassuring,
    which is the worst combination.
    """
    assert (repo() / "src" / "aki_agent" / "exposure.py").exists()
    lowered = readme.lower()
    for claim in ("no remote access", "localhost only"):
        assert claim not in lowered, (
            f"README still says {claim!r}, but remote access exists and is "
            "opt-in -- say that instead")


def test_the_ollama_path_is_described_as_supported(readme):
    """Three files once gave two answers about this. The README is the fourth
    place a person could meet the wrong one."""
    assert "Ollama" in readme
    assert "ANTHROPIC_BASE_URL" in readme, (
        "the README describes the Ollama path without the one setting that "
        "makes it work")
    assert "the honest answer is no" not in readme


# ---------------------------------------------------------------------------
# Things that should not travel to strangers


def private_terms() -> list[str]:
    """Names and places that must not appear, read from OUTSIDE the repo.

    The first version of this check listed the author's family here, by name.
    In a private repository that is a guard; in a public one it publishes the
    very list it exists to protect -- a check that leaks what it is checking
    for. So the terms live in a file in the home folder, and this test skips
    when there is none, which is what a stranger cloning the repo will see.

    `~/.claude/scrub-terms.txt`, one per line, `#` for comments. Shared with
    `06_shared/01_skills/pre-publish-scrub`, which does the same job across
    the git history as well.
    """
    path = Path.home() / ".claude" / "scrub-terms.txt"
    if not path.exists():
        return []
    return [line.strip() for line in
            path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip() and not line.startswith("#")
            # The author's own name is authorship, not a leak: it is in the
            # plugin manifest on purpose. Only the rest of the list applies.
            and line.strip().lower() not in ("anzon", "wong")]


def test_no_private_names_are_used_as_sample_data():
    """They creep in as the nearest realistic example to hand.

    One test string was chosen because an apostrophe in it broke the confirm
    dialogs -- and the name was the author's wife. A public repository turns
    convenient sample data into somebody's name on the internet. `O'Brien`
    breaks exactly as well and is nobody.
    """
    family = private_terms()
    if not family:
        pytest.skip("no ~/.claude/scrub-terms.txt on this machine")

    found = []
    here = Path(__file__).resolve()
    for folder in ("src", "tests", "skills", "docs", "bin"):
        for path in (repo() / folder).rglob("*"):
            # This file names them in order to forbid them, which is the
            # oldest way for a check like this to fail against itself.
            if path.resolve() == here:
                continue
            if path.suffix not in (".py", ".md", ".html", ".json"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):         # pragma: no cover
                continue
            for name in family:
                if re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
                    found.append(f"{path.relative_to(repo())}: {name}")
    assert not found, "private terms used as sample data: " + "; ".join(found)


def test_nobodys_own_home_folder_is_baked_into_a_test():
    """A path like `C:/Users/<whoever wrote it>/Documents`, left in a test.

    Asked of `Path.home()` rather than of a name written down here, which
    means it hardcodes nobody, works on any machine, and -- the point -- would
    have caught this on the author's machine before the repository was public
    rather than after.
    """
    whose = Path.home().name
    if not whose or len(whose) < 3:                      # pragma: no cover
        pytest.skip("cannot tell whose home folder this is")

    for path in (repo() / "tests").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for shape in (f"Users/{whose}", f"Users\\{whose}", f"home/{whose}"):
            assert shape.lower() not in text.lower(), (
                f"{path.name} has somebody's own home folder in it: {shape}")
