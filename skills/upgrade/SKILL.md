---
name: upgrade
description: Move this assistant onto a newer release. Use when the person says upgrade, update, "I downloaded the new version", or names a new Aki-Agent zip. Handles both halves — the Python engine and the Claude Code plugin — from one command.
---

# Upgrading

One command. It finds the new release, replaces the engine inside their own
folder, re-points the launcher and the scheduled tasks at it, and hands Claude
Code the new plugin.

## Why this is one command and not a list of steps

The package is two things: a Python engine and a Claude Code plugin. Upgrading
used to mean adopting the engine *and* re-pointing the marketplace, and the maintainer
said plainly on 2026-08-19 that this was too complicated. He was right — being
two things is the package's problem, not the user's.

So do not walk them through the pieces. Run the command.

## Fetch the new version first, without asking them to

Somebody who installed from the marketplace has their new version downloaded
by Claude Code, not by them. Run both lines before anything else -- they are
safe to run when there is nothing new, and they are the difference between
one command and a list of steps:

```bash
claude plugin marketplace update aki-agent
claude plugin install aki-agent@aki-agent
```

If either is not available on this machine, say so plainly and carry on: the
engine half below still works, and a zip user never needed these at all.

**Do not hand these to the person to paste.** The reason this skill exists is
that the package is two things and the user should never have to know it. Somebody
testing a fresh macOS install was handed three commands to type into a
terminal and said, reasonably, that an update should resolve the problem
rather than produce more commands. Being two halves is the package's
problem. Run the commands.

## Do this

```bash
python ~/.aki-agent/aki.py aki_agent.cli upgrade
```

That reports what it found and changes nothing. It looks in Claude Code's
plugin cache as well as in Downloads, Documents and Desktop, so after the two
lines above it finds the new version on its own. Read it back to them: which
version they are on, which version they would move to, and where the new files
came from.

### If it says it could not find a release

**Do not ask them where it is yet.** The upgrade that runs is the one already
installed, so an engine older than 0.47.2 is searching with a version of the
search that never knew about the plugin cache — and it will say it found
nothing while the new release sits in that cache. This is the one hop the
package cannot make on its own, and the skill carries it rather than the
person:

```bash
ls -d ~/.claude/plugins/cache/*/aki-agent/*
```

Pick the highest version number in that list — compare the numbers, not the
text, so 0.47.10 beats 0.47.9 — and hand it over:

```bash
python ~/.aki-agent/aki.py aki_agent.cli upgrade --from "<that folder>" --yes
```

Only when there is no such folder at all is this a zip install, and only then
do you ask where they downloaded it:

```bash
python ~/.aki-agent/aki.py aki_agent.cli upgrade --from "<path to the zip or folder>"
```

## Ask with a menu, not a sentence

**Draw the choice. Do not merely say "reply with a number".**

Telling somebody to reply with a number and then not showing them any numbers
is the specific thing the maintainer reported on 2026-08-20: he was asked for one and
had nothing to pick from. A number belongs to an option; on its own it is a
riddle.

```bash
python ~/.aki-agent/aki.py aki_agent.cli screen menu   --title "<Move from <old> to <new>?>"   --option "<Yes, upgrade now>"   --option "<Not now>"   --option "<Tell me what will change first>"   --footer "<reply with a number>"
```

Draw it with the command rather than typing the box yourself — the frame is
built from display width, which is the only thing that keeps it square when
the labels are in their language rather than English.

Then, once they have picked the first one:

```bash
python ~/.aki-agent/aki.py aki_agent.cli upgrade --from "<the same path>" --yes
```

## Afterwards

**Tell them to restart Claude Code.** The new skills are read at start-up, so
until they do, they are talking to the version they had before — which looks
exactly like the upgrade having done nothing.

Then run the health check and read them the result:

```bash
python ~/.aki-agent/aki.py aki_agent.doctor
```

The check to look for is *"Everything runs from your own folder"*. When that
passes, say the sentence they actually want to hear: **the folder you
downloaded can be deleted.**

## If the version does not change

The command says so rather than hiding it. Three releases once went out under
one version number, and the only symptom was an upgrade that appeared to do
nothing — so if it reports the same version on both sides, that is worth
repeating to them out loud rather than glossing over.

## What this never touches

Their settings, their memory, and everything in their workspace. The engine
folder is replaced wholesale; nothing else is read, moved or deleted.

## The screens

Draw the frames, do not type them:

```bash
python ~/.aki-agent/aki.py aki_agent.cli screen banner \
  --title "<what is about to happen>" --subtitle "upgrade"
python ~/.aki-agent/aki.py aki_agent.cli screen outcome \
  --title "<what happened>" [--detail "<what it means for them>"] [--failed]
```

An ASCII frame is a drawing, not a sentence: its meaning is in which character
sits above which, and that does not survive being written out token by token —
least of all with a Chinese label, where three characters occupy six columns.
`screens.py` measures display width so every border is square in every
language. A crooked box reads as a broken program.

Any question with countable answers gets `screen menu` and a number, not a
blank prompt. Keep the last option as *none of these — I'll tell you*.
