"""Keep INTEGRATE.md honest.

INTEGRATE.md is read by *another agent* -- one running inside a student's own
setup, about to modify files on their machine. A guide that names a file which
no longer exists is not a documentation nit in that situation. It sends an
agent looking for something that is not there, and agents faced with a missing
file have a habit of improvising.

Documentation that is only checked by people rots. This checks it every run.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GUIDE = REPO_ROOT / "INTEGRATE.md"

# Files the guide mentions that belong to the READER's setup, not to this
# package. They must not be looked for here.
NOT_OURS = {"CLAUDE.md"}

# Extensions we treat as "this names a file".
FILE_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".json", ".toml", ".bat",
                 ".sh", ".command"}


def _referenced_paths(text: str) -> set[str]:
    """Every backticked token in the guide that looks like a path in this repo.

    Deliberately conservative. A token is only treated as a path if it has a
    recognised file extension or ends in a slash. Anything with a space is a
    shell command, not a path, and is skipped.
    """
    found: set[str] = set()

    for token in re.findall(r"`([^`\n]+)`", text):
        token = token.strip()
        if not token or " " in token:
            continue
        if token.startswith("~") or token.startswith("http"):
            continue          # the user's home folder, or a URL
        if token in NOT_OURS:
            continue
        if token.endswith("/"):
            found.add(token)
            continue
        if Path(token).suffix in FILE_SUFFIXES:
            found.add(token)

    return found


def test_guide_exists_and_is_addressed_to_an_agent():
    assert GUIDE.exists(), "INTEGRATE.md is missing"
    text = GUIDE.read_text(encoding="utf-8")
    # The first paragraph must make the audience unmistakable, because an
    # agent that thinks it is reading human documentation will skim it.
    assert "addressed to an AI agent" in text


def test_every_file_the_guide_names_actually_exists():
    """A guide that points at a missing file sends an agent improvising."""
    text = GUIDE.read_text(encoding="utf-8")
    missing: list[str] = []

    for reference in sorted(_referenced_paths(text)):
        if "*" in reference:
            # A glob, e.g. bin/check.* -- at least one match must exist.
            parent = REPO_ROOT / Path(reference).parent
            pattern = Path(reference).name
            if not (parent.exists() and list(parent.glob(pattern))):
                missing.append(reference)
            continue

        candidate = REPO_ROOT / reference
        if candidate.exists():
            continue

        # Bare module names in the capability table are relative to the
        # package directory -- `paths.py` means `src/aki_agent/paths.py`.
        if "/" not in reference:
            if (REPO_ROOT / "src" / "aki_agent" / reference).exists():
                continue

        missing.append(reference)

    assert not missing, (
        "INTEGRATE.md names files that do not exist. An agent following it "
        "would go looking for these:\n  " + "\n  ".join(missing)
    )


def test_guide_states_the_provenance_rule():
    """The safety rule is the reason this document is allowed to work at all.

    A document instructing an agent to change a machine is shaped exactly like
    a prompt injection. What makes this one legitimate is that the user asked
    for it. If that reasoning is ever edited out, the guide becomes a template
    for the attack it is currently teaching people to recognise.
    """
    text = GUIDE.read_text(encoding="utf-8")
    assert "provenance" in text.lower()
    assert "prompt injection" in text.lower()
    # And it must still require confirmation, not merely explain the risk.
    assert re.search(r"confirm .* with your user", text, re.IGNORECASE)


def test_guide_forbids_carrying_across_credentials_and_third_party_material():
    text = GUIDE.read_text(encoding="utf-8").lower()
    assert "credentials, ever" in text
    assert "belonging to somebody else" in text


def test_integrate_skill_points_at_the_guide_rather_than_summarising_it():
    """The skill must defer to the document, not replace it.

    If the skill ever becomes a self-contained summary, the two drift, and the
    agent works from the shorter, staler one.
    """
    skill = REPO_ROOT / "skills" / "integrate" / "SKILL.md"
    assert skill.exists()
    text = skill.read_text(encoding="utf-8")
    assert "INTEGRATE.md" in text
    assert "Read that file completely" in text
