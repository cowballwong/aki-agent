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

## 0.48.4 - 2026-09-11 - the workspace nobody could see

Reported from a macOS install with two workspaces on disk, `01_Work` and
`02_Family`, one of them still empty. The front page came up titled
"Workspaces" and listed projects. `02_Family` was on no card, in no list, and
reachable from nowhere in the dashboard.

`Scan.by_workspace()` built its groups from the items it had read, so a
workspace holding no projects produced no group and did not exist as far as
anything downstream could tell. A workspace somebody has just created is empty
by definition, which means the workspace they most recently made was always
the one that could not be seen.

The missing card was the smaller half. The front page decides whether it is
the list of workspaces or the list of projects by counting those groups, while
the heading beside it counts the workspaces in the config. Two sources for one
question, disagreeing exactly when one workspace is empty -- hence a page
titled with one thing and filled with the other.

- `Scan` now carries the workspaces the config declares and the schema each
  reads with, and `by_workspace()` returns a group for every one of them,
  ordered by the config. An empty workspace keeps its own schema, because
  there are no items to infer one from and another workspace's would draw the
  wrong columns the moment somebody put a project in it.
- The page's "am I a list of workspaces?" test is now the same question the
  heading asks.
- The Today picker skips the empty groups. An empty workspace belongs on the
  workspace list, where it can be opened and filled; it does not belong in a
  picker of projects as a heading with nothing under it.

2,013 tests, four of them checked red against the code with the fix removed.
One of those four went in asserting that a folder the config does not list
would be shown, which is not what this package does -- `item_dirs()` walks the
configured workspaces and an unlisted folder surfaces through "Refresh from
folders" instead. It now pins the real behaviour, so that ordering from the
config is never quietly turned into filtering by it.

---

## 0.48.5 - 2026-09-11 - launchd hands a job four directories

With the workspace out of `Documents`, the scheduled tasks still did not run.
Different cause, same shape.

`runner.find_claude()` was `shutil.which("claude")` and nothing else.
`shutil.which` reads `PATH`, and a scheduled job does not get the `PATH` a
terminal gets: launchd hands its children `/usr/bin:/bin:/usr/sbin:/sbin`,
while Claude Code's own installer puts `claude` in `~/.local/bin`. So every
task raised `ClaudeNotFound` and died, while the same command typed into a
terminal worked perfectly.

The note directly under that function already said a scheduled run does not
inherit the terminal's environment -- it is why `ANTHROPIC_BASE_URL` is put
back by hand for anyone running a local model. The reasoning was right and
`PATH` was simply never one of the pieces it was applied to.

- `find_claude()` falls back to the places Claude Code is actually installed
  once `PATH` has failed: `~/.local/bin`, Homebrew on both architectures, and
  the usual npm prefixes. Only after `PATH` has failed -- somebody who put a
  particular `claude` on their `PATH` chose it, and a list of guesses must
  never overrule that.
- The launchd plist now sets `EnvironmentVariables/PATH`, so anything a task
  goes on to invoke gets the same directories rather than each caller growing
  its own list of likely locations. Written out in full, because launchd does
  not expand `~` inside a plist value.
- `bin/*.command` and `bin/check.sh` are marked executable in git. They were
  mode 644, so a marketplace install -- which is a clone -- produced scripts
  the system would not run. The zip build had always set the bit, which is
  why this never showed up before the repository became an install route in
  0.48.2.

2,018 tests, three checked red against the code with the fix removed. The two
that pass either way are the guards: that `PATH` still wins when it has an
answer, and that a genuinely missing install still says so.

Not changed, because neither is a fault: scheduled results arriving during
quiet hours are held in `state/held-messages.json` and released afterwards,
and scheduled runs are given Read, Grep and Glob rather than network access.
A task that needs to fetch something needs that decision made deliberately,
not inherited from a bug fix.

---

## 0.48.6 - 2026-09-12 - one list, because two of them drifted within the hour

