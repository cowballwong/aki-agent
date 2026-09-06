"""Google Drive over the API — for the things the synced folder cannot do.

WHY THIS EXISTS AT ALL, GIVEN `files.py` SAYS NOT TO BUILD IT
--------------------------------------------------------------
`files.py` reads Drive as an ordinary folder on the disk, and that is still
the right default: it works offline, it is faster than any API, and the person
can see exactly what the assistant can see by opening the folder. None of that
changes. It also listed what is genuinely lost, and this module is that list:

  * files that live only in the cloud and were never synced
  * searching a whole Drive rather than one folder tree
  * a Drive on a machine with no desktop client at all


SO THE TWO ARE NOT ALTERNATIVES
--------------------------------
Nothing here replaces the folder. This is the second half, taken only by
somebody who signs in for it, and the folder path keeps working untouched
whether they do or not.

READ ONLY, AND THAT IS NOT A PHASE
-----------------------------------
The scope is `drive.readonly` and there is no write anywhere in this file.
Writing to somebody's Drive from an assistant is a different decision, with a
different confirmation story, and quietly having the permission "for later"
is how a read-only tool turns out to have been a write tool all along.

WHAT COMES BACK
---------------
`find` returns metadata. `read` returns text: a Google Doc is exported as
plain text, a Sheet as CSV, and an ordinary file is downloaded as-is and
decoded if it is text at all. A PDF or an image is reported as something this
cannot turn into text rather than returned as a wall of bytes.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

from . import google_account
from .google_account import DRIVE, GoogleError

API_ROOT = "https://www.googleapis.com/drive/v3"

# What a Google-native file is exported as. Anything not here is downloaded.
EXPORTS = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}

# Types that are text once decoded. A file not on this list is not guessed at:
# returning the bytes of a PDF as if they were a document is worse than saying
# it cannot be read.
TEXT_TYPES = {
    "text/plain", "text/csv", "text/markdown", "text/html", "text/xml",
    "application/json", "application/xml", "application/rtf",
}

# Never return an unbounded document into a conversation.
MAX_CHARS = 200_000
DEFAULT_LIMIT = 20
HARD_LIMIT = 100


@dataclass
class DriveFile:
    """One file, in the terms the rest of this package speaks."""

    file_id: str
    name: str
    mime_type: str = ""
    modified: str = ""
    size: int = 0
    link: str = ""
    folder: bool = False
    synced_locally: bool = False

    @property
    def kind(self) -> str:
        if self.folder:
            return "folder"
        if self.mime_type in EXPORTS:
            return self.mime_type.rsplit(".", 1)[-1]
        return self.mime_type or "file"


def connected() -> bool:
    return google_account.connected(DRIVE)


def _call(path: str, params: dict | None = None, raw: bool = False):
    import urllib.request

    url = API_ROOT + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, method="GET")
    request.add_header("Authorization",
                       f"Bearer {google_account.access_token(DRIVE)}")
    if not raw:
        return google_account.send(request)

    try:
        with urllib.request.urlopen(request, timeout=30) as answer:
            return answer.read()
    except Exception as exc:                              # noqa: BLE001
        raise GoogleError(f"Could not read that file. ({exc})") from exc


def _as_file(entry: dict) -> DriveFile:
    mime = entry.get("mimeType", "") or ""
    try:
        size = int(entry.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    return DriveFile(
        file_id=entry.get("id", ""),
        name=entry.get("name", ""),
        mime_type=mime,
        modified=entry.get("modifiedTime", "") or "",
        size=size,
        link=entry.get("webViewLink", "") or "",
        folder=mime == "application/vnd.google-apps.folder",
    )


def _quote(text: str) -> str:
    """Drive's query language, which uses backslash escapes inside quotes."""
    return text.replace("\\", "\\\\").replace("'", "\\'")


def find(text: str = "", limit: int = DEFAULT_LIMIT,
         folder_id: str = "") -> list[DriveFile]:
    """Files matching `text` in their name or their contents.

    Bounded, always: `limit` is capped, and the trashed files Drive would
    otherwise include are excluded here rather than left for the caller to
    notice.
    """
    limit = max(1, min(int(limit or DEFAULT_LIMIT), HARD_LIMIT))
    clauses = ["trashed = false"]
    text = (text or "").strip()
    if text:
        # `fullText` covers the name as well as the contents, which is what
        # somebody typing a few words means. `name contains` alone misses a
        # document whose title is a date.
        clauses.append(f"fullText contains '{_quote(text)}'")
    if folder_id:
        clauses.append(f"'{_quote(folder_id)}' in parents")

    answer = _call("/files", {
        "q": " and ".join(clauses),
        "pageSize": limit,
        "orderBy": "modifiedTime desc",
        "fields": ("files(id,name,mimeType,modifiedTime,size,webViewLink)"),
        # Shared drives too -- a file somebody shared with you is one of the
        # things the synced folder is worst at.
        "includeItemsFromAllDrives": "true",
        "supportsAllDrives": "true",
    })
    return [_as_file(one) for one in answer.get("files", [])]


def details(file_id: str) -> DriveFile:
    answer = _call(f"/files/{urllib.parse.quote(file_id)}", {
        "fields": "id,name,mimeType,modifiedTime,size,webViewLink",
        "supportsAllDrives": "true",
    })
    return _as_file(answer)


def read(file_id: str, limit: int = MAX_CHARS) -> tuple[str, DriveFile]:
    """The file's text, and what it was.

    Raises rather than returning a placeholder when the file is not text:
    silently handing back "" for a PDF reads, to whatever asked, exactly like
    an empty document.
    """
    about = details(file_id)
    if about.folder:
        raise GoogleError(f"{about.name} is a folder, not a file.")

    export_as = EXPORTS.get(about.mime_type)
    if export_as:
        body = _call(f"/files/{urllib.parse.quote(file_id)}/export",
                     {"mimeType": export_as}, raw=True)
    elif about.mime_type in TEXT_TYPES or about.mime_type.startswith("text/"):
        body = _call(f"/files/{urllib.parse.quote(file_id)}",
                     {"alt": "media", "supportsAllDrives": "true"}, raw=True)
    else:
        raise GoogleError(
            f"{about.name} is a {about.mime_type or 'file'}, which this "
            "cannot turn into text. Open it from the synced folder instead.")

    text = body.decode("utf-8", errors="replace")
    if len(text) > limit:
        text = text[:limit] + f"\n\n[...cut at {limit:,} characters]"
    return text, about


def describe() -> str:
    """One paragraph for the dashboard and the guide, honest either way."""
    if not connected():
        return ("Not signed in. The synced Drive folder on this computer is "
                "read directly and needs no sign-in; this connection is only "
                "for what that cannot reach — files that were never synced, "
                "and searching the whole Drive.")
    return ("Signed in, read only. Searching and reading go through Google; "
            "the synced folder on this computer is still read directly and "
            "still works offline.")
