"""Editing the configuration from the dashboard.

WHY THIS WAS THE BIGGEST OMISSION
---------------------------------
The whole package rests on one idea: everything specific to a person lives in
their configuration, not in the code. And there was no way to see or change
that configuration except by opening a YAML file in a text editor — which is
exactly the thing this package promises its users they will never have to do.

The setup interview writes the file once. Everything after that is a change:
a new field on the dashboard, a different quiet-hours window, a colour they
have gone off. Sending someone to a text editor for that is sending them back
to the world the package exists to get them out of.

WHAT IS EDITABLE HERE, AND WHAT IS NOT
--------------------------------------
Editable: everything about the person and how the assistant behaves and looks.

Not editable: secrets. They are never shown, never pre-filled into a form, and
never round-tripped through a browser. Connections are managed separately, and
even there a saved secret is referred to by name and never by value.

THE RULE THAT MAKES THIS SAFE TO USE
------------------------------------
A save reads the existing config, changes only the fields the form supplied,
and writes it back atomically. A form that posts half the settings must never
silently blank the other half — that is how somebody loses their field
definitions by editing their own name.
"""

from __future__ import annotations

from pathlib import Path

from .. import config as config_module
from ..config import Config
from ..schema import FIELD_TYPES, Field, ItemSchema


def apply_form(existing: Config, form) -> tuple[Config, list[str]]:
    """Return a copy of `existing` with whatever the form supplied applied.

    `form` is anything with `.get(name, default)` — a Flask form, or a plain
    dict in a test.

    Only keys actually present are touched. Everything else is left exactly as
    it was, which is what stops a partial form wiping settings it never
    displayed.
    """
    problems: list[str] = []

    # --- the assistant ----------------------------------------------------
    if "assistant_name" in form:
        existing.assistant.name = form.get("assistant_name", "").strip()
    if "assistant_tone" in form:
        existing.assistant.tone = form.get("assistant_tone", "").strip()
    if "assistant_logo" in form:
        existing.assistant.logo = form.get("assistant_logo", "").strip()[:4]
    if "assistant_colour" in form:
        wanted = form.get("assistant_colour", "").strip()
        candidate = config_module.Assistant(colour=wanted)
        if wanted and candidate.safe_colour() != wanted:
            problems.append(
                f"'{wanted}' is not a colour. Use something like #4ade80. "
                "The colour was left as it was."
            )
        else:
            existing.assistant.colour = wanted

    # --- the person -------------------------------------------------------
    if "user_name" in form:
        existing.user.name = form.get("user_name", "").strip()
    if "user_occupation" in form:
        existing.user.occupation = form.get("user_occupation", "").strip()
    if "user_timezone" in form:
        existing.user.timezone = form.get("user_timezone", "").strip()

    # --- working hours ----------------------------------------------------
    # Added 2026-09-05. Three fields with three readers -- `User.is_working`,
    # `User.working_hours_sentence`, and the CLAUDE.md `scaffold` writes --
    # and, until now, no writer anywhere: not here, not in the setup
    # interview, not in the CLI. Every install ran on the dataclass defaults.
    if "working_days" in form:
        # Empty means every day, which is what `is_working` already does with
        # an empty tuple. Upper-cased because that is the form `is_working`
        # compares against, and a person typing "mon" means Monday.
        existing.user.working_days = tuple(
            part.strip().upper()
            for part in form.get("working_days", "").split(",")
            if part.strip())

    for field in ("working_from", "working_to"):
        if field not in form:
            continue
        value = form.get(field, "").strip()
        # `minutes()` parses these; a value it cannot read would leave the
        # hours silently wrong rather than loudly refused, and "silently
        # wrong" is the failure this whole audit was about.
        parts = value.split(":")
        if (len(parts) != 2 or not all(p.isdigit() for p in parts)
                or not 0 <= int(parts[0]) <= 23 or not 0 <= int(parts[1]) <= 59):
            problems.append(f"{value!r} is not a time like 09:00, so the "
                            "working hours were left as they were.")
        else:
            setattr(existing.user, field, value)
    if "user_location" in form or "user_here" in form:
        # `user.location` has existed since the weather was written and there
        # was no way to set it from anywhere in the dashboard -- so the card
        # on the front page could not work for anybody who had not hand-edited
        # the YAML. Reported as "weather card 唔 work", which it was.
        #
        # TWO INPUTS, ONE STORED VALUE. reported 2026-09-04, asked to choose
        # between typing a town and letting the computer answer. The radio
        # says which of the two boxes is the answer; storing the mode as well
        # would be a second key to keep in step with a value that already
        # says which it is (numbers, or words).
        mode = form.get("location_mode", "town").strip()
        if mode == "here":
            found = form.get("user_here", "").strip()
            # A refused or failed lookup sends an empty box. Keeping what was
            # already there beats replacing a working location with nothing
            # because the browser was in a bad mood.
            if found:
                existing.user.location = found
            elif not existing.user.location:
                problems.append(
                    "No location came back from the browser, so nothing was "
                    "saved for the weather. Type a town name instead.")
        else:
            existing.user.location = form.get("user_location", "").strip()

    if "identity_aliases" in form:
        aliases = tuple(
            part.strip() for part in form.get("identity_aliases", "").split(",")
            if part.strip())
        if not aliases:
            problems.append(
                "At least one alias is needed, otherwise the assistant cannot "
                "tell which work in your notes is yours. Your name was kept."
            )
        else:
            existing.user.identity_aliases = aliases

    if "languages" in form:
        languages = tuple(
            part.strip() for part in form.get("languages", "").split(",")
            if part.strip())
        existing.user.languages = languages or ("en",)

    # --- the workspace ----------------------------------------------------
    if "workspace_root" in form:
        raw = form.get("workspace_root", "").strip()
        if raw:
            candidate = Path(raw).expanduser()
            if not candidate.exists():
                problems.append(
                    f"There is no folder at {candidate}. The workspace was "
                    "left pointing where it was."
                )
            else:
                existing.layout.root = candidate

    schema = existing.layout.schema
    if "item_label" in form:
        label = form.get("item_label", "").strip()
        plural = form.get("item_label_plural", "").strip()
        if label:
            schema.item_label = label
            schema.item_label_plural = plural or (label + "s")

    if "summary_files" in form:
        names = tuple(
            part.strip() for part in form.get("summary_files", "").split(",")
            if part.strip())
        if not names:
            problems.append("At least one summary file is needed, otherwise "
                            "there is nothing to read.")
        else:
            schema.summary_files = names

    # --- the PIN ----------------------------------------------------------
    if form.get("pin_new", "").strip() or form.get("pin_now", "").strip():
        from .. import dashboard_auth

        # The current one is required even though the person is already
        # logged in. A dashboard left open on an unlocked screen is exactly
        # the situation the PIN exists for, and "already signed in" is not
        # evidence that the person typing is the one who signed in.
        if not dashboard_auth.check(form.get("pin_now", "")):
            problems.append("That is not your current PIN, so it was left "
                            "as it was.")
        else:
            refused = dashboard_auth.set_pin(form.get("pin_new", ""))
            if refused:
                problems.append(refused)

    # --- notifications ----------------------------------------------------
    # Restored 2026-09-05. The dashboard rework (0.45.0, f6a80ff) deleted this
    # block while leaving both forms that post into it -- the Settings page and
    # the Notifications page -- exactly as they were. Saving redirected without
    # a problem message and changed nothing, and the only remaining way to set
    # quiet hours was hand-editing the YAML, which is the thing this page
    # exists to avoid. `notifications.enabled`, `quiet_hours` and
    # `urgent_keywords` all have live readers (`notify.py`, `me_time.py`).
    if "notifications_present" in form:
        existing.notifications.enabled = bool(form.get("notifications_enabled"))

        quiet_from = form.get("quiet_from", "").strip()
        quiet_to = form.get("quiet_to", "").strip()
        if quiet_from and quiet_to:
            existing.notifications.quiet_hours = (quiet_from, quiet_to)
        else:
            existing.notifications.quiet_hours = None

        existing.notifications.urgent_keywords = tuple(
            part.strip() for part in form.get("urgent_keywords", "").split(",")
            if part.strip())

    return existing, problems


