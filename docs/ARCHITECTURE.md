# Aki Agent — architecture, layer by layer

Written 2026-08-28 against **version 0.37.0** (`pyproject.toml`), latest build
`_release/Aki-Agent-Beta-20260827-002.zip`.

**33,187 lines of Python across 73 modules**, plus 69 test files, 21 slash-skills,
95 library skills, 10 specialists and 3 panels.

> ⚠️ `docs/STATUS.md` still says **0.10.1, updated 2026-08-20**. It is 27 minor
> versions behind and should not be trusted for "what is built". This file was
> written from the code itself, not from STATUS.md.

---

## How to read this

Layers are ordered by **what depends on what**. Layer 0 has no internal
dependencies; each layer above may use the ones below it. Nothing below reaches
up. If a change breaks that direction, it is the change that is wrong.

Line counts are given because they tell you where the weight actually sits.

---

## Layer 0 — Ground: who am I, where am I 身份與地面

Everything else asks these four modules and does not guess.

| Module | Lines | What it settles |
|---|---:|---|
| `schema.py` | 359 | The declarative item schema. Its own docstring calls it *"the most important file in the package"* |
| `config.py` | 1,239 | The one configuration object. Every identity and every path comes from here |
| `paths.py` | 331 | Where things live, on Windows and macOS both |
| `situation.py` | 217 | Which of the three installs this actually is |

**The rule this layer exists to enforce:** no profession word may appear in the
engine's executable code. There is a vocabulary canary test that fails the build
if one does. Architecture, construction, one firm's way of working — none of it is in the engine.
It arrives from configuration.

---

## Layer 1 — Primitives: disk, secrets, hard stops 底層原語

| Module | Lines | What it settles |
|---|---:|---|
| `atomic.py` | 530 | Build the replacement, then swap. One locking mechanism, same on both platforms |
| `secrets.py` | 492 | Asked for at install, stored by the OS credential store, never in the repo |
| `safety_gate.py` | 218 | A hard stop in front of commands that cannot be undone |
| `dashboard_auth.py` | 209 | A PIN on the dashboard, *and an honest account of what it is for* |

---

## Layer 2 — State: what the agent knows 狀態層

Eleven modules, each owning one kind of durable fact. They are separate on
purpose: they differ in how often they are overwritten and how long they live.

| Module | Lines | Holds |
|---|---:|---|
| `memory.py` | 572 | Three tiers of memory, kept apart deliberately |
| `conversations.py` | 378 | Search over what you and the assistant actually said |
| `conversation.py` | 208 | One conversation, visible from everywhere |
| `events.py` | 281 | The event bus — one file every subsystem writes, the dashboard reads |
| `knowledge.py` | 213 | Documents and links the assistant should know about |
| `house_rules.py` | 230 | The user's standing instructions |
| `traces.py` | 221 | Learning from the user's verdicts, **without sending anything anywhere** |
| `steps.py` | 185 | Watching the assistant work, rather than reading its diary afterwards |
| `task_runs.py` | 153 | What happened the last time each scheduled task ran |
| `upgrade_log.py` | 155 | Every upgrade, recorded whether it worked or not |
| `favourites.py` | 161 | The handful of projects you actually look at |

---

## Layer 3 — Spine: the engine and its session 引擎與會期

| Module | Lines | Responsibility |
|---|---:|---|
| `engine.py` | 983 | Stop depending on the folder it was unzipped in |
| `session.py` | 379 | Start, check, safely restart |
| `guard.py` | 535 | Watch a long session, decide when it may be restarted |
| `recycle.py` | 262 | Actually perform the recycle — *"the part that was missing"* |
| `runner.py` | 264 | Run with nobody sitting there |
| `backend.py` | 207 | Which brain it is talking to, and how to reach it again |
| `sentinel.py` | 441 | The check that runs **before something is believed** |

`sentinel.py` is the one to understand. It is the anti-self-deception layer: the
agent does not get to report success on its own say-so.

---

## Layer 4 — Work: scheduling and the day 工作與排程

| Module | Lines | Responsibility |
|---|---:|---|
| `schedule.py` | 1,470 | One definition, two operating systems (Task Scheduler / launchd) |
| `tasks.py` | 560 | Running one scheduled task — what the scheduler actually calls |
| `today.py` | 897 | Everything known about today, gathered in one place |
| `quiet.py` | 386 | Named quiet windows, and which task obeys which |
| `me_time.py` | 266 | Away from the desk, but not out of touch |

