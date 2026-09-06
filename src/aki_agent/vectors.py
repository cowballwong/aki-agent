"""The vector store: your notes, and the documents on your shelf.

WHAT IT IS FOR, WHICH IS TWO DIFFERENT THINGS
---------------------------------------------
**Your notes.** A few hundred short facts. Searching them by meaning finds
"the roof leak job" when you wrote "water ingress at the Hatfield site". This
already worked before Chroma existed here, on a plain JSON index — see
`semantic.py` — and at that size a real database buys nothing.

**Your documents.** The Knowledge shelf stores a *pointer* to a file, not the
file. So an assistant that has been given a 200-page Approved Document knows
the document exists, knows what you said it is for, and has never read a word
of it. Splitting those pages into passages, embedding each one and keeping
where it came from is what lets a question be answered with the paragraph that
answers it.

That second one is why Chroma is worth installing. A few hundred notes fit in
a JSON file; a shelf of documents is tens of thousands of passages, and that
is a database.

NOTHING IS A HARD DEPENDENCY
----------------------------
`pyproject.toml` says, in as many words, that the core install stays at one
runtime dependency. Everything here is fetched on request and the page says
what each piece is for before it fetches it — the same call made for
`fastembed` on the Knowledge page, and for the same reason: a student who will
never search a document by meaning should not be made to download the
machinery for it.

ONE EMBEDDING MODEL, NOT TWO
----------------------------
Chroma will happily supply its own embedding function, which would mean this
package carried two models that disagree about what "similar" means, and a
note indexed under one could never be compared with a passage indexed under
the other. So the vectors are computed here, with `semantic`'s model, and
handed to Chroma to store. Chroma is the shelf; it is not the reader.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import atomic, paths

# Each piece, and what it is for in words somebody deciding would use.
#
# Ordered by how much they cost, because that is the order somebody reads a
# list of downloads in.
PIECES: tuple[tuple[str, str], ...] = (
    ("pypdf", "reads the words out of a PDF"),
    ("chromadb", "the store that holds the passages and searches them"),
    ("fastembed", "turns text into numbers so meaning can be compared "
                  "(a few hundred megabytes — it includes the model)"),
)

# How a document is cut up.
#
# Long enough to hold a whole clause of a regulation, short enough that a
# match points at something a person can read in one go. Overlapping, because
# the sentence that answers a question is otherwise exactly the one that falls
# across a boundary and is never returned whole.
CHUNK = 1200
OVERLAP = 200

# What can be read without asking the user to install anything else.
PLAIN_TEXT = {".md", ".markdown", ".txt", ".csv", ".json", ".yaml", ".yml"}


def store_dir() -> Path:
    """Where Chroma keeps its files.

    Inside the package's own folder, not `~/.claude`: this is machinery, not
    something the user wrote, and it can be deleted and rebuilt at any time.
    """
    return paths.state_dir() / "vector-store"


def switch_file() -> Path:
    return paths.state_dir() / "vector-store.json"


# ---------------------------------------------------------------------------
# What is installed, and getting the missing parts
# ---------------------------------------------------------------------------

def _importable(name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):                      # noqa: BLE001
        return False


def missing() -> list[str]:
    """Which pieces are not here yet, in the order they are listed."""
    return [name for name, _why in PIECES if not _importable(name)]


def ready() -> bool:
    return not missing()


def install() -> tuple[bool, str]:
    """Fetch whatever is missing, in one press.

    One button rather than three. Three separate installs is three chances to
    stop half way and end up with a page that can embed but not store, which
    reports itself as neither working nor broken.

    It takes minutes. Whatever calls this has to say so first.
    """
    import subprocess
    import sys

    wanted = missing()
    if not wanted:
        return True, "Everything it needs is already here."

    try:
        finished = subprocess.run(
            [sys.executable, "-m", "pip", "install", *wanted],
            capture_output=True, text=True, timeout=3600, check=False)
    except subprocess.TimeoutExpired:
        return False, ("It was still downloading after an hour and was "
                       "stopped. Trying again picks up what it already got.")
    except (OSError, subprocess.SubprocessError) as problem:
        return False, f"It could not be started: {problem}"

    if finished.returncode != 0:
        detail = (finished.stderr or finished.stdout or "").strip().splitlines()
        return False, ("It did not install: "
                       + (detail[-1] if detail else "pip gave no reason."))

    # The import system caches what it saw in each directory, so a package
    # that arrived during this process's lifetime is invisible until the
    # caches are dropped.
    import importlib
    importlib.invalidate_caches()

    still = missing()
    if still:
        # Asked again rather than trusted. pip can exit 0 having installed
        # into a different Python than the one running this.
        return False, ("pip reported success but " + ", ".join(still) +
                       " still cannot be loaded here. That usually means it "
                       "went into a different Python.")

    return True, "Ready. You can index your documents now."


# ---------------------------------------------------------------------------
# Reading a document
# ---------------------------------------------------------------------------

def read_text(path: Path) -> tuple[str, str]:
    """The words in one file, and anything worth saying about the attempt.

    Returns `("", reason)` rather than raising. A shelf of forty documents
    will contain one that is a scan with no text layer, one that is locked,
    and one somebody moved — and none of those should stop the other
    thirty-seven being indexed.
    """
    suffix = path.suffix.lower()

    if suffix in PLAIN_TEXT:
        try:
            return path.read_text(encoding="utf-8", errors="replace"), ""
        except OSError as problem:
            return "", f"could not be read: {problem}"

    if suffix == ".pdf":
        if not _importable("pypdf"):
            return "", "needs pypdf, which is not installed"
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            pages = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:                          # noqa: BLE001
                    pages.append("")
            found = "\n\n".join(pages).strip()
        except Exception as problem:                       # noqa: BLE001
            return "", f"could not be opened: {type(problem).__name__}"

        if not found:
            # The commonest disappointment, and worth naming exactly. A
            # scanned drawing set has no text in it at all, and "0 passages"
            # with no reason reads as a bug in this software.
            return "", ("no text in it — it is probably a scan, which would "
                        "need character recognition")
        return found, ""

    return "", f"{suffix or 'that kind of file'} is not something it can read"


def into_passages(text: str) -> list[str]:
    """Cut text into overlapping passages.

    Split on the character count rather than on sentences on purpose: the
    documents this is for are regulations and reports, where a "sentence" runs
    to a numbered clause with sub-paragraphs and a table in the middle.
    """
    text = " ".join(text.split())
    if not text:
        return []

    found: list[str] = []
    start = 0
    while start < len(text):
        found.append(text[start:start + CHUNK])
        if start + CHUNK >= len(text):
            break
        start += CHUNK - OVERLAP
    return found


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def _collection():
    """Chroma's collection, created if need be. Raises if Chroma is absent."""
    import chromadb

    # `keeper`, not `client`: the engine's own code may not carry
    # profession vocabulary, and an architect has clients. Chroma's
    # class name is Chroma's business; the variable is ours.
    keeper = chromadb.PersistentClient(path=str(store_dir()))
    # Cosine, to match how `semantic.py` compares its vectors. Left at the
    # default (L2) the two halves of this package would rank the same pair of
    # texts differently, which is the sort of disagreement nobody finds until
    # they are comparing two search results and cannot see why.
    return keeper.get_or_create_collection(
        name="documents", metadata={"hnsw:space": "cosine"})


