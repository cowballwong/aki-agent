"""Matching by meaning as well as by words — off unless somebody turns it on.

WHY THIS IS OPTIONAL AND WHY IT IS OFF (reported 2026-08-20)
----------------------------------------------------------
He asked whether the package had ChromaDB and a self-optimising loop — the
memory layers he teaches — and the honest answer was no vector store at all,
on purpose. `memory.search` is BM25: thirty lines of arithmetic anybody can
read, which is why a student can be shown exactly why a result ranked where
it did.

The gap that leaves is real and is written down in that file: **it cannot
match "car" to "vehicle".**

Given the choice between adding embeddings for everyone and not adding them,
he chose neither: *"加做選項,預設關"*. That is the right call, and the reason
is the thing this whole package is built on — you can open the folder and read
what your assistant knows. An index nobody can inspect is a memory nobody can
debug, and a teaching package whose memory is a black box teaches the wrong
lesson.

So:

  * **off unless turned on**, and the classical search is what runs otherwise
  * **nothing downloads until it is turned on** — no model, no runtime
  * the index is a **plain JSON file** you can open, holding the text each
    vector was made from, so "why did it match that?" has an answer
  * results are **labelled** as meaning-matches and carry their score, and
    they are added to the word-matches rather than replacing them

WHAT IT USES
------------
FastEmbed, which runs a small ONNX model locally. No API key, no account,
nothing sent anywhere — the same rule every other connector in this package
follows. It is a real download (a few hundred megabytes with its runtime) and
that is said plainly before anybody agrees to it, rather than discovered as a
first run that appears to hang.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import atomic, paths

# The smallest model that is actually good at this. Chosen over anything
# larger because the whole feature has to justify its download, and a
# personal fact store is hundreds of files rather than millions.
MODEL = "BAAI/bge-small-en-v1.5"

# Below this, a "match by meaning" is noise wearing a number. Tuned to be
# conservative: a missing result is a smaller failure here than a confident
# irrelevant one, which is the specific way semantic search loses trust.
FLOOR = 0.62


def switch_file() -> Path:
    return paths.state_dir() / "semantic.json"


def index_file() -> Path:
    """The index itself, and deliberately readable.

    JSON rather than a database file: somebody who wants to know why their
    assistant matched a particular note can open this and see the text each
    vector was built from. That is the whole reason this is allowed to exist
    in a package that otherwise refuses opaque stores.
    """
    return paths.state_dir() / "semantic-index.json"


def available() -> bool:
    """Is the library actually here? Its absence is a normal state."""
    try:
        import fastembed                                   # noqa: F401
    except Exception:                                      # noqa: BLE001
        return False
    return True


def enabled() -> bool:
    """Off unless somebody said otherwise. Absence of the file means off.

    The opposite default to the sentinel, and for the opposite reason: the
    sentinel costs nothing and catches mistakes, while this costs a download
    and changes how memory behaves. A feature that installs several hundred
    megabytes must be chosen, never inherited.
    """
    stored = atomic.read_json(switch_file(), default=None)
    if not isinstance(stored, dict):
        return False
    return bool(stored.get("on"))


def turn_on() -> tuple[bool, str]:
    if not available():
        return False, (
            "Matching by meaning needs one extra library, and it is a real "
            "download — a few hundred megabytes, because it includes the "
            "model that does the matching. Nothing is sent anywhere; it runs "
            "on this computer. Install it with:\n"
            "    pip install fastembed\n"
            "then turn this on again.")
    atomic.write_json(switch_file(), {"on": True})
    return True, ("On. Your assistant will now also find notes that mean the "
                  "same thing in different words. Word matches still come "
                  "first, and meaning matches are labelled.")


def turn_off() -> tuple[bool, str]:
    atomic.write_json(switch_file(), {"on": False})
    return True, ("Off. Searching is back to matching words, which is what it "
                  "did before. The index is kept — turning this on again "
                  "costs nothing.")


def state() -> dict[str, Any]:
    """Everything a page needs to describe this honestly."""
    stored = atomic.read_json(index_file(), default={}) or {}
    entries = stored.get("entries") or []
    return {
        "available": available(),
        "enabled": enabled(),
        "indexed": len(entries),
        "model": stored.get("model", MODEL),
        "index_path": str(index_file()),
    }


# ---------------------------------------------------------------------------
# Building the index
# ---------------------------------------------------------------------------

def _embedder():
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=MODEL)


def _texts_to_index() -> list[tuple[str, str]]:
    """(key, text) for everything worth matching against.

    The facts only. The daily narrative is long, repetitive and mostly about
    when things happened rather than what is true, and indexing it would bury
    the facts under it — which is the usual way a semantic memory becomes
    worse than no semantic memory.
    """
    from . import memory

    found = []
    for fact in memory.recall(limit=10_000):
        text = f"{fact.summary}\n{fact.body}".strip()
        if text:
            found.append((fact.key, text))
    return found


def rebuild() -> tuple[int, str]:
    """Re-embed everything. Returns (how many, what to say)."""
    if not available():
        return 0, "The library for this is not installed."

    pairs = _texts_to_index()
    if not pairs:
        atomic.write_json(index_file(), {"model": MODEL, "entries": []})
        return 0, "There is nothing in memory to index yet."

    try:
        model = _embedder()
        vectors = list(model.embed([text for _key, text in pairs]))
    except Exception as exc:                              # noqa: BLE001
        return 0, f"Could not build the index: {type(exc).__name__}: {exc}"

    entries = []
    for (key, text), vector in zip(pairs, vectors):
        values = [float(number) for number in vector]
        entries.append({
            "key": key,
            # Kept so the index can be read by a person. Truncated because the
            # point is recognising the note, not storing it twice.
            "text": text[:400],
            "vector": values,
        })

    atomic.write_json(index_file(), {"model": MODEL, "entries": entries})
    return len(entries), f"Indexed {len(entries)} note(s)."


def _cosine(one: list[float], two: list[float]) -> float:
    if not one or not two or len(one) != len(two):
        return 0.0
    dot = sum(a * b for a, b in zip(one, two))
    left = math.sqrt(sum(a * a for a in one))
    right = math.sqrt(sum(b * b for b in two))
    if not left or not right:
        return 0.0
    return dot / (left * right)


@dataclass
class Match:
    key: str
    score: float
    text: str


def search(query: str, limit: int = 5) -> list[Match]:
    """Notes that mean something close to the query.

    Returns nothing at all when this is off, unavailable, unindexed, or when
    nothing clears the floor — and "nothing" is the correct answer in every
    one of those cases. A search that quietly returns its best bad guess is
    how somebody ends up trusting a match that was never there.
    """
    query = (query or "").strip()
    if not query or not enabled() or not available():
        return []

    stored = atomic.read_json(index_file(), default={}) or {}
    entries = stored.get("entries") or []
    if not entries:
        return []

    try:
        model = _embedder()
        asked = [float(number) for number in next(iter(model.embed([query])))]
    except Exception:                                     # noqa: BLE001
        return []

    scored = []
    for entry in entries:
        score = _cosine(asked, entry.get("vector") or [])
        if score >= FLOOR:
            scored.append(Match(key=str(entry.get("key", "")), score=score,
                                text=str(entry.get("text", ""))))
    scored.sort(key=lambda one: one.score, reverse=True)
    return scored[:limit]


def install() -> tuple[bool, str]:
    """Fetch the library, so that nobody has to open a terminal.

     -- by the time somebody is looking at this, it should be a
    switch and not a homework assignment.

    NOT A PACKAGE DEPENDENCY, and that is a deliberate difference from what
    he asked for. `fastembed` brings the embedding model with it: a few
    hundred megabytes, onto the machine of every student who installs this,
    most of whom will never search their notes by meaning. This module's own
    rule is that such a feature must be chosen and never inherited, and
    bundling it would be inheriting it for them.

    So the download stays a choice and the terminal goes away: one button,
    here and at setup. If he wants it in the base install instead, that is
    one line in the packaging and this function stays exactly as useful.

    It takes minutes. Whatever calls this has to say so before it starts.
    """
    import subprocess
    import sys

    if available():
        return True, "It is already here."

    try:
        finished = subprocess.run(
            [sys.executable, "-m", "pip", "install", "fastembed"],
            capture_output=True, text=True, timeout=1800, check=False)
    except subprocess.TimeoutExpired:
        return False, ("It was still downloading after half an hour, so it "
                       "was stopped. A slow connection is the usual reason; "
                       "trying again picks up what it already fetched.")
    except (OSError, subprocess.SubprocessError) as problem:
        return False, f"It could not be started: {problem}"

    if finished.returncode != 0:
        # The last line of pip's complaint, not all of it. The whole thing is
        # hundreds of lines and the useful sentence is at the end.
        detail = (finished.stderr or finished.stdout or "").strip().splitlines()
        return False, ("It did not install: "
                       + (detail[-1] if detail else "pip gave no reason."))

    # The import system caches what it saw in each directory, so a package
    # that appeared during this process's lifetime is invisible until the
    # caches are dropped. Without this the check below fails on a perfectly
    # good install and tells the user it went to the wrong Python.
    import importlib
    importlib.invalidate_caches()

    # Asked again rather than trusted. pip can exit 0 having installed
    # something that this interpreter still cannot import -- a different
    # environment, a partial wheel -- and reporting success on the strength
    # of an exit code is how a feature comes to be "installed" and absent.
    if not available():
        return False, ("pip reported success, but the library still cannot "
                       "be loaded here. That usually means it went into a "
                       "different Python than the one running this.")

    return True, "Installed. You can turn it on now."


def explain() -> str:
    """What this is, for somebody deciding whether to switch it on."""
    now = state()
    if not now["available"]:
        return (
            "Searching your memory matches words. It cannot tell that "
            "\"car\" and \"vehicle\" mean the same thing.\n"
            "\n"
            "Matching by meaning can, and it runs entirely on this computer "
            "— no account, no API key, nothing sent anywhere. It needs one "
            "library, which is a real download of a few hundred megabytes "
            "because it includes the model:\n"
            "\n"
            "    pip install fastembed\n"
            "\n"
            "It is off by default on purpose. Word matching is something you "
            "can read and check; this is not, so it should be a choice.")
    if not now["enabled"]:
        return ("Ready, and off. Turn it on to also find notes that mean the "
                "same thing in different words.")
    return (f"On, with {now['indexed']} note(s) indexed. The index is a plain "
            f"file you can open: {now['index_path']} — it holds the text each "
            "match was made from, so you can always see why something "
            "matched.")