0.48.5 gave a scheduled job the directories it needs, and shipped that as two
separate lists: a PATH written into the launchd plist, and a list of candidate
locations inside `runner.find_claude()`.

Within the hour a scheduled task ran, finished, and still delivered nothing.
`claude` was found. `bun` was not -- the Claude Code channel plugins run on it,
so the Telegram plugin could not start. `~/.bun/bin` was in neither list,
because adding a directory meant remembering there were two places to add it.

There is now one list, `paths.EXTRA_BIN_DIRS`, read by both. `bun`, deno and
volta are in it alongside the original entries. Adding another is one edit.

Two smaller things fell out of writing it:

- The PATH is built with `as_posix()`. It is read by launchd, which is POSIX
  by definition, while the tests for it run on Windows -- where `str(Path)`
  produces backslashes, and the separator is already the PATH delimiter.
- A test asserts that every directory in the shared list appears in the
  generated plist. The drift that caused this release is silent: nothing
  errors when the two disagree, a scheduled task simply cannot find something.

2,020 tests.

---

## 0.48.7 - 2026-09-12 - a line that says it was held, and what held it

A task ran at 23:50, took 32 seconds, succeeded, and sent nothing. The whole
of the evidence was `(held, not delivered)`. That says something held it. It
does not say what, and it does not say when the thing will arrive, so working
it out meant reading the notifier's rules and the held-message file.

`notify.send()` already returns the reason -- "quiet hours", "the telegram
channel is switched off", "notifications are switched off". It was being
discarded one line before it could be printed. The line now carries it, and
says the message goes out when that reason stops applying.

A hold with no reason recorded still says it was held. The reason is an
improvement, not a precondition, and a hold must never read as a delivery.

2,023 tests.

### Still not fixed

`test_the_schedule_page_renders_its_tasks_once` fails in roughly one full-suite
run in four, and passes alone, in its own module repeatedly, and paired with
every module a bisect implicated. It is a test-isolation problem, not a fault
in the product, and it is written down here rather than quietly left out.

---

## 0.48.8 - 2026-09-12 - the repository was not a signed release

Asked whether somebody who installed from a zip could now just use
`/aki-agent:upgrade`, and checking rather than answering found that nobody
could -- including the zip users, and including the machine being tested that
night.

`make_release.py` signs a zip. Until 0.48.2 a zip was the only way anybody got
this package, so that was the only thing needing a signature. Then the
repository became an install route: `marketplace add` clones it, and `upgrade`
reads that clone out of Claude Code's plugin cache.
`release_trust.verify_package()` looked there for `RELEASE.manifest` and
`RELEASE.sig`, found neither, and returned "this release is not signed".

So the one-command upgrade this package advertises ended at a refusal, and the
only way past was `--allow-unsigned` -- teaching people to wave through exactly
the check the signing exists to make. Measured, not reasoned about: the
verdict was read off the real plugin cache on a real machine.

- The repository carries its own `RELEASE.manifest` and `RELEASE.sig`, and a
  clone now verifies as signed.
- `bin/sign_repo.py` writes them, and refuses if the manifest describes
  anything git does not carry -- a file signed but not cloned makes every
  clone fail verification.
- `tests/test_the_repo_is_signed.py` fails when the signature and the files
  disagree. A manifest is a list of hashes, so a forgotten re-sign does not
  read as "unsigned", it reads as TAMPERED WITH: a worse failure, and a much
  more alarming one. It skips in a development checkout, which carries no
  manifest.

Signing is now the last step before a commit, after the version, the changelog
and the tests. The test above is what catches it when it is not.

2,026 tests.

---

## 0.49.1 - 2026-09-13 - one line to change the model

Looking at the launcher the package writes, a user asked two things: does it
really need to be that long, and could Ollama users be given one line to edit
to switch to another model?

Every command in it was needed. The prose around them was not: about a third
of the file was the history of why each line exists, written into the one file
a student opens to change something. The reasons now live in `launcher.py`,
where the people who need them read them. Windows 76 lines to 52, macOS 65 to
41, and not one command removed.

