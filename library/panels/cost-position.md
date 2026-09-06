---
name: cost-position
title: Cost position
kind: bars
description: Budget against what is committed and what has been spent, line by
  line, scaled so the big line is obvious at a glance.
industries: [architect, contractor, engineer, project manager, surveyor]
category: Built environment
keywords: [cost, budget, committed, spent, valuation, 成本, 預算]
reads: rows
file: cost.md
rows: lines
label: label
values: [budget, committed, spent]
unit: "£"
unsourced_note: "{n} of {total} lines carry no source. Ask me to trace them back to the cost plan."
empty_note: "This panel reads the cost file in each project folder — give me a cost plan or a valuation and I will fill it in."
---

Reads `cost.md` in each project folder:

```
---
source: "Cost plan rev 4, 03 Jul 2026 (p.6)"
lines:
  - label: Substructure
    budget: 210000
    committed: 198500
    spent: 121000
---
```

The three figures are the three that get confused in every meeting: what was
allowed, what has been ordered, and what has actually gone out. Where
`spent` exceeds `budget` the overspend is stated on the line as a figure, not
as a colour alone — a red bar nobody can read off is a decoration.

Figures come from the `cost-update` skill reading a real cost plan or
valuation. It never estimates a missing figure; a line it cannot source is
left out and reported.
