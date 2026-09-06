"""Letting the dashboard be reached from outside, deliberately and visibly.

WHY THIS MODULE IS NOT JUST A BOOLEAN
-------------------------------------
reported 2026-08-28: users should be able to reach their dashboard from away
from the desk, through a tunnel, by pasting a key.

The dashboard already refuses that, on purpose. `guard_mutations` rejects any
request carrying a forwarding header or addressed to a host that is not this
machine — **for reads as well as writes** — and the comment beside it records
why: on the reference system exactly that arrangement left a control surface,
house lights included, reachable from outside with no password at all, and it
was found afterwards.

So this is not a switch that removes a guard. It is a narrow, named exception
to it, and the shape of the exception is the whole security argument:

  * **OFF until somebody turns it on.** Nothing changes for anyone who does not
    ask for this.
  * **REFUSED while the PIN is still the shipped one.** The throttle makes
    guessing expensive; it cannot help if the answer is 000000.
  * **ONE HOSTNAME, DECLARED BY THE USER.** This is the part that matters. The
    obvious implementation trusts `X-Forwarded-For` and lets anything through a
    proxy in — which is precisely the hole that was found, because those headers
    are set by the client. Instead the user says what their tunnel is called,
    and only that exact name is answered.

    That also keeps the DNS-rebinding path shut. The attack is a page the user
    is merely visiting re-resolving its own domain to 127.0.0.1 and then
    reading this dashboard same-origin. It arrives with the attacker's hostname
    in `Host`, which is not the declared one, so it is still refused.
  * **SAID ON EVERY PAGE.** A door that is open and does not look open is the
    state this whole module exists to avoid.

WHAT IT STILL DOES NOT GIVE YOU
-------------------------------
Everything the assistant knows is behind one six-digit PIN and a throttle. That
is a door, not a safe. Anybody publishing this should pick a PIN nobody would
guess, and prefer a tunnel that can do authentication of its own.

The transport is not checked here either. A tunnel's own `X-Forwarded-Proto`
can be set by the client, so enforcing HTTPS from inside would be theatre. The
guide says use an HTTPS tunnel; this module does not pretend to verify it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import atomic, dashboard_auth, paths

STATE_FILE = "remote-access.json"

# A hostname, not a URL and not a pattern. Anything looser would be a rule
# somebody could satisfy accidentally.
HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")

# Refused as a declared host: these are what the guard already allows, so
# naming one here would be a way of turning the exception into a no-op that
# looks like protection.
NEVER = {"localhost", "127.0.0.1", "::1", ""}


@dataclass(frozen=True)
class State:
    on: bool = False
    host: str = ""

    def describe(self) -> str:
        if not self.on:
            return "Remote access is off. The dashboard answers only on this computer."
        return (f"Remote access is ON for {self.host}. Anyone who reaches that "
                "address needs your PIN, and nothing else.")


def _path() -> Path:
    return paths.app_dir() / STATE_FILE


def state() -> State:
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
        return State(on=bool(raw.get("on")), host=str(raw.get("host") or ""))
    except Exception:                                      # noqa: BLE001
        # Unreadable means off. A security switch whose broken state is "open"
        # is a switch that fails in the wrong direction.
        return State()


def _save(value: State) -> None:
    atomic.write_text(_path(), json.dumps({"on": value.on, "host": value.host},
                                          sort_keys=True))


def why_not(host: str) -> str:
    """Why this hostname cannot be used. Empty string means it can."""
    host = (host or "").strip().lower()
    if not host:
        return "Give the address your tunnel gives you, for example a1b2.ngrok-free.app."
    if "://" in host or "/" in host:
        return "Just the address — no https:// and no path."
    if ":" in host:
        return "Just the address — no port."
    if host in NEVER:
        return ("That is this computer's own name, which already works. Give "
                "the address your tunnel hands out.")
    if not HOSTNAME.match(host):
        return "That does not look like an address a tunnel would give you."
    return ""


def turn_on(host: str) -> tuple[bool, str]:
    """Open it for one hostname. Returns (done, what to tell the user)."""
    problem = why_not(host)
    if problem:
        return False, problem
    if dashboard_auth.is_default():
        # The throttle makes guessing expensive. It cannot help if the answer
        # is the number printed in the instructions.
        return False, ("Choose your own PIN first. The shipped one is public, "
                       "and this would put it on the internet.")
    _save(State(on=True, host=host.strip().lower()))
    return True, (f"Remote access is on for {host.strip().lower()}. "
                  "Every page will say so while it is.")


def turn_off() -> tuple[bool, str]:
    _save(State())
    return True, "Remote access is off. The dashboard answers only on this computer."


def allows(host: str) -> bool:
    """Is this the one hostname the user declared?

    Called by the dashboard's guard. Compared exactly, lower-cased, with any
    port stripped — no wildcards, no suffix matching. `evil-ngrok-free.app`
    must not be let in by a rule written for `ngrok-free.app`.
    """
    current = state()
    if not current.on or not current.host:
        return False
    host = (host or "").split(":")[0].strip().lower()
    return bool(host) and host == current.host
