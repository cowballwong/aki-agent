"""Walking the machine's folders, so nobody has to type a path from memory.

reported 2026-08-21, about the "folder to watch" box on the schedule page:

A web page cannot open a real folder picker and learn the answer. The file
input's directory mode hands JavaScript the *names* of the files inside a
folder and nothing else -- no absolute path, deliberately, because a page is
not supposed to learn where you keep things. So the picker has to be built
from this side: the dashboard already runs on the machine whose folders we
are naming, and it can list them.

Read-only. Nothing here opens, moves, or changes a file; the only thing it
learns is which folders exist, and the route that calls it sits behind the
same token guard as every other change, so a foreign page cannot use it to
map the disk.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from pathlib import Path

# Folders Windows keeps for itself. Listing them is slow, sometimes refused,
# and never what somebody browsing for their drawings is looking for.
SKIP = {
    "$recycle.bin",
    "system volume information",
    "$windows.~ws",
    "$windows.~bt",
    "recovery",
    "config.msi",
}


@dataclass(frozen=True)
class Folder:
    """One row in the picker."""

    name: str
    path: str


def _worth_showing(entry: Path) -> bool:
    name = entry.name
    if name.lower() in SKIP:
        return False
    # Windows keeps recovery and reset images in $-prefixed folders at the
    # root of every drive. Browsing C:\ on the reference machine listed
    # $SysReset and $WinREAgent above Documents, which is both noise and an
    # invitation to point a scheduled task at something that must not be
    # touched.
    if name.startswith("$"):
        return False
    # Dot-folders are tooling, not documents. `.claude` and friends are
    # things the agent manages; somebody picking a folder to watch means a
    # folder they put things in.
    return not name.startswith(".")


def starting_points() -> list[Folder]:
    """Where the picker opens: your home folder, then every drive.

    Home first because that is where a person's own folders are, and drives
    after because that is where everything else is.
    """
    places: list[Folder] = []
    home = Path.home()
    if home.exists():
        places.append(Folder("Home", str(home)))

    if Path("C:/").exists():  # Windows
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:/")
            try:
                if drive.exists():
                    places.append(Folder(f"{letter}:", str(drive)))
            except OSError:
                # A mapped drive whose server is away raises rather than
                # answering False. It is simply not offered.
                continue
    else:
        places.append(Folder("/", "/"))

    return places


def listing(where: str = "", want_files: bool = False) -> dict:
    """The folders inside `where`, plus how to go back up.

    An unreadable or missing folder is reported, not raised: the picker keeps
    working and says why that one is empty.

    `want_files` adds the files as a second list. reported 2026-09-05, of the
    Knowledge page. Folders are always listed, because you have to be able to walk to
    the file; `files` stays empty when it was not asked for, so the schedule
    page's folder picker reads exactly the same answer it always did.
    """
    if not where:
        return {
            "here": "",
            "label": "This computer",
            "up": None,
            "folders": [f.__dict__ for f in starting_points()],
            "files": [],
            "trouble": "",
        }

    here = Path(where)
    parent = here.parent
    # A drive root's parent is itself, which would make Up a button that does
    # nothing. Above a drive root is the list of drives.
    up = "" if parent == here else str(parent)

    folders: list[Folder] = []
    files: list[Folder] = []
    trouble = ""
    try:
        for entry in sorted(here.iterdir(), key=lambda p: p.name.lower()):
            try:
                if entry.is_dir() and _worth_showing(entry):
                    folders.append(Folder(entry.name, str(entry)))
                elif want_files and entry.is_file() and _worth_showing(entry):
                    files.append(Folder(entry.name, str(entry)))
            except OSError:
                # One bad entry -- a broken link, a file being written --
                # should not empty the whole list.
                continue
    except FileNotFoundError:
        trouble = "That folder is not there any more."
    except PermissionError:
        trouble = "Windows will not let this account read that folder."
    except OSError as problem:
        trouble = f"That folder could not be read: {problem}"

    return {
        "here": str(here),
        "label": str(here),
        "up": up,
        "folders": [f.__dict__ for f in folders],
        "files": [f.__dict__ for f in files],
        "trouble": trouble,
    }

# ---------------------------------------------------------------------------
# The machine's own folder dialog
#
#
# A web page cannot open one -- but this program is not a web page. The
# dashboard is a process on the same machine, running in the same desktop
# session as the browser, so it can open the real dialog itself and hand the
# answer back through the response. What the browser gets is a path it was
# never allowed to read; what the person gets is the window they know.
#
# It only works when the dashboard has a desktop to draw on. Started from a
# service, over SSH, or on a machine with no Tk, there is no window -- so
# `ask_for_folder` says so plainly and the page falls back to the list it can
# draw itself.
# ---------------------------------------------------------------------------

def can_open_a_window() -> bool:
    """Is there a desktop to put a dialog on?

    Answered without importing tkinter, deliberately: loading Tk into the
    dashboard's own process is the thing this module goes out of its way not
    to do.
    """
    import importlib.util
    import sys

    if importlib.util.find_spec("tkinter") is None:
        return False
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return True
    return _has_display()


def _has_display() -> bool:
    """On Linux a missing DISPLAY means Tk cannot start."""
    import os

    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


# The dialog runs in a process of its own, and that is the important part.
#
# Tk is not built for being started, used and torn down inside one thread of
# a web server that is serving other requests at the same time; when it goes
# wrong it does not raise, it takes the process with it. The dashboard dying
# while somebody presses Browse would look exactly like the unexplained
# dashboard deaths the maintainer has been chasing -- so the dialog is given its own
# short-lived process, and the worst it can do is fail to answer.
DIALOG = """
import sys, tkinter
from tkinter import filedialog

