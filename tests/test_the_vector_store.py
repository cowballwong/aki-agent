"""The vector store: what it reads, what it refuses, and what it never claims.

 and, after being
shown that a few hundred notes do not need a database.

The point of the tab is the second use, not the first. The Knowledge shelf
stores a POINTER to each document — so a two-hundred-page Approved Document
somebody added is known about and has never been read. These tests are mostly
about the reading: what happens to a scan with no text in it, to a file that
moved, to a format nothing here can open. Forty documents will contain one of
each, and none of them may stop the other thirty-seven.

Chroma itself is not installed in this suite and is not required to be. What
can be tested without it — which is everything except the storing — is tested
without it, because a test that only runs on a machine with a few hundred
megabytes of extras is a test that stops running.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aki_agent import paths, vectors

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "src" / "aki_agent" / "dashboard" / "templates"


# ---------------------------------------------------------------------------
# Nothing is forced on anybody
# ---------------------------------------------------------------------------

def test_none_of_it_is_a_hard_dependency():
    """`pyproject.toml` says in as many words that the core install stays at
    one runtime dependency. A student who will never search a document by
    meaning should not be made to download the machinery for it."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    for name, _why in vectors.PIECES:
        assert name not in text, f"{name} became a hard dependency"


def test_every_piece_says_what_it_is_for():
    """A list of three downloads with no reasons is a list nobody can
    consent to."""
    for name, why in vectors.PIECES:
        assert name and why
        assert len(why) > 15, name

    # And the expensive one says so where it is chosen, not afterwards.
    costly = dict(vectors.PIECES)["fastembed"]
    assert "hundred megabytes" in costly


def test_it_is_one_button_and_not_three():
    """Three separate installs is three chances to stop half way and end up
    able to embed but not store -- a state that reports itself as neither
    working nor broken."""
    page = (TEMPLATES / "history.html").read_text(encoding="utf-8")
    assert page.count('name="action" value="install"') == 1
    assert "Set it up" in page


# ---------------------------------------------------------------------------
# Reading a document
# ---------------------------------------------------------------------------

def test_plain_text_needs_nothing_installed(tmp_path):
    note = tmp_path / "brief.md"
    note.write_text("# Brief\n\nThe stair must be 1200 wide.\n",
                    encoding="utf-8")

    text, trouble = vectors.read_text(note)
    assert not trouble
    assert "1200 wide" in text


def test_a_format_it_cannot_open_is_reported_not_raised(tmp_path):
    odd = tmp_path / "model.rvt"
    odd.write_bytes(b"\x00\x01\x02")

    text, trouble = vectors.read_text(odd)
    assert text == ""
    assert ".rvt" in trouble


def test_a_pdf_without_pypdf_says_which_piece_is_missing(tmp_path,
                                                        monkeypatch):
    """Not "could not read it". The person can act on the first sentence and
    can only shrug at the second."""
    monkeypatch.setattr(vectors, "_importable", lambda name: False)

    text, trouble = vectors.read_text(tmp_path / "adb.pdf")
    assert text == ""
    assert "pypdf" in trouble


def test_a_scan_with_no_text_says_so_exactly(tmp_path, monkeypatch):
    """The commonest disappointment, and worth naming.

    A scanned drawing set has no text layer at all. "0 passages" with no
    reason reads as a bug in this software, and the person goes looking in
    the wrong place.
    """
    class EmptyPage:
        @staticmethod
        def extract_text():
            return ""

    class EmptyReader:
        pages = [EmptyPage(), EmptyPage()]

        def __init__(self, _path):
            pass

    monkeypatch.setattr(vectors, "_importable", lambda name: True)
    import sys
    import types

    fake = types.ModuleType("pypdf")
    fake.PdfReader = EmptyReader
    monkeypatch.setitem(sys.modules, "pypdf", fake)

    text, trouble = vectors.read_text(tmp_path / "scan.pdf")
    assert text == ""
    assert "scan" in trouble
    assert "character recognition" in trouble


# ---------------------------------------------------------------------------
# Cutting it up
# ---------------------------------------------------------------------------

def test_passages_overlap_so_an_answer_is_never_cut_in_half():
    """The sentence that answers a question is otherwise exactly the one that
    falls across a boundary and is never returned whole."""
    text = "word " * 2000
    passages = vectors.into_passages(text)

    assert len(passages) > 1
    assert all(len(one) <= vectors.CHUNK for one in passages)

    # The tail of one appears at the head of the next.
    tail = passages[0][-vectors.OVERLAP:]
    assert passages[1].startswith(tail)


def test_nothing_in_gives_nothing_out():
    assert vectors.into_passages("") == []
    assert vectors.into_passages("      ") == []


def test_a_short_document_is_one_passage():
    assert len(vectors.into_passages("A short brief.")) == 1


# ---------------------------------------------------------------------------
# What it refuses to do without its parts
# ---------------------------------------------------------------------------

def test_indexing_without_the_pieces_says_which_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    monkeypatch.setattr(vectors, "_importable", lambda name: False)

    ok, said = vectors.index()
    assert not ok
    assert "chromadb" in said


def test_searching_without_the_pieces_answers_empty(tmp_path, monkeypatch):
    """Not an exception. Every caller of this shows results beside other
    results, so a search that raises takes the whole page with it."""
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    monkeypatch.setattr(vectors, "_importable", lambda name: False)

    assert vectors.search("anything") == []
    assert vectors.search("") == []


# ---------------------------------------------------------------------------
# One model, not two
# ---------------------------------------------------------------------------

def test_the_vectors_come_from_this_packages_own_model():
    """Chroma will happily supply its own embedding function.

    Letting it would mean two models that disagree about what "similar"
    means, and a note indexed under one could never be compared with a
    passage indexed under the other.
    """
    source = (REPO_ROOT / "src" / "aki_agent"
              / "vectors.py").read_text(encoding="utf-8")

    assert "semantic._embedder()" in source
    assert "embeddings=vectors" in source, (
        "the vectors have to be handed to Chroma, or it computes its own")
    assert "embedding_function" not in source


def test_the_engines_code_carries_no_profession_vocabulary():
    """`client` was the natural name for the Chroma handle and is on the
    banned list -- an architect has clients, and this package has to read the
    same to a piano teacher. Chroma's class name is Chroma's business; the
    variable is ours."""
    source = (REPO_ROOT / "src" / "aki_agent"
              / "vectors.py").read_text(encoding="utf-8")
    code = re.sub(r"#.*", "", source)
    code = re.sub(r'""".*?"""', "", code, flags=re.S)

    assert not re.search(r"(?<![A-Za-z])client\s*=", code)


# ---------------------------------------------------------------------------
# What the page promises
# ---------------------------------------------------------------------------

def test_the_page_explains_why_a_database_is_needed_at_all():
    """He asked what a vector store is actually for. The answer -- that his
    shelf holds pointers and nothing has read the documents -- is the whole
    reason Chroma earns its keep, so it belongs on the page and not only in
    a message he will scroll past."""
    page = (TEMPLATES / "history.html").read_text(encoding="utf-8")

    assert "pointer" in page
    assert "never been read" in page


def test_clearing_the_store_promises_the_documents_are_untouched():
    ok_text = (TEMPLATES / "history.html").read_text(encoding="utf-8")
    assert "not touched" in ok_text or "untouched" in ok_text

    source = (REPO_ROOT / "src" / "aki_agent"
              / "vectors.py").read_text(encoding="utf-8")
    start = source.index("def forget(")
    body = source[start:]
    # It removes its own folder and nothing else.
    assert "store_dir()" in body
    assert "shutil.rmtree" in body
    assert "knowledge" not in body
