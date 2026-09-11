# Changelog

This repository starts with one commit. The three weeks of development before
it happened in a private repository whose history carries the author's family,
home town and employer in its sample data — removed from the files, but a
`git log -S` away in the commits. Squashing was the only way to be certain
none of it travelled, and certainty was worth more than the archaeology.

What the archaeology was worth is written down here instead. Not a list of
versions: a list of the things that turned out to be true, in the order they
were learned, because most of them were learned by being wrong first.

---

## The thread that runs through all of it

**A mechanism that works and that nothing reaches.**

Nearly every release below fixed at least one of these, and the same shape
kept coming back in new places:

- a switch on a page, wired to nothing
- a setting read by the code and writable from nowhere
- a function that did the work, with no caller
- a failure that reported success
- a sentence in the interface that the code did not keep

None of these raise anything. None of them fail a test that was written by
the same person who wrote the mistake. They are found by asking a different
question — *what reads this?* — and asking it mechanically.

---

## 0.29.0 — 2026-08-23 — the first audit

Written over some weeks, then read properly for the first time. The reading
found more than the writing had: four ways a machine could be taken over, a
dead install that reported itself healthy, a folder watch that did not watch
the folder, "drafts only" that did not mean it, held messages that were
promised in the README and never delivered, and — grouped as its own class —
nine controls that were drawn and connected to nothing.

The lesson kept from it: **the tests were all written by the author**, so
they only ever checked what he had thought of. Every headline finding was
invisible to them.

## 0.30.x — 2026-08-24 — search, and the machine disagreeing with the tests

Search across what had been said, and noticing what keeps being asked. Then
three defects the tests passed and the actual machine did not — including a
rename a virus scanner can lose you, and a bot token printed back into a
terminal.

## 0.31.x — the line between what is yours and what is the assistant's

Said out loud rather than assumed, and enforced: a sandbox it writes in
freely, project folders it does not touch without being asked.

Also the first evidence for a rule this project now follows everywhere: a
prose instruction to a model needs an **example**, not more adjectives. The
run-on sentence rule was rewritten three times before it was given one.

## 0.32.0–0.38.0 — 2026-08-24 to 2026-08-28 — the dashboard grows a door

A PIN, then the realisation that six digits was never the part that mattered
and a throttle behind it was. Then remote access, added as **one named
exception** to the host guard rather than as a hole in it: the user declares
the single hostname their tunnel hands out, and nothing else is answered,
because trusting a forwarding header is the hole itself.

The dashboard's route surface was pinned to a fixture in the same period, so
that splitting a 3,000-line file could be *proved* not to have changed
anything rather than hoped.

## 0.39.0–0.43.x — 2026-09-01 to 2026-09-04 — clones, and a week of channels

Several agents, one memory, one conversation. That made a race reachable that
had always existed, so the working state got a lock.

Then a long, ugly run of releases — 0.40.1 through 0.43.1 — spent learning how
a Claude Code channel actually works. Almost every one of those numbers is a
bug found by running it, not by reading it. The one worth remembering:
**another assistant's session was taking this dashboard's messages**, because
hooks installed by one agent fire in every session on the machine.

0.44.1 is the other one: **the test suite was writing into the assistant
somebody was using.**

## 0.45.0 — 2026-09-05 — the dashboard rework

Five pages rebuilt. Several things quietly wrong, found while rebuilding.

## 0.46.0 — 2026-09-05 — the second audit, by a different model

A Fable 5.1 agent audited the rework; the findings were verified item by item
against the code before anything was changed, and several of its file and line
references turned out to be wrong even where the substance held. One of its
recommended fixes would have introduced a fresh bug and was caught by
rendering it first.

The dominant finding was not broken code. It was **interfaces claiming things
the code did not do** — including four claims about privacy and consent:

- "the answer goes no further than this computer", of a location that was sent
  to two web services
- "never written to a file here", of a password that falls back to a file when
  there is no keyring
- "every change is confirmed with you first", where no prompt existed in code
- a forgotten PIN "written to your Desktop", which in fact goes to the phone

