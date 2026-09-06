---
name: stock-and-expiry
title: Stock and expiry watch
description: Track consumable stock and expiry dates and warn, when you ask, before something runs out or expires. Use when the user mentions stock, supplies, expiry dates, or reordering.
industries: [clinic, beauty, retail, allied health]
category: Health, care and education
keywords: [stock, expiry, consumables, reorder, 存貨, 到期]
confidence: draft
---

# Stock and expiry watch

## The register

Item · quantity held · reorder level · supplier · lead time · expiry dates by
batch.

## What to warn about

- **expiring within the period that matters** — for anything clinical or
  edible, well before, so it can be used or replaced rather than binned
- **below reorder level**, taking lead time into account: an item with a
  three-week lead time has to be flagged three weeks early, not when it runs
  out
- **batches** — expiry is per batch, not per item, and a register that
  averages them is wrong in the direction that matters

## Rules

Never adjust a count to match a record. If the count and the record disagree,
report both — a stock discrepancy is information, not an error to be tidied.

## Output

What to order today, what to use first, and what to discard, each with the
date that drives it.

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
