"""The three things the maintainer asked for on the Schedule page, 2026-08-21.





The third was two faults wearing one complaint: the route answered with JSON
so the browser navigated to a page of `{"ok": ...}`, and the row offered both
buttons at once next to a column saying which one applied.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import config as config_module, folders, paths
from aki_agent.dashboard import create_app, navigation

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "src" / "aki_agent" / "dashboard" / "templates"
EXAMPLE = REPO_ROOT / "configs" / "examples" / "architecture.yaml"


def test_schedule_leads_the_abilities_group():
    group = next(g for g in navigation.GROUPS if g.key == "abilities")
    assert group.pages[0].path == "/schedule", (
        "Schedule is meant to be the first tab under Abilities.")


def test_a_task_shows_one_state_and_one_way_to_change_it():
    page = (TEMPLATES / "schedule.html").read_text(encoding="utf-8")

    # The old pair is gone: no row offers Install to something installed.
    assert 'action="/schedule/install"' not in page
    assert 'action="/schedule/remove"' not in page
    assert ">Install<" not in page
    assert ">Remove<" not in page

    # What replaced them picks its own destination from the state.
    assert "'remove' if is_installed.get(task.key) else 'install'" in page
    assert 'class="state' in page

    # And the column that used to duplicate the state now carries it.
    assert "<th>Installed</th>" not in page
    assert "Runs automatically" in page


@pytest.mark.parametrize("route", ["/schedule/install", "/schedule/remove"])
def test_switching_a_task_lands_back_on_the_page(route):
    """Not on a screenful of JSON, which is the "decline page" he saw."""
    source = (Path(__file__).resolve().parents[1] / "src" / "aki_agent"
              / "dashboard" / "app.py").read_text(encoding="utf-8")

    name = route.rsplit("/", 1)[1]
    start = source.index(f'@app.route("/schedule/{name}", methods=["POST"])')
    end = source.index("@app.route", start + 10)
    body = source[start:end]

    assert "return jsonify" not in body, (
        f"{route} answers a form post, so it has to answer with a page.")
    assert 'redirect(url_for("scheduled"' in body
    assert "note=" in body, "and it has to say what happened."


def test_the_page_shows_what_it_was_told():
    """A note nobody renders is the same as no note at all."""
    page = (TEMPLATES / "schedule.html").read_text(encoding="utf-8")
    assert "{% if note %}" in page

    source = (Path(__file__).resolve().parents[1] / "src" / "aki_agent"
              / "dashboard" / "app.py").read_text(encoding="utf-8")
    start = source.index('def scheduled():')
    end = source.index('@app.route', start)
    assert 'note=request.args.get("note", "")' in source[start:end]


# -- the folder picker -----------------------------------------------------

def test_the_watch_card_offers_a_browse_button():
    """The folder field has a Browse button, and typing still works.

    This used to assert `function watchFields`, the name of the JavaScript
    that built the card. The fields are rendered by the server now -- one
    trigger family per tab means their shape is known before the page is
    sent -- so that function is gone while everything it was there to
    produce is still on the page. The test was naming the implementation;
    it now names the thing a person can do.
    """
    page = (TEMPLATES / "schedule.html").read_text(encoding="utf-8")
    assert 'id="watchpath"' in page
    assert "Browse" in page
    assert "/schedule/folders" in page
    # Typing still works. The button is the other way in, not the only way.
    assert 'name="t0_path"' in page
    assert "placeholder=" in page


def test_the_top_of_the_walk_lists_somewhere_to_start():
    top = folders.listing("")
    assert top["up"] is None, "there is nothing above the list of drives"
    assert top["folders"], "the picker has to open on something"
    assert all(Path(one["path"]).exists() for one in top["folders"])


def test_walking_into_a_folder_lists_its_folders(tmp_path):
    (tmp_path / "drawings").mkdir()
    (tmp_path / "notes.txt").write_text("not a folder", encoding="utf-8")
    (tmp_path / ".claude").mkdir()

    listed = folders.listing(str(tmp_path))
    names = [one["name"] for one in listed["folders"]]

    assert names == ["drawings"], (
        "files are not folders, and dot-folders are tooling, not documents")
    assert listed["up"] == str(tmp_path.parent)
    assert not listed["trouble"]


def test_windows_own_folders_stay_out_of_the_picker(tmp_path):
    """Found on the test laptop, 2026-08-21.

    Browsing C:\\ listed `$SysReset` and `$WinREAgent` above `Documents` --
    noise at best, and at worst an invitation to point a scheduled task at
    Windows' recovery image.
    """
    for name in ("$SysReset", "$WinREAgent", "$RECYCLE.BIN",
                 "System Volume Information", "Drawings"):
        (tmp_path / name).mkdir()

    names = [one["name"] for one in folders.listing(str(tmp_path))["folders"]]
    assert names == ["Drawings"]


def test_a_folder_that_is_not_there_is_reported_not_raised(tmp_path):
    listed = folders.listing(str(tmp_path / "gone"))
    assert listed["folders"] == []
    assert listed["trouble"], "the picker has to say why it is empty"


def test_the_picker_cannot_be_asked_from_another_page(dashboard_client):
    """It changes nothing, but it maps the disk, so it takes the token."""
    refused = dashboard_client.post("/schedule/folders", data={"at": ""})
    assert refused.status_code == 403


@pytest.mark.parametrize("worked, expected", [
    (True, "no longer runs on its own"),
    (False, "could not be switched off"),
])
def test_switching_a_task_off_says_which_way_it_went(
        dashboard_client, monkeypatch, worked, expected):
    """Including when it fails.

    Windows answers a failed `schtasks /Delete` with an empty string often
    enough that passing the raw message through produced a blank note -- which
    reads exactly like a success. So the page states the outcome itself and
    adds the machine's words only as detail.
    """
    from aki_agent import schedule
    from aki_agent.dashboard import app as app_module

    task = schedule.DEFAULT_TASKS[0]
    monkeypatch.setattr(schedule, "remove", lambda _t: (worked, ""))

    landed = dashboard_client.post(
        "/schedule/remove",
        data={"token": app_module.SESSION_TOKEN, "key": task.key},
        follow_redirects=True)

    assert landed.status_code == 200
    body = landed.get_data(as_text=True)
    assert "{&#34;ok&#34;" not in body and '{"ok"' not in body, (
        "the browser must not land on JSON")
    assert expected in body


# -- the machine's own folder dialog ---------------------------------------

def test_browse_asks_for_the_real_window_first():
    """Browse asks for the real window first."""
    page = (TEMPLATES / "schedule.html").read_text(encoding="utf-8")
    assert "/schedule/folders/native" in page
    # and the built-in list is still there for when there is no desktop
    assert "/schedule/folders" in page
    assert "data.trouble" in page, (
        "no desktop must fall back to the list, not show an error")


def test_no_desktop_is_reported_not_raised(monkeypatch):
    from aki_agent import folders as folders_module

    monkeypatch.setattr(folders_module, "can_open_a_window", lambda: False)
    answered = folders_module.ask_for_folder()
    assert answered["path"] == ""
    assert answered["trouble"]


def test_cancelling_the_dialog_is_not_a_failure(monkeypatch):
    """Cancel must leave the field alone, not blank it or shout."""
    import subprocess

    from aki_agent import folders as folders_module

    monkeypatch.setattr(folders_module, "can_open_a_window", lambda: True)

    class Finished:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Finished())
    assert folders_module.ask_for_folder() == {"path": "", "trouble": ""}


def test_a_chosen_folder_comes_back_as_a_windows_path(monkeypatch):
    import subprocess

    from aki_agent import folders as folders_module

    monkeypatch.setattr(folders_module, "can_open_a_window", lambda: True)

    class Finished:
        returncode = 0
        stdout = "C:/Users/sample/Documents\n"      # Tk answers in slashes
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Finished())
    answered = folders_module.ask_for_folder()
    assert answered["trouble"] == ""
    assert answered["path"].replace("\\", "/") == "C:/Users/sample/Documents"


def test_the_dialog_never_runs_inside_the_dashboard():
    """Tk in the server's own thread can take the whole process down.

    That failure would look exactly like the unexplained dashboard deaths
    The maintainer has been chasing, so the dialog gets its own short-lived process
    and this test is what keeps it there.
    """
    source = (Path(__file__).resolve().parents[1] / "src" / "aki_agent"
              / "folders.py").read_text(encoding="utf-8")

    # Read as code, not as text: `import sys, tkinter` on one line is still
    # an import, and a string search for "import tkinter" would miss it.
    import ast

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name.split(".")[0] for alias in node.names]
            assert "tkinter" not in names, (
                "tkinter must never be imported into the dashboard's own "
                "process -- the dialog gets a process of its own")
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("tkinter"), (
                "tkinter must never be imported into the dashboard's own "
                "process -- the dialog gets a process of its own")

    # Checked on `_ask_with`, which is where both dialogs run since
    # 2026-09-05 -- the file picker was added and the error handling around
    # the subprocess, which took three attempts to get right, was collapsed
    # into one copy rather than gaining a second.
    start = source.index("def _ask_with(")
    body = source[start:source.index("def ask_for_file(")]
    assert "subprocess.run" in body
    assert "timeout=" in body, "a dialog left open must not hang the request"

    # And both public entry points go through it, so neither can quietly
    # grow its own in-process Tk call later.
    for name in ("ask_for_file", "ask_for_folder"):
        where = source.index(f"def {name}(")
        after = source[where:where + 1400]
        assert "_ask_with(" in after, f"{name} runs Tk somewhere else now"


# -- who owns a scheduled task ---------------------------------------------

def test_access_denied_is_explained_not_echoed():
    """The Task Scheduler's own words say nothing a person can act on.

    Found on the test laptop, 2026-08-21: every attempt to switch a built-in
    task off answered `ERROR: Access is denied.` because an elevated SSH
    session had created the tasks, leaving him Read-only on his own machine.
    """
    from aki_agent import schedule

    said = schedule._explain("ERROR: Access is denied.")
    assert "Access is denied" not in said
    assert "administrator" in said
    assert "ordinary window" in said, "it has to say what to do about it"

    # anything else passes through untouched
    assert schedule._explain("something else") == "something else"


def test_installing_as_an_administrator_warns_first(monkeypatch):
    from aki_agent import schedule

    monkeypatch.setattr(schedule, "running_elevated", lambda: True)
    warning = schedule.elevation_warning()
    assert "administrator" in warning
    assert "will not be able to switch them off" in warning

    monkeypatch.setattr(schedule, "running_elevated", lambda: False)
    assert schedule.elevation_warning() == ""


def test_schedule_install_knows_what_is_already_there():
    """The comparison that has now been written wrong four times.

    `installed_names()` answers `AkiAgent-morning-summary`; a task's key is
    `morning-summary`. `cmd_schedule_install` compared the two directly, so
    its "already there" branch never ran and every invocation re-created all
    six.
    """
    source = (Path(__file__).resolve().parents[1] / "src" / "aki_agent"
              / "cli.py").read_text(encoding="utf-8")
    start = source.index("def cmd_schedule_install(")
    end = source.index("\ndef ", start + 10)
    body = source[start:end]

    assert "task.key in already" not in body
    assert "schedule.is_installed(task, already)" in body


# ---------------------------------------------------------------------------
# Copying a built-in, and editing your own
# ---------------------------------------------------------------------------

def test_a_built_in_offers_a_copy_and_not_an_edit(dashboard_client):
    """A built in offers a copy and not an edit.

    Editing a shipped task in place would work until the next upgrade wrote
    it back over the top -- so what is offered is a copy, which is a task of
    his that nothing overwrites.
    """
    page = dashboard_client.get("/schedule").get_data(as_text=True)
    # The tab travels with the link since 2026-09-05, so that Custom on an
    # Event task opens the Event form rather than the default one.
    assert "custom=morning-summary" in page
    assert "edit=morning-summary" not in page


def test_the_copy_arrives_in_the_panel_with_no_key(dashboard_client):
    """No key is the whole difference between a copy and an edit."""
    page = dashboard_client.get("/schedule?custom=morning-summary").get_data(
        as_text=True)

    assert "Your copy of" in page
    assert 'name="key" value=""' in page
    assert "Morning summary" in page

    # AND ITS SETTINGS CAME WITH IT.
    #
    # This used to look for the prefill JSON the page handed to JavaScript
    # (`"kind": "time"`). There is no prefill blob any more -- the fields are
    # rendered filled in -- so the check is now the value a person would see
    # in the box. Morning summary runs at 08:00 on weekdays.
    assert 'value="08:00"' in page
    assert 'name="t0_day_MON"' in page and "checked" in page


def test_saving_a_copy_leaves_the_built_in_alone(dashboard_client):
    from aki_agent import schedule
    from aki_agent.dashboard import app as app_module

    dashboard_client.post("/schedule/save", data={
        "token": app_module.SESSION_TOKEN,
        "key": "",
        "title": "Morning summary", "why": "mine", "prompt": "do it",
        "t0_kind": "time", "t0_hour": "06:00",
    })

    mine = schedule.read_user_tasks()
    assert len(mine) == 1
    # It must not take the shipped key, or every switch on the page would go
    # on operating the built-in instead.
    assert mine[0].key != "morning-summary"
    assert schedule.get_task("morning-summary").built_in is True


def test_a_user_task_offers_an_edit_that_keeps_its_key(dashboard_client):
    from aki_agent import schedule
    from aki_agent.dashboard import app as app_module

    dashboard_client.post("/schedule/save", data={
        "token": app_module.SESSION_TOKEN, "key": "",
        "title": "Watch drawings", "why": "x", "prompt": "y",
        "t0_kind": "time", "t0_hour": "07:00",
    })
    key = schedule.read_user_tasks()[0].key

    page = dashboard_client.get(f"/schedule?edit={key}").get_data(as_text=True)
    assert "Edit" in page
    assert f'name="key" value="{key}"' in page

    dashboard_client.post("/schedule/save", data={
        "token": app_module.SESSION_TOKEN, "key": key,
        "title": "Watch drawings", "why": "changed", "prompt": "y",
        "t0_kind": "time", "t0_hour": "08:15",
    })

    tasks = schedule.read_user_tasks()
    assert len(tasks) == 1, "editing must replace, not add a second"
    assert tasks[0].why == "changed"
    assert (tasks[0].triggers[0].hour, tasks[0].triggers[0].minute) == (8, 15)

