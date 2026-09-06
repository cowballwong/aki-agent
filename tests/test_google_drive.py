"""Google Drive over the API, for what the synced folder cannot reach.

WHY (reported 2026-08-29)
-----------------------

`files.py` deliberately does NOT use this API: a Drive that is installed on
the computer is already a folder full of ordinary files, which is faster,
works offline, and is inspectable by opening it. That stays the default. This
is the part it listed as genuinely lost — cloud-only files, and search across
a whole Drive — and nothing here replaces the folder.

The properties held down below are the ones a later change could quietly take
away: that it reads and never writes, that a file it cannot turn into text is
reported rather than returned as bytes, and that a result set is bounded.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import secrets as secrets_module
from aki_agent.connectors import google_account, google_drive

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def store(monkeypatch):
    kept: dict[str, str] = {}
    monkeypatch.setattr(secrets_module, "set_secret",
                        lambda key, value: kept.__setitem__(key, value) or "")
    monkeypatch.setattr(secrets_module, "get_secret", lambda key: kept.get(key))
    monkeypatch.setattr(secrets_module, "delete_secret",
                        lambda key: kept.pop(key, None) is not None)
    return kept


@pytest.fixture()
def google(monkeypatch):
    """Every call Drive would make, recorded instead of sent."""
    calls: list[tuple[str, dict, bool]] = []

    def fake(path, params=None, raw=False):
        calls.append((path, dict(params or {}), raw))
        if raw:
            return b"the contents"
        if path == "/files":
            return {"files": [
                {"id": "1", "name": "Notes", "mimeType": "text/plain",
                 "modifiedTime": "2026-08-01T10:00:00Z", "size": "12"},
            ]}
        return {"id": "1", "name": "Notes", "mimeType": "text/plain"}

    monkeypatch.setattr(google_drive, "_call", fake)
    return calls


# ---------------------------------------------------------------------------
# It is a read-only connection, and that is not a phase
# ---------------------------------------------------------------------------

def test_the_scope_asked_for_is_read_only():
    assert google_account.DRIVE.scope.endswith("drive.readonly")


def test_the_module_contains_no_way_to_change_anything():
    """A property, not a style check.

    The permission granted is read-only, so a write here would fail at
    Google — but it would fail *after* somebody had been told their file was
    saved. Easier to keep the file honest than to explain that later.
    """
    source = (REPO_ROOT / "src" / "aki_agent" / "connectors"
              / "google_drive.py").read_text(encoding="utf-8")
    for verb in ('method="POST"', 'method="PATCH"', 'method="DELETE"',
                 'method="PUT"'):
        assert verb not in source, f"google_drive.py can {verb}"


def test_drive_is_its_own_grant(store):
    """Signing in to read files must not be implied by anything else."""
    secrets_module.set_secret(google_account.CALENDAR.refresh_key, "token")
    secrets_module.set_secret(google_account.GMAIL.refresh_key, "token")
    assert google_drive.connected() is False


# ---------------------------------------------------------------------------
# Searching
# ---------------------------------------------------------------------------

def test_deleted_files_are_never_returned(google):
    google_drive.find("invoice")
    _path, params, _raw = google[0]
    assert "trashed = false" in params["q"]


def test_a_search_looks_at_contents_as_well_as_names(google):
    """A `name contains` search misses a document whose title is a date."""
    google_drive.find("invoice")
    _path, params, _raw = google[0]
    assert "fullText contains 'invoice'" in params["q"]


def test_an_apostrophe_in_the_search_does_not_break_the_query(google):
    """Drive's query language is a string language; a quote must be escaped."""
    google_drive.find("the maintainer's notes")
    _path, params, _raw = google[0]
    assert "the maintainer\\'s notes" in params["q"]


def test_an_empty_search_lists_recent_files_rather_than_erroring(google):
    found = google_drive.find("")
    _path, params, _raw = google[0]
    assert "fullText" not in params["q"]
    assert params["orderBy"].startswith("modifiedTime")
    assert found and found[0].name == "Notes"


