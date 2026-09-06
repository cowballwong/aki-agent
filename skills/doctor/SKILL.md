---
name: doctor
description: Check that everything the assistant needs is installed and configured, and explain in plain language how to fix anything that is missing. Use when the user types /doctor, says something is broken, says the dashboard will not start, or when any other skill hits a missing dependency or missing configuration.
user-invocable: true
allowed-tools:
  - Read
  - Bash
---

# Doctor — what is wrong, and what to do about it

Run the health check and translate the result for the user.

```bash
python ~/.aki-agent/aki.py aki_agent.doctor
```

The launcher creates the private environment and installs what is missing the
first time it runs, so this also doubles as the repair command.

## How to report the result

**Lead with the verdict, not the list.** "Everything's working" or "one thing
needs fixing: Python is too old". Then the detail.

**Never paste a stack trace at the user.** If the check itself fails in an
unexpected way, say what you were doing and what happened in one sentence, and
offer to look at the specific file.

**Fix it with them, not for them, when a decision is involved.** Installing a
missing package is fine to just do. Changing where their workspace folder
lives is not — ask.

## Things that look broken and are not

- **A workspace folder on a cloud drive that has just started up.** Google
  Drive, OneDrive, iCloud and Dropbox mount their folders some time after
  login. Wait, retry, and only then treat it as missing.
- **`keyring` reporting no backend.** Unusual but harmless — secrets fall back
  to a file. Tell the user that has happened; do not treat it as fatal.
- **No configuration yet, right after install.** That is expected. Point them
  at `/aki-agent:setup`.

## The rule about staleness, which matters more than it sounds

If any check cannot determine an answer, it must say so — never assume the
last known answer is still true.

A panel that shows stale data confidently is worse than one that shows
nothing, because the user acts on it. This applies to your summary too: if you
could not check something, say you could not check it.
