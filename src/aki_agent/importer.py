"""Reading an assistant somebody already built, so its contents can move here.

THE QUESTION THIS ANSWERS (reported 2026-08-20)
---------------------------------------------
A person who already has their own agent has two ways to end up with this one,
and he asked for both. They are not symmetrical, and the asymmetry is the
whole design:

  **Import** — Aki is the base; their material moves in. Bounded, because the
  destination is a structure this package defines and can therefore check.
  That is this file.

  **Integrate** — their agent is the base; Aki's capabilities move out to it.
  Unbounded, because the destination is somebody else's codebase, different
  every time and impossible to test against. That one stays *guidance*
  (`INTEGRATE.md`) and deliberately has no tool. A tool implies a guarantee
  nobody can make.

WHAT MOVES, AND THE ONE THING THAT MUST NOT
-------------------------------------------
Four kinds of thing are worth taking: what they have written down, the facts
about them their setup encodes, the instructions they wrote for their agent,
and anything they had scheduled.

**Their code does not move.** Their Python is theirs and this package has its
own engine; a "just bring the scripts too" import is not an import any more,
it is `INTEGRATE.md` performed badly by something that thinks it is copying
files. Code is surveyed so it can be *reported* — "you had eleven scripts,
none came, here is what they seem to do" — and never copied.

EVERYTHING THIS CANNOT TAKE MUST BE NAMED
-----------------------------------------
The failure to avoid is the one this codebase found in itself the same
morning: an upgrade silently did not copy `library`, 103 files, and every
check passed. So `Survey` carries `skipped` alongside `found`, `report()`
prints both, and nothing here is allowed to finish quietly. An import that
says only what it took is indistinguishable from one that lost half of it.

THEIR FILES ARE DATA
--------------------
An agent folder is full of instructions — that is what an agent folder is for.
`CLAUDE.md` will contain sentences like "always do X", "never mention Y",
addressed to *their* assistant. Read here, those are content to be moved, not
orders to be followed. This module only ever reads and classifies; it runs
nothing it finds, and the skill above it is told the same thing in the same
words.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Kinds, in the order a report lists them.
NOTES = "notes"
INSTRUCTIONS = "instructions"
SETTINGS = "settings"
SCHEDULE = "schedule"
CODE = "code"
SECRET = "secret"
OTHER = "other"

TAKEABLE = (INSTRUCTIONS, SETTINGS, NOTES, SCHEDULE)

# What each kind means when it lands in the report, in the words a person
# would use. Held here rather than in the skill so the wording cannot drift
# between the two.
MEANING = {
    NOTES: "things you or your agent wrote down",
    INSTRUCTIONS: "instructions you wrote for your agent",
    SETTINGS: "settings and configuration",
    SCHEDULE: "anything you had running on a timer",
    CODE: "programs — these stay where they are, see the note below",
    SECRET: "passwords and keys — never copied, see the note below",
    OTHER: "everything else",
}

INSTRUCTION_NAMES = {
    "claude.md", "agents.md", "system.md", "prompt.md", "persona.md",
    "instructions.md", "readme.md", "soul.md",
}
SETTINGS_SUFFIXES = {".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".env"}
NOTE_SUFFIXES = {".md", ".markdown", ".txt", ".org"}
CODE_SUFFIXES = {".py", ".js", ".ts", ".sh", ".ps1", ".bat", ".command",
                 ".rb", ".go", ".rs", ".java", ".c", ".cpp"}
SCHEDULE_HINTS = ("cron", "schedule", "task", "timer", "launchd", "schtasks")

# Never opened, never copied, always mentioned.
SECRET_HINTS = ("secret", "credential", "password", "token", "apikey",
                "api_key", ".env", "id_rsa", ".pem", ".key")

# Folders that are somebody else's business: caches, checkouts, dependencies.
IGNORED_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules", ".pytest_cache",
    "dist", "build", ".idea", ".vscode", ".mypy_cache", ".ruff_cache",
    "site-packages", ".cache",
}

# A file bigger than this is not a note somebody wrote; it is data, a model or
# a log, and copying it into a memory store helps nobody.
TOO_BIG = 2 * 1024 * 1024


@dataclass
class Item:
    path: Path
    kind: str
    size: int = 0
    why_skipped: str = ""

    @property
    def takeable(self) -> bool:
        return self.kind in TAKEABLE and not self.why_skipped


@dataclass
class Survey:
    root: Path
    items: list[Item] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)

    def of_kind(self, kind: str) -> list[Item]:
        return [one for one in self.items if one.kind == kind]

    @property
    def takeable(self) -> list[Item]:
        return [one for one in self.items if one.takeable]

    @property
    def skipped(self) -> list[Item]:
        return [one for one in self.items if not one.takeable]


def classify(path: Path, root: Path) -> Item:
    """What kind of thing is this, and can it come?

    Ordered most-specific first. Secrets are decided before anything else,
    because a file called `secrets.yaml` is a settings file by every other
    test here and must never be treated as one.
    """
    name = path.name.lower()
    relative = str(path.relative_to(root)).lower().replace("\\", "/")
    suffix = path.suffix.lower()

    try:
        size = path.stat().st_size
    except OSError:
        size = 0

    if any(hint in relative for hint in SECRET_HINTS):
        return Item(path, SECRET, size,
                    "it looks like it holds a password or key, and those are "
                    "never copied — set them up again on the API keys page")

    if suffix in CODE_SUFFIXES:
        return Item(path, CODE, size,
                    "programs are not imported — the assistant here has its "
                    "own engine")

    if name in INSTRUCTION_NAMES:
        kind = INSTRUCTIONS
    elif any(hint in relative for hint in SCHEDULE_HINTS) and suffix in (
            SETTINGS_SUFFIXES | NOTE_SUFFIXES):
        kind = SCHEDULE
    elif suffix in SETTINGS_SUFFIXES:
        kind = SETTINGS
    elif suffix in NOTE_SUFFIXES:
        kind = NOTES
    else:
        return Item(path, OTHER, size,
                    "not a kind of file this knows how to bring across")

    if size > TOO_BIG:
        return Item(path, kind, size,
                    f"it is {size // 1024 // 1024} MB — too big to be "
                    "something you wrote, so it is left where it is")

    return Item(path, kind, size)


def survey(root: Path | str) -> Survey:
    """Look at somebody's agent folder. Reads nothing into memory, runs nothing.

    Only the shape and the names are examined here; the contents are read
    later, by the skill, one file at a time and with the user watching. That
    split is deliberate — a survey that slurps every file has already done the
    thing it was supposed to ask permission for.
    """
    root = Path(root).expanduser()
    found = Survey(root=root)

    if not root.is_dir():
        found.unreadable.append(f"{root} is not a folder that exists.")
        return found

    for path in sorted(root.rglob("*")):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        try:
            found.items.append(classify(path, root))
        except OSError as exc:                            # pragma: no cover
            found.unreadable.append(f"{path}: {exc}")

    return found


def report(found: Survey) -> str:
    """What was seen, what can come, and — the point — what cannot.

    Written to be read out to a person before anything is copied, so the
    sentence "this is what I am about to do" is true rather than a formality.
    """
    if found.unreadable and not found.items:
        return "\n".join(found.unreadable)

    lines = [f"In {found.root}:", ""]

    for kind in (INSTRUCTIONS, SETTINGS, NOTES, SCHEDULE):
        items = [one for one in found.of_kind(kind) if one.takeable]
        if items:
            lines.append(f"  can come — {MEANING[kind]}: {len(items)} file(s)")
    if not found.takeable:
        lines.append("  nothing here can be brought across automatically.")

    lines.append("")

    # Grouped by reason rather than by file: forty lines of "skipped" is a
    # wall nobody reads, and the reason is the part that is actually useful.
    reasons: dict[str, int] = {}
    for one in found.skipped:
        reasons[one.why_skipped or "no reason recorded"] = reasons.get(
            one.why_skipped or "no reason recorded", 0) + 1
    if reasons:
        lines.append("  NOT coming, and why:")
        for reason, count in sorted(reasons.items(), key=lambda p: -p[1]):
            lines.append(f"    {count:>4}  {reason}")

    for problem in found.unreadable:
        lines.append(f"    !  {problem}")

    lines += [
        "",
        "  Nothing in your own folder is moved, changed or deleted. This",
        "  copies; your assistant keeps working exactly as it does now.",
    ]
    return "\n".join(lines)
