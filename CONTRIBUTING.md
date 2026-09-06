# Contributing

Pull requests are welcome.

This file exists because a repository that stays silent about how it is
written teaches every newcomer to guess, and then the maintainer rewrites
their work and everybody is disappointed. Four things below are conventions
you cannot infer from reading the code, and one is a rule about what counts
as tested.

---

## Running it

```
python -m venv venv
venv/Scripts/pip install -e .        # Windows
.venv/bin/pip install -e .           # macOS
python -m pytest -q
```

The suite is the specification. It runs in about ninety seconds and is
expected to be green before and after your change — a red suite on `main` is
treated as an incident, not as a backlog item.

Tests write only to a temporary home. If a run leaves anything in your real
`~/.aki-agent`, that is a bug in the test rather than an inconvenience: a
session guard fails the whole run when the real state folder is touched, and
it is there because test fixtures once landed in the author's live install.

---

## The `WHY` notes, and how to write one now

Throughout the code you will find blocks like:

```python
# WHY (reported 2026-08-19)
# -----------------------
# ...
```

They record the decision behind a piece of code: what was asked for, when,
and what it was trading against. They are the most valuable thing in the
repository and they are not decoration — several of them are the only record
of why an obvious-looking simplification is wrong.

**They name a person because, until this repository was opened, there was
only one.** That does not generalise, so the convention from 2026-09-05 is:

- **Existing notes stay exactly as they are.** They are a historical record,
  and rewriting a record to look tidier is how records stop being trusted.
- **New notes carry the date and the reason, and no name.**

  ```python
  # WHY (2026-09-06)
  # ----------------
  # Reading the file twice looked wasteful and was not: the first read is
  # what proves the lock was ours.
  ```

- If a decision genuinely turns on *who* wanted it — a maintainer's call
  against the obvious reading — say the role, not the person: "the
  maintainer's call, 2026-09-06".

Write the note where somebody would edit the line, not only in the module
docstring. A reassurance nobody scrolls to is a reassurance nobody reads.

And if your note cites a test, cite it by its exact name. There is a test
that checks one such citation still resolves, because the first one written
named a function that had been renamed.

---

## Both platforms, every time

This package runs on Windows and macOS, and every change ships both halves.
That is a standing rule, not a nice-to-have: scheduling, launchers, terminal
windows and credential storage are each written twice, and a change to one
half that forgets the other is the most common defect this project has had.

**A platform is only "done" when the change has run on a real machine of that
kind.** Not a fake `sys.platform`, not a mocked path — those catch typos and
nothing else. `tests/test_dual_platform.py` forces both halves to exist; it
cannot tell you either one works.

So in your pull request, say plainly which half you actually ran. "Windows
verified, macOS written and reviewed but not executed" is a completely
acceptable thing to write, and it is what the maintainer's own changes say.
An unqualified "works" that turns out to mean "the tests passed" is not.

---

## What gets refused

- **Anything that widens the safety gate.** `safety_gate.py` is short on
  purpose. A longer denylist blocks ordinary work, and a gate that blocks
  ordinary work gets switched off — after which nothing is checked at all.
  The reasoning is in the module docstring; read it before proposing a rule.
- **A profession word in executable code.** The engine must not know what job
  the user does; every domain word lives in configuration. A canary in
  `tests/test_two_configs.py` walks the syntax tree and fails the build.
- **A button that reports success it did not achieve.** The failure this
  codebase is most prone to is not crashing — it is a control that looks like
  it worked and did nothing. If your change adds a switch, add the test that
  proves the switch moved something.

---

## Reporting a security problem

Not here. See [SECURITY.md](SECURITY.md).
