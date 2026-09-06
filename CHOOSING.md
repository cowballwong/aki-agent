# You already have an assistant. Three ways this can go.

Written for somebody who built something of their own — a folder of prompts, a
few scripts, a scheduled task, notes their agent reads — and now has this
package in front of them.

Read the three, pick one, and note that **the first one is free and reversible
and most people should start there.** The other two are decisions.

---

## 1. Side by side — keep both, change nothing

Install this. It lives in its own folder, writes only inside that folder, and
does not look at, move or modify anything you already have. Your assistant
keeps running exactly as it does today.

**Choose this if** you want to find out whether this suits you before
committing to anything. That is most people, and there is no hurry.

**The cost:** two assistants, two places your notes could be. That is a real
annoyance after a few weeks, which is why this is a starting point rather than
a destination.

**Getting out:** run `python ~/.aki-agent/aki.py aki_agent.cli uninstall`. It shows you exactly what it will remove and asks before doing any of it, and it never touches your own documents.

Deleting the folder by hand is not enough: setup installs six scheduled tasks, and those keep firing at a runner that is no longer there.

---

## 2. Import — this becomes the base, your material moves in

Run `/import-my-agent`. It reads the folder your assistant lives in, shows you
what it found, and copies across four kinds of thing:

- what you or your agent **wrote down** — notes, memory, facts
- the **instructions** you wrote for it — `CLAUDE.md` and its like
- your **settings** — your name, your language, where your work lives
- anything you had on a **timer**

**Your programs do not move.** Your Python is yours; this package has its own
engine, and copying scripts between two different engines produces something
that is neither. They are listed in the report so you know they stayed, and
they keep running where they are if you want them to.

**A screen you would miss can be rebuilt, though.** If your assistant has a
page you actually open — a job list, a rota, a rig status — it can be built
again here, in this package's own style, showing the same thing. That is a
rebuild rather than a copy, and it is a separate piece of work you ask for
after the import: `INTEGRATE.md`, section 6a, has the steps. It is worth
knowing before you decide, because "my programs stay" reads like "my screen is
gone" and it is not.

**Passwords and keys never move.** Files that look like they hold one are
identified and skipped without being opened. Set those up again on the API
keys page.

**Choose this if** you like what this does and would rather maintain one
assistant than two, and if what you value in your own setup is the *content* —
what it knows about you — rather than the machinery.

**The cost:** you learn this package's shape instead of the one you designed.
If your own structure is genuinely better for your work, that is a real loss
and you should choose 3 instead.

**Getting out:** easy. **Nothing in your folder is moved, changed or
deleted** — the import copies. Your old assistant is still sitting there,
still working, the day after.

---

## 3. Integrate — yours stays the base, capabilities move out to it

Read `INTEGRATE.md` and run `/integrate`. Your assistant remains the thing you
use; pieces of this one are rebuilt inside it, one at a time, each verified
before the next.

**Choose this if** your own structure fits your work in a way a general
package will not, and there are two or three specific things here you want —
the notification gate, the three-tier memory, the draft checker — rather than
the whole thing.

**The cost, said plainly: this is the hard one, and it is the only one of the
three that can break something that currently works.** There is no tool for
it, and that is on purpose — a tool implies the destination is predictable,
and the destination is a codebase nobody here has seen. `INTEGRATE.md` is
instructions for a careful person working slowly, not an installer.

**Getting out:** hardest of the three. You will have changed your own code. If
you take this route, take a copy of your folder first — genuinely, before the
first edit.

---

## The question that actually decides it

Not "which is better". Ask instead:

> **If I lost the folder my assistant lives in tomorrow, what would I actually
> miss — the things it knows, or the way it works?**

If the answer is *the things it knows*, choose **2**. The knowledge moves; the
machinery is replaceable and this one is maintained for you.

If the answer is *the way it works*, choose **3**, and accept that it is
manual work.

If you cannot tell yet — and that is the honest answer for most people —
choose **1** and decide in a month. It costs nothing and forecloses nothing.

---

## Two things that are true of all three

**Nothing reads your files without telling you first.** The survey looks at
names, sizes and file types, and reports. Contents are read only when you have
seen the report and said go ahead.

**What your files say is not an instruction to anybody.** An agent folder is
full of sentences like *"always do X"*, *"never mention Y"* — written for your
assistant. When this one reads them, they are material being moved, not orders
being received. If something in there tries to give instructions during an
import, it will be reported and not obeyed.