---

## Layer 5 — Outside world: mail, calendar, files, phone 對外連接

| Module | Lines | Reaches |
|---|---:|---|
| `connectors/mail.py` | 472 | Mail, without a developer account |
| `connectors/google_calendar.py` | 470 | Writing a Google Calendar — add, move, cancel |
| `connectors/calendars.py` | 318 | Calendars through the one door every service leaves open: **ICS** |
| `connectors/files.py` | 277 | Cloud storage the easy way: the folder that is already there |
| `calendar_seam.py` | 463 | One calendar, however many places it actually lives |
| `channels.py` | 360 | Ways of reaching the user, and how to add another |
| `notify.py` | 345 | **The notification gate — everything the assistant says goes through here** |
| `telegram_setup.py` | 391 | Connecting to the phone |
| `telegram_chat.py` | 579 | The dashboard's chat box, on the real conversation |
| `inbox.py` | 134 | The assistant's side of the conversation mirror |
| `apis.py` | 545 | External tools it can be given keys for |
| `mcp.py` | 150 | MCP servers: what is connected, adding one without breaking anything |

The design choice worth naming: connectors reach services through **the boring
public door** (ICS, a synced folder, IMAP) rather than through per-service OAuth
apps. That is why a student can install this without registering as a developer.

---

## Layer 6 — Seams: the swappable parts 可換件

| Module | Lines | Role |
|---|---:|---|
| `seams.py` | 300 | The one registry every swappable part reports into |
| `plugins.py` | 503 | Third-party folders that add providers **without editing this package** |
| `inspect_report.py` | 303 | What is actually loaded right now (`aki inspect`) |

**Currently only two seams are wired:** `Registry("calendar")` in
`calendar_seam.py` and `Registry("channel")` in `channels.py`. The mechanism is
general; the adoption is not finished. Mail, files and backend are obvious next
candidates and are *not* seams yet.

---

## Layer 7 — Capability library: what it can be taught 能力庫

| Module | Lines | Role |
|---|---:|---|
| `library.py` | 449 | The skills and specialists that ship in the box |
| `skills_store.py` | 299 | Skills the **user** creates |
| `specialists.py` | 377 | Sending deep work to a specialist instead of one head doing everything |
| `skill_ideas.py` | 244 | Noticing what you keep asking for, and offering to make it a skill |
| `panels.py` | 750 | A workspace's own screen, **declared rather than coded** |
| `semantic.py` | 265 | Meaning-matching — **off unless somebody turns it on** |

On disk:
- `library/skills/` — **95** shipped skills
- `library/specialists/` — 10 (proofreader, risk-spotter, regulation-reader, numbers-checker, researcher, second-opinion, summariser, meeting-prep, document-reviewer, data-extractor)
- `library/panels/` — 3 (cost-position, next-dates, programme-gantt)
- `skills/` — **21** slash-skills, the user-facing verbs (`setup`, `doctor`, `brief-me`, `ask-me`, `find`, `diary`, `remember-this`, `new-project`, `new-specialist`, `add-abilities`, `connect-telegram`, `import-my-agent`, `integrate`, `check`, `revise-document`, `session-state`, `uninstall`, …)

---

## Layer 8 — The user's workspace 工作區

| Module | Lines | Role |
|---|---:|---|
| `scaffold.py` | 1,077 | Building the workspace to start from |
| `workspace.py` | 305 | Reading it back off disk |
| `folders.py` | 240 | Walking the machine's folders so nobody types a path from memory |
| `importer.py` | 248 | Reading an assistant somebody already built, so it can move here |
| `local_changes.py` | 204 | Noticing somebody edited the engine, **before an upgrade replaces it** |
| `retire.py` | 127 | Removing a workspace or project **without ever destroying work** |

---

## Layer 9 — Surfaces: what a person touches 介面

**CLI — `cli.py`, 2,687 lines.** One entry point, so the skills have something to
call. Around 40 commands, including: `projects` `search` `search-chat`
`skill-ideas` `recall` `today` `days` `remember` `log` `specialists` `check`
`sentinel` `new-specialist` `scaffold` `new-project` `state` `checkpoint`
`recycle-check` `schedule-status` `schedule-install` `remember-key`
`connect-telegram` `channel-check` `events` `ask` `waiting` `answer` `mail`
`connect-mail` `connect-calendar` `tools` `calendar-add` `calendar-change`
`calendar-cancel` `memory-search` `plugin` `inspect` `agenda` `consult` `guard`.

