# What the five words mean

Settled 2026-08-29, after the maintainer put it plainly: **. Before that day the code had four of
these five ideas built and no page saying how they relate, so each one had
grown its own door. This is the page. If a future change makes one of these
words mean something else, change it here first.

## Tool

An ability. Smaller than a skill. `image gen` is a tool; so is *send a
Telegram message*, *read the calendar*, *fetch a page*.

Tools live in `seams.py`. A seam is a named slot — `calendar`, `notify` — and
a tool is something registered into one. That is why a plugin's `plugin.py`
has a `register(seams)` function: registering tools is the only thing that
needs code to run at install.

## Skill

A way of doing something. Prose, not code — an SOP the assistant reads and
follows. Small enough to be one move.

Skills live in `library/skills/<key>/SKILL.md`, and now also in a plugin's
own `skills/` folder (either `<key>/SKILL.md` or a flat `<key>.md`).

## Workflow

Also an SOP, but for a **whole job** rather than one move. The test is not
length. It is these four, and a workflow has all of them:

- it owns a **project folder** — state that outlives the conversation
- it has **gates** — points where a person signs off before it goes on
- it **resumes** — you can stop halfway and come back tomorrow
- it ends in a **deliverable** — something you hand to somebody else

A skill has none of those. Asked to write an email, a skill writes the email.
A feasibility study is a workflow: it runs for days, stops for judgement it is
not entitled to make, and ends in a PDF that goes to a client.

Workflows live in `<config>/workflows/<name>/WORKFLOW.md`, and now also in a
plugin's own `workflows/` folder.

## Panel

A screen. UI, declared as data rather than coded — `panels.py` has said so
since it was written: *"a workspace's own screen, declared rather than
coded"*.

Panels live in `library/panels/`, the user's own `panels/`, and a plugin's
`panels/`.

## Plugin

**Not a fifth kind of thing. A box.** A plugin is how the other four arrive
and leave together:

```
my-plugin/
├── PLUGIN.md      the manifest — name, version, what it is for
├── plugin.py      optional: register(seams) — only needed to add TOOLS
├── skills/        <key>/SKILL.md, or flat <key>.md
├── workflows/     <name>/WORKFLOW.md
└── panels/        <key>.md
```

A whole trade arrives as one thing and is removed as one thing. That is the
entire point, and it is why the contents **stay inside the plugin folder**
rather than being copied out to their own homes on install: copy them out and
nobody can tell later which loose skill came from which package, so nothing
can be cleanly uninstalled. Instead each registry looks in —
`panels.plugin_panels_dirs()`, `library.plugin_skills_dirs()`,
`workflows.plugin_workflow_dirs()`. Delete the plugin folder and everything
it brought is gone, with nothing left behind.

### Counted, not declared

There is no `contains:` field in `PLUGIN.md`, deliberately. A declared list is
a promise; `plugins.contents()` counts the folders on disk, so the number
shown to somebody before they install is the number they actually get. A
manifest claiming six skills while shipping two would be a lie the software
told on the author's behalf.

### A package with no `plugin.py` is not broken

It is a package that carries no tools. Until this was written down, every
skills-only plugin was reported as broken on every load — the code knew only
about tools, so anything else looked like an omission.

### Precedence, and why it differs by kind

| kind | who wins a name clash | why |
|---|---|---|
| panels | the plugin's | a screen is meant to be replaceable; that is how forking a panel works |
| skills | ours | a skill is instruction the assistant follows, and a package should not be able to quietly redefine one of ours by choosing its name |
| workflows | one installed directly | what somebody put there by hand beats what arrived in a box |

## The two doors

`plugin add` installs a box. `workflow add` installs a bare workflow straight
into `<config>/workflows/`. The second is a shortcut, not a second model — it
exists because a workflow on its own is a normal thing to hand somebody, and
making them wrap it in a package first would be ceremony. Both show what they
will install before installing it, and neither runs anything on install.
