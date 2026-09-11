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

## 0.48.0 — 2026-09-11 — the session is told, not trusted to ask

A scheduled task sends its result from its own run, hours before the session
that will read the reply exists. So the answer — "yes", "the second one", "do
it" — arrives at a session that never asked anything.

Half of that was already solved and stays: every outbound message, scheduled
work included, is written into the one conversation log, and the persona is
told to read it when a message looks like a fragment. The half that was
missing could not be fixed by writing a firmer instruction.

- **Nothing put it in front of the session.** The prompt hook carried
  dashboard messages and nothing else, so the whole mechanism rested on the
  model choosing to go and look. It now injects what is open and what was
  recently sent into every turn.
- **A log cannot tell two open questions apart.** It does not record which
  answers are outstanding; the approvals queue does, and nothing was reading
  it here. Open questions and drafts now arrive by id, with their options, and
  the block names the command that closes one — an answer that is given to the
  user but never recorded leaves the question open for ever.
- **What was already sent is labelled a log, not a list of jobs.** A session
  handed a list of things it has apparently not done will helpfully do them
  again.

Built on the existing approvals queue rather than a new store. A second list
of "things waiting for the user" would be two answers to one question, which
is the shape this changelog keeps returning to.

---

## 0.47.3 — 2026-09-11 — two things macOS does that nothing here knew about

Both found by running the scheduler on a real Mac for an evening, which is
longer than it had ever run before.

- **A scheduled task could not read the workspace, and said nothing.** A job
  fired exactly on time and died with exit 126: macOS does not let anything
  started by launchd read `Documents`, `Desktop` or `Downloads`, and setup
  used to suggest `~/Documents/Workspace`. So every scheduled task installed
  cleanly, reported success, and would then have failed at every firing for as
  long as it existed. Setup no longer suggests that folder on a Mac, and the
  health check says plainly what it costs anybody who chose it anyway — with
  the two ways out, rather than a refusal.
- **Updating threw a notification per task, every time.** macOS posts
  "Background Items Added" whenever a LaunchAgent is loaded, and repair and
  upgrade both re-registered every task unconditionally, including jobs whose
  definition had not changed by a character. The notification is macOS telling
  somebody that software has arranged to run itself and should stay exactly
  that; what was wrong was doing the thing that triggers it for no reason. An
  install that changes nothing now touches nothing.

---

## 0.47.2 — 2026-09-11 — an update that finishes by itself

0.47.1 fixed what stopped a macOS install. Repairing the machine it was found
on then took three commands pasted into a terminal, which is its own answer to
whether the install procedure was fixed.

- **The update looked everywhere except where the update lands.** A
  marketplace install downloads its new version into Claude Code's plugin
  cache. The search for "a release to upgrade from" covered the running copy,
  Downloads, Documents and Desktop — every place a *zip* arrives, and not that
  one. It now looks there first, and compares versions as numbers so 0.47.10
  is newer than 0.47.9.
- **The upgrade skill fetches the new version itself** rather than asking the
  person to refresh the marketplace by hand first.
- **Repair writes a launcher that was never created.** It used to rewrite one
  only if the file already existed, so an install whose setup stopped early
  could be repaired, upgraded and health-checked for ever without ever
  producing the file to double-click — each step reporting success, because
  each step it knew about had succeeded.

Updating is now `/aki-agent:upgrade`, and that is the whole of it. Being two
halves — a Python engine and a Claude Code plugin — is the package's problem,
not the user's, and every step of the old path could succeed while the next
one was simply never run.

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

## 0.48.1 - 2026-09-11 - the check with no caller

The first release where macOS was run on a real machine by somebody using it,
and it failed in the way the list at the top of this file names third.

`paths.inside_a_protected_folder()` knew the whole problem. macOS does not
let anything started by launchd read `Documents`, `Desktop` or `Downloads`,
so a workspace in one of them means every scheduled task installs, reports
success, and then dies at exit 126 on every firing, silently, for as long as
it exists. The function was written, documented at length, and covered by
tests.

