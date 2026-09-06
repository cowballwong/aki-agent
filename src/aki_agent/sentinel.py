"""The check that runs before something is believed.

WHY THIS IS NOT ONE OF THE USER'S SPECIALISTS
---------------------------------------------
`specialists.py` deliberately holds no roles of its own: a specialist is
configuration, because one person's specialists are about regulations and
drawings and another's are about lesson plans. Putting a named role into the
engine is the failure that file exists to prevent.

This one is the exception, and the reason it is an exception is worth stating
rather than assuming. Checking that a claim has a source behind it, that a
verdict has evidence, that the wording does not overreach, and that a secret
is not about to leave the machine — none of that is anyone's profession. It
is the same check for a surveyor and for a music teacher, because it is a
check about *how a claim was arrived at*, not about what the claim is about.

The second reason is harder: a check the user has to remember to create is a
check that is not there on the day it was needed. Everything else in this
package is opt-in. This one is on the moment the assistant is installed,
without anybody choosing it.

ON BY DEFAULT, AND STILL THEIRS (reported 2026-08-20)
---------------------------------------------------
On by default is not the same as compulsory, and the first draft of this file
got that wrong: it made the checker undeletable, on the reasoning that a gate
with an off switch is decoration. That reasoning is wrong for *this* package.
Somebody who never asked for a checker and cannot turn one off will route
around it, and a checker being routed around is worse than one switched off,
because it is still reporting.

So it behaves like everything in the library:

- **On by default.** The off switch is a file that does not exist yet, so a
  fresh install has the check on, and a wiped state folder returns it to on
  rather than leaving it silently off. Same reasoning as the notification
  gate, where an unknown channel defaults to sending.
- **Turned off in one move**, and the assistant says so plainly when it is.
- **Edited by copying.** `adapt()` writes a new specialist carrying the four
  checks, in their own words and their own field, and leaves this one alone —
  exactly what `library.fork` does and for the same reason. `save()` in
  `specialists.py` refuses this key, which is what makes that true rather
  than merely intended: there is no route by which an edit lands on top of
  the original.

The result a user sees: a checker that was already there, that they can shape
into their own, and that they can switch off if they decide they do not want
it. What they cannot do is have it half-on — quietly weakened while still
reporting that a draft passed.

WHAT IT DOES NOT DO
-------------------
It does not rewrite. It reads a draft, says approve / flag / reject with
reasons, and hands it back. Rewriting would make it an author, and an author
cannot check its own work — which is the whole problem it was built for.

It also does not decide the substance. It is not a second opinion on whether
the answer is *good*; it checks whether the draft's claims stand up. That
boundary keeps it useful: a checker that argues about content gets overruled
and then ignored.

FAILING CLOSED
--------------
If the check cannot run, or comes back in a shape that cannot be read, the
result is a FLAG and never an approval. The alternative — treating an
unreachable checker as a pass — means the gate quietly stops existing at
exactly the moment something is wrong with the machine. That has happened in
this codebase before, in the notification gate, and the lesson was written
down there too: silence is not consent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import atomic, memory, paths, secrets, specialists

# The key no user specialist may take. Guarded in `specialists.save`.
KEY = specialists.BUILT_IN_KEY

# Checking is bounded work — a draft and its sources. Half the normal
# specialist ceiling, so a stuck check does not hold up an outbound message
# for ten minutes.
TIMEOUT = 300

# The four checks, in the order they are reported. Names are the parse keys
# as well as the display names, so a rename cannot leave the two disagreeing.
CHECKS = ("sources", "evidence", "language", "privacy")

APPROVE = "approve"
FLAG = "flag"
REJECT = "reject"

PURPOSE = (
    "Checks a draft before it is shown, recorded or sent: whether its "
    "sources are real, its verdicts are evidenced, its wording claims no "
    "more than the evidence supports, and nothing private is about to leave."
)

BRIEF = """\
Something has been drafted and is about to be shown to the person you work
for, written into their records, or sent outward. You look at it first.

You check four things and nothing else. You do not rewrite it, and you do not
substitute your own judgement for the drafter's on the substance of the work.

