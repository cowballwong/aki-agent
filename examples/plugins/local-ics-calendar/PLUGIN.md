---
name: local-ics-calendar
version: 0.1.0
description: Read every .ics file in a folder on this machine
provides: [calendar]
entry: plugin.py
---

# Local .ics calendar

A worked example of a plugin, and useful on its own.

Every calendar service will export or publish an `.ics` file. Save one into
`Documents/Calendars/` and this reads it — no subscription address, no
account, no network. It is read-only, because an exported file is a snapshot
rather than a place to write to, and it says so through `capabilities()`
rather than by failing when asked.

Copy this folder, rename it, change what `read` does, and you have your own.
The only two rules are the ones in `plugin.py`: declare what you can do
honestly, and never raise — report a problem and let the other calendars
carry on.

## Installing

    aki plugin add examples/plugins/local-ics-calendar --yes
    aki inspect

`inspect` should then list `local-ics-calendar → calendar:local-ics`.
