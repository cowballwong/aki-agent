"""Reflection: a quiet pass over what has happened, looking for what is true.

WHAT THIS IS, AND WHERE IT COMES FROM
-------------------------------------

That repository is the Stanford *Generative Agents* research code — the one
with twenty-five agents living in Smallville. It is not a library: no PyPI
package, no `setup.py`, and running it means standing up a Django frontend on
:8000, a `reverie.py` simulation backend, and supplying an OpenAI key. Its own
README warns that a run is costly. So it cannot be installed as a dependency
here, and pretending otherwise would be the kind of claim this package exists
not to make.

What transfers is the idea it is known for. Between actions, its agents stop
and **reflect**: they read back over their recent memory stream and ask what
they can now conclude, then write those conclusions back as memories of a
higher order. Later behaviour reads the conclusions rather than re-deriving
them from a thousand raw observations.

That is what this module does, and the page says so in those words rather
than claiming the repository is inside.

WHY IT IS A SCHEDULED TASK AND NOT A SCHEDULER OF ITS OWN
---------------------------------------------------------
The maintainer asked to be able to set what time it dreams. There is already a thing in
this package that runs work at a time you set, survives a reboot, obeys quiet
hours, records what it did and can be switched off in one press — and building
a second one beside it would mean two answers to "what is scheduled", two
places a run can silently stop, and two things to fix.

So Dreaming writes an ordinary task into the schedule, keyed `dreaming`, and
the tab is a friendly face on it. Turning it on installs the task; changing
the time rewrites the trigger; turning it off removes it. It also shows up on
the Schedule page under Loops, which is correct and not a leak: it *is* a
loop that runs at a time you chose.

IT SHIPS OFF
------------
A reflection is a model call every night, for ever. The maintainer's own rule about
metered things is that they are chosen, never inherited — the same call made
for `fastembed` on the Knowledge page and for the three Event examples in
`schedule.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import schedule

# The key the scheduled task is kept under. One name, in one place, because
# every function here finds the task by it.
KEY = "dreaming"

DEFAULT_HOUR = 3
DEFAULT_MINUTE = 0


# What the assistant is asked to do while nobody is watching.
#
# WRITTEN TO A BUDGET, like the evening wrap-up before it. This package tests
# that its prompts stay short (`test_the_prompt_is_still_inside_its_budget`),
# and the reason is the same one that applies to everything that runs nightly
# for ever: a prompt that rambles costs that rambling every single night.
#
# The instruction to say nothing rather than invent is the important line.
# A reflection pass with nothing to reflect on will happily manufacture an
# insight, and a memory full of manufactured insights is worse than an empty
# one -- it is confidently wrong, and it is read back later as though it were
# observed.
PROMPT = (
    "Read back over the last few days of my notes.\n"
    "Name at most THREE things you can now conclude that no single day "
    "showed -- a pattern, a preference of mine, something that keeps "
    "returning.\n"
    "One line each, only what the notes support. Nothing worth concluding: "
    "say 'Nothing new.' and stop. Never invent one to fill the space.\n"
    "Remember each one, so it is there next time."
)

# "lesson" was the obvious word here and is on the engine's forbidden list --
# profession vocabulary belongs in the user's config, never in the code, so
# that this package reads the same to an architect and to a piano teacher.
# Caught by `test_engine_source_contains_no_profession_vocabulary`.
WHY = ("looks back over several days at once and writes down what it can "
       "conclude, so the same thing is not worked out twice")


@dataclass(frozen=True)
class State:
    """What the tab needs to draw itself."""

    on: bool = False
    hour: int = DEFAULT_HOUR
    minute: int = DEFAULT_MINUTE
    # True when the task exists but the scheduler does not have it -- saved
    # and inert, which is the failure this package has hit three times and
    # which must never be drawn as "on".
    saved_but_not_running: bool = False

    def at(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"


def task_for(hour: int, minute: int) -> schedule.ScheduledTask:
    """The task this feature is, at a given time."""
    return schedule.ScheduledTask(
        key=KEY,
        title="Dreaming",
        why=WHY,
        prompt=PROMPT,
        triggers=(schedule.Trigger(kind="time", hour=hour, minute=minute),),
        # It has something to tell you, but not at three in the morning. The
        # conclusions are written into memory; the notification gate on
        # Notifications decides whether you also hear about it, and the
        # default here is that you do not.
        announce=False,
    )


def _saved() -> schedule.ScheduledTask | None:
    for one in schedule.read_user_tasks():
        if one.key == KEY:
            return one
    return None


def state() -> State:
    """Read the truth off the schedule, not off a settings file.

    There is no separate record of whether dreaming is on. If there were, it
    could disagree with the scheduler -- and the page would then be reporting
    a preference while the machine did something else. The same reasoning
    that made `ScheduledTask.work` a derived property this morning.
    """
    saved = _saved()
    if saved is None:
        return State()

    trigger = saved.triggers[0] if saved.triggers else schedule.Trigger()
    # `installed_names_or_empty`, not the raising kind. This is called on
    # every render of the Memory page -- all five tabs -- and a bare
    # `is_installed(saved)` asks the scheduler directly, so once a Dreaming
    # task existed, a scheduler that could not be reached turned the whole
    # page into a 500. Every other page already opts out this way. The cost
    # of being wrong here is a switch drawn as "off" for one render, which is
    # a great deal better than no page at all. Fixed 2026-09-05.
    running = schedule.is_installed(saved, schedule.installed_names_or_empty())

    return State(
        on=running,
        hour=trigger.hour,
        minute=trigger.minute,
        saved_but_not_running=not running,
    )


def turn_on(hour: int, minute: int) -> tuple[bool, str]:
    """Write the task and hand it to the scheduler.

    Both halves, always. Writing the file and stopping is exactly the shape
    of bug this package's own notes call out three times -- something that is
    saved, listed, and never runs.
    """
    hour = max(0, min(23, int(hour)))
    minute = max(0, min(59, int(minute)))

    saved, problems = schedule.save_user_task(task_for(hour, minute))
    if problems:
        return False, " ".join(problems)

    runner = schedule.runner_script()
    if not runner.exists():
        return False, ("Saved, but the file the scheduler calls is missing, "
                       "so nothing would have run. Try Repair on Health.")

    ok, said = schedule.install(saved, runner, confirmed=True)
    if not ok:
        return False, f"Saved, but the scheduler refused it: {said}"

    return True, f"Dreaming at {hour:02d}:{minute:02d}."


def turn_off() -> tuple[bool, str]:
    """Take it out of the scheduler and out of the file.

    Removed rather than left switched off, because a task nobody wants is
    clutter on the Schedule page -- and turning it back on is one press that
    writes it again from the same function.
    """
    saved = _saved()
    if saved is None:
        return True, "It was not on."

    if schedule.is_installed(saved):
        ok, said = schedule.remove(saved)
        if not ok:
            return False, (f"It is still in the scheduler: {said}. Nothing "
                           "was deleted, so it can be tried again.")

    schedule.delete_user_task(KEY)
    return True, "Dreaming is off. Nothing you have already remembered is lost."


def set_time(hour: int, minute: int) -> tuple[bool, str]:
    """Move it. Only meaningful while it is on."""
    if _saved() is None:
        return False, "Turn dreaming on first, and it will run at that time."
    return turn_on(hour, minute)
