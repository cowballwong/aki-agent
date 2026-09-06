---
name: end-of-day
description: Write today up — what moved in the user's projects, what is on tomorrow, what is still waiting on them. Saves it to the day log and sends it to them. Use when the user says EOD, end of day, wrap up the day, "that's me done", or types /end-of-day.
user-invocable: true
allowed-tools:
  - Bash
---

# End of day

**Say you have started, before you start.** One line, in their language, then
run the command. Not a paragraph — "Writing up the day, back in a minute or
two." is the whole acknowledgement.

This matters more here than almost anywhere else in the package: the command
below holds for one to two minutes while a headless run writes the entry, and
the person who asked is usually on their phone, where a minute of silence is
indistinguishable from a message that never sent.

```bash
python ~/.aki-agent/aki.py aki_agent.cli eod
```

## Do not write the entry yourself

The command runs the same job as the dashboard's **End of day** button and the
18:30 schedule. That job has its own instructions about what an entry contains
and in what order, it saves the result as the day's record, and it sends it to
the user through their usual channel.

Writing your own summary instead gives them a second account of the same day
that does not match the one in their log — and they have no way of knowing
which they are reading. If the command fails, say it failed. Do not fill the
gap with a summary of your own.

## When it comes back

It has **already been sent to them**. Do not paste the entry into your reply —
they will get it twice, from two directions, and the copies will not look the
same.

Say one line: it is written and where it lives. If the command reported that
it was held rather than delivered, that line is what you say instead — the
entry exists but has not reached them yet, and only they can tell you whether
that is what they wanted.

## If they ask again the same evening

Run it again. A second entry for one day is a real thing to want — the day
carried on after the first one — and refusing on the grounds that one already
exists is the assistant deciding it knows better. Just say it is the second.