# ---------------------------------------------------------------------------
# The field editor
# ---------------------------------------------------------------------------

def apply_field(existing: Config, form) -> tuple[Config, list[str]]:
    """Add or replace one declared field.

    Fields are the heart of the whole design — what the dashboard shows about
    each item. Being able to add one without opening a text editor is the
    difference between a schema that is genuinely the user's and one that is
    only theoretically theirs.
    """
    key = form.get("key", "").strip().lower().replace(" ", "_")
    field = Field(
        key=key,
        label=form.get("label", "").strip(),
        type=form.get("type", "text").strip(),
        values=tuple(part.strip() for part in form.get("values", "").split(",")
                     if part.strip()),
        source="frontmatter",
        help=form.get("help", "").strip(),
    )

    problems = field.validate()
    if problems:
        return existing, problems

    schema = existing.layout.schema
    others = tuple(other for other in schema.fields if other.key != field.key)
    schema.fields = others + (field,)
    return existing, []


def remove_field(existing: Config, key: str) -> Config:
    schema = existing.layout.schema
    schema.fields = tuple(field for field in schema.fields
                          if field.key != key)
    return existing


def field_types() -> tuple[str, ...]:
    return FIELD_TYPES


def describe_type(name: str) -> str:
    """What each field type means, in the user's terms rather than a coder's."""
    return {
        "text": "any words",
        "enum": "one of a fixed list you choose",
        "percent": "0 to 100, drawn as a bar",
        "number": "any number",
        "date": "a date",
        "bool": "yes or no",
        "tags": "several short labels",
    }.get(name, name)


def save(config: Config, path: Path | None = None) -> Path:
    """Write it back. Atomic, like every other write in this package."""
    return config_module.save(config, path)
