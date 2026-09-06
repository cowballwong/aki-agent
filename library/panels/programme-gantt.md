---
name: programme-gantt
title: Programme
kind: gantt
description: Every dated stage across the projects in this workspace, drawn
  against its baseline so slippage is visible rather than calculated.
industries: [architect, contractor, engineer, project manager, surveyor]
category: Built environment
keywords: [programme, gantt, milestone, baseline, slippage, 進度, 甘特圖]
reads: rows
file: programme.md
rows: milestones
label: label
start: start
end: end
baseline: baseline_end
status: status
unsourced_note: "{n} of {total} dates carry no source. Ask me to trace them back to the programme."
empty_note: "This panel reads the programme file in each project folder — give me a programme and I will fill it in."
---

Reads `programme.md` in each project folder. One entry per dated stage:

```
---
source: "Contract programme rev C, 12 Jun 2026"
milestones:
  - label: Substructure
    start: 2026-04-06
    end: 2026-06-19
    baseline_end: 2026-06-05
    status: live
---
```

`baseline_end` is the date the contract programme gave. `end` is what is
forecast now. The gap between them is the slip, and it is drawn.

Nothing writes this file automatically. The `programme-update` skill fills it
in from a programme the user supplies, and records where each date came from
in `source`. A row with no source is drawn hatched, because a date nobody can
trace is not a date anyone should act on.