@pytest.mark.parametrize("asked, expected", [
    (5, 5), (0, google_drive.DEFAULT_LIMIT), (10_000, google_drive.HARD_LIMIT),
])
def test_the_number_of_results_is_bounded(google, asked, expected):
    google_drive.find("x", limit=asked)
    _path, params, _raw = google[0]
    assert params["pageSize"] == expected


def test_files_shared_with_you_are_included(google):
    """The thing the synced folder is worst at."""
    google_drive.find("x")
    _path, params, _raw = google[0]
    assert params["includeItemsFromAllDrives"] == "true"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _file(monkeypatch, mime: str, name: str = "Thing"):
    monkeypatch.setattr(
        google_drive, "details",
        lambda _id: google_drive.DriveFile(
            file_id="1", name=name, mime_type=mime,
            folder=mime.endswith(".folder")))


def test_a_google_doc_is_exported_as_text(google, monkeypatch):
    _file(monkeypatch, "application/vnd.google-apps.document")
    text, _about = google_drive.read("1")
    path, params, raw = google[0]
    assert path.endswith("/export") and raw is True
    assert params["mimeType"] == "text/plain"
    assert text == "the contents"


def test_a_sheet_comes_back_as_csv(google, monkeypatch):
    _file(monkeypatch, "application/vnd.google-apps.spreadsheet")
    google_drive.read("1")
    _path, params, _raw = google[0]
    assert params["mimeType"] == "text/csv"


def test_an_ordinary_text_file_is_downloaded(google, monkeypatch):
    _file(monkeypatch, "text/markdown")
    google_drive.read("1")
    _path, params, raw = google[0]
    assert params["alt"] == "media" and raw is True


def test_something_that_is_not_text_is_refused_rather_than_returned(
        google, monkeypatch):
    """Returning "" for a PDF reads, to whatever asked, as an empty document."""
    _file(monkeypatch, "application/pdf", name="Contract.pdf")
    with pytest.raises(google_drive.GoogleError) as raised:
        google_drive.read("1")
    assert "Contract.pdf" in str(raised.value)


def test_a_folder_is_refused_with_the_reason(google, monkeypatch):
    _file(monkeypatch, "application/vnd.google-apps.folder", name="Work")
    with pytest.raises(google_drive.GoogleError) as raised:
        google_drive.read("1")
    assert "folder" in str(raised.value)


def test_a_very_long_document_is_cut_and_says_so(monkeypatch):
    _file(monkeypatch, "text/plain")
    monkeypatch.setattr(google_drive, "_call",
                        lambda path, params=None, raw=False: b"x" * 5_000)
    text, _about = google_drive.read("1", limit=100)
    assert len(text) < 5_000
    assert "cut at" in text


# ---------------------------------------------------------------------------
# What it says when it is not connected
# ---------------------------------------------------------------------------

def test_it_says_the_folder_needs_no_sign_in_when_nothing_is_connected(store):
    words = google_drive.describe()
    assert "needs no sign-in" in words
    assert "never synced" in words


def test_it_still_says_the_folder_works_once_connected(store):
    secrets_module.set_secret(google_account.DRIVE.refresh_key, "token")
    words = google_drive.describe()
    assert "read only" in words
    assert "offline" in words


# ---------------------------------------------------------------------------
# A report that must not describe its own failures as the thing it reports on
# ---------------------------------------------------------------------------

def test_a_provider_with_nothing_to_connect_to_is_not_reported_as_broken():
    """Found on the Surface, 2026-08-29.

    `guide` providers are documents — there is nothing for one to be
    connected to, so they have no `available()`. `inspect` printed every
    guide as unusable with "'Guide' object has no attribute 'available'"
    beside it, which reads as a broken connection rather than a category
    error in the report.
    """
    from aki_agent import inspect_report

    class ADocument:
        name = "a-guide"

    usable, reason = inspect_report._availability(ADocument())

    assert usable is True
    assert reason == ""


def test_a_provider_that_raises_is_still_reported_as_the_problem_it_is():
    """The fix above must not swallow a real failure."""
    from aki_agent import inspect_report

    class Broken:
        name = "broken"

        def available(self):
            raise RuntimeError("the credential store is unreachable")

    usable, reason = inspect_report._availability(Broken())

    assert usable is False
    assert "credential store" in reason
