"""Writing files safely, and taking a lock, the same way on both platforms.

TWO INHERITED BUGS ARE FIXED HERE
---------------------------------

**1. Torn reads.** The source system wrote state files by opening them for
writing and printing into them. Other processes read those files on a
schedule. A reader that arrived mid-write got half a file, threw an exception,
and — because the thing that threw was a message sender — silently dropped the
message it was about to send. Nobody noticed for a while, which is the worst
kind of bug.

The fix is old and boring: build the complete replacement somewhere else, then
rename it into place. Rename is atomic on Windows and macOS both, so a reader
sees either the whole old file or the whole new one. Never truncate the live
file before the replacement has been written successfully.

**2. Locking that was not there.** The source guarded its file-locking import
inside a try/except so the code would run everywhere. It ran everywhere by
locking nowhere — on the platform it actually ran on, the import failed and
locking was silently skipped for the life of the system.

That is worse than having no locking at all, because the code *looks* locked.

So this module uses ONE mechanism that behaves identically on Windows and
macOS: an exclusive lock *file*, created with O_CREAT|O_EXCL, which is atomic
on both. No `fcntl`, no `msvcrt`, no import that can quietly fail. If the lock
cannot be taken, you get an exception — never a silent pass.
"""

from __future__ import annotations

import errno
import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

# How long before a lock left behind by a crashed process is considered dead.
# Long enough that a slow write is never stolen from, short enough that a
# crash does not wedge the system until someone notices.
STALE_LOCK_SECONDS = 120


class LockTimeout(Exception):
    """Raised when a lock could not be taken in time.

    Deliberately an exception rather than a silent skip. A caller that cannot
    take the lock must decide what to do; it must never carry on as though it
    had.
    """


# ---------------------------------------------------------------------------
# Atomic writing
# ---------------------------------------------------------------------------

def _replace_retrying(temporary: Path, path: Path, tries: int = 6) -> None:
    """Rename over the target, retrying while Windows says no.

    On Windows a rename fails outright if ANY process holds a handle to
    either file, and on a real machine something usually does for a few
    milliseconds after a file is created: Defender scanning it, the search
    indexer, a backup agent, Google Drive. It comes back as WinError 5
    (access denied) or WinError 32 (in use), and it is transient -- the very
    next attempt succeeds.

    Found 2026-08-24: a test that saves an approval failed roughly one run in
    nine, always here, always with WinError 5. On a laptop that is not a flaky
    test, it is the assistant losing somebody's answer and saying it saved it.

    Bounded on purpose. A genuine permissions problem -- a read-only folder,
    a file owned by another account -- must still surface rather than being
    retried into a hang; six attempts over about a fifth of a second covers a
    scanner and gives up on anything real.
    """
    delay = 0.01
    for attempt in range(tries):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(delay)
            delay *= 2


