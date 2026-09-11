"""Scheduled work: one definition, two operating systems.

THE LESSON THIS MODULE EXISTS TO APPLY
--------------------------------------
From the system this package derives from, recorded in its own notes after it
happened: **a tool is not automation.** Its session-recycling mechanism was
built, worked correctly, and sat there for weeks doing nothing, because
nothing ever triggered it. The capability existed; the automation did not.

So schedules ship *with* the tools. A default set is installed at setup, not
offered as something to configure later.

**A small fixed set, deliberately.** The source system accumulated 43
scheduled tasks. Nobody can hold 43 tasks in their head, nobody audits them,
and when one silently stops nobody notices. This ships ten, of which seven run
by default. A student can add more; they will not be given a machine full of
jobs they never chose.

The last three are the Event ones added on 2026-09-05, and they ship
`enabled=False` on purpose: they are examples you can read and switch on, not
work that starts happening to you because you upgraded. That distinction is
the reason the number can grow without the set getting heavier.

Six until 2026-08-23, when the Me time watch was built. The number is not the
principle and should not be defended as one — what matters is that the set
stays small enough to read in one sitting and that every entry does something
the user would recognise as theirs. The seventh is the half of Me time that
was missing: the switch, the state and the copy all existed, and nothing read
a mailbox, so the button recorded that somebody had stepped away and then did
nothing about it. On every day nobody presses it, that task reads one small
file and stops.

*Installed at setup* was a claim this file made for a while and nothing
honoured: `install()` was reachable only from the dashboard, which setup never
mentioned either, so a normal install ended with every schedule defined and
none of them running. Setup now calls `cli schedule-install --yes`, `doctor`
counts what is installed, and `cli schedule-status` will say so plainly.

ONE DEFINITION, TWO PLATFORMS
-----------------------------
A `ScheduledTask` is plain data. Each platform has a generator turning it into
that platform's native form — Task Scheduler on Windows, launchd on macOS.

The generators are pure functions returning the command or file content, which
means the *whole translation* is testable on any machine, including the one
platform you do not have. That is why they are written this way: it is the
only way to have any confidence in the macOS half without a Mac.

Actually installing is a separate, side-effecting function you must ask for.

EVERYTHING IS USER-SCOPE
------------------------
No `SYSTEM` account, no `sudo`, no `/Library/LaunchDaemons`. Tasks run as the
user, when the user is logged in. A personal assistant has no business running
as a machine service.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import subprocess
import time
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

from . import paths


class CouldNotAsk(RuntimeError):
    """The scheduler could not be queried at all.

    Distinct from "nothing is installed", and the distinction is the whole
    point of the class. Those two answers used to be the same empty list, so
    a machine that could not be asked looked exactly like a machine with no
    tasks — and every caller went on to act as though the user had none.
    """

# Prefix for every task this package creates, so that listing and removing
# ours never touches anyone else's.
# Named after the package. The prefix was left behind by the rename and is
# corrected here rather than later: nothing has been installed under the old
# one yet (scheduling had no caller until the day this was written), so this
# is the last moment it can be changed for free.
TASK_PREFIX = "AkiAgent"


# The kinds of trigger a task can have.
#
#   "time"     at a particular time, on particular days
#   "interval" every N minutes, all day
#   "login"    when the user logs in
#   "watch"    when a folder changes
#
# The first three work on both platforms. The fourth does not, and that is
# handled honestly rather than faked -- see `supported_triggers()`.
TRIGGERS = ("time", "interval", "login", "watch", "happening")

# What each one is called on screen.
#
# Named after the moment, not the mechanism. Home Assistant spent this year
# making the same move -- their 2026.8 release renamed every trigger after
# what happens ("Door opened") rather than how it is detected ("state changed
# on binary_sensor") -- and the reason is that nobody scheduling their own
# work thinks in terms of intervals and watches. The keys are unchanged, so
# nothing stored has to be rewritten; only what a person reads.
KIND_NAMES = {
    "time": "At a set time",
    "interval": "Every so often",
    "login": "When you log in",
    "watch": "When a folder changes",
    "happening": "When something happens",
}

WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


# The sorts of thing an "Event" task can wait for.
#
# These are `events.KINDS` said in the second person, plus "any". The keys
# are the event log's own, so nothing has to be translated at match time --
# and if a new kind is ever recorded, the worst that happens here is that it
# shows under its own short name.
#
# Deliberately NOT the full list: `said` and `heard` are the assistant and
# the user talking, and a task that fires every time you type would run
# constantly and tell you what you already know.
# Every one of these is checked against the list of things that actually call
# `events.record`. "change" was written here first and taken out again the same
# hour: the kind is declared in `events.KINDS` and nothing in the package has
# ever recorded one, so offering "when a file is written" would have been a
# choice that could be made and could never fire. An option that cannot happen
# is worse than a missing option -- the person who picks it concludes the
# feature is broken, and they are right.
EVENT_KIND_NAMES = {
    "any": "anything happens",
    "problem": "something goes wrong",
    "task": "a scheduled task runs",
    "decision": "something is approved or refused",
    "note": "the assistant notes something",
}


# The three kinds of scheduled work -- WHEN it runs, not whether it talks.
#
# WHAT CHANGED, AND WHY (reported 2026-09-05)
# -----------------------------------------
# These two words used to mean "has something to tell you" and "keeps the
# machine honest, you should never hear from it". That is a real distinction
# and it was the right one to draw -- but it was drawn in the wrong place. It
# made the TAB mean one thing (does it talk to you) while the trigger next to
# it meant another (when does it run), so a task could sit under Heartbeat and
# be scheduled for 08:05, and both statements were true and unrelated.
# `release-held` was exactly that.
#
# -- the tab IS
# the trigger. So the timing meaning wins here, and "does it reach you" moves
# to where it can be answered on its own: `announce`, a field that already
# existed and that Notifications already reads. Nothing was invented for it;
# it was only ever unreachable from the form.
#
# The gain is that the two questions stop being one question. A task can now
# be a fixed rhythm that DOES interrupt you (`me-time-watch`) or a clock time
# that never says a word (`release-held`), and the page can say so.
KINDS_OF_WORK = {
    "loop": ("Loops", "Runs on the clock — at a time you set, on the "
                      "days you choose."),
    "heartbeat": ("Heartbeat", "Runs on a fixed rhythm — every so often, "
                               "all day, without being asked."),
    "event": ("Event", "Runs when something happens — a folder changes, "
                       "you log in, or something you describe."),
}


# Which tab a trigger belongs to. One family per tab, and no trigger in two.
#
# This is what makes the tab and the trigger incapable of disagreeing: `work`
# is no longer stored and chosen separately, it is read off the trigger. See
# `ScheduledTask.work`.
WORK_OF_TRIGGER = {
    "time": "loop",
    "interval": "heartbeat",
    "login": "event",
    "watch": "event",
    "happening": "event",
}

# What the form offers on each tab, in the order it offers them. Loops and
# Heartbeat have exactly one each, which is the whole reason the "+ Add
# trigger" picker could go: there was nothing left to pick.
TRIGGERS_FOR_WORK = {
    "loop": ("time",),
    "heartbeat": ("interval",),
    "event": ("happening", "watch", "login"),
}



@dataclass(frozen=True)
class Trigger:
    """One moment that starts a task.

    WHY THIS IS A CLASS AND NOT FIVE FIELDS ON THE TASK (2026-08-21)
    ---------------------------------------------------------------
    It used to be five: `trigger`, `hour`, `minute`, `weekdays`,
    `every_minutes`, `watch_path`, all flat on `ScheduledTask`. Which meant
    the Add-a-task form had to show all of them at once, including the ones
    that do nothing for the kind you picked -- the caption on that form read
    "only for the folder trigger", which is a form apologising for its own
    shape.

    The settings could not follow
    the choice while they belonged to the task rather than to the trigger.
    Every system read for this -- Windows Task Scheduler, Home Assistant, n8n
    -- puts them on the trigger.

    SEVERAL TRIGGERS MEAN *OR*, AND ONE FIRING IS ONE RUN.
    There is no useful AND between triggers: a trigger is a moment, and two
    moments do not coincide. "Only on weekdays *and* only when the folder
    changed" is one trigger and one condition, which is a different feature
    and deliberately not built here.
    """

    kind: str = "time"
    hour: int = 9
    minute: int = 0
    # Days it runs. Empty means every day. Only for kind == "time".
    weekdays: tuple[str, ...] = ()
    # Only for kind == "interval" (and the Windows fallback for "watch"
    # and "happening" -- neither platform hands us a real hook, so both are
    # a poll that stops early when nothing moved).
    every_minutes: int = 60
    # Only for kind == "watch".
    watch_path: str = ""

    # Only for kind == "happening". Which sort of thing to wait for, and
    # optionally some words it has to contain.
    #
    # `match` is that -- free
    # text, no syntax to learn, matched case-insensitively against the text
    # of the event. `event_kind` narrows it to one of `events.KINDS`, or
    # "any" for all of them, so "when anything goes wrong" is a choice and
    # not a regular expression.
    event_kind: str = "any"
    match: str = ""

    @property
    def name(self) -> str:
        return KIND_NAMES.get(self.kind, self.kind)

    def when(self) -> str:
        """This one moment, in words a person would use."""
        if self.kind == "interval":
            if self.every_minutes % 60 == 0 and self.every_minutes >= 60:
                hours = self.every_minutes // 60
                return f"every {hours} hour{'s' if hours != 1 else ''}"
            return f"every {self.every_minutes} minutes"
        if self.kind == "login":
            return "when you log in"
        if self.kind == "watch":
            where = self.watch_path or "a folder"
            if paths.is_windows():
                # Said as it happens. Task Scheduler has no folder-watch
                # trigger, so this is a poll that checks the folder and stops
                # if nothing moved -- which is a different sentence from "when
                # the folder changes", and the page should not print the one
                # it cannot deliver.
                every = max(1, self.every_minutes or 5)
                return f"every {every} min, and only if {where} changed"
            return f"when {where} changes"
        if self.kind == "happening":
            what = EVENT_KIND_NAMES.get(self.event_kind, self.event_kind)
            said = what if self.event_kind != "any" else "anything happens"
            if self.match:
                said += f" mentioning ‘{self.match}’"
            # Said as it happens, for the same reason `watch` is. There is no
            # event hook on either platform -- this is a poll that reads the
            # log and stops if there is nothing new since last time. Printing
            # "when X happens" would promise an immediacy the package cannot
            # deliver, which is the complaint `watch` already answered.
            every = max(1, self.every_minutes or 5)
            return f"every {every} min, and only if {said}"
        days = ", ".join(self.weekdays) if self.weekdays else "every day"
        return f"{self.hour:02d}:{self.minute:02d}, {days}"

    def problems(self) -> list[str]:
        found: list[str] = []
        if self.kind not in TRIGGERS:
            found.append(f"'{self.kind}' is not a kind of trigger.")
            return found

        if self.kind == "time":
            if not 0 <= self.hour <= 23 or not 0 <= self.minute <= 59:
                found.append("The time is not a real time.")
            unknown = [day for day in self.weekdays if day not in WEEKDAYS]
            if unknown:
                found.append(f"{', '.join(unknown)} is not a day of the week.")
        elif self.kind == "interval":
            if self.every_minutes < 5:
                found.append(
                    "Running more often than every five minutes is almost "
                    "never useful and will get tiring quickly."
                )
            elif self.every_minutes > 1440:
                found.append(
                    "More than a day apart -- use a daily time instead, so "
                    "you know when it will happen."
                )
        elif self.kind == "watch":
            if not self.watch_path:
                found.append("It needs a folder to watch.")
            elif not Path(self.watch_path).exists():
                found.append(f"There is no folder at {self.watch_path}.")
        elif self.kind == "happening":
            if self.event_kind not in EVENT_KIND_NAMES:
                found.append(
                    f"'{self.event_kind}' is not something it can wait for.")
            if self.every_minutes < 1:
                found.append("It needs to check at least once in a while.")
            # No complaint about an empty `match`: "any problem at all" is a
            # perfectly good thing to want, and the kind on its own says it.
        return found

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "hour": self.hour,
            "minute": self.minute,
            "weekdays": list(self.weekdays),
            "every_minutes": self.every_minutes,
            "watch_path": self.watch_path,
            "event_kind": self.event_kind,
            "match": self.match,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Trigger":
        return cls(
            kind=str(data.get("kind", "time")),
            hour=int(data.get("hour", 9)),
            minute=int(data.get("minute", 0)),
            weekdays=tuple(data.get("weekdays") or ()),
            every_minutes=int(data.get("every_minutes", 60)),
            watch_path=str(data.get("watch_path", "")),
            # Defaults chosen so a task written before this existed loads
            # unchanged rather than failing: neither field means anything
            # unless the kind is "happening".
            event_kind=str(data.get("event_kind") or "any"),
            match=str(data.get("match", "")),
        )


@dataclass
class ScheduledTask:
    """One recurring job, described once."""

    key: str                  # short identifier, e.g. "morning-summary"
    title: str                # what the user sees
    why: str                  # plain-language reason, shown before installing
    prompt: str = ""          # what the assistant is asked to do
    enabled: bool = True

    # Every moment that starts it. Any one of them is enough; see `Trigger`.
    triggers: tuple[Trigger, ...] = ()

    # True for the six that ship with the package, False for the user's own.
    built_in: bool = False

    # Whether what this task produces IS the day's record, rather than a
    # message about it.
    #
    # WHY THIS EXISTS (2026-08-24)
    # ----------------------------
    # The evening wrap-up is told to "write today's narrative entry". It was
    # never able to: a headless run has nobody to approve a write, so every
    # attempt was refused -- and the run was recorded as "finished in 194s".
    # It composed a whole day's account, could not save one word, said so in a
    # message, and the ledger says it succeeded.
    #
    # The fix is not to hand an unattended agent a way to write files. It is
    # to notice that the package is already holding the text: the runner has
    # the output. So the assistant writes the words and this program saves
    # them, which needs no permission at all and cannot be talked into
    # saving something else.
    records_day: bool = False

    # Whether this task's result is worth interrupting somebody for.
    #
    # WHY THIS IS PER TASK (reported 2026-08-20)
    # ----------------------------------------
    # Scheduled results started going to Telegram, and within two hours he got
    # a phone message -- launcher closed, dashboard shut -- reporting that
    # there was nothing to report. The first fix was "say nothing when there is
    # nothing to say", which is a guess about what he wants to hear. He asked
    # for the better thing: **let me choose which ones reach my phone.**
    #
    # He was right, and the difference matters. Guessing is a heuristic that
    # will be wrong for somebody; a switch is an answer. The guess is kept as
    # well, as a second line -- a task he *has* asked to hear from should still
    # not wake him to say it has nothing.
    #
    # The default is set per task rather than globally: a morning summary
    # exists to be read, and a checkpoint doing its job correctly is a
    # checkpoint nobody should ever hear from.
    announce: bool = True

    def __post_init__(self) -> None:
        # A task with no trigger would be a job that never runs, reported as
        # installed. One set time is the least surprising default; the form
        # opens on exactly the same thing.
        self.triggers = tuple(self.triggers) or (Trigger(),)

    @property
    def work(self) -> str:
        """Which tab this belongs on -- read off the trigger, never stored.

        It WAS stored, and chosen separately from the trigger, which is how
        `release-held` came to sit under "Heartbeat" while running at 08:05.
        Two fields for one fact is two fields that will disagree; the only
        question is when. Deriving it means the disagreement is not
        expressible.

        The first trigger decides, and since 2026-09-05 the form writes
        exactly one, so there is nothing to break the tie on anything the
        form has made.
        """
        for one in self.triggers:
            found = WORK_OF_TRIGGER.get(one.kind)
            if found:
                return found
        return "loop"

    @property
    def task_name(self) -> str:
        return f"{TASK_PREFIX}-{self.key}"

    @property
    def label(self) -> str:
        """Reverse-DNS style label, which is what launchd expects."""
        return f"com.aki-agent.{self.key}"

    def when(self) -> str:
        """When it runs, in words a person would use.

        Several triggers are joined with "or", because that is what they
        mean -- whichever happens first starts it.
        """
        if not self.triggers:
            return "never -- it has no trigger"
        return ", or ".join(one.when() for one in self.triggers)

    def describe(self) -> str:
        return f"{self.title} — {self.when()}. {self.why}"

    def problems(self) -> list[str]:
        """What is wrong with this task definition, in plain language."""
        found: list[str] = []

        if not self.title.strip():
            found.append("It needs a name.")
        if not self.prompt.strip():
            found.append("It needs instructions -- what should it actually do?")
        if not self.triggers:
            found.append("It needs at least one trigger, or it will never run.")

        for one in self.triggers:
            found.extend(one.problems())

        # launchd has exactly one StartInterval per job, so a second
        # "every so often" could be written down and would then never fire.
        # Said here rather than discovered on somebody's Mac.
        intervals = sum(1 for one in self.triggers if one.kind == "interval")
        if intervals > 1:
            found.append(
                "Only one \u2018every so often\u2019 trigger per task -- macOS "
                "cannot run two, and the second would silently never fire. "
                "Use set times instead, or a second task."
            )

        return found


# ---------------------------------------------------------------------------
# The default set. Six, not forty-three.
# ---------------------------------------------------------------------------

DEFAULT_TASKS: tuple[ScheduledTask, ...] = (
    ScheduledTask(
        key="morning-summary",
        title="Morning summary",
        why="tells you what is waiting before the day starts",
        triggers=(Trigger(hour=8, minute=0, weekdays=("MON", "TUE", "WED", "THU", "FRI")),),
        # "Say if nothing does" was an invitation to send "nothing needs
        # attention" to somebody's phone at eight in the morning. The
        # say-nothing rule now lives once in `tasks._prompt_for`.
        # The empty day is the common one before a real project exists, and
        # it used to arrive as a paragraph touring every demo folder.
        prompt=("Read my workspace and give me a short summary of what needs "
                "attention today. Be brief. If nothing needs attention, say "
                "so in one line and name one next step -- do not tour the "
                "folders or list what is empty."),
        built_in=True,
    ),
    ScheduledTask(
        key="evening-wrapup",
        title="Evening wrap-up",
        why="writes down what happened today, so tomorrow starts informed",
        triggers=(Trigger(hour=18, minute=30, weekdays=("MON", "TUE", "WED", "THU", "FRI")),),
        # reported 2026-09-04, of a wrap-up that was fifteen engine upgrades,
        # eight session recycles and three port collisions:
        #
        # The old wording -- "what changed, what I decided, what is still
        # open" -- named no subject, and the machine's own log is by far the
        # loudest thing a headless run can read. So it wrote up itself. The
        # subject has to be said, the order has to be fixed, and the machine
        # has to be given a ceiling, or it takes the whole message again.
        # Written to the character. The first version of this said the same
        # things in 822 characters and blew the package's own prompt budget
        # (`test_the_prompt_is_still_inside_its_budget`) by nearly half --
        # 1446 against 1000, once the shared wrapper is added. The budget is
        # right: this runs every weekday for ever. The rules were made to fit
        # it rather than the other way round, which is the same call that was
        # made the last two times.
        prompt=("Today's entry, in order. One line each.\n"
                "1. What moved in my projects, named. None: 'No project "
                "work today.'\n"
                "2. What is on tomorrow. Nothing: say so.\n"
                "3. What is waiting on me. Nothing: 'Nothing waiting.'\n"
                "At most ONE line on the assistant itself, only if it "
                "changes my tomorrow -- never a list of upgrades or "
                "restarts.\n"
                "My projects are the point, not the machine. Entry only."),
        built_in=True,
        records_day=True,
    ),
    ScheduledTask(
        key="release-held",
        title="Deliver anything held",
        why=("delivers whatever was held as soon as your quiet hours end, "
             "whatever time that is"),
        # EVERY TEN MINUTES, NOT 08:05 (the maintainer's open question, decided
        # 2026-09-06)
        # -------------------------------------------------------------------
        # This ran once a day. The copy was corrected on 2026-09-05 to say so
        # honestly, and the behaviour was left as a question for him: a quiet
        # window that ends at 15:00 held everything until the following
        # morning, which is not what "quiet until three" means to anybody.
        #
        # Ten minutes costs nothing on the days nothing is held. `run_one`
        # reads one counter and returns before loading the configuration, and
        # `notify.release` re-checks quiet and leaves the queue untouched if
        # it is still on -- so running this often is the same as running it
        # once, except on the days it matters.
        #
        # The same shape as `me-time-watch` below, and for the same reason.
        #
        # `kind="interval"` is not optional decoration. Written first as
        # `Trigger(every_minutes=10)`, this stayed a TIME trigger -- `kind`
        # defaults to "time" and `hour` to 9 -- so it would have quietly
        # become "once a day at nine" while reading like "every ten minutes".
        # A worse version of the bug being fixed, and caught only because the
        # test asserts on the trigger rather than on the comment.
        triggers=(Trigger(kind="interval", every_minutes=10),),
        # Handled in `tasks.run_one`, like `__checkpoint__` and `__inbox__`.
        # This used to be the sentence "Deliver any notifications held while
        # I was unavailable" — plain English, handed to a model that has no
        # command for it, so the queue only ever grew.
        prompt="__release__",
        built_in=True,
    ),
    ScheduledTask(
        key="me-time-watch",
        title="Watch for something urgent while you are away",
        why=("this is what makes the Me time button mean anything — it reads "
             "your mail while you are away and interrupts you only for the "
             "words you said were worth interrupting for"),
        # Every ten minutes, and it costs nothing on the days it is off: the
        # first thing it does is read one small file and stop.
        triggers=(Trigger(kind="interval", every_minutes=10),),
        prompt="__me_time__",       # handled internally, no model call
        built_in=True,
        # This one is allowed to interrupt. It is the only thing in the
        # package whose entire purpose is to, and only while the user has
        # said so by pressing the button.
        announce=True,
    ),
    ScheduledTask(
        key="checkpoint",
        title="Save where I am, and restart the session when it is safe",
        why=("means a crash or a restart never loses the thread — and it is "
             "what keeps a session left running for days from filling up and "
             "grinding to a halt"),
        triggers=(Trigger(kind="interval", every_minutes=20),),
        prompt="__checkpoint__",     # handled internally, no model call
        built_in=True,
        # Housekeeping. Working correctly means nobody ever hears from it.
        announce=False,
    ),
    ScheduledTask(
        key="collect-messages",
        title="Pick up anything typed in the dashboard",
        why=("means a message you typed in the dashboard does not sit there "
             "unread — without this it queues forever"),
        # Five minutes, not thirty.
        #
        # WHY IT COULD BE SHORTENED (2026-08-20)
        # --------------------------------------
        # Thirty was chosen when every run cost a model call, so the interval
        # was really a budget. Since the empty queue is now answered before
        # the model is invoked at all -- no queue, no run, no cost -- the only
        # thing the interval still buys is latency, and latency is the whole
        # complaint: The maintainer typed into the dashboard, got no sign of it in his
        # session, and reasonably suspected something was broken. Nothing was;
        # he was waiting up to half an hour for a reply to something he had
        # just typed, which is indistinguishable from broken.
        triggers=(Trigger(kind="interval", every_minutes=5),),
        # `__inbox__` rather than a command written out here. The command
        # depends on where the engine ended up, this text is written before
        # that is known, and the previous version -- `python -m
        # aki_agent.inbox pending` -- failed on every real install while the
        # task reported success. See `engine.bootstrap`.
        prompt="__inbox__",
        built_in=True,
    ),
    ScheduledTask(
        key="weekly-tidy",
        title="Weekly tidy",
        why="checks the workspace for items that have gone quiet or stale",
        triggers=(Trigger(hour=9, minute=0, weekdays=("MON",)),),
        prompt=("Look through my workspace for anything that has not been "
                "touched in a while or that looks out of date, and list it."),
        built_in=True,
    ),

    # -----------------------------------------------------------------
    # Event tasks.
    #
    # ALL THREE SHIP SWITCHED OFF (`enabled=False`), and that is the whole
    # care taken here. `cli schedule-install` installs every default task
    # whose `enabled` is True, and it runs at setup and again on repair --
    # so three new entries with the default would have quietly started three
    # new jobs on every machine that already has the package, including his
    # students'. Adding a capability must not be the same act as switching it
    # on for people who never asked.
    #
    # Each one waits for a kind that something in this package actually
    # records. That was checked against the `events.record` call sites rather
    # than against `events.KINDS`, because the two do not agree -- see the
    # note on `EVENT_KIND_NAMES`.
    # -----------------------------------------------------------------
    ScheduledTask(
        key="on-problem",
        title="Tell me when something goes wrong",
        why=("problems are written to the log whether or not anybody is "
             "looking, and nobody looks -- this is the half that tells you"),
        triggers=(Trigger(kind="happening", event_kind="problem",
                          every_minutes=10),),
        prompt=("Something went wrong and was written to the event log. Say "
                "in one or two lines what it was and whether it needs me. "
                "If it looks like it fixed itself, say that instead."),
        built_in=True,
        enabled=False,
    ),
    ScheduledTask(
        key="on-approval-waiting",
        title="Tell me when something is waiting for me",
        why=("an approval nobody answers is work that has stopped, and the "
             "only sign of it is a line in a log"),
        # `approvals.py` records `("note", "Asked: <title>")`. Matching the
        # word rather than the kind alone is what keeps this from firing on
        # every other note the assistant makes.
        triggers=(Trigger(kind="happening", event_kind="note",
                          match="asked", every_minutes=10),),
        prompt=("Something is waiting for my decision. Say what it is in one "
                "line, and what happens if I do nothing."),
        built_in=True,
        enabled=False,
    ),
    ScheduledTask(
        key="on-login",
        title="Catch me up when I log in",
        why=("the machine keeps working when you are not at it, and this is "
             "the one moment you are certain to be there"),
        triggers=(Trigger(kind="login"),),
        prompt=("I have just logged in. In at most three lines: anything "
                "that went wrong while I was away, anything waiting on me, "
                "and what is next today. Nothing to report: say so in one "
                "line."),
        built_in=True,
        enabled=False,
    ),
)


# ---------------------------------------------------------------------------
# Windows — Task Scheduler
# ---------------------------------------------------------------------------

def runner_script(root: Path | None = None) -> Path:
    """The file the scheduler calls to run one task.

    `root` names a copy of the package other than the one running -- which
    is what re-pointing the schedule at the adopted engine needs, since
    that happens while this process is still importing the old copy.

    Ships with the package rather than being generated, so there is exactly
    one of it and it is covered by the same tests as everything else.

    A GAP THAT EXISTED HERE, AND WHY IT IS WORTH THE COMMENT
    --------------------------------------------------------
    Scheduling was built before this script was. `install()` happily created
    a real Task Scheduler entry pointing at a path that did not exist. The
    task installed, the dashboard showed "installed: yes", and it failed
    silently on every single firing.

    Nothing errored. The only symptom was an absence -- which is the hardest
    kind of bug to notice and the reason `install()` now checks that this file
    is really there before scheduling anything against it.
    """
    package_root = Path(root) if root else Path(__file__).resolve().parents[2]
    name = "run-task.bat" if paths.is_windows() else "run-task.command"
    return package_root / "bin" / name


def hidden_runner(root: Path | None = None) -> Path:
    """The script that runs a task without opening a window.

    Windows only, and it wraps `run-task.bat` rather than replacing it:
    Task Scheduler runs a .bat as the logged-in user, which always gets a
    console window, and there is no schtasks flag that suppresses it. A
    script host can ask for a hidden window; a batch file cannot ask on
    its own behalf.
    """
    package_root = Path(root) if root else Path(__file__).resolve().parents[2]
    return package_root / "bin" / "run-task.vbs"


def trigger_caveats() -> dict[str, str]:
    """What this platform cannot do properly, said where it applies.

    Kept apart from the names so the same sentence is not both a heading and
    a warning: the dropdown needs it while somebody is choosing, and the card
    needs it afterwards, but a card titled with the whole sentence stops
    having a title.
    """
    # Said on every platform, unlike the folder one. macOS can watch a folder
    # natively; nothing can be woken by a line arriving in a log, so there is
    # no version of this that is instant and the caveat is not a Windows
    # apology -- it is what the feature is.
    both = {
        "happening": ("Nothing can be woken the moment something happens, so "
                      "this checks every few minutes and runs if there is "
                      "anything new -- it is not instant."),
    }
    if paths.is_macos():
        return both
    return {
        "watch": ("Windows has no way to be told a folder changed, so this "
                  "checks every few minutes -- it is not instant."),
        **both,
    }


def supported_triggers() -> dict[str, str]:
    """Which triggers work on this platform, and what to say about the rest.

    Honesty about the gap matters here. `watch` has a native implementation on
    macOS (launchd's WatchPaths) and no simple equivalent through `schtasks`
    on Windows. Rather than pretend, the Windows answer is an interval that
    checks the folder -- and the user is told that is what is happening, so
    "why did it take four minutes to notice" has an answer.
    """
    named = dict(KIND_NAMES)
    if not paths.is_macos():
        named["watch"] = (KIND_NAMES["watch"] + " -- on Windows this is done "
                          "by checking every few minutes, so it is not instant")
    # Said on BOTH platforms, unlike `watch`. macOS can watch a folder
    # natively; neither system can wake a program because a line was written
    # to a log, so this one is a poll everywhere and there is no version of
    # it that is instant.
    named["happening"] = (KIND_NAMES["happening"] + " -- checked every few "
                          "minutes, so it is not instant")
    return named


def windows_target(task: ScheduledTask, runner: Path) -> tuple[str, str]:
    """What Windows should actually run: the program, and its arguments.

    Through the hidden-window wrapper when it is there, and straight at the
    batch file when it is not -- an install made before the wrapper existed
    must keep working, with a window, rather than not at all.
    """
    wrapper = hidden_runner(Path(runner).parent.parent)
    if wrapper.exists():
        return "wscript.exe", f'//B //Nologo "{wrapper}" "{task.key}"'
    return str(runner), f'"{task.key}"'


def newest_change_in(folder: str) -> float:
    """The most recent modification time anywhere under a folder.

    0.0 when the folder is missing or unreadable, which reads as "nothing has
    changed" rather than as an error -- a watched folder on a sync drive is
    routinely absent for a minute after a reboot, and the right response is
    to do nothing yet.
    """
    root = Path(folder)
    newest = 0.0
    try:
        if not root.exists():
            return 0.0
        newest = root.stat().st_mtime
        for entry in root.rglob("*"):
            try:
                newest = max(newest, entry.stat().st_mtime)
            except OSError:                               # pragma: no cover
                continue
    except OSError:                                       # pragma: no cover
        return 0.0
    return newest


def watch_marks_file() -> Path:
    return paths.state_dir() / "watched-folders.json"


def folder_has_changed(task_key: str, folder: str) -> bool:
    """Has this folder moved since the last time this task looked?

    THE PATH WAS COLLECTED AND THEN DISCARDED (2026-08-23)
    ------------------------------------------------------
    Windows Task Scheduler has no folder-watch trigger, so a watch trigger
    becomes a five-minute poll -- and `_windows_trigger_xml` dropped
    `watch_path` on the floor. The task then ran every five minutes for ever,
    whatever the folder did, while the schedule page said the folder was
    being watched.

    The maintainer asked for the Browse-folder button on 2026-08-21. It was feeding a
    field nothing read.

    A poll that remembers what it saw last time is a folder watch. Not an
    instant one, but an honest one.
    """
    from . import atomic

    marks = atomic.read_json(watch_marks_file(), default={}) or {}
    seen = float(marks.get(task_key) or 0.0)
    newest = newest_change_in(folder)
    if newest <= 0.0:
        return False
    if newest <= seen:
        return False

    marks[task_key] = newest
    atomic.write_json(watch_marks_file(), marks)
    return True


def event_has_happened(task_key: str, one: Trigger) -> bool:
    """Has the thing this trigger waits for happened since it last looked?

    The same shape as `folder_has_changed`, and for the same reason: neither
    platform gives us a hook. Task Scheduler cannot wake a program when a
    line is appended to a log, so an "Event" task is a poll that reads what
    is new and stops if there is nothing -- which is what the card on screen
    says it is, rather than promising something instant.

    The watermark is `events.unseen`/`mark_seen`, which already existed for
    exactly this: a named reader with its own position in the log. So a task
    that has been switched off for a week does not come back and fire once
    per missed event; it sees that there is something, runs once, and marks
    everything up to now as read.

    NOTE ON `events.py`'s own rule. That module says it is a record and that
    nothing consumes entries to decide what to do next. This does not break
    it: nothing here mutates an entry or removes one. The watermark is a
    reader's bookmark kept outside the log, which is the mechanism the module
    itself provides.
    """
    from . import events as events_module

    try:
        fresh = events_module.unseen(f"task:{task_key}", limit=200)
    except Exception:
        # A poll that cannot read the log must not take the task down with
        # it, and must not fire either -- silence is the safe answer.
        return False

    wanted = (one.event_kind or "any").strip()
    needle = (one.match or "").strip().lower()

    def fits(event) -> bool:
        if wanted != "any" and getattr(event, "kind", "") != wanted:
            return False
        if needle and needle not in str(getattr(event, "text", "")).lower():
            return False
        return True

    hits = [event for event in fresh if fits(event)]

    # Marked whether or not anything matched. Otherwise a log full of events
    # this task does not care about would be re-read on every single poll,
    # and the first matching one would arrive alongside a week of backlog.
    try:
        events_module.mark_seen(f"task:{task_key}")
    except Exception:
        pass

    return bool(hits)


def _windows_trigger_xml(one: Trigger) -> str:
    """One trigger, as Task Scheduler describes it.

    The date on a calendar trigger is a start boundary, not the day it runs;
    Task Scheduler requires one and ignores everything before it. A fixed
    date in the past is used rather than today's, so that the same task
    definition produces the same XML on any machine on any day -- which is
    what makes this function testable.
    """
    at = f"2020-01-01T{one.hour:02d}:{one.minute:02d}:00"

    if one.kind == "login":
        return ("      <LogonTrigger>\n"
                "        <Enabled>true</Enabled>\n"
                "      </LogonTrigger>")

    if one.kind in ("interval", "watch", "happening"):
        # Task Scheduler has no folder-watch trigger, and no way at all to be
        # woken by a line appearing in a log. `supported_triggers()` says so
        # out loud; here both become a poll, which is the honest fallback
        # rather than a pretend one.
        #
        # `happening` MUST be in this list. Left out, it falls through to the
        # calendar trigger at the bottom and installs as "09:00 every day" --
        # a task that reports itself as event-driven and is not, which is the
        # exact failure `watch_path` had before 2026-08-23.
        minutes = max(1, one.every_minutes if one.kind == "interval"
                      else (one.every_minutes or 5))
        return ("      <TimeTrigger>\n"
                "        <StartBoundary>2020-01-01T00:00:00</StartBoundary>\n"
                "        <Repetition>\n"
                f"          <Interval>PT{minutes}M</Interval>\n"
                "          <StopAtDurationEnd>false</StopAtDurationEnd>\n"
                "        </Repetition>\n"
                "        <Enabled>true</Enabled>\n"
                "      </TimeTrigger>")

    if one.weekdays:
        days = "\n".join(f"            <{day}/>" for day in
                          (_WINDOWS_DAYS[d] for d in one.weekdays
                           if d in _WINDOWS_DAYS))
        return ("      <CalendarTrigger>\n"
                f"        <StartBoundary>{at}</StartBoundary>\n"
                "        <Enabled>true</Enabled>\n"
                "        <ScheduleByWeek>\n"
                "          <DaysOfWeek>\n"
                f"{days}\n"
                "          </DaysOfWeek>\n"
                "          <WeeksInterval>1</WeeksInterval>\n"
                "        </ScheduleByWeek>\n"
                "      </CalendarTrigger>")

    return ("      <CalendarTrigger>\n"
            f"        <StartBoundary>{at}</StartBoundary>\n"
            "        <Enabled>true</Enabled>\n"
            "        <ScheduleByDay>\n"
            "          <DaysInterval>1</DaysInterval>\n"
            "        </ScheduleByDay>\n"
            "      </CalendarTrigger>")


_WINDOWS_DAYS = {
    "MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday",
    "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday", "SUN": "Sunday",
}


def windows_task_xml(task: ScheduledTask, runner: Path) -> str:
    """The whole task, as Task Scheduler XML.

    WHY XML AND NOT THE COMMAND LINE (2026-08-21)
    ---------------------------------------------
    `schtasks /Create /SC ...` can express exactly one trigger. Windows itself
    has supported many per task for twenty years -- only the command line
    cannot say so. Since a task may now hold several triggers, the command
    line stopped being able to describe what this package means, and the
    alternative to XML would have been one Windows task per trigger: three
    rows in Task Scheduler for one job, and an on/off switch that is on for
    some of them.

    Still no `/RU SYSTEM` and no `/RL HIGHEST`: `LeastPrivilege` and
    `InteractiveToken` below are the same promise the command line made by
    omission, now stated. It matters more than it looks -- a task created
    with a higher run level can only be changed by an administrator, which
    is exactly the trap that made the dashboard's off switch fail earlier
    today.

    Pure, like the command it replaces: returns the text, writes nothing.
    """
    program, arguments = windows_target(task, runner)
    triggers = "\n".join(_windows_trigger_xml(one) for one in task.triggers)

    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{_xml_escape(task.why)}</Description>
    <URI>\\{_xml_escape(task.task_name)}</URI>
  </RegistrationInfo>
  <Triggers>
{triggers}
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{_xml_escape(program)}</Command>
      <Arguments>{_xml_escape(arguments)}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def windows_command(task: ScheduledTask, xml_path: Path) -> list[str]:
    """The `schtasks` call that registers the XML above.

    Pure -- returns the command rather than running it, so the translation can
    be tested anywhere.
    """
    return ["schtasks", "/Create", "/TN", task.task_name,
            "/XML", str(xml_path), "/F"]


def windows_delete_command(task: ScheduledTask) -> list[str]:
    return ["schtasks", "/Delete", "/TN", task.task_name, "/F"]


# ---------------------------------------------------------------------------
# macOS — launchd
# ---------------------------------------------------------------------------

def _launchd_is_loaded(label: str) -> bool:
    """Is launchd already holding this job? False when it cannot be asked.

    False is the safe answer: it means "carry on and register it", which is
    what the caller did unconditionally before this existed. A wrong False
    costs one redundant notification; a wrong True would leave a task the user
    thinks is scheduled and is not.
    """
    try:
        result = subprocess.run(["launchctl", "list", label],
                                capture_output=True, text=True,
                                timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):         # pragma: no cover
        return False
    return result.returncode == 0


def launchd_plist_path(task: ScheduledTask) -> Path:
    """User-scope LaunchAgents, never the machine-wide LaunchDaemons."""
    return paths.home() / "Library" / "LaunchAgents" / f"{task.label}.plist"


def launchd_plist(task: ScheduledTask, runner: Path) -> str:
    """The plist content for this task.

    Pure, for the same reason as `windows_task_xml`: this is the half that
    cannot be tested on the machine it was written on, so it is written to be
    testable anywhere.

    launchd takes several triggers in one job without complaint, and each kind
    has its own key: `StartCalendarInterval` accepts an array of times,
    `WatchPaths` an array of folders, `RunAtLoad` a flag. So the union of a
    task's triggers is one plist, which is what keeps one Aki task equal to
    one operating-system job on both platforms.

    The exception is `StartInterval`, of which there is exactly one. A second
    "every so often" trigger is refused in `problems()` rather than written
    down here and silently never fired.

    launchd weekday numbers are 0-6 with Sunday as 0.
    """
    weekday_numbers = {
        "SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6,
    }

    calendar: list[str] = []
    watched: list[str] = []
    interval_seconds: int | None = None
    run_at_load = False

    for one in task.triggers:
        if one.kind == "login":
            run_at_load = True
        elif one.kind == "interval":
            if interval_seconds is None:
                interval_seconds = max(60, one.every_minutes * 60)
        elif one.kind == "watch":
            if one.watch_path:
                watched.append(one.watch_path)
        elif one.kind == "happening":
            # launchd watches FILES, not logs, and there is no key for "when
            # a line is appended". So this is a poll here too -- the same
            # answer Windows gives, for the same honest reason.
            #
            # This branch must exist. Without it the trigger has no
            # `weekdays`, falls through to the plain-calendar `else` below,
            # and installs as "09:00 every day" while the page says it is
            # event-driven.
            if interval_seconds is None:
                interval_seconds = max(60, (one.every_minutes or 5) * 60)
        elif one.weekdays:
            for day in one.weekdays:
                if day in weekday_numbers:
                    calendar.append(
                        "        <dict>\n"
                        f"            <key>Weekday</key><integer>{weekday_numbers[day]}</integer>\n"
                        f"            <key>Hour</key><integer>{one.hour}</integer>\n"
                        f"            <key>Minute</key><integer>{one.minute}</integer>\n"
                        "        </dict>")
        else:
            calendar.append(
                "        <dict>\n"
                f"            <key>Hour</key><integer>{one.hour}</integer>\n"
                f"            <key>Minute</key><integer>{one.minute}</integer>\n"
                "        </dict>")

    blocks: list[str] = []
    if calendar:
        blocks.append("    <key>StartCalendarInterval</key>\n"
                      "    <array>\n" + "\n".join(calendar) + "\n    </array>")
    if interval_seconds is not None:
        blocks.append("    <key>StartInterval</key>\n"
                      f"    <integer>{interval_seconds}</integer>")
    if watched:
        paths_xml = "\n".join(f"        <string>{_xml_escape(one)}</string>"
                              for one in watched)
        blocks.append("    <key>WatchPaths</key>\n"
                      "    <array>\n" + paths_xml + "\n    </array>")
    if not blocks:
        blocks.append("    <!-- Triggered by RunAtLoad, below. -->")

    schedule_block = "\n\n".join(blocks)
    run_at_load_text = "true" if run_at_load else "false"

    log_path = paths.log_dir() / f"{task.key}.log"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_xml_escape(task.label)}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{_xml_escape(str(runner))}</string>
        <string>{_xml_escape(task.key)}</string>
    </array>

{schedule_block}

    <key>RunAtLoad</key>
    <{run_at_load_text}/>

    <key>StandardOutPath</key>
    <string>{_xml_escape(str(log_path))}</string>
    <key>StandardErrorPath</key>
    <string>{_xml_escape(str(log_path))}</string>
</dict>
</plist>
"""


# ---------------------------------------------------------------------------
# Installing (side effects live here, and only here)
# ---------------------------------------------------------------------------

def describe_install(tasks: tuple[ScheduledTask, ...] = DEFAULT_TASKS) -> str:
    """What would be scheduled, for the user to approve before it happens."""
    lines = ["These would run automatically, as you, while you are logged in:",
             ""]
    for task in tasks:
        if task.enabled:
            lines.append(f"  - {task.describe()}")
    lines += ["", "Nothing runs as an administrator. You can remove any of "
                  "them at any time."]
    return "\n".join(lines)


def installed_with_file() -> Path:
    return paths.state_dir() / "installed-with.json"


def remember_install_root(root: Path | None = None) -> None:
    """Record which copy of the package the schedule was built against.

    WHY THIS MATTERS MORE THAN IT LOOKS
    -----------------------------------
    A scheduled task stores an absolute path to the runner script, and that
    script lives inside the package. Installed as a plugin, the package sits
    in a folder whose name contains its VERSION. So the next release lands in
    a new folder, and every task installed by the previous one keeps pointing
    at the old path.

    If that old folder is then cleaned up, all of them fail on every firing,
    reporting nothing, exactly like the class of defect this package was
    written to stop. Recording the root is what lets `doctor` notice and
    `repair` fix it, instead of the user discovering months later that their
    morning summary stopped.
    """
    from . import atomic

    try:
        paths.ensure_app_dirs()
        atomic.write_json(installed_with_file(), {
            "package_root": str(root or Path(__file__).resolve().parents[2]),
            "at": _dt.datetime.now().isoformat(timespec="seconds"),
        })
    except Exception:                                    # noqa: BLE001
        return


def install_root_is_current() -> tuple[bool, str]:
    """Is the schedule pointing at the copy of the package running now?"""
    from . import atomic

    recorded = (atomic.read_json(installed_with_file(), default={}) or {})
    was = str(recorded.get("package_root", ""))
    now = str(Path(__file__).resolve().parents[2])
    if not was:
        return True, ""                     # nothing installed, nothing stale
    if was == now:
        return True, ""
    return False, was


def running_elevated() -> bool:
    """Is this process running as an administrator?

    It matters because of who ends up owning the task. A scheduled task
    created by an elevated process gets a security descriptor that only
    administrators can change -- the ordinary user is left with Read. The
    dashboard runs as the ordinary user, so every attempt to switch such a
    task off answers "Access is denied", and the row stays on with no
    explanation.

    Found on the test machine, 2026-08-21: an SSH session on Windows had an
    elevated token, the upgrade run inside it re-created all six built-in
    tasks, and from then on the dashboard could not remove any of them. The
    task files were owned by BUILTIN\\Administrators with `anzon` holding
    Read alone.
    """
    if not paths.is_windows():
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:                                        # noqa: BLE001
        return False


def elevation_warning() -> str:
    """What to say before creating tasks from an administrator window."""
    if not running_elevated():
        return ""
    return (
        "You are running as an administrator. Tasks created now can only be "
        "changed by an administrator, so the dashboard -- which runs as you, "
        "not as an administrator -- will not be able to switch them off "
        "afterwards. Nothing has been scheduled. Close this window, open an "
        "ordinary one, and run it again."
    )


def _explain(detail: str) -> str:
    """Turn the Task Scheduler's own words into something actionable."""
    if "access is denied" in (detail or "").lower():
        return (
            "Windows would not let this account change that task. It was "
            "created by an administrator, so only an administrator can "
            "change it. Install the schedule again from an ordinary window "
            "-- not one opened as administrator -- and the dashboard will be "
            "able to switch it on and off."
        )
    return detail


def install(task: ScheduledTask, runner: Path,
            confirmed: bool, allow_elevated: bool = False) -> tuple[bool, str]:
    """Create one scheduled task, and forget what we thought was installed.

    Wrapped rather than clearing the cache at each of the six return points
    inside, because a cache invalidated at five of six places is worse than
    no cache: it is right until the day somebody takes the sixth path.
    """
    try:
        return _install(task, runner, confirmed, allow_elevated)
    finally:
        forget_what_is_installed()


def _install(task: ScheduledTask, runner: Path,
             confirmed: bool, allow_elevated: bool = False) -> tuple[bool, str]:
    """Create one scheduled task. Requires explicit confirmation.

    As with dependency installs, `confirmed` is load-bearing: the caller must
    have shown the user `describe_install()` and had a yes.
    """
    if not confirmed:
        return False, "Not scheduled: nobody confirmed it."

    # Refused, not warned.
    #
    # `elevation_warning()` was printed by one caller -- `schedule-install` --
    # which then created all six tasks anyway and closed by saying "Nothing
    # runs as an administrator", which is false in exactly the case the
    # warning had just described. `repair`, `upgrade` and the dashboard's own
    # install button did not check at all.
    #
    # A task created by an elevated process gets a security descriptor only
    # administrators can change. `schtasks` has no way to set a different one
    # -- the XML schema does not carry a DACL, and the SDDL parameter exists
    # only on the COM RegisterTask call -- so the run level being
    # LeastPrivilege does not help: the OWNERSHIP is what locks the user out.
    #
    # Which means the only reliable fix is not to create it. Refusing here
    # rather than in the CLI covers every path, including the two that never
    # asked and the one somebody adds next.
    if running_elevated() and not allow_elevated:
        return False, elevation_warning()

    # Never schedule something against a file that is not there. See the long
    # note on `runner_script()` -- this exact check is what stops a task
    # installing "successfully" and then failing silently forever.
    if not Path(runner).exists():
        return False, (
            f"Nothing was scheduled: {runner} does not exist, so the task "
            "would have been created and then failed every time it ran."
        )

    if paths.is_windows():
        # The XML goes to a directory of this process's own, not the shared
        # temp folder: a task definition is a thing that will be executed, and
        # a predictable path in a place other accounts can write is how that
        # becomes somebody else's program.
        #
        # UTF-16 because the declaration says so and schtasks believes it.
        import tempfile

        with tempfile.TemporaryDirectory(prefix="aki-task-") as folder:
            written = Path(folder) / f"{task.task_name}.xml"
            try:
                written.write_text(windows_task_xml(task, runner),
                                   encoding="utf-16")
            except OSError as exc:
                return False, f"could not write the task definition: {exc}"

            try:
                result = subprocess.run(windows_command(task, written),
                                        capture_output=True, text=True,
                                        timeout=60, check=False)
            except (OSError, subprocess.SubprocessError) as exc:
                return False, f"could not run schtasks: {exc}"

        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            return False, _explain(detail)[:400]
        return True, f"scheduled '{task.title}'"

    if paths.is_macos():
        from . import atomic
        path = launchd_plist_path(task)
        wanted = launchd_plist(task, runner)

        # Nothing to do, and saying so is the feature.
        #
        # WHY A NO-OP IS WORTH CODE HERE
        # ------------------------------
        # macOS posts a "Background Items Added" notification every time a
        # LaunchAgent is loaded. `_repoint` reinstalls every enabled task, and
        # `repair` and `upgrade` both call it -- so a single update threw
        # one notification per task at the user, over and over, for jobs
        # already registered with the identical definition.
        #
        # The notification cannot be suppressed; it is a macOS security
        # feature and should stay one. What can be removed is the pointless
        # re-registration that triggers it. An install that changes nothing
        # now touches nothing.
        if path.exists() and _launchd_is_loaded(task.label):
            try:
                if path.read_text(encoding="utf-8") == wanted:
                    return True, f"'{task.title}' was already scheduled"
            except OSError:                               # pragma: no cover
                pass

        try:
            atomic.write_text(path, wanted)
        except OSError as exc:
            return False, f"could not write {path}: {exc}"

        # Replacing, not adding: `launchctl load` refuses a label that is
        # already loaded, so re-pointing an existing job would report failure
        # while the *old* definition stayed live. The unload comes after the
        # write on purpose -- the correct plist is on disk before anything is
        # taken down, so the worst case is a job that loads at next login
        # rather than one that has vanished.
        subprocess.run(["launchctl", "unload", str(path)],
                       capture_output=True, text=True, timeout=60,
                       check=False)

        # `launchctl load` is what makes it live. If this fails the plist is
        # still on disk and will load at next login, so report the partial
        # state honestly rather than claiming either success or failure.
        try:
            result = subprocess.run(["launchctl", "load", str(path)],
                                    capture_output=True, text=True,
                                    timeout=60, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, (f"the schedule file was written to {path}, but "
                           f"loading it failed: {exc}. It should start "
                           "working after your next login.")
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            return False, (f"the schedule file was written to {path}, but "
                           f"launchctl refused it: {detail[:200]}")
        return True, f"scheduled '{task.title}'"

    return False, (f"Scheduling is not supported on "
                   f"{paths.platform_label()} yet.")


def remove(task: ScheduledTask) -> tuple[bool, str]:
    """Remove one scheduled task, and forget what we thought was installed."""
    try:
        return _remove(task)
    finally:
        forget_what_is_installed()


def _remove(task: ScheduledTask) -> tuple[bool, str]:
    """Remove one scheduled task."""
    if paths.is_windows():
        try:
            result = subprocess.run(windows_delete_command(task),
                                    capture_output=True, text=True,
                                    timeout=60, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"could not run schtasks: {exc}"
        detail = (result.stderr or result.stdout).strip()
        if result.returncode != 0:
            return False, _explain(detail)[:400]
        return True, detail

    if paths.is_macos():
        path = launchd_plist_path(task)
        subprocess.run(["launchctl", "unload", str(path)],
                       capture_output=True, text=True, timeout=60, check=False)
        if path.exists():
            path.unlink()
        return True, f"removed '{task.title}'"

    return False, f"Not supported on {paths.platform_label()}."


# ---------------------------------------------------------------------------
# The user's own tasks
#
# The four defaults ship with the package. Everything else a person creates is
# theirs, and lives in their own folder -- so a package update cannot delete
# their work, and they can back it up without backing up software.
# ---------------------------------------------------------------------------

def user_tasks_file() -> Path:
    return paths.app_dir() / "schedule.json"


def _task_to_dict(task: ScheduledTask) -> dict:
    return {
        "key": task.key, "title": task.title, "why": task.why,
        "prompt": task.prompt, "enabled": task.enabled,
        "announce": task.announce,
        # Written, never read back (see `_task_from_dict`). `work` is derived
        # from the trigger now, so storing it would be storing a second copy
        # of a fact -- but a person opening schedule.json should still be able
        # to see which tab a task is on without working it out.
        "work": task.work,
        "triggers": [one.to_dict() for one in task.triggers],
    }


def _task_from_dict(data: dict) -> ScheduledTask:
    """Read one task back, in either shape.

    Files written before 2026-08-21 carry the trigger flat on the task --
    `trigger`, `hour`, `minute`, `weekdays`, `every_minutes`, `watch_path`.
    Those become a single trigger. This is the whole migration, and it has to
    keep working: getting it wrong does not error, it silently empties
    somebody's schedule.
    """
    written = data.get("triggers")
    if written:
        triggers = tuple(Trigger.from_dict(one) for one in written)
    else:
        triggers = (Trigger(
            kind=str(data.get("trigger", "time")),
            hour=int(data.get("hour", 9)),
            minute=int(data.get("minute", 0)),
            weekdays=tuple(data.get("weekdays") or ()),
            every_minutes=int(data.get("every_minutes", 60)),
            watch_path=str(data.get("watch_path", "")),
        ),)

    return ScheduledTask(
        key=str(data.get("key", "")),
        title=str(data.get("title", "")),
        why=str(data.get("why", "")),
        prompt=str(data.get("prompt", "")),
        enabled=bool(data.get("enabled", True)),
        # `work` is deliberately NOT read back. It is derived from the
        # trigger, so a stored value can only ever be a stale second opinion
        # -- and every file written before today has one, from when the two
        # were chosen separately. Ignoring it is the migration: a task saved
        # as a "heartbeat" running at 08:05 simply appears where it runs.
        triggers=triggers,
        built_in=False,
        announce=bool(data.get("announce", True)),
    )


def announce_file() -> Path:
    return paths.state_dir() / "task-announce.json"


def announce_overrides() -> dict:
    """Which tasks the user has changed their mind about.

    A separate store because the shipped tasks are a constant in this file --
    there is nowhere in `DEFAULT_TASKS` to record a decision somebody made
    about one. Only differences are kept, so a task's default can be improved
    in a later release and will reach everybody who never had an opinion.
    """
    from . import atomic

    stored = atomic.read_json(announce_file(), default=None)
    if not isinstance(stored, dict):
        return {}
    return {str(key): bool(value) for key, value in stored.items()}


def announces(key: str) -> bool:
    """Should this task's result reach the user where they actually are?"""
    override = announce_overrides().get(key)
    if override is not None:
        return override
    task = get_task(key)
    return task.announce if task else True


def set_announce(key: str, on: bool) -> dict:
    from . import atomic

    current = announce_overrides()
    current[key] = bool(on)
    atomic.write_json(announce_file(), current)
    return current


def enabled_file() -> Path:
    return paths.state_dir() / "task-enabled.json"


def enabled_overrides() -> dict:
    """Which shipped tasks the user has switched on, or off.

    THE BUG THIS EXISTS FOR (2026-09-05)
    ------------------------------------
    The three Event examples ship `enabled=False` so that installing the
    package does not start making model calls about your event log. The
    Schedule page's on/off button posts to `/schedule/install`, which
    registers the task with the operating system whatever `enabled` says; the
    row then reads "on"; and `tasks.run_one` returns at the top with
    `ok=True, "switched off, nothing to do"`. So the switch went on, the task
    ran every ten minutes, did nothing, and recorded a clean run each time.
    Nothing on any screen or in any log said otherwise.

    `enabled` lives in `DEFAULT_TASKS`, a constant in this file, so there was
    nowhere to record the user's decision -- the same problem `announce` had,
    solved the same way. Only differences are stored, so a later release can
    change a shipped default and reach everybody who never had an opinion.
    """
    from . import atomic

    stored = atomic.read_json(enabled_file(), default=None)
    if not isinstance(stored, dict):
        return {}
    return {str(key): bool(value) for key, value in stored.items()}


def set_enabled(key: str, on: bool) -> dict:
    from . import atomic

    current = enabled_overrides()
    current[key] = bool(on)
    atomic.write_json(enabled_file(), current)
    return current


def forget_enabled(key: str) -> dict:
    """Drop the user's decision, so the shipped default applies again.

    Switching a task off in the scheduler is not the same as declaring it
    disabled: a user task removed from the scheduler must still run when
    somebody presses Run now, while an Event example must go back to doing
    nothing. Storing `False` for both would have got the first of those
    wrong, quietly, in exactly the way this audit has been about.
    """
    from . import atomic

    current = enabled_overrides()
    if current.pop(key, None) is None:
        return current
    atomic.write_json(enabled_file(), current)
    return current


def read_user_tasks() -> list[ScheduledTask]:
    from . import atomic

    # `read_json_for_update`, not `read_json`: every caller of this reads the
    # queue, changes it, and writes it back. A plain read cannot tell "the
    # file is not there" from "the file is there and would not open", and
    # answering the second with an empty list is how the whole queue used to
    # be erased by the next write.
    raw = atomic.read_json_for_update(user_tasks_file(), default=[]) or []
    tasks: list[ScheduledTask] = []
    for item in raw:
        try:
            tasks.append(_task_from_dict(item))
        except (TypeError, ValueError):
            continue      # one malformed entry must not lose the rest
    return tasks


def save_user_task(task: ScheduledTask) -> tuple[ScheduledTask, list[str]]:
    """Add or replace one of the user's tasks. Returns it and its problems.

    Saves even when there are problems, and reports them. A half-written task
    is a normal state; refusing to save somebody's work is not helpful.
    """
    from . import atomic
    import re

    if not task.key:
        # `\w` with UNICODE, not `[a-z0-9]`. This was the fifth instance of
        # the slug bug -- `memory`, `specialists`, `skills_store`, `knowledge`
        # and here -- and the only one written inline rather than as a
        # `_safe_key`, which is exactly why the package-wide test written for
        # the other four did not reach it. Two tasks titled in Chinese both
        # slugged to "task", and the second silently replaced the first.
        slug = re.sub(r"[^\w]+", "-", task.title.lower(),
                      flags=re.UNICODE).strip("-_")
        task.key = (slug or "task")[:40]

        # And a NEW task must not land on an existing one's key. The line
        # below rebuilds the list as "everything except this key, plus this
        # task", which is right when editing and silently destructive when
        # adding: two tasks called "Second one" left one task, carrying the
        # second's settings, under a note that said "Added". Only reached
        # when the caller supplied no key, i.e. when adding. 2026-09-05.
        taken = {one.key for one in read_user_tasks()}
        if task.key in taken:
            stem, number = task.key, 2
            while task.key in taken:
                task.key = f"{stem}-{number}"[:40]
                number += 1

    # Never let a user's task take a shipped task's key.
    #
    # `all_tasks()` is the six plus the user's, and `get_task` answers with
    # the first match -- so a user task keyed `morning-summary` would be
    # created, listed, and then invisible to every switch on the page, which
    # would go on operating the built-in instead. Copying a built-in is now
    # one button, so this stopped being hypothetical.
    reserved = {one.key for one in DEFAULT_TASKS}
    if task.key in reserved:
        stem = task.key
        task.key = f"{stem}-mine"
        taken = {one.key for one in read_user_tasks()} | reserved
        number = 2
        while task.key in taken:
            task.key = f"{stem}-mine-{number}"
            number += 1

    existing = [other for other in read_user_tasks() if other.key != task.key]
    existing.append(task)
    atomic.write_json(user_tasks_file(),
                      [_task_to_dict(entry) for entry in existing])
    return task, task.problems()


def delete_user_task(key: str) -> tuple[bool, str]:
    """Delete a task the user made — from our list AND from the scheduler.

    Returns whether the task was ours to delete, and what to tell them about
    the scheduler half.

    **Why the scheduler half matters.** This used to drop the task from the
    package's own list and stop. Windows kept the entry and kept firing it,
    every day, at a task key that no longer resolved — and because the task
    was gone from our list, the Schedule page no longer offered any way to
    remove it. The only remaining cure was Task Scheduler by hand, which is
    the thing this package exists so nobody has to open.

    The order is deliberate: uninstall from the scheduler first. If that
    fails, the task stays in our list, still listed, still removable. Doing it
    the other way round is what produced the orphan.
    """
    from . import atomic

    tasks = read_user_tasks()
    if all(task.key != key for task in tasks):
        return False, ""

    note = ""
    try:
        # `remove` takes the task, not its key. Passing the key raised
        # `AttributeError: 'str' object has no attribute 'task_name'` inside
        # `_remove` -- before any `schtasks`/`launchctl` call -- and the broad
        # `except` below turned that into a note. So the row vanished from the
        # list while the operating system kept firing the task, and every
        # firing then logged "no longer exists": exactly the orphan the
        # docstring above says the ordering was chosen to prevent. Fixed
        # 2026-09-05.
        #
        # And `if removed:` tested a `(ok, message)` tuple, which is truthy
        # even for `(False, "Access is denied")`, so a refusal by the
        # scheduler read as "Also removed from the scheduler."
        doomed = next(task for task in tasks if task.key == key)
        removed, why = remove(doomed)
        note = ("Also removed from the scheduler." if removed else
                f"Removed from the list, but the scheduler kept its own "
                f"entry: {why}")
    except CouldNotAsk as exc:
        # We do not know whether it is installed, so we do not know whether an
        # orphan is being left. Say that, rather than reporting a clean
        # removal we cannot vouch for.
        note = (f"Removed from the list. The scheduler could not be reached "
                f"({exc}), so if it was installed it may still be there.")
    except Exception as exc:                 # noqa: BLE001
        note = (f"Removed from the list, but the scheduler entry could not be "
                f"deleted: {exc}. Run `aki schedule-status` to check.")

    remaining = [task for task in tasks if task.key != key]
    atomic.write_json(user_tasks_file(),
                      [_task_to_dict(entry) for entry in remaining])

    try:
        from . import task_runs

        task_runs.forget(key)
    except Exception:                        # noqa: BLE001
        pass

    return True, note


def all_tasks() -> list[ScheduledTask]:
    """The ones that ship, plus everything the user has added.

    The user's `enabled` decisions are applied HERE rather than at each of the
    six places that read `task.enabled` -- `tasks.run_one`, `doctor`, two
    spots in `cli`, the plist writer, and the page. Applying it once is what
    keeps them agreeing with each other; the last time this comparison was
    written out by hand in several places, four of the five copies were wrong
    (see `is_installed`). 2026-09-05.
    """
    import dataclasses

    overrides = enabled_overrides()
    tasks = list(DEFAULT_TASKS) + read_user_tasks()
    if not overrides:
        return tasks
    return [dataclasses.replace(task, enabled=overrides[task.key])
            if task.key in overrides else task
            for task in tasks]


def get_task(key: str) -> ScheduledTask | None:
    for task in all_tasks():
        if task.key == key:
            return task
    return None


def is_installed(task: "ScheduledTask",
                 installed: "list[str] | set[str] | None" = None) -> bool:
    """Does the operating system know about this task?

    WHY THIS IS A FUNCTION AND NOT AN `IN` (2026-08-20)
    ---------------------------------------------------
    `installed_names()` returns what the scheduler calls a task --
    `aki-agent-morning-summary`, sometimes with a folder in front. A task's
    `key` is `morning-summary`. Comparing the two never matches.

    That comparison was written out by hand in three places. The dashboard got
    it right (`task_name in installed or label in installed`); `cli._repoint`
    and `doctor.check_schedule` both got it wrong, and both had been wrong
    from the day they were written:

      * every upgrade reported "Re-pointed 0 scheduled task(s)" -- so the
        tasks were never actually re-pointed, and nobody noticed because the
        engine lives at a fixed path and did not need it. On an install where
        the path does change, every scheduled job would have quietly stopped.
      * `doctor` reported "6 installed, 6 not" in the same breath, which a
        user's own assistant called "that confused line". It was right.

    Three hand-written copies of one comparison is three chances to get it
    wrong, and two of them were taken. So: one function, and the callers ask
    it.
    """
    known = set(installed if installed is not None else installed_names())
    return (task.task_name in known
            or getattr(task, "label", task.task_name) in known
            or task.key in known)


# Asking the scheduler is expensive, and pages ask repeatedly.
#
# `schtasks /Query` walks every job on the machine: 1.32 seconds on the maintainer's,
# which has 403 of them. The schedule page called it once per task and took
# 9.4 seconds to answer a button press; four other pages call it once each
# and paid 1.3 seconds for a number.
#
# So: a very short cache, cleared the moment anything is installed or
# removed. Short enough that a stale answer cannot outlive a page render,
# and explicitly invalidated so that the one case where staleness would
# actually mislead -- looking straight after acting -- cannot happen.
_ASKED: tuple[float, list[str]] | None = None
_ASKED_FOR_SECONDS = 4.0


def forget_what_is_installed() -> None:
    """Drop the cache. Called whenever this package changes the scheduler."""
    global _ASKED
    _ASKED = None


def installed_names_or_empty() -> list[str]:
    """For places that only display a count and cannot usefully fail.

    Deliberately separate from `installed_names()` so that the callers who
    must know the difference between "none" and "could not ask" still get an
    exception, and only the ones that genuinely just draw a number opt out
    of knowing.
    """
    try:
        return installed_names()
    except CouldNotAsk:
        return []


def installed_names() -> list[str]:
    """Which of our tasks the operating system currently knows about.

    Only ever reports tasks carrying our prefix. A scheduler listing is full
    of other people's work and touching any of it would be a serious bug.

    Cached for a few seconds -- see `_ASKED_FOR_SECONDS`. A raise is never
    cached: a machine that could not be asked has to be asked again.
    """
    global _ASKED
    if _ASKED is not None and time.monotonic() - _ASKED[0] < _ASKED_FOR_SECONDS:
        return list(_ASKED[1])
    found = _ask_the_scheduler()
    _ASKED = (time.monotonic(), list(found))
    return found


def _ask_the_scheduler() -> list[str]:
    if paths.is_windows():
        # CSV, not LIST, and the reason is not tidiness (2026-08-23).
        #
        # This used to read `/FO LIST` and look for lines starting with
        # "taskname:". `schtasks` translates its field labels: a Traditional
        # Chinese Windows prints and this returned [] for ever.
        #
        # Which would be a small bug if anything treated [] as suspicious.
        # Nothing did. `doctor` reported "nothing installed"; `cli._repoint`
        # skipped every task on upgrade, so they all kept pointing at the
        # deleted old folder and every piece of automation stopped, silently;
        # `uninstall` left them all behind. The maintainer teaches Hong Kong
        # architects, so the affected machine is the normal case, not an edge
        # one.
        #
        # `/FO CSV /NH` puts the task name in the first column whatever the
        # display language is.
        try:
            result = subprocess.run(
                ["schtasks", "/Query", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=60, check=False)
        except (OSError, subprocess.SubprocessError) as problem:
            raise CouldNotAsk(
                f"the scheduler could not be queried: {problem}") from problem
        if result.returncode != 0:
            raise CouldNotAsk(
                "the scheduler refused the query: "
                + (result.stderr or result.stdout or "no reason given").strip())

        names = set()
        for row in csv.reader(io.StringIO(result.stdout)):
            if not row:
                continue
            name = row[0].strip().lstrip("\\")
            if TASK_PREFIX in name:
                names.add(name)
        return sorted(names)

    if paths.is_macos():
        directory = paths.home() / "Library" / "LaunchAgents"
        if not directory.exists():
            return []
        return sorted(path.stem for path in directory.glob("com.aki-agent.*.plist"))

    return []
