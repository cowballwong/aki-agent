---
name: diary
description: Read what is on, and add, move or cancel appointments in the user's Google Calendar. Use when the user types /diary, asks "what's on", "am I free", "book that in", "put that in my calendar", "move that meeting", "cancel Friday", or when a piece of work produces a date they will need to be somewhere for.
user-invocable: true
allowed-tools:
  - Bash
  - Read
---

# The diary — reading it, and changing it

Two different connections, and the difference matters before you promise
anything:

| | what it can do | how it is set up |
|---|---|---|
| **Subscription (ICS)** | read only | an address, two minutes |
| **Google account** | read, add, move, cancel | a one-off Google setup |

A subscription address is a file to download. There is no "write" in that
protocol, so if only a subscription is connected, **say that** rather than
trying and failing — and offer the Google route, which is on the dashboard's
Connections page.

## What is on

```bash
python ~/.aki-agent/aki.py aki_agent.cli agenda --limit 8
```

Google entries are listed first, marked "can be changed", and each carries an
`[event id]`. That id is what the other commands take. Subscription entries
have none, because there is nothing you could do with one.

Read it back as sentences, not as a table dump: *"Two things tomorrow — the
site visit at 10, and a parents' evening at 6."*

## Putting something in

```bash
python ~/.aki-agent/aki.py aki_agent.cli calendar-add "Site visit — Riverside" --start "2026-09-12 14:30" --end "2026-09-12 16:00" --location "Winchester"
```

**Run it without `--yes` first.** It prints exactly what it would put in the
diary and adds nothing. Show that to the user, in your own words, and wait.

Then, and only if they say yes, the same command with `--yes`.

Times are given plainly: `2026-09-12 14:30`. The command deliberately does not
understand "next Tuesday" — you do, and you know which Tuesday they meant, so
work the date out and pass it. A parser guessing at that would be guessing in
the one place nobody would check.

## Moving one

```bash
python ~/.aki-agent/aki.py aki_agent.cli calendar-change <event id> --start "2026-09-12 16:00" --yes
```

Only what you name changes. Everything else — the guests, the description, the
conference link — is left exactly as it was.

## Cancelling one

```bash
python ~/.aki-agent/aki.py aki_agent.cli calendar-cancel <event id> --yes
```

This is the one with no undo, and it is not silent: **anyone invited is told
by Google.** Say that before asking, not after. "Shall I cancel it?" and
"Shall I tell the other four people it is off?" are different questions, and
the second one is what is actually happening.

## The rule that outranks being helpful

Setting up the Google connection is not a standing permission to rearrange
somebody's week. Every add, every move, every cancellation is confirmed with
them first — the same rule sending email follows, for the same reason: it is
visible to other people the moment it happens, and it cannot be taken back
quietly.

If they have already said "book it", that is the confirmation. Do not ask
twice for the same thing.

## When something refuses

- **"Not signed in to Google yet"** — the Google connection is not set up.
  Point them at Connections on the dashboard; do not try to work around it.
- **"Google would not renew the sign-in"** — the permission was withdrawn, or
  the password changed. It needs connecting again; nothing is broken.
- **A subscription that fails to load** — say which calendar and carry on with
  the others. One unreachable feed is not a reason to report no diary at all.
