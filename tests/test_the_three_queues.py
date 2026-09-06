"""The three queue buttons on Today, and the rows they open.

reported 2026-08-23, in one message:






The thing worth guarding here is not the layout. It is that `waiting`,
`question` and `draft` stay three different kinds of thing, because the whole
reason for splitting one Inbox into three was that they are: one is somebody
else's move, one is yours, one is words already written for you to approve.
Merge them again and the buttons become three names for one list.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from aki_agent import approvals
from aki_agent.dashboard import app as dashboard_app
from aki_agent.dashboard import create_app

CONFIG = Path("configs/examples/architecture.yaml")


@pytest.fixture
def queues(tmp_path, monkeypatch):
    """A queue with one of each kind in it, in its own home."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    yesterday = (_dt.date.today() - _dt.timedelta(days=4)).isoformat()
    approvals.ask("Party wall award not back", kind="waiting",
                  waiting_on="Winchester council", due=yesterday,
                  project="P-2418", body="Sent 12 Aug. Chased once.")
    approvals.ask("Which staircase option?", kind="question",
                  project="P-2431", body="A keeps the landing.")
    approvals.ask("Reply to Thomas", kind="draft", project="P-2440",
                  body="Draft: thanks for the notes.")

    app = create_app(CONFIG)
    app.config["TESTING"] = True
    return app.test_client()


def page(client) -> str:
    return client.get("/").get_data(as_text=True)


def _settle(item_id: str, seconds: float = 3.0) -> None:
    """Wait for the background draft check to write its verdict back.

    The check runs off the calling thread on purpose -- see `_start_checking`.
    Polling for the result is what a test has to do about that; sleeping a
    fixed amount would be slower and still occasionally wrong.
    """
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for one in approvals.open_items():
            if one.id == item_id and one.checked != approvals.BEING_CHECKED:
                return
        time.sleep(0.02)
    raise AssertionError(f"{item_id} was never checked")


def asked_about(recorded) -> list[str]:
    return [draft for draft, _sources in recorded]


def mark_seen(client, kind: str) -> None:
    """Open a queue the way the browser does, and check that it worked.

    Without the token this POST is refused with a 403, and a test that only
    looked at the count afterwards would report the light as stuck on rather
    than the request as rejected -- which is the wrong bug to go looking for.
    """
    reply = client.post("/queues/seen",
                        data={"kind": kind, "token": dashboard_app.SESSION_TOKEN})
    assert reply.status_code == 204, reply.status_code


def test_each_kind_lands_in_its_own_pane(queues):
    """Three kinds, three panes, and nothing appearing in two of them.

    The failure this guards is quiet: a view that filters on `open` rather
    than on kind renders all three lists identically, every count reads 3,
    and the page looks finished.
    """
    html = page(queues)

    panes = {}
    for name in ("waiting", "action", "drafted"):
        start = html.index(f'class="queuelist" data-pane="{name}"')
        end = html.index('class="queuelist"', start + 10) if \
            html.count('class="queuelist"', start + 10) else len(html)
        panes[name] = html[start:end]

    assert "Party wall award not back" in panes["waiting"]
    assert "Which staircase option?" in panes["action"]
    assert "Reply to Thomas" in panes["drafted"]

    # And not anywhere else.
    assert "Party wall award not back" not in panes["action"]
    assert "Which staircase option?" not in panes["waiting"]
    assert "Reply to Thomas" not in panes["waiting"]


def test_the_waiting_button_does_not_say_it_is_waiting_for_you(queues):
    """The waiting button does not say it is waiting for you.

    "Waiting for you" described the opposite queue. Getting it backwards is
    worse than a bad label: it puts the items somebody else owes him in the
    pile he thinks he has to clear.
    """
    html = page(queues)
    assert "Waiting for you" not in html
    assert "Waiting…" in html


def test_a_row_carries_what_it_needs_to_be_acted_on(queues):
    """Id, heading, who, project, due — and a way to open the rest."""
    html = page(queues)
    item = next(one for one in approvals.open_items()
                if one.kind == "waiting")

    assert f'data-copy="{item.id}"' in html, "no copy button on the id"
    assert "Winchester council" in html, "no sign of who is being waited on"
    assert "P-2418" in html, "no project number"
    assert item.due in html, "no due date"
    assert 'class="queueexpand"' in html, "no way to see the detail"


def test_a_due_date_that_has_passed_says_so(queues):
    """A date alone is not a state. Read at a glance, 19 August and 30 August
    look like the same kind of fact, and only one of them changes today."""
    html = page(queues)
    assert "queuedue late" in html, (
        "an overdue item is drawn exactly like one that is not yet due")


