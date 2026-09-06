"""The skills and specialists that ship with the package.

The maintainer's design, 2026-08-19, and it is better than the one it replaced:

  1. a **factory library** we write, which is **read-only**;
  2. a **per-user activation** — setup reads what they do for a living and
     turns on what fits, and they add or remove any of it from the dashboard
     afterwards;
  3. **editing forks.** Changing a library item in the dashboard produces a
     new item of their own. The original is never modified.

WHY POINT 3 IS THE ONE THAT MATTERS
-----------------------------------
Because the library is read-only, **an upgrade can replace all of it without
asking anybody anything.** Nothing a user has changed is in there to lose.

The alternative — shipping editable files — is the version that dies: every
upgrade would have to ask "have you touched this one?", the honest answer
would often be "I don't remember", and within a few releases nobody upgrades
at all. That is a well-worn path and this design avoids it entirely.

WHERE THINGS PHYSICALLY GO, AND WHY IT IS NOT TIDY
--------------------------------------------------
An activated skill is **copied into `~/.claude/skills/`**, because that is the
only folder Claude Code reads. Not a symlink (Windows needs a privilege for
those that a student will not have), and not a reference (there is nothing to
reference it with). Deactivating deletes that copy; the library keeps its own.

This package has already shipped one skill store that wrote somewhere tidier
and was never read — saved, listed, and inert. The rule that catches it is to
run the path a real user takes and check the effect, so the tests here assert
on what ends up in the skills folder rather than on what these functions
return.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import paths, skills_store

# Set on every copy we place in the shared skills folder, so that an item can
# be traced back to the library entry it came from -- and so a user's own fork
# is never mistaken for one of ours.
FROM_LIBRARY = "aki-library"


def library_dir() -> Path:
    """Where the shipped library lives: inside the package, never in config.

    `parents[2]` is the repository root, which is correct for a checkout and
    for the editable install `bin/_bootstrap.py` performs. It is NOT correct
    for a plain `pip install .`: `pyproject.toml` ships only `src/`, so the
    library would not be there at all and this would point somewhere above
    site-packages.

    That case fails silently -- `catalogue()` globs a folder that is not
    there, gets `[]`, and the Library page renders as an empty list with no
    error anywhere. `is_present()` exists so `doctor` can say so instead.
    """
    return Path(__file__).resolve().parents[2] / "library"


def is_present() -> bool:
    """Whether the shipped library is actually on disk.

    Asked rather than assumed, because the way it goes missing produces an
    empty page rather than a failure, and an empty page reads as "there is
    nothing in the library" rather than "the library is not installed".
    """
    return (library_dir() / "skills").is_dir()


@dataclass
class Item:
    """One thing the library ships."""

    key: str
    kind: str                       # "skill" | "specialist"
    name: str
    description: str = ""
    # Which occupations want this. `("*",)` means everybody -- the core set.
    industries: tuple = ()
    # What sort of job it is, for grouping a hundred of these into something
    # a person can look through.
    category: str = "General"
    # Words somebody might search for that are not in the name or the
    # description -- trade terms, abbreviations, the Chinese word for it.
    keywords: tuple = ()
    # How sure we are that this matches real practice: "high" where it was
    # written from first-hand knowledge, "draft" where it was written from
    # the shape of the work and wants review by somebody in that trade.
    confidence: str = "high"
    path: Path | None = None
    body: str = ""

    def matches(self, query: str) -> bool:
        """Free-text search across everything worth searching."""
        if not query:
            return True
        needle = query.casefold().strip()
        haystack = " ".join((
            self.key, self.name, self.description, self.category,
            " ".join(self.keywords), " ".join(self.industries))).casefold()
        return all(word in haystack for word in needle.split())

    @property
    def core(self) -> bool:
        return "*" in self.industries

    def wanted_by(self, occupation: str) -> bool:
        """Does this belong to somebody who describes their work like that?

        Deliberately generous: the occupation is free text a person typed
        during setup ("architect, small practice"), so this matches on any
        industry tag appearing in it. Being offered one skill too many is a
        click; missing one is an assistant that cannot do the job.
        """
        if self.core:
            return True
        lowered = (occupation or "").casefold()
        return any(tag.casefold() in lowered for tag in self.industries)


def _frontmatter(text: str) -> tuple[dict, str]:
    """Split `---` frontmatter from the body. No YAML dependency: the fields
    are flat strings and lists, and this file has to work before anything is
    installed."""
    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    header, body = text[3:end], text[end + 4:].lstrip("\n")
    fields: dict = {}
    for line in header.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            fields[key.strip()] = tuple(
                part.strip().strip("'\"")
                for part in value[1:-1].split(",") if part.strip())
        else:
            fields[key.strip()] = value.strip("'\"")
    return fields, body


def read_item(path: Path, kind: str) -> Item | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:                                       # pragma: no cover
        return None

    fields, body = _frontmatter(text)
    industries = fields.get("industries") or ()
    if isinstance(industries, str):
        industries = tuple(part.strip() for part in industries.split(",")
                           if part.strip())

    keywords = fields.get("keywords") or ()
    if isinstance(keywords, str):
        keywords = tuple(part.strip() for part in keywords.split(",")
                         if part.strip())

    return Item(
        # A shipped skill is `skills/<key>/SKILL.md`, so the folder names it.
        # A plugin may instead carry `skills/<key>.md` flat, and there the file
        # names it -- without this branch every flat skill in a package would
        # be keyed "skills" and all but the first would vanish as duplicates.
        key=str(fields.get("name")
                or (path.parent.name if kind == "skill"
                    and path.name.lower() == "skill.md" else path.stem)),
        kind=kind,
        name=str(fields.get("title") or fields.get("name") or path.stem),
        description=str(fields.get("description") or ""),
        industries=tuple(industries),
        category=str(fields.get("category") or "General"),
        keywords=tuple(keywords),
        confidence=str(fields.get("confidence") or "high"),
        path=path,
        body=body,
    )


def plugin_skills_dirs() -> list[Path]:
    """A `skills/` folder inside any installed plugin.

    The third of the same seam: `panels.plugin_panels_dirs()` opened it and its
    docstring already promised this one -- "a plugin ships the panels, the
    skills and the field list for one trade together". A profession arrives as
    one box and leaves as one box.

    Failures are swallowed. A broken plugin costs the user its own skills and
    not the library.
    """
    try:
        from . import plugins

        found, _ = plugins.installed()
        return [one.path / "skills" for one in found]
    except Exception:
        return []


def catalogue() -> list[Item]:
    """Everything available: what we ship, plus what plugins brought.

    A shipped skill of the same key wins, the opposite of the panel rule and
    deliberately so: a panel is a screen a plugin may legitimately want to
    replace, while a skill is instruction the assistant follows, and a package
    should not be able to quietly redefine one of ours by choosing its name.
    """
    found: list[Item] = []
    root = library_dir()

    for path in sorted((root / "skills").glob("*/SKILL.md")):
        item = read_item(path, "skill")
        if item:
            found.append(item)

    for directory in plugin_skills_dirs():
        if not directory.is_dir():
            continue
        # Both shapes: `<key>/SKILL.md` like ours, or a flat `<key>.md`.
        paths = sorted(directory.glob("*/SKILL.md")) + sorted(directory.glob("*.md"))
        for path in paths:
            item = read_item(path, "skill")
            if item and not any(one.key == item.key for one in found):
                found.append(item)

    for path in sorted((root / "specialists").glob("*.md")):
        item = read_item(path, "specialist")
        if item:
            found.append(item)

    return found


def by_key(key: str) -> Item | None:
    for item in catalogue():
        if item.key == key:
            return item
    return None


def categories() -> list[str]:
    """Every category in the library, in the order a person would read them.

    Core first because it is what everybody has, then the rest alphabetically
    -- a hundred items sorted by nothing is a list nobody scrolls.
    """
    found = {item.category for item in catalogue()}
    ordered = [name for name in ("Core",) if name in found]
    return ordered + sorted(found - set(ordered))


def industries() -> list[str]:
    """Every occupation tag in the library, for the filter."""
    tags = set()
    for item in catalogue():
        tags.update(tag for tag in item.industries if tag != "*")
    return sorted(tags)


def search(query: str = "", category: str = "", industry: str = "",
           kind: str = "") -> list[Item]:
    """The library, filtered. Every argument is optional and they compose."""
    found = catalogue()
    if query:
        found = [item for item in found if item.matches(query)]
    if category:
        found = [item for item in found
                 if item.category.casefold() == category.casefold()]
    if industry:
        found = [item for item in found
                 if industry.casefold() in
                 {tag.casefold() for tag in item.industries}]
    if kind:
        found = [item for item in found if item.kind == kind]
    return found


# ---------------------------------------------------------------------------
# Turning things on and off
# ---------------------------------------------------------------------------

def active_keys() -> set:
    """Which library skills are currently in the folder Claude Code reads."""
    found = set()
    folder = skills_store.skills_dir()
    if not folder.is_dir():
        return found

    for path in folder.glob("*/SKILL.md"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:                                   # pragma: no cover
            continue
        match = re.search(rf"{FROM_LIBRARY}:\s*(\S+)", text)
        if match:
            found.add(match.group(1))
    return found


def _stamp(text: str, key: str) -> str:
    """Record which library entry a copy came from, inside its frontmatter."""
    line = f"{FROM_LIBRARY}: {key}"
    if not text.startswith("---"):
        return f"---\n{line}\n---\n\n{text}"
    end = text.find("\n---", 3)
    if end == -1:                                         # pragma: no cover
        return text
    return text[:end] + f"\n{line}" + text[end:]


def _key_for(name: str) -> str:
    """A filename-safe key that survives a name written in Chinese.

    `[^a-z0-9]` has destroyed non-Latin data twice in this codebase -- two
    facts written entirely in Chinese both slugged to an empty string and the
    second silently replaced the first. `\\w` with Unicode semantics keeps
    them distinct.
    """
    cleaned = re.sub(r"[^\w]+", "-", (name or "").strip().casefold(),
                     flags=re.UNICODE).strip("-")
    return cleaned or "item"


# Files an operating system or a sync client leaves lying about. None of them
# is anybody's work, and all of them travel if nothing stops them.
CLUTTER = ("desktop.ini", "Thumbs.db", ".DS_Store", "Icon\r", "__pycache__",
           "*.pyc")


def _is_clutter(name: str) -> bool:
    return name in CLUTTER or name.endswith(".pyc")


def activate(key: str) -> tuple[bool, str]:
    """Copy one library skill into the folder Claude Code reads.

    A copy, not a link: Windows requires a privilege for symlinks that the
    people this package is for do not have, and a broken link is worse than a
    stale copy because it fails silently.
    """
    item = by_key(key)
    if item is None:
        return False, f"There is no library item called {key}."
    if item.kind != "skill":
        return activate_specialist(item)

    try:
        target = skills_store.skills_dir() / item.key
        target.mkdir(parents=True, exist_ok=True)
        original = item.path.read_text(encoding="utf-8", errors="replace")
        (target / "SKILL.md").write_text(_stamp(original, item.key),
                                         encoding="utf-8")
        # Anything alongside the SKILL.md -- checklists, templates -- comes
        # too. Except the things that are not content.
        #
        # Measured 2026-08-23: `library/skills` held 93 SKILL.md files and 94
        # `desktop.ini`, and nothing else. So this loop had never once copied
        # anything a person wrote -- it had only ever copied Google Drive's
        # own folder metadata, onto students' machines, marking their skill
        # folders with a system attribute and a custom icon they never chose.
        #
        # Refused by name rather than by a pattern. A skill that genuinely
        # needs a file called `.DS_Store` does not exist.
        for extra in item.path.parent.iterdir():
            if extra.name == "SKILL.md" or _is_clutter(extra.name):
                continue
            if extra.is_dir():
                shutil.copytree(extra, target / extra.name, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns(*CLUTTER))
            else:
                shutil.copy2(extra, target / extra.name)
    except OSError as exc:
        return False, f"could not turn on {item.name}: {exc}"

    return True, f"{item.name} is on"


def activate_specialist(item: Item) -> tuple[bool, str]:
    """Register a library specialist as one of the user's own.

    A specialist is configuration rather than a file, so "activating" it means
    writing the template's brief into their specialists file -- from where it
    behaves exactly like one they wrote.
    """
    from . import specialists

    fields, body = _frontmatter(
        item.path.read_text(encoding="utf-8", errors="replace"))

    existing = {one.key for one in specialists.read_all()}
    if item.key in existing:
        return True, f"{item.name} is already there"

    made = specialists.Specialist(
        key=item.key,
        name=item.name,
        purpose=item.description or item.name,
        brief=body.strip(),
        reads=tuple(part.strip()
                    for part in str(fields.get("reads", "")).split(",")
                    if part.strip()),
    )
    saved, problems = specialists.save(made)
    if problems:
        return False, "; ".join(problems)
    return True, f"{saved.name} is on"


def deactivate(key: str) -> tuple[bool, str]:
    """Remove our copy. The library keeps its own, so this is reversible."""
    item = by_key(key)
    name = item.name if item else key

    target = skills_store.skills_dir() / key
    marker = target / "SKILL.md"
    if not marker.is_file():
        return True, f"{name} was not on"

    text = marker.read_text(encoding="utf-8", errors="replace")
    if FROM_LIBRARY not in text:
        # Somebody's own work living under the same name. Not ours to delete.
        return False, (f"{name} in your skills folder is not the library copy "
                       "— it looks like your own. Rename or delete it "
                       "yourself if that is what you want.")

    try:
        shutil.rmtree(target)
    except OSError as exc:                                # pragma: no cover
        return False, f"could not turn off {name}: {exc}"
    return True, f"{name} is off"


def suggest(occupation: str) -> list[Item]:
    """What to turn on for somebody who describes their work like that."""
    return [item for item in catalogue() if item.wanted_by(occupation)]


# ---------------------------------------------------------------------------
# Editing without editing
# ---------------------------------------------------------------------------

def fork(key: str, new_name: str, body: str) -> tuple[bool, str]:
    """Save an edited version as the user's own, leaving the library alone.

    This is the whole of the maintainer's third rule. The library entry is never
    written to, which is what lets an upgrade replace the library wholesale
    without asking anybody whether they have changed anything.
    """
    item = by_key(key)
    if item is None:
        return False, f"There is no library item called {key}."

    wanted = (new_name or "").strip() or f"{item.name} (mine)"
    if wanted.casefold() == item.name.casefold():
        # Two things with one name is a coin toss over which one applies.
        wanted = f"{wanted} (mine)"

    if item.kind == "specialist":
        from . import specialists

        made = specialists.Specialist(key=_key_for(wanted), name=wanted,
                                      purpose=item.description or wanted,
                                      brief=body.strip())
        saved, problems = specialists.save(made)
        if problems:
            return False, "; ".join(problems)
        return True, (f"Saved as {saved.name}. The library's "
                      f"{item.name} is untouched.")

    _, problems = skills_store.save(name=wanted,
                                    description=item.description,
                                    body=body)
    if problems:
        return False, "; ".join(problems)
    return True, (f"Saved as {wanted}. The library's {item.name} is "
                  "untouched, and yours wins where they overlap.")
