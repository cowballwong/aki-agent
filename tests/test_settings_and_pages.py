"""Settings, connections, sessions and logs — the sections that were missing.

The settings page is the one that mattered most and was absent longest. The
whole package rests on "everything about you lives in configuration, not in
code", and there was no way to see or change that configuration except by
opening a YAML file — the exact thing this package promises its users they
will never have to do.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import config as config_module
from aki_agent import paths
from aki_agent.dashboard import app as dashboard_app
from aki_agent.dashboard import create_app, settings

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "configs" / "examples" / "architecture.yaml"


@pytest.fixture
def config_copy(tmp_path):
    """A writable copy, so tests never edit the shipped example."""
    original = config_module.load(EXAMPLE)
    target = tmp_path / "config.yaml"
    config_module.save(original, target)
    return target


@pytest.fixture
def browser(config_copy, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    app = create_app(config_copy)
    app.config["TESTING"] = True
    with app.test_client() as testing_client:
        yield testing_client


def token() -> str:
    return dashboard_app.SESSION_TOKEN


# ---------------------------------------------------------------------------
# Every page renders
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", ["/settings", "/connections", "/sessions",
                                 "/logs"])
def test_the_new_sections_render(browser, url):
    assert browser.get(url).status_code == 200


# ---------------------------------------------------------------------------
# Editing settings
# ---------------------------------------------------------------------------

def test_the_assistant_can_be_renamed_and_recoloured(browser, config_copy):
    browser.post("/settings/save", data={
        "token": token(),
        "assistant_name": "Ada", "assistant_colour": "#f4a261",
        "assistant_logo": "◆",
    })

    reloaded = config_module.load(config_copy)
    assert reloaded.assistant.name == "Ada"
    assert reloaded.assistant.colour == "#f4a261"
    assert reloaded.assistant.logo == "◆"


def test_a_partial_form_never_wipes_the_settings_it_did_not_show(
        browser, config_copy):
    """The rule that makes this page safe to use.

    A form posting only the name must not blank the field definitions, the
    workspace or the notification settings. That is how somebody loses their
    whole schema by fixing a typo in their own name.
    """
    before = config_module.load(config_copy)

    browser.post("/settings/save", data={
        "token": token(), "assistant_name": "Only this changed"})

    after = config_module.load(config_copy)
    assert after.assistant.name == "Only this changed"
    assert after.layout.schema.fields == before.layout.schema.fields
    assert after.layout.root == before.layout.root
    assert after.user.identity_aliases == before.user.identity_aliases


def test_a_colour_that_is_not_a_colour_is_refused_and_the_old_one_kept():
    existing = config_module.load(EXAMPLE)
    original = existing.assistant.colour

    updated, problems = settings.apply_form(
        existing, {"assistant_colour": "red; } body { display:none"})

    assert problems
    assert updated.assistant.colour == original


def test_emptying_the_aliases_is_refused():
    """Without at least one, the assistant cannot tell which work is yours."""
    existing = config_module.load(EXAMPLE)
    updated, problems = settings.apply_form(existing,
                                            {"identity_aliases": "   "})

    assert problems
    assert updated.user.identity_aliases


def test_a_workspace_that_does_not_exist_is_refused(tmp_path):
    existing = config_module.load(EXAMPLE)
    original = existing.layout.root

    updated, problems = settings.apply_form(
        existing, {"workspace_root": str(tmp_path / "nope")})

    assert any("no folder at" in problem for problem in problems)
    assert updated.layout.root == original


def test_a_config_that_never_set_one_does_not_grow_the_section(tmp_path):
    """Short configs stay short — the rule the rest of `to_dict` follows."""
    existing = config_module.load(EXAMPLE)
    target = tmp_path / "config.yaml"
    config_module.save(existing, target)

    assert "weekly_token_limit" not in target.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The field editor — the heart of the design, now editable without YAML
# ---------------------------------------------------------------------------

def test_a_field_can_be_added_from_the_dashboard(browser, config_copy):
    browser.post("/settings/field", data={
        "token": token(), "label": "Next review", "key": "next_review",
        "type": "date"})

    reloaded = config_module.load(config_copy)
    keys = {field.key for field in reloaded.layout.schema.fields}
    assert "next_review" in keys


def test_an_enum_field_needs_its_values():
    existing = config_module.load(EXAMPLE)
    _, problems = settings.apply_field(existing, {
        "label": "Status", "key": "status", "type": "enum", "values": ""})

    assert any("lists no allowed values" in problem for problem in problems)


def test_a_bad_field_is_not_saved(browser, config_copy):
    before = config_module.load(config_copy).layout.schema.fields

    browser.post("/settings/field", data={
        "token": token(), "label": "", "key": "Bad Key!", "type": "nonsense"})

    assert config_module.load(config_copy).layout.schema.fields == before


def test_a_field_can_be_removed(browser, config_copy):
    browser.post("/settings/field/delete", data={
        "token": token(), "key": "client"})

    keys = {field.key
            for field in config_module.load(config_copy).layout.schema.fields}
    assert "client" not in keys


def test_every_field_type_has_a_plain_language_description():
    """The user picks from this list; 'enum' means nothing to them."""
    for kind in settings.field_types():
        described = settings.describe_type(kind)
        assert described != kind, f"{kind} has no description"


# ---------------------------------------------------------------------------
# Settings changes are guarded like every other change
# ---------------------------------------------------------------------------

def test_settings_cannot_be_changed_without_the_token(browser, config_copy):
    before = config_module.load(config_copy).assistant.name

    response = browser.post("/settings/save",
                            data={"assistant_name": "Hijacked"})

    assert response.status_code == 403
    assert config_module.load(config_copy).assistant.name == before


# ---------------------------------------------------------------------------
# Connections never reveal a secret
# ---------------------------------------------------------------------------

def test_the_connections_page_shows_no_secret_values(browser):
    html = browser.get("/connections").get_data(as_text=True)

    # It reports presence, not content.
    assert "saved" in html or "none" in html
    # And nothing is pre-filled into an input.
    assert 'value="1234567890' not in html
    assert "TELEGRAM_BOT_TOKEN=" not in html


def test_secret_inputs_are_not_remembered_by_the_browser(browser):
    """A token in a browser's autofill is a token in a shared laptop."""
    html = browser.get("/connections").get_data(as_text=True)
    assert html.count('autocomplete="off"') >= 2


