"""Cloud storage, reached the easy way: the folder that is already there.

THE INSIGHT THIS FILE IS BUILT ON
---------------------------------
Google Drive, Dropbox, OneDrive and iCloud Drive all install a desktop client
that puts a real folder on the disk. Everything in it is an ordinary file.

So the assistant does not need the Google Drive API, an OAuth application, a
client secret or a developer account. It needs a folder path -- and that keeps
the package's central promise intact.

It is also better in three practical ways:
  * it works offline
  * it is faster than any of their APIs
  * the student can see exactly what the assistant can see, by opening the
    folder

WHAT IS GENUINELY LOST
----------------------
    * Files that live only in the cloud and have never been synced. Some
      clients show these as placeholder files; opening one triggers a
      download, which may be slow or may fail offline.
    * Sharing, permissions, comments, version history, starring.
    * Anything on a service with no desktop client.

Each of those needs the provider's API, which needs OAuth, which needs a
registered application. If a user needs them, the honest answer is that this
tool does not do it -- not a half-built version that only works on Tuesdays.

ONE MORE THING, AND IT IS A REAL RULE
-------------------------------------
Never create a virtual environment, a `node_modules`, or anything else with
thousands of small files inside a synced folder. The sync client will either
grind for hours or corrupt it, and the failure looks like "the software is
broken" rather than "your sync client ate it". `is_synced()` exists so callers
can check before writing.
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass
from pathlib import Path

from .. import paths

# Folder names each desktop client uses, relative to the home directory.
# Ordered most-likely-first; the first that exists wins.
KNOWN_LOCATIONS: dict[str, tuple[str, ...]] = {
    "Google Drive": (
        "My Drive", "Google Drive/My Drive", "Google Drive",
        "GoogleDrive/My Drive",
    ),
    "OneDrive": (
        "OneDrive", "OneDrive - Personal",
    ),
    "Dropbox": (
        "Dropbox",
    ),
    "iCloud Drive": (
        "iCloud Drive",
        "Library/Mobile Documents/com~apple~CloudDocs",
    ),
    "Box": (
        "Box", "Box Sync",
    ),
}

# Names that indicate a folder is a sync root, used by `is_synced`.
_SYNC_MARKERS = ("google drive", "my drive", "onedrive", "dropbox",
                 "icloud drive", "com~apple~clouddocs", "box sync")


@dataclass
class Store:
    """One cloud folder that is present on this machine."""

    name: str
    path: Path

    @property
    def available(self) -> bool:
        """Is it there right now?

        Not the same as "is it configured". A cloud folder can be configured
        and absent -- the client has not started yet, the drive letter is not
        mounted, the laptop just woke up. Callers must handle that as a normal
        state rather than an error.
        """
        return self.path.exists()

    def describe(self) -> str:
        return f"{self.name}: {self.path}"


def detect() -> list[Store]:
    """Find every cloud folder present on this machine.

    Detection only. Nothing is read, nothing is written, nothing is indexed.
    """
    home = paths.home()
    found: list[Store] = []

    for name, candidates in KNOWN_LOCATIONS.items():
        for relative in candidates:
            candidate = home / relative
            if candidate.is_dir():
                found.append(Store(name=name, path=candidate))
                break

    # Windows sometimes mounts Google Drive as its own drive letter rather
    # than a folder in the home directory. Check the plausible letters, but
    # only for a Drive-shaped root -- probing every letter for every service
    # would be slow and would spin up sleeping external disks.
    if paths.is_windows():
        for letter in "GHIJKLMNOPQ":
            candidate = Path(f"{letter}:/My Drive")
            if candidate.is_dir():
                if not any(store.name == "Google Drive" for store in found):
                    found.append(Store(name="Google Drive", path=candidate))
                break

    return found


def is_synced(path: Path) -> bool:
    """Does this path look like it is inside a sync folder?

    Used before writing anything bulky. A false positive costs a warning; a
    false negative costs somebody's afternoon and possibly their files.
    """
    text = str(path).casefold().replace("\\", "/")
    return any(marker in text for marker in _SYNC_MARKERS)


def warn_if_synced(path: Path) -> str | None:
    """The warning to show before writing many files into `path`."""
    if not is_synced(path):
        return None
    return (
        f"{path} looks like it is inside a cloud-synced folder.\n"
        "Do not put a virtual environment, node_modules, or anything else "
        "made of thousands of small files in there -- sync clients handle "
        "that very badly, and the damage looks like a software fault rather "
        "than a sync fault."
    )


@dataclass
class FileInfo:
    path: Path
    size: int
    modified: _dt.datetime

    @property
    def name(self) -> str:
        return self.path.name

    def describe(self) -> str:
        size = _human_size(self.size)
        when = self.modified.strftime("%d %b %Y, %H:%M")
        return f"{self.name} ({size}, changed {when})"


def recent_files(root: Path, days: int = 7, limit: int = 50,
                 extensions: tuple[str, ...] = ()) -> list[FileInfo]:
    """Files changed recently, newest first.

    Bounded by both `days` and `limit`, and it skips the folders that are
    always noise. Walking somebody's entire Drive unbounded is how an
    assistant appears to hang.
    """
    if not root.exists():
        return []

    cutoff = _dt.datetime.now() - _dt.timedelta(days=days)
    wanted = tuple(extension.lower() for extension in extensions)
    found: list[FileInfo] = []

    skip = {".git", "node_modules", "__pycache__", ".venv", "venv",
            ".Trash", ".tmp.drivedownload", ".dropbox.cache"}

    for directory, subdirectories, filenames in os.walk(root):
        # Prune in place, which stops os.walk descending into them at all.
        subdirectories[:] = [name for name in subdirectories
                             if name not in skip and not name.startswith(".")]

        for filename in filenames:
            if filename.startswith(".") or filename == "desktop.ini":
                continue
            if wanted and not filename.lower().endswith(wanted):
                continue

            candidate = Path(directory) / filename
            try:
                stat = candidate.stat()
            except OSError:
                # A placeholder for a cloud-only file, or a permissions
                # problem. Skipping is right; failing the whole scan is not.
                continue

            modified = _dt.datetime.fromtimestamp(stat.st_mtime)
            if modified < cutoff:
                continue

            found.append(FileInfo(candidate, stat.st_size, modified))

            if len(found) > limit * 10:
                # Enough to sort meaningfully without walking forever on a
                # very busy drive.
                break

    found.sort(key=lambda info: info.modified, reverse=True)
    return found[:limit]


def find(root: Path, needle: str, limit: int = 50) -> list[FileInfo]:
    """Find files whose name contains `needle`. Case-insensitive."""
    if not root.exists() or not needle.strip():
        return []

    needle = needle.strip().casefold()
    found: list[FileInfo] = []
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv"}

    for directory, subdirectories, filenames in os.walk(root):
        subdirectories[:] = [name for name in subdirectories
                             if name not in skip and not name.startswith(".")]
        for filename in filenames:
            if needle not in filename.casefold():
                continue
            candidate = Path(directory) / filename
            try:
                stat = candidate.stat()
            except OSError:
                continue
            found.append(FileInfo(candidate, stat.st_size,
                                  _dt.datetime.fromtimestamp(stat.st_mtime)))
            if len(found) >= limit:
                return found

    return found


def _human_size(size: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "bytes":
                return f"{size} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"


def describe_what_is_available() -> str:
    """A summary for the setup interview."""
    stores = detect()
    if not stores:
        return (
            "No cloud folders found on this computer.\n"
            "\n"
            "That is not a problem -- the assistant works with ordinary "
            "folders. If you do use Google Drive, Dropbox or OneDrive, "
            "install their desktop app and the folder will appear."
        )

    lines = ["Found on this computer:", ""]
    for store in stores:
        lines.append(f"  - {store.describe()}")
    lines += [
        "",
        "These are read as ordinary folders, which needs no account, no key "
        "and no permissions. Files kept only in the cloud and never synced "
        "will not be visible.",
    ]
    return "\n".join(lines)
