---
name: deadline-watch
title: Deadline and renewal watch
description: Keep one list of every dated obligation — statutory, contractual, licence, insurance, subscription — and warn before each one when you ask. Use when the user asks what is due, mentions a deadline or renewal, or asks what they are forgetting.
industries: [*]
category: Core
keywords: [due dates, renewals, statutory, MPF, IRD, 死線, 續期]
confidence: high
---

# Deadline and renewal watch

One list, everything dated, sorted by what happens soonest.

## What belongs on it

- **Statutory** — tax filing, employer returns, mandatory contributions,
  statutory inspections, licence renewals.
- **Contractual** — milestones, notice periods, options that lapse.
- **Practical** — insurance, subscriptions, professional membership,
  certificates that expire.

## How to build it

Read what the user actually has: their project files, their notes, anything
they have told you to remember. **Every entry must name where it came from.**
A date with no source is a date nobody will act on, because they cannot
check it.

If they are in Hong Kong, the recurring ones worth asking about are MPF
contribution dates, IRD filing, the 12 months of wage records the Employment
Ordinance requires an employer to keep, business registration renewal, and
any trade licence. **Ask — do not assume any of them apply.**

## Warning

Warn at a distance that matches the work, not a fixed number of days: a form
that takes an afternoon needs a week; an audit needs a month. State the
assumption so they can correct it.

## What this never does

It does not file anything, pay anything, or contact a regulator. It does
not run on its own either -- see below.

## Being told without asking

**This skill runs when you ask it to. It does not watch the calendar on its
own** -- nothing here wakes up in the morning and checks.

That distinction was blurred for a while: the description said it warns ahead,
which reads as something happening in the background, and there was nothing in
the background at all. Somebody who believed it would have found out on the
day.

To make it genuine, give it a heartbeat of its own. On the dashboard's
Schedule page, add a task that runs once a day and says:

> Run this skill. If anything is due inside its warning window, tell me. If
> nothing is, say nothing.

That is a real scheduled task, it runs whether or not anybody is at the
machine, and the "say nothing" half matters: a daily message that is usually
empty gets ignored within a fortnight, and then so does the one that is not.
