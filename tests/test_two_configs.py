"""THE test. If this fails, the package has become a single-profession tool.

The brief for this project put it plainly: the same engine, given two
different configuration files, must produce a coherent dashboard for two
unrelated occupations without a code change.

So this file loads an architect's config and a music teacher's config, runs
the identical loader over both, and checks that everything which differs is
configuration and everything which is shared is code.

There is also a guard test at the bottom which reads the engine's own source
and fails if a profession-specific word has crept into it. That one is the
canary: it will catch the day someone "just adds a field to the model".
"""

from __future__ import annotations

import ast
import datetime as _dt
import re
from pathlib import Path

import pytest

from aki_agent import config as config_module
from aki_agent import workspace as workspace_module

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "configs" / "examples"
ENGINE_DIR = REPO_ROOT / "src" / "aki_agent"

CONFIG_A = EXAMPLES / "architecture.yaml"
CONFIG_B = EXAMPLES / "music_teaching.yaml"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def architecture():
    return config_module.load(CONFIG_A)


@pytest.fixture
def music():
    return config_module.load(CONFIG_B)


# ---------------------------------------------------------------------------
# Both configs are valid
# ---------------------------------------------------------------------------

def test_both_configs_load_and_validate(architecture, music):
    """Neither example config has a declaration problem.

    Note what this does NOT assert: that the user's *data* is clean. The
    architecture fixture deliberately contains a bad value and a missing file,
    because real folders are untidy and the engine has to cope.
    """
    assert architecture.validate() == []
    assert music.validate() == []


def test_the_two_configs_really_are_unrelated():
    """Guard the test itself.

    If someone later edits the examples so they resemble each other, this test
    would keep passing while proving nothing. So: assert up front that the two
    configs share no field keys and no item label.
    """
    a = config_module.load(CONFIG_A).layout.schema
    b = config_module.load(CONFIG_B).layout.schema

    assert a.item_label != b.item_label
    a_keys = {field.key for field in a.fields}
    b_keys = {field.key for field in b.fields}
    assert not (a_keys & b_keys), (
        "the two example configs share field keys, so this test would no "
        f"longer prove anything: {a_keys & b_keys}"
    )


# ---------------------------------------------------------------------------
# The same loader produces both dashboards
# ---------------------------------------------------------------------------

def test_same_loader_reads_both_workspaces(architecture, music):
    """One function, two occupations, no branching."""
    space_a = workspace_module.scan(architecture)
    space_b = workspace_module.scan(music)

    assert len(space_a.items) == 3
    assert len(space_b.items) == 2

    # The engine calls them by whatever the user calls them.
    assert space_a.schema.item_label_plural == "Projects"
    assert space_b.schema.item_label_plural == "Students"


def test_declared_fields_are_the_only_fields(architecture, music):
    """An item carries exactly the fields its own config declared."""
    space_a = workspace_module.scan(architecture)
    space_b = workspace_module.scan(music)

    item_a = space_a.item_by_key("riverside-school-hall")
    item_b = space_b.item_by_key("amelia-hart")

    assert set(item_a.values) == {
        "stage", "completion", "client", "next_deadline", "on_site",
        "disciplines",
    }
    assert set(item_b.values) == {
        "grade", "instrument", "next_lesson", "fees_settled", "pieces",
    }

    # And crucially, neither knows anything about the other's vocabulary.
    assert "grade" not in item_a.values
    assert "stage" not in item_b.values


def test_values_are_typed_correctly(architecture, music):
    """Each declared type is coerced properly, in both configs."""
    item = workspace_module.scan(architecture).item_by_key(
        "riverside-school-hall")

    assert item.values["stage"].value == "technical"
    assert item.values["completion"].value == 65.0
    assert item.values["completion"].display == "65%"
    assert item.values["client"].value == "Riverside Academy Trust"
    assert item.values["next_deadline"].value == _dt.date(2026, 9, 30)
    assert item.values["on_site"].value is False
    assert item.values["disciplines"].value == [
        "structural", "services", "acoustics"]

    student = workspace_module.scan(music).item_by_key("amelia-hart")

    assert student.values["grade"].value == "grade 5"
    assert student.values["instrument"].value == "piano"
    assert student.values["next_lesson"].value == _dt.date(2026, 8, 19)
    assert student.values["fees_settled"].value is True
    assert student.values["pieces"].value == [
        "Bach Invention 8", "Chopin Waltz Op69 No2"]


