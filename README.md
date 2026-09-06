# Aki Agent

An assistant for people who do not write code.

Answer some questions, and it configures itself around **your** work — not a
developer's. No API key. No server. No Docker. Nothing to keep running in a
data centre. It installs inside Claude Code, on your own computer, and works
as you.

---

## Honest status, before you spend an evening on it

This is a real project, not a demo, and it is also not finished. What that
means in specifics:

| | |
|---|---|
| Version | 0.47.0 |
| Tests | 1,947, all passing |
| Run on Windows | Yes, daily, by the author |
| Run on macOS | **Never.** Not one line has knowingly executed on a Mac. The Mac code is written and reviewed; it is not observed |
| Installed by somebody other than the author | Twice, both times with the author present |
| Licence | MIT |

The failure this codebase is most prone to is not crashing. It is a button
that looks like it worked and did nothing — and an audit on 2026-09-05 found
several, in code that had a thousand passing tests over it. They are fixed and
written up. Others are probably still there. If you find one, that is the most
useful thing you can send.

---

## Is this for you?

**Probably yes if:** you have a Claude subscription, you do the same handful of
jobs over and over, and you have wished something would remember where you got
to.

**Probably not yet if:** you need it on a phone with nothing on your computer,
you need several people to share one assistant, or you need it to keep working
while your laptop is shut. None of those exist here, by choice — see
[Design limits](#design-limits-stated-rather-than-half-solved).

---

## Part 1 — Getting to a working assistant

Written for somebody with nothing installed. If you already have Claude Code
running, skip to [Step 3](#step-3--install-it).

There are **two paths**, and the only difference is which brain your assistant
thinks with. Pick one now; you can change later.

| | **Path A — your Claude subscription** | **Path B — a model on your own computer (Ollama)** |
|---|---|---|
| Who it is for | Almost everybody | People who want nothing leaving the machine, or who have no subscription |
| Costs | Your existing Claude subscription | Nothing, if the model runs locally |
| Speed and quality | Good | Slower, and noticeably weaker at multi-step work — which is most of what an assistant does |
| How well tested | This is the tested path | Supported and wired up, but **not tested end to end**. Expect rough edges |

> **If you are not sure, choose Path A.** Path B is real and this package
> supports it properly — it records which model you chose and starts it the
> same way every time, including in scheduled tasks. But it is the less
> travelled road here, and it is honest to say so before you walk it.

### Step 1 — Install Python

Aki Agent uses Python for its own housekeeping. You will never have to write
any.

1. Go to <https://www.python.org/downloads/> and press the big download
   button.
2. Run the installer.
3. **On Windows, tick "Add Python to PATH" on the first screen.** It is easy to
   miss and everything afterwards depends on it.

You need version **3.10 or newer**, which is anything you download today.

### Step 2 — Install Claude Code, and give it a brain

Claude Code is the program Aki Agent lives inside. Get it from
<https://claude.com/claude-code> and follow its own installer.

**Path A — your Claude subscription**

Open a terminal (Windows: *Terminal* or *Command Prompt*; Mac: *Terminal*)
and type:

```
claude
```

The first run walks you through signing in. When it stops at a prompt and
waits for you, you are done with this step. Type `/exit` to leave.

**Path B — a model on your own computer**

1. Install Ollama from <https://ollama.com>.
2. Fetch a model. In a terminal:

   ```
   ollama pull qwen2.5:7b
   ```

   That one is about 4.7 GB and is a reasonable all-rounder. Bigger models are
   better and slower; your computer's memory decides how far you can go.

3. Tell Claude Code to use it. In the **same terminal window** you will start
   your assistant from:

   **Windows (PowerShell)**
   ```powershell
   $env:ANTHROPIC_AUTH_TOKEN = "ollama"
   $env:ANTHROPIC_API_KEY = ""
   $env:ANTHROPIC_BASE_URL = "http://localhost:11434"
   claude --model qwen2.5:7b
   ```

   **macOS / Linux**
   ```bash
   export ANTHROPIC_AUTH_TOKEN=ollama
   export ANTHROPIC_API_KEY=
   export ANTHROPIC_BASE_URL=http://localhost:11434
   claude --model qwen2.5:7b
   ```

   `ollama` is not a password. Claude Code insists on sending something, and
   Ollama ignores what it is.

> **Those settings live only in that terminal window.** Close it and they are
> gone — which would leave your assistant starting up tomorrow morning talking
> to a service you are not signed in to, and failing in a way nobody could
> diagnose.
>
> Aki Agent handles this for you: it notices which brain you are on and writes
> it into the file you double-click and into every scheduled task. That is why
> Step 4 matters more on Path B than on Path A.

### Step 3 — Install it

In Claude Code (`claude` in a terminal — on Path B, the terminal from Step 2),
two lines:

```
/plugin marketplace add cowballwong/aki-agent
/plugin install aki-agent@aki-agent
```

There is nothing to download, unzip or delete. Claude Code fetches the
repository itself and keeps its own copy in its plugin folder.

> **Installed Aki Agent from a zip before?** Do not run those two lines. They
> would leave you with an assistant that looks updated and quietly stops doing
> anything unattended. Go to
> [Coming from a zip install](#coming-from-a-zip-install) instead — it is a
> one-time job, and it explains why.

<details>
<summary>Installing from a zip instead</summary>

Releases are also published as a `.zip`, for a machine with no access to
GitHub or somebody who would rather read the whole thing before running it.
Unzip it anywhere, then:

```
/plugin marketplace add <the folder you unzipped>
/plugin install aki-agent@aki-agent
```

Then **delete the zip and the unzipped folder.** What you unzipped is a
delivery box, not your assistant: the engine has been copied into Claude
Code's own plugin folder, and nothing you make should ever be saved inside
the box.

A release zip is signed. `aki upgrade` checks that signature and refuses a
zip that is not one of ours, or one that has been altered since it was
built — see [SECURITY.md](SECURITY.md).
</details>

### Step 4 — Let it set itself up

```
/aki-agent:setup
```

A ten-to-twenty minute conversation. It asks who you are, what you call your
work, what you want to see at a glance — and then writes your configuration
and checks it works. There is nothing to fill in afterwards.

Near the end it asks **two real questions**. Neither is a formality:

**Should it get on with things, or ask each time?**
Auto mode acts without stopping for permission at each small step: far less
interrupting, and genuinely less supervised. Most people want it eventually.
Starting with *ask* and changing your mind later costs nothing.

**Which model should it start with?**
On Path A, your subscription answers this. On Path B, this is where you
choose — and you can see what your machine actually has:

```
python ~/.aki-agent/aki.py aki_agent.cli make-launcher --local-model
```

That lists every model your Ollama is holding and says of each whether it runs
on your computer (free) or on Ollama's servers (needs an account, and is
metered). Then:

```
python ~/.aki-agent/aki.py aki_agent.cli make-launcher --model qwen2.5:7b --yes
```

You end up with a file you double-click. That is the whole point of this step:
without it, the only way to start your assistant is to type commands in a
terminal, which for most people means it never gets started again.

### Step 5 — Check it is really working

```
/aki-agent:doctor
```

It reports in plain language what is missing and exactly what to type. It never
shows you a stack trace.

---

## Part 2 — Reaching you on your phone (optional)

Your assistant can message you on Telegram. It takes about five minutes and
costs nothing. Skip it if you would rather it stayed on the computer.

1. **Install Telegram** on your phone, if you have not.
2. Open Telegram and search for **@BotFather** — the one with the blue tick.
3. Send it `/newbot`, and answer its two questions: a name (anything) and a
   username (must end in `bot`).
4. BotFather replies with a **token** — a long line of letters and numbers.
   **That token is the password to your bot.** Anyone holding it can send
   messages as it. Do not paste it into a chat, a document, or a screenshot.
5. Back in Claude Code:

   ```
   /aki-agent:connect-telegram
   ```

   It asks for the token, saves it into your operating system's password
   manager, and walks you through the rest — including sending your bot a
   first message, which is the step everybody forgets and the reason a
   correctly configured bot sometimes says nothing.

> **On Path B, one honest warning.** Replying on Telegram is not just wiring —
> the model has to *decide* to use the sending tool. Small local models are
> unreliable at exactly that. The setup is the same on both paths; the
> behaviour may not be.

---

## What it actually does

**Remembers.** Three kinds of memory, deliberately kept apart: what it is in
the middle of, things that stay true about you, and a day-by-day record. They
are overwritten at completely different rates, and merging them lets the
shortest-lived one set the rules for all three.

**Works while you are not there.** Scheduled tasks that run as you — at a set
time, every so often, or when something happens: a folder changes, you log in,
something you describe. **Seven ship switched on**, and three more ship
switched off, as examples to read and enable when you want them. You can write
your own from the dashboard.

**Reaches you.** Telegram, with a notification gate and quiet hours. Anything
held while you are quiet is delivered afterwards as one summary rather than
dropped. (Today, that delivery happens at 08:05 the next morning, or when you
press the button — not the moment your quiet hours end.)

**Shows you what it is thinking.** A dashboard on your own machine: your work,
what it is holding, what it has learned from you, and a health check. It binds
to your own computer only. Reaching it from another device is possible and is
**off unless you deliberately turn it on**, for one named address, and it
refuses while your PIN is still the default.

**Reads your mail, files and calendar** over IMAP, your existing sync folders,
and calendar subscription links. No API key, no developer account.
Mail is **headers only** — who wrote, what about, when. No message body is
ever fetched. Sending is off unless you turn it on for that mailbox, and every
individual message still asks first.

**Learns your taste.** When you accept, edit or reject what it produces, it
notes the correction and reads it back next time. Entirely on your computer.

**Uses outside services, but only the ones you choose.** An API-keys page for
pictures, voices, transcription, video and web search. Paste a key, then tick
what it may be used for — a key on its own is not permission. Keys go into
your operating system's password manager, never into a file here, and are
never shown back to you. All optional; everything above works with no key.

---

## Your assistant lives in one folder

```
Aki-Agent/
    CLAUDE.md            what it reads at the start of every session
    .claude/skills/      skills written for you
    01_Config/           settings, memory, logs, your launcher
    02_Sandbox/          its desk — it writes here freely
    03_Workspace/
        01_Work/
            01_Project-1/    yours — never changed without your say-so
        02_Personal/...
```

Back up that folder and you have backed up the assistant.

| What | Where |
|---|---|
| Your configuration | `01_Config/config.yaml`. `~/.aki-agent/` holds a pointer to it |
| Your passwords and keys | Windows Credential Manager / macOS Keychain — never in a file here |
| Its private Python environment | `~/.aki-agent/venv` |
| Your actual work | Wherever you told it. This package never moves your files |

Everything installs into your own user account. Nothing here ever asks for an
administrator password.

---

## Updating

One line:

```
/plugin marketplace update aki-agent
```

Nothing in your folder is touched — an update replaces the engine, never your
configuration or your work.

If you installed from a zip, it is the same two steps as before with the
newer one, and then delete the download. `aki upgrade` will not install a zip
whose signature it cannot verify; pass `--allow-unsigned` only for a build
you made yourself.

Then run **one** more command, and it is worth understanding why:

```
/aki-agent:doctor
```

Each version installs into its own folder, and your scheduled tasks hold the
full path to the previous one. After an update they point at a folder that is
about to disappear — and if nothing corrects them they simply stop running one
day, with no error, which is the worst way for software to fail. `doctor`
notices and tells you to run `repair`, which re-points them.

## Coming from a zip install

Aki Agent was handed out as a zip before it was a repository. If that is how
you got it, moving onto the GitHub copy is a one-time job, and the two install
lines at the top are **not** it.

Three things are in the way, and none of them announce themselves:

- **The name is already taken.** Your Claude Code has a marketplace called
  `aki-agent` that points at the folder you unzipped. Adding the GitHub one
  under the same name is two things claiming one entry.
- **The plugin is only half of it.** Your actual engine was copied into your
  own assistant folder at setup — inside the workspace you chose, not in the
  plugin cache — and installing a plugin does not touch it. You would be
  running new skills against an old engine.
- **Your scheduled tasks hold a full path.** They point at that engine folder.
  Nothing re-points them on its own, and when it is replaced they stop firing —
  no error, no message, just an assistant that gradually does nothing.

So do this instead. In Claude Code:

```
/plugin marketplace remove aki-agent
/plugin marketplace add cowballwong/aki-agent
/plugin install aki-agent@aki-agent
```

Removing first is deliberate — it is the same order the upgrade itself uses,
because `marketplace update` would re-read the old folder and faithfully
reinstall the version you are trying to leave.

**Now restart Claude Code.** Skills are read at start-up; until you do, you
are still talking to the old ones, which looks exactly like nothing having
happened.

Then one command, which copies the new engine into your own folder and
re-points your launcher and every scheduled task at it:

**macOS / Linux**
```bash
python "$(ls -dt ~/.claude/plugins/cache/*/aki-agent/*/bin/_bootstrap.py | head -1)" aki_agent.cli adopt-engine --yes
```

**Windows (PowerShell)**
```powershell
$bootstrap = Get-ChildItem "$HOME\.claude\plugins\cache\*\aki-agent\*\bin\_bootstrap.py" |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
python $bootstrap.FullName aki_agent.cli adopt-engine --yes
```

Finally, check it:

```
/aki-agent:doctor
```

Look for **"Everything runs from your own folder"**. When that passes, the
folder you originally unzipped can be deleted.

Your configuration, your memory and your work sit beside that engine in your
own workspace, and in your project folders. None of this goes near them —
`adopt-engine` says as much before it does anything, and says it again in the
plan it prints if you run it without `--yes` first.

From then on, updating is the one line above — `/plugin marketplace update
aki-agent` — and you never download a zip again.

## When something goes wrong

`/aki-agent:doctor` first, always.

| It says | What it means |
|---|---|
| A scheduled task failed | Usually your Claude sign-in expired. Run `claude` once and sign in again |
| Nothing runs on its own | Scheduling may not be supported on your platform. The assistant still works; it just does nothing unattended |
| The dashboard will not open | Something else is on its port, or it stopped. `doctor` says which |

## Getting rid of it

```bash
python ~/.aki-agent/aki.py aki_agent.cli uninstall
```

It lists exactly what it will remove — scheduled tasks, the private
environment, the pointer file, copied skills, every credential it holds — and
asks before doing any of it. **Your own documents are never touched.**

Deleting the folder by hand is not enough. The scheduled tasks live in Windows
Task Scheduler or macOS launchd, not in the folder, and they carry on firing at
a runner that is no longer there.

---

## Already built your own assistant?

You do not have to start again. Three ways this can go — keep both side by
side, import your material into this one, or bring pieces of this out to
yours. What each costs and how hard each is to undo: **`CHOOSING.md`**, or ask
`/aki-agent:already-have-an-agent`.

To merge, tell your own assistant:

> *Read the Aki Agent package at `<path>` and integrate what is useful into my
> setup.*

It will find **`INTEGRATE.md`**, written for it rather than for you: what to
adopt, in what order, and a rule that it proposes every change and waits for
your approval before writing anything.

The highest-value part of that merge is usually not a feature. It is pulling
your own name, paths and drive letters out of your assistant's code and into a
configuration file — which is what turns something that works for you into
something that would work for anyone.

---

## For people reading the code

This package is teaching material as much as it is software; it gets opened in
class and taken apart. So it is written to be read:

- an obvious implementation beats a compact one, every time
- the comments explaining *why* are the point, not clutter
- every trap learned by something breaking is written down where it was learned

**The design decision everything rests on:** the engine does not know what job
you do. Every profession-specific word lives in your configuration, not in the
code. The same engine serves an architect and a music teacher with nothing
changed. `tests/test_two_configs.py` proves it, `tests/test_dashboard.py`
proves it again at the rendered page, and a canary in the first of those
parses every engine file's syntax tree — code and string literals, docstrings
excluded — and fails if a profession word ever reaches executable code.

Start with `src/aki_agent/schema.py` — the file the whole design turns on.

```
src/aki_agent/
    schema.py       the declarative item schema  <- read this first
    config.py       the single configuration object
    paths.py        where everything lives, on both platforms
    backend.py      which brain it is talking to, and how to start it again
    workspace.py    reading your folders off disk
    atomic.py       safe writes and one locking mechanism
    memory.py       the three memory tiers
    session.py      restart safely, and verify it actually happened
    notify.py       the notification gate
    channels.py     ways of reaching you, and how to add one
    runner.py       running the assistant without you sitting there
    traces.py       learning from your verdicts, entirely locally
    schedule.py     one definition, two operating systems
    skills_store.py skills you write yourself
    knowledge.py    the documents and links you point it at
    secrets.py      the OS password manager, and the redactor
    apis.py         optional outside services, and one job to one service
    exposure.py     letting another device reach the dashboard, deliberately
    doctor.py       the plain-language health check
    launcher.py     generating your own start-up file
    connectors/     mail (IMAP) · files (sync folders) · calendars (ICS)
    dashboard/      Flask app + templates
tests/              1,947 tests
```

Several files carry long comments about a bug found while writing them — a
lock that deadlocked only under threads, a redactor that ate its own log
messages, a slug that turned every Chinese name into the same empty string.
Those comments are the most useful thing in the codebase and should survive
any tidy-up.

### Running the tests

```bash
python -m pytest
```

**A warning worth more than the number.** Every test here was written by the
same person who wrote the code, so they only check what somebody had already
thought of. An outside audit on 2026-09-05 found a settings form that saved
nothing, seven confirmation dialogs that did not parse, and names in Chinese
overwriting each other — all while the suite was green, and two of the tests
covering them could not have failed. A passing suite is evidence of care, not
of correctness.

---

## Design limits, stated rather than half-solved

- **One trusted person per installation.** No multi-user isolation, and there
  will not be. If two people share a login, they share the assistant.
- **Your machine must be on.** No cloud component means nothing runs while the
  laptop is shut.
- **The dashboard is yours, not the internet's.** It binds locally. Letting
  another device reach it exists, is off by default, must be turned on for one
  named address, and refuses while the PIN is unchanged.
- **macOS is written but unobserved.** See the status table at the top.

## Contributing, and reporting a problem

**Pull requests are welcome.** One maintainer, working evenings, so a review
may take a while — but the door is open rather than decorative.

Read [CONTRIBUTING.md](CONTRIBUTING.md) first. Two conventions in there cannot
be guessed from the code: how to write the `WHY` notes now that more than one
person writes them, and the rule that a platform counts as tested only when
the change has run on a real machine of that kind.

Found a security hole? Not a public issue — [SECURITY.md](SECURITY.md).

## Naming

The product is **Aki Agent**. The package is `aki-agent`, the Python module is
`aki_agent`, your folder is `~/.aki-agent`.

Your *assistant's* name is a different thing and it is already yours — you
choose it during setup. Nothing here imposes one.

## Licence

MIT.