1. SOURCES — every citation, quotation, figure, date, name and reference in
   the draft must resolve to something real that actually says it. Open the
   source and read it. Mark each one:
     CONFIRMED    the source exists and says this
     PLAUSIBLE    consistent with the source, but not stated outright
     NOT FOUND    no source given, or the source does not exist
     CONTRADICTED the source says something else
   Never accept a figure or a reference because it sounds right, because it
   appeared earlier in the conversation, or because you remember it. Those
   are the three ways a wrong number gets through.

2. EVIDENCE — no conclusion, status or verdict without something traceable
   behind it. Anything marked done, complete, correct, in order, settled,
   approved or agreed needs a reference that says so, naming the document and
   where in it. A gap that has quietly turned into a pass is the exact failure
   this check exists for.

3. LANGUAGE — the strength of the wording must not exceed the strength of the
   evidence. "proves", "confirms", "guarantees", "ensures" where the evidence
   supports only "suggests", "indicates" or "is consistent with" is an
   overstatement: name the phrase and give the weaker wording that fits.
   The same check catches a step reported as finished when it was only
   attempted. "I restarted it" and "I restarted it and saw the new one
   running" are different claims, and only the second one is evidence.
   Also: no authority that was never given. The assistant does not approve,
   certify, sign off or guarantee anything on the user's behalf.

4. PRIVACY — nothing leaving the machine may carry a password, key, token or
   account detail. Nothing private to the user, or to a third party they owe
   confidence to, may appear anywhere it was not meant to go. If you cannot
   tell whether the draft is going outward, assume it is.

Answer in exactly this shape, and put nothing before it:

VERDICT: APPROVE
SOURCES: pass - every reference opened and matched
EVIDENCE: pass - ...
LANGUAGE: flag - "confirms the account is closed" is supported only by ...
PRIVACY: pass - ...

Each of the four lines is pass, flag or fail, then a dash, then the reason.
Quote the line at fault. After those five lines you may add a short paragraph
if something needs explaining, and nothing more.

  APPROVE  all four pass. The draft goes on unchanged.
  FLAG     it can go on, but with a concern the person must see first.
  REJECT   at least one check fails in a way that would mislead someone.
           Say which line, and what would have to change.

A source that is fabricated or contradicted is always REJECT. A password or
key in something going outward is always REJECT.

Where you could not verify something — no source was given, a file would not
open, a link would not load — that is not a pass. Say plainly that you could
not verify it and FLAG at least. An unchecked claim reported as checked is
worse than no check, because it gets acted on with confidence.

