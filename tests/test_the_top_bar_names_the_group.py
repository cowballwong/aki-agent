"""The top bar names the group, not the tab you are on.


The tab strip is a foot below the heading and it already says which tab you
are on, by highlighting one of six. A heading that repeats it spends the
largest type on the page saying "Knowledge" on a screen whose rail says
System.

TWO KINDS OF PAGE KEEP THEIR OWN NAME, and both were found by tests rather
than by thinking:

  A GROUP WITH ONE PAGE has no tab strip, so there is nothing repeating the
  name -- and Workspace is exactly that. Its heading is the user's own word
  for their work ("Projects", "Students"), and the first version of this
  change replaced it with "Workspace". The vocabulary canary caught it.

  A DRILL-DOWN -- one project, one guide, one library entry -- has a heading
  that is the name of the thing you opened. There is nowhere else on the
  page that says it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aki_agent.dashboard.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "src" / "aki_agent" / "dashboard" / "templates"
CONFIG_A = REPO_ROOT / "configs" / "examples" / "architecture.yaml"


@pytest.fixture(scope="module")
def browser():
    app = create_app(CONFIG_A)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _heading(browser, url: str) -> str:
    html = browser.get(url).get_data(as_text=True)
    found = re.search(r"<h1>(.*?)</h1>", html, re.S)
    assert found, f"{url} has no heading at all"
    return found.group(1).strip()


@pytest.mark.parametrize("url, group", [
    ("/knowledge", "Abilities"),
    ("/schedule", "Abilities"),
    ("/history", "System"),
    ("/health", "System"),
    ("/running", "System"),
])
def test_a_tab_shows_the_group_it_belongs_to(browser, url, group):
    assert _heading(browser, url) == group


def test_the_one_page_group_keeps_its_own_word(browser):
    """Workspace has no tab strip, and its heading is the user's own word.

    "Projects" here comes from the architect's configuration. On a music
    teacher's machine the same page says "Students". Replacing it with the
    group's label deletes the only place the dashboard uses their word.
    """
    assert _heading(browser, "/projects") == "Projects"


def test_a_drill_down_still_names_what_you_opened(browser):
    """The heading is the only place the thing's name appears."""
    html = browser.get("/projects").get_data(as_text=True)
    link = re.search(r'href="(/item/[^"]+)"', html)
    if link is None:
        pytest.skip("the example workspace has no items to open")

    heading = _heading(browser, link.group(1))
    assert heading not in ("Workspace", "Projects"), (
        "opening one item must not replace its name with the group's")


def test_the_doors_keep_their_own_heading():
    """A login page has no group to belong to.

    Checked in the templates rather than over HTTP: reaching some of these
    means putting the dashboard into a state the other tests want it out of.
    """
    for door in ("login.html", "not_found.html", "went_wrong.html",
                 "not_configured.html", "first_pin.html", "stopped.html",
                 "updated.html"):
        text = (TEMPLATES / door).read_text(encoding="utf-8")
        assert "{% block titlemode %}page{% endblock %}" in text, (
            f"{door} would show a navigation group's name")
        # Inside the file, not commented out -- the first attempt at this
        # inserted the line into `went_wrong.html`'s opening comment, where
        # it did nothing and looked correct.
        assert not re.search(
            r"\{#(?:(?!#\}).)*\{% block titlemode %\}", text, re.S), (
            f"{door}'s titlemode block is inside a comment")
