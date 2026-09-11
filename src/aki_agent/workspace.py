"""Reading the user's workspace off disk.

WHAT A WORKSPACE IS
-------------------
A folder. Inside it, one sub-folder per item. Inside each of those, a few
markdown files whose names come from the user's config -- by default
`state.md`, `actions.md`, `waiting.md`, `history.md`.

That convention is kept deliberately from the system this package derives
from, because it is one of the genuinely domain-neutral things about it.
"Each item is a folder with a few summary files" is true whether the items are
building projects, music students, rental properties or legal matters. Only
the *fields inside* were profession-specific, and those now live in config.

WHY MARKDOWN AND NOT A DATABASE
-------------------------------
Because the user must be able to open their own data, read it, and edit it
without the software. A database would be tidier and would make this file
shorter. It would also mean that the day the software breaks, the user's notes
become unreachable, and that the class cannot open a file and see what the
agent sees. Legibility wins.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

from . import atomic
from .config import Config
from .schema import ItemSchema, Value


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

def split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown file into (frontmatter dict, body text).

    Frontmatter is a YAML block fenced by `---` lines at the very top of the
    file. A file without one is perfectly valid and yields an empty dict --
    plenty of a user's notes will just be prose, and that must not be an error.
    """
    import yaml

    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines()
    # Find the closing fence, starting after the opening one.
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            block = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1:])
            try:
                data = yaml.safe_load(block) or {}
            except yaml.YAMLError:
                # A malformed frontmatter block is a user typo, not a crash.
                # We return the whole thing as body so nothing is lost, and
                # the item's `problems` list will carry the explanation.
                return {"__frontmatter_error__": True}, text
            if not isinstance(data, dict):
                return {}, body
            return data, body

    # Opening fence with no closing fence -- treat the lot as body.
    return {}, text


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

@dataclass
class Item:
    """One unit of the user's work, whatever they call it.

    Note the absence of any profession-specific attribute. `values` holds
    whatever the user declared in their config, keyed by field name. If you are
    ever tempted to add `self.stage` or `self.client` here, that is the moment
    the design fails -- put it in the config schema instead.
    """

    key: str                      # the folder name, used as a stable id
    title: str                    # what to display
    path: Path
    values: dict[str, Value] = dataclass_field(default_factory=dict)
    sections: dict[str, str] = dataclass_field(default_factory=dict)
    problems: list[str] = dataclass_field(default_factory=list)
    # Which workspace this came from, and the schema that described it. Carried on
    # the item rather than looked up later, because with two workspaces "what shape
    # is this thing" is no longer answerable from the workspace alone.
    workspace: str = ""
    schema: ItemSchema = dataclass_field(default_factory=ItemSchema)
    missing_files: list[str] = dataclass_field(default_factory=list)
    last_modified: _dt.datetime | None = None

    @property
    def has_problems(self) -> bool:
        return bool(self.problems) or any(
            not value.ok for value in self.values.values())

    def value_problems(self) -> list[str]:
        """Field-level problems, phrased for a human."""
        return [
            f"{value.field.label}: {value.problem}"
            for value in self.values.values()
            if not value.ok
        ]


