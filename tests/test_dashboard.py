"""The two-config test, taken all the way to the rendered page.

`test_two_configs.py` proves the *loader* is generic. This proves the thing
that actually matters to a user: that the **dashboard they look at** is
generic. The loader could be perfectly domain-neutral and the dashboard could
still have a hardcoded column heading, and the failure would only be visible
by looking at the screen.

So this starts the real application against each example configuration and
reads the HTML that comes out.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aki_agent.dashboard import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "configs" / "examples"
CONFIG_A = EXAMPLES / "architecture.yaml"
CONFIG_B = EXAMPLES / "music_teaching.yaml"

TEMPLATE_DIR = (REPO_ROOT / "src" / "aki_agent" / "dashboard"
                / "templates")


# The project list moved to /projects when Today became the landing page
# (reported 2026-08-19). These tests are about the vocabulary on the page
# that lists the work, so they follow it.
def _page(config_path: Path, url: str = "/projects") -> str:
    app = create_app(config_path)
    app.config["TESTING"] = True
    with app.test_client() as browser:
        response = browser.get(url)
        assert response.status_code == 200, f"{url} returned {response.status_code}"
        return response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# The same application, two occupations
# ---------------------------------------------------------------------------

def test_dashboard_speaks_the_architects_vocabulary():
    html = _page(CONFIG_A)

    assert "Projects" in html            # their word for the unit of work
    assert "Work stage" in html          # their field labels
    assert "Consultants" in html
    assert "Riverside School" in html    # their actual items
    assert "Mira" in html                # the assistant name they chose


def test_dashboard_speaks_the_music_teachers_vocabulary():
    html = _page(CONFIG_B)

    assert "Students" in html
    assert "Working towards" in html
    assert "Instrument" in html
    assert "Amelia Hart" in html
    assert "Bo" in html


def test_neither_dashboard_leaks_the_others_vocabulary():
    """The real proof. One engine, and neither page knows the other exists."""
    architecture = _page(CONFIG_A)
    music = _page(CONFIG_B)

    for word in ("Working towards", "Instrument", "Amelia", "Student"):
        assert word not in architecture, (
            f"the architect's dashboard contains '{word}', which belongs to "
            "the other configuration"
        )

    for word in ("Work stage", "Consultants", "Riverside", "Project"):
        assert word not in music, (
            f"the music teacher's dashboard contains '{word}', which belongs "
            "to the other configuration"
        )


def test_the_summary_strip_groups_by_whatever_enum_was_declared():
    """The strip is field-agnostic: it uses the first enum the user declared."""
    architecture = _page(CONFIG_A)
    music = _page(CONFIG_B)

    # First enum in config A is `stage`; in config B it is `grade`.
    assert "technical" in architecture
    assert "grade 5" in music


# ---------------------------------------------------------------------------
# Honest failure, on the screen and not just in the data
# ---------------------------------------------------------------------------

def _visible_text(html: str) -> str:
    """The page with tooltip text removed.

    This distinction caught a false alarm worth keeping. The first version of
    the test below simply asserted the rejected value was absent from the
    page, and failed -- because the value DOES appear, inside the `title`
    attribute of the cell, in the sentence explaining why it was rejected.

    That is exactly right, and the test was wrong. Showing "?" in the cell and
    "'sketching' is not one of the allowed values" on hover is the honest
    behaviour: the user needs to know what was in their file in order to fix
    it. What must never happen is the bad value appearing as though it were
    the answer.

    So: strip the explanations, then check what is left.
    """
    return re.sub(r'title="[^"]*"', "", html)


def test_a_bad_value_is_never_rendered_as_if_it_were_good():
    """`brambling-court` has a stage that is not allowed and a percent of 120.

    Neither may be displayed as a value. A panel that shows wrong data
    confidently is worse than one that shows nothing.
    """
    visible = _visible_text(_page(CONFIG_A))

    assert "sketching" not in visible, (
        "the dashboard displayed a value that failed validation"
    )
    assert "120%" not in visible
    # And it must show that something is wrong rather than a silent blank.
    assert "needs a look" in visible


def test_item_page_explains_what_is_wrong():
    html = _page(CONFIG_A, "/item/brambling-court")

    assert "not one of the allowed values" in html
    assert "waiting.md" in html          # the missing file is named


def test_missing_item_is_a_polite_404():
    app = create_app(CONFIG_A)
    app.config["TESTING"] = True
    with app.test_client() as browser:
        response = browser.get("/item/does-not-exist")
    assert response.status_code == 404
    assert "There is nothing at that address" in response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Every page renders under both configurations
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", ["/", "/history", "/notifications",
                                 "/schedule", "/health", "/learned"])
@pytest.mark.parametrize("config_path", [CONFIG_A, CONFIG_B])
def test_every_page_renders(url, config_path):
    """A page that throws on an empty machine is a page nobody sees twice."""
    html = _page(config_path, url)
    assert "<html" in html.lower()


def test_the_old_activity_address_lands_on_the_day_log():
    """`/activity` stopped being a page on 2026-09-04 and became a door.

    It used to render fourteen days of narrative as folded cards, and
    History included the same block from the same files. The EOD tab
    replaced both with a calendar and one day at a time, so the route
    redirects rather than rendering a second account of the same thing.

    It is not deleted: the address is in the docs and in somebody's
    browser history, and a 404 would read as "that feature is gone".
    """
    app = create_app(CONFIG_A)
    app.config["TESTING"] = True
    with app.test_client() as browser:
        response = browser.get("/activity")

    assert response.status_code in (301, 302)
    assert "/history" in response.headers["Location"]
    assert "tab=eod" in response.headers["Location"]


def test_api_returns_the_declared_fields_only():
    app = create_app(CONFIG_B)
    app.config["TESTING"] = True
    with app.test_client() as browser:
        data = browser.get("/api/items").get_json()

    assert data["item_label"] == "Student"
    first = data["items"][0]
    assert set(first["values"]) == {
        "grade", "instrument", "next_lesson", "fees_settled", "pieces"}


# ---------------------------------------------------------------------------
# Things the dashboard must not do
# ---------------------------------------------------------------------------

def test_dashboard_binds_only_to_localhost():
    """No remote access in this version, and not by accident either."""
    from aki_agent.dashboard import app as dashboard_app

    assert dashboard_app.LOCALHOST == "127.0.0.1"

    source = Path(dashboard_app.__file__).read_text(encoding="utf-8")
    assert "0.0.0.0" not in source, (
        "the dashboard must never bind to all interfaces -- that puts a "
        "personal dashboard on whatever network the laptop is joined to"
    )


def test_pages_make_no_external_requests():
    """Nothing is fetched from the internet to draw the page.

    A dashboard that pulls a font or a script from a CDN stops working on a
    plane, leaks the fact that it is being used, and adds a third party to a
    tool whose entire pitch is that it runs locally.
    """
    offenders: list[str] = []
    for template in sorted(TEMPLATE_DIR.glob("*.html")):
        text = template.read_text(encoding="utf-8")
        for match in re.findall(r"""(?:src|href)\s*=\s*["']([^"']+)["']""",
                                text):
            if match.startswith(("http://", "https://", "//")):
                offenders.append(f"{template.name}: {match}")

    assert not offenders, (
        "the dashboard would fetch these from the internet:\n  "
        + "\n  ".join(offenders)
    )


def test_debug_mode_is_off():
    """Flask's debugger exposes an interactive console in the browser.

    On a machine holding somebody's personal notes that is not a trade worth
    making for prettier error pages.
    """
    from aki_agent.dashboard import app as dashboard_app

    source = Path(dashboard_app.__file__).read_text(encoding="utf-8")
    assert "debug=False" in source
    assert "debug=True" not in source
