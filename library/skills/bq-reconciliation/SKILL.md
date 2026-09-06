---
name: bq-reconciliation
title: Bill of quantities reconciliation
description: Reconcile a priced bill against the drawings and specification revision it was measured from. Use when the user mentions a BQ, a bill, remeasurement, or a pricing check.
industries: [QS, contractor]
category: Built environment
keywords: [BQ, bill of quantities, remeasure, 工料, 對數]
confidence: high
---

# Bill of quantities reconciliation

## The question this answers

Does this bill still describe the drawings we now have?

## Method

1. Note the drawing revisions the bill was measured from, and the revisions
   current today. Every difference is a candidate for a change.
2. Walk the bill section by section. For each item: quantity, unit, rate,
   and the drawing reference it came from.
3. Flag: items with no drawing reference, quantities that moved by more than
   the user's threshold, units that changed, and rates that appear in two
   places with different values.

## What to hand back

- **differences that change money**, largest first, each with the drawing
  revision that caused it
- **items to remeasure**
- **items with no basis** — the ones that will be argued about

## Rules

Never adjust a quantity to make a total agree. If two figures disagree, name
both and say which document each came from. Arithmetic that has been quietly
reconciled is the hardest kind of error to find later.
