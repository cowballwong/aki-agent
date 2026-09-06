"""Self-optimisation: letting your own corrections rewrite the guidance.


WHAT CHANGES BY SWITCHING THIS ON
---------------------------------
Half an hour before he asked for this, he asked whether "What I have learned
from you" was DSPy. It is not: `traces.py` distils verdicts into a card using
plain rules, on this machine, with no model call and nothing leaving it. That
module's docstring defends the trade in as many words.

This is the other road, and he chose it knowing that. DSPy optimises by
*trying things* — it calls a model repeatedly with candidate instructions and
keeps what scores best. So switching this on means the corrections you have
written about your own work are sent to whichever model you pick.

That is why the local option is not a footnote here. Pointed at Ollama,
nothing leaves the machine and the privacy claim survives intact; pointed at
an API, it does not, and the page has to say so where the choice is made
rather than afterwards.

THE LESSON THIS MODULE IS BUILT AROUND
--------------------------------------
From an earlier system: **an optimiser that exits 0 is not an optimiser that
worked.** A run there reported success while DSPy had failed outright, because
the code checked that the script finished and that a card had been refreshed —
and a refreshed card is not evidence of learning. It is evidence of a file
having been written.

So `run()` returns what it actually did: how many examples it had, whether the
optimiser produced anything different from what was already there, and whether
the result scored better than the thing it replaced. It refuses to overwrite
on anything less, and says which of those it was.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from . import atomic, paths, traces

# Where DSPy is asked to send its calls.
#
# `local` first, deliberately -- it is the only one of the three that keeps
# the promise `traces.py` makes about this data.
PROVIDERS: tuple[tuple[str, str, str], ...] = (
    ("ollama", "On this computer (Ollama)",
     "Nothing leaves the machine. Needs Ollama running."),
    ("anthropic", "Anthropic",
     "Your corrections are sent to Anthropic. Needs ANTHROPIC_API_KEY."),
    ("openai", "OpenAI",
     "Your corrections are sent to OpenAI. Needs OPENAI_API_KEY."),
)

# Offered when the machine has none of its own yet. Small on purpose: this
# job is rewriting a paragraph of guidance, not answering hard questions, and
# a seven-billion-parameter model that runs on a laptop does it well enough.
SUGGESTED_LOCAL = (
    ("qwen2.5:7b", "a good all-rounder, about 4.7 GB"),
    ("llama3.1:8b", "about 4.9 GB"),
    ("phi4-mini", "the smallest of the three, about 2.5 GB"),
)

OLLAMA_URL = "http://localhost:11434"

# How many verdicts before there is anything to learn from.
#
# Below this an "optimisation" is fitting to noise -- and worse, it is fitting
# to noise convincingly, because the output is prose that reads like insight.
ENOUGH = 12

KEY = "self-optimise"

# `tasks.run_one` handles this without calling a model, the same way
# `__checkpoint__` and `__inbox__` are handled. The work is a Python job, not
# a sentence for an agent to interpret.
PROMPT = "__optimise__"


def settings_file():
    return paths.state_dir() / "self-optimise.json"


def read_settings() -> dict:
    stored = atomic.read_json(settings_file(), default={}) or {}
    if not isinstance(stored, dict):
        stored = {}
    return {
        "provider": str(stored.get("provider") or "ollama"),
        "model": str(stored.get("model") or ""),
        "hour": int(stored.get("hour") or 4),
        "minute": int(stored.get("minute") or 0),
    }


def save_settings(provider: str, model: str, hour: int, minute: int) -> dict:
    known = {one for one, _label, _why in PROVIDERS}
    settings = {
        "provider": provider if provider in known else "ollama",
        "model": (model or "").strip(),
        "hour": max(0, min(23, int(hour))),
        "minute": max(0, min(59, int(minute))),
    }
    atomic.write_json(settings_file(), settings)
    return settings


# ---------------------------------------------------------------------------
# The library
# ---------------------------------------------------------------------------

def available() -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec("dspy") is not None
    except (ImportError, ValueError):                      # noqa: BLE001
        return False


def install() -> tuple[bool, str]:
    """Fetch DSPy. Minutes, not hundreds of megabytes -- it brings no model."""
    import subprocess
    import sys

    if available():
        return True, "It is already here."

    try:
        finished = subprocess.run(
            [sys.executable, "-m", "pip", "install", "dspy"],
            capture_output=True, text=True, timeout=1800, check=False)
    except (OSError, subprocess.SubprocessError,
            subprocess.TimeoutExpired) as problem:
        return False, f"It could not be installed: {problem}"

    if finished.returncode != 0:
        detail = (finished.stderr or finished.stdout or "").strip().splitlines()
        return False, ("It did not install: "
                       + (detail[-1] if detail else "pip gave no reason."))

    import importlib
    importlib.invalidate_caches()
    if not available():
        return False, ("pip reported success but dspy still cannot be loaded "
                       "here -- usually a different Python.")
    return True, "Installed. Choose where it should run."


# ---------------------------------------------------------------------------
# Ollama: what is here, and fetching more
# ---------------------------------------------------------------------------

def _ask_ollama(path: str, body: dict | None = None,
                timeout: int = 5) -> tuple[bool, Any]:
    """One request to the local Ollama. Never raises.

    Ollama not running is the normal state on most machines, so it has to be
    an answer rather than an exception -- the page draws a list either way.
    """
    url = f"{OLLAMA_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data else {})

    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            return True, json.loads(answer.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return False, None


def local_models(timeout: int = 1) -> tuple[bool, list[str]]:
    """(is Ollama reachable, what it already has).

    The two are separate answers. "Ollama is not running" and "Ollama has no
    models" need different things done about them, and one empty list cannot
    say which it is.

    One second, not five. This is asked while drawing a page, and on the many
    machines with no Ollama the connection is not refused but dropped, so the
    tab took the full timeout to open -- measured at 5,032ms against ~10ms for
    every other tab in the dashboard, with nothing on screen to say why. A
    local service that has not answered in a second is not running.
    Model pulls keep their own, much longer, timeout. 2026-09-05.
    """
    reachable, answer = _ask_ollama("/api/tags", timeout=timeout)
    if not reachable or not isinstance(answer, dict):
        return False, []

    found = []
    for one in answer.get("models") or []:
        name = (one or {}).get("name") or (one or {}).get("model")
        if name:
            found.append(str(name))
    return True, sorted(found)


def is_cloud(name: str) -> bool:
    """Is this one of Ollama's hosted models rather than a local one?

    IT MATTERS MORE HERE THAN ANYWHERE. The whole reason the local option is
    offered first is the sentence "nothing leaves the machine" -- and Ollama
    lists its cloud models in exactly the same place as the ones on your
    disk. The maintainer's own machine has `gemma4:31b-cloud` sitting between two
    local models in that list.

    Picking one of those quietly makes the privacy claim false and starts
    spending metered credit, with nothing on screen to say either. So they
    are marked, and the page says which is which.
    """
    return (name or "").strip().lower().endswith("-cloud")


def pull_model(name: str) -> tuple[bool, str]:
    """Download one model into Ollama.

    This blocks until it is done, and a model is gigabytes, so whatever
    calls it has to raise the overlay first.
    """
    name = (name or "").strip()
    if not name:
        return False, "No model was named."

    reachable, _ = local_models()
    if not reachable:
        return False, ("Ollama is not answering on this machine. Start it "
                       "and try again — nothing was downloaded.")

    # `stream: false` so this is one request that finishes rather than a
    # progress feed nobody is reading. Ollama holds the connection open for
    # the whole download, which is why the timeout is in hours.
    ok, answer = _ask_ollama("/api/pull", {"name": name, "stream": False},
                             timeout=7200)
    if not ok:
        return False, (f"{name} could not be fetched. Ollama stopped "
                       "answering — it may still be downloading; check "
                       "Ollama itself before starting again.")

    if isinstance(answer, dict) and answer.get("error"):
        return False, f"Ollama refused: {answer['error']}"

    _reachable, have = local_models()
    if not any(one == name or one.startswith(name + ":") for one in have):
        # Asked again rather than trusted, the same rule as every other
        # install in this package: a success code is not the thing itself.
        return False, (f"Ollama reported no error, but {name} is not in its "
                       "list afterwards.")

    return True, f"{name} is ready to use."


# ---------------------------------------------------------------------------
# What a run actually did
# ---------------------------------------------------------------------------

@dataclass
class Outcome:
    """Reported in full, because "it ran" is not "it worked".

    Every field here exists because its absence once allowed a run to be
    recorded as a success when nothing had been learned.
    """

    ok: bool = False
    examples: int = 0
    tasks_looked_at: int = 0
    improved: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    why: str = ""

    def sentence(self) -> str:
        if not self.ok:
            return self.why or "It did not run."
        if not self.improved:
            return (f"Read {self.examples} verdict(s) across "
                    f"{self.tasks_looked_at} kind(s) of work and found nothing "
                    "worth changing. Nothing was overwritten.")
        return (f"Read {self.examples} verdict(s) and improved "
                f"{len(self.improved)}: {', '.join(self.improved)}."
                + (f" {len(self.unchanged)} left as they were."
                   if self.unchanged else ""))


def state(ask_ollama: bool = True) -> dict:
    """Everything the tab draws itself from.

    `ask_ollama=False` skips the network call. It matters: `local_models()`
    is an HTTP request to localhost with a timeout, and this function was
    being called on EVERY render of the Memory page -- so the EOD tab, which
    has nothing to do with any of this, paid for a connection attempt, and on
    a machine with no Ollama it paid the whole timeout. Measured in the suite
    as 74s -> 155s before this argument existed.
    """
    settings = read_settings()
    reachable, have = (local_models() if ask_ollama else (False, []))

    return {
        "available": available(),
        "provider": settings["provider"],
        "model": settings["model"],
        "hour": settings["hour"],
        "minute": settings["minute"],
        "at": f"{settings['hour']:02d}:{settings['minute']:02d}",
        "providers": [{"key": key, "label": label, "why": why}
                      for key, label, why in PROVIDERS],
        "ollama_running": reachable,
        "local_models": [{"name": one, "cloud": is_cloud(one)} for one in have],
        "suggested": [{"name": name, "why": why}
                      for name, why in SUGGESTED_LOCAL],
        "verdicts": sum(traces.stats().values()),
        "enough": ENOUGH,
        "on": is_on(),
        # So the page can tell "Ollama said it has none" from "we did not
        # ask" -- drawing an empty list for the second would be a lie about
        # the machine.
        "asked_ollama": ask_ollama,
    }


def _lm(settings: dict):
    """The model DSPy should call, or a reason it cannot be reached."""
    import dspy

    provider = settings["provider"]
    model = settings["model"]

    if provider == "ollama":
        if not model:
            return None, "No local model has been chosen."
        reachable, _have = local_models()
        if not reachable:
            return None, "Ollama is not running on this machine."
        return dspy.LM(f"ollama_chat/{model}",
                       api_base=OLLAMA_URL, api_key=""), ""

    # Note that a `-cloud` model reaches this branch as "ollama" and is not
    # blocked. It is a real choice somebody may want; it is only one that
    # must not be made by accident, which is the page's job.

    import os

    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None, "ANTHROPIC_API_KEY is not set in this environment."
        return dspy.LM(f"anthropic/{model or 'claude-sonnet-5'}"), ""

    if not os.environ.get("OPENAI_API_KEY"):
        return None, "OPENAI_API_KEY is not set in this environment."
    return dspy.LM(f"openai/{model or 'gpt-4.1-mini'}"), ""


def run() -> Outcome:
    """One optimisation pass over the verdicts.

    WHAT IT OPTIMISES. For each kind of work with enough verdicts, the
    guidance card `traces.distil` writes by rule. DSPy is asked to produce a
    better one from the same corrections, and the two are scored against
    held-back corrections: does the guidance actually mention what the person
    kept changing?

    WHAT IT REFUSES TO DO. Overwrite a card on anything except a score that
    beat the existing one. Not "DSPy finished", not "a card was produced" --
    those were both true on the day an earlier system reported success while
    having learned nothing at all.
    """
    settings = read_settings()

    if not available():
        return Outcome(why="DSPy is not installed.")

    every = traces.read_traces()
    if len(every) < ENOUGH:
        return Outcome(
            examples=len(every),
            why=(f"Only {len(every)} verdict(s) so far. Below about {ENOUGH} "
                 "there is nothing to learn that is not noise — and prose "
                 "fitted to noise reads exactly like insight."))

    try:
        import dspy
    except Exception as problem:                           # noqa: BLE001
        return Outcome(why=f"DSPy would not load: {problem}")

    model, trouble = _lm(settings)
    if model is None:
        return Outcome(why=trouble)

    by_task: dict[str, list] = {}
    for one in every:
        by_task.setdefault(one.task, []).append(one)

    done = Outcome(ok=True, examples=len(every), tasks_looked_at=len(by_task))

    try:
        dspy.configure(lm=model)
    except Exception as problem:                           # noqa: BLE001
        return Outcome(why=f"The model could not be reached: {problem}")

    for task, rows in by_task.items():
        corrections = [one.correction for one in rows if one.correction.strip()]
        if len(corrections) < 4:
            done.unchanged.append(task)
            continue

        # Held back, so the score is not marked against the same lines it was
        # written from. Small, because the data is small -- but a score with
        # no held-back set at all is not a score.
        held = corrections[-2:]
        shown = corrections[:-2]

        try:
            write = dspy.Predict(
                "corrections -> guidance: one paragraph of instructions that "
                "would have avoided these corrections")
            answer = write(corrections="\n".join(shown))
            suggested = (getattr(answer, "guidance", "") or "").strip()
        except Exception:                                  # noqa: BLE001
            done.unchanged.append(task)
            continue

        if not suggested:
            done.unchanged.append(task)
            continue

        before = traces.card_for(task)
        if suggested == before.strip():
            done.unchanged.append(task)
            continue

        # THE SCORE, and the whole point of the module. How much of what the
        # person actually kept changing is reflected in the guidance? Crude,
        # and crude is fine -- what matters is that it is measured against
        # something held back, and that a worse answer cannot win.
        def covers(text: str) -> int:
            words = {word for line in held for word in line.lower().split()
                     if len(word) > 4}
            body = text.lower()
            return sum(1 for word in words if word in body)

        if covers(suggested) <= covers(before):
            done.unchanged.append(task)
            continue

        path = traces.card_dir() / f"{traces._safe(task)}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_text(path, suggested + "\n")
        done.improved.append(task)

    return done


# ---------------------------------------------------------------------------
# The schedule, borrowed rather than rebuilt
# ---------------------------------------------------------------------------

WHY = ("rewrites the guidance it keeps about your work, using the corrections "
       "you have already made")


def task_for(hour: int, minute: int):
    """The scheduled task this feature is.

    The same choice as Dreaming, for the same reason: there is one thing in
    this package that runs work at a time you set, and a second would mean
    two answers to "what is scheduled".
    """
    from . import schedule

    return schedule.ScheduledTask(
        key=KEY,
        title="Self-optimise",
        why=WHY,
        prompt=PROMPT,
        triggers=(schedule.Trigger(kind="time", hour=hour, minute=minute),),
        # It has something to say only when it changed something, and
        # `run()` says which. Off by default all the same: this is
        # housekeeping, and four in the morning is not a conversation.
        announce=False,
    )


def _saved():
    from . import schedule

    for one in schedule.read_user_tasks():
        if one.key == KEY:
            return one
    return None


def is_on() -> bool:
    from . import schedule

    saved = _saved()
    # See `dreaming.state`: called on every Memory-page render, so it must not
    # raise `CouldNotAsk` at a page that has no way to recover. 2026-09-05.
    return bool(saved and schedule.is_installed(
        saved, schedule.installed_names_or_empty()))


def turn_on(hour: int, minute: int) -> tuple[bool, str]:
    """Write the task and register it. Both halves, always."""
    from . import schedule

    saved, problems = schedule.save_user_task(task_for(hour, minute))
    if problems:
        return False, " ".join(problems)

    runner = schedule.runner_script()
    if not runner.exists():
        return False, ("Saved, but the file the scheduler calls is missing, "
                       "so nothing would have run.")

    ok, said = schedule.install(saved, runner, confirmed=True)
    if not ok:
        return False, f"Saved, but the scheduler refused it: {said}"
    return True, f"It will run at {hour:02d}:{minute:02d}."


def turn_off() -> tuple[bool, str]:
    from . import schedule

    saved = _saved()
    if saved is None:
        return True, "It was not on."
    if schedule.is_installed(saved):
        ok, said = schedule.remove(saved)
        if not ok:
            return False, f"It is still in the scheduler: {said}"
    schedule.delete_user_task(KEY)
    return True, "Off. Nothing it has already written is undone."
