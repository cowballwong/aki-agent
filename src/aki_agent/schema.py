"""The declarative item schema. This is the most important file in the package.

THE PROBLEM THIS SOLVES
-----------------------
The system this package is derived from has a dashboard whose data model is
*generic in shape* but *specific in its fields*. Its shape is fine: a workspace
contains items; each item has a state summary, a list of actions, a list of
things it is waiting on, and a history. That structure fits almost any kind of
work -- projects, clients, legal matters, courses, properties, patients.

But the fields inside were written as Python attributes belonging to one
profession. To use it for a different job you would have to edit Python.

So the rule for this package is:

    The SHAPE is code. The FIELDS are configuration.

An architect's items have a RIBA stage. A tutor's items have a exam board and a
next lesson date. A letting agent's items have a rent review date. None of
those words may ever appear in this file, or anywhere else in the engine.

THE TEST THAT PROVES IT WORKED
------------------------------
`tests/test_two_configs.py` loads two configuration files describing two
unrelated occupations and asserts that the same engine produces a coherent
dashboard for both, with no code change. If you ever find yourself thinking
"I'll just add a field to the model", stop: that is the exact failure this
design exists to prevent, and it ends with a single-profession dashboard
wearing a new coat of paint.

A NOTE ON FAILURE BEHAVIOUR
---------------------------
Nothing in this file raises when a user's data is untidy. A person's real
folder of notes is always untidy. Instead, a value that cannot be read is
returned as "unknown, and here is why".

That is a deliberate inherited lesson: a panel that displays stale or wrong
data *confidently* is worse than a panel that displays nothing. Blank with a
reason beats a plausible wrong number, every time.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field as dataclass_field
from typing import Any


# ---------------------------------------------------------------------------
# Field types
#
# Kept deliberately small. Every type added here is a type the dashboard must
# know how to render and the setup interview must know how to ask about, so
# each one has a real cost. Resist adding more without a concrete need.
# ---------------------------------------------------------------------------

FIELD_TYPES = (
    "text",     # free text, shown as-is
    "enum",     # one of a fixed list of allowed values
    "percent",  # 0-100, rendered as a bar
    "number",   # any number, rendered as-is
    "date",     # ISO date, rendered relative ("in 3 days") plus absolute
    "bool",     # yes/no, rendered as a tick or a dash
    "tags",     # a list of short labels
)

# Where a field's value comes from.
FIELD_SOURCES = (
    "frontmatter",  # read from the YAML block at the top of a summary file
    "computed",     # derived by the engine (e.g. counting open actions)
)


@dataclass(frozen=True)
class Field:
    """One declared attribute of an item.

    `key`     the name used in the user's markdown frontmatter
    `label`   what the dashboard prints -- the user's own words, any language
    `type`    one of FIELD_TYPES
    `values`  the allowed values, for type "enum" only
    `source`  "frontmatter" (the user writes it) or "computed" (we derive it)
    `help`    a sentence shown in the setup interview and in the dashboard
    """

    key: str
    label: str
    type: str = "text"
    values: tuple[str, ...] = ()
    source: str = "frontmatter"
    help: str = ""

    def validate(self) -> list[str]:
        """Return a list of problems with this field *declaration*.

        This checks the config the user wrote, not the data. It runs at load
        time so that a mistyped config is reported once, clearly, rather than
        producing confusing behaviour later.
        """
        problems: list[str] = []

        if not self.key:
            problems.append("a field has no 'key'")
        elif not re.fullmatch(r"[a-z][a-z0-9_]*", self.key):
            problems.append(
                f"field key '{self.key}' should be lower-case letters, "
                "numbers and underscores, starting with a letter"
            )

        if not self.label:
            problems.append(f"field '{self.key}' has no 'label' to display")

        if self.type not in FIELD_TYPES:
            problems.append(
                f"field '{self.key}' has type '{self.type}', which is not one "
                f"of: {', '.join(FIELD_TYPES)}"
            )

        if self.type == "enum" and not self.values:
            problems.append(
                f"field '{self.key}' is an enum but lists no allowed values"
            )

        if self.type != "enum" and self.values:
            problems.append(
                f"field '{self.key}' lists allowed values but its type is "
                f"'{self.type}', not 'enum' -- the values will be ignored"
            )

        if self.source not in FIELD_SOURCES:
            problems.append(
                f"field '{self.key}' has source '{self.source}', which is not "
                f"one of: {', '.join(FIELD_SOURCES)}"
            )

        return problems


@dataclass(frozen=True)
class Value:
    """A single field's value after reading it from a user's file.

    Three states, and the difference between them matters:

      ok=True,  present=True   we read a good value
      ok=True,  present=False  the user simply has not filled this in
      ok=False                 there was something there, we could not use it

    The third case is the one that must never be rendered as if it were the
    second. "Blank" and "wrong" look identical on a dashboard unless you make
    the difference explicit, and a confidently wrong panel is the failure this
    package is trying not to inherit.
    """

    field: Field
    raw: Any = None
    value: Any = None
    ok: bool = True
    present: bool = False
    problem: str = ""

    @property
    def display(self) -> str:
        """A string safe to show a human, in every state."""
        if not self.ok:
            return "?"
        if not self.present:
            return "--"
        if self.field.type == "bool":
            return "yes" if self.value else "no"
        if self.field.type == "percent":
            return f"{self.value:g}%"
        if self.field.type == "tags":
            return ", ".join(self.value)
        if self.field.type == "date":
            return self.value.isoformat()
        return str(self.value)


def read_value(field: Field, raw: Any) -> Value:
    """Turn whatever was in the user's file into a typed Value.

    Never raises. Every route out of this function produces a Value that the
    dashboard can render honestly.
    """
    # Missing entirely, or explicitly blank.
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return Value(field=field, raw=raw, present=False)

    try:
        if field.type == "text":
            return Value(field=field, raw=raw, value=str(raw).strip(),
                         present=True)

        if field.type == "enum":
            text = str(raw).strip()
            # Compare case-insensitively -- a user typing "Active" when the
            # config says "active" has not made a mistake worth punishing.
            for allowed in field.values:
                if text.lower() == allowed.lower():
                    return Value(field=field, raw=raw, value=allowed,
                                 present=True)
            return Value(
                field=field, raw=raw, ok=False,
                problem=(f"'{text}' is not one of the allowed values "
                         f"({', '.join(field.values)})"),
            )

        if field.type == "percent":
            number = float(str(raw).strip().rstrip("%"))
            if not 0 <= number <= 100:
                return Value(field=field, raw=raw, ok=False,
                             problem=f"{number:g} is not between 0 and 100")
            return Value(field=field, raw=raw, value=number, present=True)

        if field.type == "number":
            return Value(field=field, raw=raw, value=float(str(raw).strip()),
                         present=True)

        if field.type == "bool":
            text = str(raw).strip().lower()
            if text in ("true", "yes", "y", "1", "done"):
                return Value(field=field, raw=raw, value=True, present=True)
            if text in ("false", "no", "n", "0"):
                return Value(field=field, raw=raw, value=False, present=True)
            return Value(field=field, raw=raw, ok=False,
                         problem=f"'{raw}' is not a yes/no value")

        if field.type == "date":
            if isinstance(raw, _dt.datetime):
                return Value(field=field, raw=raw, value=raw.date(),
                             present=True)
            if isinstance(raw, _dt.date):
                return Value(field=field, raw=raw, value=raw, present=True)
            return Value(field=field, raw=raw,
                         value=_dt.date.fromisoformat(str(raw).strip()),
                         present=True)

        if field.type == "tags":
            if isinstance(raw, (list, tuple)):
                tags = [str(item).strip() for item in raw if str(item).strip()]
            else:
                tags = [part.strip() for part in str(raw).split(",")
                        if part.strip()]
            return Value(field=field, raw=raw, value=tags, present=bool(tags))

    except (TypeError, ValueError) as exc:
        return Value(field=field, raw=raw, ok=False,
                     problem=f"could not read as {field.type}: {exc}")

    # Unknown type. The declaration validator should have caught this already,
    # but we must still return something honest rather than crash a dashboard.
    return Value(field=field, raw=raw, ok=False,
                 problem=f"unknown field type '{field.type}'")


@dataclass
class ItemSchema:
    """What one 'thing' in this user's workspace looks like.

    Note what is NOT here: any word belonging to any profession. `item_label`
    is whatever the user calls their unit of work -- Project, Client, Matter,
    Course, Property, Case. The engine never needs to know which.
    """

    item_label: str = "Item"
    item_label_plural: str = "Items"

    # The markdown files expected inside each item's folder.
    #
    # This convention -- "each item is a folder containing a few summary
    # markdown files" -- is genuinely domain-neutral, which is why it is kept
    # from the source system rather than reinvented. Only the fields inside
    # were profession-specific.
    summary_files: tuple[str, ...] = ("state", "actions", "waiting", "history")

    fields: tuple[Field, ...] = ()

    def validate(self) -> list[str]:
        """Problems with the schema declaration itself."""
        problems: list[str] = []

        if not self.item_label:
            problems.append("item_label is empty -- what does the user call "
                            "one unit of their work?")
        if not self.summary_files:
            problems.append("summary_files is empty -- there would be nothing "
                            "to read")

        seen: set[str] = set()
        for field in self.fields:
            problems.extend(field.validate())
            if field.key in seen:
                problems.append(f"field key '{field.key}' is declared twice")
            seen.add(field.key)

        return problems

    def field_by_key(self, key: str) -> Field | None:
        for field in self.fields:
            if field.key == key:
                return field
        return None

    def read_all(self, frontmatter: dict) -> dict[str, Value]:
        """Read every declared field out of one item's frontmatter."""
        return {
            field.key: read_value(field, frontmatter.get(field.key))
            for field in self.fields
            if field.source == "frontmatter"
        }

    # -- construction from configuration -----------------------------------

    @classmethod
    def from_dict(cls, data: dict) -> "ItemSchema":
        """Build a schema from the user's config file.

        Tolerant on purpose: a missing section means "use the default", not
        "crash". The validator reports anything genuinely wrong afterwards.
        """
        data = data or {}

        raw_fields = data.get("fields") or []
        fields = tuple(
            Field(
                key=str(entry.get("key", "")).strip(),
                label=str(entry.get("label", "")).strip(),
                type=str(entry.get("type", "text")).strip(),
                values=tuple(str(value) for value in entry.get("values", ())),
                source=str(entry.get("source", "frontmatter")).strip(),
                help=str(entry.get("help", "")).strip(),
            )
            for entry in raw_fields
            if isinstance(entry, dict)
        )

        label = str(data.get("item_label", "Item")).strip() or "Item"
        plural = str(data.get("item_label_plural", "")).strip()
        if not plural:
            # Good enough for English, and the user can override it. We do not
            # try to be clever about pluralisation in other languages -- we ask
            # instead, in the setup interview.
            plural = label + "s"

        summary_files = tuple(
            str(name).strip()
            for name in data.get("summary_files",
                                 ("state", "actions", "waiting", "history"))
            if str(name).strip()
        )

        return cls(
            item_label=label,
            item_label_plural=plural,
            summary_files=summary_files,
            fields=fields,
        )
