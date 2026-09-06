"""Searching what you and the assistant have actually said to each other.

WHY THIS EXISTS
---------------
`memory` searches what the assistant WROTE DOWN. This searches what was SAID.
They are not the same thing, and the gap between them is where most of a
working relationship lives: the reason a decision went the way it did, the
thing that was tried and abandoned, the number somebody quoted in passing.
None of that becomes a memory note, and until now none of it could be found
again -- Claude Code writes every session to disk and offers no way to look
inside one.

WHY IT NEEDS NOTHING INSTALLED
------------------------------
This runs on somebody else's laptop. Anything needing a server, a model
download or an API key is a feature that works on the machine it was built on
and nowhere else. SQLite ships with Python, FTS5 is compiled into the standard
build, and the whole index is one file.

WHY TRIGRAM
-----------
FTS5's default tokenizer splits on spaces, so a sentence written in Chinese --
which has none -- becomes one token and searching for a word inside it finds
nothing. `tokenize='trigram'` indexes every run of three characters instead.
The cost is that it does not know where words end: `Day 2` also matches
`Sunday 23rd`. That is why every result carries its surrounding words.

WHAT IS INDEXED, AND WHAT DELIBERATELY IS NOT
---------------------------------------------
Only sessions started inside this person's own workspace. Claude Code keeps
every project's transcripts under one folder, so an index that took all of
them would quietly pull in whatever else they use Claude Code for -- their
employer's code, somebody else's client work. Their assistant has no business
reading that, and a search that surfaces it once has already done the damage.

Only speech: what they typed and what the assistant said back. Tool results and
file contents are the overwhelming majority of the bytes and almost none of the
meaning.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import sqlite3
from pathlib import Path

from . import paths

TRANSCRIPT_ROOT = Path(".claude") / "projects"

# Bump this whenever what counts as speech changes -- a new marker in
# NOT_SPEECH, a change to what gets unwrapped, a different set of records read.
#
# Without it the index is a record of the rules that applied when each line was
# first read, and since reading is incremental those rules never get revisited.
# That is not theoretical: the filter that drops a sub-agent's system prompt
# was added, shipped, installed, and the Surface went on reporting that the maintainer
# asks to be David 23 times -- because those rows had been indexed the day
# before and nothing was going to look at them again. A fix that only applies
# to lines nobody has read yet is not a fix.
RULES = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS said USING fts5(
    text,
    role UNINDEXED,
    stamp UNINDEXED,
    session UNINDEXED,
    tokenize='trigram'
);
CREATE TABLE IF NOT EXISTS sources (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    offset INTEGER NOT NULL
);
"""


def database() -> Path:
    return paths.app_dir() / "state" / "conversations.db"


def _spoken(record: dict) -> str:
    """The words in one transcript record, or "" if it carries none.

    A person's turn is a plain string; the assistant's is a list of blocks, of
    which only `text` is speech. `tool_use` is an instruction to a machine and
    `thinking` is addressed to nobody.
    """
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text") or ""
            for block in content
            if isinstance(block, dict) and block.get("type") == "text")
    return ""


# A `user` record is not always a person talking. Claude Code files several
# other things under the same type: the system prompt handed to a sub-agent,
# the marker for a slash command, a skill's preamble, its own reminders. All
# of them read as fluent first-person text, so nothing downstream can tell
# them apart -- and left in, the first thing a search for "assistant" returns
# is the machine talking to itself, and a feature that counts what somebody
# keeps asking for concludes they ask to be David ninety-nine times.
NOT_SPEECH = (
    "you are ",
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<local-command-caveat>",
    "<system-reminder>",
    "base directory for this skill",
    "caveat: the messages below",
    # The harness writing to itself. Filed as `user` records like the rest,
    # and the most repetitive text on the machine -- so left in, they are the
    # first thing a habit-finder decides somebody keeps asking for. The
    # Surface offered "interrupted request tool use, 3 times" as a skill.
    "[request interrupted by user",
    "[your previous response had no visible output",
)

# The channel wrapper IS a person -- it is how a message from Telegram
# arrives -- so the envelope is removed and the words inside are kept.
_CHANNEL = re.compile(r"</?channel\b[^>]*>", re.IGNORECASE)


