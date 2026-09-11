"""One command-line entry point, so the skills have something to call.

WHY THIS EXISTS
---------------
`memory.search()` was written, tested and correct, and for a while nothing
called it. That is the defect this package keeps finding in itself: a working
mechanism with nothing wired to it, whose only symptom is an absence.

A skill is a markdown file. It cannot import Python. So every engine capability
a skill needs must be reachable as a command, or it may as well not exist. This
module is that surface, and it is deliberately small: each subcommand does one
thing and prints plain text a model can read back to a person without
translating it.

DESIGN RULES
------------
1. **Plain text out, never a stack trace.** These run behind an assistant that
   is talking to a person. `doctor` sets the tone; this follows it.
2. **Read-only by default.** The only subcommands that write are `remember`,
   `log` and `new-project`, and `new-project` writes only after `--yes`.
3. **Say when there is nothing**, in words. "No projects yet" is an answer;
   empty output is a bug report waiting to happen.
4. **Never print a secret.** Nothing here reads credentials, and anything
   printed from user content goes through `secrets.redact` first, because
   people do paste passwords into notes.

    python "<engine>/bin/_bootstrap.py" aki_agent.cli <command>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config as config_module
from . import memory, paths as paths_module, scaffold, secrets, specialists
from . import workspace as workspace_module


def _load_config():
    """The config, or None with a plain sentence explaining why not."""
    from . import seams

    try:
        loaded = config_module.load()
        # The `providers:` block decides which channel, calendar and so on
        # this installation loads. Applied here because this is the one place
        # every command gets its configuration, and refused loudly rather
        # than skipped: a provider name nothing answers to would otherwise
        # switch something off and say nothing, and be discovered hours later
        # as "why did it not tell me".
        trouble = seams.apply(loaded)
        if trouble:
            return None, "\n".join(trouble)
        return loaded, ""
    except Exception as problem:        # ConfigError and anything below it
        # Passed through as written. `config.py` already explains itself in
        # plain words and names `/aki-agent:setup`; appending a second instruction here
        # produced "…type /aki-agent:setup.. Run /aki-agent:setup to create one." on the first run
        # of this command, which is exactly the kind of seam a user reads as
        # sloppiness in everything else.
        return None, str(problem)


def _program_name() -> str:
    """How to invoke this, on this machine, in a form that works."""
    try:
        from . import engine

        return (f'{engine.python_word()} "{engine.bootstrap()}" '
                "aki_agent.cli")
    except Exception:                                     # pragma: no cover
        return "aki_agent.cli"


def _clean(text: str) -> str:
    """Anything printed from the user's own material passes through here."""
    return secrets.redact(text) if text else text


# ---------------------------------------------------------------------------
# Reading


def cmd_projects(args) -> int:
    config, problem = _load_config()
    if not config:
        print(problem)
        return 1

    space = workspace_module.scan(config)
    if space.problems and not space.items:
        for line in space.problems:
            print(line)
        return 1

    label = config.layout.schema.item_label_plural
    print(f"{len(space.items)} {label.lower()} in {space.root}:")
    print()
    for item in space.items:
        # The workspace is the parent folder when workspaces are in use, and the
        # workspace root when they are not -- shown either way, because "which
        # of my two work lives is this" is the first thing anyone asks.
        workspace = item.path.parent.name
        print(f"  {workspace} / {item.path.name}")
        for problem in item.problems:
            print(f"      ! {_clean(problem)}")

    # Printed even when items were found. A workspace-level problem is
    # typically "one of your two workspaces matched nothing" -- which is invisible
    # if it is only reported when the list is completely empty.
    if space.problems:
        print()
        for line in space.problems:
            print(f"  ! {_clean(line)}")
    return 0


def cmd_search(args) -> int:
    query = " ".join(args.query).strip()
    if not query:
        print("Nothing to search for.")
        return 1

    results = memory.search(query, limit=args.limit)
    if not results:
        print(f"Nothing remembered matches {query!r}.")
        return 0

    print(f"{len(results)} match(es) for {query!r}, best first:")
    print()
    for score, fact in results:
        print(f"  [{score:.1f}] {_clean(fact.summary)}")
        if fact.body:
            first_line = _clean(fact.body).strip().splitlines()[0]
            print(f"        {first_line[:150]}")
    return 0


def cmd_search_chat(args) -> int:
    """Search the conversations, not the notes.

    `search` looks through what the assistant wrote down. Most of what matters
    was never written down -- it was said once and moved on from.
    """
    from . import conversations

    query = " ".join(args.query).strip()
    if not query:
        print("Nothing to search for.")
        return 1

    # Refreshed on the way in rather than on a schedule. An index nobody
    # updates is worse than no index, because it answers confidently about a
    # world that has moved on.
    conversations.refresh()

    hits = conversations.search(query, limit=args.limit, days=args.days)
    if not hits:
        print(f"Nothing said matches {query!r}.")
        print("Only conversations held inside your own workspace are kept,")
        print("and what was said in the session you are in now is not on disk")
        print("yet -- scroll up for that.")
        return 0

    print(f"{len(hits)} match(es) for {query!r}, newest first:")
    for hit in hits:
        when = (hit["stamp"] or "")[:16].replace("T", " ")
        who = "you" if hit["role"] == "user" else "your assistant"
        print()
        print(f"  {when}  {who}")
        print(f"    {hit['said'][:300]}")
    print()
    print("Square brackets mark the match. It matches any three characters in")
    print("a row -- which is what makes Chinese searchable -- so it can land")
    print("mid-word: read the words around it before believing a hit.")
    return 0


def cmd_skill_ideas(args) -> int:
    """Offer what somebody keeps asking for. Never write it for them."""
    from . import skill_ideas

    if args.not_this:
        skill_ideas.dismiss(args.not_this)
        print("Noted — that one will not be offered again.")
        return 0

    ideas = skill_ideas.propose(limit=args.limit)
    if not ideas:
        print("Nothing has come up often enough yet.")
        print("It takes three asks, on at least two different days —")
        print("five in one afternoon is one job going badly, not a habit.")
        return 0

    print(f"{len(ideas)} thing(s) you keep asking for:")
    for idea in ideas:
        print()
        print(f"  {idea.title}")
        print(f"    {idea.sentence()}")
        for ask in idea.asks[:3]:
            print(f"      {(ask['when'] or '')[:10]}  "
                  f"\"{ask['said'][:110]}\"")
        print(f"    not interested:  skill-ideas --not-this {idea.key}")
    print()
    print("These are suggestions, not skills. Nothing has been written.")
    return 0


def cmd_recall(args) -> int:
    facts = memory.recall(limit=args.limit)
    if not facts:
        print("Nothing has been remembered yet.")
        return 0
    print(f"{len(facts)} remembered:")
    for fact in facts:
        print(f"  - {_clean(fact.summary)}")
    return 0


def cmd_today(args) -> int:
    """The day's log so far. Used by the on-demand brief."""
    text = memory.read_day().strip()
    if not text:
        print("Nothing logged today yet.")
        return 0
    print(_clean(text))
    return 0


def cmd_eod(args) -> int:
    """Write the day up now, from a terminal or from the assistant.

    THE SAME JOB as the dashboard's End of day button and the 18:30 schedule
    -- `tasks.run_one("evening-wrapup")`, never a second writer. The maintainer asked
    for this on 2026-09-04 after finding that saying "EOD" to the assistant
    produced a summary it had improvised itself: not the scheduled job, not
    written to the day log, and not following the wrap-up's own instructions.
    Three entrances that each write their own account of one day is how a day
    log stops being worth reading.
    """
    from . import tasks

    # Printed BEFORE the run, and flushed. This holds the terminal for a
    # minute or two while a headless model run writes the entry, and a
    # command that prints nothing for that long has already been read as
    # broken by the time it succeeds.
    print("Writing up the day. This is the same job as the 18:30 wrap-up, "
          "so give it a minute or two.")
    sys.stdout.flush()

    outcome = tasks.run_one("evening-wrapup")

    if not outcome.ok:
        print(f"It did not run: {outcome.message}")
        return 1

    print(f"Done in {outcome.seconds:.0f}s. It is saved under today's log — "
          f"`{_program_name()} today` shows it.")
    if not outcome.delivered:
        # Held is a feature; held-and-looking-sent is not. Without this line
        # the terminal says "done" and the phone stays quiet, and the only
        # available conclusion is that messages are broken.
        print("It has not been sent to you — quiet hours are holding it.")
    return 0


def cmd_days(args) -> int:
    entries = memory.recent_days(args.count)
    if not entries:
        print("No daily logs yet.")
        return 0
    for day, text in entries:
        print(f"--- {day.isoformat()}")
        print(_clean(text).strip() or "(nothing logged)")
        print()
    return 0


# ---------------------------------------------------------------------------
# Writing


def cmd_remember(args) -> int:
    summary = " ".join(args.summary).strip()
    if not summary:
        print("Nothing to remember.")
        return 1
    fact = memory.remember(summary, body=args.body or "")
    print(f"Remembered: {fact.summary}")
    print(f"  {fact.path}")
    return 0


def cmd_log(args) -> int:
    text = " ".join(args.text).strip()
    if not text:
        print("Nothing to log.")
        return 1
    path = memory.log_event(text)
    print(f"Logged to {path.name}: {text}")
    return 0


def cmd_specialists(args) -> int:
    from . import sentinel

    found = specialists.read_all()
    # The built-in checker is listed first and always, with its state, because
    # "no specialists yet" was a true sentence that gave the wrong impression:
    # there has been one since installation.
    state = "on" if sentinel.is_on() else "off"
    print(f"  {sentinel.KEY} — {sentinel.agent().describe()} [{state}, "
          "built in]")
    if not found:
        print("No specialists of your own yet.")
        return 0
    print(f"and {len(found)} of your own:")
    for one in found:
        print(f"  {one.key} — {one.describe()}")
    return 0


def cmd_check(args) -> int:
    """Put a draft in front of the built-in checker before it goes anywhere."""
    from . import sentinel

    if args.file:
        path = Path(args.file).expanduser()
        if not path.is_file():
            print(f"There is nothing to check at {path}.")
            return 1
        draft = path.read_text(encoding="utf-8", errors="replace")
    else:
        draft = " ".join(args.text or ())

    if not draft.strip():
        print("Nothing to check. Pass some text, or --file a draft.")
        return 1

    loaded, _ = _load_config()
    workspace = (loaded.layout.root
                 if loaded is not None and loaded.layout.root else None)

    verdict = sentinel.review(draft, sources=" ".join(args.sources or ()),
                              workspace=workspace)

    print(_clean(verdict.line()))
    if verdict.note:
        print(f"  {verdict.note}")
    for name in sentinel.CHECKS:
        if name in verdict.checks:
            print(f"  {name}: {verdict.checks[name]} "
                  f"{_clean(verdict.reasons.get(name, ''))}".rstrip())

    # An exit code the caller can branch on, because a scheduled task piping
    # this into something else needs to know without reading English.
    return 2 if verdict.blocked else 0


def cmd_sentinel(args) -> int:
    """Turn the built-in check on or off, or say which it is."""
    from . import sentinel

    if args.state == "on":
        print(sentinel.turn_on())
    elif args.state == "off":
        print(sentinel.turn_off())
    else:
        print("The check is on." if sentinel.is_on() else
              "The check is off. Nothing is verified before it goes out.")
    return 0


