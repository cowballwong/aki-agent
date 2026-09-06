---
name: time-and-billing
title: Time and billing capture
description: Reconstruct where the day or week went and turn it into billable lines. Use when the user asks about timesheets, billable hours, what they did today, or needs to bill time.
industries: [*]
category: Core
keywords: [timesheet, billable, hours, WIP, 工時, 記帳]
confidence: high
---

# Time and billing capture

## Where the material comes from

What actually happened — files touched, meetings held, messages sent,
site visits, notes written. Reconstruct the day from the record rather than
asking the user to remember it, then show it for correction.

## What a line needs

Date · job · what was done, in the client's language · time · billable or not.

"Correspondence" is not what was done. "Reviewed structural comments and
replied to engineer" is. The second one survives a fee query; the first one
invites it.

## Rules

- **Never invent time.** A gap is a gap; show it and ask.
- Round the way the user's own practice rounds, and ask once what that is.
- Flag anything that looks unbillable — internal admin, rework — as
  non-billable by default and let them argue with it. The other way round is
  how a client relationship gets damaged.

## Afterwards

Offer the total by job and the total unbilled, oldest first. That second
number is usually the one that matters and the one nobody has.