def test_summary_files_are_configurable(architecture, music):
    """The music config declares three summary files, not four."""
    assert architecture.layout.schema.summary_files == (
        "state", "actions", "waiting", "history")
    assert music.layout.schema.summary_files == (
        "state", "actions", "history")

    student = workspace_module.scan(music).item_by_key("amelia-hart")
    # It must not report `waiting.md` missing -- this user never declared it.
    assert student.missing_files == []


def test_counting_works_for_any_enum_field(architecture, music):
    """The dashboard's summary strip is field-agnostic."""
    space_a = workspace_module.scan(architecture)
    space_b = workspace_module.scan(music)

    stages = space_a.count_by_field("stage")
    assert stages["technical"] == 1
    assert stages["construction"] == 1

    instruments = space_b.count_by_field("instrument")
    assert instruments == {"piano": 1, "violin": 1}


# ---------------------------------------------------------------------------
# Honest failure: bad data must be visible, never silently wrong
# ---------------------------------------------------------------------------

def test_bad_values_are_reported_not_guessed(architecture):
    """The messy fixture exercises every honest-failure path.

    `brambling-court` has a stage that is not in the allowed list, a
    percentage of 120, a yes/no field reading "maybe", and no waiting.md.

    The rule being enforced: a panel that displays wrong data confidently is
    worse than a panel that displays nothing.
    """
    item = workspace_module.scan(architecture).item_by_key(
        "brambling-court")

    assert item.has_problems

    stage = item.values["stage"]
    assert stage.ok is False
    assert "not one of the allowed values" in stage.problem
    assert stage.display == "?"          # never the raw bad value

    completion = item.values["completion"]
    assert completion.ok is False
    assert "between 0 and 100" in completion.problem

    on_site = item.values["on_site"]
    assert on_site.ok is False

    assert item.missing_files == ["waiting.md"]

    # A field the user simply left out reads as blank, and is NOT confused
    # with a field that was there and unreadable. `brambling-court` declares
    # no deadline at all, which is a perfectly normal thing for an early
    # enquiry -- blank is an answer, not a fault.
    blank = item.values["next_deadline"]
    assert blank.ok is True
    assert blank.present is False
    assert blank.display == "--"

    # Contrast the three states side by side, because this is the distinction
    # the whole honest-failure design rests on.
    assert item.values["stage"].display == "?"        # present but unusable
    assert item.values["next_deadline"].display == "--"  # simply absent
    assert item.values["client"].display == "Brambling Developments"  # good


def test_missing_workspace_is_reported_not_crashed(architecture, tmp_path):
    """A cloud drive that has not mounted yet is a normal state."""
    architecture.layout.root = tmp_path / "not-here"
    space = workspace_module.scan(architecture)

    assert space.items == []
    assert any("not available" in problem for problem in space.problems)


# ---------------------------------------------------------------------------
# Ownership must be explicit
# ---------------------------------------------------------------------------

def test_ownership_is_explicit_not_inferred(architecture, music):
    """Identity comes from configured aliases, never from guessing.

    The system this package derives from decided whether work belonged to its
    user by substring-matching their name in free text, which meant a second
    person installing it would be told none of their work was theirs.
    """
    assert architecture.user.owns("Issued by Sam O on Tuesday") is True
    assert architecture.user.owns("Issued by the contractor") is False

    # And one user's aliases mean nothing to the other's config.
    assert music.user.owns("Issued by Sam O on Tuesday") is False
    assert music.user.owns("Wing to confirm the lesson time") is True


# ---------------------------------------------------------------------------
# The canary
# ---------------------------------------------------------------------------

# Words belonging to one profession or another. None of these may appear in
# the engine's executable code or in any string it can print.
#
# Explanatory prose is exempt -- the docstrings deliberately use concrete
# examples like "an architect's items have a work stage", because a comment
# that cannot name an example teaches nothing. The test strips comments and
# docstrings before looking, so an example in prose is fine and a literal in
# code is not.
FORBIDDEN_VOCABULARY = (
    # from example config A
    "riba", "feasibility", "developed design", "handover", "consultant",
    "practice", "planning permission", "contractor", "drawing register",
    # from example config B
    "grade", "instrument", "piano", "violin", "lesson", "exam board",
    "pupil", "scales",
    # generic profession words that would betray a single-tenant assumption
    "client", "matter", "patient", "tenant", "invoice",
)


