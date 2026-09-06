---
name: check
description: Check a draft before it is shown, recorded or sent — whether its sources are real, its verdicts are evidenced, its wording claims no more than the evidence supports, and nothing private is about to leave. Use before anything goes to another person, before writing a conclusion into the user's records, when the user asks "is this right" or "are you sure", and when they type /check.
user-invocable: true
allowed-tools:
  - Read
  - Bash
---

# Check it before they believe it

The assistant ships with one specialist of its own: a checker. It reads a
draft and says approve, flag or reject, with reasons. It never rewrites — an
author cannot check its own work, which is the entire reason this exists.

It is **on from installation**. Nobody has to set it up.

## When to run it without being asked

- Anything going to another person — an email, a message, a document they
  will pass on.
- Anything being written into the user's own records as settled: a status, a
  figure, a date, a decision.
- Any answer resting on a source you read rather than on what the user told
  you directly.
- Any time the user asks whether something is right, or whether you are sure.

Not for chat, not for a draft they are still thinking out loud about, and not
twice on the same text. A check that runs on everything gets ignored.

## Running it

```bash
python ~/.aki-agent/aki.py aki_agent.cli check --file <path> --sources <path> <path>
```

Or pass the text directly instead of `--file`. `--sources` is whatever the
draft rests on — the files, the extracts, the reasoning that produced it.

**Pass the sources.** A draft handed over with nothing behind it comes back
flagged on the evidence check, correctly, and you will have learnt nothing
you did not already know.

## What comes back

`approve` — all four checks passed. Carry on.

`flag` — it can go, but with a concern. **Show the user the concern before
they act**, in their language. Do not decide on their behalf that it was
minor.

`reject` — something in it would mislead. Fix the named line and check again.
Do not send it and mention the objection afterwards.

If the answer says the check could not be run, or could not be read, then
**nothing was verified**. Say exactly that. "It came back clean" and "it did
not come back" are different sentences, and only one of them is true.

## Turning it off, and making it theirs

```bash
python ~/.aki-agent/aki.py aki_agent.cli sentinel off
python ~/.aki-agent/aki.py aki_agent.cli sentinel on
```

Off means you stop checking drafts on your own initiative. If they then ask
for a check, run one — they have asked.

If they want it shaped to their own field — different sources to open,
different wording to catch — that makes a **new** specialist alongside this
one, the same as editing anything from the library. Use `/new-specialist`,
starting from what the built-in one does. The original is left alone, so an
upgrade cannot destroy their version and their version cannot weaken the
general check.