@dataclass
class Indexed:
    """What one indexing pass did."""

    documents: int = 0
    passages: int = 0
    skipped: list[str] = field(default_factory=list)

    def sentence(self) -> str:
        if not self.documents and not self.skipped:
            return "There is nothing on the shelf to read yet."
        said = (f"Read {self.documents} document(s) into {self.passages} "
                f"passage(s).")
        if self.skipped:
            said += f" {len(self.skipped)} could not be read."
        return said


def index() -> tuple[bool, Indexed | str]:
    """Read every document on the shelf into the store.

    Rebuilds rather than adds. Working out what changed since last time needs
    a record of what was indexed and when, and that record is one more thing
    that can disagree with the truth -- for a few dozen documents, reading
    them again is cheaper than being wrong about which ones moved.
    """
    if not ready():
        return False, ("It still needs " + ", ".join(missing()) + ".")

    from . import knowledge, semantic

    try:
        collection = _collection()
    except Exception as problem:                           # noqa: BLE001
        return False, f"The store would not open: {type(problem).__name__}"

    done = Indexed()
    texts: list[str] = []
    metas: list[dict] = []
    ids: list[str] = []

    for entry in knowledge.read_all():
        if entry.kind != "document":
            continue
        path = Path(entry.target)
        if not path.exists():
            done.skipped.append(f"{entry.title}: the file is not there")
            continue

        text, trouble = read_text(path)
        if trouble:
            done.skipped.append(f"{entry.title}: {trouble}")
            continue

        passages = into_passages(text)
        if not passages:
            done.skipped.append(f"{entry.title}: nothing to read")
            continue

        done.documents += 1
        for number, passage in enumerate(passages):
            texts.append(passage)
            # Where it came from, kept with the passage. Without this a match
            # is a paragraph with no source, which is worse than no match --
            # you cannot check it, so you cannot use it.
            metas.append({"title": entry.title, "source": str(path),
                          "key": entry.key, "passage": number})
            ids.append(f"{entry.key}:{number}")

    done.passages = len(texts)

    try:
        # Cleared first, since this is a rebuild. `delete` with no filter is
        # refused by Chroma, so the collection goes and comes back.
        import chromadb

        keeper = chromadb.PersistentClient(path=str(store_dir()))
        try:
            keeper.delete_collection("documents")
        except Exception:                                  # noqa: BLE001
            pass                       # not there yet, which is fine
        collection = keeper.get_or_create_collection(
            name="documents", metadata={"hnsw:space": "cosine"})

        if texts:
            model = semantic._embedder()
            vectors = [[float(number) for number in one]
                       for one in model.embed(texts)]
            collection.add(ids=ids, documents=texts, metadatas=metas,
                           embeddings=vectors)
    except Exception as problem:                           # noqa: BLE001
        return False, (f"The passages could not be stored: "
                       f"{type(problem).__name__}: {problem}")

    atomic.write_json(switch_file(), {
        "on": True,
        "documents": done.documents,
        "passages": done.passages,
    })
    return True, done