def _executable_text(source_path: Path) -> str:
    """Return a file's code and string literals, with docstrings removed.

    Uses the parser rather than a regular expression, because a regex over
    source code is a guess and this test needs to be trustworthy enough that
    a failure is believed rather than deleted.
    """
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    # Collect the id() of every node that is a docstring, so they can be
    # skipped when we walk the constants.
    docstring_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstring_nodes.add(id(body[0].value))

    pieces: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstring_nodes:
                pieces.append(node.value)
        elif isinstance(node, ast.Name):
            pieces.append(node.id)
        elif isinstance(node, ast.Attribute):
            pieces.append(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            pieces.append(node.name)
        elif isinstance(node, ast.arg):
            pieces.append(node.arg)

    return "\n".join(pieces).casefold()


# The one documented exception, and why it is a refinement of the rule rather
# than a hole in it.
#
# "Client ID" and "Client secret" are the names Google prints on its own
# screen, and the setup instructions have to use those words or somebody
# cannot match what they are reading to what they are looking at. That is a
# field label, not a profession's word for the people it serves.
#
# So the phrases are removed before matching and **`client` on its own stays
# forbidden everywhere** -- which is the thing the rule was written to catch.
# Anything wanting to slip the word past this has to spell it as one of these
# two exact phrases, which is a conspicuous thing to find in a diff.
#
# Written this way rather than by exempting a file: a per-file exemption grows
# quietly and stops meaning anything, and it would have hidden a genuine
# "client" in the same file.
OAUTH_FIELD_NAMES = (
    "client id", "client secret",
    # 2026-09-04. A vendor's URL path, not a word this package chose:
    # `https://api.bigdatacloud.net/data/reverse-geocode-client` is how the
    # weather turns "use my location" into a town name instead of the words
    # "Your location".
    #
    # Spent here rather than by splitting the string in `today.py`, which is
    # what a person quietly working around this test would do and would leave
    # nothing to find. It is one exact path segment: a real "client" anywhere
    # else in the engine, in that file included, still fails.
    "reverse-geocode-client",
)


def _spend_the_exception(text: str) -> str:
    for phrase in OAUTH_FIELD_NAMES:
        text = text.replace(phrase, "oauth-field")
    return text


def test_engine_source_contains_no_profession_vocabulary():
    """The canary. If this fails, a domain assumption has entered the engine.

    A NOTE ON WHY THIS MATCHES WHOLE WORDS
    --------------------------------------
    The first version of this test matched substrings, and immediately failed
    on the word `frontmatter` -- because "matter" is inside it.

    That is worth keeping in the file rather than quietly fixing, because it
    is the *same* mistake this package exists to correct: the source system
    decided who owned a piece of work by looking for a name as a substring of
    free text. Substring matching feels like it is being generous. It is
    actually just being wrong in a way that is hard to see.

    So this matches on word boundaries, and `frontmatter` is left alone.
    """
    offences: list[str] = []

    # rglob, not glob: the dashboard lives in a sub-package and is precisely
    # where a profession word would creep in, because that is the layer where
    # somebody is tempted to write a column heading.
    for source_path in sorted(ENGINE_DIR.rglob("*.py")):
        text = _spend_the_exception(_executable_text(source_path))
        for word in FORBIDDEN_VOCABULARY:
            # \b is a word boundary: "grade" matches "grade" but not "upgrade".
            if re.search(rf"\b{re.escape(word)}\b", text):
                offences.append(f"{source_path.name}: '{word}'")

    assert not offences, (
        "profession-specific vocabulary found in the engine's executable "
        "code. Every one of these belongs in the user's config file, not in "
        "the code:\n  " + "\n  ".join(offences)
    )


def test_the_spent_phrases_are_exact_and_no_wider():
    """The exception has to stay small enough to read in one line.

    `client` alone is still an offence -- that is the profession word the rule
    exists for. Only exact strings that no author chose are spent: the two
    field labels Google prints on its own screen, and one vendor's URL path.
    This fails if anybody widens that later, which is the point of it.
    """
    assert OAUTH_FIELD_NAMES == (
        "client id", "client secret", "reverse-geocode-client")

    # Still caught.
    assert "client" in _spend_the_exception("a client of the practice")
    assert "client" in _spend_the_exception("clients")            # substring
    assert "client" in _spend_the_exception("the reverse geocode client")
    # Spent, and only in these exact forms.
    assert "client" not in _spend_the_exception("paste the client id here")
    assert "client" not in _spend_the_exception("the client secret")
    assert "client" not in _spend_the_exception(
        "https://api.bigdatacloud.net/data/reverse-geocode-client")