def _is_speech(text: str) -> bool:
    head = text.lstrip().lower()[:160]
    return not any(mark in head for mark in NOT_SPEECH)


def _carries_a_secret(text: str) -> bool:
    """Whether this line looks like it contains a credential.

    People paste keys into chat. It is not careless -- it is how you give an
    assistant a token -- but it means an index of everything said is also an
    index of everything pasted, and this one is read back out loud: a
    suggestion, a search result, a screen shared in a classroom. The Surface
    printed the maintainer's real Telegram bot token as a skill suggestion before this
    existed.

    Refused rather than redacted. A redaction has to be right every time; a
    refusal only has to be right once, and nobody searches their own
    conversations to recover a key -- the password manager holds it.
    """
    from . import secrets

    try:
        return bool(secrets.scan_for_committed_secrets(text))
    except Exception:                                     # noqa: BLE001
        # A scanner that errors must not become a scanner that passes
        # everything. Keeping the line out is the safe direction.
        return True


def _unwrap(text: str) -> str:
    return _CHANNEL.sub(" ", text).strip()


def _inside(cwd: str, root: Path | None) -> bool:
    """Was this session started inside the workspace?

    Read from the record rather than from the folder name: Claude Code names
    its project folders after a mangled path, and reconstructing a real path
    from one of those is guesswork. Every record states its own `cwd`.
    """
    if root is None or not cwd:
        return False
    try:
        Path(cwd).resolve().relative_to(Path(root).resolve())
    except (ValueError, OSError):
        return False
    return True


def _new_lines(path: Path, offset: int, root: Path | None):
    """Yield (stamp, role, text, position) for speech after `offset`."""
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            while True:
                line = handle.readline()
                if not line:
                    return
                # `readline` and `tell`, never iteration: iterating a text file
                # disables `tell()` and raises, which reads as "this file is
                # unreadable" and produces a confidently empty index.
                position = handle.tell()
                try:
                    record = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if record.get("type") not in ("user", "assistant"):
                    continue
                if not _inside(str(record.get("cwd") or ""), root):
                    continue
                said = _unwrap(_spoken(record))
                if not said or not _is_speech(said):
                    continue
                if _carries_a_secret(said):
                    continue
                yield (record.get("timestamp") or "", record["type"], said,
                       position)
    except OSError:                                       # pragma: no cover
        return


def refresh(root: Path | None = None) -> dict:
    """Fold anything new into the index. Cheap enough to run on every cycle.

    Incremental by remembered offset, the same way the usage meter reads these
    files: re-reading gigabytes to answer one question is how a feature becomes
    the slowest thing in the product.
    """
    if root is None:
        from . import config as config_module
        try:
            root = config_module.load().layout.root
        except Exception:                                 # noqa: BLE001
            root = None

    target = database()
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target)
    try:
        db.executescript(SCHEMA)

        # Rebuilding is one slow pass, once. Keeping rows that were admitted
        # under rules that no longer hold is wrong for ever, and invisibly so.
        stored = db.execute(
            "SELECT value FROM meta WHERE key = 'rules'").fetchone()
        if (stored[0] if stored else "") != str(RULES):
            db.execute("DELETE FROM said")
            db.execute("DELETE FROM sources")
            db.execute("INSERT OR REPLACE INTO meta (key, value)"
                       " VALUES ('rules', ?)", (str(RULES),))

        known = {row[0]: (row[1], row[2])
                 for row in db.execute("SELECT path, size, offset FROM sources")}

        added = 0
        folder = paths.home() / TRANSCRIPT_ROOT
        found = sorted(folder.glob("*/*.jsonl")) if folder.is_dir() else []
        for path in found:
            key = str(path)
            try:
                size = path.stat().st_size
            except OSError:                               # pragma: no cover
                continue

            offset = 0
            if key in known:
                seen_size, seen_offset = known[key]
                # A file that shrank was rewritten, so what is remembered about
                # it describes a different file wearing the same name.
                offset = seen_offset if size >= seen_size else 0
                if size == seen_size and offset >= size:
                    continue

            rows = []
            for stamp, role, said, position in _new_lines(path, offset, root):
                rows.append((said, role, stamp, path.stem))
                offset = position
            if rows:
                db.executemany("INSERT INTO said (text, role, stamp, session)"
                               " VALUES (?, ?, ?, ?)", rows)
                added += len(rows)
            db.execute("INSERT OR REPLACE INTO sources (path, size, offset)"
                       " VALUES (?, ?, ?)", (key, size, offset))

        db.commit()
        total = db.execute("SELECT count(*) FROM said").fetchone()[0]
    finally:
        db.close()
    return {"added": added, "total": total}


