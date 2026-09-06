"""Three kinds of memory, kept apart on purpose.

WHY THREE AND NOT ONE
---------------------
It is tempting to build "the memory system" as one store. Resist it. These
three differ in the two dimensions that actually decide storage design —
**how often they are overwritten** and **how long they must survive** — and
merging them means the shortest-lived one dictates the rules for all three.

    WORKING STATE   rewritten every few minutes    lives for one session
                    "what I am in the middle of"

    FACTS           written rarely, read constantly    lives for years
                    "things that stay true about this person"

    DAILY NARRATIVE appended through the day        lives forever, read rarely
                    "what happened, in order"

Put facts in the working state and they get wiped on every rewrite. Put
working state in the facts and it accumulates into noise nobody can search.
Put either in the narrative and you cannot find them again.

THE PART THAT MATTERS MOST, AND IS EASIEST TO GET WRONG
-------------------------------------------------------
The working-state file is rewritten mechanically. It therefore has a section
below a marker line which is **never** touched by the rewrite, where the
assistant records what it was mid-doing and what it intended next.

That distinction is the whole value. The mechanical part records *what
happened*, which any summary can reconstruct. The human notes record *what I
was in the middle of and why*, which a summary destroys — and which is
precisely what you need after a crash.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

from . import atomic, paths, secrets

# Everything below this line in the working-state file survives a rewrite.
HUMAN_NOTES_MARKER = "<!-- notes below this line survive regeneration -->"

# A working-state file older than this is reported as stale rather than
# trusted. See the staleness rule at the bottom of this module.
STALE_AFTER_HOURS = 12


# ---------------------------------------------------------------------------
# Tier 1 — working state
# ---------------------------------------------------------------------------

@dataclass
class WorkingState:
    """What the assistant is in the middle of, right now."""

    generated_at: _dt.datetime
    open_items: list[str] = dataclass_field(default_factory=list)
    waiting_on: list[str] = dataclass_field(default_factory=list)
    recent_files: list[str] = dataclass_field(default_factory=list)
    human_notes: str = ""

    @property
    def age(self) -> _dt.timedelta:
        return _dt.datetime.now() - self.generated_at

    @property
    def is_stale(self) -> bool:
        return self.age > _dt.timedelta(hours=STALE_AFTER_HOURS)

    def staleness_note(self) -> str:
        """What to tell the user about how much to trust this.

        INHERITED RULE: a panel that shows stale data confidently is worse
        than one that shows nothing. So anything reading this file must be
        able to say how old it is, and must say so when it is old.
        """
        hours = self.age.total_seconds() / 3600
        if hours < 1:
            return "current"
        if not self.is_stale:
            return f"about {round(hours)} hours old"
        return (f"{round(hours)} hours old -- treat as history, not as the "
                "current situation")


def state_file() -> Path:
    return paths.state_dir() / "working-state.md"


def read_working_state() -> WorkingState | None:
    """Read the working state, or None if there is none yet."""
    path = state_file()
    if not path.exists():
        return None

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    mechanical, _, notes = text.partition(HUMAN_NOTES_MARKER)

    generated = _dt.datetime.fromtimestamp(path.stat().st_mtime)
    match = re.search(r"generated:\s*(\S+)", mechanical)
    if match:
        try:
            generated = _dt.datetime.fromisoformat(match.group(1))
        except ValueError:
            pass

    return WorkingState(
        generated_at=generated,
        open_items=_bullets_under(mechanical, "Open"),
        waiting_on=_bullets_under(mechanical, "Waiting"),
        recent_files=_bullets_under(mechanical, "Recently touched"),
        human_notes=notes.strip(),
    )


def write_working_state(state: WorkingState) -> Path:
    """Rewrite the mechanical half. The human notes are preserved verbatim.

    This is the function that must never lose the notes. It reads them back
    off disk rather than trusting the caller to have carried them, because the
    caller is usually a scheduled job that never read them in the first place.

    **That read is why this takes the lock** (2026-09-01). Reading and writing
    as two steps is safe with one session and only with one session: two
    writers each read, each build their own replacement, and each write it
    successfully -- so the second silently erases the first, with no torn file
    and no error anywhere. `atomic.write_text` cannot help, because nothing
    here is torn; the whole operation has to be one turn. The clone design
    makes this concurrent for the first time, so the bug stops being latent.
    """
    with atomic.lock(state_file()):
        return _write_working_state_locked(state)


def _write_working_state_locked(state: WorkingState) -> Path:
    """The body of a working-state write. The caller must hold the lock.

    Separate from the public function because `append_human_note` needs to
    read and then write inside ONE lock, and the lock is a lock file created
    with O_CREAT|O_EXCL -- taking it twice on the same path deadlocks rather
    than nesting.
    """
    path = state_file()

    existing = read_working_state()
    notes = state.human_notes or (existing.human_notes if existing else "")

    lines = [
        "# Working state",
        "",
        f"generated: {_dt.datetime.now().isoformat(timespec='seconds')}",
        "",
        "This top half is rewritten automatically. Anything you want kept",
        "goes below the marker at the bottom.",
        "",
        "## Open",
    ]
    lines += [f"- {item}" for item in state.open_items] or ["- (nothing)"]
    lines += ["", "## Waiting"]
    lines += [f"- {item}" for item in state.waiting_on] or ["- (nothing)"]
    lines += ["", "## Recently touched"]
    lines += [f"- {item}" for item in state.recent_files] or ["- (nothing)"]
    lines += [
        "",
        HUMAN_NOTES_MARKER,
        "",
        notes or ("_Write here what you are in the middle of and what you "
                  "intended next. This survives every rewrite._"),
        "",
    ]

    return atomic.write_text(path, "\n".join(lines))


def append_human_note(note: str) -> Path:
    """Add to the protected half without disturbing the mechanical half.

    Read and write happen inside one lock. Appending is a read-modify-write in
    its plainest form, and it is the operation with the most to lose: what it
    is appending to is the half of the file nothing else is allowed to touch.
    """
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    addition = f"- {stamp} — {note.strip()}"

    with atomic.lock(state_file()):
        existing = read_working_state()

        if existing is None:
            return _write_working_state_locked(WorkingState(
                generated_at=_dt.datetime.now(), human_notes=addition))

        existing.human_notes = (existing.human_notes + "\n" + addition).strip()
        return _write_working_state_locked(existing)


# ---------------------------------------------------------------------------
# Tier 1, kept — the handoff archive
#
# The working state above is ONE FILE and every write overwrites it. That is
# correct for what it is: a new session needs the current handoff at a known
# path, not a pile of them to choose between. But it means that until now the
# assistant had no history of handing over at all -- each recycle erased the
# account of the one before it, and by the time anybody wanted to look back
# there was exactly one snapshot left, the newest.
#
#
# So this is a fourth kind by the module's own two questions: written at a
# moment, never overwritten, lives for ever, read rarely. It is a copy taken
# at the point of handoff, not a second live state -- nothing reads it to
# find out what is happening now, and nothing should.
#
# NOT WRITTEN BY THE TWENTY-MINUTE CHECKPOINT. That runs 72 times a day and
# almost every run says the same thing; archiving it would bury the handful
# of records that mean something under a day of identical ones. A handoff is
# a session actually changing hands: a recycle, or a person asking for one.
# ---------------------------------------------------------------------------

HANDOFF_SYSTEM = "system"
HANDOFF_MANUAL = "manual"


@dataclass
class Handoff:
    """One saved handoff, as it was written."""

    at: _dt.datetime
    kind: str
    why: str
    name: str
    body: str

    @property
    def by_hand(self) -> bool:
        return self.kind == HANDOFF_MANUAL

    @property
    def detail(self) -> str:
        """The body without its own header lines.

        `at`, `kind` and `why` are how the file is read back; the page shows
        all three in the heading above the panel, so printing them again at
        the top of the panel is the same three facts twice.
        """
        lines = self.body.splitlines()
        keep = [line for line in lines
                if not re.match(r"^(at|kind|why):\s", line)]
        return "\n".join(keep).strip()


def handoff_dir() -> Path:
    return paths.log_dir() / "handoffs"


def record_handoff(state: WorkingState, *, kind: str, why: str) -> Path:
    """Keep this handoff under its own name, for ever.

    The filename carries the timestamp and the kind, so the archive can be
    listed and filtered without opening a single file -- which matters once
    there are a few hundred of them.

    Colons are not legal in a Windows filename, which is why the time is
    written with dashes rather than in ISO form.
    """
    now = _dt.datetime.now()
    directory = handoff_dir()
    directory.mkdir(parents=True, exist_ok=True)

    kind = kind if kind in (HANDOFF_SYSTEM, HANDOFF_MANUAL) else HANDOFF_SYSTEM
    name = f"{now.strftime('%Y-%m-%dT%H-%M-%S')}-{kind}"

    lines = [
        f"at: {now.isoformat(timespec='seconds')}",
        f"kind: {kind}",
        f"why: {why}",
        "",
        "## Open",
    ]
    lines += [f"- {item}" for item in state.open_items] or ["- (nothing)"]
    lines += ["", "## Waiting"]
    lines += [f"- {item}" for item in state.waiting_on] or ["- (nothing)"]
    lines += ["", "## Recently touched"]
    lines += [f"- {item}" for item in state.recent_files] or ["- (nothing)"]

    # The half that is worth keeping. The mechanical lists above can be
    # reconstructed from the workspace at any time; what the session said it
    # was in the middle of cannot.
    if state.human_notes.strip():
        lines += ["", "## Notes", state.human_notes.strip()]

    path = directory / f"{name}.md"
    atomic.write_text(path, "\n".join(lines) + "\n")
    return path


def _handoff_from(path: Path) -> Handoff | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    at = _dt.datetime.fromtimestamp(path.stat().st_mtime)
    match = re.search(r"^at:\s*(\S+)", text, re.MULTILINE)
    if match:
        try:
            at = _dt.datetime.fromisoformat(match.group(1))
        except ValueError:
            pass

    kind = HANDOFF_SYSTEM
    found = re.search(r"^kind:\s*(\w+)", text, re.MULTILINE)
    if found and found.group(1) in (HANDOFF_SYSTEM, HANDOFF_MANUAL):
        kind = found.group(1)

    why = ""
    reason = re.search(r"^why:\s*(.+)$", text, re.MULTILINE)
    if reason:
        why = reason.group(1).strip()

    return Handoff(at=at, kind=kind, why=why, name=path.stem, body=text)


def recent_handoffs(count: int = 50) -> list[Handoff]:
    """Newest first. Sorted by the name, which is the timestamp."""
    directory = handoff_dir()
    if not directory.exists():
        return []

    out: list[Handoff] = []
    for path in sorted(directory.glob("*.md"), reverse=True):
        one = _handoff_from(path)
        if one is not None:
            out.append(one)
        if len(out) >= count:
            break
    return out


def read_handoff(name: str) -> Handoff | None:
    """One handoff by name, or None -- including when the name is a trick.

    The name arrives from a query string. `resolve()` and the parent check
    are what stop `?h=../../../config.yaml` reading the config file, which is
    the same guard the raw-log browser already carries.
    """
    directory = handoff_dir()
    if not directory.exists() or not name:
        return None

    target = (directory / f"{name}.md").resolve()
    if directory.resolve() not in target.parents or not target.is_file():
        return None
    return _handoff_from(target)


def _bullets_under(text: str, heading: str) -> list[str]:
    """Pull the bullet list following a heading."""
    pattern = rf"^#+\s*{re.escape(heading)}.*$"
    lines = text.splitlines()
    collected: list[str] = []
    inside = False

    for line in lines:
        if re.match(pattern, line.strip(), re.IGNORECASE):
            inside = True
            continue
        if inside:
            stripped = line.strip()
            if stripped.startswith("#"):
                break
            if stripped.startswith("- "):
                value = stripped[2:].strip()
                if value and value != "(nothing)":
                    collected.append(value)

    return collected


# ---------------------------------------------------------------------------
# Tier 2 — durable facts
# ---------------------------------------------------------------------------

@dataclass
class Fact:
    """One thing that stays true about this person or their work.

    One fact per file, on purpose. It makes them individually reviewable,
    individually deletable, and diffable — and it means a wrong fact can be
    removed without rewriting a store.
    """

    key: str                      # file-name-safe identifier
    summary: str                  # one line, used when deciding relevance
    body: str = ""
    written_at: _dt.datetime | None = None
    source: str = ""              # how it was learned, in the user's words

    @property
    def path(self) -> Path:
        return paths.memory_dir() / f"{self.key}.md"


def _safe_key(text: str) -> str:
    """Turn a summary into a filename.

    A BUG THAT ONLY BILINGUAL USERS WOULD HAVE HIT
    ----------------------------------------------
    The first version stripped everything outside `[a-z0-9]`. For a fact
    written entirely in Chinese that leaves an empty string, which fell back
    to the literal name "fact" -- so the *second* Chinese fact overwrote the
    first, and the third overwrote that.

    Memories disappeared silently, and only for users who wrote in a
    non-Latin script. Nothing errored. It was found by a search test that
    could not find something that had been written a moment earlier.

    `\\w` with Unicode semantics keeps letters in any script, which is what
    was meant all along. Both Windows and macOS handle such filenames fine.
    """
    key = re.sub(r"[^\w]+", "-", text.lower(), flags=re.UNICODE).strip("-_")
    return (key or "fact")[:60]


def remember(summary: str, body: str = "", key: str | None = None,
             source: str = "") -> Fact:
    """Write down something durable."""
    fact = Fact(
        key=key or _safe_key(summary),
        summary=summary.strip(),
        body=body.strip(),
        written_at=_dt.datetime.now(),
        source=source.strip(),
    )

    lines = [
        "---",
        f"summary: {secrets.redact(fact.summary)}",
        f"written: {fact.written_at.isoformat(timespec='seconds')}",
    ]
    if fact.source:
        lines.append(f"source: {fact.source}")
    lines += ["---", "", secrets.redact(fact.body or fact.summary), ""]

    paths.memory_dir().mkdir(parents=True, exist_ok=True)
    atomic.write_text(fact.path, "\n".join(lines))
    return fact


def recall(query: str = "", limit: int = 20) -> list[Fact]:
    """Find facts whose summary or body mentions the query.

    Plain substring matching over a small set of files. No embeddings, no
    index, no database.

    That is a deliberate choice, not a shortcut: a personal fact store is
    hundreds of files, not millions, and a student can open the folder and
    read it. When it stops being fast enough, that is the moment to add an
    index — and not before, because an index nobody can inspect is a memory
    system nobody can debug.
    """
    directory = paths.memory_dir()
    if not directory.exists():
        return []

    needle = query.strip().casefold()
    found: list[Fact] = []

    for path in sorted(directory.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if needle and needle not in text.casefold():
            continue

        summary = ""
        match = re.search(r"^summary:\s*(.+)$", text, re.MULTILINE)
        if match:
            summary = match.group(1).strip()

        body = text.split("---", 2)[-1].strip()

        found.append(Fact(
            key=path.stem,
            summary=summary or path.stem,
            body=body,
            written_at=_dt.datetime.fromtimestamp(path.stat().st_mtime),
        ))
        if len(found) >= limit:
            break

    return found


def search(query: str, limit: int = 10) -> list[tuple[float, Fact]]:
    """Rank facts by how well they match, not just whether they contain a word.

    WHY NOT EMBEDDINGS
    ------------------
    Semantic search with a local embedding model is better at this. It also
    means a model download of several hundred megabytes, a dependency that
    needs compiling on some machines, and a first run that appears to hang.
    For a non-developer installing this in under fifteen minutes, that trade
    is wrong.

    So this is **BM25**, the ranking function behind most classical search
    engines. Written out in about thirty lines of arithmetic, no dependency,
    instant, and — the part that matters for teaching — you can read it and
    see exactly why a result ranked where it did.

    What it does that plain substring matching does not:
      * ranks by relevance instead of returning everything or nothing
      * a rare word counts for more than a common one
      * a short fact mentioning the word twice beats a long one mentioning it
        once

    What it still cannot do: match "car" to "vehicle". That needs embeddings,
    and when a user's memory is large enough for that to matter, it will be
    obvious — and adding it then is a small change, because everything else
    goes through this one function.

    **It was a small change, and it is at the bottom of this function.**
    The maintainer asked for meaning-matching as an option (2026-08-20) and chose to
    have it default to off. So BM25 above is still what runs for everybody;
    `semantic` adds to the end of the list, only when switched on, and only
    with notes the word search did not already find. Nothing here is replaced
    — an assistant that quietly stops matching words because a model thought
    otherwise is one nobody can predict.
    """
    import math
    from collections import Counter

    terms = _tokenise(query)
    if not terms:
        return []

    facts = recall(limit=10_000)
    if not facts:
        return []

    documents = [_tokenise(f"{fact.summary} {fact.body}") for fact in facts]
    lengths = [len(document) for document in documents]
    average_length = sum(lengths) / len(lengths) if lengths else 1.0

    # How many documents contain each term.
    containing = Counter()
    for document in documents:
        for term in set(document):
            containing[term] += 1

    total = len(documents)
    k1, b = 1.5, 0.75      # the standard BM25 constants

    scored: list[tuple[float, Fact]] = []
    for fact, document, length in zip(facts, documents, lengths):
        counts = Counter(document)
        score = 0.0
        for term in terms:
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            # Rarer terms are worth more. This is the part plain substring
            # matching has no way to express.
            rarity = math.log(
                1 + (total - containing[term] + 0.5) / (containing[term] + 0.5)
            )
            normalised = frequency * (k1 + 1) / (
                frequency + k1 * (1 - b + b * length / (average_length or 1))
            )
            score += rarity * normalised

        if score > 0:
            scored.append((score, fact))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    ranked = scored[:limit]
    return _with_meaning_matches(query, ranked, limit)


def _with_meaning_matches(query, ranked, limit):
    """Append notes that mean the same thing, when that is switched on.

    Added, never substituted, and only for notes the word search missed --
    so turning the option on can surface something extra but can never take
    away a result somebody was relying on.

    Each one carries its similarity score rather than being blended into the
    BM25 numbers, because the two are not the same measurement and adding
    them together would produce a ranking nobody could explain.
    """
    from . import semantic

    if not semantic.enabled():
        return ranked

    already = {fact.key for _score, fact in ranked}
    room = max(0, limit - len(ranked))
    if not room:
        return ranked

    extra = []
    for match in semantic.search(query, limit=room):
        if match.key in already:
            continue
        for fact in recall(limit=10_000):
            if fact.key == match.key:
                extra.append((match.score, fact))
                break
    return ranked + extra
def _tokenise(text: str) -> list[str]:
    """Split text into comparable words.

    Handles CJK by treating each character as its own token, because Chinese
    and Japanese do not put spaces between words. Without this, a bilingual
    user's memory would be searchable in English only — which for this user
    base is most of the point missed.
    """
    tokens: list[str] = []
    current: list[str] = []

    for character in text.casefold():
        if "一" <= character <= "鿿" or "぀" <= character <= "ヿ":
            if current:
                tokens.append("".join(current))
                current = []
            tokens.append(character)
        elif character.isalnum():
            current.append(character)
        else:
            if current:
                tokens.append("".join(current))
                current = []

    if current:
        tokens.append("".join(current))

    return [token for token in tokens if len(token) > 1
            or not token.isascii()]


def forget(key: str) -> bool:
    """Delete a fact. Returns True if there was one.

    Forgetting is a first-class operation. A memory store you cannot correct
    accumulates confident wrong answers, and a wrong fact repeated is worse
    than a fact never recorded.
    """
    path = paths.memory_dir() / f"{key}.md"
    if not path.exists():
        return False
    path.unlink()
    return True


# ---------------------------------------------------------------------------
# Tier 3 — daily narrative
# ---------------------------------------------------------------------------

def daily_path(day: _dt.date | None = None) -> Path:
    day = day or _dt.date.today()
    return paths.log_dir() / "daily" / f"{day.isoformat()}.md"


def log_event(text: str, day: _dt.date | None = None) -> Path:
    """Append one line to today's narrative.

    Append-only. Nothing here is ever rewritten, which is what makes it
    trustworthy later: if it says something happened at 14:03, it did, and
    nothing has tidied it since.
    """
    path = daily_path(day)
    stamp = _dt.datetime.now().strftime("%H:%M")

    if not path.exists():
        header = (f"# {(day or _dt.date.today()).strftime('%A %d %B %Y')}\n")
        atomic.write_text(path, header)

    # Redacted, like every other thing this package writes down.
    #
    # It was not, and the day's narrative is exactly the file where a
    # credential ends up by accident: everything that happens gets a line
    # here, including the line about connecting a mailbox. Meanwhile the
    # house-rules page badged any rule mentioning "password" as enforced in
    # code by `secrets.redact`, naming a function this module did not import.
    atomic.append_line(path, f"- {stamp} {secrets.redact(text.strip())}")
    return path


def log_entry(title: str, body: str, day: _dt.date | None = None) -> Path:
    """Append a written passage — not a one-line event — to today's narrative.

    `log_event` records that something happened. This records what was said
    about it, which is a different shape: several lines, kept as they were
    written, under a heading and a time.

    It exists because the evening wrap-up had no way to save its own work. It
    was asked to write the day's entry, a headless run cannot be granted a
    write, and so for months the file held a list of task timings and none of
    the account they were timings of. The assistant writes the words; this
    saves them. Nothing is granted to anybody.
    """
    path = daily_path(day)
    stamp = _dt.datetime.now().strftime("%H:%M")

    if not path.exists():
        header = f"# {(day or _dt.date.today()).strftime('%A %d %B %Y')}\n"
        atomic.write_text(path, header)

    passage = secrets.redact(body.strip())
    if not passage:
        return path

    atomic.append_line(path, "")
    atomic.append_line(path, f"## {stamp} {title.strip()}")
    atomic.append_line(path, "")
    for line in passage.splitlines():
        atomic.append_line(path, line)
    return path


@dataclass
class DayEntry:
    """One written passage from a day file — a wrap-up, usually."""

    at: str
    title: str
    body: str


def split_day(text: str) -> tuple[list[DayEntry], list[str]]:
    """A day file, separated into what was written and what merely happened.

    The two live in one file and are written by two functions. `log_entry`
    adds `## HH:MM Title` and a passage; `log_event` adds a `- HH:MM ...`
    line. Reading the file straight out, as the dashboard did, puts the
    wrap-up somebody came to read underneath a hundred lines of task timings
    -- which on a day with ten recycles means it is off the bottom of the
    panel.

    So the passages come out separately, and the timings stay
    available rather than in the way.
    """
    entries: list[DayEntry] = []
    events: list[str] = []
    current: DayEntry | None = None

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            at, _, title = heading.partition(" ")
            # A heading whose first word is not a time is still a heading;
            # it just has no time to show.
            if not re.fullmatch(r"\d{1,2}:\d{2}", at):
                at, title = "", heading
            current = DayEntry(at=at, title=title.strip(), body="")
            entries.append(current)
            continue

        if stripped.startswith("# "):
            # The file's own date heading. Neither of the two.
            current = None
            continue

        # An event line is an event line wherever it appears -- INCLUDING
        # below a heading. The day does not stop when the wrap-up is
        # written: every recycle after it appends another `- HH:MM ...`
        # underneath, and a parser that only looked at the top of the file
        # swallowed all of them into the wrap-up passage. Found by a test
        # that logged one event, wrote the entry, and logged another.
        #
        # `- HH:MM ` and not merely `- ` is what tells them apart: that is
        # the shape `log_event` writes, and a wrap-up is entitled to start a
        # line with a dash.
        if re.match(r"-\s+\d{1,2}:\d{2}\s", stripped):
            events.append(stripped[2:].strip())
            continue

        if current is not None:
            current.body += line + "\n"

    for one in entries:
        one.body = one.body.strip()
    return [one for one in entries if one.body], events


def logged_days() -> set[_dt.date]:
    """Which days have a narrative at all — from the filenames alone.

    The calendar needs to mark the days worth clicking, and `recent_days`
    would answer that by reading every file on disk to decide whether to
    show a dot on a grid. One `glob` and a date parse is the whole job.
    """
    directory = paths.log_dir() / "daily"
    if not directory.exists():
        return set()

    found: set[_dt.date] = set()
    for path in directory.glob("*.md"):
        try:
            found.add(_dt.date.fromisoformat(path.stem))
        except ValueError:
            continue
    return found


def read_day(day: _dt.date | None = None) -> str:
    path = daily_path(day)
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def recent_days(count: int = 7) -> list[tuple[_dt.date, str]]:
    """The last `count` days that have a narrative, newest first."""
    directory = paths.log_dir() / "daily"
    if not directory.exists():
        return []

    entries: list[tuple[_dt.date, str]] = []
    for path in sorted(directory.glob("*.md"), reverse=True):
        try:
            day = _dt.date.fromisoformat(path.stem)
        except ValueError:
            continue
        try:
            entries.append((day, path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
        if len(entries) >= count:
            break

    return entries
