"""Things the assistant wants a decision on, and what happens when it gets one.

WHY THIS IS A SEPARATE STORE FROM THE EVENT BUS
-----------------------------------------------
`events.py` is a record: append-only, never edited, nothing consumes it. This
is a queue: every entry has a status that *changes*, exactly once, when a
person decides something. Mixing the two would mean rewriting history to
record a decision, and a log you rewrite is a log you cannot trust.

WHAT AN ITEM IS
---------------
One question with its own declared answers. That covers both shapes the
reference systems needed:

* **A draft** — "here is the email I would send; may I?" Options: send, don't.
* **A question** — "which of these did you mean?" Options: whatever it asks.

Same store, same lifecycle, so a person sees one list of "things waiting for
me" rather than several.

THE DECLARED-OPTIONS RULE, AND WHY IT IS NOT DECORATION
-------------------------------------------------------
An item carries its own answer options, each with the exact text that answering
it produces. A tap sends *that stored text*, never text supplied by the caller.

This is what makes a tap-to-answer surface safe to expose to a phone: a stolen
device token can only ever replay one of the options the assistant itself
declared. An endpoint that relays arbitrary text into a live agent session is
a remote-instruction endpoint, whoever holds the token.

Free text is still possible — people need to say things that are not on a
menu — but it goes through a separate, narrower path that must name an item
that is genuinely open, and is length-bounded.

THE TWO GATES
-------------
Approving runs the work immediately, so the person sees a result rather than a
"queued" spinner. But approving must NOT be the same act as making something
public or irreversible: sending an email, publishing, deleting. Those stop at
a second gate — staged, and confirmed separately. Two gates, not one: *do the
work* and *let it out* are different decisions.
"""

from __future__ import annotations

import datetime as _dt
import json
import uuid
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Callable

from . import atomic, events, paths, secrets, traces

OPEN = "open"
KINDS = ("question", "waiting", "draft")
DONE = "answered"
DROPPED = "dismissed"

MAX_FREE_TEXT = 2000


def queue_file() -> Path:
    return paths.state_dir() / "approvals.json"


@dataclass
class Option:
    """One answer, and the exact words answering with it produces."""

    key: str
    label: str
    says: str = ""

    def spoken(self) -> str:
        return self.says or self.label

    def as_dict(self) -> dict[str, str]:
        return {"key": self.key, "label": self.label, "says": self.spoken()}


@dataclass
class Item:
    id: str
    title: str
    body: str = ""
    # question : needs an answer from the person -- "Action now"
    # waiting  : the assistant is waiting on somebody ELSE -- "Waiting…"
    # draft    : something written, for approval -- "Drafted"
    #
    # `waiting` added 2026-08-23. The old label was
    # accurate about the old contents and the wrong thing to have: a list of
    # what he owes somebody and a list of what somebody owes him are two
    # different queues, and only one of them is his to act on.
    kind: str = "question"          # question | waiting | draft
    status: str = OPEN
    options: list[Option] = dataclass_field(default_factory=list)
    task: str = ""                  # what to learn from this decision
    context: str = ""               # ties this to the thing that raised it
    created_at: str = ""
    answered_at: str = ""
    # What a row has to show, per the brief of 2026-08-23: an id you can copy, a
    # heading, when it is due, which project it belongs to, and -- for the
    # waiting list -- who is being waited on.
    due: str = ""                   # ISO date, or "" when there is no date
    project: str = ""               # which piece of work this belongs to
    waiting_on: str = ""            # who owes the answer. Only for `waiting`
    seen_at: str = ""               # when the person last looked at this list
    # What the draft checker made of this, in one line. Only ever set for a
    # draft, and only when the check is switched on -- see `_check_the_draft`.
    checked: str = ""
    answer: str = ""                # the option key, or "" for free text
    said: str = ""                  # what the answer actually said
    staged: str = ""                # where an irreversible action is waiting

    def as_dict(self) -> dict[str, Any]:
        data = {key: getattr(self, key) for key in
                ("id", "title", "body", "kind", "status", "task", "context",
                 "created_at", "answered_at", "answer", "said", "staged",
                 "due", "project", "waiting_on", "seen_at", "checked")}
        data["options"] = [option.as_dict() for option in self.options]
        return data

    @property
    def is_open(self) -> bool:
        return self.status == OPEN

    def option(self, key: str) -> Option | None:
        for option in self.options:
            if option.key == key:
                return option
        return None


