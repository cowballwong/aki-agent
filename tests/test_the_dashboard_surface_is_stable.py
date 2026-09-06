"""The dashboard's surface, pinned, so a refactor can be proved to be a move.

WHY THIS FILE EXISTS
--------------------
reported 2026-08-28, on the idea of splitting `dashboard/app.py` into modules:


The honest answer is no — 100% is not a thing anybody can offer, and saying it
would be exactly the self-deception `sentinel.py` exists to prevent. What *can*
be offered is a specific, measurable guarantee, and this file is it.

A split of that file is supposed to be a **pure move**: the same routes, the
same names, the same methods, in different files. That is a claim a machine can
check, and these tests check it three ways.

  1. THE ROUTE TABLE IS IDENTICAL. Every URL rule, its endpoint name and its
     methods, compared against a snapshot committed beside this file. A route
     that vanished, was renamed, or quietly lost its POST is caught exactly,
     not eventually.

  2. EVERY PAGE STILL RENDERS. Each argument-free GET is fetched and must not
     return a server error. A template that moved and was not found, an import
     that went with a route into a new module, a `url_for` pointing at an
     endpoint that got renamed — all of those show up here as a 500, at the
     page, rather than in somebody's browser a week later.

  3. THE REST OF THE SUITE STILL PASSES. That is not in this file; it is the
     other 1,300 tests, and they are the reason a refactor is safe to attempt
     at all.

WHAT THIS STILL DOES NOT PROVE
------------------------------
Stated plainly, because a guard whose limits are unwritten gets trusted past
them:

  * **POST routes are not fired.** Half of them change something — shutting the
    assistant down, recycling a session, removing an account. A test suite that
    exercised them for coverage's sake would be a test suite that occasionally
    destroyed the machine it ran on.
  * **Nothing in the browser is checked.** JavaScript, layout, whether a button
    is reachable on a phone. A page can return 200 and be unusable.
  * **A 200 is not correctness.** These say the page came back, not that it
    came back right. The tests that check *what* a page says are the other
    ones, by name, elsewhere in this suite.

So: this file turns "I think the split went fine" into "the surface is provably
unchanged and every page still renders". That is a great deal less than 100%,
and it is honest about which part it is.

UPDATING THE SNAPSHOT
---------------------
When a route is genuinely added or removed, regenerate:

    python -m tests.regenerate_dashboard_routes

and the diff in that JSON file becomes part of the change under review, which
is the point — adding a route should be visible, not incidental.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aki_agent.dashboard import create_app

HERE = Path(__file__).resolve().parent
SNAPSHOT = HERE / "fixtures" / "dashboard_routes.json"
CONFIG = HERE.parent / "configs" / "examples" / "architecture.yaml"

# Argument-free GETs that are deliberately not fetched.
#
# Nothing is excluded for being slow or awkward. These are excluded because
# fetching them *does* something, and a smoke test must not.
NOT_FETCHED: set[str] = set()


def _app():
    app = create_app(CONFIG)
    app.config["TESTING"] = True
    return app


def _live_routes(app) -> list[dict]:
    rules = []
    for rule in app.url_map.iter_rules():
        methods = sorted(m for m in rule.methods
                         if m not in ("HEAD", "OPTIONS"))
        rules.append({"rule": str(rule.rule),
                      "endpoint": rule.endpoint,
                      "methods": methods})
    rules.sort(key=lambda one: (one["rule"], one["endpoint"]))
    return rules


def test_the_snapshot_exists():
    """Without it the other tests would pass by having nothing to compare."""
    assert SNAPSHOT.exists(), (
        "the route snapshot is missing; regenerate it with "
        "tests/regenerate_dashboard_routes.py")


def test_every_route_still_exists_with_the_same_name_and_methods():
    """The one that makes a split provable rather than hopeful."""
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    actual = _live_routes(_app())

    expected_map = {(r["rule"], r["endpoint"]): r["methods"] for r in expected}
    actual_map = {(r["rule"], r["endpoint"]): r["methods"] for r in actual}

    missing = sorted(set(expected_map) - set(actual_map))
    added = sorted(set(actual_map) - set(expected_map))
    changed = sorted(key for key in set(expected_map) & set(actual_map)
                     if expected_map[key] != actual_map[key])

    assert not missing, f"routes disappeared: {missing}"
    assert not changed, (
        "methods changed: "
        + ", ".join(f"{k}: {expected_map[k]} -> {actual_map[k]}"
                    for k in changed))
    assert not added, (
        "new routes are fine, but the snapshot has to record them — "
        f"regenerate it: {added}")


def _fetchable(app) -> list[str]:
    return sorted(
        str(rule.rule)
        for rule in app.url_map.iter_rules()
        if "GET" in rule.methods
        and "<" not in str(rule.rule)
        and str(rule.rule) not in NOT_FETCHED
    )


def test_there_are_pages_to_smoke():
    """Guards the guard: a filter bug that fetched nothing would look green."""
    assert len(_fetchable(_app())) > 30


@pytest.mark.parametrize("path", _fetchable(_app()))
def test_every_page_still_renders(path):
    """A 5xx here is a template, an import or a `url_for` that moved.

    Parametrised so a failure names the page rather than making somebody read
    a loop's traceback to find out which one broke.
    """
    reply = _app().test_client().get(path)
    assert reply.status_code < 500, (
        f"{path} returned {reply.status_code}")
