"""The one configuration object.

WHY THIS FILE EXISTS
--------------------
The system this package is derived from performs five environment-variable
reads in its entire engine, and not one of them is an identity or a path.
Everything else -- who the user is, where their work lives, what their
assistant is called, which language to speak -- is a literal typed into the
source. That is the single reason it is a one-person appliance rather than
something anyone can install.

So this package has exactly one rule about configuration:

    Nothing in the engine knows anything about a particular person.
    Everything it needs to know, it asks this object.

If you are about to write a name, a path, a job title, a language or a folder
into any other file: don't. Add it here, ask for it in the setup interview,
and read it from here.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any

from . import paths
from .schema import ItemSchema

# The config file format version. If a future release needs to change the
# shape of the file, this is what tells it whether it is reading an old one.
# Migrations are a real cost; the number exists so that we can charge it once
# rather than guess.
SCHEMA_VERSION = 1


class ConfigError(Exception):
    """Raised only for problems that make the config genuinely unusable.

    Note how rarely this is used. Most problems are collected and reported
    together in plain language by `Config.validate()`, because a user who has
    made three mistakes should be told about three mistakes, not made to fix
    them one crash at a time.
    """


@dataclass
class Assistant:
    """How the agent presents itself.

    The name is the *user's* choice, asked at install. That is not a cosmetic
    decision: an assistant a person has named is a thing they own, which is
    exactly the feeling this package is trying to produce. It also means the
    package itself does not need to impose a persona name on anyone.
    """

    name: str = "Assistant"
    # A short description of manner, fed to the agent persona. Plain words --
    # the user writes this themselves at install, in their own language.
    tone: str = "Warm, concise and practical."

    # --- how it looks -----------------------------------------------------
    #
    # The colour and the mark are the user's, chosen at setup, for the same
    # reason the name is: a thing you have named and coloured is yours in a
    # way a default never is. It is also the cheapest possible way to make two
    # students' assistants feel like different things rather than two copies
    # of the same software.
    #
    # One colour, not a palette. Everything else in the interface is derived
    # from it -- tints, borders, hovers -- so there is exactly one value to
    # get right and no way to produce a clashing combination.
    colour: str = "#67e8f9"
    # A short mark: one or two characters, or an emoji. Rendered in the
    # corner. Kept to text rather than an image file on purpose -- an image
    # means a path that can break, a file that can go missing, and a thing to
    # back up, for a decoration.
    logo: str = ""

    def initials(self) -> str:
        """What to show when no mark was chosen."""
        if self.logo:
            return self.logo
        words = [word for word in self.name.split() if word]
        if not words:
            return "?"
        if len(words) == 1:
            return words[0][:2].upper()
        return (words[0][:1] + words[1][:1]).upper()

    def safe_colour(self) -> str:
        """The colour, or the default if it is not a usable one.

        Validated because it is written straight into a stylesheet. A value
        that is not a colour would not merely look wrong -- it could close the
        CSS rule early and let arbitrary text through, which is how a settings
        field becomes an injection.
        """
        import re

        candidate = (self.colour or "").strip()
        if re.fullmatch(r"#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}", candidate):
            return candidate
        return "#67e8f9"


@dataclass
class User:
    """Who the agent works for.

    IDENTITY MUST BE EXPLICIT -- INHERITED DEFECT
    ---------------------------------------------
    The source system decides whether a piece of work belongs to its user by
    substring-matching their name inside free text, in several places. It even
    carries a tolerance for one misspelling of that name, and a reference to a
    colleague who has since left.

    The consequence is not subtle: a second person installing that system would
    be told that none of their work is theirs, and would have no idea why.

    So ownership here is an explicit, configured list of the strings that mean
    "me" -- your name, your initials, your username, however your own notes
    refer to you. The engine matches against that list and nothing else, and it
    never guesses.
    """

    name: str = ""
    # Every string that means "this is mine" in the user's own notes.
    identity_aliases: tuple[str, ...] = ()
    timezone: str = ""
    # Languages the user wants to be addressed in, most-preferred first.
    languages: tuple[str, ...] = ("en",)
    # Free text. The engine never branches on this; it is passed to the agent
    # persona so it can speak sensibly. If you ever find code doing
    # `if occupation == ...`, that is the bug this whole package guards against.
    occupation: str = ""
    # Where they are, in plain words -- "Winchester", "Hong Kong". Used
    # for the weather on the Today page and nothing else. A town name
    # rather than coordinates because a person can type a town name.
    location: str = ""

    # When they are at work. Not a preference -- three separate things read
    # it, and they must all read the same one.
    working_days: tuple[str, ...] = ("MON", "TUE", "WED", "THU", "FRI")
    working_from: str = "09:00"
    working_to: str = "17:30"

    def is_working(self, when=None) -> bool:
        """Is this a working day, at a working hour?

        A window that ends before it starts is read as crossing midnight --
        a night shift is a working pattern, not a typo, and refusing to
        represent one would quietly exclude whoever has it.
        """
        import datetime as _dt

        when = when or _dt.datetime.now()
        days = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
        if self.working_days and days[when.weekday()] not in self.working_days:
            return False

        def minutes(value: str):
            try:
                hour, _, minute = str(value).partition(":")
                hour, minute = int(hour), int(minute)
            except (TypeError, ValueError):
                return None
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None
            return hour * 60 + minute

        start, end = minutes(self.working_from), minutes(self.working_to)
        if start is None or end is None:
            return True          # unset or unreadable: do not lock anybody out
        now = when.hour * 60 + when.minute
        if start == end:
            return True          # all day
        if start < end:
            return start <= now < end
        return now >= start or now < end       # crosses midnight

    def working_hours_sentence(self) -> str:
        days = ", ".join(self.working_days) if self.working_days else "any day"
        return f"{self.working_from}–{self.working_to}, {days}"

    def owns(self, text: str) -> bool:
        """Does this free text refer to the user?

        Explicit, case-insensitive, whole-string-contains matching against the
        configured aliases. No fuzzy matching, no guessing at nicknames, no
        tolerance for misspellings -- if a user's notes call them something
        new, they add it to their aliases and the behaviour becomes
        predictable again.
        """
        if not text:
            return False
        haystack = text.casefold()
        return any(alias.casefold() in haystack
                   for alias in self.identity_aliases if alias)


@dataclass
class Layout:
    """Where everything lives on disk, and what one unit of work looks like.

    THE SHAPE (settled with reported 2026-08-17; sandbox lifted 2026-08-19)
    ---------------------------------------------------------------------
        <root>/                       the one folder that IS the assistant
            CLAUDE.md                 read at the start of every session
            .claude/skills/           skills written for this user
            01_Config/                config, memory, state, logs, launcher
            02_Sandbox/               the assistant's desk -- writes freely
            03_Workspace/
                01_Work/              a WORKSPACE
                    01_Project-1/     an ITEM -- the user's, needs approval
                        state.md ...  the tracking notes
                02_Personal/...

    The sandbox sits at the top rather than inside each workspace (the maintainer,
    2026-08-19). Three folders, numbered, visible the moment the folder is
    opened: settings, the assistant's desk, the person's work. A draft has
    one home instead of one per workspace, and nothing the assistant writes
    of its own accord is ever mixed in among the person's files.

    A folder made by an earlier version keeps its sandboxes inside each
    workspace and keeps working: `sandbox_dirs()` finds either shape.

    Three decisions in that picture are worth stating, because each replaced
    something that had been wrong:

    1. **`CLAUDE.md` and `.claude/` sit at the top, not in `01_Config`.**
       Claude Code reads them from the folder the session starts in and
       nowhere else. Tidied away into the config folder they would simply
       never load -- this package's most-repeated bug, and one it shipped
       once already.

    2. **One sandbox for the whole assistant, not one per item.** It sorts
       second, it is obvious, and there is exactly one place to look for a
       draft.

    3. **The item folder itself is what needs approval.** Not a `documents`
       sub-folder inside it -- anything the user puts in their project is
       theirs. The exception, and it is the whole job rather than a loophole,
       is the item's own summary files: the assistant keeps those up to date
       without asking, which is what makes it a tracker at all.

    `workspaces` empty means the simple shape -- one folder with item folders
    directly inside it -- which stays supported and is all some people need.
    """

    # The folder that holds the lot. `02_Workspace` and `01_Config` live
    # inside it.
    root: Path | None = None
    schema: ItemSchema = dataclass_field(default_factory=ItemSchema)
    # Top-level workspaces, in display order. Empty means the simple shape.
    workspaces: tuple[str, ...] = ()
    # A schema per workspace, for people whose two lives do not describe work the
    # same way.
    #
    # WHY THIS EXISTS (reported 2026-08-17)
    # -----------------------------------
    # An architect who teaches piano at weekends is one person with one
    # assistant, and the two halves of their work have nothing in common. A
    # building project has a stage, a client and a deadline; a pupil has a
    # grade, an instrument and unpaid fees. One shared set of fields leaves
    # both halves with boxes that do not apply.
    #
    # The package already proved the engine could serve either profession --
    # `configs/examples/architecture.yaml` and `music_teaching.yaml` are
    # exactly those two. What it could not do was serve both *at once*,
    # because the schema was a property of the whole workspace.
    #
    # An workspace with no entry here uses `schema` below, so the ordinary
    # one-occupation install is unchanged and its config file gains nothing.
    #
    # NOTHING WRITES THIS (noted 2026-09-06). It is read, it round-trips
    # through the YAML, and it works -- but the Settings page's field editor
    # only ever edits `schema`, the default one, so a per-workspace schema
    # exists only for somebody who opens the config file and types it. Said
    # here rather than left to be discovered, and not given a form on the
    # strength of an audit: whether it deserves one is a product decision.
    workspace_schemas: dict[str, ItemSchema] = dataclass_field(
        default_factory=dict)
    # Folder names. Configurable rather than constants because a user renaming
    # a folder should not break their install -- nothing in the engine may
    # assume these particular words.
    config_dir: str = "01_Config"
    work_dir: str = "03_Workspace"
    sandbox_dir: str = "02_Sandbox"

    @staticmethod
    def defaults() -> dict[str, str]:
        """The shipped folder names, read off the dataclass itself.

        `to_dict` writes these three only when they have been changed, and it
        has to compare against something. Taken from the field defaults rather
        than typed out a second time — two copies of the same three strings is
        two things to keep in step, and getting it wrong here means silently
        dropping somebody's renamed folder.
        """
        return {name: Layout.__dataclass_fields__[name].default
                for name in ("config_dir", "work_dir", "sandbox_dir")}

    def config_path(self) -> Path | None:
        """Where this agent keeps its configuration, memory and logs."""
        return self.root / self.config_dir if self.root else None

    def work_root(self) -> Path | None:
        """The folder the workspaces sit in.

        Falls back to the root itself when there is no `02_Workspace` folder,
        so a workspace arranged by hand -- or made by an older version -- keeps
        working instead of reporting itself empty.
        """
        if not self.root:
            return None
        nested = self.root / self.work_dir
        return nested if nested.is_dir() else self.root

    def schema_for(self, workspace: str | None) -> ItemSchema:
        """The schema describing work in this workspace.

        Falls back to the default schema, which is what every workspace uses
        unless the user asked for something different during setup. Asked for
        by name rather than by index so that reordering workspaces cannot
        silently give one somebody else's fields.
        """
        if workspace and workspace in self.workspace_schemas:
            return self.workspace_schemas[workspace]
        return self.schema

    def workspace_of(self, path: Path) -> str | None:
        """Which configured workspace contains this path, if any."""
        if not self.root or not self.workspaces:
            return None
        candidate = Path(path).resolve()
        for workspace, folder in self.resolved_workspaces().items():
            if folder is None:
                continue
            folder = folder.resolve()
            if candidate == folder or folder in candidate.parents:
                return workspace
        return None

    @staticmethod
    def _workspace_alias(name: str) -> str:
        """A folder name reduced to what a person actually said.

        Drops any `NN_` ordering prefix and the difference between spaces,
        hyphens, underscores and case -- none of which anybody means when they
        say which workspace their work is in.
        """
        import re
        cleaned = re.sub(r"^\d+[_\-. ]+", "", name.strip())
        return re.sub(r"[\s_\-]+", "", cleaned).casefold()

    def resolved_workspaces(self) -> dict[str, Path | None]:
        """Each configured workspace mapped to its folder on disk, or None.

        WHY THIS IS NOT JUST `work_root() / name`
        -----------------------------------------
        The setup interview asks somebody what their workspaces are called,
        they say "work" and "church", and the scaffold creates `01_work` and
        `02_church` because a file manager sorts alphabetically. If what gets
        written into the config is what they *said*, every lookup misses: no
        workspace folder is found, no item folder is found, and the dashboard
        shows an empty page.

        Found on a real install, 2026-08-17. It is exactly this package's
        recurring failure -- a correct mechanism wired to a name that does not
        exist -- and it produced no error at any layer, only an absence.

        So a configured name that does not match a folder exactly is matched
        again ignoring the number prefix, the separators and the case. The
        match is reported by `unmatched_workspaces()` and by `doctor`, because
        quietly working around a wrong config is how a wrong config survives.
        """
        base = self.work_root()
        if base is None or not base.exists():
            return {name: None for name in self.workspaces}

        resolved: dict[str, Path | None] = {}
        for name in self.workspaces:
            exact = base / name
            resolved[name] = exact if exact.is_dir() else self._walk_to(name)
        return resolved

    def _walk_to(self, workspace: str) -> Path | None:
        """Find a workspace's folder a segment at a time.

        Segment-wise because a real interview produced nested names
        (`01_Work/02_Piano`), and the prefix can be missing at any level: what
        somebody says is "work, piano" and what sorts properly on disk is
        `01_Work/02_Piano`.
        """
        current = self.work_root()
        assert current is not None
        for segment in Path(workspace).parts:
            step = current / segment
            if step.is_dir():
                current = step
                continue
            wanted = self._workspace_alias(segment)
            try:
                children = sorted(
                    (child for child in current.iterdir()
                     if child.is_dir() and not child.name.startswith(".")),
                    key=lambda child: child.name.lower())
            except OSError:
                return None
            match = next((child for child in children
                          if self._workspace_alias(child.name) == wanted), None)
            if match is None:
                return None
            current = match
        return current

    def _found_as(self, path: Path) -> str:
        """How a resolved workspace folder should be named in the config."""
        base = self.work_root()
        try:
            return path.relative_to(base).as_posix()
        except (ValueError, TypeError):
            return path.name

    def unmatched_workspaces(self) -> list[str]:
        """Configured workspaces with no folder on disk at all."""
        return [name for name, path in self.resolved_workspaces().items()
                if path is None]

    def renamed_workspaces(self) -> list[tuple[str, str]]:
        """Found under a different name: (configured, path under the root).

        Compared as a path, not as a folder name -- a workspace may
        legitimately be two deep, and comparing `01_Work/02_Piano` against the
        last segment `02_Piano` reported every nested one as renamed when
        nothing was wrong.
        """
        return [(name, self._found_as(path))
                for name, path in self.resolved_workspaces().items()
                if path is not None
                and self._found_as(path) != Path(name).as_posix()]

    def workspace_dirs(self) -> list[Path]:
        """Each configured workspace that actually exists on disk."""
        return [path for path in self.resolved_workspaces().values()
                if path is not None]

    def sandbox_dirs(self) -> list[Path]:
        """Every sandbox: where the assistant may write freely.

        One for the whole assistant, at the root, beside `01_Config` and
        `03_Workspace` (reported 2026-08-19). A single obvious place to look for
        a draft beats a dozen scattered ones.

        Folders built by an earlier version put a sandbox inside each
        workspace instead. Both shapes are looked for, and whichever exists on
        disk is what gets returned -- an upgrade must not silently take away
        the assistant's only place to write, which would leave it either
        blocked or writing into the person's project folders.
        """
        found: list[Path] = []
        if self.root:
            at_root = self.root / self.sandbox_dir
            if at_root.is_dir():
                found.append(at_root)

        bases = self.workspace_dirs() or (
            [self.work_root()] if self.work_root() else [])
        found += [base / self.sandbox_dir for base in bases
                  if (base / self.sandbox_dir).is_dir()]
        return found

    @staticmethod
    def _contains(parent: Path, candidate: Path) -> bool:
        """Containment, decided on resolved paths.

        By path and not by folder name, so that a stray folder of the same
        name somewhere else cannot claim protection it was never given -- and,
        more importantly, so a symlink or `..` cannot walk out of a sandbox
        while still looking like it is inside one.
        """
        parent = parent.resolve()
        return candidate == parent or parent in candidate.parents

    def is_protected(self, path: Path) -> bool:
        """Is this the user's own material -- not to be written unasked?

        The question that matters before any write, and since 2026-08-17 the
        answer is the whole item folder: anything the user puts inside one of
        their projects is theirs, without their having to file it into a
        special sub-folder first. Somebody who drops a contract into a project
        should be protected by that, not by having remembered where to drop it.

        The one exception is the item's own summary files -- `state.md` and
        the rest. Keeping those current is the assistant's job; stopping to ask
        before writing a tracker's tracking notes would make it useless.

        Still answered by *inclusion*: a folder nobody has classified is never
        silently treated as safe to overwrite.
        """
        candidate = Path(path).resolve()
        for item in self.item_dirs():
            if not self._contains(item, candidate):
                continue
            schema = self.schema_for(self.workspace_of(item))
            summaries = {(item / f"{name}.md").resolve()
                         for name in schema.summary_files}
            return candidate not in summaries
        return False

    def is_sandboxed(self, path: Path) -> bool:
        """Is this inside a sandbox -- somewhere free to write and to ruin?"""
        candidate = Path(path).resolve()
        return any(self._contains(sandbox, candidate)
                   for sandbox in self.sandbox_dirs())

    def item_dirs(self) -> list[Path]:
        """Every item folder, sorted by name.

        With workspaces configured, an item is a folder inside a workspace.
        Without them, an item is a folder directly inside the work root. The
        sandbox is never an item -- it is the assistant's own desk.

        Returns an empty list rather than raising if the folder is missing. A
        cloud-synced folder that has not mounted yet is a normal Tuesday, not
        an exception -- `doctor` is what tells the user about it.
        """
        base = self.work_root()
        if base is None or not base.exists():
            return []

        parents = self.workspace_dirs() if self.workspaces else [base]

        # The config folder is excluded by name as well as by position: with
        # no workspaces configured the work root and the agent's root can be
        # the same folder, and `01_Config` listed as a project is both wrong
        # and alarming.
        skip = {self.sandbox_dir.lower(), self.config_dir.lower(),
                self.work_dir.lower()}

        found: list[Path] = []
        for parent in parents:
            found += [child for child in parent.iterdir()
                      if child.is_dir() and not child.name.startswith(".")
                      and child.name.lower() not in skip]

        # De-duplicated by resolved path.
        #
        # WHY THIS IS NEEDED AT ALL (2026-08-20)
        # --------------------------------------
        # A real install had every project listed twice, in both halves of its
        # handoff. Two configured workspace names had resolved to the *same*
        # folder -- `resolved_workspaces` matches a name that does not exist
        # exactly by ignoring number prefixes, separators and case, so "Work"
        # and "01_Work" both land on `01_Work`. `workspace_dirs` then returned
        # it twice and every item inside it was read twice.
        #
        # Nothing errored. The symptom was a handoff that looked like the
        # person had two of everything -- the same class of failure this
        # package keeps finding in itself, where a wrong configuration is
        # quietly worked around until it surfaces as something inexplicable.
        #
        # So: deduplicate here, because a list of item folders containing the
        # same folder twice is wrong however the config got that way -- and
        # separately REPORT the collision through `colliding_workspaces`,
        # because silently absorbing a bad config is how a bad config
        # survives.
        seen: set[Path] = set()
        unique: list[Path] = []
        for child in found:
            try:
                key = child.resolve()
            except OSError:                               # pragma: no cover
                key = child
            if key in seen:
                continue
            seen.add(key)
            unique.append(child)

        return sorted(unique, key=lambda path: path.name.lower())

    def colliding_workspaces(self) -> list[tuple[str, ...]]:
        """Configured workspace names that point at one and the same folder.

        Returned so `doctor` can say so. The fuzzy match in
        `resolved_workspaces` exists to rescue a config whose names lost their
        number prefixes; it was never meant to let two names claim one folder,
        and when it does, the user has a config saying something they did not
        mean.
        """
        by_folder: dict[Path, list[str]] = {}
        for name, path in self.resolved_workspaces().items():
            if path is None:
                continue
            try:
                key = path.resolve()
            except OSError:                               # pragma: no cover
                key = path
            by_folder.setdefault(key, []).append(name)

        return [tuple(names) for names in by_folder.values() if len(names) > 1]


@dataclass
class Notifications:
    """Notification policy.

    Two inherited rules are encoded in the defaults, and both were learned the
    hard way:

    1. AN UNKNOWN CHANNEL DEFAULTS TO ON. A new sender that is silently off
       goes missing for weeks and nobody finds out. A new sender that is too
       noisy announces itself and gets switched off in one click. Fail towards
       being heard.

    2. A SUPPRESSED MESSAGE IS HELD, NOT DROPPED, and delivered as a single
       digest when suppression lifts. A held message that vanishes is worse
       than a noisy one, because the user never learns it existed.

    And the rule that is not a default but a design constraint: suppression
    stops the broadcast, never the work. Scheduled work keeps running; only
    the outbound message waits.
    """

    enabled: bool = True
    # Per-channel switches. A channel absent from this mapping is ON -- see
    # rule 1 above. That is why the lookup is a method, not a dict access.
    channels: dict[str, bool] = dataclass_field(default_factory=dict)
    quiet_hours: tuple[str, str] | None = None
    # Messages matching these are allowed through even when suppressed.
    urgent_keywords: tuple[str, ...] = ()

    def channel_enabled(self, channel: str) -> bool:
        """Is this channel switched on? Unknown channels are ON by design."""
        return self.channels.get(channel, True)



# The `Allowance` dataclass stood here until 2026-09-04. It held the weekly
# and five-hour token figures the two usage rings measured against, and both
# rings were removed the same evening: nothing on the machine records a
# subscription's limits, and every attempt to derive one was worse than
# showing nothing. See the note in `today.py` above the context ring.


def _schema_to_dict(schema: ItemSchema) -> dict:
    """One schema as plain data.

    Shared by the workspace-level schema and every per-workspace one, so the two
    can never drift into different spellings of the same thing -- which would
    load fine and then quietly lose a field.
    """
    return {
        "item_label": schema.item_label,
        "item_label_plural": schema.item_label_plural,
        "summary_files": list(schema.summary_files),
        "fields": [
            {
                "key": field.key,
                "label": field.label,
                "type": field.type,
                **({"values": list(field.values)} if field.values else {}),
                "source": field.source,
                **({"help": field.help} if field.help else {}),
            }
            for field in schema.fields
        ],
    }


@dataclass
class MailAccount:
    """One mailbox the assistant may read, and may draft from.

    THE PASSWORD IS NOT HERE, AND THAT IS THE POINT
    -----------------------------------------------
    Only what is safe in a plain-text file that gets copied around: the
    address, the servers, whether it may send. The app password lives in the
    operating system's credential store under `mail:{address}` -- which is
    the key `connectors.mail` already looks for, so the two halves finally
    meet. Before this there was nowhere to put an account at all, so the
    reading and sending code, both written and both correct, could never run.
    """

    address: str = ""
    label: str = ""
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 587
    may_send: bool = False

    def secret_key(self) -> str:
        return f"mail:{self.address}"


@dataclass
class CalendarFeed:
    """A read-only calendar subscription.

    An ICS URL, which every calendar service can produce and which needs no
    OAuth app registration -- keeping the promise that this package asks for
    no API keys. Read-only is stated rather than implied: nothing here can
    create or move an appointment, and a user should be told that plainly
    rather than discovering it.
    """

    name: str = ""
    url: str = ""


@dataclass
class ApiTool:
    """An outside service the user has given the assistant a key for.

    THE KEY IS NOT HERE, FOR THE SAME REASON THE PASSWORD IS NOT
    -----------------------------------------------------------
    Only what is safe in a plain-text file that gets backed up and copied
    between machines: which service, what it is allowed to be used for, and
    whether it is switched on. The key lives in the operating system's
    credential store under `api:{tool}` -- see `apis.secret_name`.

    WHY A JOB LIST RATHER THAN JUST "ON"
    ------------------------------------
    A key is not permission. Someone who pastes an OpenAI key so their
    assistant can transcribe a meeting has not agreed to it generating video at
    ten times the price. `jobs` is the agreement, and an empty list is a key
    stored and used for nothing -- which is a legitimate state, not a
    half-finished one.

    `label` and `env_name` are only for services that are not in the built-in
    catalogue, so that a user who pays for something unlisted is not stuck.
    """

    tool: str = ""
    label: str = ""
    jobs: tuple[str, ...] = ()
    enabled: bool = True
    env_name: str = ""

    def secret_key(self) -> str:
        return f"api:{self.tool}"


@dataclass
class Connections:
    """Everything the assistant is connected to, other than the chat channel."""

    mail: tuple[MailAccount, ...] = ()
    calendars: tuple[CalendarFeed, ...] = ()
    # Optional outside services -- pictures, voices, transcription, search.
    # Empty for everyone who never opens that page, which is the default state
    # and costs them nothing.
    apis: tuple[ApiTool, ...] = ()


def _providers_from(raw) -> dict:
    """The `providers:` block, cleaned, or an empty mapping.

    Shape errors are dropped rather than raised. A seam whose value is a
    string instead of a list, or a stray `providers: yes`, should not stop the
    assistant starting -- `seams.apply` is where a *name* nobody answers to
    becomes a loud problem, and it can only say that once it has a list to
    look at.
    """
    if not isinstance(raw, dict):
        return {}
    cleaned: dict = {}
    for what, names in raw.items():
        key = str(what).strip()
        if not key:
            continue
        if isinstance(names, str):
            names = [names]
        if not isinstance(names, (list, tuple)):
            continue
        wanted = tuple(str(one).strip() for one in names if str(one).strip())
        cleaned[key] = wanted
    return cleaned


@dataclass
class Config:
    """Everything the engine knows about this installation."""

    schema_version: int = SCHEMA_VERSION
    assistant: Assistant = dataclass_field(default_factory=Assistant)
    user: User = dataclass_field(default_factory=User)
    layout: Layout = dataclass_field(default_factory=Layout)
    notifications: Notifications = dataclass_field(
        default_factory=Notifications)
    connections: Connections = dataclass_field(default_factory=Connections)

    # Which providers each swappable part should load, by seam name --
    # `{"channel": ("file",), "calendar": ("ics", "google")}`. A seam that is
    # absent here keeps every provider it has, so a file written before this
    # existed behaves exactly as it did. `seams.apply` enforces the rest.
    providers: dict = dataclass_field(default_factory=dict)

    # Where this config was loaded from. Useful in `doctor` output and in
    # error messages -- "your config says X" is far more useful when the user
    # is told which file said it.
    source_path: Path | None = None

    # ---------------------------------------------------------------- checks

    def validate(self) -> list[str]:
        """Return every problem, in plain language, all at once.

        Deliberately returns strings a non-developer can act on. Compare with
        what this package must never do: print a traceback and stop.
        """
        problems: list[str] = []

        if self.schema_version != SCHEMA_VERSION:
            problems.append(
                f"This config says it is version {self.schema_version}, but "
                f"this version of the software expects {SCHEMA_VERSION}. "
                "Run the setup again to bring it up to date."
            )

        if not self.user.name:
            problems.append("Your name is not set -- run setup again.")

        if not self.user.identity_aliases:
            problems.append(
                "No identity aliases are set, so the assistant cannot tell "
                "which work in your notes is yours. Run setup again, or add "
                "at least your name."
            )

        if not self.assistant.name:
            problems.append("Your assistant has no name -- run setup again.")

        if self.layout.root is None:
            problems.append(
                "No workspace folder is set, so there is nothing to show. "
                "Run setup again and choose the folder your work lives in."
            )
        elif not self.layout.root.exists():
            problems.append(
                f"The workspace folder does not exist right now:\n"
                f"    {self.layout.root}\n"
                "If it is on a cloud drive (Google Drive, OneDrive, iCloud), "
                "it may simply not have finished starting up. If you moved it, "
                "run setup again."
            )

        problems.extend(self.layout.schema.validate())
        return problems

    # ------------------------------------------------------------ conversion

    @classmethod
    def from_dict(cls, data: dict, source_path: Path | None = None) -> "Config":
        """Build a Config from the parsed YAML file.

        Every section is optional. A half-finished config should load and then
        be *reported on*, not refuse to load -- otherwise `doctor` cannot tell
        the user what is wrong with it.
        """
        data = data or {}

        assistant_data = data.get("assistant") or {}
        user_data = data.get("user") or {}
        # `layout:` is the current name. `workspace:` was the name until
        # 2026-08-17, when "workspace" was given to the layer inside it -- and
        # a config written under the old name must keep loading rather than
        # come up empty, because an empty-looking config is the exact failure
        # this section has already produced once.
        layout_data = data.get("layout") or data.get("workspace") or {}
        notify_data = data.get("notifications") or {}

        # A workspace path may be written either absolutely (what the setup
        # interview writes, because a real user's folder is somewhere
        # specific) or relatively (what the example configs use, so that they
        # work on anyone's machine without editing).
        #
        # A relative path is resolved against the folder holding the config
        # file, NOT against the current working directory. Resolving against
        # the working directory would mean the same config behaved differently
        # depending on where you happened to launch it from, which is exactly
        # the kind of thing that wastes an afternoon.
        root_raw = layout_data.get("root")
        root: Path | None = None
        if root_raw:
            root = Path(str(root_raw)).expanduser()
            if not root.is_absolute() and source_path is not None:
                root = (Path(source_path).parent / root).resolve()

        connections_data = data.get("connections") or {}
        mail_accounts = tuple(
            MailAccount(
                address=str(entry.get("address", "")).strip(),
                label=str(entry.get("label", "")).strip(),
                imap_host=str(entry.get("imap_host", "")).strip(),
                imap_port=int(entry.get("imap_port", 993) or 993),
                smtp_host=str(entry.get("smtp_host", "")).strip(),
                smtp_port=int(entry.get("smtp_port", 587) or 587),
                may_send=bool(entry.get("may_send", False)),
            )
            for entry in (connections_data.get("mail") or [])
            if isinstance(entry, dict) and str(entry.get("address", "")).strip()
        )
        calendar_feeds = tuple(
            CalendarFeed(name=str(entry.get("name", "")).strip(),
                         url=str(entry.get("url", "")).strip())
            for entry in (connections_data.get("calendars") or [])
            # Keyed on the NAME, not the URL. The subscription address is a
            # bearer token for the whole calendar, so it lives in the OS
            # credential store and this entry carries an empty `url`. An
            # earlier version filtered on the URL being present, which
            # silently dropped every calendar on the way back in: the command
            # reported success and the config came back empty. Found by
            # running the real path rather than by a test, which is the point.
            if isinstance(entry, dict) and str(entry.get("name", "")).strip()
        )
        # Kept even when the named service is not in this build's catalogue.
        # Dropping an unrecognised entry would silently delete a user's own
        # unlisted service the next time anything saved the config -- the
        # quiet data loss this file warns about everywhere else.
        api_tools = tuple(
            ApiTool(
                tool=str(entry.get("tool", "")).strip().lower(),
                label=str(entry.get("label", "")).strip(),
                jobs=tuple(
                    str(one).strip()
                    for one in (entry.get("jobs") or ())
                    if str(one).strip()
                ),
                enabled=bool(entry.get("enabled", True)),
                env_name=str(entry.get("env_name", "")).strip(),
            )
            for entry in (connections_data.get("apis") or [])
            if isinstance(entry, dict) and str(entry.get("tool", "")).strip()
        )

        quiet = notify_data.get("quiet_hours")
        quiet_hours = (str(quiet[0]), str(quiet[1])) if quiet else None

        # A `usage:` block in an older config is read and ignored. It is not
        # an error to have one -- it is what this package asked for until
        # 2026-09-04 -- and dropping it on the next save is the right way for
        # a setting that no longer exists to go.

        return cls(
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
            assistant=Assistant(
                name=str(assistant_data.get("name", "Assistant")).strip(),
                tone=str(assistant_data.get(
                    "tone", "Warm, concise and practical.")).strip(),
                colour=str(assistant_data.get("colour", "#67e8f9")).strip(),
                logo=str(assistant_data.get("logo", "")).strip(),
            ),
            user=User(
                name=str(user_data.get("name", "")).strip(),
                identity_aliases=tuple(
                    str(alias).strip()
                    for alias in user_data.get("identity_aliases", ())
                    if str(alias).strip()
                ),
                timezone=str(user_data.get("timezone", "")).strip(),
                languages=tuple(
                    str(code).strip()
                    for code in user_data.get("languages", ("en",))
                    if str(code).strip()
                ) or ("en",),
                occupation=str(user_data.get("occupation", "")).strip(),
                location=str(user_data.get("location", "")).strip(),
                working_days=tuple(user_data.get("working_days")
                                   or ("MON", "TUE", "WED", "THU", "FRI")),
                working_from=str(user_data.get("working_from")
                                 or "09:00").strip(),
                working_to=str(user_data.get("working_to") or "17:30").strip(),
            ),
            layout=Layout(
                root=root,
                schema=ItemSchema.from_dict(layout_data),
                # `areas` was the name for these until 2026-08-17. Read as a
                # fallback so that a config written by an earlier version
                # keeps finding its own folders instead of coming up empty.
                workspaces=tuple(
                    str(workspace).strip()
                    for workspace in (layout_data.get("workspaces")
                                      or layout_data.get("areas") or ())
                    if str(workspace).strip()
                ),
                # Each entry is a whole schema in the same shape as the
                # workspace-level one, so a user who has read their config
                # file once already knows how to edit these.
                workspace_schemas={
                    str(name).strip(): ItemSchema.from_dict(fields or {})
                    for name, fields in (
                        layout_data.get("workspace_schemas")
                        or layout_data.get("area_schemas") or {}).items()
                    if str(name).strip()
                },
                # Falling back to the defaults rather than to "" matters: an
                # empty folder name would make the sandbox and the documents
                # folder both resolve to the workspace itself, silently handing the
                # assistant write access to everything.
                config_dir=str(layout_data.get(
                    "config_dir", "01_Config")).strip() or "01_Config",
                # A config file written by an earlier version carries its own
                # folder names and keeps them; only a file that never named
                # them picks up today's defaults.
                work_dir=str(layout_data.get(
                    "work_dir", "03_Workspace")).strip() or "03_Workspace",
                sandbox_dir=str(layout_data.get(
                    "sandbox_dir", "02_Sandbox")).strip() or "02_Sandbox",
            ),
            connections=Connections(mail=mail_accounts,
                                    calendars=calendar_feeds,
                                    apis=api_tools),
            notifications=Notifications(
                enabled=bool(notify_data.get("enabled", True)),
                channels=dict(notify_data.get("channels") or {}),
                quiet_hours=quiet_hours,
                urgent_keywords=tuple(
                    str(word).strip()
                    for word in notify_data.get("urgent_keywords", ())
                    if str(word).strip()
                ),
            ),
            providers=_providers_from(data.get("providers")),
            source_path=source_path,
        )

    def to_dict(self) -> dict:
        """Round-trip back to plain data, for writing the config file."""
        schema = self.layout.schema
        return {
            "schema_version": self.schema_version,
            # Like `connections`, written only when it says something, so a
            # config for someone who never limited a seam stays as short as
            # it was.
            **({"providers": {what: list(names)
                              for what, names in sorted(self.providers.items())}}
               if self.providers else {}),
            "assistant": {
                "name": self.assistant.name,
                "tone": self.assistant.tone,
                "colour": self.assistant.colour,
                "logo": self.assistant.logo,
            },
            # Written only when something is connected, so a config for
            # someone who connected nothing stays as short as it was.
            **({"connections": {
                    **({"mail": [
                        {"address": one.address, "label": one.label,
                         "imap_host": one.imap_host, "imap_port": one.imap_port,
                         "smtp_host": one.smtp_host, "smtp_port": one.smtp_port,
                         "may_send": one.may_send}
                        for one in self.connections.mail]}
                       if self.connections.mail else {}),
                    **({"calendars": [{"name": one.name, "url": one.url}
                                      for one in self.connections.calendars]}
                       if self.connections.calendars else {}),
                    # The order of this list is what decides which service does
                    # a job when two of them could -- see `apis.for_job`. So it
                    # is written out in order and must not be sorted here for
                    # tidiness.
                    **({"apis": [
                        {"tool": one.tool,
                         **({"label": one.label} if one.label else {}),
                         "jobs": list(one.jobs),
                         "enabled": one.enabled,
                         **({"env_name": one.env_name} if one.env_name
                            else {})}
                        for one in self.connections.apis]}
                       if self.connections.apis else {}),
                }} if (self.connections.mail or self.connections.calendars
                       or self.connections.apis)
               else {}),
            "user": {
                "name": self.user.name,
                "identity_aliases": list(self.user.identity_aliases),
                "timezone": self.user.timezone,
                "languages": list(self.user.languages),
                "occupation": self.user.occupation,
                **({"location": self.user.location}
                   if self.user.location else {}),
                "working_days": list(self.user.working_days),
                "working_from": self.user.working_from,
                "working_to": self.user.working_to,
            },
            "layout": {
                "root": str(self.layout.root) if self.layout.root
                        else "",
                # Written only when in use, so a config for the simple
                # one-folder shape stays as short as it was.
                **({"workspaces": list(self.layout.workspaces)}
                   if self.layout.workspaces else {}),
                # The three folder names travel with `workspaces` no longer.
                #
                # They used to be written only alongside it, so an install
                # with the simple one-folder shape dropped all three on every
                # save. If such an install had ever carried non-default names,
                # they survived exactly until the next save of anything at
                # all, and then the config reverted to the defaults while
                # pointing at folders that no longer had those names. Nothing
                # errored; the assistant simply stopped finding its own files.
                #
                # This comment said "which `/settings/save` offers", and it
                # does not: that page offers the workspace ROOT and nothing
                # else. `config_dir`, `work_dir` and `sandbox_dir` are
                # reachable only by editing the YAML, or from a config an
                # older version wrote. Corrected 2026-09-06 -- the defensive
                # write below is still right, and it is worth knowing that
                # what it defends against arrives by hand rather than through
                # a form somebody could be told to stop using.
                #
                # Written when they differ from the defaults, so the short
                # config the comment above is protecting stays short.
                **{name: value for name, value in (
                    ("config_dir", self.layout.config_dir),
                    ("work_dir", self.layout.work_dir),
                    ("sandbox_dir", self.layout.sandbox_dir))
                   if value != Layout.defaults()[name]},
                **_schema_to_dict(schema),
                # Written only when a workspace actually declares its own
                # fields. An architect who does not also teach piano never
                # sees this key in their file.
                **({"workspace_schemas": {
                        name: _schema_to_dict(workspace_schema)
                        for name, workspace_schema
                        in self.layout.workspace_schemas.items()}}
                   if self.layout.workspace_schemas else {}),
            },
            "notifications": {
                "enabled": self.notifications.enabled,
                "channels": dict(self.notifications.channels),
                **({"quiet_hours": list(self.notifications.quiet_hours)}
                   if self.notifications.quiet_hours else {}),
                "urgent_keywords": list(self.notifications.urgent_keywords),
            },
        }


# ---------------------------------------------------------------------------
# Loading and saving
# ---------------------------------------------------------------------------

def load(path: Path | None = None) -> Config:
    """Load the user's config.

    `path` is for tests and for the two-config demonstration. Normal callers
    pass nothing and get the installed user's config.
    """
    import yaml  # imported here so that `doctor` can run without PyYAML

    config_path = Path(path) if path else paths.config_file()

    if not config_path.exists():
        raise ConfigError(
            f"No configuration found at {config_path}.\n"
            "Run the setup interview first -- in Claude Code, type /aki-agent:setup."
        )

    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    if not isinstance(data, dict):
        raise ConfigError(
            f"{config_path} does not look like a configuration file. "
            "It should start with 'schema_version:'."
        )

    return Config.from_dict(data, source_path=config_path)


def save(config: Config, path: Path | None = None) -> Path:
    """Write the config file, atomically.

    ATOMIC WRITE -- INHERITED TRAP
    ------------------------------
    Write to a temporary file, then rename over the target. Never truncate the
    real file first.

    Two separate incidents in the source system trace to not doing this: a
    reader on a schedule caught a half-written state file and threw, and the
    sender that threw dropped its message silently. Rename is atomic on both
    Windows and macOS, so the reader either sees the whole old file or the
    whole new one, and never a torn one.

    WHERE IT GOES WHEN NOBODY SAYS
    ------------------------------
    Back where it was loaded from, and only then to the installed location.

    Reading `source_path` was missing, and on a normal install the two are the
    same file so nothing looked wrong. But the dashboard can be started against
    a named config -- that is how the two-config demonstration works -- and
    every save from it went to the installed config instead: the page reported
    success, the file it was showing never changed, and the user's real settings
    were quietly edited by a demonstration. Writing a file back where it came
    from is the least surprising thing this function can do.

    LOCKED, AND FLUSHED
    -------------------
    This wrote its own temporary file and renamed it, which is the right shape
    and was missing two things `atomic.write_text` already had.

    **No fsync.** A rename is atomic with respect to other readers, but the
    bytes behind it may still be in the operating system's cache. A power cut
    between the rename and the flush leaves a correctly-named empty config —
    which, for the one file that says who the assistant is and where
    everything lives, is the worst of the possible outcomes.

    **No lock.** The dashboard is threaded and there are ten places that save.
    Two overlapping saves each build a complete file from their own copy of
    the config, and the second rename silently wins — so a settings change and
    a schedule change made seconds apart could end with one of them simply
    absent, with both pages reporting success.
    """
    import yaml

    from . import atomic

    target = Path(path or config.source_path or paths.config_file())
    target.parent.mkdir(parents=True, exist_ok=True)

    with atomic.lock(target):
        atomic.write_text(target, yaml.safe_dump(
            config.to_dict(), sort_keys=False, allow_unicode=True))
    return target
