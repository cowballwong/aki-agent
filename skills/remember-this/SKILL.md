---
name: remember-this
description: Write down something that should stay true between sessions — a preference, a decision, a fact about a person or a project, how the user likes something done. Use when the user says remember this, note that, for future reference, don't forget, from now on, or states a standing preference in passing.
user-invocable: true
allowed-tools:
  - Read
  - Bash
---

# Remember this

```bash
python ~/.aki-agent/aki.py aki_agent.cli remember "<one line>" --body "<the detail, and why>"
```

One fact per file, on purpose: each can be reviewed, corrected or deleted on
its own, and a wrong one can be removed without rewriting anything else.

## What makes a fact worth keeping

Keep it if it will **still be true next month** and would change what you do:

- how they like something done, and why
- a decision, with the reasoning that produced it
- a standing constraint — a deadline, a rule, a person's preference
- something about a person that affects how to work with them

Do not keep:

- **what happened today.** That is the daily log — use `log`, not `remember`.
- **anything already in a file.** A fact that duplicates the project's own
  notes will go stale in one of the two places and then contradict itself.
- **a guess.** If you inferred it rather than being told it, either ask, or
  write it down as the inference it is: *"seems to prefer X — inferred from
  two occasions, not confirmed."*
- **a credential.** Ever. Not even partially. If they paste one, tell them it
  belongs in the credential store and do not repeat it back.

## Write the *why*, not just the *what*

"Prefers 09:00 meetings" ages into a rule nobody dares change.
"Prefers 09:00 meetings — school run at 08:15, so anything earlier is a
scramble" can be re-decided when the reason stops applying.

The reason is the part that stays useful. Facts without reasons become
superstitions.

## Before writing, check it is not already there

```bash
python ~/.aki-agent/aki.py aki_agent.cli search "<the gist>"
```

If something close comes back, **update that one** rather than adding a
second: pass the same wording so it replaces the old file. Two facts that
half-agree are worse than either alone, because the next session has no way
to tell which one is current.

## Say what you wrote

Read the one-line summary back. It is the user's only chance to catch you
having recorded the wrong thing — and the whole point is that this one
outlives the conversation.
