# Status — what is built, what is not, what is ugly

**Version 0.37.0.** Latest build `_release/Aki-Agent-Beta-20260827-002.zip`.
Rewritten **2026-08-28** from the code itself.

**Test suite: 1,294 passing** (run 2026-08-28).

> An earlier version of this file said **0.10.1, updated 2026-08-20**, and
> claimed 696 tests. It was 27 minor versions out of date and was the first
> file a newcomer would read — which is why this one carries the date it was
> run.

Written to be read by someone deciding what to do next, so it says what is
*wrong* as loudly as what is done.

For how the pieces fit together, see **`docs/ARCHITECTURE.md`**.
For the account-connection design, see **`docs/CONNECTING.md`**.

---

## Scale, measured

| | |
|---|---|
| Python | **~34,000 lines across 75 modules** |
| Tests | 71 files, **1,294 passing** |
| Slash-skills | 21 (`skills/`) |
| Library skills | 95 (`library/skills/`) |
| Specialists | 10 |
| Panels | 3 |
| Hard dependencies | 1 (`PyYAML`) |
| Largest file | `dashboard/app.py`, 3,194 lines |

---

## The four workstreams

| # | Workstream | State |
|---|---|---|
| 1 | Install and configuration | ✅ working end to end |
| 2 | Agent spine | ✅ built |
| 3 | Dashboard | ✅ built, including the control surface |
| 4 | Scheduling | ✅ built, two operating systems |

Since the last status these were added on top of the four: the seam registry and
plugin loading, `aki inspect`, the calendar seam, conversation search,
skill-ideas, panels, house rules, quiet time and me-time, the safety gate,
traces, and the dashboard chat panel.

---

## ✅ Built and covered by tests

Every module below exists and the suite passes against it. Grouped as in
`ARCHITECTURE.md`.

- **Ground** — `schema.py` (the crux), `config.py`, `paths.py`, `situation.py`,
  and the vocabulary canary that fails the build if a profession word enters the
  engine's executable code.
- **Primitives** — `atomic.py`, `secrets.py` (OS credential store),
  `safety_gate.py`, `dashboard_auth.py`.
- **State** — three-tier `memory.py`, `events.py`, `conversation.py`,
  `conversations.py` (search), `knowledge.py`, `house_rules.py`, `traces.py`,
  `steps.py`, `task_runs.py`, `upgrade_log.py`, `favourites.py`.
- **Spine** — `engine.py`, `session.py`, `guard.py`, `recycle.py`, `runner.py`,
  `backend.py`, `sentinel.py`.
- **Work** — `schedule.py` (one definition, two operating systems), `tasks.py`,
  `today.py`, `quiet.py`, `me_time.py`.
- **Outside** — `connectors/` mail, google_calendar, calendars (ICS), files;
  `calendar_seam.py`, `channels.py`, `notify.py`, Telegram setup and chat,
  `inbox.py`, `apis.py`, `mcp.py`.
- **Seams** — `seams.py`, `plugins.py`, `inspect_report.py`.
- **Capability** — `library.py`, `skills_store.py`, `specialists.py`,
  `skill_ideas.py`, `panels.py`, `semantic.py`.
- **Workspace** — `scaffold.py`, `workspace.py`, `folders.py`, `importer.py`,
  `local_changes.py`, `retire.py`.
- **Surfaces** — `cli.py` (~40 commands), the dashboard, `launcher.py`,
  `bin/` shims, `screens.py`, `themes.py`.
- **Approvals** — `approvals.py`, `pending_hook.py`.
- **Lifecycle** — `dependencies.py`, `doctor.py`, `uninstall.py`, packaging.

---

## ⚠️ Architectural debts

Found by reading the code on 2026-08-28. These are observations, **not a plan
anybody has agreed to**.

1. **The seam mechanism has only two customers.** `seams.py` + `plugins.py` +
   `inspect_report.py` are about 1,100 lines and serve exactly two registries:
   `Registry("calendar")` and `Registry("channel")`. Mail, files and backend are
   not seams. Either they become seams or the machinery is over-built for its
   load. See `CONNECTING.md` — the argument there is that **`account` should be
   the third seam**, because mail and files each need an auth story anyway, so
   auth is the layer underneath them.