@dataclass
class Scan:
    """Everything read from disk in one pass, plus what went wrong."""

    root: Path | None
    schema: ItemSchema
    items: list[Item] = dataclass_field(default_factory=list)
    problems: list[str] = dataclass_field(default_factory=list)
    scanned_at: _dt.datetime | None = None
    # The workspaces the CONFIG declares, and the schema each one reads with.
    # Carried separately from the items because a workspace with nothing in it
    # yet has no items to be inferred from, and is still a workspace. See the
    # note on `by_workspace()`.
    workspaces: tuple[str, ...] = ()
    workspace_schemas: dict = dataclass_field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.items

    def by_workspace(self) -> list[tuple[str, ItemSchema, list["Item"]]]:
        """Items grouped by workspace, each with the schema that describes them.

        Anything that displays a workspace must go through this rather than
        through `self.schema`, because with two workspaces there is no longer one
        answer. A table drawn from the wrong workspace's schema does not fail --
        it shows a row of empty columns, which reads as "this project has no
        details filled in" rather than "you are looking at the wrong fields".

        With no workspaces configured there is exactly one group, named "", and
        everything behaves as it did.

        EVERY CONFIGURED WORKSPACE, INCLUDING THE EMPTY ONES (2026-09-11)
        -----------------------------------------------------------------
        This used to build its groups purely from the items, so a workspace
        holding no projects yet produced no group and did not exist as far as
        anything downstream could tell.

        That is not a missing card, it is a missing LEVEL. The front page
        decides whether it is the list of workspaces or the list of projects
        by counting these groups, while the heading beside it counts the
        workspaces in the config -- two sources for one question. Somebody
        with `01_Work` and `02_Family`, having filled in only one of them,
        got a page titled "Workspaces" listing projects, with `02_Family`
        nowhere on it and no way to reach it.

        A freshly created workspace is empty by definition, so the workspace
        somebody just made was always the one that could not be seen.
        """
        order: list[str] = [name for name in self.workspaces]
        grouped: dict[str, list[Item]] = {}
        for item in self.items:
            grouped.setdefault(item.workspace, []).append(item)
            # A folder on disk that the config does not list is still real and
            # still holds the person's work. Shown after the configured ones.
            if item.workspace not in order:
                order.append(item.workspace)

        def schema_for(workspace: str) -> ItemSchema:
            items = grouped.get(workspace)
            if items:
                return items[0].schema
            return self.workspace_schemas.get(workspace, self.schema)

        return [(workspace, schema_for(workspace), grouped.get(workspace, []))
                for workspace in order]

    def item_by_key(self, key: str) -> Item | None:
        for item in self.items:
            if item.key == key:
                return item
        # Fall back to the folder name on its own. Keys gained an workspace prefix
        # when two workspaces turned out to be able to hold a folder of the same
        # name; anything that stored a bare folder name before that -- a link,
        # a note, a CLI habit -- still resolves.
        for item in self.items:
            if item.path.name == key:
                return item
        return None

    def count_by_field(self, field_key: str) -> dict[str, int]:
        """How many items hold each value of one field.

        Used by the dashboard to draw a summary strip. It works for any enum
        field the user declared, because it does not know what the field means.
        """
        counts: dict[str, int] = {}
        for item in self.items:
            value = item.values.get(field_key)
            label = value.display if value else "--"
            counts[label] = counts.get(label, 0) + 1
        return counts


def load_item(directory: Path, schema: ItemSchema,
              workspace: str = "") -> Item:
    """Read one item folder, described by the schema it is given."""
    frontmatter: dict = {}
    sections: dict[str, str] = {}
    problems: list[str] = []
    missing: list[str] = []
    newest: _dt.datetime | None = None

    for name in schema.summary_files:
        file_path = directory / f"{name}.md"
        if not file_path.exists():
            missing.append(f"{name}.md")
            continue

        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # INHERITED TRAP: a file saved by a Windows editor in the local
            # code page will not decode as UTF-8. Say so plainly rather than
            # letting the exception escape and take the dashboard down.
            problems.append(
                f"{name}.md is not saved as UTF-8 text, so it could not be "
                "read. Re-save it as UTF-8 in your editor."
            )
            continue
        except OSError as exc:
            problems.append(f"{name}.md could not be opened: {exc}")
            continue

        data, body = split_frontmatter(text)
        if data.pop("__frontmatter_error__", False):
            problems.append(
                f"The settings block at the top of {name}.md is not valid "
                "YAML, so it was ignored."
            )
        # The first file that declares a key wins. `state.md` is conventionally
        # first in summary_files, which makes it the natural home for an
        # item's headline fields.
        for key, value in data.items():
            frontmatter.setdefault(key, value)
        sections[name] = body.strip()

        modified = _dt.datetime.fromtimestamp(file_path.stat().st_mtime)
        if newest is None or modified > newest:
            newest = modified

    title = str(frontmatter.get("title") or directory.name).strip()

    # Qualified by workspace, because the default scaffold gives every workspace a
    # "Project 1" and two items sharing a key means one of them is unreachable:
    # `item_by_key` returns the first, so clicking the second opens the first,
    # with nothing to suggest the wrong one is on screen.
    key = f"{workspace}/{directory.name}" if workspace else directory.name

    return Item(
        key=key,
        title=title,
        path=directory,
        values=schema.read_all(frontmatter),
        sections=sections,
        problems=problems,
        missing_files=missing,
        last_modified=newest,
        workspace=workspace,
        schema=schema,
    )


