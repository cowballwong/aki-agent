---
name: brief-me
description: A short spoken-length summary of what needs attention — right now, on demand, rather than waiting for the scheduled morning summary. Use when the user asks what is on, what needs doing, where things stand, what they missed, or types /brief-me.
user-invocable: true
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
---

# Brief me

```bash
python ~/.aki-agent/aki.py aki_agent.cli projects
python ~/.aki-agent/aki.py aki_agent.cli today
```

Then read the notes of anything that looks live, and say what matters.

## The shape of a good brief

**Lead with the verdict.** "Two things need you today" or "nothing urgent" —
then the detail. Someone asking this is usually deciding whether to sit down
and work, and the first sentence should answer that.

**Three or four things, not everything.** A brief that lists twelve items has
not done the job the user asked for, which is choosing.

**Say what changed since last time**, not what is true in general. The state
of a project they have not touched in a month is not news.

**Then stop.** Do not append encouragement, a plan for the day, or an offer to
do all of it. If they want more they will ask.

## Where the ranking comes from

In order: something with a date attached that has passed or is close · someone
else waiting on them · work that has gone quiet longer than usual · everything
else.

**Do not invent urgency.** If nothing is pressing, the correct brief is
"nothing needs you today" and that is a good outcome, not a failure to find
material. A daily brief that manufactures three concerns every morning gets
switched off inside a fortnight.

## Two honesty rules

**Say when you could not read something.** A cloud folder that has not mounted
yet, a file that would not parse — that goes in the brief. A brief that
silently skips a project reads as "nothing there", and the user acts on it.

**Never present the last known state as the current one.** If the workspace
could not be read, say the brief is stale and when it was last good. Confident
stale data is worse than no data, because it gets acted on.

## Afterwards

If the user reacts to something — decides, dismisses, defers — write it down
before it evaporates:

```bash
python ~/.aki-agent/aki.py aki_agent.cli log "<what they decided>"
```

That log is what tomorrow's brief reads to know what already got handled.
Without it, the same three things get raised every morning until the user
stops reading.