def _default_options(kind: str) -> list[Option]:
    if kind == "draft":
        return [
            Option("yes", "Go ahead", "Yes, go ahead."),
            Option("change", "Change it", "Not quite — I'll say what to change."),
            Option("no", "Leave it", "No, leave it."),
        ]
    if kind == "waiting":
        # Nothing. A waiting item is not a question put to the maintainer, so there is
        # no answer of his for a button to stand for -- it is a record that
        # somebody else owes a reply. It was showing Yes/No, which invited him
        # to answer on their behalf and then closed the item as though they
        # had. What it offers instead is what the row already gives: note what
        # they said, or stop waiting.
        return []
    return [
        Option("yes", "Yes", "Yes."),
        Option("no", "No", "No."),
    ]


BEING_CHECKED = "being checked…"


def _checking_is_on() -> bool:
    """Whether drafts get checked. Asked before the item is built.

    A separate function from `_start_checking` because the answer decides
    what the row says at the moment it is stored, and the check itself can
    only begin once the row exists.
    """
    from . import sentinel

    try:
        return bool(sentinel.is_on())
    except Exception:                                    # noqa: BLE001
        return False


def _start_checking(item: Item) -> None:
    """Send a draft to the checker, off this thread.

    Never blocks the draft and never holds it back. A draft that cannot be
    checked still reaches the person saying so — losing it would be a worse
    failure than showing it unverified, and going quiet about it would be
    worse than both.
    """
    import threading

    from . import sentinel

    def work() -> None:
        try:
            verdict = sentinel.review(item.body or item.title,
                                      sources=item.context)
            line = secrets.redact(verdict.line())[:300]
        except Exception as exc:                         # noqa: BLE001
            line = f"not checked — the checker could not run ({exc})"
        _record_check(item.id, line)

    # Daemon, so a check in flight never keeps the process alive. Losing a
    # verdict because the machine shut down is a small thing; a scheduled task
    # that will not exit is not.
    threading.Thread(target=work, daemon=True,
                     name=f"check-{item.id}").start()


def _record_check(item_id: str, line: str) -> None:
    """Put a verdict onto a draft that is already in the queue.

    Under the lock, because this runs on a different thread from everything
    else that touches the queue. Read-modify-write from two threads without
    one is how an item raised while a check was in flight disappears.
    """
    try:
        with atomic.lock(queue_file()):
            items = _read()
            for one in items:
                if one.id == item_id:
                    one.checked = line
                    _write(items)
                    return
    except Exception:                                    # noqa: BLE001
        # The draft matters more than the note about it. A queue that cannot
        # be written is a real problem, and it is not this thread's to report.
        return


def _read() -> list[Item]:
    # `read_json_for_update`, not `read_json`: every caller of this reads the
    # queue, changes it, and writes it back. A plain read cannot tell "the
    # file is not there" from "the file is there and would not open", and
    # answering the second with an empty list is how the whole queue used to
    # be erased by the next write.
    raw = atomic.read_json_for_update(queue_file(), default=[]) or []
    items: list[Item] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        options = [Option(key=str(one.get("key", "")),
                          label=str(one.get("label", "")),
                          says=str(one.get("says", "")))
                   for one in entry.get("options", [])
                   if isinstance(one, dict)]
        items.append(Item(
            id=str(entry.get("id", "")),
            title=str(entry.get("title", "")),
            body=str(entry.get("body", "")),
            kind=str(entry.get("kind", "question")),
            status=str(entry.get("status", OPEN)),
            due=str(entry.get("due", "")),
            project=str(entry.get("project", "")),
            waiting_on=str(entry.get("waiting_on", "")),
            seen_at=str(entry.get("seen_at", "")),
            checked=str(entry.get("checked", "")),
            options=options,
            task=str(entry.get("task", "")),
            context=str(entry.get("context", "")),
            created_at=str(entry.get("created_at", "")),
            answered_at=str(entry.get("answered_at", "")),
            answer=str(entry.get("answer", "")),
            said=str(entry.get("said", "")),
            staged=str(entry.get("staged", "")),
        ))
    return items


def _write(items: list[Item]) -> None:
    paths.ensure_app_dirs()
    atomic.write_json(queue_file(), [item.as_dict() for item in items])