def scan(config: Config) -> Scan:
    """Read the whole workspace described by a config.

    This is the function the two-config test drives: give it two different
    configs and it must produce two coherent workspaces with no code change.
    """
    schema = config.layout.schema
    root = config.layout.root
    problems: list[str] = []

    if root is None:
        problems.append("No workspace folder is configured.")
        return Scan(root=None, schema=schema, problems=problems,
                         scanned_at=_dt.datetime.now())

    if not root.exists():
        # Deliberately not an exception. A cloud drive that has not mounted is
        # a normal state, and the honest response is an empty dashboard that
        # says why -- not a stack trace, and above all not a stale cache
        # presented as current.
        problems.append(
            f"The workspace folder is not available right now: {root}"
        )
        return Scan(root=root, schema=schema, problems=problems,
                         scanned_at=_dt.datetime.now())

    # Each item is read with the schema for *its own* workspace. With no workspaces
    # configured, `schema_for(None)` is the workspace schema and this is the
    # behaviour it always had.
    items = []
    for directory in config.layout.item_dirs():
        workspace = config.layout.workspace_of(directory) or ""
        items.append(load_item(directory, config.layout.schema_for(workspace),
                               workspace))

    # A configured workspace with no folder is the one failure that used to show as
    # a blank page and nothing else. Say it, and say what is actually there --
    # the answer is nearly always a numbering prefix the config did not get.
    for workspace, on_disk in config.layout.renamed_workspaces():
        problems.append(
            f"The config calls one workspace {workspace!r} but the folder is called "
            f"{on_disk!r}. It is being read anyway. Fix the name in Settings "
            "so the two agree."
        )
    missing_workspaces = config.layout.unmatched_workspaces()
    if missing_workspaces:
        present = sorted(child.name for child in root.iterdir()
                         if child.is_dir() and not child.name.startswith("."))
        problems.append(
            f"No folder for {', '.join(repr(a) for a in missing_workspaces)} in "
            f"{root}. Folders there: {', '.join(present) or 'none'}."
        )

    if not items:
        problems.append(
            f"No {schema.item_label_plural.lower()} found in {root}. "
            f"Each one should be a folder containing "
            f"{', '.join(name + '.md' for name in schema.summary_files)}."
        )

    return Scan(root=root, schema=schema, items=items,
                     problems=problems, scanned_at=_dt.datetime.now(),
                     workspaces=tuple(config.layout.workspaces),
                     workspace_schemas={name: config.layout.schema_for(name)
                                        for name in config.layout.workspaces})


# ---------------------------------------------------------------------------
# Renaming, and catching up with a folder somebody renamed themselves
#
#
# The two belong together. A workspace's name exists in two places -- the
# folder on disk and the `workspaces:` list in the config -- and this package
# has already been bitten once by letting them drift: a config saying `work`
# beside a folder called `01_work` gave two real installs an empty dashboard
# with nothing reporting an error. `resolved_workspaces()` now papers over
# small differences, which keeps people working and makes the drift quieter
# rather than rarer.
#
# So: rename moves BOTH in one action, and refresh is how the config catches
# up when somebody has already moved one of them in Explorer.
# ---------------------------------------------------------------------------