- **A settings block at the top.** For an Ollama or custom-endpoint install,
  `set AKI_MODEL=qwen3.5` (Windows) or `AKI_MODEL="qwen3.5"` (macOS), with the
  hint `Any name from: ollama list`, above a line that says there is no need to
  edit below it. The `claude` command uses the variable, not a literal, so
  there is no second copy of the name to fall out of step. An ordinary install
  gets no block and no `--model`, exactly as before.
- **The line is the answer, not a copy of it.** An edit that only the
  double-click honoured would be worse than no line at all: the night's
  scheduled work would go on running the old model out of
  `state/backend.json`, and the next repair or upgrade would write the old
  name back over the edit. `backend.stored()` now reads the model from the
  launcher's settings line when there is one, so scheduled tasks, `doctor` and
  a regenerated launcher all follow it.
- **A release that could not be installed, fixed on the way out.** Since the
  repo started carrying its own `RELEASE.manifest` and `RELEASE.sig`, the build
  copied them into the zip, hashed them into the zip's manifest, and wrote a
  second pair on top. The verifier ignores those two names, so the unzipped
  package failed with "missing: RELEASE.manifest" and `upgrade --from` would
  refuse it. 0.49.0 was built the same way. The old test asked whether the zip
  *carried* a signature; the new one unzips it and runs the real check.
- `tests/test_model_line.py` holds all of that on both platforms: one line
  near the top, scheduled work uses an edited line, a rewrite keeps it, an
  ordinary install has none, and the file stays mostly commands.

## 0.49.0 - 2026-09-12 - found out at the launcher

Asked what actually goes wrong most often, a user named two things: the
Telegram bot token and chat id are not installed correctly, and nobody finds
out until the install is finished and the launcher is opened; and second, the
dashboard, found out the same way.

Both were true, and both had the same cause. `doctor` had twenty-five checks
and not one of them was about messaging, while the dashboard was covered by
`check_launcher` -- which asks whether there is a file to double-click and
whether the machine may execute it. Proxies. An import error inside `app.py`,
a template that will not render, a token revoked last week: every one of those
passed, and the person found out when they opened the launcher, days later,
with nobody around who could fix it.

The same file already had the answer in it. `check_workspace_names` does not
ask whether the folder exists; it runs the lookup and reads the number back,
because the first real install wrote workspace names that matched nothing and
the dashboard came up blank with no error anywhere. That lesson had been
learned once and not carried across.

- **`check_messaging`** asks Telegram whether the saved token is real, and
  names the bot it belongs to. `getMe` was already in the package for the
  dashboard's chat box; it had simply never been asked at diagnosis time.
- **`check_dashboard_serves`** builds the dashboard and requests its first
  page through Flask's test client -- the whole application, imports,
  configuration, routing and templates, without binding a port or fighting
  whatever already holds 4321.
- **`cli check-messaging`** sends a real message. This is separate on purpose:
  `getMe` proves the token and cannot prove the recipient, because it answers
  perfectly for a token whose chat id belongs to somebody else. The only thing
  that proves a chat id is a phone buzzing, so it is the one diagnosis with a
  side effect, and it happens when somebody asks for it, at the end of an
  install, never on a timer. Setup now runs it and waits to be told it
  arrived.

Verified on a second machine, which is where the first version of
`check_messaging` was caught being wrong. On a test Mac the token check hit
`CERTIFICATE_VERIFY_FAILED` -- something re-signing TLS in the middle -- and
the check said "if this machine is offline, ignore it." The machine was not
offline, and the advice pointed away from the fault, which is the one thing a
line in `doctor` must never do. A certificate failure now says so and names
the three things that cause it. The same file had just split the dashboard's
two failures apart for exactly this reason; the sibling case a few lines
below went unnoticed until it ran somewhere else.

Two things that check out as costs rather than faults: the dashboard check
takes about 16 seconds on a 2019 Intel Mac, because it genuinely builds the
dashboard, and `doctor` over a bare SSH shell reports Claude Code as missing
when it is installed and simply not on that shell's `PATH`.

