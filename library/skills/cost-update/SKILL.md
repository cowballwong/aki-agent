---
name: cost-update
title: Update the cost position
description: Read a cost plan, valuation, order schedule or fee account the user supplies and write the figures into the project's cost.md so the Cost position panel can draw budget against committed and spent. Use when the user mentions a cost plan, budget, valuation, certificate, commitment, overspend, or asks where the money is.
industries: [architect, contractor, engineer, project manager, surveyor]
category: Built environment
keywords: [cost, budget, committed, spent, valuation, cost plan, overspend, 成本, 預算, 超支]
confidence: high
---

# Update the cost position

Writes `cost.md` in one project folder. The `cost-position` panel reads it.

## The rule that comes before everything else

**Never write a figure you cannot point at.**

No estimating a missing line, no pro-rata split of a lump sum across elements,
no carrying a figure forward from an older revision to fill a gap. A line you
cannot source is left out and reported to the user by name. Three sourced
lines and a sentence saying what is missing beats eight lines where five are
guesses, every time — and the guesses are the ones that get quoted in a
meeting.

Where two documents disagree, write neither. Say which two, what each says,
and ask which governs.

## The three figures, and why they are these three

```
---
source: "Cost plan rev 4, 03 Jul 2026 (p.6); valuation 07, 22 Aug 2026"
lines:
  - label: Frame and envelope
    budget: 1240000
    committed: 1318000
    spent: 742000
---
```

- `budget` — what was allowed. The allowance the line is measured against.
- `committed` — what has been ordered or instructed. Money that is gone
  whether or not it has been paid.
- `spent` — what has actually been certified or paid out.

They are these three because they are the three that get confused in every
meeting, and because `committed` is where an overspend appears **first**. A
report that shows only budget against spent finds the problem after it is too
late to do anything about it.

Plain numbers, no commas, no currency symbol — the panel formats them.

## What to say afterwards

One line per breach: which line, over by how much, against which figure. Then
the totals. Do not editorialise about whether it is acceptable; that is the
user's judgement and their client's money.

Where nothing is committed yet — pre-tender — say that, so a page of budget
bars with nothing beside them reads as "not started" rather than "no data".

## Before you write

Show the lines and the source and get a yes.

## Do not

- Do not add VAT, fees or contingency that the source does not show as its own
  line. If the source is exclusive of something, say so in `source`.
- Do not convert currencies silently. Ask, and record the rate and its date in
  `source`.
- Do not reconcile to a total by adjusting a line. A set of lines that does not
  add up to the stated total is a finding to report, not a rounding error to
  absorb.
