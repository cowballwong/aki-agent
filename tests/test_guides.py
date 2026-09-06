"""Set-up guides, and the promise they are built to keep.

The promise, in the maintainer's terms (2026-08-28), having chosen the route where each
user makes their own OAuth client.

The instructions were never missing. They were in five places under five
different names, plus some hard-coded blocks inside one template, so a person
could find help only if they were already on the right page looking at the
right section. That is what these tests are really about: not whether the words
exist, but whether they are *reachable* and whether they stay in one copy.

`test_a_guide_wraps_the_connector_and_does_not_restate_it` is the one that
matters most. A guide that copies a connector's words creates a second copy to
go stale, and the first sentence to go stale in a copied instruction is the one
that changed — which is the one the reader needed.
"""

from __future__ import annotations

import pytest

from aki_agent import accounts, guides, paths, seams


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


@pytest.fixture(autouse=True)
def clean_registry():
    guides.reset_to_defaults()
    accounts.reset_to_defaults()
    yield
    guides.reset_to_defaults()
    accounts.reset_to_defaults()


# ---------------------------------------------------------------------------
# It is a seam, so a plugin can teach its own set-up
# ---------------------------------------------------------------------------

def test_guide_is_a_seam():
    seams.import_seam_modules()
    assert "guide" in seams.known()


def test_the_shipped_guides_are_registered():
    assert set(guides.topics()) == {
        "google-oauth", "gmail-oauth", "google-drive", "mail-app-password",
        "calendar-ics",
        "cloud-files", "telegram", "dashboard-pin", "semantic-search",
        "remote-access"}


def test_a_plugin_can_add_a_guide_for_the_provider_it_added():
    """The gap this closes: a third-party provider used to arrive undocumented.

    It could register a calendar without editing the package, and then had
    nowhere to put the instructions for connecting it — so it landed
    unexplained at exactly the moment the user needed an explanation.
    """
    guides.register(guides.Guide(
        topic="bitbucket",
        title="Connecting Bitbucket",
        minutes=4,
        why="So it can read your repositories.",
        body=lambda: "1. Make a token.",
        undo="revoke the token",
    ))
    assert "bitbucket" in guides.topics()
    assert "Make a token" in guides.get("bitbucket").text()


# ---------------------------------------------------------------------------
# One copy of the words
# ---------------------------------------------------------------------------

def test_a_guide_wraps_the_connector_and_does_not_restate_it(monkeypatch):
    """Change the connector's words; the guide must change with them."""
    from aki_agent.connectors import google_calendar

    monkeypatch.setattr(google_calendar, "how_to_set_up",
                        lambda: "SENTINEL STEPS")
    assert "SENTINEL STEPS" in guides.get("google-oauth").text()


def test_the_ics_guide_wraps_the_connector_too(monkeypatch):
    from aki_agent.connectors import calendars

    monkeypatch.setattr(calendars, "how_to_get_the_address",
                        lambda: "SENTINEL ADDRESS")
    assert "SENTINEL ADDRESS" in guides.get("calendar-ics").text()


def test_the_files_guide_wraps_the_connector_too(monkeypatch):
    from aki_agent.connectors import files

    monkeypatch.setattr(files, "describe_what_is_available",
                        lambda: "SENTINEL FILES")
    assert "SENTINEL FILES" in guides.get("cloud-files").text()


# ---------------------------------------------------------------------------
# What every guide owes the reader
# ---------------------------------------------------------------------------

def test_every_guide_says_how_long_it_takes_before_the_steps():
    """"About ten minutes" is the difference between starting and closing the tab."""
    for guide in guides.every():
        text = guide.text()
        assert guide.minutes >= 1, f"{guide.topic} has no estimate"
        head = text.split("\n\n")[0:2]
        assert any("minute" in part for part in head), guide.topic


def test_every_guide_says_how_to_undo_it():
    """A set-up that cannot be explained backwards should not be asked for."""
    for guide in guides.every():
        assert guide.undo, f"{guide.topic} does not say how to undo it"
        assert guide.undo in guide.text()


def test_every_guide_says_why_before_how():
    for guide in guides.every():
        assert guide.why, f"{guide.topic} never says why"