And the release route, which had quietly stopped working.

`release_trust` and `make_release` each kept a list of what to leave out, and
were allowed to disagree. `.gitignore` names `desktop.ini`; `make_release`
named it; the signer did not. `bin/sign_repo.py` signs what the signer's list
allows and then refuses if anything it signed is absent from git -- so six
stray files nobody wrote, every one already ignored, made a signed 0.49.0
impossible. The two lists are now one, `make_release` imports it, and a test
holds them together. The secret-bearing names stay out of the signer's list
deliberately: a stray `.env` in a checkout must be signed, so that signing
refuses rather than passing over it in silence.

And the guard the same conversation turned up.

`INSTALL.md` ends: "Everything here is reversible except one thing: running a
first-time setup over a configuration that already exists." Nothing enforced
it. The `setup` skill writes `config.yaml` with the `Write` tool, has no check
of its own, and its description says it triggers on "start again" -- so
somebody typing `/aki-agent:setup`, who has never opened `INSTALL.md`, got
their configuration replaced with no copy kept and nothing said. The assistant
still started. It simply no longer knew who they were.

A warning in a document the reader will not open is not a guard.

- **`config_guard`**, a `PreToolUse` hook on `Write`. It keeps a copy first --
  that part happens whether or not anybody reads what comes next, and it is
  what turns the irreversible thing into a reversible one. Then it refuses
  once, naming the copy and giving the assistant the question to ask. A second
  attempt at the same file goes through, because a guard that cannot be got
  past on purpose is a guard that gets switched off.
- **`check_a_configuration_was_replaced`** reports the copies in `doctor`, for
  the person who has just noticed their assistant has forgotten them.

One thing the tests caught rather than review: the first version of the copy
used a second-resolution timestamp for the filename, and the retry lands
inside the same second -- so the second copy silently replaced the first, and
the file being protected was the one that got lost.

## 0.48.11 - 2026-09-12 - a user folder with a space in it

Reported within hours of the release before it, by somebody whose Windows
account name has a space in it. They double-clicked the launcher and got one
line back:

    'C:\Users\Anna' is not recognized as an internal or external command

The launcher had carried it since the first commit. Two lines quoted a path
twice over -- `""%~f0""` and `""...dashboard.vbs""` -- and `start` has already
taken the leading empty `""` as the window title, so the second pair collapses
to no quotes at all. Whatever receives the path is handed everything up to the
first space, and a folder name with a space in it is cut in half.

Every machine this package has been developed or tested on has a user folder
with no space in it. That is the whole reason it lived this long: the collapse
is real on all of them and invisible on all of them.

- `start "" wt cmd /c "%~f0"` -- one pair. This was the visible failure: the
  launcher died before a single line of it ran.
- `start "" wscript.exe //B //Nologo "...\dashboard.vbs"` -- one pair. This
  half failed *silently*, because `//B` shows no dialog. On any such machine
  the dashboard has never opened, and nothing anywhere said so.
- `test_a_user_folder_with_a_space_in_it_still_starts` renders the launcher
  against a path containing a space and counts the quotes on every line that
  names a path, so the next line to name one is checked too.

Verified by running the real generated launcher out of a folder whose name
contains a space: Windows Terminal opens, the session starts, the dashboard
starts. The macOS launcher was already correct and is unchanged.

Anyone already installed gets the corrected file from `upgrade` or from
`doctor`, both of which rewrite the launcher while preserving the choices in
it. Somebody who cannot start at all can edit the two lines by hand and delete
the doubled quotes.

2,049 tests.

---

## What is still not true

- **macOS is now run, but rarely.** The first real install was 2026-09-11
  and it found four separate faults; see 0.47.1. Treat macOS coverage as thin
  rather than absent, and assume the next one is still there.
- One test fails intermittently and the cause is not known. It is marked as
  such in the file rather than quietly retried.
- The safety gate is a short denylist and fails open, on purpose.