# ---------------------------------------------------------------------------
# The log viewer is not a file browser
# ---------------------------------------------------------------------------

def test_a_path_outside_the_log_folder_is_refused(browser):
    html = browser.get(
        "/logs?file=../../../../Windows/win.ini").get_data(as_text=True)

    assert "outside the log folder" in html
    # And nothing from that file is rendered.
    assert "[fonts]" not in html
    assert "[extensions]" not in html


def test_a_missing_log_says_so_rather_than_showing_an_empty_box(browser):
    """An empty body reads as 'this log is empty', not 'I would not open it'."""
    html = browser.get("/logs?file=not-a-real-log.txt").get_data(as_text=True)
    assert "no such log file" in html.lower()


def test_log_contents_are_redacted(browser, tmp_path):
    from fake_credentials import FAKE_HEX_KEY

    (paths.log_dir() / "sample.log").write_text(
        f'api_key = "{FAKE_HEX_KEY}"', encoding="utf-8")

    html = browser.get("/logs?file=sample.log").get_data(as_text=True)
    assert FAKE_HEX_KEY not in html


# ---------------------------------------------------------------------------
# The chat panel is part of the shell, not a separate page
# ---------------------------------------------------------------------------

def test_nothing_that_moves_the_layout_is_restored_after_the_first_paint(
        browser):
    """The bug the maintainer found on 2026-08-24, as a rule rather than a fix.

        "當個 panel 拉左出黎，再switch page 嘅時候，chat panel 入面嘅 text
         boxes 會有一下變形"

    A chat panel dragged wider was remembered in the browser and put back by a
    script at the FOOT of the document. So every page was painted at the CSS
    default width first and then jumped, and the full-width textarea inside it
    deformed on the way through. The folded state had the same shape: a panel
    somebody had closed flashed open on every page before closing again.

    Fixing the two instances would leave the third to be found by the maintainer. The
    rule is what is checked: anything read out of storage that changes the
    layout is applied in the head, before the browser paints.
    """
    html = browser.get("/").get_data(as_text=True)
    head, _, below = html.partition("</head>")

    assert "EVERYTHING REMEMBERED ABOUT THE LAYOUT" in head, (
        "the pre-paint block must be inside <head>, not merely before <body> "
        "-- a script between </head> and <body> lands in the head only "
        "because the parser puts it there, which is not a thing to rely on")

    late = [line.strip() for line in below.splitlines()
            if "getItem" in line and (
                "chat-folded" in line or "'pa' + name" in line
                or "width" in line)]
    assert not late, (
        "these read a layout value after the page has been painted, which is "
        "what makes it flash: " + "; ".join(late))


def test_the_return_path_cannot_be_used_to_redirect_off_site(browser):
    """`back` comes from a form field, so it is untrusted input."""
    response = browser.post("/chat/send", data={
        "token": token(), "text": "hello",
        "back": "//evil.example/steal"})

    assert "evil.example" not in response.headers.get("Location", "")
