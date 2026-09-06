---
name: install-check
description: Work out whether installing means a first install, an update, or a merge into an assistant the user already has — and confirm with them before anything happens. Use when the user says install, reinstall, update, upgrade, "set this up", points at a downloaded package, or asks what version they are on.
user-invocable: true
allowed-tools:
  - Bash
  - Read
---

# Before you install anything

```bash
python ~/.aki-agent/aki.py aki_agent.cli situation
```

Run this first, every time, before acting on any request that sounds like
installing. It changes nothing. It reports which of five situations this
machine is actually in, and the evidence behind that.

## Why this exists

"Install this" is one sentence covering three different jobs, and the person
saying it usually cannot tell which one applies — that is not their job to
know. Getting it wrong is not symmetrical either: almost everything here is
reversible, except running a first-time setup over a configuration that
already exists.

## What to do with each answer

**First install, nothing here yet** — install the plugin and run setup. Then
tell them the downloaded folder can be deleted; their assistant lives in
`~/.aki-agent` and their own workspace, not in the download.

**First install, but they already have their own assistant** — stop and ask.
**Three** options, and what separates them is which assistant ends up as the
main one:

- **side by side** — install normally. Nothing of theirs is touched, and they
  have two assistants whose memories never meet.
- **this one becomes the main assistant** — their existing agent's memory,
  instructions, settings and scheduled work are brought across into it, and
  their own folder is left untouched. The `import-my-agent` skill.
- **their assistant stays the main one** — capabilities from this package are
  added to it, one at a time, additively. The `integrate` skill, and
  `INTEGRATE.md` describes it.

Never say "merge" here. It was the word this question used until 2026-09-06,
and it says nothing about direction: The maintainer asked for the second option, was
offered the third, and had no way to tell from the wording that they were
opposites. Name the destination, not the operation. Do not guess which they
want from how long they have run their own — ask, then read the direction
back to them in your own words before touching anything.

**Plugin installed, setup never run** — do not reinstall anything. Just run
setup.

**An update** — install as usual and say plainly that their configuration,
memory and work are not touched, because people reasonably fear otherwise.
Then run the repair step, which is not optional:

```bash
python ~/.aki-agent/aki.py aki_agent.cli repair --yes
```

Each version installs into its own folder, so their scheduled tasks and
launcher still point at the previous one. Left alone they stop running the day
it is cleaned up — no error, no message, just an assistant that gradually does
nothing.

**Already installed, same version** — nothing to install. Find out what they
actually wanted: a setting changed, or something fixed.

## The rules

**Report before you act.** Tell them what was found, in two or three sentences
in their own language, then ask the question the report gives you and wait.

**Never run setup over an existing configuration** because someone said
"install" and sounded certain. Confirm that specific thing, in those words.

**Say what will not be touched.** Most of the fear around updating is about
losing work. Naming what stays is more reassuring than any reassurance.
