---
name: find
description: Find something the user half-remembers — across what has been remembered, the daily logs, and the notes in their projects. Use when they ask where something is, what was decided about something, when something happened, whether they wrote something down, or "what do I know about X".
user-invocable: true
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
---

# Find it

Three places hold different kinds of answer. Search the one that fits the
question first, then widen.

| They are asking | Look in | Command |
|---|---|---|
| what was decided / how they like things | remembered facts | `cli search "<words>"` |
| when something happened | the daily logs | `cli days --count 14` |
| anything about a piece of work | the project notes | Grep the workspace |

```bash
python ~/.aki-agent/aki.py aki_agent.cli search "<their words>"
python ~/.aki-agent/aki.py aki_agent.cli days --count 14
```

The search is ranked, not filtered — the best match comes first, and a low
score means "this was the closest thing, not necessarily the thing". Say so
when the scores are poor rather than presenting a weak match confidently.

It also works in Chinese and Japanese, which have no spaces between words.

## Search with their words, then with yours

People search for what they called it at the time, so start there. If nothing
comes back, try the obvious synonyms yourself before reporting failure — one
extra attempt costs a second and saves the user rephrasing.

But **do not silently substitute a different question.** If they asked about
"the fee thing" and you searched three phrasings, say which ones you tried.

## When you find nothing

Say so plainly, say where you looked, and stop.

Do not reconstruct an answer from what seems likely. "I did not find anything
about that" is a useful answer. A confident invention is the failure this
whole system is designed to avoid, and it is worse here than anywhere else,
because the user asked precisely *because* they could not remember.

Then offer the one useful next step: if it should have been written down,
offer to write it down now (`remember-this`).

## When you find too much

Do not paste the list. Give the two or three that answer the question, say how
many others matched, and offer to show more. A wall of results is the same as
no answer — the user still has to do the finding.