2. **Four connectors, four different ways to obtain a credential.** Storing is
   uniform (`secrets.py`); getting is not. App password, OAuth, ICS URL, synced
   folder — each owned by its own connector. This is the concrete cost of debt 1.
   **Partly addressed 2026-08-28:** the `account` seam now reports every
   connection uniformly, and the `guide` seam gives every one of them a set-up
   explanation reachable from one place. Neither has taken ownership of
   *obtaining* the credential yet — that is the remaining half.
3. **`dashboard/app.py` is 3,194 lines**, the largest file in the project, and it
   is the surface most likely to keep growing. **Still open** — splitting the
   main surface of the product deserves its own clear run, not a tail-end of a
   session that has already changed a lot.
4. **`cli.py` is 2,687 lines** with ~40 commands in one module. Same shape of
   problem, lower urgency — a CLI accumulates more gracefully than a web app.
5. ~~**`semantic.py` is off unless somebody turns it on.** Undecided whether
   that is permanent.~~ **Closed 2026-08-28.** It was never undecided — the
   module's own docstring records the maintainer's decision of 2026-08-20,, with the reasoning. He confirmed it again on 2026-08-28:
   The debt was documentation treating a settled choice as a
   pending feature. It now has a guide (`aki-agent guide semantic-search`) so a
   user who outgrows word-matching can find the switch themselves, rather than
   being asked to decide during setup.

---

## What is ugly

Carried forward from the previous status. **Not re-verified on 2026-08-28** —
each still needs checking against current code before it is acted on.

1. **`APP_DIR_NAME` is duplicated** in `paths.py` and `bin/_bootstrap.py`.
   Unavoidable — the launcher runs before the package is importable — and
   guarded by a test.
2. **`_bootstrap.py` probes with an import, not a version check.** A present but
   wrong-version dependency passes the probe and fails later.
3. **The dashboard reloads config on every request.** Correct and simple; would
   need caching if a workspace ever got large.
4. **`skills/setup/SKILL.md` assumes the model knows the package directory.**
5. **No `settings.json` wiring the persona as the main-thread agent.**
6. **The knowledge shelf has no search.** Deliberate — a list of pointers is
   honest where a retrieval system that silently returns nothing is not — but it
   will not scale past a few hundred entries.

---

## 🚫 NOT verified

Carried forward from the previous status. **None of these were re-checked on
2026-08-28**, so treat them as open until somebody proves otherwise. Where there
is partial evidence since, it is named.

- **macOS.** Not one line has knowingly run on a Mac. launchd generation is
  written as pure functions and checked with the standard library's own plist
  parser; that is analysis, not observation. **Still the largest open risk.**
- **Every external install command.** winget, Homebrew and Bun installer lines
  are transcribed from official documentation and have never been executed.
  `describe_install()` says so, and a test fails if that caveat disappears while
  a command stays unverified.
- **A real non-technical person running `/setup`.** The interview is written.
  *Partial evidence since:* Aki has been installed and run on the test laptop,
  with scheduled tasks firing — so an install has happened, by its author. That
  is not the same as a stranger going through the interview.
- **Installing as a plugin from a marketplace.** `.claude-plugin/plugin.json` and
  `marketplace.json` are valid and match the documented schema; the install path
  has not been exercised.
- **Real IMAP, SMTP or ICS traffic.** Protocol code is standard library and
  parsing is tested against samples. Whether a real account has since been
  connected has **not been confirmed** — check before relying on it.
- **Any Google OAuth beyond Calendar.** Drive and Gmail have no implementation at
  all yet. See `CONNECTING.md`.

---

## Distribution

Dated beta zips in `_release/`, newest `Aki-Agent-Beta-20260827-002.zip`, built
by `bin/make_release.py`. Console scripts `aki-agent-doctor` and
`aki-agent-dashboard`. Plugin manifests under `.claude-plugin/`.

Dependencies are **lower bounds, not exact pins**, and the reasoning is written
into `pyproject.toml`: an exact pin would force a downgrade on a student who
already has that library for something else.

---

## How this file should be maintained

The previous copy went 27 versions stale because it was written by hand and
described a moment. The numbers at the top of this one — line count, module
count, test count, skill counts — are all things a script can recount in seconds.
**If this file drifts again, generate those numbers rather than typing them.**
