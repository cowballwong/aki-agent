---
name: session-state
description: Save or read what the assistant is in the middle of, and say whether restarting it right now would be safe. Use when the user types /session-state, asks "where were we", "what were you doing", "save where we are", "can I restart you", or when a session is about to end or be restarted.
user-invocable: true
allowed-tools:
  - Bash
  - Read
---

# Session state — the thread between one session and the next

A session ends. The next one starts knowing nothing. Everything in between is
carried by one small file: the **handoff**, written every twenty minutes by
the checkpoint task, holding what is open, what we are waiting on, and what
was touched recently.

This skill is the manual door to it — for the moments the schedule does not
cover, which are exactly the moments that matter: just before a restart, at
the end of a long piece of work, when someone asks "where were we".

## Where were we

```bash
python ~/.aki-agent/aki.py aki_agent.cli state
```

Read it back as a couple of sentences, not as a list dump: *"Last saved at
14:20 — you were mid-way through the tender letter, waiting on the structural
engineer, and the last thing touched was the drawing register."*

Two rules when you report it:

- **It describes a moment that has passed.** If it names a file or a decision,
  check that it is still true before acting on it. Say "the handoff says…",
  not "you are…".
- **Never redo something it records as finished.** That is the specific
  failure a handoff exists to prevent.

If it says nothing has been saved, the checkpoint is not running. Check with
`python ~/.aki-agent/aki.py aki_agent.cli schedule-status`, and offer to install the schedule
if it is empty.

## Save where we are, now

```bash
python ~/.aki-agent/aki.py aki_agent.cli checkpoint
```

Worth doing before a restart, before closing a long session, or at the end of
a real piece of work. It costs nothing and it is the difference between coming
back informed and coming back blind.

## Is it safe to restart

```bash
python ~/.aki-agent/aki.py aki_agent.cli recycle-check
```

Idle time decides this, and nothing else. A session that has grown large but
is mid-task must not be restarted — interrupting real work to tidy a number
destroys the work and improves nothing.

So: if it says do not restart, do not argue with it, and do not restart
anyway because the session feels big. Say what it said and why, and offer to
checkpoint instead.

If it says restarting is safe, checkpoint **first**, then restart. In that
order, always — the state must be on disk before anything stops.

## What not to do

Do not present a restart as routine housekeeping the user need not think
about. It ends whatever they were in the middle of. Ask, wait for an answer,
and if none comes, nothing has been approved.