# Anything at the work root that is not somebody's work.
_NOT_A_WORKSPACE = {".git", ".venv", "__pycache__", ".DS_Store"}


def _reserved(config: Config) -> set[str]:
    layout = config.layout
    return {layout.config_dir, layout.sandbox_dir, layout.work_dir}


def folders_on_disk(config: Config) -> list[str]:
    """Every folder under the work root that could be a workspace.

    Sorted by name, which is the order a file manager shows and therefore the
    order the numbers in `01_`, `02_` were chosen to produce.
    """
    root = config.layout.work_root()
    if root is None or not root.is_dir():
        return []

    reserved = _reserved(config)
    found = []
    for path in sorted(root.iterdir(), key=lambda one: one.name.lower()):
        if not path.is_dir():
            continue
        if path.name in reserved or path.name in _NOT_A_WORKSPACE:
            continue
        if path.name.startswith("."):
            continue
        found.append(path.name)
    return found


def rename_workspace(config: Config, old: str, new: str) -> tuple[bool, str]:
    """Rename the folder and the config entry together.

    Refuses rather than guesses, in every case where guessing could lose
    somebody's work: no name, no change, a name with a path separator in it,
    a folder that is not there, or a folder that is.

    The config is updated in memory; saving it is the caller's job, so a
    failed rename cannot leave a config pointing at a folder that was never
    moved.
    """
    old = (old or "").strip()
    new = (new or "").strip()

    if not old or not new:
        return False, "A workspace needs a name."
    if new == old:
        return False, "That is the name it already has."

    # A rename is not a move. `..` or a slash here would take the folder out
    # of the workspace entirely, which is not what an Edit button means.
    if any(part in new for part in ("/", "\\", "..")) or new.startswith("."):
        return False, ("A workspace name cannot contain a slash or start "
                       "with a dot.")

    resolved = config.layout.resolved_workspaces()
    source = resolved.get(old)
    if source is None or not source.is_dir():
        return False, f"There is no folder for {old} to rename."

    target = source.parent / new
    if target.exists():
        return False, f"Something is already called {new} there."

    try:
        source.rename(target)
    except OSError as exc:
        # The usual cause on Windows is a file inside the folder being open,
        # and the usual cause of THAT is the person having it open. Say so
        # rather than reporting a failure with no cause.
        return False, (f"The folder could not be renamed: {exc}. Close "
                       "anything you have open inside it and try again.")

    config.layout.workspaces = tuple(
        new if one == old else one for one in config.layout.workspaces)
    # Per-workspace schemas are keyed by name, so they have to move too or the
    # renamed workspace silently loses its own fields and falls back to the
    # default -- an empty row of columns rather than an error.
    schemas = getattr(config.layout, "workspace_schemas", None)
    if isinstance(schemas, dict) and old in schemas:
        schemas[new] = schemas.pop(old)

    return True, f"Renamed to {new}."


def rescan_workspaces(config: Config) -> tuple[bool, str]:
    """Make the config's list match the folders that are actually there.

    For when somebody renamed, added or removed a folder in Explorer. The
    config is the thing that is wrong in that situation, and the folders are
    the thing that is true -- so the folders win.

    Only the list is touched. Nothing on disk is created, moved or deleted by
    a refresh: a button labelled "refresh" must never be the one that removes
    a folder.
    """
    root = config.layout.work_root()
    if root is None or not root.is_dir():
        return False, "There is no workspace folder to read yet."

    on_disk = folders_on_disk(config)
    if not on_disk:
        return False, (f"No workspace folders found in {root}. Nothing was "
                       "changed.")

    # Configured names that already resolve to a folder keep their own
    # spelling: `resolved_workspaces` matches `work` to `01_work`, and
    # rewriting that to the folder name would be a refresh quietly renaming
    # things in the config nobody asked it to touch.
    resolved = config.layout.resolved_workspaces()
    claimed = {one.name for one in resolved.values() if one is not None}

    kept = [name for name, path in resolved.items() if path is not None]
    added = [name for name in on_disk if name not in claimed]
    dropped = [name for name, path in resolved.items() if path is None]

    if not added and not dropped:
        return False, "Already up to date."

    config.layout.workspaces = tuple(kept + added)

    said = []
    if added:
        said.append("added " + ", ".join(added))
    if dropped:
        said.append("dropped " + ", ".join(dropped)
                    + " (no folder on disk)")
    return True, "Refreshed: " + "; ".join(said) + "."

