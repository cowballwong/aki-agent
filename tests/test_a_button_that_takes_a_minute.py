"""A button that holds for two minutes has to say so.


`End of day` posts a form and the response does not come back until a headless
model run has finished writing the day up. `Recycle now` posts a form and the
response does not come back until the session has been saved, killed, started
again and verified. Both are correct; both looked like dead buttons; and a
dead-looking button gets pressed again, which queues a second run of the same
job.
"""

from __future__ import annotations

from pathlib import Path

import pytest

TEMPLATES = (Path(__file__).resolve().parents[1] / "src" / "aki_agent"
             / "dashboard" / "templates")


@pytest.fixture(scope="module")
def base() -> str:
    return (TEMPLATES / "base.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def quick() -> str:
    return (TEMPLATES / "_quick.html").read_text(encoding="utf-8")


def test_both_slow_buttons_declare_themselves(quick):
    """One attribute per slow form, so the next one is one attribute too."""
    assert quick.count("data-working=") == 2, (
        "End of day and Recycle now both hold the browser; both must say so")
    assert 'action="/today/eod"' in quick
    assert 'action="/sessions/recycle-now"' in quick


def test_the_message_says_where_the_answer_will_arrive(quick):
    """The result of End of day does not come back to this page.

    It is saved to the day log and sent through the user's channel. Somebody
    who does not know that watches a page that never shows them anything.
    """
    assert "History" in quick


def test_a_cancelled_confirm_does_not_raise_it(base):
    """Recycle now asks `confirm()` from its own `onsubmit`.

    That runs on the form, before the delegated listener runs on the
    document, and answering "cancel" calls preventDefault -- which does not
    stop the event bubbling. Without this check, saying no to the question
    still put an overlay over a page where nothing was about to happen.
    """
    assert "if (e.defaultPrevented) { return; }" in base


def test_pressing_it_twice_is_not_possible(base):
    """Two presses of End of day is two wrap-ups for one day."""
    assert "b.disabled = true" in base


def test_going_back_does_not_leave_it_stuck(base):
    """The browser restores a cached page exactly as it was left.

    Overlay up, button disabled, nothing running. `pageshow` fires on that
    restore where `load` does not.
    """
    assert "'pageshow'" in base
    assert "box.hidden = true" in base
