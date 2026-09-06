"""Names that are not in Latin script must still produce distinct keys.

This bug has now been found four times in four modules: `memory`, then
`specialists`, then `skills_store` and `knowledge` together. Each was written
separately, each stripped everything outside `[a-z0-9]`, and each therefore
turned a name written entirely in Chinese into an empty string, a constant
fallback, and a silent overwrite of whatever was saved under it before.

`specialists.py` records the lesson in a comment -- "a fix applied to an
instance is not applied to the class" -- and then the class went unfixed for
another fortnight, because every test written for it named one module.

So this file asks the question of the package instead of of a module. It
finds every `_safe_key` there is, by import, and holds all of them to the
same rule. A fifth one written next month is covered on the day it is
written, by a test nobody has to remember to update.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import aki_agent


def every_safe_key():
    """(module name, function) for each `_safe_key` in the package."""
    found = []
    for info in pkgutil.walk_packages(aki_agent.__path__,
                                      prefix="aki_agent."):
        try:
            module = importlib.import_module(info.name)
        except Exception:                                # pragma: no cover
            # A module that cannot be imported at all is somebody else's
            # failing test, not this one's finding.
            continue
        function = getattr(module, "_safe_key", None)
        if callable(function):
            found.append((info.name, function))
    return found


def test_there_is_at_least_one_to_check():
    """Guards the guard: a walk that finds nothing would pass everything."""
    assert len(every_safe_key()) >= 4


@pytest.mark.parametrize("script,names", [
    ("Chinese", ("報價單", "會議紀錄", "圖則審批")),
    ("Japanese", ("見積書", "議事録")),
    ("Greek", ("Προσφορά", "Πρακτικά")),
    ("Cyrillic", ("Смета", "Протокол")),
])
def test_names_in_one_script_do_not_collapse_together(script, names):
    for module_name, safe_key in every_safe_key():
        keys = [safe_key(one) for one in names]

        assert all(keys), f"{module_name}: {script} produced an empty key"
        assert len(set(keys)) == len(names), (
            f"{module_name}: {script} names collapsed to {set(keys)} -- the "
            "second one saved would silently replace the first")


def test_a_name_with_nothing_usable_still_gets_a_key():
    """The fallback is still needed; it just must not be the common case."""
    for module_name, safe_key in every_safe_key():
        assert safe_key("!!! ???"), f"{module_name}: punctuation gave no key"


def test_latin_names_are_unchanged():
    """The fix must not move anybody's existing folder."""
    for module_name, safe_key in every_safe_key():
        assert safe_key("Weekly update") == "weekly-update", module_name
        assert safe_key("  Spaced  Out  ") == "spaced-out", module_name
