"""The queue bar and its sheet belong to the window, not to Today.


They were rendered by `today.html` alone, so walking to Settings left the
three counts behind -- and the bar is the thing that says something needs
you, which is least useful on the one page you were already looking at.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent.dashboard.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "src" / "aki_agent" / "dashboard" / "templates"
CONFIG_A = REPO_ROOT / "configs" / "examples" / "architecture.yaml"

EVERY_PAGE = ("/", "/projects", "/schedule", "/knowledge", "/history",
              "/health", "/running", "/connections", "/settings",
              "/notifications", "/inbox")


@pytest.fixture(scope="module")
def browser():
    app = create_app(CONFIG_A)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.mark.parametrize("url", EVERY_PAGE)
def test_the_bar_and_the_sheet_are_on_every_page(browser, url):
    html = browser.get(url).get_data(as_text=True)

    assert html.count('id="queuebar"') == 1, f"{url} should carry one bar"
    assert html.count('id="queue"') == 1, f"{url} should carry one sheet"


def test_it_is_rendered_once_and_only_once():
    """Today used to include it. Base does now, and both would be two."""
    today = (TEMPLATES / "today.html").read_text(encoding="utf-8")
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")

    assert '{% include "_columns.html" %}' not in today
    assert '{% include "_columns.html" %}' in base


def test_it_is_outside_the_main_column():
    """`main` carries a z-index, which makes it a stacking context.

    The sheet is a modal with a backdrop over the navigation rail; rendered
    inside `main` every z-index on it would be a number measured within it,
    which is a bug this dashboard has already had once.
    """
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")

    closes_main = base.index("</main>")
    include = base.index('{% include "_columns.html" %}')

    assert include > closes_main


def test_the_queue_names_do_not_collide_with_a_pages_own(browser):
    """`held` means `notify.read_held()` on Notifications and on Inbox.

    Shared context is overridden by a page's own kwargs, so putting the
    sheet's three lists under `waiting` / `held` / `drafted` would have fed
    notification objects to the sheet on exactly those two pages -- the two
    nobody would think to check. They are `queue_*` instead.
    """
    partial = (TEMPLATES / "_columns.html").read_text(encoding="utf-8")

    assert "queue_waiting" in partial
    assert "queue_action" in partial
    assert "queue_drafted" in partial

    # And the pages that own the word still render.
    for url in ("/notifications", "/inbox"):
        assert browser.get(url).status_code == 200


def test_a_door_page_carries_neither(browser):
    """It lists real work, and a login page is served to anyone on the port."""
    html = browser.get("/login").get_data(as_text=True)

    assert 'id="queuebar"' not in html
    assert 'id="queue"' not in html