def recent(days: int = 30, role: str = "", limit: int = 2000) -> list[dict]:
    """Everything said in the last `days`, newest first.

    Separate from `search` because it answers a different question -- not
    "where did we discuss X" but "what has been going on" -- and the caller
    that needs it (skill proposals) has no search term to give.
    """
    target = database()
    if not target.exists():
        return []
    cutoff = (_dt.datetime.now(_dt.timezone.utc)
              - _dt.timedelta(days=max(1, days))).isoformat()

    db = sqlite3.connect(target)
    try:
        sql = ["SELECT stamp, role, session, text FROM said WHERE stamp >= ?"]
        args: list = [cutoff]
        if role:
            sql.append("AND role = ?")
            args.append(role)
        sql.append("ORDER BY stamp DESC LIMIT ?")
        args.append(max(1, limit))
        rows = db.execute(" ".join(sql), args).fetchall()
    finally:
        db.close()

    return [{"stamp": stamp, "role": said_by, "session": session,
             "said": " ".join((text or "").split())}
            for stamp, said_by, session, text in rows]


def _as_one_phrase(term: str) -> str:
    """Hand FTS5 a quoted string rather than an expression.

    Somebody searching for `--fix` or `a AND b` is typing what they remember,
    not writing a query language, and unquoted both are syntax errors rather
    than empty results. Doubling the quote is FTS5's own escape.
    """
    return '"' + term.replace('"', '""') + '"'


def search(term: str, limit: int = 10, days: int = 0) -> list[dict]:
    """Matches, newest first. An empty list means nothing matched."""
    term = (term or "").strip()
    if not term:
        return []
    target = database()
    if not target.exists():
        return []

    # Trigram indexes runs of THREE characters, so a two-character query --
    # which in Chinese is an ordinary word, not an abbreviation (報告, 問題,
    # 時間) -- matches nothing and reports it as "we never discussed that".
    # Short queries fall back to a plain scan. On one person's own
    # conversations that is thousands of rows, not millions, and a correct
    # answer in a few milliseconds beats an instant wrong one.
    short = len(term) < 3

    db = sqlite3.connect(target)
    try:
        sql = ["SELECT stamp, role, session,"
               " snippet(said, 0, '[', ']', ' ... ', 24)"
               " FROM said WHERE said MATCH ?"]
        args: list = [_as_one_phrase(term)]
        if short:
            # `snippet()` needs a MATCH to point at, so the scan returns the
            # whole line and the caller trims it. `%` and `_` are wildcards in
            # LIKE, so a search for a literal one is escaped rather than
            # quietly matching everything.
            sql = ["SELECT stamp, role, session, text"
                   " FROM said WHERE text LIKE ? ESCAPE '~'"]
            escaped = (term.replace("~", "~~")
                       .replace("%", "~%").replace("_", "~_"))
            args = ["%" + escaped + "%"]
        if days:
            cutoff = (_dt.datetime.now(_dt.timezone.utc)
                      - _dt.timedelta(days=days)).isoformat()
            sql.append("AND stamp >= ?")
            args.append(cutoff)
        sql.append("ORDER BY stamp DESC LIMIT ?")
        args.append(max(1, limit))
        try:
            rows = db.execute(" ".join(sql), args).fetchall()
        except sqlite3.OperationalError:
            # A malformed FTS expression is a search that found nothing, not a
            # crash for somebody to decipher.
            return []
    finally:
        db.close()

    return [{"stamp": stamp, "role": role, "session": session,
             "said": " ".join((snippet or "").split())}
            for stamp, role, session, snippet in rows]
