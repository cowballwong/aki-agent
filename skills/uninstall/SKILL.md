---
name: uninstall
description: Remove the assistant from this machine — settings, memory, scheduled tasks, skills, launcher and the plugin — while leaving every document untouched. Use when the user types /uninstall, or says "remove this", "get rid of the assistant", "undo the install", "I want my machine back", or asks how to uninstall.
user-invocable: true
allowed-tools:
  - Bash
  - Read
---

# Uninstall — leaving, without taking their work with you

Anything a person installs, they must be able to remove. If uninstalling means
hunting through a home folder and a task scheduler guessing which entries
belong to which product, then "try it and see" was never a fair offer.

**The thing that matters most here is what does *not* get removed.** Their work
stays. Every project folder, every document, every file they ever put in the
workspace is theirs and is left exactly where it is. Say so out loud, before
anything happens — this is the one moment where a person is entitled to be
nervous, and the fix is showing them, not reassuring them.

## First, show them the list

```bash
python ~/.aki-agent/aki.py aki_agent.cli uninstall
```

This removes nothing. It prints two lists: what would go, and what would stay.
Read the second one back to them in plain words — *"your work folder, 340
files, is not on the removal list"* — and then let them decide.

If they have a reason to keep something, stop and say what you can do instead.
There is no partial mode here beyond `--keep-plugin`; anything else is a
conversation, not a flag.

## Then, only after they say yes

```bash
python ~/.aki-agent/aki.py aki_agent.cli uninstall --yes
```

Add `--keep-plugin` if they want to keep the Claude Code plugin installed —
for instance because they are about to reinstall somewhere else.

It removes: the config folder (settings, memory, state, logs), the pointer file
that says where that folder is, an older config folder from a previous install,
every scheduled task carrying this package's prefix, the skills this package
put in Claude Code's own skills folder, the generated launcher, the sandbox
(the assistant's own desk — the plan says how many files are in it before
anything happens), `CLAUDE.md`, `README.md` and `.claude/` at the top of the
assistant's folder, and the plugin itself.

`CLAUDE.md` and `README.md` are removed **only while they still carry the line
the scaffold wrote into them**. If the person has rewritten either, the words in
it are theirs and it is listed as kept instead.

## When something will not delete

On Windows this is almost always a program still holding the folder open — the
dashboard, or a terminal whose current directory is inside it. Close those and
run it again. Do not suggest deleting by hand as the first answer; a person
deleting folders manually next to their documents is exactly the situation this
command exists to avoid.

## What this does not touch

- **Their documents.** Never, under any circumstance, and there is no flag for
  it. If someone asks you to delete their work as part of uninstalling, that is
  a separate request and they should do it themselves, deliberately, in their
  own file manager.
- **Claude Code.** Removing this assistant does not remove Claude Code, and
  should not be described as if it might.
- **The folder they unzipped.** Tell them they can delete it whenever they
  like; nothing runs from there once the plugin is gone.

## Afterwards

Say what was removed, say plainly where their work still is, and stop. Do not
offer to reinstall in the same breath — they asked to leave.

## The screens

Draw the frames, do not type them:

```bash
python ~/.aki-agent/aki.py aki_agent.cli screen banner \
  --title "<what is about to happen>" --subtitle "uninstall"
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