It was called from `doctor`. Nowhere else. Setup did not ask it, and neither
did the thing that creates the tasks - so seven tasks were created on a real
Mac, all seven reported success, and none of them had ever run. The diagnosis
existed and only spoke when somebody already suspected something.

Three changes, in the order they matter:

- **`schedule.install()` refuses** a task whose runner sits in a restricted
  folder. The check directly above it asks whether the runner *exists*, which
  is always true: install runs in a Terminal, and a Terminal can read
  `Documents`. launchd cannot. Same note, same reason, right question.
- **`move-workspace`** moves the folder, records the new location, and
  re-points the schedule and the launcher at it - one command. The advice
  before this was three manual steps ending in "work out which tasks fire",
  which is advice nobody takes. Refuses a restricted target, refuses a
  non-empty one, and moves nothing at all if either applies.
- **Install says so while it is still a choice.** `default_root()` is the
  folder Claude Code was started in, and people start terminals in
  `Documents`. `suggest_root()` already steered away, but it only gets a vote
  when nobody opened a terminal somewhere else. (Superseded by 0.48.3, which
  moves the folder rather than printing a note about it.)

Full Disk Access is the other way out and is not recommended anywhere in this
release. The runner is a bash script, TCC grants to the interpreter, so the
grant is `/bin/bash` reading the entire disk - far more access than the
problem needs, and dropped again on the next major macOS update.

2,003 tests.

---

## 0.48.2 - 2026-09-11 - the repository was not an update route

0.48.1 was pushed to the public repository, and the machine that needed it
could not see it. Not a network problem: `refresh_plugin` re-added the
marketplace after every upgrade pointing at the engine folder inside the
user's own workspace. That is a `directory` source, so
`claude plugin marketplace update aki-agent` -- the one command anybody would
try, and the one this package's own upgrade skill ran first -- re-read the
machine it was already on, found exactly what was already installed, and
reported success.

So every release had to travel as a zip sent by hand, and the published
repository was somewhere to read the code rather than somewhere to get it.
The same shape as the entry above, one layer out: the mechanism worked, and
nothing reached it.

- The marketplace now points at the repository after an upgrade. The local
  folder remains the fallback, taken when adding the remote fails, which is
  what no network or a private copy looks like from here. The upgrade still
  finishes; it just says that the next one will need a file.
- The upgrade skill removes and re-adds the marketplace instead of calling
  `marketplace update`. Any machine upgraded before this release is still
  pointing at itself, and `update` cannot move it.

2,004 tests.

---

## 0.48.3 - 2026-09-11 - not installing there in the first place

0.48.1 printed a note when the folder somebody was installing into was one
macOS restricts, and then installed there anyway. Asked why the install could
not simply avoid `Documents`, there was no good answer: a note in front of a
broken install is still a broken install, and the note scrolls past during a
setup nobody reads twice.

A first install with no explicit `--root` that lands in `Documents`, `Desktop`
or `Downloads` on macOS now goes to `~/Aki-Agent` instead. It says which
folder it refused, why, where it went, and that Claude Code should be opened
there from now on.

This does not bring back the question `default_root()` exists to avoid -- two
of the first three real installs failed because the answer and the folders on
disk disagreed. Nothing is asked. The folder is chosen, recorded and announced
in the same breath, so the config and the disk still cannot disagree.

An explicit `--root` is honoured. Somebody who names a folder has made a
decision, and an install that lands somewhere they did not name and cannot
find is worse than the problem being avoided.

Found while writing it: the redirect was first placed *after* `scaffold.plan()`,
so the plan would have created `Documents` while the message named
`~/Aki-Agent`. Precisely the disagreement above. There is now a test asserting
the plan is built against the folder that gets announced.

2,009 tests. Both new behaviours were checked red before green.

---

## What is still not true

- **macOS is now run, but rarely.** The first real install was 2026-09-11
  and it found four separate faults; see 0.47.1. Treat macOS coverage as thin
  rather than absent, and assume the next one is still there.
- One test fails intermittently and the cause is not known. It is marked as
  such in the file rather than quietly retried.
- The safety gate is a short denylist and fails open, on purpose.
