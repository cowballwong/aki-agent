"""A workspace's projects, as cards you can act on.


It was a table, which was right while the page was rows of fields. It is not
that any more: what a person does here is open one, star one, rename one, add
one, remove one -- five verbs, none of which a table is good at.

ONE FORM, FOUR DESTINATIONS. A form cannot be nested inside another, so the
star, the minus and the plus all live in the rename form and reach their own
routes through `formaction`, each carrying the value it needs as the button's
own name/value pair.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from aki_agent import config as config_module
from aki_agent import paths, workspace
from aki_agent.dashboard.app import create_app, SESSION_TOKEN

TEMPLATES = (Path(__file__).resolve().parents[1] / "src" / "aki_agent"
             / "dashboard" / "templates")


@pytest.fixture
def dashboard(tmp_path):
    root = tmp_path / "Aki"
    (root / "01_Config").mkdir(parents=True)
    (root / "02_Sandbox").mkdir(parents=True)
    project = root / "03_Workspace" / "01_Arch" / "01_Alpha"
    project.mkdir(parents=True)
    (project / "state.md").write_text(
        "---\ntitle: 01_Alpha\nstage: design\n---\n\nnotes\n", encoding="utf-8")

    config = config_module.Config()
    config.layout.root = root
    config.layout.workspaces = ("01_Arch",)

    with patch.object(paths, "home", lambda: tmp_path / "home"), \
            patch.object(config_module, "load", lambda *a, **k: config):
        paths.ensure_app_dirs()
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            with client.session_transaction() as session:
                session["in"] = True
            yield client, config


def _names(client) -> list[str]:
    html = client.get("/workspace/01_Arch").get_data(as_text=True)
    return re.findall(r'class="itname"[^>]*>([^<]+)<', html)


def test_a_project_is_a_card_and_carries_its_fields(dashboard):
    client, _ = dashboard
    html = client.get("/workspace/01_Arch").get_data(as_text=True)

    assert 'class="favour itcard' in html
    assert "<table" not in html
    assert "design" in html, (
        "a card that says less than the table it replaced is a redesign that "
        "lost information")


def test_the_empty_card_adds_one(dashboard):
    client, _ = dashboard
    assert 'id="additem"' in client.get("/workspace/01_Arch").get_data(
        as_text=True)

    client.post("/item/new", data={"token": SESSION_TOKEN,
                                   "workspace": "01_Arch", "name": "02_Beta"})

    assert sorted(_names(client)) == ["01_Alpha", "02_Beta"]


def test_the_star_is_the_pin(dashboard):
    client, config = dashboard
    key = workspace.scan(config).items[0].key

    client.post("/projects/pin", data={"token": SESSION_TOKEN, "key": key,
                                       "back": "/workspace/01_Arch"})
    html = client.get("/workspace/01_Arch").get_data(as_text=True)

    assert 'class="pin on"' in html
    assert "itcard pinned" in html, "the card shows it too, not just the star"


def test_the_minus_retires_one(dashboard):
    client, _ = dashboard
    client.post("/item/new", data={"token": SESSION_TOKEN,
                                   "workspace": "01_Arch", "name": "02_Beta"})

    client.post("/item/remove", data={"token": SESSION_TOKEN,
                                      "workspace": "01_Arch",
                                      "folder": "02_Beta",
                                      "confirm": "02_Beta"})

    assert _names(client) == ["01_Alpha"]


def test_removing_asks_twice_and_the_second_answer_is_checked(dashboard):
    """Removing asks twice and the second answer is checked.

    The browser asks once to confirm and once for the folder name, and the
    name is what the server checks -- so a wrong answer is refused there as
    well as in the dialog. A confirmation only the browser enforces is one a
    stray Enter gets past.
    """
    client, _ = dashboard
    client.post("/item/new", data={"token": SESSION_TOKEN,
                                   "workspace": "01_Arch", "name": "02_Beta"})

    client.post("/item/remove", data={"token": SESSION_TOKEN,
                                      "workspace": "01_Arch",
                                      "folder": "02_Beta",
                                      "confirm": "not the name"})

    assert sorted(_names(client)) == ["01_Alpha", "02_Beta"], (
        "the wrong confirmation must not remove anything")

    page = (TEMPLATES / "_items.html").read_text(encoding="utf-8")
    assert "window.confirm(" in page and "window.prompt(" in page


def test_every_button_names_its_own_action():
    """Four destinations, one form, because a form cannot nest in a form."""
    page = (TEMPLATES / "_items.html").read_text(encoding="utf-8")

    for action in ("/projects/pin", "/item/remove", "/item/new",
                   "/item/refresh"):
        assert f'formaction="{action}"' in page
    assert 'action="/item/rename"' in page


def test_the_star_is_out_of_reach_while_names_are_being_edited():
    """It shares the form, so Enter in a name box could otherwise submit
    through whichever button the browser picked."""
    page = (TEMPLATES / "_items.html").read_text(encoding="utf-8")

    assert "pins.forEach(function (one) { one.disabled = on; });" in page