def test_a_waiting_item_is_not_offered_yes_and_no(queues):
    """It is not a question put to him.

    The row was rendering the default Yes/No, which invited him to answer on
    the council's behalf and then closed the item as though they had replied.
    What a waiting item offers is to record what they said, or to stop
    waiting — both of which the row already has.
    """
    item = next(one for one in approvals.open_items() if one.kind == "waiting")
    assert item.options == []

    asked = next(one for one in approvals.open_items()
                 if one.kind == "question")
    assert [one.key for one in asked.options] == ["yes", "no"]


def test_the_light_goes_out_when_the_queue_is_opened(queues):
    """ — which means it must also go off.

    A light that only ever comes on is a light nobody looks at within a week.
    """
    assert page(queues).count("pilltab fresh") == 3

    mark_seen(queues, "waiting")

    html = page(queues)
    assert html.count("pilltab fresh") == 2
    # Specifically the one that was opened, and not just any two.
    waiting_tab = html[html.index('data-pane="waiting"') - 120:
                       html.index('data-pane="waiting"')]
    assert "fresh" not in waiting_tab


def test_seeing_one_queue_does_not_clear_the_others(queues):
    """The three are separate lights on three separate lists."""
    mark_seen(queues, "waiting")
    counts = approvals.unseen_counts()
    assert counts["waiting"] == 0
    assert counts["question"] == 1
    assert counts["draft"] == 1


# ---------------------------------------------------------------------------
# The draft check, which gates something as of 2026-08-23
# ---------------------------------------------------------------------------

def test_a_draft_is_checked_before_it_is_shown(tmp_path, monkeypatch, checker):
    """`sentinel.is_on()` was read in four places and every one was a label.

    The switch said "Drafts are looked at before they are shown, recorded or
    sent" when on, and "Nothing is being verified before it goes out" when
    off. Both were false: nothing consulted it before doing anything, and
    `notify.py` -- the actual outbound gate -- has never mentioned sentinel.

     — told what it costs.
    """
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    item = approvals.ask("Reply to the council",
                         body="We will have the award back by Friday.",
                         kind="draft", context="the email of 12 Aug")

    _settle(item.id)

    assert asked_about(checker) == ["We will have the award back by Friday."]

    checked = next(one for one in approvals.open_items() if one.id == item.id)
    assert "no source" in checked.checked


def test_only_drafts_are_checked(tmp_path, monkeypatch, checker):
    """Reviewing every question and every waiting item would roughly double
    what this package costs to run, for nothing: a question is the assistant
    asking, not the assistant asserting. A draft is the one thing here that
    goes out in his name."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))

    approvals.ask("Which staircase option?", kind="question")
    approvals.ask("Party wall award", kind="waiting", waiting_on="the council")

    assert checker == []
    assert all(not one.checked for one in approvals.open_items())


def test_the_switch_being_off_means_no_check_and_no_promise(tmp_path,
                                                            monkeypatch):
    """Off has to mean off, and it has to show as nothing rather than as a
    promise that never resolves."""
    from aki_agent import sentinel

    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))
    monkeypatch.setattr(sentinel, "is_on", lambda: False)

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("a draft was checked with the switch off")

    monkeypatch.setattr(sentinel, "review", must_not_run)

    item = approvals.ask("Reply", body="text", kind="draft")
    assert item.checked == ""


def test_a_checker_that_falls_over_does_not_lose_the_draft(tmp_path,
                                                           monkeypatch):
    """Losing a draft would be a worse failure than showing it unverified,
    and going quiet about it would be worse than both."""
    from aki_agent import sentinel

    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))
    monkeypatch.setattr(sentinel, "is_on", lambda: True)

    def explode(*_args, **_kwargs):
        raise RuntimeError("the specialist store is unreadable")

    monkeypatch.setattr(sentinel, "review", explode)

    item = approvals.ask("Reply", body="text", kind="draft")
    _settle(item.id)

    kept = next(one for one in approvals.open_items() if one.id == item.id)
    assert kept.body == "text", "the draft was lost"
    assert "not checked" in kept.checked


def test_raising_a_draft_does_not_wait_for_the_check(tmp_path, monkeypatch):
    """Measured at 25.9 seconds for one draft when this ran inline. That is a
    dashboard request, a scheduled task or a live session sitting still for
    half a minute -- and it took the test suite from 87 seconds to past 400,
    quietly making real model calls on somebody's subscription."""
    import time

    from aki_agent import sentinel

    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "01_Config"))
    monkeypatch.setattr(sentinel, "is_on", lambda: True)

    def slow(*_args, **_kwargs):
        time.sleep(3)
        verdict = sentinel.Verdict(outcome=sentinel.FLAG, ran=True)
        verdict.note = "late"
        return verdict

    monkeypatch.setattr(sentinel, "review", slow)

    started = time.monotonic()
    item = approvals.ask("Reply", body="text", kind="draft")
    took = time.monotonic() - started

    assert took < 1.0, f"raising a draft blocked for {took:.1f}s"
    assert item.checked == approvals.BEING_CHECKED