root = tkinter.Tk()
root.withdraw()
# Otherwise it opens behind the browser and, to the person, nothing happened
# at all except that the button stopped working.
root.attributes("-topmost", True)
root.update()
chosen = filedialog.askdirectory(
    parent=root,
    title="Pick the folder to watch",
    initialdir=(sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None),
    mustexist=True,
)
root.destroy()
sys.stdout.write(chosen or "")
"""


# The same dialog, asking for a file.
#
# The same thing was asked for folders on 2026-08-21. Typing a full path
# from memory is
# not something anybody does correctly, and the one place it matters most is
# here, where a wrong path is stored as a pointer that looks exactly like a
# working one until the day it is read.
#
# Its own process for the same reason as the folder one: Tk taken up and torn
# down inside a serving thread does not raise when it goes wrong, it takes the
# dashboard with it.
FILE_DIALOG = """
import sys, tkinter
from tkinter import filedialog

root = tkinter.Tk()
root.withdraw()
root.attributes("-topmost", True)
root.update()
chosen = filedialog.askopenfilename(
    parent=root,
    title="Pick the document",
    initialdir=(sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None),
)
root.destroy()
sys.stdout.write(chosen or "")
"""


def _ask_with(script: str, start_at: str, what: str) -> dict:
    """Run one of the dialogs above in its own process and read the answer.

    Written once because the folder and file versions differ only in which
    Tk function they call -- and the error handling around them is the part
    that took three attempts to get right.
    """
    import subprocess
    import sys

    if not can_open_a_window():
        return {"path": "", "trouble": "no window"}

    try:
        finished = subprocess.run(
            [sys.executable, "-c", script, start_at],
            capture_output=True, text=True, timeout=300, check=False)
    except subprocess.TimeoutExpired:
        return {"path": "", "trouble":
                f"The {what} window was left open too long. Type the path, "
                "or press Browse again."}
    except (OSError, subprocess.SubprocessError) as problem:
        return {"path": "", "trouble": f"no window: {problem}"}

    if finished.returncode != 0:
        detail = (finished.stderr or "").strip().splitlines()
        return {"path": "", "trouble":
                "no window: " + (detail[-1] if detail else "it would not open")}

    chosen = finished.stdout.strip()
    if not chosen:
        return {"path": "", "trouble": ""}       # cancelled, and that is fine
    # Tk answers in forward slashes even on Windows.
    return {"path": str(Path(chosen)), "trouble": ""}


def ask_for_file(start_at: str = "") -> dict:
    """Open the machine's own file dialog and wait for an answer."""
    return _ask_with(FILE_DIALOG, start_at, "file")


def ask_for_folder(start_at: str = "") -> dict:
    """Open the operating system's folder dialog and wait for an answer.

    Returns `{"path": ...}` when something was picked, `{"path": ""}` with no
    trouble when the person cancelled, and a `trouble` when no dialog could
    be opened at all -- which the page treats as "use the built-in list
    instead", never as an error to show.

    The body moved into `_ask_with` on 2026-09-05, when the file dialog was
    added. The two differ in one Tk call; everything around them is error
    handling that took three attempts to get right, and keeping two copies of
    that is keeping one copy that will not get the next fix.
    """
    return _ask_with(DIALOG, start_at, "folder")