def _retitle(directory: Path, schema: ItemSchema, new: str) -> None:
    """Point the `title:` in this item's summary files at its new name.

    WITHOUT THIS, RENAMING DOES NOTHING VISIBLE. `read_item` takes the title
    from the frontmatter and only falls back to the folder name -- so a
    project whose `state.md` says `title: 01_Project 1` goes on saying that
    however the folder is called.

    The maintainer met exactly this on 2026-09-05, having renamed four folders in
    Explorer. All four still read `01_Project 1`.

    Edited line by line rather than re-serialised through YAML. Round-tripping
    somebody's own file reorders their keys, drops their comments and
    reformats their quoting -- a rename has no business doing any of that.
    """
    for name in schema.summary_files:
        path = directory / f"{name}.md"
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        lines = text.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            continue

        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                break
            if lines[index].split(":", 1)[0].strip() == "title":
                lines[index] = f"title: {new}\n"
                try:
                    atomic.write_text(path, "".join(lines))
                except OSError:
                    pass
                break


def rename_item(config: Config, key: str, new: str) -> tuple[bool, str]:
    """Rename one project: its folder, its title, and its key.

    Refuses rather than guesses, for the same reasons `rename_workspace`
    does. Returns the new key when it worked, so the caller can move any pin
    that pointed at the old one.
    """
    key = (key or "").strip()
    new = (new or "").strip()

    if not key or not new:
        return False, "A name is needed."
    if any(part in new for part in ("/", "\\", "..")) or new.startswith("."):
        return False, ("A name cannot contain a slash or start with a dot.")

    space = scan(config)
    item = space.item_by_key(key)
    if item is None:
        return False, f"There is no {key} to rename."
    if item.path.name == new and item.title == new:
        return False, "That is the name it already has."

    target = item.path.parent / new
    if target.exists() and target != item.path:
        return False, f"Something is already called {new} there."

    if target != item.path:
        try:
            item.path.rename(target)
        except OSError as exc:
            return False, (f"The folder could not be renamed: {exc}. Close "
                           "anything you have open inside it and try again.")

    # After the move, and never allowed to undo it. The folder is the rename;
    # the title inside is what makes it visible. If a summary file cannot be
    # written -- read-only, open in an editor -- the rename still happened and
    # saying otherwise would be the lie. `_retitle` swallows per-file errors
    # for that reason.
    _retitle(target, item.schema, new)
    return True, f"Renamed to {new}."

def refresh_titles(config: Config, workspace: str = "") -> tuple[int, str]:
    """Make each project's name match the folder it is in.

    For when the folders were renamed somewhere else. `read_item` takes the
    title from the frontmatter and only falls back to the folder, so a folder
    renamed in Explorer changes nothing on screen -- the maintainer met that on
    2026-09-05 with four projects all still reading `01_Project 1`.

    The folders are the thing that is true here; the titles are the thing
    that is stale. Nothing on disk is created, moved or deleted -- only the
    `title:` line inside files that already have one.
    """
    space = scan(config)
    changed = 0
    for item in space.items:
        if workspace and item.workspace != workspace:
            continue
        if item.title == item.path.name:
            continue
        _retitle(item.path, item.schema, item.path.name)
        changed += 1

    if not changed:
        return 0, "Every name already matches its folder."
    return changed, (f"{changed} name{'s' if changed != 1 else ''} taken from "
                     "the folders.")
