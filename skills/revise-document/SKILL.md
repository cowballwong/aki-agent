---
name: revise-document
description: Change one of the user's own documents safely — draft the new version in the workspace sandbox, show what differs, and only move it into their project folder once they approve. Use when the user asks to edit, rewrite, update, tidy, translate or reformat a file that lives in one of their project folders, or says "change my …" about anything they wrote.
user-invocable: true
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Bash
---

# Revise a document — draft, show, then ask

This is the skill that demonstrates the one rule the whole workspace is built
around, so work it exactly as written even when a change looks trivial.

**You draft in the workspace's `00_Sandbox`. Nothing enters one of the
user's project folders without them approving that specific change.**

## The four steps

### 1. Find the document, and say which one you found

```bash
python ~/.aki-agent/aki.py aki_agent.cli projects
```

If more than one file could be the one they meant, list the candidates and ask
which. Guessing wrong here means the rest of the work is wasted, and a
one-line question costs nothing.

Read the file before proposing anything. Never revise a document you have not
read — including when the user says "just fix the dates" and it sounds like
you would not need to.

### 2. Draft the new version in the sandbox

Write to `<workspace>/00_Sandbox/`, keeping the original filename and adding
nothing to it except, if a draft of the same file is already there, a short
suffix so you do not overwrite your own earlier attempt without noticing.

The original file is not touched at this stage. Not renamed, not backed up,
not opened for writing.

### 3. Show what changed, in their language

State it as **differences**, not as a summary of the new version:

- what you changed, and why, in one line each
- anything you were unsure about, marked as such
- anything you deliberately left alone

If the change is long, show the two or three passages that matter rather than
the whole thing. A wall of text gets approved without being read, and an
approval nobody read is not an approval.

### 4. Wait

**Do not move the file.** Say plainly that the draft is in the sandbox and
that you will move it across when they say so.

If they say yes, move it into the project folder, replacing the original, and tell
them it is done. If they say no, leave the draft where it is — it costs
nothing and they may want it later.

If they do not answer at all, nothing has been approved. Silence is not
consent, and neither is "sounds good" said about a different question.

## The exceptions, which are narrower than they look

There are none for the user's own files. Not "it was obviously wrong". Not "they
asked me to make the change last week". Not "it is only whitespace". The rule
is worth more than any single edit it costs.

Two things are **not** covered by the rule, so do not go asking about them:

- **The sandbox.** Yours entirely. Overwrite, delete, make a mess.
- **The project's own notes** — `state.md`, `actions.md` and the rest.
  Keeping those current is the job, not an intrusion.

## Why it works this way

An assistant that can edit anything is one misunderstanding away from
overwriting something that mattered, and the person usually finds out days
later, with no way to tell what the file used to say.

Drafting in the open makes the mistake visible while it is still cheap. That
is the entire trade: a few seconds of the user's attention buys a guarantee
that nothing they own changed without them seeing it.
