"""Noticing that somebody has edited the engine, before an upgrade replaces it.

WHY THIS EXISTS
---------------
An upgrade replaces `01_Config/engine` whole. That is the right design -- a
program you can reason about is one you can also put back -- but it means any
edit made inside that folder is discarded, and until now discarded in silence:
nothing recorded what the files were supposed to look like, so nothing could
tell that they had changed.

The person most likely to be caught by that is the one this package is aimed
at. They ask their assistant to "change that button", their assistant edits a
template in the engine because that is where the button is, and a fortnight
later an upgrade quietly undoes an afternoon of their work. They do not read
release notes; they notice the button went back.

WHAT IT DOES, AND DELIBERATELY DOES NOT DO
------------------------------------------
It records a fingerprint per file at install, compares before the next
replacement, and reports what differs. It does NOT merge, refuse, or protect.
Editing the engine stays allowed -- this package is teaching material and
somebody reading the code and changing it is the point. What was missing was
being told.

THE SECOND USE, WHICH MAY MATTER MORE
-------------------------------------
A list of the files people actually edit is the shortest route to knowing
which extension points are missing. Somebody who edits a template wanted a
setting that does not exist yet. Ten people editing the same file is a feature
request with ten signatures, arrived at without a survey.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

# Recorded beside the manifest, inside the engine folder, so it travels with
# the thing it describes: a fingerprint file that outlived its engine would
# describe a program that is no longer there.
FINGERPRINT_FILE = ".installed-fingerprints"

# Compiled bytecode, caches, build output and the fingerprint file itself.
# Their contents change without anybody editing anything, and reporting them
# as somebody's work would train the reader to skip the whole list -- which
# costs exactly the warning this module exists to give.
#
# `.egg-info` earned its place by running this: installing the package into a
# virtual environment writes seven files there, so the first honest test of
# the feature reported one real edit buried under seven build artefacts.
IGNORED_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache", ".git",
                 "build", "dist", ".mypy_cache", "node_modules"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
IGNORED_PARTS_ENDING = (".egg-info",)


def _worth_recording(path: Path, root: Path) -> bool:
    if path.suffix in IGNORED_SUFFIXES:
        return False
    relative = path.relative_to(root)
    if relative.name in (FINGERPRINT_FILE,):
        return False
    if any(part in IGNORED_NAMES for part in relative.parts):
        return False
    return not any(part.endswith(IGNORED_PARTS_ENDING)
                   for part in relative.parts)


def fingerprint(path: Path) -> str:
    """A short hash of one file's bytes.

    Bytes, not text: a template saved with different line endings IS a
    different file to everything downstream, and pretending otherwise would
    hide the most common edit of all.

    Truncated to sixteen characters. This is a change detector, not a
    signature -- nothing here defends against somebody deliberately forging a
    match, and a shorter file keeps the record readable.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()[:16]


def record(engine_dir: Path) -> int:
    """Write down what every file looks like now. Returns how many were kept.

    Called at the end of an install, on the folder that was just put in place,
    so the record describes a known-good copy rather than whatever was there
    before.
    """
    engine_dir = Path(engine_dir)
    prints: dict[str, str] = {}
    for path in sorted(engine_dir.rglob("*")):
        if not path.is_file() or not _worth_recording(path, engine_dir):
            continue
        try:
            prints[path.relative_to(engine_dir).as_posix()] = fingerprint(path)
        except OSError:                                   # pragma: no cover
            continue

    try:
        (engine_dir / FINGERPRINT_FILE).write_text(
            json.dumps(prints, indent=0, sort_keys=True), encoding="utf-8")
    except OSError:                                       # pragma: no cover
        # A missing record means the next upgrade cannot tell what changed.
        # That is the state everything was in before this existed, so it is a
        # loss of a warning, never a reason to stop an install.
        return 0
    return len(prints)


@dataclass
class Changes:
    """What somebody has done to their copy since it was installed."""

    edited: tuple = ()
    added: tuple = ()
    removed: tuple = ()
    checked: bool = True        # False when there was no record to compare to

    @property
    def any(self) -> bool:
        return bool(self.edited or self.added or self.removed)

    def sentence(self) -> str:
        """One line, in the terms somebody would use about their own work."""
        if not self.checked:
            return ("this engine was installed before changes were tracked, "
                    "so there is nothing to compare against")
        if not self.any:
            return "nothing in the engine has been edited"

        parts = []
        if self.edited:
            parts.append(f"{len(self.edited)} file(s) edited")
        if self.added:
            parts.append(f"{len(self.added)} added")
        if self.removed:
            parts.append(f"{len(self.removed)} removed")
        return ", ".join(parts)


def compare(engine_dir: Path) -> Changes:
    """What differs between this engine and the record made when it landed.

    An unreadable or absent record answers "cannot tell" rather than "nothing
    changed". The difference matters: one of those is a reason to look, and
    the other is a reason to relax.
    """
    engine_dir = Path(engine_dir)
    try:
        recorded = json.loads(
            (engine_dir / FINGERPRINT_FILE).read_text(encoding="utf-8"))
        if not isinstance(recorded, dict):
            raise ValueError
    except (OSError, ValueError):
        return Changes(checked=False)

    present: dict[str, str] = {}
    for path in sorted(engine_dir.rglob("*")):
        if not path.is_file() or not _worth_recording(path, engine_dir):
            continue
        try:
            present[path.relative_to(engine_dir).as_posix()] = fingerprint(path)
        except OSError:                                   # pragma: no cover
            continue

    edited = tuple(sorted(name for name, mark in recorded.items()
                          if name in present and present[name] != mark))
    added = tuple(sorted(set(present) - set(recorded)))
    removed = tuple(sorted(set(recorded) - set(present)))
    return Changes(edited=edited, added=added, removed=removed)


def keep_aside(engine_dir: Path, changes: Changes, where: Path) -> Path | None:
    """Copy the changed files somewhere the upgrade will not touch.

    Copied, not moved: the upgrade needs the folder as it is, and a person
    whose work has just been set aside should not also find their working
    install altered on the way.

    Returns where they went, or None if there was nothing to keep.
    """
    import shutil

    wanted = [name for name in (*changes.edited, *changes.added)]
    if not wanted:
        return None

    where = Path(where)
    where.mkdir(parents=True, exist_ok=True)
    for name in wanted:
        source = engine_dir / name
        destination = where / name
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        except OSError:                                   # pragma: no cover
            continue
    return where
