"""Skills the user creates for themselves.

WHAT A SKILL IS, IN ONE SENTENCE
--------------------------------
A markdown file describing a job the assistant knows how to do, so that "write
my Monday update" means the same thing every Monday.

WHY THE USER MUST BE ABLE TO MAKE THEM
--------------------------------------
This is the difference between an assistant somebody uses and one somebody
owns. The moment a person writes their own skill, the tool has become theirs.
It is also the most teachable artefact in the whole package: a skill is a
plain text file, and reading one explains the entire idea in thirty seconds.

WHERE THEY LIVE, AND THE BUG THAT DECIDED IT
--------------------------------------------
In **`~/.claude/skills/`** — the folder Claude Code actually reads.

The first version wrote them to `~/.aki-agent/skills/`, which is tidier
and completely useless: Claude Code does not look there. A user could write a
skill, see it listed on the dashboard, and their assistant would never once
load it. Saved, visible, and inert.

That is the third time in this build the same mistake appeared — a thing built
without the thing that makes it take effect. The other two were a scheduler
pointing at a runner script that did not exist, and a notification channel
that cached its path before the folder was known. All three looked correct.
None of them errored. Each one's only symptom was an absence.

**The rule that would have prevented all three: after building something, run
the path a real user would take, end to end, and check the effect — not the
return value.**

Skills still never go inside the package, for three separate reasons:
  * an update to the package must never overwrite a person's own work
  * a person must be able to back up their skills without backing up software
  * a skill full of their private working details must not sit in a folder
    they might reasonably zip up and send to a colleague

Since `~/.claude/skills/` may also hold skills from elsewhere, every skill
written here carries a `source: aki-agent` marker, and this module only
ever lists or deletes ones carrying it. Somebody else's skills are not ours to
touch.

THE SHAPE OF A SKILL
--------------------
YAML frontmatter with a name and a description, then instructions in prose.
The description is what the assistant reads to decide whether a skill applies,
so a vague description means a skill that never triggers -- which is the
single most common way a hand-written skill fails.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from pathlib import Path

from . import atomic, paths


# The marker that says a skill in the shared folder is one of ours.
OWNER_MARKER = "aki-agent"

# The stamp `library.activate` puts on a copy it makes. Kept here as well as
# in `library.py` so that "is this one ours" can be answered without importing
# the library module -- which imports this one.
LIBRARY_MARKER = "aki-library"


def _placed_by_us(text: str) -> bool:
    """Did this package put this skill in the shared folder?

    TWO MARKERS, NOT ONE (2026-09-05)
    ---------------------------------
    Only `source: aki-agent` was checked, which is what a hand-written skill
    carries. A skill added from the Library is stamped `aki-library: <key>`
    instead -- so `read_all` filtered every one of them out, and adding
    something from the Library put a file on disk that never appeared in the
    Skills list. The maintainer asked for , reasonably believing that was already the behaviour; it was
    the behaviour of `activate` and not of the list.

    The rule this guard exists for is unchanged and is the right rule:
    somebody else's skills are not ours to list, edit or delete. A copy this
    package made from its own library is not somebody else's.
    """
    return (f"source: {OWNER_MARKER}" in text) or (f"{LIBRARY_MARKER}:" in text)


def skills_dir() -> Path:
    """Where Claude Code reads user skills from.

    NOT `~/.aki-agent/skills/`. See the note at the top of this file —
    writing there produced skills that were saved, listed, and never loaded.
    """
    return paths.home() / ".claude" / "skills"


@dataclass
class Skill:
    """One user-written skill."""

    key: str
    name: str
    description: str
    body: str = ""
    created: str = ""
    modified: str = ""
    # False for a skill in the shared folder that came from somewhere else.
    ours: bool = True

    @property
    def path(self) -> Path:
        return skills_dir() / self.key / "SKILL.md"

    def problems(self) -> list[str]:
        """What is wrong with this skill, in plain language.

        Checked on save so the user finds out immediately rather than
        wondering for a week why their skill never runs.
        """
        found: list[str] = []

        if not self.name.strip():
            found.append("It needs a name.")

        description = self.description.strip()
        if not description:
            found.append(
                "It needs a description. This is the part the assistant reads "
                "to decide whether to use the skill, so without one it will "
                "never trigger."
            )
        elif len(description) < 25:
            found.append(
                "The description is very short. It is what decides whether "
                "this skill gets used, so say when it applies -- for example "
                "'Use when the user asks for a weekly update, says \"write my "
                "Monday report\", or mentions the team summary.'"
            )
        elif " when " not in description.casefold():
            found.append(
                "The description does not say *when* to use this skill. "
                "Descriptions that name the trigger work far better than ones "
                "that only say what the skill does."
            )

        if not self.body.strip():
            found.append("It has no instructions in it yet.")

        return found


def _safe_key(text: str) -> str:
    """A stable key from a skill's name, in any script.

    THE SAME BUG AS `memory._safe_key` AND `specialists._safe_key`, A THIRD
    TIME. This stripped everything outside `[a-z0-9]`, so a skill named
    entirely in Chinese slugged to empty, fell back to the literal "skill",
    and the second such skill silently replaced the first. Nothing errors:
    the user saves two skills, sees one, and has no way to work out why.

    It happens only to people who do not name things in Latin script, which
    is most of the audience this package is written for. Fixed 2026-09-05,
    along with `knowledge._safe_key`, which had it too --
    `test_keys_survive_every_script` now asserts it of every `_safe_key` in
    the package at once, because fixing the instances has three times failed
    to fix the class.
    """
    key = re.sub(r"[^\w]+", "-", text.lower(), flags=re.UNICODE).strip("-_")
    return (key or "skill")[:50]


def read_all(include_others: bool = False) -> list[Skill]:
    """Skills in the shared folder.

    By default only ours. The folder belongs to the user and may hold skills
    from anywhere; listing somebody else's as though this package managed them
    would invite deleting them.
    """
    directory = skills_dir()
    if not directory.exists():
        return []

    found: list[Skill] = []
    for path in sorted(directory.glob("*/SKILL.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        name, description, body = _split(text)
        ours = _placed_by_us(text)

        if not ours and not include_others:
            continue

        stat = path.stat()
        found.append(Skill(
            key=path.parent.name,
            name=name or path.parent.name,
            description=description,
            body=body,
            ours=ours,
            modified=_dt.datetime.fromtimestamp(
                stat.st_mtime).isoformat(timespec="seconds"),
        ))
    return found


def get(key: str) -> Skill | None:
    for skill in read_all():
        if skill.key == key:
            return skill
    return None


def save(name: str, description: str, body: str,
         key: str | None = None) -> tuple[Skill, list[str]]:
    """Write a skill. Returns it, and anything wrong with it.

    Note that it saves even when there are problems, and reports them. A
    half-finished skill is a normal state -- refusing to save somebody's
    work-in-progress because the description is too short would be obnoxious.
    """
    skill = Skill(
        key=key or _safe_key(name),
        name=name.strip(),
        description=description.strip(),
        body=body.strip(),
    )

    # Never overwrite a skill that came from somewhere else. The folder is
    # shared, and quietly replacing another tool's skill would be a genuinely
    # nasty thing to do to somebody.
    if skill.path.exists():
        try:
            existing = skill.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            existing = ""
        if existing and not _placed_by_us(existing):
            return skill, [
                f"There is already a skill called '{skill.key}' in "
                f"{skills_dir()} that was not created here. It has been left "
                "alone. Choose a different name."
            ]

    # WHERE THE COPY CAME FROM SURVIVES AN EDIT (2026-09-05)
    #
    # The frontmatter was rebuilt from scratch here, with `source:` and
    # nothing else, so `library.activate`'s `aki-library: <key>` stamp was
    # thrown away by the first Save on the Tools tab. `library.active_keys()`
    # is a search for that stamp, so the Library row flipped back to **Add**
    # -- and Add is a `write_text` of the original over the copy, with no
    # condition on it. Edit your copy, glance at the Library, press what looks
    # like the button that installs it, and the edit is gone. `deactivate`
    # then refused to touch it ("looks like your own"), so the row could not
    # be cleared either.
    #
    # Only this one line is carried across; the rest of the frontmatter is
    # this function's to own.
    came_from = ""
    if skill.path.exists():
        try:
            for line in skill.path.read_text(encoding="utf-8").splitlines():
                # The literal, not `library.FROM_LIBRARY`: `library` imports
                # this module, so importing it back here is a cycle. The two
                # are held together by `test_a_library_copy_survives_an_edit`
                # rather than by an import.
                if line.startswith("aki-library:"):
                    came_from = line.strip()
                    break
        except (OSError, UnicodeDecodeError):
            came_from = ""

    text = "\n".join([
        "---",
        f"name: {skill.name}",
        f"description: {skill.description}",
        f"source: {OWNER_MARKER}",
        *([came_from] if came_from else []),
        "---",
        "",
        skill.body,
        "",
    ])

    skill.path.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_text(skill.path, text)

    return skill, skill.problems()


def delete(key: str) -> bool:
    """Remove a skill and its folder. Only ever one of ours."""
    skill = get(key)
    if skill is None or not skill.ours:
        return False

    try:
        skill.path.unlink()
        # Remove the folder too, but only if it is now empty -- the user may
        # have put supporting files in there.
        try:
            skill.path.parent.rmdir()
        except OSError:
            pass
        return True
    except OSError:
        return False


def _split(text: str) -> tuple[str, str, str]:
    """Pull name, description and body out of a skill file."""
    if not text.startswith("---"):
        return "", "", text.strip()

    lines = text.splitlines()
    name = description = ""
    body_start = 0

    for index in range(1, len(lines)):
        stripped = lines[index].strip()
        if stripped == "---":
            body_start = index + 1
            break
        if stripped.lower().startswith("name:"):
            name = stripped.partition(":")[2].strip()
        elif stripped.lower().startswith("description:"):
            description = stripped.partition(":")[2].strip()

    return name, description, "\n".join(lines[body_start:]).strip()


TEMPLATE_BODY = """\
## When to use this

Describe the situation. Be specific -- this is what decides whether the
assistant reaches for this skill at all.

## What to do

1. First step
2. Second step
3. Third step

## What good looks like

Describe the output you want. If you have an example of one you were happy
with, paste it here -- an example is worth a paragraph of description.

## What to avoid

Anything you have had to correct before. This section is where a skill stops
repeating the same mistake.
"""


def starter(name: str = "") -> Skill:
    """A blank skill with a useful shape, for the dashboard's 'new' button."""
    return Skill(
        key=_safe_key(name) if name else "",
        name=name,
        description="",
        body=TEMPLATE_BODY,
    )