def write_text(path: Path, text: str, encoding: str = "utf-8") -> Path:
    """Replace a file's contents atomically.

    The temporary file is created in the same directory as the target, which
    matters: rename is only atomic within a filesystem, and the system
    temporary directory is often on a different one.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Include the process id AND the thread id, so two writers at once cannot
    # collide on the temporary name itself.
    #
    # The thread half was missing until 2026-08-23 and it bit the moment
    # anything wrote from a background thread: two threads in one process
    # share a pid, so both built `.approvals.json.59272.tmp`, and the second
    # `replace` failed with "the process cannot access the file because it is
    # being used by another process". On Windows that is an outright error;
    # on macOS it would have been the quieter outcome of one thread's data
    # silently winning.
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")

    try:
        with temporary.open("w", encoding=encoding, newline="\n") as handle:
            handle.write(text)
            # Push it to disk before the rename. Without this, a power loss
            # between rename and flush can leave a correctly-named empty file,
            # which is the one outcome worse than the old contents surviving.
            handle.flush()
            os.fsync(handle.fileno())

        _replace_retrying(temporary, path)
    finally:
        # If anything above failed, do not leave debris behind.
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass

    return path


def write_json(path: Path, data: Any, indent: int = 2) -> Path:
    return write_text(path, json.dumps(data, indent=indent,
                                       ensure_ascii=False) + "\n")


class Unreadable(Exception):
    """The file is there, and we could not find out what is in it.

    Distinct from "not there", which is an ordinary answer. This one means a
    caller about to rewrite the file must stop, because it does not know what
    it is about to replace.
    """


# What a quarantined file is called. Dated, so a second corruption does not
# overwrite the evidence from the first.
QUARANTINE_MARK = ".unreadable-"


def _quarantine(path: Path) -> Path | None:
    """Move a corrupt file aside, keeping its bytes. Returns where it went.

    Called at the one moment we know the file is broken. Renaming it does two
    things at once: the next read finds nothing and starts clean, and the
    original bytes survive the write that would otherwise have flattened them.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    kept = path.with_name(f"{path.name}{QUARANTINE_MARK}{stamp}")

    # Seconds are not fine enough. Two corruptions inside the same second --
    # which is exactly what a repeated read of a broken file produces -- landed
    # on the same name, and `replace` overwrote the first rescue with the
    # second. The whole point of a dated name is that the evidence
    # accumulates, so it must never collide with itself.
    if kept.exists():
        for nth in range(2, 100):
            candidate = kept.with_name(f"{kept.name}-{nth}")
            if not candidate.exists():
                kept = candidate
                break
        else:
            return None     # a hundred in one second: something else is wrong

    try:
        path.replace(kept)
        return kept
    except OSError:
        # Could not move it. Say so rather than reporting a rescue that did
        # not happen -- the caller decides what to do with that.
        return None


def quarantined(folder: Path) -> list[Path]:
    """Every file moved aside because it could not be read.

    `read_json`'s docstring has always said the user "gets told by doctor".
    This is what doctor asks. Before it existed, that sentence was a promise
    with nothing behind it: a file was silently replaced by its default and
    nobody ever heard about it.
    """
    folder = Path(folder)
    if not folder.exists():
        return []
    return sorted(one for one in folder.rglob(f"*{QUARANTINE_MARK}*")
                  if one.is_file())


def read_json(path: Path, default: Any = None) -> Any:
    """Read JSON, returning `default` if the file is missing or unreadable.

    A corrupt state file must not stop the software starting. The caller gets
    the default and the user gets told by `doctor` — that is a better failure
    than a crash on launch that a non-developer cannot interpret.

    **What was wrong with that, until 2026-08-23.** Most callers here read a
    list, change it, and write it back. Returning `default` for an unreadable
    file made "corrupt" indistinguishable from "empty", so the very next write
    replaced the real contents with an empty structure — permanently, with no
    backup anywhere. A single bad byte in `held.json` silently discarded every
    held message; the same shape existed in the schedule, the quiet modes and
    the pending conversation queue.

    So a file that is present but unparseable is now moved aside first. The
    caller still gets its default and still starts, and the bytes are still
    there to be recovered from.

    A transient `OSError` is treated differently and deliberately: a file
    briefly locked by a backup agent or a virus scanner is not corrupt, and
    moving it aside would turn a hiccup into a loss. Read-modify-write callers
    want `read_json_for_update`, which refuses to guess in that case.
    """
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        _quarantine(path)
        return default
    except OSError:
        return default


def read_json_for_update(path: Path, default: Any = None) -> Any:
    """Read JSON for a caller that is about to write the file back.

    Same as `read_json` for the two answers it can give honestly — the file is
    absent, so here is the default; the file is corrupt, so it has been moved
    aside and here is the default.

    It raises `Unreadable` for the third case, where the file exists and the
    read failed for a reason that says nothing about its contents. Returning a
    default there would let the caller write an empty structure over data that
    is probably perfectly fine.
    """
    path = Path(path)
    if not path.exists():
        return default

    # Tried a few times before giving up. On Windows the common cause of an
    # OSError on a small file that exists is somebody else holding it for an
    # instant -- a backup agent, an indexer, a virus scanner, or our own
    # `write_text` between its rename and the old handle closing. Raising on
    # the first attempt would turn a routine hiccup into an error page.
    last: OSError | None = None
    for attempt in range(3):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            _quarantine(path)
            return default
        except OSError as exc:
            last = exc
            time.sleep(0.05 * (attempt + 1))

    raise Unreadable(
        f"{path.name} could not be read, and it is still there. Nothing has "
        "been changed — writing now would replace contents we were unable to "
        "see."
    ) from last


