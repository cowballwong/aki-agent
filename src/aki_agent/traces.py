"""Learning from the user's verdicts, without sending anything anywhere.

THE IDEA
--------
Every time the assistant produces something and the user reacts — accepted it,
edited it, rejected it — that reaction is the most valuable training signal
available, and it is thrown away by default.

So: append it to a log. Then distil the log into a short card the assistant
reads *before* attempting the same kind of task again. The user stops having
to repeat the same correction.

TWO DESIGN CHOICES WORTH DEFENDING
----------------------------------

**It is append-only.** Nothing is ever rewritten, so the record of what the
user actually said cannot drift. Distillation reads the log and writes a
separate file; it never edits the source.

**It is entirely local, and rule-based.** No model call, no API, nothing
leaves the machine. That is not a limitation to be lifted later — the whole
point is that a person's corrections about their own work are private, and a
learning loop that phones home is one most people should decline.

A rule-based distillation is much dumber than a model-based one. It is also
inspectable, free, offline, and impossible to be surprised by, and for "remind
me what this person told me last time" that trade is correct.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, asdict
from pathlib import Path

from . import atomic, paths, secrets

VERDICTS = ("accepted", "edited", "rejected")


def trace_file() -> Path:
    return paths.log_dir() / "traces.jsonl"


def card_dir() -> Path:
    return paths.memory_dir() / "learned"


@dataclass
class Trace:
    """One thing the assistant did, and what the user thought of it."""

    task: str                # what kind of work this was, e.g. "summary"
    output: str              # what the assistant produced (may be trimmed)
    verdict: str             # one of VERDICTS
    correction: str = ""     # what the user changed it to, in their words
    context: str = ""        # terse note about the situation
    at: str = ""

    def __post_init__(self) -> None:
        if not self.at:
            self.at = _dt.datetime.now().isoformat(timespec="seconds")
        if self.verdict not in VERDICTS:
            raise ValueError(
                f"verdict must be one of {VERDICTS}, not {self.verdict!r}")


def log(task: str, output: str, verdict: str, correction: str = "",
        context: str = "", max_chars: int = 2000) -> Trace:
    """Record one verdict.

    Everything written here is redacted first. Traces are the most likely
    place for a credential to be captured by accident, because the assistant's
    output is whatever it happened to be working on.
    """
    trace = Trace(
        task=task.strip(),
        output=secrets.redact(output.strip())[:max_chars],
        verdict=verdict,
        correction=secrets.redact(correction.strip())[:max_chars],
        context=secrets.redact(context.strip())[:500],
    )
    atomic.append_line(trace_file(),
                       json.dumps(asdict(trace), ensure_ascii=False))
    return trace


def record_verdict(task: str, output: str, verdict: str,
                   correction: str = "", context: str = "") -> Path:
    """Log a verdict AND refresh the card, in one step.

    THE MISSING TRIGGER
    -------------------
    `log()` and `distil()` both existed and worked. Nothing called `distil()`.
    So verdicts accumulated in a file that was never turned into anything the
    assistant reads, and the learning loop learned nothing — while looking,
    from the outside, exactly like a learning loop.

    That is the third instance of the same shape in this package: a correct
    mechanism with nothing wired to it. Hence this function, which is the only
    one anything else should call. `log()` and `distil()` remain separate so
    each is still readable on its own, but the pair is now impossible to use
    by halves.
    """
    log(task=task, output=output, verdict=verdict,
        correction=correction, context=context)
    return distil(task)


def read_traces(task: str | None = None) -> list[Trace]:
    path = trace_file()
    if not path.exists():
        return []

    traces: list[Trace] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            trace = Trace(**data)
        except (json.JSONDecodeError, TypeError, ValueError):
            # A malformed line is skipped, not fatal. An append-only log that
            # refuses to load because of one bad row is a log you lose.
            continue
        if task is None or trace.task == task:
            traces.append(trace)

    return traces


def stats(task: str | None = None) -> dict[str, int]:
    counts = {verdict: 0 for verdict in VERDICTS}
    for trace in read_traces(task):
        counts[trace.verdict] = counts.get(trace.verdict, 0) + 1
    return counts


def distil(task: str, keep_corrections: int = 12,
           keep_examples: int = 3) -> Path:
    """Turn the log into a card the assistant reads before doing this task.

    The rules are deliberately simple and completely inspectable:

      * every correction the user made, newest first
      * a few examples they accepted without changing
      * a tally, so the assistant knows how it is doing

    That is it. No summarising, no inference, no cleverness. The user's own
    words are the instruction; anything that paraphrases them loses the point.
    """
    traces = read_traces(task)
    counts = stats(task)

    corrections = [trace for trace in reversed(traces)
                   if trace.correction and trace.verdict in ("edited",
                                                             "rejected")]
    accepted = [trace for trace in reversed(traces)
                if trace.verdict == "accepted"]

    lines = [
        f"# What I have learned about: {task}",
        "",
        f"_Distilled from {len(traces)} recorded verdicts on "
        f"{_dt.date.today().isoformat()}. Entirely local -- nothing here has "
        "left this machine._",
        "",
        f"Accepted {counts.get('accepted', 0)} · "
        f"edited {counts.get('edited', 0)} · "
        f"rejected {counts.get('rejected', 0)}",
        "",
    ]

    if corrections:
        lines += ["## Corrections to honour", "",
                  "These are the user's own words. Follow them.", ""]
        for trace in corrections[:keep_corrections]:
            when = trace.at[:10]
            lines.append(f"- **{when}** — {trace.correction}")
            if trace.context:
                lines.append(f"  - context: {trace.context}")
        lines.append("")
    else:
        lines += ["## Corrections to honour", "",
                  "_None recorded yet._", ""]

    if accepted:
        lines += ["## Accepted before", "",
                  "Examples that needed no change.", ""]
        for trace in accepted[:keep_examples]:
            excerpt = trace.output.strip().splitlines()
            preview = excerpt[0][:200] if excerpt else ""
            lines.append(f"- {preview}")
        lines.append("")

    card_dir().mkdir(parents=True, exist_ok=True)
    return atomic.write_text(card_dir() / f"{_safe(task)}.md",
                             "\n".join(lines))


def card_for(task: str) -> str:
    """The card's text, or an empty string if there is not one yet."""
    path = card_dir() / f"{_safe(task)}.md"
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _safe(task: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", task.lower()).strip("-") or "task"