Write your reasons in the language the draft is written in.
"""


def agent() -> specialists.Specialist:
    """The checker itself, built fresh each time it is asked for.

    Built rather than stored, for the same reason `specialists.build_prompt`
    assembles the standing rules rather than saving them: anything on disk is
    something an update, a sync conflict or a careless edit can hollow out.
    A brief that only ever exists in code cannot come back weakened.
    """
    return specialists.Specialist(
        key=KEY,
        name="Sentinel",
        purpose=PURPOSE,
        brief=BRIEF,
        may_write=False,
        timeout_seconds=TIMEOUT,
    )


# ---------------------------------------------------------------------------
# The switch
# ---------------------------------------------------------------------------

def switch_file() -> Path:
    return paths.state_dir() / "sentinel.json"


def is_on() -> bool:
    """Whether the assistant should check drafts without being asked.

    ABSENCE MEANS ON, AND THAT IS THE WHOLE DESIGN
    ----------------------------------------------
    The file only exists once somebody has turned the check off. So a fresh
    install has it on, and — the part that actually earns the decision — a
    state folder that gets wiped, corrupted or restored from a machine where
    it was never written comes back **on**.

    Store it the other way round and every one of those accidents silently
    disables the check, with the assistant still reporting drafts as fine
    because nothing failed. `notify.py` reached the same conclusion about
    unknown channels: the default has to be the direction where a mistake is
    visible.
    """
    stored = atomic.read_json(switch_file(), default=None)
    if not isinstance(stored, dict):
        return True
    return bool(stored.get("on", True))


def turn_on() -> str:
    atomic.write_json(switch_file(), {"on": True})
    return "The check is on. Drafts get looked at before they go anywhere."


def turn_off() -> str:
    atomic.write_json(switch_file(), {"on": False})
    memory.log_event("the draft check was turned off")
    return ("The check is off. Nothing will be verified before it is shown, "
            "recorded or sent — turn it back on whenever you want it.")


# ---------------------------------------------------------------------------
# Editing without editing
# ---------------------------------------------------------------------------

def adapt(new_name: str, brief: str = "",
          reads: tuple[str, ...] = ()) -> tuple[specialists.Specialist, list[str]]:
    """Save a version of the checker shaped to the user's own field.

    A copy under a new name, never a write on top of this one. Two reasons,
    and the second is the one that keeps mattering:

    1. An upgrade replaces the built-in brief wholesale. If a user's edits
       lived in it, every upgrade would either destroy their work or have to
       ask them about it — the position `library.fork` was written to avoid.
    2. Somebody who narrows the four checks to their own field should not
       thereby remove the general check from their assistant. They end up
       with both, and the built-in one keeps doing what it did.

    An empty `brief` means "the same checks, under my own name", so the
    built-in brief is copied across rather than left blank -- a specialist
    saved with no brief is one that will not work, and `problems()` would say
    so after the user had already been told it was created.
    """
    made = specialists.Specialist(
        key="",
        name=new_name,
        purpose=PURPOSE,
        brief=(brief.strip() or BRIEF),
        reads=reads,
        may_write=False,
        timeout_seconds=TIMEOUT,
    )
    return specialists.save(made)


@dataclass
class Verdict:
    """What came back, in a shape the caller can branch on."""

    outcome: str = FLAG
    checks: dict[str, str] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    note: str = ""
    raw: str = ""
    ran: bool = True
    seconds: float = 0.0

    @property
    def approved(self) -> bool:
        return self.outcome == APPROVE

    @property
    def blocked(self) -> bool:
        """Whether this must not go on without the drafter redoing it."""
        return self.outcome == REJECT

    def failures(self) -> list[str]:
        """The checks that did not pass, worst first, as readable lines."""
        order = {"fail": 0, "flag": 1}
        named = [(order.get(state, 2), name) for name, state
                 in self.checks.items() if state in order]
        return [f"{name}: {self.reasons.get(name, '') or self.checks[name]}"
                for _, name in sorted(named)]

    def line(self) -> str:
        """One line, for a log or a status strip.

        THE SENTENCE THIS FUNCTION IS NOT ALLOWED TO SAY
        -----------------------------------------------
        The first version read: no failures, therefore "all four checks
        passed". An answer that came back in an unreadable shape has no
        failures — nothing parsed at all — and so was reported as a clean
        pass. The checker built to catch a claim with no evidence behind it
        was making one.

        Absence of a recorded failure is not a recorded pass, and the two
        have to be different sentences here.
        """
        if not self.ran:
            return "flag - the check did not run, so nothing was verified"
        if not self.checks:
            return (f"{self.outcome} - the answer could not be read, so "
                    "nothing in this draft has been verified")
        problems = self.failures()
        missing = [name for name in CHECKS if name not in self.checks]
        if not problems and not missing:
            return f"{self.outcome} - all four checks passed"
        if missing:
            problems = problems + ["not reported on: " + ", ".join(missing)]
        return f"{self.outcome} - " + "; ".join(problems)


_VERDICT_WORDS = {"approve": APPROVE, "approved": APPROVE,
                  "flag": FLAG, "flagged": FLAG,
                  "reject": REJECT, "rejected": REJECT}

_STATES = {"pass": "pass", "passed": "pass", "ok": "pass",
           "flag": "flag", "flagged": "flag", "concern": "flag",
           "fail": "fail", "failed": "fail", "reject": "fail"}


def parse(text: str) -> Verdict:
    """Read the checker's answer.

    Lenient about shape, strict about the outcome. A model writing `**VERDICT:
    REJECT**` or leading with a courtesy sentence should not silently become
    an approval because the parser wanted an exact line — but neither should
    anything be *promoted* to a pass by a parser being generous. So: find the
    words if they are findable, and where they are not, fall to FLAG.
    """
    verdict = Verdict(raw=text or "")
    if not (text or "").strip():
        verdict.note = "The check returned nothing."
        return verdict

    for raw_line in text.splitlines():
        line = raw_line.strip().strip("*_# ").strip()
        if not line:
            continue

        head, _, tail = line.partition(":")
        label = head.strip().strip("*_ ").casefold()
        rest = tail.strip()

        if label == "verdict":
            word = re.split(r"[^a-z]+", rest.casefold().strip("*_ "))
            for piece in word:
                if piece in _VERDICT_WORDS:
                    verdict.outcome = _VERDICT_WORDS[piece]
                    break
            continue

        if label in CHECKS and rest:
            found = re.match(r"([A-Za-z]+)\s*(.*)$", rest, flags=re.DOTALL)
            state = _STATES.get(found.group(1).casefold()) if found else None
            reason = found.group(2) if found else rest
            if state is None:
                # A line we cannot read is not a pass. Recording it as a flag
                # keeps the concern visible instead of dropping it.
                verdict.checks[label] = "flag"
                verdict.reasons[label] = rest
            else:
                verdict.checks[label] = state
                verdict.reasons[label] = reason.lstrip(" -–—:").strip()

    # A stated APPROVE that contradicts its own check lines is not honoured.
    # This is not defensiveness for its own sake: the failure mode of a model
    # asked for a verdict and a breakdown is to write the breakdown carefully
    # and then round the summary off to something agreeable.
    if verdict.outcome == APPROVE:
        states = set(verdict.checks.values())
        missing = [name for name in CHECKS if name not in verdict.checks]
        # Ordered worst-first, so a run that both failed a check and skipped
        # another lands on the failure rather than on the milder complaint.
        if "fail" in states:
            verdict.outcome = REJECT
            verdict.note = ("Reported as approved, but a check failed. The "
                            "failed check is what counts.")
        elif "flag" in states:
            verdict.outcome = FLAG
            verdict.note = ("Reported as approved, but a check was flagged. "
                            "The flag is what counts.")
        elif missing:
            # An approval with no breakdown behind it is the same defect as a
            # draft with no sources behind it, and gets the same treatment.
            verdict.outcome = FLAG
            verdict.note = ("Reported as approved, but " + ", ".join(missing)
                            + (" was" if len(missing) == 1 else " were")
                            + " not actually reported on. Treat that as "
                              "unchecked.")

    return verdict


def review(draft: str, sources: str = "", workspace: Path | None = None
           ) -> Verdict:
    """Put a draft in front of the checker and wait for the answer.

    `sources` is whatever the draft rests on — file paths, quoted extracts,
    the reasoning that produced it. Passing nothing is allowed and is itself
    informative: a draft arriving with no stated basis is very likely to come
    back flagged on the evidence check, which is the correct outcome rather
    than an inconvenience.

    This does not consult `is_on()`. The switch governs whether the assistant
    checks drafts *without being asked*; somebody who has turned that off and
    then asks for a check has asked for a check. Refusing on the grounds of
    their earlier preference would be the software arguing with them.
    """
    task_parts = ["Check this draft.", "", "--- the draft ---", "",
                  draft.strip()]
    if sources.strip():
        task_parts += ["", "--- what it rests on ---", "", sources.strip()]
    else:
        task_parts += ["", "No sources were supplied with this draft. Find "
                       "what you can, and say plainly what you could not "
                       "verify."]

    consultation = specialists.consult(agent(), "\n".join(task_parts),
                                       workspace=workspace)

    if not consultation.ok:
        # Fail closed. See the module docstring.
        verdict = Verdict(outcome=FLAG, ran=False, seconds=consultation.seconds)
        verdict.note = ("The check could not be run, so nothing in this draft "
                        "has been verified. Treat it as unchecked.")
        memory.log_event("the check did not run - draft not verified")
        return verdict

    verdict = parse(consultation.answer)
    verdict.seconds = consultation.seconds
    memory.log_event("checked a draft: " + secrets.redact(verdict.line())[:120])
    return verdict
