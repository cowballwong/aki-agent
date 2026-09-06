---
name: programme-update
title: Update the programme
description: Read a programme the user supplies — a PDF, a spreadsheet, a Project export, a photograph of a wall chart — and write the dated stages into the project's programme.md so the Programme panel can draw them. Use when the user mentions a programme, a revised programme, slippage, milestone dates, or asks why the chart is out of date.
industries: [architect, contractor, engineer, project manager, surveyor]
category: Built environment
keywords: [programme, gantt, milestone, baseline, slippage, revised programme, 進度, 甘特圖]
confidence: high
---

# Update the programme

Writes `programme.md` in one project folder. The `programme-gantt` panel reads
it. Nothing else in the system writes this file.

## The rule that comes before everything else

**Never type a date that is not in the document in front of you.**

Not an interpolated one, not a "reasonable" one, not one carried over from a
conversation. If a stage has no date in the source, write the row with the
dates it does have and leave the rest out. The panel draws what is missing as
missing, and that is the correct outcome. A schedule with an invented date on
it is worse than no schedule, because somebody will act on it.

The same rule applies to reading badly: if a date is illegible in a scan, say
so and ask. "I could not read the tender return date" costs one message.

## What to write

```
---
source: "Contract programme rev C, 12 Jun 2026"
milestones:
  - label: Substructure
    start: 2026-03-16
    end: 2026-06-05
    baseline_end: 2026-05-22
    status: done
    owner: Principal contractor
---
```

- `source` — the document, its revision and its date. Written once at the top
  where the whole file came from one document; on the row where a single date
  came from somewhere else (a minute, an email, a call).
- `label` — the stage, in the words the source uses.
- `start` / `end` — what is forecast now. ISO dates, `YYYY-MM-DD`.
- `baseline_end` — the date the **contract or agreed** programme gave. Leave it
  out where there is no agreed baseline; do not use the current forecast as its
  own baseline, which would draw every job as running exactly to time.
- `status` — `done`, `live`, `next`. Optional; it only changes the shading.
- `owner` — who has to make it happen. Optional.

## A revision replaces, it does not accumulate

When a new revision arrives, rewrite the file from it. Keep `baseline_end` from
the original agreed programme — that is the whole point of a baseline, and a
baseline quietly re-pointed at the latest revision is how a job appears to have
never slipped.

Say what changed in one line: which stages moved, by how many days, and what
that does to completion.

## Before you write

Show the rows and the source line and get a yes. The project folder is the
user's, and this file is the one the chart on their wall is drawn from.

## Do not

- Do not read a percentage of completion off a bar chart image. Bar lengths in
  a scanned programme are not measurements.
- Do not merge two projects into one file.
- Do not put commentary in the frontmatter. Prose goes under it, where the
  panel ignores it and a person can still read it.