def state() -> dict:
    """What the tab needs to draw itself."""
    stored = atomic.read_json(switch_file(), default={}) or {}
    if not isinstance(stored, dict):
        stored = {}

    return {
        "ready": ready(),
        "missing": missing(),
        "pieces": [{"name": name, "why": why, "here": _importable(name)}
                   for name, why in PIECES],
        "documents": int(stored.get("documents") or 0),
        "passages": int(stored.get("passages") or 0),
        "where": str(store_dir()),
    }


def search(query: str, limit: int = 5) -> list[dict]:
    """Passages that mean something like the question.

    Answers an empty list rather than raising when the store is not set up,
    because every caller of this is showing results next to other results --
    a search that raises takes the whole page with it.
    """
    query = (query or "").strip()
    if not query or not ready():
        return []

    from . import semantic

    try:
        collection = _collection()
        model = semantic._embedder()
        vector = [float(number) for number in list(model.embed([query]))[0]]
        answer = collection.query(query_embeddings=[vector],
                                  n_results=max(1, min(20, limit)))
    except Exception:                                      # noqa: BLE001
        return []

    found = []
    documents = (answer.get("documents") or [[]])[0]
    metadatas = (answer.get("metadatas") or [[]])[0]
    distances = (answer.get("distances") or [[]])[0]

    for text, meta, distance in zip(documents, metadatas, distances):
        found.append({
            "text": text,
            "title": (meta or {}).get("title", ""),
            "source": (meta or {}).get("source", ""),
            # Cosine distance, so nearer to zero is better. Turned into
            # something a person reads the right way round.
            "score": round(1.0 - float(distance), 3),
        })
    return found


def forget() -> tuple[bool, str]:
    """Throw the store away. The documents themselves are never touched."""
    import shutil

    try:
        if store_dir().exists():
            shutil.rmtree(store_dir())
    except OSError as problem:
        return False, f"Could not clear it: {problem}"

    atomic.write_json(switch_file(), {"on": False,
                                      "documents": 0, "passages": 0})
    return True, ("Cleared. Your documents are untouched — this only threw "
                  "away what had been read out of them.")