Nine sentences corrected to say what the code does. Two real gaps closed: a
fresh install had no notification switch at all, and working hours ran on the
defaults because nothing could set them.

The audit did not finish — it hit an account limit — and two of its lanes died
before reporting. That is what 0.47.0 went back for.

## 0.47.0 — 2026-09-06 — the lanes that died, and the upgrade path

**Releases are signed.** `upgrade` used to install whichever
`Aki-Agent-Beta-*` zip was newest in Downloads, Documents or Desktop, checking
only that its shape looked right. Getting a file with that name onto somebody's
machine was the whole attack, and it landed the next time they pressed
upgrade. Now: a signed manifest of every file, Ed25519, verified before the
manifest is believed. See [SECURITY.md](SECURITY.md).

**The PIN could be reset without limit.** `/login/forgot` takes no password —
it cannot — and had no throttle, so pressing it in a loop locked the owner out
permanently while their phone filled with superseded PINs.

**The plaintext credential file was not protected on Windows.** It was guarded
by `os.chmod(0o600)`, beside a comment admitting chmod is ignored there.

**The install question asked the opposite of what it meant.** Somebody who
wanted their existing assistant brought *into* this one was offered the
reverse, because the question said "merge" — a word that names an operation
and not a direction. Three options now, each named by where things end up.

**A workflow could hang the dashboard**, having no timeout, and reported
failures with an empty message.

**A mailbox could not be finished**: the handler read an `smtp_host` box that
did not exist, and neither port could be set from anywhere at all.

**A clone permission granted nothing.** `may_write_shared` was a field, a
registry column, an argument and a form read — and nothing anywhere consulted
it. Removed rather than wired up: a flag that records an intention is worse
than no flag, because the next interface to show it would tell somebody their
clone is restricted, on the authority of a value nothing reads.

Held messages now go out when quiet hours end rather than at 08:05.

1,947 tests. Every fix in this release was checked red before it was checked
green, and two of the new tests were rewritten after passing against code with
the fix removed.

---

## 0.47.1 — 2026-09-11 — the first real macOS install

The changelog said macOS had been written, reviewed and never run. It was run.
Four things stopped it, none of them loudly, and all four were on the path any
Mac user takes on their first day.

- **Apple ships 3.9.6 as `python3`, and this package needs 3.10.** The
  bootstrap refused it and said to install a current Python — to people who
  may already have one, somewhere it had not looked. It now searches, naming
  Homebrew's folder and the python.org framework outright rather than hoping
  they are on PATH, because a `.command` opened from Finder starts with a
  minimal one and a non-interactive bash never reads the profile the installer
  wrote to. Guarded against forking for ever, and the file still parses under
  3.9 so its last-resort message can still be printed.
- **macOS has no bare `python`.** Every generated line that began with that
  word — the launcher's own preflight, every `fix:` line the health check
  prints, the inbox commands written into a new workspace — was a line a Mac
  user could not run. One function now answers the question for both
  platforms.
- **`bin/dashboard.command` arrived without its executable bit.** The launcher
  starts it in the background, so the denial went to a job nobody reads: the
  assistant opened perfectly and simply had no dashboard. Adoption and repair
  now restore the bit instead of trusting the mode they were handed.
- **A launcher that was never written was nobody's problem.** Every existing
  check read a launcher only `if launcher_file.exists()`, so a setup that
  stopped before its last step passed them all. The health check now looks for
  the file itself, and on macOS checks that it can be run.

The shape is the one this changelog keeps returning to: not a mechanism that
was wrong, but a failure with nothing watching it. Four of the seventeen new
tests exist only to hold the rule that a Windows-only fix is not a finished
fix.

---

## What is still not true

- **macOS is now run, but rarely.** The first real install was 2026-09-11
  and it found four separate faults; see 0.47.1. Treat macOS coverage as thin
  rather than absent, and assume the next one is still there.
- One test fails intermittently and the cause is not known. It is marked as
  such in the file rather than quietly retried.
- The safety gate is a short denylist and fails open, on purpose.