def test_the_google_guide_does_not_open_by_repeating_itself():
    """The first draft said the same sentence twice before saying anything.

    That reads as padding, and padding at the top of a guide teaches a reader
    to skip the top of every guide.
    """
    guide = guides.get("google-oauth")
    first_sentence_of_why = guide.why.split(".")[0].strip().lower()
    body_start = guide.body().strip().split(".")[0].strip().lower()
    assert first_sentence_of_why != body_start


def test_the_mail_guide_lists_real_providers():
    """It reads the providers table rather than hardcoding a list.

    Written as a dict lookup the first time, which would have raised inside a
    help page — the one screen a person reaches precisely because something
    has already gone wrong.
    """
    text = guides.get("mail-app-password").text()
    assert "Gmail" in text or "gmail" in text.lower()


# ---------------------------------------------------------------------------
# Reachable from the connection it explains
# ---------------------------------------------------------------------------

def test_every_connection_offers_a_guide():
    """A connection with no guide is a connection somebody gets stuck on."""
    for connection in accounts.every(None):
        assert connection.guide, f"{connection.service} has no guide"
        assert guides.get(connection.guide) is not None, connection.guide


def test_an_unknown_topic_is_not_pretended_to_exist():
    assert guides.get("no-such-thing") is None

def test_the_semantic_guide_does_not_ask_the_user_to_decide_during_setup():
    """It exists for later, not for the interview.

    The maintainer settled this on 2026-08-20 and again on 2026-08-28: off by default,
    permanently, because an index nobody can read is a memory nobody can debug.
    The guide is there for the day somebody notices word-matching missing
    something -- so it must say the download size before anything else, and
    must not read as a recommendation.
    """
    guide = guides.get("semantic-search")
    assert "default" in guide.why.lower()
    joined = " ".join(guide.gotchas).lower()
    assert "megabyte" in joined or "download" in joined
    assert "nothing is sent anywhere" in joined

# ---------------------------------------------------------------------------
# Reachable in the dashboard, which is where a stuck person actually is
# ---------------------------------------------------------------------------

from pathlib import Path                                    # noqa: E402

from aki_agent.dashboard import create_app                  # noqa: E402

CONFIG = (Path(__file__).resolve().parents[1] / "configs" / "examples"
          / "architecture.yaml")


def _browser():
    app = create_app(CONFIG)
    app.config["TESTING"] = True
    return app.test_client()


def test_the_guides_page_lists_them_all():
    page = _browser().get("/guides")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    for guide in guides.every():
        assert guide.title in html, guide.topic


def test_a_guide_page_shows_the_connector_own_steps():
    page = _browser().get("/guide/google-oauth")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "console.cloud.google.com" in html
    assert "undo" in html.lower()


def test_a_guide_page_offers_the_terminal_route_as_well():
    """The dashboard is often the thing that is broken."""
    html = _browser().get("/guide/telegram").get_data(as_text=True)
    assert "aki-agent guide telegram" in html


def test_an_unknown_guide_is_a_404_not_a_blank_page():
    assert _browser().get("/guide/no-such-thing").status_code == 404


def test_the_same_guide_is_available_as_data():
    """So an in-page popover never needs a second copy of the words."""
    reply = _browser().get("/guide/google-oauth?json=1")
    assert reply.status_code == 200
    data = reply.get_json()
    assert data["topic"] == "google-oauth"
    assert "console.cloud.google.com" in data["body"]


def test_every_section_that_asks_for_something_links_to_its_guide():
    """This is the ask, in one assertion.

     -- so the
    connections page must carry the affordance beside each section, not once at
    the top where it explains nothing in particular.
    """
    # Counted across the tabs, because the page grew tabs on 2026-08-29 and
    # the requirement did not change: every section still carries its own
    # link, and no tab is allowed to lose the one it holds.
    browser = _browser()
    tabs = ("gateway", "mail", "calendar", "files")
    pages = {tab: browser.get(f"/connections?tab={tab}").get_data(as_text=True)
             for tab in tabs}
    html = "".join(pages.values())
    assert html.count("how do I set this up?") >= 5
    for topic, tab in (("telegram", "gateway"),
                       ("mail-app-password", "mail"),
                       ("calendar-ics", "calendar"),
                       ("google-oauth", "calendar"),
                       ("cloud-files", "files")):
        assert f"/guide/{topic}" in pages[tab], (topic, tab)


def test_the_settings_page_has_them_too():
    html = _browser().get("/settings").get_data(as_text=True)
    assert "/guide/dashboard-pin" in html