def ask(title: str, *, body: str = "", kind: str = "question",
        options: list[Option] | None = None, task: str = "",
        context: str = "", due: str = "", project: str = "",
        waiting_on: str = "") -> Item:
    """Raise something for the user to decide. Returns the stored item."""
    kind = kind if kind in KINDS else "question"

    item = Item(
        id=uuid.uuid4().hex[:12],
        title=secrets.redact(title.strip()),
        body=secrets.redact(body.strip()),
        kind=kind,
        options=options or _default_options(kind),
        task=task,
        context=context,
        due=due.strip(),
        project=project.strip(),
        waiting_on=secrets.redact(waiting_on.strip()),
        created_at=_dt.datetime.now().isoformat(timespec="seconds"),
    )

    # The draft check, actually gating something.
    #
    # `sentinel.is_on()` was read in four places and every one of them was a
    # label. The switch said "Drafts are looked at before they are shown,
    # recorded or sent" when it was on, and "Nothing is being verified before
    # it goes out" when it was off, and both sentences were false: nothing
    # consulted it before doing anything. `cmd_check` called `review()`
    # without asking, and `notify.py` -- the actual outbound gate -- has never
    # mentioned sentinel at all.
    #
    # This is the "shown" half, and it is the half worth having. A draft is
    # the one thing here that goes out in the user's name, it is rare enough
    # that a model call per draft is proportionate, and the verdict arrives
    # attached to the item so it is in front of him at the moment he decides.
    #
    # Deliberately only `draft`. Reviewing every question and every waiting
    # item would double the model spend on this package for no gain -- a
    # question is the assistant asking, not the assistant asserting.
    # Started here, finished elsewhere. Measured at 25.9 seconds for one
    # draft: `sentinel.review` is a full model consultation, and putting that
    # on this line means whatever created the draft sits still for half a
    # minute -- a dashboard request, a scheduled task, a live session. The
    # first version of this did exactly that, and the test suite went from 87
    # seconds to over 400 because it was quietly making real model calls.
    #
    # So the draft is stored immediately and the verdict lands on it when it
    # arrives. "Before it is shown" still holds for any realistic reading: a
    # draft is raised and looked at some seconds later, not answered within
    # them.
    wants_checking = item.kind == "draft" and _checking_is_on()
    if wants_checking:
        item.checked = BEING_CHECKED

    items = _read()
    items.append(item)
    _write(items)

    # Started AFTER the item is in the queue, not before.
    #
    # The first version started the thread and then wrote, which is a race the
    # stub in the tests won immediately: the check finished, `_record_check`
    # read a queue the draft was not in yet, found nothing to update, and the
    # verdict was dropped. With a real model taking twenty seconds it would
    # have worked every time and failed on the day something was cached.
    if wants_checking:
        _start_checking(item)

    events.record("note", f"Asked: {item.title}", source="approvals",
                  detail={"id": item.id, "kind": item.kind})
    return item


def seen_file() -> Path:
    return paths.state_dir() / "queues-seen.json"


def unseen_counts() -> dict[str, int]:
    """How many items in each queue have arrived since it was last opened.

     A count alone
    cannot say that: three has meant three all week, and three where one is
    new is a different morning.
    """
    from . import atomic

    seen = atomic.read_json(seen_file(), default={}) or {}
    counts = {kind: 0 for kind in KINDS}
    for item in open_items():
        if item.created_at > str(seen.get(item.kind, "")):
            counts[item.kind] = counts.get(item.kind, 0) + 1
    return counts


def mark_seen(kind: str) -> None:
    """Remember that this queue has been looked at, so the light goes out."""
    from . import atomic

    if kind not in KINDS:
        return
    seen = atomic.read_json(seen_file(), default={}) or {}
    seen[kind] = _dt.datetime.now().isoformat(timespec="seconds")
    atomic.write_json(seen_file(), seen)


def open_items() -> list[Item]:
    return [item for item in _read() if item.is_open]


def get(item_id: str) -> Item | None:
    for item in _read():
        if item.id == item_id:
            return item
    return None