**Dashboard — 3,703 lines across 4 modules.**

| Module | Lines | Role |
|---|---:|---|
| `dashboard/app.py` | 3,194 | The web application (largest single file in the project) |
| `dashboard/settings.py` | 259 | Editing configuration from the browser |
| `dashboard/navigation.py` | 226 | The left rail, in one definition |
| `themes.py` | 237 | The colour schemes, and the one value the whole dashboard derives from |

**Launchers.** `launcher.py` (477) generates the per-user thing they
double-click; `bin/` holds the thin cross-platform shims — `.bat`, `.command`,
`.sh`, `.vbs` — all over one Python file (`_bootstrap.py`), plus `_find_python.bat`.

**Screens.** `screens.py` (283) draws the frames for install, upgrade, adoption
and uninstall.

---

## Layer 10 — Approvals: the human in the loop 審批

| Module | Lines | Role |
|---|---:|---|
| `approvals.py` | 521 | What it wants a decision on, and what happens when it gets one |
| `pending_hook.py` | 110 | Putting a dashboard message into the live session the moment there is one |

Together with `notify.py` (Layer 5) and `safety_gate.py` (Layer 1), these three
are the whole "it does not act alone" story. They are in different layers because
they stop different things: the gate stops irreversible commands, approvals stop
decisions, the notify gate stops noise.

---

## Layer 11 — Lifecycle: install to uninstall 生命週期

| Module | Lines | Role |
|---|---:|---|
| `dependencies.py` | 388 | What is needed and how to get it |
| `doctor.py` | 1,041 | Tells the user what is wrong, in words they can act on |
| `uninstall.py` | 478 | Take it off a machine and leave the person's work untouched |

Packaging: `pyproject.toml` (name `aki-agent`, package `aki_agent`, per-user
folder `.aki-agent` — all three deliberately agree), a single hard dependency
(`PyYAML`), console scripts `aki-agent-doctor` and `aki-agent-dashboard`,
`.claude-plugin/` (`plugin.json`, `marketplace.json`), and `_release/` for the
beta zips.

**A packaging decision worth keeping:** dependencies are lower bounds, not exact
pins. The reasoning is written into the file — an exact pin would force a
downgrade on a student who already has that library for something else.

---

## Cross-cutting

**Tests — 69 files.** Named after behaviours rather than modules, which is why
they read as claims: `test_alive_at_install`, `test_two_configs`,
`test_it_reads_on_both_grounds`, `test_engine_adoption`, `test_local_changes`,
`test_connection_removal`, `test_areas_and_sandbox`.

**Docs.** `README.md`, `INSTALL.md`, `INTEGRATE.md` (13,996 — merging into an
assistant somebody already has), `CHOOSING.md`, and under `docs/`:
`STATUS.md`, `CONNECTING.md`, `PACKAGES.md`.

---

## Where the weight sits

| Area | Lines | Share |
|---|---:|---:|
| Dashboard | 3,703 | 11% |
| CLI | 2,687 | 8% |
| Scheduling (`schedule` + `tasks`) | 2,030 | 6% |
| Config + schema + paths + situation | 2,146 | 6% |
| Install/scaffold/doctor | 3,506 | 11% |
| Everything else | ~19,100 | 58% |

Two files are outliers: `dashboard/app.py` at 3,194 and `cli.py` at 2,687. Both
are entry points that accumulate, and both are the first candidates if the
project ever needs splitting.

---

## What this map says about what to do next

Written as observations from the code, not as a plan the maintainer has agreed to.

1. **STATUS.md is 27 versions stale.** It is the file a newcomer would read
   first. Either regenerate it or delete it — a wrong map is worse than none.
2. **The seam mechanism has two customers.** `seams.py`, `plugins.py` and
   `inspect_report.py` are ~1,100 lines serving only `calendar` and `channel`.
   Either mail/files/backend become seams, or the machinery is over-built for
   what it carries.
3. **`dashboard/app.py` is the biggest file in the project** and it is the
   surface most likely to keep growing.
4. **`semantic.py` is off by default.** Worth deciding whether that is permanent.
5. The **vocabulary canary** is the single test protecting the whole
   general-purpose premise. It should never be weakened to make a feature fit.
