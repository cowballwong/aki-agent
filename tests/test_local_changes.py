"""Telling somebody their engine edits are about to be replaced.

An upgrade replaces the engine folder whole. That is what makes it reversible,
and it is also why an edit inside it disappears. Until this existed it
disappeared in silence — which for the person this package is aimed at means
asking their assistant to change a button, and finding a fortnight later that
the button went back with no explanation available to anybody.

What is held here is the difference between three answers that look alike from
outside: nothing changed, something changed, and cannot tell.
"""

from __future__ import annotations

import json

import pytest

from aki_agent import local_changes


@pytest.fixture
def engine(tmp_path):
    """An installed engine, with its fingerprints recorded."""
    folder = tmp_path / "engine"
    (folder / "src" / "aki_agent" / "dashboard" / "templates").mkdir(
        parents=True)
    # Written as BYTES. Python translates "\n" to CRLF on Windows by default,
    # so a fixture written the obvious way is already CRLF — and the
    # line-ending test below then compares CRLF with CRLF and silently proves
    # nothing. What ships is LF, and the fixture should be what ships.
    (folder / "src" / "aki_agent" / "tasks.py").write_bytes(
        b"def run():\n    return 1\n")
    (folder / "src" / "aki_agent" / "dashboard" / "templates"
     / "today.html").write_bytes(b"<h1>Today</h1>\n")
    (folder / "README.md").write_bytes(b"read me\n")
    local_changes.record(folder)
    return folder


def test_an_untouched_engine_reports_nothing(engine):
    changes = local_changes.compare(engine)

    assert changes.any is False
    assert "nothing" in changes.sentence()


def test_an_edited_template_is_named(engine):
    """The commonest edit of all: somebody changed a button."""
    page = engine / "src" / "aki_agent" / "dashboard" / "templates" / "today.html"
    page.write_text("<h1>Today</h1>\n<button>Mine</button>\n", encoding="utf-8")

    changes = local_changes.compare(engine)

    assert changes.edited == (
        "src/aki_agent/dashboard/templates/today.html",)
    assert "1 file(s) edited" in changes.sentence()


def test_a_file_somebody_added_is_not_confused_with_one_they_edited(engine):
    (engine / "src" / "aki_agent" / "mine.py").write_text(
        "print('hello')\n", encoding="utf-8")

    changes = local_changes.compare(engine)

    assert changes.added == ("src/aki_agent/mine.py",)
    assert changes.edited == ()


def test_a_deleted_file_is_reported_too(engine):
    (engine / "README.md").unlink()

    changes = local_changes.compare(engine)

    assert changes.removed == ("README.md",)


def test_a_line_ending_change_counts_as_an_edit(engine):
    """Bytes, not text.

    A template saved by a Windows editor IS a different file to everything
    downstream, and calling that "unchanged" would hide the single most common
    way somebody's edit arrives.
    """
    page = engine / "src" / "aki_agent" / "dashboard" / "templates" / "today.html"
    page.write_bytes(b"<h1>Today</h1>\r\n")

    assert local_changes.compare(engine).edited


def test_compiled_bytecode_is_never_somebody_s_work(engine):
    """Otherwise the first upgrade after any use reports a folder full of
    edits, and the reader learns to skip the list."""
    cache = engine / "src" / "aki_agent" / "__pycache__"
    cache.mkdir()
    (cache / "tasks.cpython-313.pyc").write_bytes(b"\x00\x01binary")

    changes = local_changes.compare(engine)

    assert changes.any is False


def test_no_record_says_cannot_tell_rather_than_nothing_changed(tmp_path):
    """The two answers look alike and mean opposite things.

    An engine installed before this existed has no record. Reporting that as
    "nothing changed" would be the package asserting something it has no way
    of knowing — the exact failure it keeps finding in itself.
    """
    folder = tmp_path / "old-engine"
    folder.mkdir()
    (folder / "thing.py").write_text("x = 1\n", encoding="utf-8")

    changes = local_changes.compare(folder)

    assert changes.checked is False
    assert changes.any is False
    assert "nothing to compare" in changes.sentence()


def test_an_unreadable_record_is_also_cannot_tell(engine):
    (engine / local_changes.FINGERPRINT_FILE).write_text(
        "not json at all", encoding="utf-8")

    assert local_changes.compare(engine).checked is False


def test_the_record_does_not_fingerprint_itself(engine):
    recorded = json.loads(
        (engine / local_changes.FINGERPRINT_FILE).read_text(encoding="utf-8"))

    assert local_changes.FINGERPRINT_FILE not in recorded, (
        "a file that changes whenever it is written can never match itself")


def test_edited_files_are_copied_aside_and_left_in_place(engine, tmp_path):
    """Copied, not moved.

    The upgrade needs the folder as it is, and somebody whose work has just
    been set aside should not also find their working install altered on the
    way to being told about it.
    """
    page = engine / "src" / "aki_agent" / "dashboard" / "templates" / "today.html"
    page.write_text("<h1>Mine now</h1>\n", encoding="utf-8")
    changes = local_changes.compare(engine)

    where = local_changes.keep_aside(engine, changes, tmp_path / "kept")

    saved = where / "src" / "aki_agent" / "dashboard" / "templates" / "today.html"
    assert saved.read_text(encoding="utf-8") == "<h1>Mine now</h1>\n"
    assert page.exists(), "the working copy must be left exactly as it was"


def test_keeping_nothing_aside_returns_nothing(engine, tmp_path):
    changes = local_changes.compare(engine)

    assert local_changes.keep_aside(engine, changes, tmp_path / "kept") is None


def test_build_output_is_never_somebody_s_work(engine):
    """Found by running it, not by thinking about it.

    Installing the package into a virtual environment writes seven files into
    `src/aki_agent.egg-info/`. The first honest test of this feature reported
    one real edit buried under seven build artefacts — and a list like that
    teaches the reader to skip it, which costs the warning entirely.
    """
    info = engine / "src" / "aki_agent.egg-info"
    info.mkdir(parents=True)
    for name in ("PKG-INFO", "SOURCES.txt", "top_level.txt"):
        (info / name).write_bytes(b"generated\n")
    (engine / "build").mkdir()
    (engine / "build" / "thing.o").write_bytes(b"\x00")

    changes = local_changes.compare(engine)

    assert changes.any is False, changes.added
