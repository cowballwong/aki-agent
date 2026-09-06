---
name: already-have-an-agent
description: Explain the three ways somebody who already built their own assistant can end up with this one — side by side, import, or integrate — and help them choose. Use when the user says they already have an agent, asks whether they must give up their own setup, asks how to combine the two, or types /already-have-an-agent.
user-invocable: true
allowed-tools:
  - Read
  - Bash
---

# They already have an assistant

The full explanation is **`CHOOSING.md`** at the root of this package. **Read
it completely before saying anything.** What follows is how to run the
conversation, not a summary you can work from instead.

## Lead with the option nobody thinks of

They asked how to combine the two, so they are picturing a merge. Say first
that **side by side is free**: this installs into its own folder, touches
nothing of theirs, and their assistant keeps working. Most people should start
there and decide in a month.

Saying that first costs you a decision they might have made badly, and costs
them nothing.

## Then show all three

```bash
python ~/.aki-agent/aki.py aki_agent.cli screen menu \
  --title "<in their language: you already have an assistant — which way?>" \
  --option "<keep both, change nothing (recommended to start)>" \
  --option "<this one becomes the base, my material moves in>" \
  --option "<mine stays the base, bring some of this over to it>" \
  --option "<tell me more first>" \
  --footer "<reply with a number>"
```

Then, for whichever they lean towards, give them the three facts
`CHOOSING.md` gives for each: **who it is for, what it costs, and how hard it
is to get back out.** The third is the one people want and do not know to ask.

## The question that decides it

If they are stuck, ask the one from `CHOOSING.md`:

> If you lost the folder your assistant lives in tomorrow, what would you
> actually miss — the things it knows, or the way it works?

*The things it knows* → import. *The way it works* → integrate. *Don't know*
→ side by side, and no embarrassment about it.

## Where each one goes

| They chose | You do |
|---|---|
| Side by side | Nothing. Carry on with `/aki-agent:setup` if they have not run it |
| Import | `/import-my-agent` |
| Integrate | Read `INTEGRATE.md` in full, then `/integrate` |

## Do not sell

They built something. It works for them. Two of these three paths end with
them maintaining less, and one ends with them maintaining more — say which is
which honestly, including when the honest answer is that their own structure
suits their work better than this package will.

An assistant that talks somebody out of a setup that was serving them has not
helped them, whatever the install count says.
