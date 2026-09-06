---
name: tax-filing-calendar
title: Tax and filing calendar
description: Build the year's filing obligations with dates, and warn ahead of each when you ask. Use when the user mentions tax filing, profits tax, employer returns, annual returns, or asks what is due.
industries: [accountant, company secretary, SME]
category: Professional services
keywords: [IRD, profits tax, employer return, filing, 報稅, 報表]
confidence: high
---

# Tax and filing calendar

## Build it from their own facts

Entity type, financial year end, whether they employ anybody, whether they are
registered for anything else. Ask once; the answers drive every date.

## What goes on it

Returns and their statutory dates, extensions where an extension regime
exists, payment dates, and the internal date by which the work must start —
which is the one people actually need.

**Every entry names its source.** A date with no source cannot be checked,
and this is a list where being wrong is expensive.

## Rules

- Do not state a statutory deadline from memory. Work from the notice, the
  authority's published date, or the user's own prior-year record — and say
  which.
- Distinguish the filing date from the payment date. They are different
  obligations with different consequences.

## Warning

Warn far enough ahead for the work, not the form: an audit-dependent return
needs months, not weeks.

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
