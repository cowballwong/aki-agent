---
name: new-project
description: Start a new piece of work — creates the project folder and its tracking notes, in whichever workspace the user says. Use when the user says they have a new job, case, client, matter, module, trip or project, or types /new-project, or describes something new they are about to start working on.
user-invocable: true
allowed-tools:
  - Read
  - Bash
---

# Start a new project

## Do this

```bash
python ~/.aki-agent/aki.py aki_agent.cli new-project "<workspace>" "<name>"
```

That **plans** it and writes nothing. Show the user the list, then create it:

```bash
python ~/.aki-agent/aki.py aki_agent.cli new-project "<workspace>" "<name>" --yes
```

Two commands rather than one on purpose. The user sees exactly what is about
to appear in their own folders before it appears.

## Getting the two answers

**The workspace** — if they did not say, list what exists and ask:

```bash
python ~/.aki-agent/aki.py aki_agent.cli projects
```

Never invent a workspace. If the one they name does not exist the command says so
and lists the real ones; pass that on rather than creating something close to
what they said.

**The name** — use their words. Not a tidied version, not a slug, not a date
prefix they did not ask for. They will be reading this folder name in a file
manager for the next two years, and it should say what they call the thing.

If the name has a character Windows will not allow in a folder name
(`\ / : * ? " < > |`), say so and offer the nearest sensible spelling.

## After it exists

Say what was created in one line, then **put something in it.** A brand new
project with three empty files is not obviously useful; the same project with
what they just told you already written into its notes is.

If they described the work while asking — a deadline, who it is for, what the
first step is — write that into the project's own notes now. Do not ask them
to repeat it.

## What not to do

- **Do not create the folder yourself with `mkdir`.** Use the command. It
  knows the folder names from the user's configuration, and a hand-made one
  where the engine expects something else produces a project that looks fine
  and is invisible to everything else. This is not hypothetical: on
  2026-08-17 an entire workspace was made by hand and every file that should
  have been inside it was missing, with nothing reporting a failure.
- **Do not put your own files into the new project folder.** That is the
  user's shelf. Drafts go in the workspace's `00_Sandbox`. The project's own
  tracking notes are the exception — fill those in. See `revise-document`.
- **Do not create several projects at once because they mentioned several.**
  Confirm the list first — bulk-creating folders someone has to delete one by
  one is a poor first impression.
