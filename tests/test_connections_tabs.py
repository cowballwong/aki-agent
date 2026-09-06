"""Connections, split into tabs.

WHY (reported 2026-08-29)
-----------------------
 — nine sections in one 540-line page, so whatever somebody came
for was usually below the fold.

The split itself is a template change and would need no tests. What needs
them is the thing a split quietly breaks: every form on this page answers by
redirecting back to it with a sentence in `?note=`, and a redirect that names
no tab drops that sentence on Gateway — leaving somebody who just typed a
mail password on a different tab, with the answer to their own action on a
page they are not looking at.

This page has had that failure before, in a worse form: five routes sent a
sentence back and not one of them was displayed at all, so the maintainer typed his
sign-in code, saw the page reload unchanged, and concluded he had signed in.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent.dashboard import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "configs" / "examples" / "architecture.yaml"

TABS = ("gateway", "mail", "calendar", "files")


@pytest.fixture()
def browser():
    app = create_app(EXAMPLE)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _token() -> str:
    import aki_agent.dashboard.app as module

    return module.SESSION_TOKEN


def _tab(browser, name: str) -> str:
    reply = browser.get(f"/connections?tab={name}")
    assert reply.status_code == 200, f"tab {name} answered {reply.status_code}"
    return reply.get_data(as_text=True)


# A heading that appears on exactly one tab, for each tab.
ONLY_HERE = {
    # Was "The dashboard’s chat box" until 2026-09-04, when the chat
    # panel was taken out of the dashboard. What is left on this tab is
    # the Telegram connection itself, which is the part being kept.
    "gateway": "Reaching this when you are out",
    "mail": ">Email</h2>",
    "calendar": "Google Calendar",
    "files": ">Files</h2>",
}


@pytest.mark.parametrize("here", TABS)
def test_each_tab_draws_its_own_sections_and_not_the_others(browser, here):
    page = _tab(browser, here)
    assert ONLY_HERE[here] in page, f"{here} is missing its own section"
    for other in TABS:
        if other != here:
            assert ONLY_HERE[other] not in page, (
                f"the {other} section is showing on the {here} tab")


def test_an_unknown_tab_falls_back_rather_than_showing_an_empty_page(browser):
    """?tab=nonsense is a typed address, not a fault worth a 404."""
    page = _tab(browser, "nonsense")
    assert ONLY_HERE["gateway"] in page


def test_what_is_true_of_every_tab_is_not_repeated_on_each_one(browser):
    """The promise at the top, and where secrets live, sit outside the tabs.

    Both are facts about the page rather than about one connection. Checked
    because the tempting way to split a page is to give every tab a copy of
    the introduction, and four copies of a promise read as four promises.
    """
    for name in TABS:
        page = _tab(browser, name)
        assert "Secrets are never shown on this page" in page
        assert "Where secrets are kept" in page


def test_a_form_comes_back_to_the_tab_it_was_sent_from(browser):
    """The reason these tests exist."""
    reply = browser.post("/connections/mail/forget",
                         data={"token": _token(), "address": "nobody@here"})
    assert reply.status_code in (301, 302)
    assert "tab=mail" in reply.headers["Location"], reply.headers["Location"]
    # And it still carries its answer, which is the half that was lost before.
    assert "note=" in reply.headers["Location"]


def test_the_calendar_forms_come_back_to_the_calendar_tab(browser):
    reply = browser.post("/connections/calendar/forget",
                         data={"token": _token(), "name": "no-such-calendar"})
    assert reply.status_code in (301, 302)
    assert "tab=calendar" in reply.headers["Location"]


def test_the_outside_access_switch_comes_back_to_the_gateway_tab(browser):
    """It used to answer on Settings, which is no longer where it lives."""
    reply = browser.post("/remote", data={"token": _token(), "off": "1"})
    assert reply.status_code in (301, 302)
    where = reply.headers["Location"]
    assert "/connections" in where and "tab=gateway" in where, where


# ---------------------------------------------------------------------------
# The Google sign-ins, once there is more than one of them
# ---------------------------------------------------------------------------

def test_the_email_tab_offers_the_google_sign_in(browser):
    """The email tab offers the google sign in."""
    page = _tab(browser, "mail")
    assert "Sign in with Google" in page or "Google app first" in page
    assert 'name="service" value="gmail"' in page or "Calendar tab" in page


def test_every_google_button_says_which_permission_it_is_asking_for():
    """Both tabs press the same route, so neither may rely on its default.

    Read from the templates rather than from the rendered page: those buttons
    only appear once a Google app has been registered, so a rendered-page
    assertion would pass by drawing nothing at all.
    """
    import re

    templates = (REPO_ROOT / "src" / "aki_agent" / "dashboard" / "templates")
    for name, expected in (("_conn_calendar.html", "calendar"),
                           ("_conn_mail.html", "gmail")):
        page = (templates / name).read_text(encoding="utf-8")
        forms = re.findall(
            r'<form[^>]*action="/connections/google/(?:connect|disconnect)".*?'
            r'</form>', page, re.S)
        assert forms, f"{name} has no Google button to check"
        for form in forms:
            assert f'name="service" value="{expected}"' in form, (
                f"a Google form in {name} does not say which permission it "
                "is asking for, so it would fall back to the route default")


def test_an_unknown_service_is_refused_rather_than_connecting_something_else(
        browser):
    """Pressing a button for a power that does not exist must not sign the
    person in to the calendar because that is what the default was."""
    reply = browser.post("/connections/google/connect",
                         data={"token": _token(), "service": "nonsense"})
    assert reply.status_code in (301, 302)
    where = reply.headers["Location"]
    assert "accounts.google.com" not in where
    assert "/connections" in where


def test_the_files_tab_offers_the_drive_sign_in_without_replacing_the_folder(
        browser):
    """The files tab offers the drive sign in without replacing the folder.

    Both halves in one assertion, because the risk in adding the API was that
    it would read as the new right way to do it. The folder stays first on
    the page and stays described as needing no account.
    """
    page = _tab(browser, "files")
    assert "no account, no key" in page
    assert "Google Drive" in page
    assert page.index("Files</h2>") < page.index("Google Drive, for what")