def cmd_new_specialist(args) -> int:
    """Create one. Read-only unless --may-write is passed deliberately."""
    one, problems = specialists.save(specialists.Specialist(
        key="",
        name=args.name,
        purpose=args.purpose,
        brief=args.brief or specialists.STARTER_BRIEF,
        reads=tuple(args.reads or ()),
        may_write=args.may_write,
    ))

    if problems and one.key == specialists.BUILT_IN_KEY:
        # Not saved at all -- the reserved name. Saying "saved, but" here
        # would be the precise failure the checker itself exists to catch:
        # reporting a step as done when it did not happen.
        for problem in problems:
            print(problem)
        return 1

    if problems:
        # Saved anyway, and the problems reported. A half-written specialist
        # the user can see and fix beats a refusal they have to reconstruct
        # from an error message -- but they must be told, or they will assume
        # it is finished.
        print(f"Saved as {one.key}, but it needs more:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(f"Created {one.key} — {one.describe()}")
    if one.may_write:
        print("  It may write, and only inside a project's sandbox.")
    else:
        print("  It reads and reports. It cannot change any file.")
    return 0


def cmd_scaffold(args) -> int:
    """Build (or complete) the agent's own folder.

    WHY THIS COMMAND HAD TO EXIST
    -----------------------------
    `scaffold.plan()` and `scaffold.build()` were reachable only from Python,
    and the only thing that runs at setup is a markdown skill, which cannot
    import anything. So on a real install the folders got made by hand --
    correctly, as it happens -- and everything the scaffold writes *into* them
    was simply never created: `CLAUDE.md`, the READMEs, `.claude/`, each
    workspace's sandbox and the summary files. The user saw `01_Work` and
    `02_Personal` and nothing else, and no step reported a failure, because no
    step ran.

    Safe to run on an existing folder: the scaffold never overwrites, so this
    fills in what is missing and leaves everything else alone. That is also how
    an install made before this command existed gets repaired.
    """
    config, problem = _load_config()
    if not config:
        print(problem)
        return 1

    # `--root`, then whatever setup already recorded, then the folder Claude
    # Code is running in. That last fallback is what "install it here" means
    # (reported 2026-08-19): no question, no dragged folder, no chance of the
    # config naming somewhere the folders are not.
    root = (Path(args.root) if args.root
            else config.layout.root or paths_module.default_root())

    # A first install has no folder recorded. Recording it here, from the same
    # command that creates the folders, is the whole reason the two cannot
    # disagree.
    adopting = config.layout.root is None
    if adopting:
        config.layout.root = root

    if args.workspaces:
        workspaces = tuple(part.strip() for part in args.workspaces.split(",")
                      if part.strip())
    else:
        workspaces = config.layout.workspaces or scaffold.DEFAULT_WORKSPACES

    the_plan = scaffold.plan(root, workspaces=workspaces,
                             schema=config.layout.schema,
                             with_examples=not args.no_examples)

    if adopting:
        print(f"Installing here: {root}")
        print()
    print(the_plan.describe())

    if not args.yes:
        print()
        print("Nothing written. Re-run with --yes to create it.")
        return 0

    ok, message = scaffold.build(the_plan, confirmed=True,
                                 schema=config.layout.schema,
                                 assistant_name=config.assistant.name,
                                 user_name=config.user.name)
    print()
    print(message)
    if not ok:
        return 1

    # An install made before the chat-mirror instructions existed has a
    # CLAUDE.md without them, and the scaffold never overwrites. Topping up
    # is the only way those users ever get the fix.
    said = scaffold.top_up(root)
    if said:
        print(said)

    # The config and the folders are now written by the same command, from the
    # same numbered names. That is the point: the mismatch this package hit on
    # its second install -- config saying `work`, folder called `01_work`, an
    # empty dashboard and no error -- cannot arise from this path at all.
    if (config.layout.root == root
            and config.layout.workspaces != the_plan.workspaces):
        config.layout.workspaces = the_plan.workspaces
        written = config_module.save(config)
        print(f"Workspaces recorded in {written}: "
              f"{', '.join(the_plan.workspaces)}")
    elif config.layout.root != root:
        print()
        print("This is not the folder in your settings. If it should be, set "
              "the folder and these workspaces there:")
        print(f"  root:       {root}")
        print(f"  workspaces: {', '.join(the_plan.workspaces)}")

    # Move in, so that every later command -- the dashboard, the scheduled
    # tasks, the CLI -- finds the config where it now lives, without the user
    # ever having to set an environment variable.
    if config.layout.root == root:
        config_home = root / config.layout.config_dir
        if config_home.is_dir():
            moved = paths_module.adopt_app_dir(config_home)
            print(f"Settings and memory now live in {config_home}"
                  + (f" ({len(moved)} things moved in)" if moved else ""))
            # Written again, into its new home: the copy that came across is
            # the one from before the workspaces were recorded.
            config_module.save(config)

    return 0


def cmd_new_project(args) -> int:
    config, problem = _load_config()
    if not config:
        print(problem)
        return 1

    root = config.layout.root
    if not root:
        print("No workspace folder is configured. Run /aki-agent:setup.")
        return 1

    the_plan = scaffold.plan_project(root, args.workspace, args.name,
                                     schema=config.layout.schema)

    if the_plan.warning:
        print(the_plan.warning)
        return 1

    if the_plan.is_empty:
        print(f"{args.workspace} / {args.name} already exists. Nothing to do.")
        return 0

    print(the_plan.describe())

    if not args.yes:
        # The plan is the whole point: it is shown, and creating it is a
        # second, separate decision.
        print()
        print("Nothing written. Re-run with --yes to create it.")
        return 0

    ok, message = scaffold.build(the_plan, confirmed=True,
                                 schema=config.layout.schema,
                                 assistant_name=config.assistant.name,
                                 user_name=config.user.name)
    print()
    print(message)
    return 0 if ok else 1


# ---------------------------------------------------------------------------


def cmd_state(args) -> int:
    """Print the working state — what the last session was in the middle of.

    THE READING HALF. `recycle.checkpoint()` writes this file every twenty
    minutes, and for a while nothing read it back: only the dashboard and the
    recycle itself looked at it, so a fresh session started blind next to a
    perfectly good handoff. A handoff nobody reads is the same as no handoff.
    """
    state = memory.read_working_state()
    if state is None:
        print("Nothing saved yet — no session has checkpointed on this "
              "machine. That is normal on the first day.")
        return 0

    print(f"Saved {state.generated_at:%Y-%m-%d %H:%M}. "
          f"{state.staleness_note()}")
    for label, items in (("Open", state.open_items),
                         ("Waiting on", state.waiting_on),
                         ("Recently touched", state.recent_files)):
        if items:
            print()
            print(f"{label}:")
            for item in items:
                print(f"  - {_clean(item)}")
    if state.human_notes:
        print()
        print(_clean(state.human_notes))
    return 0


def cmd_checkpoint(args) -> int:
    """Save the working state now, without waiting for the schedule.

    THIS IS THE MANUAL HANDOFF, and the reason it is archived while the
    twenty-minute schedule is not. The schedule calls `recycle.checkpoint()`
    directly, 72 times a day, mostly to say the same thing. Reaching this
    function means a person asked -- typed the command, or told the
    assistant to save where it had got to -- and that is a moment somebody
    may well want to find again.
    """
    from . import recycle

    recycle.checkpoint()
    state = memory.read_working_state()
    if state is None:
        print("Saved, but nothing could be read back — check the workspace "
              "path in your config.")
        return 1

    try:
        memory.record_handoff(state, kind=memory.HANDOFF_MANUAL,
                               why="saved by hand")
    except OSError as exc:                                # noqa: BLE001
        # Said, not swallowed. The save itself succeeded; only the copy for
        # the handoff log did not, and those are different pieces of news.
        print(f"(saved, but not added to the handoff log: {exc})")

    print(f"Saved. {len(state.open_items)} open, "
          f"{len(state.waiting_on)} waiting, "
          f"{len(state.recent_files)} recently touched.")
    return 0


def cmd_recycle_check(args) -> int:
    """Say whether restarting right now would be safe — and why."""
    from . import recycle

    advice = recycle.should_recycle(idle_seconds_required=args.idle_seconds)
    print("Safe to restart." if advice.safe else "Do not restart now.")
    print(advice.reason)
    return 0


def cmd_schedule_status(args) -> int:
    """What is scheduled, and what is only defined."""
    from . import schedule

    # Say so rather than answering the question wrongly. This used to
    # collapse "could not ask" into "nothing installed", and then print the
    # paragraph about none of the automatic work running -- to a user whose
    # tasks were all present and fine.
    try:
        installed = set(schedule.installed_names())
    except schedule.CouldNotAsk as problem:
        print(f"The scheduler could not be read, so this cannot say what is "
              f"installed: {problem}")
        return 1

    tasks = schedule.all_tasks()
    if not installed:
        print("Nothing is scheduled on this machine, so none of the "
              "automatic work runs — no morning summary, no evening "
              "write-up, and no checkpoint of what you are in the middle of.")
        from . import engine as engine_module

        print("Run: " + engine_module.how_to_run("aki_agent.cli",
                                                 "schedule-install --yes"))
        print()
    for task in tasks:
        # `task.key in installed` was the fifth hand-written copy of this
        # comparison, and wrong the same way as the other four: the scheduler
        # knows the task as `AkiAgent-<key>` on Windows and
        # `com.aki-agent.<key>` on macOS, never as the bare key. Every row
        # printed "NOT installed", including for tasks that were running --
        # and `delete_user_task`'s own failure note tells the user to run this
        # command to check. Fixed 2026-09-05 to use `is_installed`, which
        # exists precisely so this is written once.
        mark = ("installed" if schedule.is_installed(task, installed)
                else "NOT installed")
        print(f"  [{mark}] {task.title} — {task.why}")
    return 0


def cmd_schedule_install(args) -> int:
    """Install the built-in schedule. Requires --yes.

    The schedule module was written expecting setup to call this ("a default
    set is installed at setup"); nothing did, so every install shipped with
    the continuity machinery present and dormant.
    """
    from . import schedule

    if not args.yes:
        print(schedule.describe_install())
        print()
        print("Nothing has been scheduled. Re-run with --yes to go ahead.")
        return 0

    # Stop before anything is created, not warn and carry on.
    #
    # A task made by an administrator can only be changed by an
    # administrator, and the dashboard is not one -- so installing from an
    # elevated window produced six tasks the user could never switch off.
    # See `schedule.running_elevated()` for the day that happened.
    #
    # This used to print the warning and then create all six anyway, closing
    # with "Nothing runs as an administrator" -- false in precisely the case
    # it had just described. `schedule.install` refuses now, so every other
    # path is covered too; this is here to say it once, clearly, rather than
    # six times as six identical failures.
    warning = schedule.elevation_warning()
    if warning and not getattr(args, "anyway", False):
        print(f"  ! {warning}")
        print()
        print("  If you really do want them owned by the administrator "
              "account, add --anyway.")
        return 1

    runner = schedule.runner_script()
    try:
        already = set(schedule.installed_names())
    except schedule.CouldNotAsk as problem:
        # Installing without being able to see what is there is how a task
        # ends up duplicated or silently replaced.
        print(f"  FAILED — {problem}")
        print("Nothing was installed.")
        return 1
    failures = 0
    for task in schedule.DEFAULT_TASKS:
        if not task.enabled:
            continue
        # `already` holds what the scheduler calls a task
        # (`AkiAgent-morning-summary`); `task.key` is `morning-summary`. The
        # two never match, so this branch was dead and every run re-created
        # all six. Fourth hand-written copy of that comparison, fourth time
        # it was wrong -- `is_installed` exists precisely so it is written
        # once.
        if schedule.is_installed(task, already):
            print(f"  already there — {task.title}")
            continue
        ok, message = schedule.install(
            task, runner, confirmed=True,
            allow_elevated=getattr(args, "anyway", False))
        print(f"  {'ok' if ok else 'FAILED'} — {task.title}: {message}")
        failures += 0 if ok else 1
    # Which copy of the package these now point at, so an update can tell
    # that they are stale rather than leaving them quietly broken.
    schedule.remember_install_root()
    print()
    if schedule.running_elevated():
        # Said only when it is true. The old line said the opposite of what
        # had just happened whenever somebody used --anyway.
        print("These were created by an administrator, so the dashboard "
              "cannot switch them off. Remove them from an administrator "
              "window if you need to.")
    else:
        print("Nothing runs as an administrator, and you can remove any of "
              "them with the dashboard at any time.")
    return 1 if failures else 0


def cmd_remember_key(args) -> int:
    """Put one secret into the operating system's password manager.

    Reads the value from stdin by default, and that is not fussiness. A value
    passed as an argument is visible in the process list to every other
    process on the machine while the command runs, and it lands in the shell's
    history file afterwards — for a key whose whole purpose is not being
    written down anywhere.

    The setup skill used to do this with `python -c "... secrets.set_secret(
    'KEY', 'value')"`, which has that problem AND runs under whichever Python
    the shell resolves rather than the assistant's environment.
    """
    from . import secrets as secrets_module

    name = (args.name or "").strip()
    if not name:
        print("A key needs a name.")
        return 1

    value = args.value
    if not value:
        value = sys.stdin.read().strip()
    if not value:
        print(f"Nothing was given for {name}, so nothing was saved.")
        return 1

    try:
        where = secrets_module.set_secret(name, value)
    except secrets_module.SecretsUnavailable as problem:
        print(str(problem))
        return 1

    # The name, never the value. This output is read back in a transcript.
    print(f"{name} is in {where}.")
    return 0


def cmd_connect_telegram(args) -> int:
    """The three Telegram setup steps, as a command rather than as Python.

    WHY THIS EXISTS (2026-08-23)
    ----------------------------
    `skills/connect-telegram/SKILL.md` did these with bare
    `python -c "from aki_agent import telegram_setup; ..."` — six times.
    That `python` is whichever one the shell resolves, which is not the
    assistant's virtual environment, so the package is not on its path and
    every one of them died with `ModuleNotFoundError` in the middle of a
    setup conversation.

    The guard test that was supposed to catch this only inspected lines that
    already mentioned `_bootstrap.py`, so all six were invisible to it.

    Making them real subcommands fixes more than the path. A skill that pastes
    Python into a shell is a skill that can be talked into pasting different
    Python; a subcommand takes an argument and does one thing.
    """
    from . import telegram_setup

    if args.describe:
        print(telegram_setup.describe_setup())
        return 0

    if args.token:
        ok, message = telegram_setup.save_token(args.token, confirmed=True)
        print(message)
        return 0 if ok else 1

    if args.allow:
        ok, message = telegram_setup.allow_user(args.allow, confirmed=True)
        print(message)
        return 0 if ok else 1

    # No argument: say where things stand, which is what somebody typing the
    # bare command wants to know.
    print(telegram_setup.describe_setup())
    return 0


def cmd_channel_check(args) -> int:
    """Say, at launch, whether the assistant can reach the user.

    Runs from the generated launcher. Prints nothing when everything is
    connected — a launcher that congratulates itself every morning gets
    ignored, and then so does the one line that matters.
    """
    from . import channels

    channel = channels.get("telegram")
    if channel is not None and channel.available():
        return 0

    print()
    print("  Note: no messaging account is connected, so I cannot reach you")
    print("  when you are away from this machine. Type /connect-telegram in")
    print("  the session to set it up, or ignore this if you do not want it.")
    print()
    return 0


def cmd_events(args) -> int:
    """What has been happening."""
    from . import events

    entries = events.read(limit=args.limit, kind=args.kind)
    if not entries:
        print("Nothing recorded yet.")
        return 0
    for entry in entries:
        source = f" [{entry.source}]" if entry.source else ""
        print(f"  {entry.at:%Y-%m-%d %H:%M}  {entry.kind}{source}  "
              f"{_clean(entry.text)}")
    return 0


def cmd_ask(args) -> int:
    """Raise something for the user to decide, with its own answers.

    This is how a skill puts a card in front of the user: it declares the
    question and the exact answers, and the answering surface can only ever
    reply with one of them.
    """
    from . import approvals

    options = None
    if args.option:
        options = []
        for raw in args.option:
            key, _, label = raw.partition(":")
            label = label or key
            options.append(approvals.Option(key=key.strip(),
                                            label=label.strip()))
    item = approvals.ask(" ".join(args.title), body=args.body,
                         kind=args.kind, options=options,
                         task=args.task, context=args.context)
    print(f"Waiting for an answer: {item.title}  [{item.id}]")
    for option in item.options:
        print(f"  {option.key} — {option.label}")
    return 0


def cmd_waiting(args) -> int:
    """What is waiting for the user, and what it can be answered with."""
    from . import approvals

    items = approvals.open_items()
    if not items:
        print("Nothing is waiting for you.")
        return 0
    for item in items:
        print(f"[{item.id}] {item.kind}: {_clean(item.title)}")
        if item.body:
            print(f"    {_clean(item.body)[:300]}")
        print("    " + " · ".join(f"{one.key}={one.label}"
                                  for one in item.options))
    return 0


def cmd_answer(args) -> int:
    """Answer one of them — by option key, or in the user's own words."""
    from . import approvals

    if args.text:
        ok, message = approvals.reply(args.id, " ".join(args.text))
    elif args.dismiss:
        ok, message = approvals.dismiss(args.id)
    elif args.option:
        ok, message = approvals.answer(args.id, args.option)
    else:
        print("Say which option, or pass --text, or --dismiss.")
        return 1
    print(message)
    return 0 if ok else 1


def cmd_mail(args) -> int:
    """What is in the mailbox.

    THE READING HALF HAD NO ENTRY POINT (2026-08-23)
    ------------------------------------------------
    `mail.recent()`, `mail.send()` and `mail.test_connection()` had no caller
    outside tests. Nothing in the package could open a mailbox. Meanwhile
    README said "Reads your mail... over IMAP", the connections page drew a
    column headed "Reads from", and the setup interview walked a student
    through creating a real app password and handing it over -- for a
    mailbox nothing would ever open.

    Collecting a credential for a capability that does not exist is the worst
    version of this package's recurring fault, because the cost lands on
    somebody else's account.

    Headers only, and deliberately: `recent()` fetches RFC822.HEADER, so no
    message body is ever retrieved. Sender, subject and date are what an
    assistant needs to say "there is something from the planners"; the body
    is the part worth not having.
    """
    from .connectors import mail as mail_module

    loaded, problem = _load_config()
    if loaded is None:
        print(problem)
        return 1

    accounts = list(loaded.connections.mail)
    if not accounts:
        print("No mailbox is connected. Add one with `connect-mail`.")
        return 1
    if args.address:
        accounts = [one for one in accounts if one.address == args.address]
        if not accounts:
            print(f"No mailbox here is {args.address}.")
            return 1

    for account in accounts:
        print(f"{account.label or account.address}")
        try:
            found = mail_module.recent(mail_module.from_config(account),
                                       limit=args.limit,
                                       unread_only=args.unread)
        except Exception as exc:                          # noqa: BLE001
            # Named plainly. A mailbox that cannot be opened is the single
            # most likely thing to go wrong here, and "it silently showed
            # nothing" is indistinguishable from "there is nothing".
            print(f"  could not be opened: {exc}")
            continue

        if not found:
            print("  nothing" + (" unread" if args.unread else ""))
            continue
        for message in found:
            print("  " + _clean(message.safe_summary()))
    return 0


def cmd_connect_mail(args) -> int:
    """Add a mailbox. The password goes to the OS store, never the config."""
    from . import config as cfg
    from . import connectors, secrets as secrets_module
    from .connectors import mail as mail_module

    loaded, problem = _load_config()
    if loaded is None:
        print(problem)
        return 1

    guess = mail_module.guess_provider(args.address)
    account = cfg.MailAccount(
        address=args.address.strip(),
        label=args.label or args.address.strip(),
        imap_host=args.imap_host or (guess.imap_host if guess else ""),
        smtp_host=args.smtp_host or (guess.smtp_host if guess else ""),
        # Both ports were read by `mail.py` on every connection and settable
        # from nowhere -- not here, not on the Connections page -- so a
        # mailbox that is not on 993/587 could not be configured at all, and
        # the symptom was a timeout rather than anything that named a port.
        imap_port=args.imap_port or (guess.imap_port if guess else 993),
        smtp_port=args.smtp_port or (guess.smtp_port if guess else 587),
        may_send=args.may_send,
    )
    if not account.imap_host:
        print("I do not know the server for that address — pass --imap-host "
              "and --smtp-host, which your email provider's help pages list.")
        return 1

    if args.password:
        secrets_module.set_secret(account.secret_key(), args.password)
        print(f"The password went into this computer's credential store, "
              f"under {account.secret_key()}. It is not in any file here.")
    else:
        print("No password given, so nothing was stored. Add it with "
              "--password when you have an app password ready.")

    import dataclasses

    existing = [one for one in loaded.connections.mail
                if one.address != account.address]
    # `replace`, not a fresh Connections(): a hand-built one silently drops
    # every field it forgets to mention.
    loaded.connections = dataclasses.replace(
        loaded.connections, mail=tuple(existing) + (account,))
    cfg.save(loaded)
    print(f"Added {account.address}. Sending is "
          f"{'allowed' if account.may_send else 'off'} — drafts only until "
          "you turn it on.")
    return 0


def cmd_connect_calendar(args) -> int:
    """Subscribe to a calendar by its ICS address. Read-only, and said so."""
    from . import config as cfg

    loaded, problem = _load_config()
    if loaded is None:
        print(problem)
        return 1

    from .connectors import calendars as calendar_module

    # The address itself goes to the credential store, not the config file:
    # an ICS subscription URL is a bearer token for the whole calendar, and
    # `connectors.calendars` was written expecting to find it there.
    calendar = calendar_module.Calendar(name=args.name)
    calendar.save_url(args.url)

    import dataclasses

    feed = cfg.CalendarFeed(name=args.name, url="")
    existing = [one for one in loaded.connections.calendars
                if one.name != feed.name]
    loaded.connections = dataclasses.replace(
        loaded.connections, calendars=tuple(existing) + (feed,))
    cfg.save(loaded)
    print(f"Subscribed to {feed.name}. The address went into this computer's "
          "credential store, not into any file here — anyone holding it can "
          "read the whole calendar.")
    print("This is read-only: I can tell you what is on, but I cannot add or "
          "move anything.")
    return 0


def cmd_tools(args) -> int:
    """What outside services are set up, and which job each one does.

    PRINTS NO KEYS, EVER, AND THAT IS THE WHOLE DESIGN OF THIS COMMAND
    -----------------------------------------------------------------
    Anything printed here lands in the session transcript, which is written to
    disk, carried into later sessions and read by a model. A paid key printed
    once is a paid key in a log file for good.

    So this reports names and capabilities only. Code that needs the key fetches
    it in-process with `apis.for_job(...)` and calls the service directly --
    the key never passes through the conversation at all.
    """
    from . import apis

    loaded, problem = _load_config()
    if loaded is None:
        print(problem)
        return 1

    if args.job:
        resolved = apis.for_job(loaded, args.job)
        if resolved is None:
            print(f"Nothing is set up for '{args.job}'. Tell the user plainly "
                  "that no key is set up for it, and that the API keys page in "
                  "the dashboard is where one goes. Do not offer to do it "
                  "another way.")
            return 1
        print(f"{args.job}: {resolved.name} (key stored as "
              f"{apis.secret_name(resolved.tool_key)}, "
              f"read it with apis.for_job -- never print it)")
        return 0

    print(apis.brief(loaded))

    rows = apis.listing(loaded)
    if rows:
        print()
        print("Set up, in the order that decides who wins a shared job:")
        for row in rows:
            jobs = ", ".join(row["job_labels"]) or "nothing yet"
            state = "key saved" if row["has_key"] else "NO KEY"
            switch = "" if row["enabled"] else ", switched off"
            print(f"  - {row['name']}: {jobs} ({state}{switch})")
    return 0


def _when(text: str):
    """A time somebody typed, or None with the reason said out loud.

    Accepts what a person writes -- "2026-09-12 14:30", "2026-09-12T14:30" --
    and nothing clever. Guessing at "next Tuesday" here would put the guess in
    the wrong place: the assistant reading this command already knows what day
    the user meant, and a parser that quietly resolves an ambiguous phrase to
    the wrong week is worse than one that refuses.
    """
    import datetime as _d

    raw = (text or "").strip().replace("T", " ")
    for shape in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return _d.datetime.strptime(raw, shape).astimezone()
        except ValueError:
            continue
    return None


def cmd_calendar_add(args) -> int:
    """Put something in the diary, using whichever calendar can take it."""
    from . import calendar_seam

    diary = calendar_seam.writer()
    if diary is None:
        # Said before the dry run, not after. Printing "Would add: ..." for
        # something no connected calendar can accept is the exact lie this
        # seam exists to stop.
        print(calendar_seam.why_no_writer())
        return 1

    start = _when(args.start)
    if start is None:
        print(f"I could not read '{args.start}' as a time. "
              "Use 2026-09-12 14:30.")
        return 1
    end = _when(args.end) if args.end else None

    if not args.yes:
        # The dry run is the default, and it prints what it would do rather
        # than a warning about not having done it. A person checking a booking
        # wants to see the booking.
        when = start.strftime("%a %d %b %Y, %H:%M")
        print(f"Would add to {diary.name}: {args.title}")
        print(f"           {when}"
              + (f" until {end.strftime('%H:%M')}" if end else " (one hour)"))
        if args.location:
            print(f"           at {args.location}")
        print()
        print("Nothing was added. Add --yes to do it.")
        return 0

    ok, message = diary.add(
        args.title, start, end, location=args.location or "",
        description=args.description or "",
        calendar_id=args.calendar, confirmed=True)
    print(message)
    return 0 if ok else 1


def cmd_calendar_change(args) -> int:
    """Move or retitle something already in the diary."""
    from . import calendar_seam

    diary = calendar_seam.writer()
    if diary is None:
        print(calendar_seam.why_no_writer())
        return 1

    start = _when(args.start) if args.start else None
    end = _when(args.end) if args.end else None
    if args.start and start is None:
        print(f"I could not read '{args.start}' as a time.")
        return 1

    if not args.yes:
        print(f"Would change {args.event_id}:")
        if args.title:
            print(f"  title    -> {args.title}")
        if start:
            print(f"  starts   -> {start.strftime('%a %d %b %Y, %H:%M')}")
        if end:
            print(f"  ends     -> {end.strftime('%H:%M')}")
        if args.location:
            print(f"  location -> {args.location}")
        print()
        print("Nothing was changed. Add --yes to do it.")
        return 0

    ok, message = diary.change(
        args.event_id, calendar_id=args.calendar, summary=args.title,
        start=start, end=end, location=args.location, confirmed=True)
    print(message)
    return 0 if ok else 1


def cmd_calendar_cancel(args) -> int:
    """Take something out of the diary. The one with no undo."""
    from . import calendar_seam

    diary = calendar_seam.writer()
    if diary is None:
        print(calendar_seam.why_no_writer())
        return 1

    if not args.yes:
        print(f"Would cancel {args.event_id}.")
        print("Anyone invited would be told by Google, and there is no undo.")
        print()
        print("Nothing was cancelled. Add --yes to do it.")
        return 0

    ok, message = diary.cancel(
        args.event_id, calendar_id=args.calendar, confirmed=True)
    print(message)
    return 0 if ok else 1


def cmd_memory_search(args) -> int:
    """Turn meaning-matching on or off, and rebuild its index.

    Off by default, and staying that way unless somebody chooses it: it is a
    few hundred megabytes of download and it makes memory behave in a way
    that cannot be read off the page, which is the opposite of everything
    else here.
    """
    from . import semantic

    if args.action == "status":
        print(semantic.explain())
        return 0

    if args.action == "on":
        ok, message = semantic.turn_on()
        print(message)
        if ok:
            count, said = semantic.rebuild()
            print(said)
            return 0 if count or "nothing" in said.lower() else 1
        return 1

    if args.action == "off":
        _ok, message = semantic.turn_off()
        print(message)
        return 0

    count, message = semantic.rebuild()
    print(message)
    return 0 if count or "nothing" in message.lower() else 1


def cmd_plugin(args) -> int:
    """Add, remove and list third-party plugins.

    `add` deliberately does nothing without `--yes`. Installing a plugin is
    trusting its author with everything the assistant can reach, and there is
    no sandbox to fall back on -- so the default is to show what was found and
    stop, the same shape as every other irreversible command here.
    """
    from . import plugins as plugin_module

    if args.action == "list":
        found, problems = plugin_module.load_all(force=True)
        if not found and not problems:
            print("No plugins installed. They live in "
                  f"{plugin_module.plugins_dir()}.")
            print("Add one with: plugin add <folder or zip> --yes")
            return 0
        for one in found:
            held = _package_line(one)
            state = one.problem or (", ".join(one.registered) or held
                                    or "loaded, added nothing")
            print(f"  {one.describe()}")
            print(f"    {state}")
            # Both lines only when it does both -- registering tools AND
            # carrying skills or a workflow. Otherwise `state` already said it.
            if held and not one.problem and one.registered:
                print(f"    {held}")
        for problem in problems:
            print(f"  ! {problem}")
        return 1 if problems else 0

    if args.action == "remove":
        if not args.name:
            print("Which one? plugin remove <name>")
            return 1
        ok, message = plugin_module.remove(args.name)
        print(message)
        return 0 if ok else 1

    # add
    if not args.name:
        print("Add what? plugin add <folder or zip>")
        return 1

    candidate = plugin_module.examine(args.name)
    if candidate.plugin is None:
        print(candidate.problem)
        plugin_module.cleanup(candidate)
        return 1

    print("Would install:")
    print(plugin_module.consent_text(candidate))

    if not args.yes:
        print()
        print("Nothing was installed. Add --yes to do it.")
        plugin_module.cleanup(candidate)
        return 0

    ok, message = plugin_module.install(candidate)
    print()
    print(message)
    return 0 if ok else 1


def _package_line(plugin) -> str:
    """One line saying what a package holds, or "" when it holds nothing."""
    held = plugin.contents
    if not held:
        return ""
    return "contains " + ", ".join(f"{n} {kind}" for kind, n in held.items())


def cmd_workflow(args) -> int:
    """Add, remove, list and run whole jobs.

    A workflow is a job, not a capability: it owns a project folder, carries
    sign-off gates, stops for judgement and resumes. `plugin` is the other
    thing — see `workflows.py` for why the distinction is real and not a
    naming preference.

    `add` refuses without `--yes`, same as `plugin add`. Nothing runs on
    install; `run` is when somebody else's code executes as you.
    """
    from . import workflows as wf

    if args.action == "list":
        found, problems = wf.installed()
        if not found and not problems:
            print(f"No workflows installed. They live in {wf.workflows_dir()}.")
            print("Add one with: workflow add <folder or zip> --yes")
            return 0
        for one in found:
            print(f"  {one.describe()}")
            bits = []
            counts = one.counts
            if counts:
                bits.append(", ".join(f"{n} {k}" for k, n in counts.items()))
            if one.gates:
                bits.append(f"gates {', '.join(one.gates)}")
            if one.requires:
                bits.append("needs " + ", ".join(one.requires))
            if bits:
                print("    " + " | ".join(bits))
            if one.problem:
                print(f"    ! {one.problem}")
        for problem in problems:
            print(f"  ! {problem}")
        return 1 if problems else 0

    if args.action == "remove":
        if not args.name:
            print("Which one? workflow remove <name>")
            return 1
        ok, message = wf.remove(args.name)
        print(message)
        return 0 if ok else 1

    if args.action == "run":
        if not args.name:
            print("Run what? workflow run <name> [arguments]")
            return 1
        one = wf.get(args.name)
        if one is None:
            print(f"No workflow called {args.name} is installed.")
            return 1
        print(f"Running {one.describe()}")
        print(f"  its code, as you, from {one.path}")
        code, message = wf.run(args.name, args.rest)
        if message:
            print(message)
        return code

    if not args.name:
        print("Add what? workflow add <folder or zip>")
        return 1

    candidate = wf.examine(args.name)
    if candidate.workflow is None:
        print(candidate.problem)
        wf.cleanup(candidate)
        return 1

    print("Would install:")
    print(wf.consent_text(candidate))

    if not args.yes:
        print()
        print("Nothing was installed. Add --yes to do it.")
        wf.cleanup(candidate)
        return 0

    ok, message = wf.install(candidate)
    wf.cleanup(candidate)
    print()
    print(message)
    return 0 if ok else 1


def cmd_inspect(args) -> int:
    """What is actually loaded, read from the live registries.

    LOADS THE CONFIGURATION ITSELF RATHER THAN THROUGH `_load_config`
    ----------------------------------------------------------------
    `_load_config` refuses when the `providers:` block names something that
    does not exist, which is right for every command that is about to act on
    it. Here it would mean the one tool for diagnosing that block is the one
    tool the block can switch off. So the trouble is reported as a finding and
    the report still comes out.
    """
    from . import inspect_report

    try:
        loaded = config_module.load()
    except Exception:                                     # noqa: BLE001
        # No configuration at all is a normal state before setup, and the
        # report is still worth having: it says what the software carries.
        loaded = None

    report = inspect_report.gather(loaded)

    if getattr(args, "json", False):
        import json

        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(inspect_report.render(report), end="")
        if loaded is None:
            print()
            print("No configuration yet — in Claude Code, type "
                  "/aki-agent:setup.")

    return 1 if report.get("problems") else 0


def cmd_guide(args) -> int:
    """How to set something up, without leaving the terminal.

    WHY THIS IS A COMMAND AND NOT ONLY A DASHBOARD PAGE
    ---------------------------------------------------
    Half the reasons somebody needs these instructions are reasons the
    dashboard is not running: the PIN is lost, the browser will not open, the
    machine is being set up over SSH. Help that is only reachable from the
    thing that is broken is help nobody gets.
    """
    from . import guides

    topic = (getattr(args, "topic", "") or "").strip()
    if not topic:
        print("Set-up guides. Ask for one by name:")
        print()
        for guide in guides.every():
            minutes = f"{guide.minutes} min" if guide.minutes else "quick"
            print(f"  {guide.topic:<20} {minutes:<8} {guide.title}")
        print()
        print("  aki-agent guide google-oauth")
        return 0

    found = guides.get(topic)
    if found is None:
        print(f"There is no guide called {topic!r}.")
        print("Available: " + ", ".join(guides.topics()))
        return 1
    print(found.text(), end="")
    return 0


def cmd_remote(args) -> int:
    """Open, close, or ask about reaching the dashboard from outside.

    A command as well as a page, for the same reason `guide` is: the moment
    somebody most wants to shut this off may be the moment they cannot get to
    the dashboard to do it.
    """
    from . import exposure

    if getattr(args, "off", False):
        _done, message = exposure.turn_off()
        print(message)
        return 0

    host = (getattr(args, "host", "") or "").strip()
    if not host:
        print(exposure.state().describe())
        return 0

    done, message = exposure.turn_on(host)
    print(message)
    if done:
        print()
        print("Point your tunnel at this dashboard's port, then open that "
              "address and sign in with your PIN.")
        print("Only that exact address is answered. Anything else, including "
              "a tunnel you set up later under a different name, is refused.")
    return 0 if done else 1


def cmd_drive_find(args) -> int:
    """Search the whole Drive, including what was never synced down."""
    from .connectors import google_drive

    if not google_drive.connected():
        print("Google Drive is not connected. The synced Drive folder on "
              "this computer is read directly and needs no sign-in — this is "
              "only for files that were never synced, and for searching the "
              "whole Drive. Connect it on the dashboard's Connections page, "
              "under Files.")
        return 1

    try:
        found = google_drive.find(args.text, limit=args.limit)
    except google_drive.GoogleError as exc:
        print(str(exc))
        return 1

    if not found:
        print(f"Nothing in Drive matching {args.text!r}.")
        return 0

    for one in found:
        line = f"  {one.name}   [{one.file_id}]"
        if one.folder:
            line = f"  {one.name}/   [{one.file_id}]"
        print(line)
        if one.modified:
            print(f"      changed {one.modified[:10]}  {one.kind}")
    return 0


def cmd_drive_read(args) -> int:
    """The text of one Drive file, by the id `drive-find` printed."""
    from .connectors import google_drive

    if not google_drive.connected():
        print("Google Drive is not connected.")
        return 1

    try:
        text, about = google_drive.read(args.file_id, limit=args.limit)
    except google_drive.GoogleError as exc:
        print(str(exc))
        return 1

    print(f"{about.name}  ({about.kind})")
    if about.link:
        print(about.link)
    print()
    print(text)
    return 0


def cmd_agenda(args) -> int:
    """What is on, across every calendar that can be read."""
    from . import calendar_seam

    loaded, problem = _load_config()
    if loaded is None:
        print(problem)
        return 1

    groups, problems = calendar_seam.grouped(limit=args.limit, config=loaded)

    for trouble in problems:
        print(trouble)

    if not groups:
        if problems:
            # Something IS connected -- it just could not be read. Saying
            # "nothing is connected" here would send the person to set up a
            # calendar they already have.
            return 1
        print("No calendars are connected yet. For reading: "
              "connect-calendar --name Work --url <the ICS address>. "
              "For adding and changing, connect Google on the dashboard's "
              "Connections page.")
        return 0

    found = 0
    for label, changeable, entries in groups:
        # The label says which lines can be acted on. A list that mixes a
        # read-only subscription with a writable calendar and says nothing
        # invites "move that to Thursday" against something nobody here can
        # move.
        print(f"{label}{' (can be changed)' if changeable else ''}:")
        for entry in entries:
            line = f"  {entry.when()}  {_clean(entry.summary)}"
            if entry.ref:
                line += f"   [{entry.ref}]"
            print(line)
            found += 1

    if not found:
        print("Nothing on.")
    return 0


def cmd_consult(args) -> int:
    """Ask one of the user's specialists to actually do something.

    `specialists.consult()` was the entire point of the feature and had no
    caller anywhere — so a user could define an expert, see it listed, and
    never be able to put it to work.
    """
    from . import specialists as specialists_module

    specialist = specialists_module.get(args.name)
    if specialist is None:
        known = ", ".join(one.key for one in specialists_module.read_all())
        print(f"There is no specialist called '{args.name}'."
              + (f" You have: {known}" if known else
                 " You have not created one yet."))
        return 1

    loaded, _ = _load_config()
    workspace = (loaded.layout.root
                 if loaded is not None and loaded.layout.root else None)
    consultation = specialists_module.consult(specialist, " ".join(args.task),
                                              workspace=workspace)
    print(_clean(getattr(consultation, "answer", "") or str(consultation)))
    return 0


def cmd_guard(args) -> int:
    """What the session guard can see, and what it will do about it."""
    from . import guard, screens

    found = guard.assess()

    print(screens.box([one.line() for one in found.conditions],
                      title="Session guard"))
    for line in screens.wrap(found.sentence(), screens.WIDTH - 4):
        print(screens.note(line))
    print()
    for line in screens.wrap(guard.FOOTER, screens.WIDTH - 4):
        print(screens.note(line))
    return 0


def cmd_recycle(args) -> int:
    """The switches, and the button.

    Separate from `guard` because looking and acting should not be the same
    command -- somebody checking how full the session is must not be one typo
    away from restarting it.
    """
    from . import guard, screens

    changes = {}
    if args.state == "on":
        changes["auto_recycle"] = True
    elif args.state == "off":
        changes["auto_recycle"] = False
    if args.nightly == "on":
        changes["nightly_recycle"] = True
    elif args.nightly == "off":
        changes["nightly_recycle"] = False
    if args.hour is not None:
        changes["recycle_hour"] = args.hour

    if changes:
        config = guard.save_settings(**changes)
    else:
        config = guard.settings()

    if args.state == "now":
        return _recycle_now(force=args.force)

    auto = "on" if config["auto_recycle"] else "off"
    nightly = ("on at %02d:00" % config["recycle_hour"]
               if config["nightly_recycle"] else "off")
    print(screens.box([
        f"Auto-recycle    {auto}",
        f"Nightly         {nightly}",
    ], title="Recycling"))
    for line in screens.wrap(guard.assess().sentence(), screens.WIDTH - 4):
        print(screens.note(line))
    return 0


def _recycle_now(force: bool = False) -> int:
    """Restart the session by hand.

    `--force` skips the idle check and nothing else. It exists because a
    person pressing a button knows something the guard does not; it does not
    exist so that the automatic path can borrow it.
    """
    from . import guard, launcher, recycle, screens

    if not force:
        advice = recycle.should_recycle(
            idle_seconds_required=guard.IDLE_MINUTES * 60)
        if not advice.safe:
            print(screens.outcome(False, "Not restarted.", advice.reason))
            print(screens.note("Add --force if you meant it anyway."))
            return 1

    # The launcher, by the same name `session.record_launch` stored, so the
    # replacement is identified the way the original was. Never by process
    # name: every agent on a machine is `python` or `node`, and matching on
    # that kills somebody else's.
    script = launcher.launcher_path()
    if not script.exists():
        print(screens.outcome(False, "There is no launcher to restart with.",
                              "Run `doctor` -- it will offer to write one."))
        return 1
    command = [str(script)]

    report = recycle.perform(command, holds_connection=True, confirmed=True,
                             idle_seconds_required=0 if force
                             else guard.IDLE_MINUTES * 60)
    print(screens.outcome(report.completed, report.summary()))
    return 0 if report.completed else 1


def cmd_guard_tick(args) -> int:
    """The scheduled check. Decides, acts, and says which.

    Prints even when it does nothing, because a guard that is silent when
    healthy is indistinguishable from a guard that has stopped running.
    """
    from . import guard

    found = guard.assess()
    print(found.sentence())

    if not found.would_recycle:
        return 0

    print("Restarting the session.")
    return _recycle_now(force=False)


def cmd_survey(args) -> int:
    """Look at an assistant somebody already built, and say what could move.

    Reads names and sizes, not contents. The contents are read afterwards, one
    file at a time, with the user watching — a survey that slurps every file
    has already done the thing it was meant to ask permission for.
    """
    from . import importer

    found = importer.survey(args.folder)
    print(_clean(importer.report(found)))
    return 0 if found.items else 1


def cmd_screen(args) -> int:
    """Draw one of the flow frames.

    WHY A SKILL CALLS THIS INSTEAD OF DRAWING THE BOX ITSELF
    -------------------------------------------------------
    A skill is markdown read by a model, and a model producing an ASCII frame
    is producing a token sequence that merely resembles one. The alignment is
    not guaranteed and does not survive a Chinese label, which is the language
    most of these interviews actually run in. So the skill supplies the words
    and this supplies the geometry -- every run identical, every border square.
    """
    from . import screens

    kind = args.kind
    if kind == "banner":
        print(screens.banner(args.title or "", args.subtitle or ""))
    elif kind == "steps":
        items = []
        for raw in args.item or ():
            label, _, state = raw.rpartition(":")
            items.append((label or raw, (state or "todo").strip()))
        print(screens.steps(items, title=args.title or ""))
    elif kind == "menu":
        if not args.option:
            print("A menu with no options is a dead end. Pass --option.")
            return 1
        print(screens.menu(args.title or "", list(args.option),
                           footer=args.footer or ""))
    elif kind == "flow":
        if not args.node:
            print("A flow with no stages shows nothing. Pass --node.")
            return 1
        print(screens.flow(list(args.node), title=args.title or ""))
    elif kind == "outcome":
        print(screens.outcome(not args.failed, args.title or "",
                              args.detail or ""))
    else:                                                 # pragma: no cover
        print(f"Unknown screen {kind!r}.")
        return 1
    return 0


def cmd_rollback(args) -> int:
    """Put the previous engine back after a bad upgrade.

    The previous one is kept beside the new one until the next upgrade, so
    this is a rename rather than a reinstall -- which matters, because the
    moment somebody wants this is the moment when "download it again" is the
    least helpful thing they could be told.
    """
    from . import engine

    ok, message = engine.rollback()
    print(f"  {'ok' if ok else 'FAILED'} - {message}")
    if not ok:
        return 1

    ok, said = engine.reinstall(engine.engine_dir())
    print(f"  {'ok' if ok else 'FAILED'} - {said}")
    return 0 if ok else 1


def cmd_upgrade_log(args) -> int:
    """Show what the last upgrade actually did."""
    from . import upgrade_log

    found = upgrade_log.latest()
    if found is None:
        print("No upgrade has been recorded yet. They are kept in "
              f"{upgrade_log.folder()}.")
        return 0
    print(found)
    print()
    print(_clean(found.read_text(encoding="utf-8", errors="replace")))
    return 0


def cmd_version(args) -> int:
    """Which version is installed, and where it is running from.

    Asked far more often than it looks: after an update, "did it actually
    update" is the first question, and a date-stamped download does not answer
    it. This does, and it names the folder too, because two copies on one
    machine is exactly the confusion an update creates.
    """
    from . import __version__

    print(f"Aki Agent {__version__}")
    print(f"  running from  {Path(__file__).resolve().parents[2]}")
    print(f"  your files    {paths_module.app_dir()}")
    return 0


def cmd_situation(args) -> int:
    """Work out which kind of install this is, and say so. Changes nothing."""
    from . import situation

    print(situation.detect().as_text())
    return 0


def _repoint_after_upgrade(target: Path, record) -> list[str]:
    """Re-point the launcher and the tasks, in a process that is not this one.

    WHY A SUBPROCESS (the test laptop, 2026-08-20)
    ----------------------------------------------
    Every upgrade printed this, and it was not noticed for a day:

        That did not work: cannot import name 'launcher' from 'aki_agent'

    The cause is a trap specific to a program that replaces itself. By the
    time this step runs, `reinstall()` has repointed the environment at the
    new engine -- but `aki_agent` was imported into *this* process minutes
    earlier, from the old location, and a package that is already imported
    keeps the path it was imported from. Asking it for a submodule it has not
    loaded yet sends it looking in a folder that is now a shim, and the import
    fails.

    Nothing about the new code is wrong; the process asking for it is simply
    standing in the wrong place. So the work is handed to a new process, which
    starts with no such history and loads the version that was just
    installed. That is also what makes it the *new* behaviour doing the
    re-pointing rather than the version being replaced -- the same reason
    `upgrade` reads its manifest from the incoming release.

    A failure to start that process falls back to doing it here, because a
    re-point that happens in the old code beats one that does not happen.
    """
    import subprocess

    from . import engine

    python = engine.venv_python()
    if python is not None and Path(python).exists():
        try:
            # `env` is not decoration. The bootstrap that started this
            # command exported its own `PACKAGE_ROOT/src` on `PYTHONPATH`,
            # a child inherits it, and an explicit `PYTHONPATH` beats the
            # editable install -- so without this the "new process" loads the
            # old package and the whole point of the subprocess is lost. See
            # `engine.env_for`.
            done = subprocess.run(
                [str(python), "-m", "aki_agent.cli", "repair", "--yes"],
                capture_output=True, text=True, timeout=600,
                env=engine.env_for(target))
            for line in (done.stdout or "").splitlines():
                if line.strip():
                    print(f"  {line.strip()}")
            if done.returncode == 0:
                record.step("re-point launcher and scheduled tasks",
                            "done by the new engine, in its own process",
                            ok=True)
                return []
            failures = [(done.stderr or "").strip()[:200] or "repair failed"]
            record.step("re-point launcher and scheduled tasks",
                        "; ".join(failures), ok=False)
            return failures
        except Exception as exc:                          # noqa: BLE001
            print(f"  note: could not re-point in a new process ({exc}); "
                  "doing it here instead")

    failures = _repoint(target)
    record.step("re-point launcher and scheduled tasks",
                "; ".join(failures) if failures else "all re-pointed",
                ok=not failures)
    return failures


def _repoint(root: "Path | None" = None) -> int:
    """Re-point the scheduled tasks and the launcher at `root`.

    Run after an update. Both the scheduled tasks and the launcher hold
    absolute paths into the package folder, and a new release lives in a new
    folder — so without this they keep pointing at the previous version and
    stop working the moment it is cleaned up, without saying anything.

    `root` defaults to the copy running now, which is what `repair` wants.
    Adopting the engine passes the copy it has just made instead, because at
    that moment the process is still importing the old one.
    """
    from . import engine as engine_module
    from . import launcher, schedule, telegram_setup

    root = Path(root) if root else Path(__file__).resolve().parents[2]
    runner = schedule.runner_script(root)

    # Before anything else: the scripts have to be runnable.
    #
    # `repair` is what somebody runs when something is already wrong, and one
    # of the things that is wrong often enough to be worth a line here is a
    # `bin/*.command` that arrived without its executable bit. The launcher
    # backgrounds `dashboard.command`, so the denial goes to a job nobody
    # reads and the only symptom is a dashboard that never appears. Repairing
    # the launcher while leaving the file unrunnable would rewrite the one
    # part that was already correct.
    restored = engine_module.make_runnable(root)
    if restored:
        print(f"  ok -- made {restored} script(s) runnable again")

    # If the scheduler cannot be asked, stop. Do not carry on as though the
    # answer were "no tasks" (2026-08-23).
    #
    # `installed_names()` used to answer [] both when there was nothing
    # installed and when it could not read the list at all — which on a
    # non-English Windows was always. Every task then failed the
    # `is_installed` test below, the loop skipped all of them, and the run
    # finished by announcing "Re-pointed 0 scheduled task(s)" as though that
    # were a result rather than a refusal to look.
    try:
        installed = set(schedule.installed_names())
    except schedule.CouldNotAsk as problem:
        print(f"  FAILED — {problem}")
        print()
        print("Nothing was re-pointed, because the existing tasks could not "
              "be listed. Your scheduled work is untouched but may still be "
              "pointing at the previous version.")
        return 1

    fixed = failed = 0
    for task in schedule.all_tasks():
        if not task.enabled or not schedule.is_installed(task, installed):
            continue

        # Replace in place. Never delete first.
        #
        # This used to call `schedule.remove(task)` and then install. Both
        # platforms already replace an existing job -- `schtasks /Create /F`
        # overwrites, and the plist is rewritten -- so the delete bought
        # nothing and cost a window in which the task existed nowhere. If the
        # install then failed, the user was left without a job they had
        # never asked to lose, and the upgrade said only "Re-pointed 2".
        #
        # That happened on the test laptop, 2026-08-21: an upgrade came back
        # having re-pointed two of six, and four scheduled tasks were simply
        # gone. It did not recur, and the reason it failed that once was
        # never established -- which is exactly why the delete has to go. A
        # step that can lose somebody's work when something else goes wrong
        # is worth removing even when you cannot say what the something else
        # was.
        ok, message = schedule.install(task, runner, confirmed=True)
        print(f"  {'ok' if ok else 'FAILED'} — {task.title}: {message}")
        fixed += 1 if ok else 0
        failed += 0 if ok else 1

    # Only when everything actually landed (2026-08-23).
    #
    # This call used to be unconditional, and that is what made the rest of
    # the failure undiagnosable. `install_root_is_current()` reads what this
    # writes, and `doctor.check_after_update` — the check the README sells as
    # the safety net for exactly this — reads that. So a repair that
    # re-pointed nothing still recorded "everything now points at the current
    # version", and from that moment the staleness could not be detected by
    # the one thing built to detect it.
    #
    # Writing it only on success means a half-finished repair stays visible.
    if not failed:
        schedule.remember_install_root(root)

    launcher_file = launcher.launcher_path()
    if launcher_file.exists():
        loaded, _ = _load_config()
        # Preserved from the existing file rather than guessed: rewriting
        # someone's launcher must not quietly change what it does.
        #
        # Read through `launcher.choices_in` rather than inline here. The
        # inline version recovered two of the three fields and silently
        # dropped `assistant_agent`, so repairing an install -- which is what
        # somebody runs when something is already wrong -- rewrote the
        # launcher without the persona. The assistant started as a plain
        # session from then on, and the repair reported success.
        was = launcher.choices_in(
            launcher_file.read_text(encoding="utf-8", errors="replace"))

        options = launcher.LauncherOptions(
            workspace=(loaded.layout.root
                       if loaded is not None and loaded.layout.root
                       else None),
            title=(loaded.assistant.name if loaded is not None
                   else "Assistant"),
            auto_mode=was["auto_mode"],
            open_dashboard=was["open_dashboard"],
            assistant_agent=was["assistant_agent"],
            # Re-derived from the machine, not preserved from the file. A
            # launcher written before this flag existed does not contain it,
            # and preserving what is there would keep every existing user
            # silently unable to receive messages after a repair -- the repair
            # would report success and change nothing that matters.
            channel_server=(telegram_setup.CHANNEL_SERVER
                            if telegram_setup.status().plugin_installed
                            else ""),
        )
        ok, message = launcher.write_launcher(options, root, confirmed=True)
        print(f"  {'ok' if ok else 'FAILED'} — launcher: {message}")
        failed += 0 if ok else 1

        # The listener the launcher's --channels flag names. Registered in the
        # same step on purpose: one without the other is a session told to
        # listen to something that is not there, or a listener nothing reads.
        try:
            from . import clones

            clones.configure_main()
            print("  ok — channel: this session listens to the dashboard")
        except Exception as exc:                          # noqa: BLE001
            print(f"  FAILED — channel: {exc}")
            failed += 1

    print()
    print(f"Re-pointed {fixed} scheduled task(s) at {root}.")
    if failed:
        print(f"{failed} did not succeed — see the FAILED lines above. "
              "Your scheduled work may still point at the previous version.")

    # The exit code has to disagree with the green box when things went wrong
    # (2026-08-23).
    #
    # This used to `return 0` on every path. It printed "FAILED — Morning
    # summary: …" and then reported success, so `cmd_repair` returned success,
    # so `_repoint_after_upgrade` judged the step by that exit code and drew
    # the green outcome box. Six tasks could fail and the upgrade would say it
    # had gone well.
    return 1 if failed else 0


def cmd_repair(args) -> int:
    """Re-point everything at the copy of the package running now."""
    if not args.yes:
        print("This will re-create the scheduled tasks, rewrite your launcher "
              "so they point at the version now installed, and add anything "
              "missing from your workspace notes.")
        print("Nothing has changed. Re-run with --yes to go ahead.")
        return 0

    failures = _repoint()

    # The workspace notes are topped up here as well as during an upgrade,
    # and that redundancy is the point.
    #
    # AN UPGRADE IS RUN BY THE VERSION BEING REPLACED (2026-08-20)
    # ------------------------------------------------------------
    # `cli upgrade` executes from the engine already installed, so a fix to
    # the top-up lands one version late: 0.12.1 taught it about a new section,
    # and the 0.12.0 -> 0.12.2 upgrade still used 0.12.0's version of it and
    # added nothing. The symptom was a house-rules page saving into a file
    # nothing had been told to read.
    #
    # `plan()` already reads the *incoming* release's manifest for this exact
    # reason. Behaviour cannot be read out of a file the same way, so the
    # answer is a second door: `repair` runs the code that is installed NOW.
    loaded, _ = _load_config()
    if loaded is not None and loaded.layout.root:
        said = scaffold.top_up(loaded.layout.root)
        if said:
            print(f"  ok - {said}")

    return failures


def cmd_uninstall(args) -> int:
    """Take the assistant off this machine, and leave the person's work alone.

    Two steps on purpose. Without `--yes` it prints what would go and what
    would stay and removes nothing, because the one thing a person needs to
    see before uninstalling anything is the list with their own documents
    visibly not on it.
    """
    from . import uninstall as uninstall_module

    config, _ = _load_config()
    the_plan = uninstall_module.plan(config=config,
                                     root=Path(args.root) if args.root else None)
    print(the_plan.describe())

    if not args.yes:
        print()
        print("Nothing removed. Re-run with --yes to go ahead.")
        return 0

    print()
    ok, message = uninstall_module.perform(
        the_plan, confirmed=True, remove_plugin=not args.keep_plugin)
    print(message)
    return 0 if ok else 1


def cmd_make_launcher(args) -> int:
    """Write the thing the user double-clicks.

    `launcher.write_launcher()` was written, tested, and called by nothing but
    its own tests — so a finished install left the user with no way to start
    their assistant except by typing the command themselves. This is the
    product path it was missing.
    """
    from . import backend as backend_module
    from . import launcher

    if args.local_model:
        print(launcher.local_model_note())
        # And what this machine can ACTUALLY run, which is the half that was
        # missing: the note explained the idea and then left the person to
        # guess a model name. 2026-09-05.
        reachable, models = backend_module.models_available()
        if reachable and models:
            print("\n  Models this endpoint is holding right now:")
            for one in models:
                where = ("Ollama's servers -- needs an account, and is metered"
                         if backend_module.is_cloud_model(one)
                         else "on this computer, free")
                print(f"    {one}  ({where})")
            print("\n  Choose one with:  make-launcher --model <name> --yes")
        elif reachable:
            print("\n  The endpoint answered but is holding no models yet. "
                  "Fetch one with `ollama pull qwen2.5:7b`.")
        else:
            print("\n  Nothing is answering on that endpoint, so there is no "
                  "list to show. Start Ollama and try again.")
        return 0

    # Record which brain this session is using, BEFORE writing the launcher,
    # because the launcher has to reproduce it and this is the only moment it
    # is visible: the student's own terminal is running us, and a scheduled
    # task later will not be.
    #
    # `--model` overrides what the environment says, because choosing the
    # model IS a launcher decision. Somebody with three models pulled
    # had no way to say which one their assistant should start with.
    chosen = (getattr(args, "model", "") or "").strip()
    found = backend_module.describe()
    if chosen:
        found.model = chosen
    brain = backend_module.remember(found)
    if chosen:
        print(f"  Model: {chosen}"
              + ("  (Ollama's servers -- needs an account, and is metered)"
                 if backend_module.is_cloud_model(chosen)
                 else "  (on this computer)" if not brain.is_default else ""))
    if not brain.is_default:
        print(f"  Using {brain.sentence()} -- the launcher will start it the "
              f"same way.")
        if brain.needs_token:
            print("  Its access token stays in your environment; it is not "
                  "written into any file here.")

    loaded, problem = _load_config()
    workspace = None
    title = "Assistant"
    agent = args.agent
    if loaded is not None:
        workspace = Path(loaded.layout.root) if loaded.layout.root else None
        title = loaded.assistant.name or title

    from . import telegram_setup

    # Written only for somebody who actually connected Telegram. Passing the
    # flag to a machine without the plugin gives them a launcher that fails on
    # something they never asked for.
    channel = (telegram_setup.CHANNEL_SERVER
               if telegram_setup.status().plugin_installed else "")

    options = launcher.LauncherOptions(
        workspace=workspace,
        assistant_agent=agent,
        auto_mode=args.auto_mode,
        open_dashboard=args.dashboard,
        title=title,
        channel_server=channel,
    )

    if not args.yes:
        print(launcher.describe(options))
        print()
        print("Nothing has been written. Re-run with --yes to create it.")
        return 0

    package_root = Path(__file__).resolve().parent.parent.parent
    ok, message = launcher.write_launcher(options, package_root, confirmed=True)
    print(message)
    return 0 if ok else 1


def cmd_adopt_engine(args) -> int:
    """Copy the engine into the assistant's own folder and use that copy.

    The point of the whole command, in one sentence a user would say: after
    this, the folder you unzipped can be deleted.
    """
    from . import engine

    the_plan = engine.plan()
    print(the_plan.describe())

    if the_plan.already:
        return 0

    if not args.yes:
        print()
        print("Nothing copied. Re-run with --yes to go ahead.")
        return 0

    print()
    ok, message = engine.copy_engine(the_plan)
    print(f"  {'ok' if ok else 'FAILED'} - {message}")
    if not ok:
        return 1

    ok, message = engine.reinstall(the_plan.target)
    print(f"  {'ok' if ok else 'FAILED'} - {message}")
    if not ok:
        return 1

    failures = _repoint(the_plan.target)

    print()
    if failures:
        print("Some of it did not re-point. Keep the folder you installed "
              "from until `doctor` is clean.")
        return 1
    print(f"Done. Everything now runs from {the_plan.target}, and the folder "
          "you installed from can be deleted.")
    return 0


def cmd_upgrade(args) -> int:
    """Move this install onto a newer release, engine and plugin together.

    WHY THIS IS ONE COMMAND (reported 2026-08-19)
    -------------------------------------------
    He was given two sets of instructions -- adopt the engine, then re-point
    the marketplace and reinstall the plugin -- and said, correctly, that this
    is too complicated. The package is two things; that is the package's
    problem, not the user's. So: find the new release, replace the engine,
    re-point the launcher and the scheduled tasks, and hand Claude Code the
    new plugin, in that order, from one word.
    """
    import shutil

    from . import __version__, engine

    source, problem = engine.source_for_upgrade(
        args.source or None,
        allow_unsigned=getattr(args, "allow_unsigned", False))
    if source is None:
        print(problem)
        return 1

    from . import screens

    new_version = engine.version_of(source) or "unknown"
    print(screens.banner(f"Aki Agent  {__version__}  ->  {new_version}",
                         "upgrade"))
    print(screens.note(f"from  {source}"))
    print(screens.note(f"to    {engine.engine_dir()}"))
    print()
    # Shown before anything is touched. The flows were opaque -- a person
    # watching one had no idea which stage they were at or how many were left,
    # and when it failed they could not tell how far it had got.
    print(screens.flow([
        "read the release",
        "build engine.new",
        "check it",
        "swap it in",
        "re-point everything",
        "hand Claude Code the plugin",
    ]))
    print()

    if new_version == __version__:
        # Said, not hidden: three releases went out under one version number,
        # and the only symptom was an upgrade that appeared to do nothing.
        print("  NOTE: that is the version already installed. Carrying on --")
        print("        the files may still differ -- but if nothing changes,")
        print("        this is why.")
        print()

    # What a dry run owes the reader: not "it exists", but what is in the way.
    # A preflight that says "nothing has changed" and is then followed by a
    # destructive failure spends the user's trust before it spends their
    # install -- which is exactly the sequence that happened on 2026-08-20.
    for note in engine.readiness():
        print(f"  note: {note}")

    # Before anything is replaced: has anybody edited this copy?
    #
    # An upgrade replaces the engine folder whole, which is what makes it
    # reversible -- and what makes an edit inside it disappear. Until this
    # existed it disappeared silently: somebody asked their assistant to
    # change a button, the button lived in the engine, and a fortnight later
    # the button went back with no explanation available to anybody.
    #
    # Reported, never refused. Editing this code is allowed and, for a package
    # that is also teaching material, half the point. What was missing was
    # being told.
    from . import local_changes

    changes = local_changes.compare(engine.engine_dir())
    if changes.any:
        print()
        print(f"  You have edited this engine: {changes.sentence()}.")
        for name in (*changes.edited, *changes.added)[:12]:
            print(f"    {name}")
        spare = len(changes.edited) + len(changes.added) - 12
        if spare > 0:
            print(f"    ... and {spare} more")
        print()
        print("  The upgrade replaces the whole engine, so these go back to")
        print("  the shipped version. A copy is kept first -- nothing you")
        print("  wrote is thrown away, but it is not merged either.")

    if not args.yes:
        print("Nothing has changed. Re-run with --yes to go ahead.")
        return 0

    if changes.any:
        kept = local_changes.keep_aside(
            engine.engine_dir(), changes,
            paths_module.app_dir() / "_your-engine-edits" / new_version)
        if kept:
            print()
            print(f"  Your edited files were copied to {kept}")

    from . import upgrade_log

    record = upgrade_log.Recorder(__version__, new_version,
                                  source=source, target=engine.engine_dir())

    the_plan = engine.plan(source=source)
    record.step("planned", "copying: " + ", ".join(the_plan.items))

    # Close the dashboard BEFORE touching the folder it runs from.
    #
    # Left open, it keeps serving the code it loaded at start-up while
    # reporting the new version — which looks exactly like an upgrade that
    # changed nothing.
    if engine.can_see_processes():
        open_dashboards = engine.dashboard_processes()
        if open_dashboards:
            print()
            # Deliberately no number.
            #
            # `dashboard_processes()` counts PROCESSES, and one dashboard is
            # a small chain of them -- the launcher's python, the bootstrap,
            # the server. On the test machine one running dashboard reported
            # as six. Printing that would tell him he has six dashboards
            # open, which is false and alarming, and it is the same mistake
            # as the duplicate-session count on the 20th: a number that is
            # technically what was measured and not what it appears to say.
            print(screens.box([
                "Closing your dashboard.",
                "",
                "It runs from the folder being replaced. Left open it keeps",
                "showing the old pages while claiming the new version.",
            ]))
            stopped, problems = engine.stop_dashboard()
            for problem in problems:
                print(f"  note: could not close {problem}")
            record.step("close the dashboard",
                        f"closed {stopped} process(es)"
                        + (f"; {len(problems)} would not close" if problems
                           else ""),
                        ok=not problems)
            closed_dashboard = stopped
        else:
            closed_dashboard = 0
    else:
        # Cannot tell is not the same as none. Say so rather than proceeding
        # in silence and letting the stale-pages confusion happen anyway.
        print("  note: cannot check for an open dashboard on this machine — "
              "close it yourself before carrying on if it is open.")
        record.step("close the dashboard", "could not check", ok=True)
        closed_dashboard = 0

    ok, message = engine.copy_engine(the_plan)
    print(f"  {'ok' if ok else 'FAILED'} - {message}")
    record.step("replace the engine", message, ok=ok)
    if not ok:
        # The log is finished before returning. The run worth keeping is the
        # one that failed, and this is the moment it would otherwise be lost.
        written = record.finish("failed")
        print()
        print(screens.outcome(False, "Nothing was changed.", message))
        print(screens.note(f"written down in {written}"))
        return 1

    ok, message = engine.reinstall(the_plan.target)
    print(f"  {'ok' if ok else 'FAILED'} - {message}")
    record.step("reinstall the environment", message, ok=ok)
    if not ok:
        written = record.finish("failed")
        print(f"What happened is written down in {written}")
        return 1

    failures = _repoint_after_upgrade(the_plan.target, record)

    loaded, _ = _load_config()
    if loaded is not None and loaded.layout.root:
        from . import scaffold as scaffold_module
        said = scaffold_module.top_up(loaded.layout.root)
        if said:
            print(f'  ok - {said}')
            record.step("workspace", said, ok=True)

    if args.engine_only:
        # For anyone whose plugin is already current, and for
        # tests: this half talks to the real Claude Code install,
        # and a test that mutates a person's plugin registry is
        # not a test, it is damage.
        print()
        print("Left Claude Code's own copy alone (--engine-only).")
        record.step("Claude Code's own copy", "left alone (--engine-only)")
    else:
        print()
        print("Claude Code's own copy:")
        for line in engine.refresh_plugin(the_plan.target):
            print(line)

    # The staging folder only ever holds an unpacked zip, and keeping it would
    # leave a second copy of the engine sitting next to the real one -- which
    # is the confusion this whole command exists to end.
    staging = engine.engine_dir().parent / engine.UNPACK_DIR_NAME
    if staging.exists() and staging in source.parents or source == staging:
        shutil.rmtree(staging, ignore_errors=True)

    # And any empty `engine (2)` folders that have appeared beside the real
    # one. Four of them accumulated on the test machine in a day before anybody
    # noticed, and the noticing was him opening the folder and asking what
    # they were -- which is the wrong way round for something an upgrade can
    # clear on its way past.
    cleared, left = engine.clear_stray_engines()
    if cleared:
        print(f"  ok - tidied {cleared} empty leftover engine folder(s)")
        record.step("tidy", f"removed {cleared} empty engine folder(s)")
    if left:
        print(f"  note: left {', '.join(left)} alone — not empty, so not mine "
              "to delete")
        record.step("tidy", f"left alone: {', '.join(left)}", ok=True)

    print()
    if failures:
        print("Some of it did not re-point -- run `doctor` before deleting "
              "anything.")
        return 1
    written = record.finish("done")
    print(screens.outcome(True, f"You are on {new_version}."))
    print(screens.note(f"written down in {written}"))
    print(screens.note("the engine you had is kept; `rollback` puts it back"))
    # Last, alone, and as a consequence rather than a courtesy.
    #
    # It was one clause in the middle of a paragraph, sitting beside "you are
    # on 0.15.0". The maintainer upgraded ten times in a day, read that line ten times,
    # and his session stayed on the code it had loaded on the 17th -- so none
    # of it took effect. A caveat that reads like a formality gets treated
    # like one.
    if closed_dashboard:
        print()
        print(screens.note("your dashboard was closed for this upgrade — "
                           "the launcher opens it again"))

    print()
    print(screens.box([
        "RESTART your assistant now.",
        "",
        "Until you do, it keeps running the version it started with —",
        "which looks exactly like this upgrade having done nothing.",
    ]))
    print(screens.note("close the window, then run the launcher"))
    return 0


def cmd_library(args) -> int:
    """List, search, turn on and turn off what the package ships.

    The setup interview calls `--suggest "<what they do>"` and then `--on`
    with the keys it chose; the dashboard calls the same functions directly.
    One surface, so the two cannot drift.
    """
    from . import library

    if args.on:
        failures = 0
        for key in args.on:
            ok, message = library.activate(key)
            print(f"  {'ok' if ok else 'FAILED'} - {message}")
            failures += 0 if ok else 1
        print()
        print("Restart Claude Code to pick these up.")
        return 1 if failures else 0

    if args.off:
        failures = 0
        for key in args.off:
            ok, message = library.deactivate(key)
            print(f"  {'ok' if ok else 'FAILED'} - {message}")
            failures += 0 if ok else 1
        return 1 if failures else 0

    if args.suggest:
        items = library.suggest(args.suggest)
        print(f"For \"{args.suggest}\" — {len(items)} of "
              f"{len(library.catalogue())}:")
        print()
        for item in items:
            mark = "core" if item.core else ", ".join(item.industries)
            print(f"  {item.key:32} {item.kind:11} {mark}")
        print()
        print("Turn them on with:  library --on " +
              " ".join(item.key for item in items[:3]) + " ...")
        return 0

    found = library.search(query=args.find or "", category=args.category or "",
                           industry=args.industry or "", kind=args.kind or "")
    active = library.active_keys()

    print(f"{len(found)} of {len(library.catalogue())} items")
    print()
    for item in found:
        state = "ON " if item.key in active else "   "
        flag = "" if item.confidence == "high" else "  (draft)"
        print(f"  {state}{item.key:32} {item.category:28} {item.name}{flag}")

    if not args.find and not args.category and not args.industry:
        print()
        print("Categories: " + " | ".join(library.categories()))
        print("Filter with --find, --category, --industry, --kind.")
    return 0


# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        # argparse prints this at the top of every `--help`, so it has to be
        # a command that runs. `python -m aki_agent.cli` is not one on an
        # install: the package is in the assistant's virtual environment.
        prog=_program_name(),
        description="What the skills call. Plain text in, plain text out.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    listing = subparsers.add_parser("projects", help="list the work")
    listing.set_defaults(func=cmd_projects)

    finding = subparsers.add_parser("search", help="ranked search of memory")
    finding.add_argument("query", nargs="+")
    finding.add_argument("--limit", type=int, default=10)
    finding.set_defaults(func=cmd_search)

    chatting = subparsers.add_parser(
        "search-chat", help="search what you and your assistant have SAID")
    chatting.add_argument("query", nargs="+")
    chatting.add_argument("--limit", type=int, default=10)
    chatting.add_argument("--days", type=int, default=0,
                          help="only the last N days")
    chatting.set_defaults(func=cmd_search_chat)

    noticing = subparsers.add_parser(
        "skill-ideas", help="things you keep asking for that could be skills")
    noticing.add_argument("--limit", type=int, default=5)
    noticing.add_argument("--not-this", default="",
                          help="stop offering the idea with this key")
    noticing.set_defaults(func=cmd_skill_ideas)

    listing_facts = subparsers.add_parser("recall", help="everything remembered")
    listing_facts.add_argument("--limit", type=int, default=20)
    listing_facts.set_defaults(func=cmd_recall)

    today = subparsers.add_parser("today", help="today's log")
    today.set_defaults(func=cmd_today)

    wrapping_up = subparsers.add_parser(
        "eod", help="write today up now (the same job as the 18:30 wrap-up)")
    wrapping_up.set_defaults(func=cmd_eod)

    days = subparsers.add_parser("days", help="recent daily logs")
    days.add_argument("--count", type=int, default=7)
    days.set_defaults(func=cmd_days)

    remembering = subparsers.add_parser("remember", help="write down a fact")
    remembering.add_argument("summary", nargs="+")
    remembering.add_argument("--body", default="")
    remembering.set_defaults(func=cmd_remember)

    logging_ = subparsers.add_parser("log", help="add a line to today's log")
    logging_.add_argument("text", nargs="+")
    logging_.set_defaults(func=cmd_log)

    listing_specialists = subparsers.add_parser(
        "specialists", help="list the specialists")
    listing_specialists.set_defaults(func=cmd_specialists)

    making = subparsers.add_parser("new-specialist",
                                   help="create a specialist (read-only by default)")
    making.add_argument("name")
    making.add_argument("--purpose", required=True,
                        help="one line: what it is for")
    making.add_argument("--brief", default="",
                        help="how it should work; a sensible default is used if omitted")
    making.add_argument("--reads", nargs="*",
                        help="folders it may read; omit for the whole workspace")
    making.add_argument("--may-write", action="store_true",
                        help="allow it to write -- sandbox only, never documents")
    making.set_defaults(func=cmd_new_specialist)

    building = subparsers.add_parser(
        "scaffold", help="create (or complete) the workspace folders")
    building.add_argument("--root", help="where to build it "
                                         "(default: the folder in settings)")
    building.add_argument("--workspaces", help="comma-separated workspace names; "
                                          "each gets a number prefix")
    building.add_argument("--no-examples", action="store_true",
                          help="workspaces only, no example project")
    building.add_argument("--yes", action="store_true",
                          help="actually create it (without this, only plan)")
    building.set_defaults(func=cmd_scaffold)

    creating = subparsers.add_parser("new-project",
                                     help="create a project in an workspace")
    creating.add_argument("workspace")
    creating.add_argument("name")
    creating.add_argument("--yes", action="store_true",
                          help="actually create it (without this, only plan)")
    creating.set_defaults(func=cmd_new_project)

    removing = subparsers.add_parser(
        "uninstall", help="remove the assistant, keeping all your work")
    removing.add_argument("--root", default="",
                          help="the assistant's folder, if it cannot be found")
    removing.add_argument("--keep-plugin", action="store_true",
                          help="leave the Claude Code plugin installed")
    removing.add_argument("--yes", action="store_true",
                          help="actually remove it (without this, only list)")
    removing.set_defaults(func=cmd_uninstall)

    adopting = subparsers.add_parser(
        "adopt-engine",
        help="copy the engine into your own folder so the installer can go")
    adopting.add_argument("--yes", action="store_true",
                          help="actually copy it (without this, only plan)")
    adopting.set_defaults(func=cmd_adopt_engine)

    upgrading = subparsers.add_parser(
        "upgrade", help="move onto a newer release, engine and plugin at once")
    upgrading.add_argument("--from", dest="source", default="",
                           help="the new zip or unzipped folder "
                                "(default: the newest one in Downloads)")
    upgrading.add_argument("--engine-only", action="store_true",
                           help="do not touch the Claude Code plugin")
    upgrading.add_argument("--yes", action="store_true",
                           help="actually do it (without this, only report)")
    upgrading.add_argument("--allow-unsigned", action="store_true",
                           dest="allow_unsigned",
                           help="install a release whose signature could not "
                                "be verified (you are vouching for it)")
    upgrading.set_defaults(func=cmd_upgrade)

    stocking = subparsers.add_parser(
        "library", help="what the package ships, and what is switched on")
    stocking.add_argument("--find", default="", help="free-text search")
    stocking.add_argument("--category", default="")
    stocking.add_argument("--industry", default="")
    stocking.add_argument("--kind", default="", choices=["", "skill",
                                                         "specialist"])
    stocking.add_argument("--suggest", default="",
                          help="what to switch on for this occupation")
    stocking.add_argument("--on", nargs="*", help="turn these on, by key")
    stocking.add_argument("--off", nargs="*", help="turn these off, by key")
    stocking.set_defaults(func=cmd_library)

    state = subparsers.add_parser(
        "state", help="what the last session was in the middle of")
    state.set_defaults(func=cmd_state)

    saving = subparsers.add_parser(
        "checkpoint", help="save what you are in the middle of, now")
    saving.set_defaults(func=cmd_checkpoint)

    restarting = subparsers.add_parser(
        "recycle-check", help="is it safe to restart right now")
    restarting.add_argument("--idle-seconds", type=float, default=900)
    restarting.set_defaults(func=cmd_recycle_check)

    sched = subparsers.add_parser(
        "schedule-status", help="what is scheduled and what is not")
    sched.set_defaults(func=cmd_schedule_status)

    sched_install = subparsers.add_parser(
        "schedule-install", help="install the built-in schedule")
    sched_install.add_argument("--yes", action="store_true",
                               help="actually install (without this, only describe)")
    sched_install.add_argument(
        "--anyway", action="store_true",
        help=("install even from an administrator window. The tasks will be "
              "owned by the administrator account and the dashboard will not "
              "be able to switch them off."))
    sched_install.set_defaults(func=cmd_schedule_install)

    launching = subparsers.add_parser(
        "make-launcher", help="write the file the user double-clicks")
    launching.add_argument("--auto-mode", action="store_true",
                           help="run without asking permission at each step")
    launching.add_argument("--dashboard", action="store_true",
                           help="open the dashboard alongside the assistant")
    launching.add_argument("--agent", default="",
                           help="persona to load, if they have one")
    launching.add_argument("--local-model", action="store_true",
                           help="what running against Ollama takes, and which "
                                "models this machine can serve right now")
    launching.add_argument("--model", default="",
                           help="which model the launcher should start -- the "
                                "choice belongs here, not in the environment")
    launching.add_argument("--yes", action="store_true",
                           help="actually write it (without this, only describe)")
    launching.set_defaults(func=cmd_make_launcher)

    version_check = subparsers.add_parser(
        "version", help="which version is installed, and from where")
    version_check.set_defaults(func=cmd_version)

    checking_situation = subparsers.add_parser(
        "situation", help="is this a first install, an update, or a merge?")
    checking_situation.set_defaults(func=cmd_situation)

    repairing = subparsers.add_parser(
        "repair", help="re-point the schedule and launcher after an update")
    repairing.add_argument("--yes", action="store_true")
    repairing.set_defaults(func=cmd_repair)

    checking = subparsers.add_parser(
        "channel-check", help="say if the assistant cannot reach you")
    checking.set_defaults(func=cmd_channel_check)

    happenings = subparsers.add_parser(
        "events", help="what has been happening")
    happenings.add_argument("--limit", type=int, default=20)
    happenings.add_argument("--kind", default="")
    happenings.set_defaults(func=cmd_events)

    asking = subparsers.add_parser(
        "ask", help="put a question or draft in front of the user")
    asking.add_argument("title", nargs="+")
    asking.add_argument("--body", default="")
    asking.add_argument("--kind", choices=("question", "draft"),
                        default="question")
    asking.add_argument("--option", action="append",
                        help="key:label -- repeat for each answer offered")
    asking.add_argument("--task", default="",
                        help="what to learn from the decision, e.g. 'email'")
    asking.add_argument("--context", default="",
                        help="ties this to whatever raised it")
    asking.set_defaults(func=cmd_ask)

    waiting = subparsers.add_parser(
        "waiting", help="what is waiting for the user")
    waiting.set_defaults(func=cmd_waiting)

    answering = subparsers.add_parser("answer", help="answer one of them")
    answering.add_argument("id")
    answering.add_argument("option", nargs="?", default="")
    answering.add_argument("--text", nargs="*",
                           help="answer in the user's own words instead")
    answering.add_argument("--dismiss", action="store_true")
    answering.set_defaults(func=cmd_answer)

    keeping = subparsers.add_parser(
        "remember-key",
        help="put one secret in the OS password manager (value on stdin)")
    keeping.add_argument("name")
    keeping.add_argument(
        "--value", default="",
        help=("the secret itself. Prefer stdin: a value passed here is "
              "visible in the process list and lands in shell history."))
    keeping.set_defaults(func=cmd_remember_key)

    telegram = subparsers.add_parser(
        "connect-telegram", help="set up Telegram, one step at a time")
    telegram.add_argument("--describe", action="store_true",
                          help="what to do, and where it has got to")
    telegram.add_argument("--token", default="",
                          help="the bot token from BotFather")
    telegram.add_argument("--allow", default="",
                          help="a Telegram user id allowed to talk to it")
    telegram.set_defaults(func=cmd_connect_telegram)

    mail_add = subparsers.add_parser(
        "connect-mail", help="add a mailbox (password goes to the OS store)")
    mail_add.add_argument("address")
    mail_add.add_argument("--label", default="")
    mail_add.add_argument("--imap-host", default="")
    mail_add.add_argument("--smtp-host", default="")
    mail_add.add_argument("--imap-port", type=int, default=0,
                          help="only if your provider is not on 993")
    mail_add.add_argument("--smtp-port", type=int, default=0,
                          help="only if your provider is not on 587")
    mail_add.add_argument("--password", default="",
                          help="an app password, never your login password")
    mail_add.add_argument("--may-send", action="store_true",
                          help="allow sending; without it, drafts only")
    mail_add.set_defaults(func=cmd_connect_mail)

    mail_read = subparsers.add_parser(
        "mail", help="what is in the mailbox (headers only, never marks read)")
    mail_read.add_argument("--limit", type=int, default=10)
    mail_read.add_argument("--unread", action="store_true",
                           help="only messages you have not opened")
    mail_read.add_argument("--address", default="",
                           help="which mailbox, if more than one is connected")
    mail_read.set_defaults(func=cmd_mail)

    cal_add = subparsers.add_parser(
        "connect-calendar", help="subscribe to a calendar (read-only)")
    cal_add.add_argument("--name", required=True)
    cal_add.add_argument("--url", required=True)
    cal_add.set_defaults(func=cmd_connect_calendar)

    outside = subparsers.add_parser(
        "tools", help="which outside services are set up, and for what")
    from . import apis as apis_module

    outside.add_argument(
        "--job", default="", choices=("",) + apis_module.JOB_KEYS,
        help="ask about one job only")
    outside.set_defaults(func=cmd_tools)

    meaning = subparsers.add_parser(
        "memory-search",
        help="match memory by meaning as well as words (off by default)")
    meaning.add_argument("action", nargs="?", default="status",
                         choices=("status", "on", "off", "reindex"))
    meaning.set_defaults(func=cmd_memory_search)

    plugging = subparsers.add_parser(
        "plugin", help="add, remove and list third-party plugins")
    plugging.add_argument("action", choices=("list", "add", "remove"))
    plugging.add_argument("name", nargs="?", default="",
                          help="a folder or zip to add, or the name to remove")
    plugging.add_argument("--yes", action="store_true",
                          help="actually install it (without this, only report)")
    plugging.set_defaults(func=cmd_plugin)

    flowing = subparsers.add_parser(
        "workflow", help="add, remove, list and run whole jobs")
    flowing.add_argument("action", choices=("list", "add", "remove", "run"))
    flowing.add_argument("name", nargs="?", default="",
                         help="a folder or zip to add, or the name to run or remove")
    flowing.add_argument("rest", nargs="*", default=[],
                         help="arguments passed through to the workflow")
    flowing.add_argument("--yes", action="store_true",
                         help="actually install it (without this, only report)")
    flowing.set_defaults(func=cmd_workflow)

    looking = subparsers.add_parser(
        "inspect", help="what is actually loaded right now")
    looking.add_argument("--json", action="store_true",
                         help="machine-readable, for the dashboard")
    looking.set_defaults(func=cmd_inspect)

    guiding = subparsers.add_parser(
        "guide", help="how to set something up, step by step")
    guiding.add_argument("topic", nargs="?", default="",
                         help="leave empty to list every guide")
    guiding.set_defaults(func=cmd_guide)

    remote = subparsers.add_parser(
        "remote", help="reach the dashboard from outside, on purpose")
    remote.add_argument("host", nargs="?", default="",
                        help="the address your tunnel gives you; empty to ask")
    remote.add_argument("--off", action="store_true",
                        help="close it again")
    remote.set_defaults(func=cmd_remote)

    # Drive, for what the synced folder cannot reach. Two verbs, both read.
    finding_files = subparsers.add_parser(
        "drive-find", help="search Google Drive, including unsynced files")
    finding_files.add_argument("text", nargs="?", default="",
                               help="words in the name or the contents")
    finding_files.add_argument("--limit", type=int, default=20)
    finding_files.set_defaults(func=cmd_drive_find)

    reading_file = subparsers.add_parser(
        "drive-read", help="the text of one Drive file, by id")
    reading_file.add_argument("file_id", help="the id drive-find printed")
    reading_file.add_argument("--limit", type=int, default=200000,
                              help="characters, before it is cut")
    reading_file.set_defaults(func=cmd_drive_read)

    agenda = subparsers.add_parser("agenda", help="what is coming up")
    agenda.add_argument("--limit", type=int, default=5)
    agenda.set_defaults(func=cmd_agenda)

    # Writing to a diary. Each of these does nothing without --yes and prints
    # what it *would* do instead, which is the same shape as every other
    # command here that touches the real world.
    adding = subparsers.add_parser(
        "calendar-add", help="put something in the diary (Google)")
    adding.add_argument("title")
    adding.add_argument("--start", required=True, help="2026-09-12 14:30")
    adding.add_argument("--end", default="")
    adding.add_argument("--location", default="")
    adding.add_argument("--description", default="")
    adding.add_argument("--calendar", default="primary")
    adding.add_argument("--yes", action="store_true", help="actually add it")
    adding.set_defaults(func=cmd_calendar_add)

    changing = subparsers.add_parser(
        "calendar-change", help="move or retitle something (Google)")
    changing.add_argument("event_id")
    changing.add_argument("--title", default=None)
    changing.add_argument("--start", default="")
    changing.add_argument("--end", default="")
    changing.add_argument("--location", default=None)
    changing.add_argument("--calendar", default="primary")
    changing.add_argument("--yes", action="store_true")
    changing.set_defaults(func=cmd_calendar_change)

    cancelling = subparsers.add_parser(
        "calendar-cancel", help="take something out of the diary (Google)")
    cancelling.add_argument("event_id")
    cancelling.add_argument("--calendar", default="primary")
    cancelling.add_argument("--yes", action="store_true")
    cancelling.set_defaults(func=cmd_calendar_cancel)

    consulting = subparsers.add_parser(
        "consult", help="put one of your specialists to work")
    consulting.add_argument("name")
    consulting.add_argument("task", nargs="+")
    consulting.set_defaults(func=cmd_consult)

    vetting = subparsers.add_parser(
        "check", help="check a draft before it is shown, recorded or sent")
    vetting.add_argument("text", nargs="*", help="the draft itself")
    vetting.add_argument("--file", help="a file holding the draft")
    vetting.add_argument("--sources", nargs="*",
                         help="what it rests on: files, extracts, reasoning")
    vetting.set_defaults(func=cmd_check)

    watching = subparsers.add_parser(
        "guard", help="how full the session is, and what will happen")
    watching.set_defaults(func=cmd_guard)

    ticking = subparsers.add_parser(
        "guard-tick", help="the scheduled check (decides and acts)")
    ticking.set_defaults(func=cmd_guard_tick)

    cycling = subparsers.add_parser(
        "recycle", help="the auto/nightly switches, and restart now")
    cycling.add_argument("state", nargs="?", choices=["on", "off", "now"],
                         help="omit to see the current settings")
    cycling.add_argument("--nightly", choices=["on", "off"])
    cycling.add_argument("--hour", type=int,
                         help="the hour for the nightly restart, 0-23")
    cycling.add_argument("--force", action="store_true",
                         help="with `now`: restart even if it looks busy")
    cycling.set_defaults(func=cmd_recycle)

    surveying = subparsers.add_parser(
        "survey", help="what could be brought over from an agent you already have")
    surveying.add_argument("folder")
    surveying.set_defaults(func=cmd_survey)

    drawing = subparsers.add_parser(
        "screen", help="draw one of the install/upgrade frames")
    drawing.add_argument("kind", choices=["banner", "steps", "menu", "flow",
                                          "outcome"])
    drawing.add_argument("--title", default="")
    drawing.add_argument("--subtitle", default="")
    drawing.add_argument("--detail", default="")
    drawing.add_argument("--footer", default="")
    drawing.add_argument("--item", action="append",
                         help="steps: 'label:done' / 'label:now' / 'label:todo'")
    drawing.add_argument("--option", action="append", help="menu: one choice")
    drawing.add_argument("--node", action="append", help="flow: one stage")
    drawing.add_argument("--failed", action="store_true",
                         help="outcome: draw it as a failure")
    drawing.set_defaults(func=cmd_screen)

    reverting = subparsers.add_parser(
        "rollback", help="go back to the engine you had before the upgrade")
    reverting.set_defaults(func=cmd_rollback)

    recounting = subparsers.add_parser(
        "upgrade-log", help="what the last upgrade did")
    recounting.set_defaults(func=cmd_upgrade_log)

    guarding = subparsers.add_parser(
        "sentinel", help="turn the built-in check on or off")
    guarding.add_argument("state", nargs="?", choices=["on", "off"],
                          help="omit to be told which it is")
    guarding.set_defaults(func=cmd_sentinel)

    return parser


def main(argv: list[str] | None = None) -> int:
    # A Windows console defaults to the legacy code page, which cannot encode
    # a Chinese character or an em dash -- so the moment output contains one,
    # printing raises and the command dies HALF FINISHED, having already shown
    # some of its answer. It reads as the feature breaking on that particular
    # question. Found 2026-08-24 running `search-chat` on the Surface: it
    # printed two of ten matches and then reported a codec error.
    for stream in ("stdout", "stderr"):
        try:
            getattr(sys, stream).reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                 # noqa: BLE001
            pass

    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception as problem:
        # Rule 1. A person is reading this through an assistant, and a
        # traceback tells them nothing they can act on.
        print(f"That did not work: {problem}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
