"""Buttons and dialogs that described work other than the work they did.

All from the Fable 5.1 audit pass of 2026-09-05. They share a shape: nothing
errors, nothing is logged, and the only way to find out is to do the thing and
notice afterwards that it did not happen -- or happened to something else.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aki_agent import library, paths, schedule, skills_store
from aki_agent.dashboard import app as dashboard_app


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


def templates() -> Path:
    return Path(dashboard_app.__file__).parent / "templates"


# ---------------------------------------------------------------------------
# A library copy, edited


def test_a_library_copy_survives_an_edit():
    """Editing it used to make the Library forget where it came from.

    `save()` rebuilt the frontmatter from scratch, dropping the
    `aki-library:` stamp. `active_keys()` searches for that stamp, so the row
    flipped back to **Add**, and Add writes the original over the copy with no
    condition attached. Edit, glance at the Library, press the button that
    looks like the one that installs it, and the edit is gone.
    """
    saved, problems = skills_store.save(
        name="Borrowed", description="Use when I say borrowed, or ask for the borrowed checklist, or mention borrowing a skill from the library.",
        body="the original")
    assert not problems

    stamped = saved.path.read_text(encoding="utf-8").replace(
        "---\n", f"---\n{library.FROM_LIBRARY}: borrowed\n", 1)
    saved.path.write_text(stamped, encoding="utf-8")
    assert "borrowed" in library.active_keys()

    skills_store.save(name="Borrowed", description="Use when I say borrowed, or ask for the borrowed checklist, or mention borrowing a skill from the library.",
                      body="MY EDIT", key=saved.key)

    text = saved.path.read_text(encoding="utf-8")
    assert "MY EDIT" in text
    assert f"{library.FROM_LIBRARY}: borrowed" in text
    assert "borrowed" in library.active_keys(), (
        "the Library has forgotten this copy, so its row offers Add -- which "
        "overwrites the edit")


def test_the_stamp_the_two_modules_use_is_the_same_string():
    """`skills_store` cannot import `library` -- `library` imports it.

    So the two are held together here instead of by an import.
    """
    source = Path(skills_store.__file__).read_text(encoding="utf-8")
    assert f'"{library.FROM_LIBRARY}:"' in source


# ---------------------------------------------------------------------------
# Dialogs that described the wrong action


def test_no_form_asks_to_remove_something_it_is_about_to_run():
    """The Run button carried `class="removes"`.

    So pressing Run asked "Remove the X workflow?", promised it was moved to
    the sandbox, and then ran it.
    """
    for path in sorted(templates().glob("*.html")):
        text = path.read_text(encoding="utf-8")
        for form in re.findall(r"<form[^>]*>", text, re.DOTALL):
            if 'action="/workflows/run"' not in form:
                continue
            assert "remove" not in form.lower().replace("/workflows/run", ""), (
                f"{path.name}: the Run form still describes itself as a "
                "removal")


def test_nothing_promises_the_sandbox_for_a_folder_it_deletes():
    """One sentence in `base.html` spoke for every removal on the site.

    `workflows.remove` and `plugins.remove` are both `shutil.rmtree`. A dialog
    that misdescribes what the button does is worse than no dialog: it is read
    once, found to be wrong, and then not read again.
    """
    base = (templates() / "base.html").read_text(encoding="utf-8")
    handler = base[base.find("document.addEventListener('submit'"):][:800]
    assert "sandbox" not in handler, (
        "the shared handler still invents a consequence for every form")

    for name in ("_workflows.html", "_plugins.html"):
        text = (templates() / name).read_text(encoding="utf-8")
        for form in re.findall(r"<form[^>]*>", text, re.DOTALL):
            if "/remove" in form and "sandbox" in form:
                pytest.fail(f"{name}: promises the sandbox for a delete")


# ---------------------------------------------------------------------------
# A task saved over another task


def test_two_new_tasks_with_the_same_title_are_two_tasks():
    """`existing = [everything except this key] + [this task]`.

    Right when editing, silently destructive when adding: two tasks titled
    "Second one" left one task, carrying the second's settings, under a note
    that said "Added".
    """
    first, _ = schedule.save_user_task(
        schedule.ScheduledTask(key="", title="Second one", why="a", prompt="p"))
    second, _ = schedule.save_user_task(
        schedule.ScheduledTask(key="", title="Second one", why="b", prompt="q"))

    assert first.key != second.key
    mine = {one.key for one in schedule.read_user_tasks()}
    assert {first.key, second.key} <= mine


def test_two_tasks_titled_in_chinese_are_two_tasks():
    """The fifth instance of the slug bug, and the one written inline.

    The package-wide `_safe_key` test could not reach it, because this one is
    four lines inside `save_user_task` rather than a function with that name.
    """
    first, _ = schedule.save_user_task(
        schedule.ScheduledTask(key="", title="報價單", why="a", prompt="p"))
    second, _ = schedule.save_user_task(
        schedule.ScheduledTask(key="", title="會議紀錄", why="b", prompt="q"))

    assert first.key != second.key
    assert first.key != "task" and second.key != "task"
    assert len(schedule.read_user_tasks()) == 2


def test_editing_a_task_still_replaces_it():
    """The other half: a supplied key must still overwrite, not multiply."""
    made, _ = schedule.save_user_task(
        schedule.ScheduledTask(key="", title="Only one", why="a", prompt="p"))
    schedule.save_user_task(
        schedule.ScheduledTask(key=made.key, title="Only one",
                               why="changed", prompt="p"))

    tasks = schedule.read_user_tasks()
    assert len(tasks) == 1
    assert tasks[0].why == "changed"
