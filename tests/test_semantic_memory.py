"""Matching by meaning — the option, and the promises made about it.

WHY (reported 2026-08-20)
-----------------------
He asked whether this package had ChromaDB and the memory layers he teaches
in his AI class. It had none: `memory.search` is BM25, chosen so a student can
read thirty lines of arithmetic and see exactly why a result ranked where it
did. The gap that leaves is written into that file — it cannot match "car" to
"vehicle".

Offered the choice, he took neither extreme: *"加做選項,預設關"*.

That decision is what these tests hold in place. The feature is easy to build
and easy to let quietly take over, and the ways it would take over are all
invisible from the outside: defaulting to on, downloading on first use,
replacing word matches instead of adding to them, or returning its best guess
when it has no good answer. Each of those has a test here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import memory, semantic


@pytest.fixture(autouse=True)
def somewhere_safe(tmp_path, monkeypatch):
    """Never touch the real state folder or the real memory."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))
    (tmp_path / "01_Config" / "state").mkdir(parents=True, exist_ok=True)
    return tmp_path


# ---------------------------------------------------------------------------
# The default, which is the whole point
# ---------------------------------------------------------------------------

def test_it_is_off_until_somebody_turns_it_on():
    """Off with no state file at all, which is how every install starts.

    A feature that installs several hundred megabytes must be chosen, never
    inherited. The opposite default to the sentinel, and deliberately so: the
    sentinel costs nothing and catches mistakes.
    """
    assert semantic.enabled() is False


def test_a_corrupt_switch_file_reads_as_off():
    """Fail closed. An unreadable switch must not turn a feature on."""
    semantic.switch_file().write_text("{not json", encoding="utf-8")
    assert semantic.enabled() is False


def test_searching_while_off_returns_nothing_and_touches_no_model(monkeypatch):
    """Off means off: no import, no model load, no download.

    The failure this prevents is the one nobody would notice until it had
    already happened — a "disabled" feature that still initialises its model
    the first time anything searches.
    """
    def explode():                                        # pragma: no cover
        raise AssertionError("the model was loaded while switched off")

    monkeypatch.setattr(semantic, "_embedder", explode)
    assert semantic.search("anything at all") == []


def test_turning_it_on_without_the_library_refuses_and_explains(monkeypatch):
    """And says what it would cost, in megabytes, before anybody agrees."""
    monkeypatch.setattr(semantic, "available", lambda: False)

    ok, message = semantic.turn_on()

    assert ok is False
    assert semantic.enabled() is False, "it turned on despite refusing"
    assert "pip install fastembed" in message
    assert "megabytes" in message, "the size was not disclosed"
    assert "nothing is sent anywhere" in message.lower()


# ---------------------------------------------------------------------------
# What it must never do to the existing search
# ---------------------------------------------------------------------------

def test_meaning_matches_are_added_and_never_replace_word_matches(monkeypatch):
    """The promise on the page, held in code.

    Somebody switching this on must not lose a result they were relying on.
    So the classical ranking is returned unchanged and anything semantic is
    appended after it.
    """
    monkeypatch.setattr(semantic, "enabled", lambda: True)

    memory.remember("car mot", body="The car is due for its MOT in March")
    memory.remember("bins", body="Bin day is Tuesday")

    word_matches = [(9.9, fact) for fact in memory.recall(limit=10)
                    if fact.key]
    assert word_matches, "the fixture wrote nothing"

    monkeypatch.setattr(
        semantic, "search",
        lambda query, limit=5: [semantic.Match(key=word_matches[0][1].key,
                                               score=0.9, text="x")])

    blended = memory._with_meaning_matches(                # noqa: SLF001
        "vehicle", word_matches, limit=10)

    assert blended[:len(word_matches)] == word_matches, (
        "the word matches were reordered or dropped")


def test_a_note_already_found_by_words_is_not_listed_twice(monkeypatch):
    monkeypatch.setattr(semantic, "enabled", lambda: True)
    memory.remember("car mot", body="The car is due for its MOT")
    facts = memory.recall(limit=10)
    ranked = [(9.9, facts[0])]

    monkeypatch.setattr(
        semantic, "search",
        lambda query, limit=5: [semantic.Match(key=facts[0].key, score=0.9,
                                               text="x")])

    blended = memory._with_meaning_matches("vehicle", ranked, limit=10)
    assert len(blended) == 1


def test_the_blend_does_nothing_at_all_while_switched_off(monkeypatch):
    memory.remember("thing", body="Anything")
    facts = memory.recall(limit=10)
    ranked = [(1.0, facts[0])]

    def explode(*_a, **_k):                               # pragma: no cover
        raise AssertionError("semantic search ran while switched off")

    monkeypatch.setattr(semantic, "search", explode)
    assert memory._with_meaning_matches("x", ranked, 10) == ranked


def test_the_limit_is_respected_so_a_page_cannot_be_flooded(monkeypatch):
    monkeypatch.setattr(semantic, "enabled", lambda: True)
    for n in range(4):
        memory.remember(f"note {n}", body=f"Note number {n}")
    facts = memory.recall(limit=10)
    ranked = [(9.0, facts[0]), (8.0, facts[1])]

    monkeypatch.setattr(
        semantic, "search",
        lambda query, limit=5: [semantic.Match(key=one.key, score=0.9, text="")
                                for one in facts[2:]][:limit])

    blended = memory._with_meaning_matches("x", ranked, limit=3)
    assert len(blended) <= 3


# ---------------------------------------------------------------------------
# Honesty about what it found
# ---------------------------------------------------------------------------

def test_a_weak_match_is_no_match(monkeypatch):
    """Below the floor, the answer is nothing.

    A search that quietly returns its best bad guess is how somebody comes to
    trust a match that was never really there — and unlike a word match, there
    is nothing on the page for them to check it against.
    """
    monkeypatch.setattr(semantic, "enabled", lambda: True)
    monkeypatch.setattr(semantic, "available", lambda: True)
    monkeypatch.setattr(semantic, "_embedder",
                        lambda: _FakeModel([1.0, 0.0, 0.0]))
    semantic.index_file().write_text(
        '{"model": "x", "entries": [{"key": "a", "text": "a",'
        ' "vector": [0.0, 1.0, 0.0]}]}', encoding="utf-8")

    assert semantic.search("anything") == [], "an orthogonal vector matched"


def test_the_index_keeps_the_text_each_vector_was_made_from(monkeypatch):
    """The condition this feature was allowed to exist on.

    "Why did it match that?" has to have an answer somebody can read, or the
    memory becomes a box nobody can debug — which is the opposite of what this
    package is for, and the reason it defaults to off.
    """
    monkeypatch.setattr(semantic, "available", lambda: True)
    monkeypatch.setattr(semantic, "_embedder",
                        lambda: _FakeModel([0.5, 0.5, 0.5]))
    memory.remember("car mot", body="The car is due for its MOT")

    count, _said = semantic.rebuild()
    assert count == 1

    import json
    stored = json.loads(semantic.index_file().read_text(encoding="utf-8"))
    entry = stored["entries"][0]
    assert "MOT" in entry["text"], "the index cannot be read by a person"
    assert entry["vector"], "no vector was stored"


def test_the_index_is_json_not_an_opaque_database():
    """Stated as a rule rather than left to whoever edits this next."""
    assert semantic.index_file().suffix == ".json"


class _FakeModel:
    """Stands in for the embedder, so no model is ever downloaded in a test."""

    def __init__(self, vector):
        self._vector = vector

    def embed(self, texts):
        for _text in texts:
            yield list(self._vector)
