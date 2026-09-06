---
name: ask-me
description: Put a decision in front of the user and pick it up later — a draft to approve, a question you cannot settle yourself. Use when you need a yes/no or a choice before acting, when the user is away from the machine, when you are told to check before sending or changing something, or when the user types /ask-me to see what is waiting.
user-invocable: true
allowed-tools:
  - Bash
  - Read
---

# Asking, when the answer has to wait

Most questions are asked in conversation and answered in the next sentence.
This is for the ones that cannot be: the user has walked away, the work runs
on a schedule at eight in the morning, or the thing you are about to do should
not happen until a person has actually looked at it.

Something asked this way survives the session. It appears on the dashboard and
on their phone, and it is still there tomorrow.

## Ask

```bash
python ~/.aki-agent/aki.py aki_agent.cli ask "Send the tender letter?" \
  --kind draft --body "<the draft itself>" --task email --context tender
```

- `--kind draft` when you are showing something you have written and want a
  yes; `--kind question` (the default) for a choice.
- `--body` is what they are actually judging. Put the whole draft there, not a
  summary of it — approving something you have only described is not approval.
- `--task` names what to learn from the decision (`email`, `report`). Their
  verdict feeds the card you read before drafting the next one of those.
- `--context` ties several related asks together, so answering or dismissing
  one clears its siblings instead of leaving ghosts behind.
- `--option key:Label` — repeat it to offer your own answers. Without it, a
  draft offers go-ahead / change / leave, and a question offers yes / no.

**Write the options as the user would say them**, not as a system would label
them. "Send it", "Not yet", "Rewrite it shorter" — never "confirm", "abort".

## See what is waiting

```bash
python ~/.aki-agent/aki.py aki_agent.cli waiting
```

Do this at the start of a session, and whenever the user says something that
sounds like an answer to a question they cannot see. They will often reply to
a question the *previous* session asked — treat "yes, go ahead" as an answer
to whatever is open, not to whatever you last said.

## Answer on their behalf when they tell you in conversation

```bash
python ~/.aki-agent/aki.py aki_agent.cli answer <id> yes
python ~/.aki-agent/aki.py aki_agent.cli answer <id> --text "make it shorter first"
```

Record it even when they told you directly in chat. An item left open reappears
on their phone tonight, and being asked again about something already settled
is the fastest way to make someone stop trusting the queue.

## The rules that make this worth having

**Ask before doing, not after.** An approval that arrives after the email has
gone is not an approval, it is a notification.

**One ask, one decision.** Do not bundle three unrelated things into a single
question so the user has to answer all of them at once, or none.

**If nothing is waiting, say so and stop.** Do not invent a question to fill
the queue.

**Never treat silence as a yes.** An item nobody answered stays open. That is
the whole point of it having a status.