def answer(item_id: str, option_key: str, *,
           run: Callable[[Item, Option], tuple[bool, str]] | None = None
           ) -> tuple[bool, str]:
    """Answer with one of the item's OWN options.

    `option_key` selects; it never supplies wording. Anything not matching a
    declared option is refused rather than passed through — that refusal is
    the whole security property of this path.
    """
    items = _read()
    for item in items:
        if item.id != item_id:
            continue
        if not item.is_open:
            return False, "That was already answered."

        option = item.option(option_key)
        if option is None:
            return False, ("That is not one of the answers offered, so "
                           "nothing was done.")

        item.status = DONE
        item.answer = option.key
        item.said = option.spoken()
        item.answered_at = _dt.datetime.now().isoformat(timespec="seconds")

        outcome = ""
        if run is not None:
            try:
                ok, outcome = run(item, option)
                if not ok:
                    item.staged = outcome
            except Exception as exc:                     # noqa: BLE001
                outcome = f"could not carry it out: {exc}"

        _write(items)
        _learn(item, option.key)
        events.record("decision", f"{item.title} — {option.label}",
                      source="approvals", detail={"id": item.id})
        return True, outcome or f"Answered: {option.label}"

    return False, "There is nothing waiting with that reference."


def reply(item_id: str, text: str) -> tuple[bool, str]:
    """Answer in the user's own words, when no option fits.

    Deliberately narrower than `answer`: it must name an item that is actually
    open, and the text is bounded. An unscoped "relay this text" endpoint is a
    remote-instruction endpoint by another name.
    """
    clean = (text or "").strip()
    if not clean:
        return False, "Nothing to say."
    if len(clean) > MAX_FREE_TEXT:
        return False, "That is too long to send as an answer."

    items = _read()
    for item in items:
        if item.id != item_id:
            continue
        if not item.is_open:
            return False, "That was already answered."

        item.status = DONE
        item.answer = ""
        # Prefixed with the question, because a session juggling several open
        # threads cannot otherwise tell which one this answers.
        item.said = f"About '{item.title}': {secrets.redact(clean)}"
        item.answered_at = _dt.datetime.now().isoformat(timespec="seconds")
        _write(items)
        _learn(item, "edited", correction=clean)
        events.record("decision", f"{item.title} — answered in own words",
                      source="approvals", detail={"id": item.id})
        return True, item.said

    return False, "There is nothing waiting with that reference."


def dismiss(item_id: str) -> tuple[bool, str]:
    """Clear it without answering.

    Clears the item AND anything sharing its context, because the reference
    system found the other way round: dismissing one half left the other, and
    the question reappeared as though nothing had happened.
    """
    items = _read()
    target = next((item for item in items if item.id == item_id), None)
    if target is None:
        return False, "There is nothing waiting with that reference."

    context = target.context
    cleared = 0
    for item in items:
        if not item.is_open:
            continue
        if item.id == item_id or (context and item.context == context):
            item.status = DROPPED
            item.answered_at = _dt.datetime.now().isoformat(timespec="seconds")
            cleared += 1
    _write(items)
    return True, f"Cleared {cleared}."


def _learn(item: Item, verdict_key: str, correction: str = "") -> None:
    """Feed the decision back, so the next draft of this kind is better.

    THE CALLER THAT DID NOT EXIST. `traces.record_verdict()` was written to be
    called exactly here and had no caller anywhere in the package, so the
    'what this person actually wants' card was always empty and the learning
    loop learned nothing while looking like one.
    """
    if not item.task:
        return
    verdict = {"yes": "accepted", "no": "rejected",
               "change": "edited", "edited": "edited"}.get(
                   verdict_key, "accepted")
    try:
        traces.record_verdict(item.task, item.body or item.title, verdict,
                              correction=correction, context=item.context)
    except Exception as problem:                         # noqa: BLE001
        # Learning is a convenience; failing to learn must never break the
        # answer the user just gave. But it must not be SILENT either.
        #
        # 2026-09-05: `test_a_decision_reaches_the_learning_card` failed twice
        # in seven full-suite runs and passed alone every time. The test was
        # not flaky -- this was. Whatever went wrong here was caught, dropped,
        # and the card simply had one fewer decision in it, which is precisely
        # the "learns nothing while looking like one" failure the docstring
        # above says this call was added to fix.
        #
        # `events` rather than a raise: the user's answer still stands.
        try:
            from . import events

            events.record("problem",
                          f"a decision about '{item.task}' was not learned "
                          f"from: {problem}",
                          source="approvals", detail={"task": item.task})
        except Exception:                                # noqa: BLE001
            pass
        return


def summary() -> str:
    waiting = open_items()
    if not waiting:
        return "Nothing is waiting for you."
    if len(waiting) == 1:
        return f"One thing is waiting: {waiting[0].title}"
    return f"{len(waiting)} things are waiting for you."


def as_json() -> str:
    return json.dumps([item.as_dict() for item in open_items()],
                      ensure_ascii=False, indent=2)
