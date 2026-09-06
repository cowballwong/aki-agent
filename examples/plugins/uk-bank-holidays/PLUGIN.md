---
name: uk-bank-holidays
version: 1.0.0
description: Every England & Wales bank holiday, computed for any year
provides: [calendar]
entry: plugin.py
---

# UK bank holidays

A calendar that needs no account, no address and no network, and is right
about the awkward years.

The movable feasts are computed rather than listed: Easter from the anonymous
Gregorian algorithm, the May and August holidays as the first or last Monday
of their month, and Christmas and Boxing Day rolled forward when they land on
a weekend — including the case where Christmas takes the Monday and Boxing Day
has to take the Tuesday.

Useful on its own for anyone counting working days into a programme. Useful as
a first plugin to read because it works the moment it is installed, so it
proves the plumbing on a machine where nothing else is connected yet.

## Installing

    aki plugin add examples/plugins/uk-bank-holidays --yes
    aki agenda