def append_line(path: Path, line: str, encoding: str = "utf-8") -> None:
    """Append one line to a log, under the file's lock.

    Append mode alone is *nearly* safe for short lines on both platforms, and
    "nearly" is what produced interleaved half-lines in the source system's
    logs. Taking the lock costs microseconds and removes the doubt.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with lock(path):
        with path.open("a", encoding=encoding, newline="\n") as handle:
            handle.write(line.rstrip("\n") + "\n")


# ---------------------------------------------------------------------------
# Logs that must not grow for ever, or be read whole to see the end of them
# ---------------------------------------------------------------------------
#
# `events.jsonl` and `conversation.jsonl` are append-only and had neither a
# trim nor a tail-read. Both were loaded entirely into memory to show the last
# twenty lines, on a page that draws on every dashboard load — so the cost of
# looking at today grew with everything that had ever happened, without limit
# and without anything ever saying so.

# Read at most this much from the end when tailing. Generous next to any
# realistic line, small enough that the read is one seek.
TAIL_CHUNK = 65_536


def tail_lines(path: Path, limit: int, encoding: str = "utf-8") -> list[str]:
    """The last `limit` lines, without reading what comes before them.

    Falls back to a whole read only for a file small enough that it makes no
    difference. Decoding errors are replaced rather than raised: a log is for
    looking at, and one bad byte in the middle must not hide the rest.
    """
    path = Path(path)
    if limit <= 0 or not path.exists():
        return []

    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            # Grow the window until it holds enough newlines, or we reach the
            # start of the file. Doubling keeps this to a couple of reads even
            # when the lines are unusually long.
            window = TAIL_CHUNK
            while True:
                start = max(0, size - window)
                handle.seek(start)
                blob = handle.read(size - start)
                if start == 0 or blob.count(b"\n") > limit:
                    break
                window *= 2

        text = blob.decode(encoding, errors="replace")
        if start > 0:
            # The first line in the window is almost certainly a fragment.
            text = text.split("\n", 1)[1] if "\n" in text else ""
        return text.splitlines()[-limit:]
    except OSError:
        return []


def trim_log(path: Path, keep_lines: int, max_bytes: int) -> int:
    """Shorten an append-only log to its last `keep_lines`. Returns how many
    lines were dropped.

    Does nothing until the file is over `max_bytes`, so the usual call is one
    `stat`. When it does act, the survivors are written through the same
    atomic replace as everything else: the old file stays whole and readable
    right up to the instant the new one takes its place, so a reader arriving
    mid-trim never sees a half log.
    """
    path = Path(path)
    try:
        if not path.exists() or path.stat().st_size <= max_bytes:
            return 0
    except OSError:
        return 0

    try:
        with lock(path, timeout=2.0):
            lines = path.read_text(encoding="utf-8",
                                   errors="replace").splitlines()
            if len(lines) <= keep_lines:
                return 0
            dropped = len(lines) - keep_lines
            write_text(path, "\n".join(lines[-keep_lines:]) + "\n")
            return dropped
    except (LockTimeout, OSError):
        # Somebody else is writing it. Trimming is housekeeping; it can wait
        # for the next append, and must never be the reason one fails.
        return 0


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------

def _lock_path(target: Path) -> Path:
    return Path(target).with_name(Path(target).name + ".lock")


# How long to wait before retrying a contended lock, and the ceiling.
#
# The first version used a flat 50ms. That was far too coarse: these locks are
# held for microseconds, so a flat poll meant at most ~20 acquisitions per
# second across the whole process, and four threads appending to one log
# exhausted a ten-second timeout on work that should take milliseconds.
#
# The symptom in real use would not have been a test failure. It would have
# been an assistant that felt inexplicably sluggish whenever two things
# happened at once, which is much harder to diagnose than an outright error.
#
# So: start very small, back off gently, cap it.
FIRST_RETRY_SECONDS = 0.0005
RETRY_GROWTH = 1.6
MAX_RETRY_SECONDS = 0.02


@contextmanager
def lock(target: Path, timeout: float = 10.0,
         poll: float | None = None) -> Iterator[None]:
    """Hold an exclusive lock on `target` for the duration of the block.

    Implemented as a lock file created with O_CREAT|O_EXCL, which is an atomic
    "create only if it does not exist" on both Windows and macOS. Whoever wins
    the create owns the lock.

    The lock file records the owning process id and the time it was taken, so
    that a lock abandoned by a crashed process can be identified and broken
    rather than blocking forever.
    """
    lock_file = _lock_path(target)
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    deadline = time.monotonic() + timeout
    acquired = False
    wait = poll if poll is not None else FIRST_RETRY_SECONDS

    while True:
        try:
            descriptor = os.open(lock_file,
                                 os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "pid": os.getpid(),
                    "taken_at": time.time(),
                }))
            acquired = True
            break

        except FileExistsError:
            if _break_if_stale(lock_file):
                continue        # the previous owner is gone; try again

            if time.monotonic() >= deadline:
                raise LockTimeout(
                    f"Could not take the lock on {Path(target).name} within "
                    f"{timeout:g} seconds. Another part of the assistant is "
                    "still writing it."
                )
            time.sleep(wait)
            wait = min(wait * RETRY_GROWTH, MAX_RETRY_SECONDS)

        except OSError as exc:
            if exc.errno == errno.EACCES:
                # On Windows a file can be briefly inaccessible while being
                # replaced. Treat it like contention rather than a hard error.
                if time.monotonic() >= deadline:
                    raise LockTimeout(
                        f"Could not take the lock on {Path(target).name}: "
                        "permission denied."
                    ) from exc
                time.sleep(wait)
                wait = min(wait * RETRY_GROWTH, MAX_RETRY_SECONDS)
                continue
            raise

    try:
        yield
    finally:
        if acquired:
            _release(lock_file)


def _release(lock_file: Path) -> None:
    """Delete the lock file, retrying briefly.

    On Windows a delete can fail transiently -- an indexer, a virus scanner or
    a backup agent may have the file open for an instant. A single attempt
    that silently gives up leaves the lock held forever, which is how a
    momentary hiccup becomes a permanent deadlock.

    So: retry for a moment. And if it still will not go, do not raise -- this
    runs in a `finally` block, and raising here would mask whatever the caller
    was actually doing. The staleness check is the backstop.
    """
    for attempt in range(10):
        try:
            lock_file.unlink()
            return
        except FileNotFoundError:
            return          # somebody already cleaned it up
        except OSError:
            time.sleep(0.005 * (attempt + 1))


def _break_if_stale(lock_file: Path) -> bool:
    """Remove a lock whose owner is clearly gone. True if it was removed.

    TWO BUGS LIVED HERE. BOTH ARE WORTH KEEPING THE STORY OF.
    ---------------------------------------------------------

    **The first was a race.** Taking the lock is two steps: create the file
    exclusively, then write who owns it. Between those steps the file exists
    and is empty. The original version treated an unreadable lock file as
    "evidence of a crashed writer" and deleted it -- so a second thread
    arriving in that window would delete a *live* lock, both threads would
    believe they held it, and the lock silently stopped working.

    **The second was worse, and only happens on Windows.** The fix for the
    first still *read* the lock file to check its age. On Windows an open file
    cannot be deleted: the holder's `unlink()` failed with a sharing
    violation, that failure was swallowed, and the lock file was never
    removed. Every subsequent attempt then blocked forever.

    Measured: 80 sequential lock cycles took 0.086 s. The same work across
    four threads completed **one** append and then deadlocked for the full
    ten-second timeout. That is what makes this worth a long comment -- the
    single-threaded case looked perfectly healthy.

    So this function never opens the lock file. It asks the filesystem for the
    modification time, which is available from the instant the file exists and
    does not hold a handle that would block anyone's delete.
    """
    try:
        taken_at = lock_file.stat().st_mtime
    except OSError:
        # It has gone entirely -- somebody else released it. Report that as
        # "not broken by us", and let the caller retry the create.
        return False

    if time.time() - taken_at < STALE_LOCK_SECONDS:
        return False

    try:
        lock_file.unlink()
        return True
    except OSError:
        return False
