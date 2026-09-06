---
name: add-abilities
description: Offer and install optional extra abilities from Anthropic's own skills marketplace — reading and writing PDF, Word, Excel and PowerPoint files being the ones most people want. Use when the user asks what else the assistant can do, wants to handle Office documents or PDFs, says a file type is not supported, or types /add-abilities.
user-invocable: true
allowed-tools:
  - Read
  - Bash
---

# Add abilities — point at them, never copy them

Some things people expect an assistant to do are already published by
Anthropic as skills. This package **does not ship copies of them**, and the
reason is not tidiness.

## Read this before offering anything

The document skills — `pdf`, `docx`, `pptx`, `xlsx` — are **source-available,
not open source.** Their licence forbids extracting them from the Services,
keeping copies outside the Services, reproducing them, and making derivative
works. Most other skills in the same repository are Apache 2.0 and could be
copied, but the rule here is the same for all of them:

**Point the user at the official source. Never copy a skill into this package,
and never copy one out of another machine.**

The user installs from Anthropic directly, under their own agreement with
Anthropic. That keeps the licence question where it belongs, and it means they
get updates without waiting for this package to catch up.

## What to offer

Ask plainly, and only about things they will recognise:

> Do you want to be able to work with PDF, Word, Excel and PowerPoint files?
> They come from Anthropic and install with two commands — I can run them now.

If they say yes:

```bash
claude plugin marketplace add anthropics/skills
claude plugin install document-skills@anthropic-agent-skills
```

Then tell them it takes effect in their **next** session, not this one.

There is also `example-skills@anthropic-agent-skills` in the same marketplace,
worth mentioning only if they ask what else is there. Do not read out a
catalogue: a list of thirty things nobody asked for is how a setup gets
abandoned.

## If a command fails

Say what failed in one sentence and stop. The likely causes, in order:

- **Not signed in, or Anthropic is having an outage.** Nothing to fix locally.
  Check `status.claude.com` before assuming the machine is at fault — an
  authentication outage looks exactly like a broken install from here.
- **`claude` is not on the path.** `/doctor` reports this properly.
- **No network.**

Do not retry a failed install more than once, and never try to work around it
by copying files from somewhere else. That is the thing the licence forbids.

## What not to say

Do not promise the assistant can already read PDFs before the install has
actually happened and a new session has started. A capability that is
announced and then absent is worse than one that was never mentioned — the
user stops trusting everything else you told them.
